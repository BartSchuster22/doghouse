"""Versioned Docker identity fingerprints; no order-dependent execution fields normalized."""
import hashlib,json,re
SCHEMA='alica-runtime-identity/v2'
CONFIG=('Image','Entrypoint','Cmd','User','Healthcheck','WorkingDir','Env','Labels')
HOST=('Privileged','CapAdd','CapDrop','ReadonlyRootfs','SecurityOpt','NetworkMode','PidMode','IpcMode','PortBindings','RestartPolicy')
def parts(row):return [{k:row['Config'].get(k) for k in CONFIG},{k:row['HostConfig'].get(k) for k in HOST}]
def legacy_signature(row):return hashlib.sha256(json.dumps(parts(row),sort_keys=True,separators=(',',':')).encode()).hexdigest()
def canonical_signature(row):
 config,host=parts(row)
 env=config['Env']
 if env is not None:
  if not isinstance(env,list) or any(not isinstance(s,str) or '=' not in s for s in env):raise ValueError('invalid-environment')
  names=[s.split('=',1)[0] for s in env]
  if any(not n for n in names) or len(names)!=len(set(names)):raise ValueError('ambiguous-environment')
  config['Env']=sorted(env)
 labels=config['Labels']
 if labels is not None:
  if not isinstance(labels,dict):raise ValueError('invalid-labels')
  labels=dict(labels);depends=labels.get('com.docker.compose.depends_on')
  if depends is not None:
   if not isinstance(depends,str):raise ValueError('invalid-dependencies')
   dependencies=depends.split(',') if depends else []
   if any(not re.fullmatch(r'[a-zA-Z0-9_-]+:(service_healthy|service_started|service_completed_successfully):(true|false)',v) for v in dependencies):raise ValueError('invalid-dependencies')
   names=[v.split(':',1)[0] for v in dependencies]
   if len(names)!=len(set(names)):raise ValueError('ambiguous-dependencies')
   labels['com.docker.compose.depends_on']=','.join(sorted(dependencies))
  config['Labels']=labels
 body=json.dumps([config,host],sort_keys=True,separators=(',',':'))
 return hashlib.sha256((SCHEMA+'\0'+body).encode()).hexdigest()
