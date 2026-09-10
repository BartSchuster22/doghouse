import copy,json,tempfile,unittest
from pathlib import Path
from doghouse_dsh.engine import Engine,Rejected,SERVICES
from doghouse_dsh.health_contracts import HealthContract,CheckObservation,evaluate_health_contract

class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.t=1000000.;self.path=Path(self.temp.name)/'ops.db'
        self.e=Engine(self.path,lambda:self.t)
        self.s={'observedAt':self.t,'bootId':'boot-a','dockerAvailable':True,'ownershipVerified':True,
                'storagePressure':False,'nativeWork':{'active':0},
                'services':{n:{'state':'healthy','running':True} for n in SERVICES}}
    def tearDown(self):self.e.db.close();self.temp.cleanup()
    def observe(self,n=1):
        self.s['observedAt']=self.t
        for _ in range(n):self.e.observe(copy.deepcopy(self.s))
    def failed(self):self.s['services']['hermes']={'state':'failed','running':False};self.observe(3)
    def test_no_checks_unknown(self):
        r=evaluate_health_contract(HealthContract('x',()),{});self.assertEqual(r.state.value,'unknown');self.assertFalse(r.safe_to_restart)
    def test_missing_active_unknown_not_zero(self):
        r=evaluate_health_contract(HealthContract('x',('active-work',)),{'active-work':CheckObservation(200,{})});self.assertFalse(r.safe_to_restart)
    def test_missing_custom_status_fails_closed(self):
        r=evaluate_health_contract(HealthContract('x',('custom',)),{'custom':CheckObservation(200,{})});self.assertFalse(r.safe_to_restart)
    def test_healthy_no_action(self):self.observe();self.assertEqual(self.e.decision('hermes'),'already-healthy')
    def test_debounce(self):
        self.s['services']['hermes']={'state':'failed','running':False};self.observe();self.assertEqual(self.e.decision('hermes'),'debouncing')
    def test_dependency_failure(self):
        self.failed();self.s['services']['postgresql']['state']='failed';self.observe();self.assertEqual(self.e.decision('hermes'),'dependency-unhealthy')
    def test_storage_blocks(self):
        self.failed();self.s['storagePressure']=True;self.observe();self.assertEqual(self.e.decision('hermes'),'storage-pressure')
    def test_docker_blocks(self):
        self.failed();self.s['dockerAvailable']=False;self.observe();self.assertEqual(self.e.decision('hermes'),'docker-unavailable')
    def test_owner_blocks(self):
        self.failed();self.s['ownershipVerified']=False;self.observe();self.assertEqual(self.e.decision('hermes'),'ownership-unverified')
    def test_unknown_not_failed(self):
        self.failed();self.s['services']['hermes']['state']='unknown';self.observe();self.assertEqual(self.e.decision('hermes'),'unknown-state')
    def test_active_running_hermes_not_killed(self):
        self.failed();self.s['services']['hermes']['running']=True
        for active in (None,1,5):
            self.s['nativeWork']['active']=active;self.observe();self.assertEqual(self.e.decision('hermes'),'active-or-unknown-native-work')
    def test_stopped_executor_can_recover_without_business_replay(self):
        self.failed();self.s['nativeWork']['active']=1;self.observe();self.assertEqual(self.e.decision('hermes'),'eligible')
    def test_stale_blocks(self):
        self.failed();self.t+=21;self.assertEqual(self.e.decision('hermes'),'stale-observation')
    def test_maintenance_persists(self):
        self.failed();self.e.maintenance(True);self.e.db.close();self.e=Engine(self.path,lambda:self.t);self.observe();self.assertEqual(self.e.decision('hermes'),'maintenance')
    def test_budget_is_durable_before_effect(self):
        self.failed();self.e.reserve('hermes');self.assertEqual(self.e.decision('hermes'),'uncertain-prior-effect')
        self.e.db.close();self.e=Engine(self.path,lambda:self.t);self.observe();self.assertEqual(self.e.decision('hermes'),'uncertain-prior-effect')
    def test_backoff_circuit_and_explicit_ack(self):
        self.failed()
        for delay in (30,60,120):
            a=self.e.reserve('hermes');self.e.finish(a,'command-returned')
            self.assertIn(self.e.decision('hermes'),('backoff','circuit-open'))
            self.t+=delay;self.observe()
        self.assertEqual(self.e.decision('hermes'),'circuit-open')
        self.e.acknowledge('hermes');self.t+=1;self.observe();self.assertEqual(self.e.decision('hermes'),'eligible')
    def test_command_return_not_health(self):
        self.failed();a=self.e.reserve('hermes');self.e.finish(a,'command-returned')
        self.assertEqual(self.e.public()['snapshot']['services']['hermes']['state'],'failed')
    def test_recurring_incident_retains_history(self):
        self.failed();self.s['services']['hermes']['state']='healthy';self.observe();self.failed()
        self.assertEqual(len(self.e.public()['incidents']),2)
    def test_reboot_audit_persists(self):
        self.observe();self.s['bootId']='boot-b';self.observe();self.assertTrue(any(a['action']=='host-boot' for a in self.e.public()['audit']))
    def test_no_arbitrary_target(self):
        self.failed()
        for target in ('docker','host','postgresql','other-cell','hermes; touch /tmp/pwn'):
            with self.assertRaises(Rejected):self.e.reserve(target)
    def test_usage_not_fabricated(self):
        self.observe();u=self.e.public()['usageProvenance'];self.assertIsNone(u['modelTokens']);self.assertIsNone(u['modelCost'])

if __name__=='__main__':unittest.main()
