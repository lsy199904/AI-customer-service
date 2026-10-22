"""Development token issuer. Production: call issue_token in trusted console backend."""
import argparse
from .core import Settings, issue_token

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--tenant',required=True)
    p.add_argument('--user',required=True)
    p.add_argument('--ttl',type=int,default=3600)
    args=p.parse_args()
    config=Settings();config.validate()
    print(issue_token(config.secret,args.tenant,args.user,args.ttl))

if __name__=='__main__':
    main()
