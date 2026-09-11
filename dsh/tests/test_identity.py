import copy,unittest
from doghouse_dsh.identity import canonical_signature,legacy_signature
class IdentityTests(unittest.TestCase):
 def setUp(self):self.row={'Config':{'Image':'sha256:fixture','Env':['A=1','B=2'],'Labels':{'com.docker.compose.depends_on':'b:service_healthy:false,a:service_started:false','owner':'fixture'},'Cmd':['one','two'],'Entrypoint':['entry','arg'],'User':'10000'},'HostConfig':{'Privileged':False,'ReadonlyRootfs':True,'NetworkMode':'fixture'}}
 def test_environment_permutation(self):
  b=copy.deepcopy(self.row);b['Config']['Env'].reverse();self.assertEqual(canonical_signature(self.row),canonical_signature(b));self.assertNotEqual(legacy_signature(self.row),legacy_signature(b))
 def test_dependency_permutation(self):
  b=copy.deepcopy(self.row);b['Config']['Labels']['com.docker.compose.depends_on']='a:service_started:false,b:service_healthy:false';self.assertEqual(canonical_signature(self.row),canonical_signature(b))
 def test_environment_value_change(self):
  b=copy.deepcopy(self.row);b['Config']['Env'][0]='A=3';self.assertNotEqual(canonical_signature(self.row),canonical_signature(b))
 def test_duplicate_environment_denied(self):
  self.row['Config']['Env'].append('A=3')
  with self.assertRaises(ValueError):canonical_signature(self.row)
 def test_malformed_environment_denied(self):
  self.row['Config']['Env'].append('BAD')
  with self.assertRaises(ValueError):canonical_signature(self.row)
 def test_duplicate_dependencies_denied(self):
  self.row['Config']['Labels']['com.docker.compose.depends_on']='a:service_healthy:false,a:service_started:false'
  with self.assertRaises(ValueError):canonical_signature(self.row)
 def test_malformed_dependency_denied(self):
  self.row['Config']['Labels']['com.docker.compose.depends_on']='arbitrary-data'
  with self.assertRaises(ValueError):canonical_signature(self.row)
 def test_dependency_condition_change_denied(self):
  b=copy.deepcopy(self.row);b['Config']['Labels']['com.docker.compose.depends_on']='b:service_started:false,a:service_started:false';self.assertNotEqual(canonical_signature(self.row),canonical_signature(b))
 def test_command_order_preserved(self):
  b=copy.deepcopy(self.row);b['Config']['Cmd'].reverse();self.assertNotEqual(canonical_signature(self.row),canonical_signature(b))
 def test_privilege_change_preserved(self):
  b=copy.deepcopy(self.row);b['HostConfig']['Privileged']=True;self.assertNotEqual(canonical_signature(self.row),canonical_signature(b))
 def test_owner_label_change_preserved(self):
  b=copy.deepcopy(self.row);b['Config']['Labels']['owner']='foreign';self.assertNotEqual(canonical_signature(self.row),canonical_signature(b))
 def test_does_not_mutate_inspection(self):
  b=copy.deepcopy(self.row);canonical_signature(self.row);self.assertEqual(self.row,b)
 def test_protocol_domains_differ(self):self.assertNotEqual(canonical_signature(self.row),legacy_signature(self.row))
if __name__=='__main__':unittest.main()
