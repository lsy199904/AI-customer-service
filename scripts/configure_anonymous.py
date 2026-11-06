"""Enable an independent anonymous entry without touching model or login settings."""
import argparse
import os
from pathlib import Path
import re
import shutil
import time
from urllib.parse import urlsplit
import uuid

ROOT=Path(__file__).resolve().parent.parent


def main():
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=('enable','disable'))
    p.add_argument('--origin',action='append',default=[])
    p.add_argument('--https-cookie',action='store_true',help='HTTPS terminates at a trusted reverse proxy')
    a=p.parse_args()
    for origin in a.origin:
        parsed=urlsplit(origin)
        if not re.fullmatch(r'https?://(?:[A-Za-z0-9.-]+|\[[0-9a-fA-F:]+\])(?::[0-9]{1,5})?',origin) or not parsed.hostname:
            p.error('origin必须是完整协议/域名/必要端口，不能包含路径或通配符')
    env=ROOT/'.env'
    if not env.is_file():raise SystemExit('请先准备.env')
    old=env.read_text();text=old
    def set_value(key,value):
        nonlocal text
        text=re.sub(r'^\s*'+re.escape(key)+r'\s*=.*(?:\n|$)','',text,flags=re.M)
        text=text.rstrip()+'\n'+key+'='+value+'\n'
    set_value('ANONYMOUS_WIDGET_ENABLED','true' if a.action=='enable' else 'false')
    if a.https_cookie:set_value('ANONYMOUS_COOKIE_SECURE','true')
    if a.origin:
        existing=re.findall(r'^\s*FRAME_ORIGINS\s*=\s*(.*)$',old,re.M)
        value=(existing[-1].strip().strip('"\'') if existing else '')
        origins=[x.strip() for x in value.split(',') if x.strip()]
        set_value('FRAME_ORIGINS',','.join(dict.fromkeys(origins+a.origin)))
    backup=ROOT/'backups'/('anonymous-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
    backup.mkdir(parents=True,mode=0o700);shutil.copyfile(env,backup/'env.before');(backup/'env.before').chmod(0o600)
    temporary=env.with_name('.env.anonymous-'+uuid.uuid4().hex)
    try:
        with open(temporary,'x',opener=lambda path,flags:os.open(path,flags,0o600)) as f:f.write(text)
        temporary.replace(env)
    finally:temporary.unlink(missing_ok=True)
    print('匿名入口配置已更新，原凭证入口和模型配置保留。执行v3.sh start后生效。')
    print('配置备份：'+str(backup/'env.before'))

if __name__=='__main__':main()
