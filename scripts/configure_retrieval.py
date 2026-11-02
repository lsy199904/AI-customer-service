"""Apply retrieval thresholds only; preserve credentials and all other policies."""
from datetime import datetime
from pathlib import Path
import os
import re
import shutil
import tempfile

ROOT=Path(__file__).resolve().parent.parent
VALUES={'SEMANTIC_MIN_SIMILARITY':'0.60','RERANK_MIN_SCORE':'0.60'}

def main():
    path=ROOT/'.env'
    if not path.is_file() or path.is_symlink():raise SystemExit('未找到普通.env文件，未修改')
    original=path.read_text()
    backup=ROOT/'backups'/('retrieval-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True,mode=0o700)
    shutil.copy2(path,backup/'env.before');(backup/'env.before').chmod(0o600)
    lines=[]
    for line in original.splitlines():
        match=re.match(r'^\s*(?:export\s+)?([A-Z_]+)\s*=',line)
        if not match or match.group(1) not in VALUES:lines.append(line)
    text='\n'.join(lines).rstrip()+'\n\n# Retrieval thresholds\n'+''.join(k+'='+v+'\n' for k,v in VALUES.items())
    fd,temp=tempfile.mkstemp(prefix='.retrieval-',dir=ROOT)
    try:
        with os.fdopen(fd,'w') as f:f.write(text)
        os.chmod(temp,0o600);os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    print('已设置向量召回门槛0.60、重排门槛0.60；其他配置保持。原.env已备份。')
    print('执行 sh scripts/v3.sh start 重建容器加载配置，无需重新入库。')

if __name__=='__main__':main()
