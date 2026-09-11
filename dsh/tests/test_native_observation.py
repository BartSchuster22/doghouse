import json,sqlite3,subprocess,sys,tempfile,unittest
from pathlib import Path
from doghouse_dsh.native_observation import read_counts,SCRIPT
class NativeObservationTests(unittest.TestCase):
 def test_fixed_argv_and_uid(self):
  seen=[]
  def run(a,timeout):seen.append((a,timeout));return '{"done":3}'
  self.assertEqual(read_counts(run,'dsh2-stage5-qa5'),{'done':3});a,t=seen[0]
  self.assertEqual(a[:4],['exec','--user','10000:10000','dsh2-stage5-qa5-hermes-1']);self.assertEqual(a[-1],SCRIPT);self.assertEqual(t,15)
 def test_foreign_cell_denied_before_execution(self):
  with self.assertRaises(ValueError):read_counts(lambda *a,**k:self.fail('executed'), 'production;cmd')
 def test_malformed_result_denied(self):
  for v in ['[]','{"done":true}','{"done":-1}','{"foreign":1}']:
   with self.subTest(v=v),self.assertRaises(ValueError):read_counts(lambda *a,**k:v,'dsh2-stage5-qa5')
 def test_real_uncheckpointed_wal_is_observed_without_data_changes(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'kanban.db';c=sqlite3.connect(p);c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA wal_autocheckpoint=0');c.execute('CREATE TABLE tasks(status TEXT)');c.commit();c.execute('INSERT INTO tasks VALUES (?)',('in_progress',));c.commit()
   before=p.read_bytes();wal=Path(str(p)+'-wal').read_bytes()
   out=subprocess.check_output([sys.executable,'-I','-c',SCRIPT.replace('/opt/data/kanban.db',str(p))],text=True)
   self.assertEqual(json.loads(out),{'in_progress':1});self.assertEqual(p.read_bytes(),before);self.assertEqual(Path(str(p)+'-wal').read_bytes(),wal);c.close()
if __name__=='__main__':unittest.main()
