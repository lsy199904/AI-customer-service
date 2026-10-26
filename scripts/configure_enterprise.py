"""Generate local infrastructure credentials without changing existing model/SSO settings."""
from pathlib import Path
import os
import secrets
import shlex
import shutil
from datetime import datetime
from urllib.parse import quote
ROOT=Path(__file__).resolve().parent.parent

def read(path):
    result={}
    for line in path.read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('#') or '=' not in line:continue
        key,value=line.split('=',1);parts=shlex.split(value,comments=True)
        if len(parts)>1:raise ValueError('配置包含未加引号的空格')
        result[key.strip()]=parts[0] if parts else ''
    return result

def main():
    path=ROOT/'.env'
    if not path.is_file():raise SystemExit('先恢复现有.env；不会自动覆盖模型或身份配置')
    values=read(path)
    directory=ROOT/'backups'/('configuration-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    shutil.copy2(path,directory/'env.before');(directory/'env.before').chmod(0o600)
    defaults={
        'POSTGRES_USER':'assistant_admin','POSTGRES_DB':'assistant','POSTGRES_PORT':'55432',
        'POSTGRES_PASSWORD':secrets.token_urlsafe(32),
        'APP_DB_USER':'assistant_runtime','APP_DB_PASSWORD':secrets.token_urlsafe(32),
        'MILVUS_ROOT_PASSWORD':secrets.token_urlsafe(32),
        'MINIO_ROOT_USER':'assistantstorage','MINIO_ROOT_PASSWORD':secrets.token_urlsafe(32),
        'MILVUS_URI':'http://127.0.0.1:19530','MILVUS_COLLECTION':'smarttitu_knowledge',
        'OPERATIONS_TOKEN':secrets.token_urlsafe(40),'APP_WORKERS':'1',
        'MODEL_DISABLE_THINKING':'true','MODEL_MAX_TOKENS':'2048',
    }
    added={key:value for key,value in defaults.items() if not values.get(key)}
    values.update(added)
    if not values.get('DATABASE_URL'):
        added['DATABASE_URL']='postgresql://'+quote(values['APP_DB_USER'],safe='')+':'+quote(values['APP_DB_PASSWORD'],safe='')+'@127.0.0.1:'+values['POSTGRES_PORT']+'/'+quote(values['POSTGRES_DB'],safe='')
    if not values.get('MILVUS_TOKEN'):added['MILVUS_TOKEN']='root:'+values['MILVUS_ROOT_PASSWORD']
    # Selecting enterprise infrastructure is explicit, rather than silently falling back.
    text=path.read_text()
    import re
    if re.search(r'^VECTOR_BACKEND=',text,re.M):text=re.sub(r'^VECTOR_BACKEND=.*$','VECTOR_BACKEND=milvus',text,flags=re.M)
    else:added['VECTOR_BACKEND']='milvus'
    if added:text+='\n# Enterprise infrastructure (generated locally; keep private)\n'+''.join(k+'='+shlex.quote(v)+'\n' for k,v in added.items())
    temp=path.with_suffix('.enterprise-tmp');temp.write_text(text);temp.chmod(0o600);temp.replace(path)
    values=read(path)
    generated=ROOT/'deploy/generated';generated.mkdir(parents=True,exist_ok=True,mode=0o700)
    # user.yaml overrides the official image defaults; credentials never enter Git/image layers.
    import json
    config='common:\n  security:\n    authorizationEnabled: true\n    defaultRootPassword: '+json.dumps(values['MILVUS_ROOT_PASSWORD'])+'\n'
    target=generated/'milvus-user.yaml';target.write_text(config);target.chmod(0o600)
    print('已保留模型与身份配置，生成企业数据库配置。原配置备份：'+str(directory/'env.before'))
    print('未启动任何服务；继续执行 enterprise.sh build / infrastructure / migrate。')

if __name__=='__main__':main()
