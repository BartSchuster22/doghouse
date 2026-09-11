"""Fixed, read-only native query. Never uses immutable=1 (which ignores WAL).
The native UID maintains SQLite locking sidecars; the host data mount stays RO.
No command, path, query or environment comes from broker callers.
"""
import json,re
QUERY="SELECT CASE WHEN status IN ('todo','in_progress','blocked','done','archived') THEN status ELSE 'other' END AS bucket,COUNT(*) FROM tasks GROUP BY bucket"
SCRIPT="import sqlite3,json;from pathlib import Path;p=Path('/opt/data/kanban.db');assert p.is_file() and not p.is_symlink();c=sqlite3.connect('file:/opt/data/kanban.db?mode=ro',uri=True,timeout=1);c.execute('PRAGMA query_only=ON');print(json.dumps(dict(c.execute("+repr(QUERY)+"))));c.close()"
def read_counts(run,cell):
 if not re.fullmatch(r'dsh2-stage[0-9]+-qa[0-9]+',cell):raise ValueError('invalid-native-cell')
 result=json.loads(run(['exec','--user','10000:10000',cell+'-hermes-1','/opt/hermes/.venv/bin/python','-I','-c',SCRIPT],timeout=15))
 allowed={'todo','in_progress','blocked','done','archived','other'}
 if not isinstance(result,dict) or set(result)-allowed or any(type(n) is not int or n<0 for n in result.values()):raise ValueError('invalid-native-observation')
 return result
