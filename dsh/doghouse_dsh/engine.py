"""Persistent, deterministic incident/recovery policy. External effects belong to broker."""
import json
import sqlite3
import time
import uuid

SERVICES = ('postgresql','keycloak','hermes','memory-v4','unify-core','uniui','caddy')
RECOVERABLE = ('hermes','memory-v4','unify-core')
DEPENDENCIES = {'postgresql': (), 'keycloak': ('postgresql',), 'hermes': ('postgresql',),
                'memory-v4': ('postgresql',), 'unify-core': ('postgresql','keycloak','hermes','memory-v4'),
                'uniui': ('unify-core',), 'caddy': ('uniui','unify-core','keycloak')}

class Rejected(Exception):
    pass

class Engine:
    def __init__(self, path, clock=time.time):
        self.clock = clock
        self.db = sqlite3.connect(path, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY,service TEXT NOT NULL,
          reason TEXT NOT NULL,state TEXT NOT NULL,first_seen REAL NOT NULL,last_seen REAL NOT NULL,
          observations INTEGER NOT NULL,UNIQUE(service,reason,state));
        CREATE TABLE IF NOT EXISTS actions(id TEXT PRIMARY KEY,service TEXT NOT NULL,
          state TEXT NOT NULL,created REAL NOT NULL,finished REAL,outcome TEXT);
        CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY AUTOINCREMENT,at REAL NOT NULL,
          action TEXT NOT NULL,service TEXT NOT NULL,outcome TEXT NOT NULL);
        ''')
        self.snapshot = None
        self.db.execute("UPDATE actions SET state='uncertain',outcome='broker-interrupted' WHERE state='issued'")
        self.db.commit()

    def meta(self, key, default=None):
        row=self.db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_meta(self,key,value):
        self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(key,json.dumps(value)))

    def log(self,action,service,outcome):
        self.db.execute('INSERT INTO audit(at,action,service,outcome) VALUES(?,?,?,?)',
                        (self.clock(),action,service,outcome))

    def incident(self,service,reason):
        now=self.clock()
        row=self.db.execute("SELECT id FROM incidents WHERE service=? AND reason=? AND state='open'",(service,reason)).fetchone()
        if row:
            self.db.execute('UPDATE incidents SET last_seen=?,observations=observations+1 WHERE id=?',(now,row[0]))
        else:
            self.db.execute('INSERT INTO incidents VALUES(?,?,?,?,?,?,?)',(str(uuid.uuid4()),service,reason,'open',now,now,1))
            self.log('incident-open',service,reason)

    def resolve(self,service,reason):
        # A resolved historical incident must not collide with a later occurrence.
        rows=self.db.execute("SELECT id FROM incidents WHERE service=? AND reason=? AND state='open'",(service,reason)).fetchall()
        for row in rows:
            self.db.execute("UPDATE incidents SET state=? WHERE id=?",('resolved:'+row[0],row[0]))
            self.log('incident-resolved',service,reason)

    def observe(self,snapshot):
        self.snapshot=snapshot
        old=self.meta('bootId')
        if old and old!=snapshot['bootId']:
            self.log('host-boot','host','changed; owner stores require reconciliation')
        self.set_meta('bootId',snapshot['bootId'])
        for service,health in snapshot['services'].items():
            if health['state']=='healthy': self.resolve(service,'not-ready')
            else: self.incident(service,'not-ready')
        for scope,problem in [('docker',not snapshot['dockerAvailable']),('storage',snapshot['storagePressure'])]:
            if problem:self.incident(scope,'unavailable')
            else:self.resolve(scope,'unavailable')
        self.db.commit()

    def maintenance(self,enabled):
        if not isinstance(enabled,bool):raise Rejected('invalid-maintenance')
        self.set_meta('maintenance',enabled);self.log('maintenance','cell','enabled' if enabled else 'disabled');self.db.commit()

    def decision(self,service):
        if service not in RECOVERABLE:return 'manual-only-service'
        s=self.snapshot
        if not s or self.clock()-s['observedAt']>20 or self.clock()<s['observedAt']:return 'stale-observation'
        if self.meta('maintenance',False):return 'maintenance'
        if not s['dockerAvailable']:return 'docker-unavailable'
        if s['storagePressure']:return 'storage-pressure'
        if not s['ownershipVerified']:return 'ownership-unverified'
        health=s['services'][service]
        if health['state']=='healthy':return 'already-healthy'
        if health['state']=='unknown':return 'unknown-state'
        if any(s['services'][d]['state']!='healthy' for d in DEPENDENCIES[service]):return 'dependency-unhealthy'
        # Running native work is never killed by a health-only decision. A stopped
        # executor can be brought back; business replay remains its native owner's job.
        if service=='hermes' and health['running'] and s['nativeWork'].get('active')!=0:return 'active-or-unknown-native-work'
        row=self.db.execute("SELECT observations FROM incidents WHERE service=? AND reason='not-ready' AND state='open'",(service,)).fetchone()
        if not row or row[0]<3:return 'debouncing'
        now=self.clock();ack=self.meta('ack:'+service,0)
        actions=self.db.execute('SELECT * FROM actions WHERE service=? AND created>? ORDER BY created DESC',(service,ack)).fetchall()
        if any(a['state'] in ('issued','uncertain') for a in actions):return 'uncertain-prior-effect'
        recent=[a for a in actions if a['created']>now-600]
        if len(recent)>=3:return 'circuit-open'
        if recent and now-recent[0]['created']<min(120,30*(2**(len(recent)-1))):return 'backoff'
        return 'eligible'

    def reserve(self,service):
        why=self.decision(service)
        if why!='eligible':raise Rejected(why)
        action=str(uuid.uuid4())
        self.db.execute('INSERT INTO actions VALUES(?,?,?,?,?,?)',(action,service,'issued',self.clock(),None,None))
        self.log('recovery-issued',service,'health-not-yet-verified');self.db.commit()
        return action

    def finish(self,action,outcome):
        if outcome not in ('command-returned','command-failed','uncertain'):raise Rejected('invalid-outcome')
        row=self.db.execute("SELECT service FROM actions WHERE id=? AND state='issued'",(action,)).fetchone()
        if not row:raise Rejected('action-not-issued')
        self.db.execute('UPDATE actions SET state=?,finished=?,outcome=? WHERE id=?',
                        ('uncertain' if outcome=='uncertain' else 'finished',self.clock(),outcome,action))
        self.log('recovery-command',row[0],outcome+'; observe readiness separately');self.db.commit()

    def acknowledge(self,service):
        if service not in RECOVERABLE:raise Rejected('manual-only-service')
        self.set_meta('ack:'+service,self.clock());self.log('operator-ack',service,'explicit-reset');self.db.commit()

    def public(self):
        return {'schema':'alica-operations/v1','owner':'doghouse-dsh','observedAt':self.snapshot['observedAt'] if self.snapshot else None,
                'snapshot':self.snapshot,'maintenance':self.meta('maintenance',False),
                'decisions':{s:self.decision(s) for s in RECOVERABLE},
                'incidents':[dict(r) for r in self.db.execute('SELECT * FROM incidents ORDER BY last_seen DESC LIMIT 100')],
                'audit':[dict(r) for r in self.db.execute('SELECT * FROM audit ORDER BY seq DESC LIMIT 100')],
                'usageProvenance':{'host':'Linux procfs/statvfs','work':'native Kanban read-only counts',
                                   'modelTokens':None,'modelCost':None,'billing':'not inferred from host metrics'},
                'rawApplicationLogs':'not exposed; operational audit contains fixed reason codes only',
                'limits':{'automaticTargets':list(RECOVERABLE),'maxAttempts':3,'windowSeconds':600,'backoffSeconds':[30,60,120],
                          'hostOrDaemonRestart':'never authorized by broker','externalEffects':'native owners only; no blind replay'}}
