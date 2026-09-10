"""Unprivileged observer. Only the Unix peer-checked broker can perform effects."""
import argparse,json,socket,time

def request(path,body):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
        s.settimeout(60);s.connect(path);s.sendall(json.dumps({'version':1,**body}).encode()+b'\n')
        raw=b''
        while not raw.endswith(b'\n'):
            b=s.recv(65536)
            if not b:raise OSError('broker-disconnected')
            raw+=b
            if len(raw)>1024*1024:raise OSError('oversize-response')
        return json.loads(raw)

def main():
    p=argparse.ArgumentParser();p.add_argument('--socket',required=True);p.add_argument('--once',action='store_true');a=p.parse_args()
    while True:
        try:
            r=request(a.socket,{'op':'snapshot'})
            if r.get('ok'):
                for service,decision in r['status']['decisions'].items():
                    if decision=='eligible':request(a.socket,{'op':'recover','service':service})
            elif a.once:raise SystemExit(1)
        except (OSError,ValueError):
            if a.once:raise SystemExit(1)
        if a.once:return
        time.sleep(5)

if __name__=='__main__':main()
