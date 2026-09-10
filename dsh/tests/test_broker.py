import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from doghouse_dsh.broker import Broker,signature
from doghouse_dsh.engine import Rejected,SERVICES,Engine

class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name);self.cell='dsh2-stage5-qa1'
        self.b=Broker.__new__(Broker);self.b.root=self.p;self.b.op=self.p;self.b.cell=self.cell;self.b.e=Engine(self.p/'ops.db')
        (self.p/'owner.json').write_text('{}')
        import hashlib
        self.rows=[{'Name':'/'+self.cell+'-'+s+'-1','Image':'sha256:'+str(i)*64,
          'Config':{'Labels':{'com.docker.compose.project':self.cell,'com.alica.stage2':self.cell},'Env':['TOKEN=secret-sentinel'],'Cmd':['fixed']},
          'HostConfig':{'RestartPolicy':{'Name':'no'}},'Mounts':[],
          'State':{'Running':True,'Health':{'Status':'healthy'},'ExitCode':0},'RestartCount':0} for i,s in enumerate(SERVICES)]
        self.b.c={'observerUid':55555,'ownerSha256':hashlib.sha256(b'{}').hexdigest(),
          'images':{s:r['Image'] for s,r in zip(SERVICES,self.rows)},'mounts':{s:[] for s in SERVICES},
          'signatures':{s:signature(r) for s,r in zip(SERVICES,self.rows)},'storagePath':str(self.p),'minimumFreeBytes':1}
    def tearDown(self):self.b.e.db.close();self.tmp.cleanup()
    def verify(self):
        with patch('doghouse_dsh.broker.trusted',side_effect=Path):self.b.verify_identity(self.rows)
    def test_exact_owner_set(self):self.verify()
    def test_foreign_cell_denied(self):
        self.rows[0]['Config']['Labels']['com.alica.stage2']='other'
        with self.assertRaises(Rejected):self.verify()
    def test_image_change_denied(self):
        self.rows[0]['Image']='sha256:'+'f'*64
        with self.assertRaises(Rejected):self.verify()
    def test_changed_command_or_restart_policy_denied(self):
        self.rows[0]['Config']['Cmd']=['unreviewed']
        with self.assertRaises(Rejected):self.verify()
    def test_added_host_mount_denied(self):
        self.rows[0]['Mounts']=[{'Type':'bind','Source':'/','Destination':'/host','RW':True}]
        with self.assertRaises(Rejected):self.verify()
    def test_peer_uid_denied_before_any_effect(self):
        with self.assertRaisesRegex(Rejected,'peer-denied'):self.b.request({'version':1,'op':'recover','service':'hermes'},55556)
    def test_observer_cannot_ack_or_change_maintenance(self):
        for op in ('ack','maintenance'):
            with self.assertRaisesRegex(Rejected,'operator-required'):self.b.request({'version':1,'op':op,'service':'hermes'},55555)
    def test_recipe_and_shell_fields_denied(self):
        for body in ({'version':1,'op':'exec'},{'version':1,'op':'recover','service':'hermes','command':'touch /tmp/never'}):
            with self.assertRaises(Rejected):self.b.request(body,0)
    def test_arbitrary_target_denied(self):
        for service in ('docker','host','hermes; echo bad','other-cell'):
            with self.assertRaisesRegex(Rejected,'target-denied'):self.b.request({'version':1,'op':'recover','service':service},0)
    def test_raw_docker_secrets_never_projected(self):
        with patch('doghouse_dsh.broker.trusted',side_effect=Path),patch.object(self.b,'run',return_value=json.dumps(self.rows)):
            self.b.collect()
        result=json.dumps(self.b.e.public());self.assertNotIn('secret-sentinel',result);self.assertNotIn('TOKEN',result)
        self.assertTrue(self.b.e.public()['snapshot']['ownershipVerified'])
    def test_cli_failure_is_unknown_not_success(self):
        with patch('doghouse_dsh.broker.trusted',side_effect=Path),patch.object(self.b,'run',side_effect=Rejected('docker-command-failed')):self.b.collect()
        self.assertFalse(self.b.e.public()['snapshot']['dockerAvailable'])
        self.assertTrue(all(x['state']=='unknown' for x in self.b.e.public()['snapshot']['services'].values()))

if __name__=='__main__':unittest.main()
