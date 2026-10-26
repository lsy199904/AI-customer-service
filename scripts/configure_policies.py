"""Apply the explicitly selected customer-service policies, preserving other settings."""
from pathlib import Path
from datetime import datetime
import os
import re
import shutil
import tempfile
ROOT=Path(__file__).resolve().parent.parent
POLICIES={'SEMANTIC_MIN_SIMILARITY':'0.75','SESSION_RETENTION_DAYS':'7',
          'SESSION_CONTEXT_ROUNDS':'20','TENANT_MESSAGES_PER_MINUTE':'20',
          'RETRIEVAL_TIMEOUT_SECONDS':'15'}

def main():
    path=ROOT/'.env'
    if not path.is_file():raise SystemExit('未找到.env，请先恢复现有配置')
    original=path.read_text()
    directory=ROOT/'backups'/('policies-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    directory.mkdir(parents=True,mode=0o700)
    shutil.copy2(path,directory/'env.before');(directory/'env.before').chmod(0o600)
    lines=[]
    for line in original.splitlines():
        match=re.match(r'^\s*([A-Z_]+)\s*=',line)
        if not match or match.group(1) not in POLICIES:lines.append(line)
    text='\n'.join(lines)+'\n\n# Customer-service policies\n'+''.join(k+'='+v+'\n' for k,v in POLICIES.items())
    fd,temp=tempfile.mkstemp(prefix='.policies-',dir=ROOT)
    try:
        with os.fdopen(fd,'w') as stream:stream.write(text)
        os.chmod(temp,0o600);os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    print('已更新相似度0.75、历史7天、上下文20轮、企业20条/分钟、检索15秒。')
    print('原配置已备份：'+str(directory/'env.before'))
    print('执行 enterprise.sh start 重建应用容器以加载新环境变量；不需要重新入库。')

if __name__=='__main__':main()
