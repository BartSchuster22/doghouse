"""Root Unix-socket broker: fixed cell, pinned images, bounded argv, no shell recipes."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import struct
import subprocess
import time
from .engine import Engine, Rejected, SERVICES, RECOVERABLE
from .health_contracts import CheckObservation, HealthContract, evaluate_health_contract

MAX_REQUEST=4096

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

from .identity import legacy_signature as signature, canonical_signature, SCHEMA as IDENTITY_SCHEMA

def trusted(path):
    p=Path(path)
    for item in [p,*p.parents]:
        st=item.lstat()
        if item.is_symlink() or st.st_uid!=0 or st.st_mode & 0o022:raise Rejected('unsafe-owned-path')
    return p

@contextmanager
def lock(path):
    fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally:os.close(fd)

def atomic(path,value):
    path=Path(path);tmp=path.with_suffix('.new')
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
    try:
        with os.fdopen(fd,'w') as f:
            json.dump(value,f,separators=(',',':'));f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
        d=os.open(path.parent,os.O_DIRECTORY);os.fsync(d);os.close(d)
    finally:
        if tmp.exists():tmp.unlink()

class Broker:
    def __init__(self,config):
        self.config_path=trusted(config);self.c=json.loads(self.config_path.read_text())
        self.root=trusted(self.c['root']);self.cell=self.c['cell']
        if not re.fullmatch(r'dsh2-stage[0-9]+-qa[0-9]+',self.cell):raise Rejected('invalid-cell')
        if set(self.c['images'])!=set(SERVICES):raise Rejected('invalid-pins')
        if self.c.get('signatureSchema') not in (None,IDENTITY_SCHEMA):raise Rejected('unsupported-signature-schema')
        self.op=self.root/'operations'
        self.e=Engine(self.op/'ops.db')
        # A previous atomic write interrupted before rename cannot replace status.
        stale=self.op/'public/status.new'
        if stale.exists():trusted(stale).unlink()
        self.rows={}

    def run(self,args,timeout=15):
        # These arguments originate only from source constants or fixed config,
        # never from caller-provided command/path/container ID.
        p=subprocess.run(['/usr/bin/docker','--host','unix:///var/run/docker.sock',*args],capture_output=True,text=True,timeout=timeout,env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','HOME':'/nonexistent','DOCKER_CONFIG':'/nonexistent'})
        if p.returncode:raise Rejected('docker-command-failed')
        if len(p.stdout)>2*1024*1024:raise Rejected('oversize-docker-response')
        return p.stdout

    def verify_identity(self,rows):
        if digest(trusted(self.root/'owner.json'))!=self.c['ownerSha256']:raise Rejected('owner-changed')
        if len(rows)!=len(SERVICES):raise Rejected('service-set-mismatch')
        for service,row in zip(SERVICES,rows):
            labels=row['Config']['Labels']
            if row['Name']!='/'+self.cell+'-'+service+'-1' or row['Image']!=self.c['images'][service]:raise Rejected('image-or-name-mismatch')
            if labels.get('com.docker.compose.project')!=self.cell or labels.get('com.alica.stage2')!=self.cell:raise Rejected('label-mismatch')
            fingerprint=canonical_signature if self.c.get('signatureSchema')==IDENTITY_SCHEMA else signature
            if fingerprint(row)!=self.c['signatures'][service]:raise Rejected('runtime-config-mismatch')
            expected=self.c['mounts'][service]
            actual=sorted([(m['Type'],m['Source'],m['Destination'],m['RW']) for m in row['Mounts']])
            if [list(x) for x in actual]!=expected:raise Rejected('mount-mismatch')

    def collect(self):
        now=time.time();ownership=False;available=False;self.rows={}
        states={s:{'state':'unknown','running':False,'reason':'observation-unavailable'} for s in SERVICES}
        try:
            rows=json.loads(self.run(['inspect',*[self.cell+'-'+s+'-1' for s in SERVICES]]))
            available=True;self.verify_identity(rows);ownership=True
            for service,row in zip(SERVICES,rows):
                running=row['State']['Running'];raw=row['State'].get('Health',{}).get('Status')
                status='healthy' if running and raw=='healthy' else ('failed' if not running or raw=='unhealthy' else 'unknown')
                observation=CheckObservation(200,{'status':status})
                normalized=evaluate_health_contract(HealthContract(service,('health',)),{'health':observation})
                states[service]={'state':status,'running':running,'reason':normalized.classification,
                                 'exitCode':row['State']['ExitCode'],'restartCount':row['RestartCount']}
                self.rows[service]=row
        except (OSError,ValueError,Rejected,subprocess.TimeoutExpired):pass
        work={'active':None,'counts':{},'source':'native-kanban-readonly','observed':False}
        if ownership:
            try:
                data=next(m['Source'] for m in self.rows['hermes']['Mounts'] if m['Destination']=='/opt/data')
                path=Path(data)/'kanban.db'
                if path.is_symlink() or not path.resolve().is_relative_to(Path(data).resolve()):raise OSError('unsafe-native-db')
                from .native_observation import read_counts
                counts=read_counts(self.run,self.cell)
                work.update(counts=counts,active=sum(v for k,v in counts.items() if k not in ('done','archived')),observed=True)
            except (OSError,sqlite3.Error,StopIteration,ValueError,Rejected,subprocess.TimeoutExpired):pass
        mem={x.split(':')[0]:int(x.split()[1])*1024 for x in Path('/proc/meminfo').read_text().splitlines()}
        free=shutil.disk_usage(trusted(self.c['storagePath'])).free
        snap={'observedAt':now,'bootId':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
              'cell':self.cell,'dockerAvailable':available,'ownershipVerified':ownership,'services':states,
              'storagePressure':free<self.c['minimumFreeBytes'],'storageAvailableBytes':free,
              'memoryAvailableBytes':mem['MemAvailable'],'nativeWork':work}
        self.e.observe(snap)
        return snap

    def publish(self):
        value=self.e.public()
        atomic(self.op/'public/status.json',value)
        return value

    def request(self,body,uid):
        if not isinstance(body,dict) or type(body.get('version')) is not int or body.get('version')!=1 or set(body)-{'version','op','service','enabled'}:raise Rejected('invalid-request')
        if uid not in (0,self.c['observerUid']):raise Rejected('peer-denied')
        operation=body.get('op')
        if operation not in ('snapshot','recover','maintenance','ack'):raise Rejected('operation-denied')
        if operation in ('maintenance','ack') and uid!=0:raise Rejected('operator-required')
        with lock(self.op/'operation.lock'):
            if operation=='maintenance':self.e.maintenance(body.get('enabled'))
            elif operation=='ack':self.e.acknowledge(body.get('service'))
            elif operation=='recover':
                service=body.get('service')
                if service not in RECOVERABLE:raise Rejected('target-denied')
                # The same owner/installation lock as the native alicactl protocol.
                with lock(self.root.parent/('.'+self.root.name+'.install.lock')):
                    self.collect();action=self.e.reserve(service)
                    try:
                        self.run(['restart','--time','30',self.cell+'-'+service+'-1'],timeout=45)
                    except subprocess.TimeoutExpired:
                        self.e.finish(action,'uncertain')
                    except (OSError,Rejected):self.e.finish(action,'command-failed')
                    else:self.e.finish(action,'command-returned')
            else:self.collect()
            return self.publish()

    def serve(self):
        p=Path(self.c['socket']);trusted(p.parent)
        if p.exists():
            if not p.is_socket():raise Rejected('unsafe-socket')
            p.unlink()
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as server:
            server.bind(str(p));os.chown(p,0,self.c['observerGid']);os.chmod(p,0o660);server.listen(8)
            while True:
                conn,_=server.accept()
                with conn:
                    conn.settimeout(5)
                    uid=struct.unpack('3i',conn.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]
                    try:
                        raw=b''
                        while b'\n' not in raw and len(raw)<=MAX_REQUEST:
                            part=conn.recv(MAX_REQUEST+1-len(raw))
                            if not part:break
                            raw+=part
                        if len(raw)>MAX_REQUEST or not raw.endswith(b'\n'):raise Rejected('invalid-frame')
                        result=self.request(json.loads(raw),uid);response={'ok':True,'status':result}
                    except (Rejected,BlockingIOError,ValueError,OSError,sqlite3.Error) as exc:
                        # No upstream error, request value, work body, environment,
                        # credential or raw Docker log is ever reflected.
                        reason=str(exc) if isinstance(exc,Rejected) else type(exc).__name__
                        try:self.e.log('request-denied','broker',reason);self.e.db.commit()
                        except sqlite3.Error:pass
                        response={'ok':False,'error':reason}
                    try:conn.sendall(json.dumps(response,separators=(',',':')).encode()+b'\n')
                    except OSError:pass

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);a=p.parse_args()
    Broker(a.config).serve()
