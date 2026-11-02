"""Apply retrieval thresholds only; preserve credentials and all other policies."""
from datetime import datetime
from pathlib import Path
import argparse
import os
import re
import shutil
import tempfile

ROOT=Path(__file__).resolve().parent.parent

def main():
    parser=argparse.ArgumentParser(description='仅显式参数才修改阈值；不传参数保留.env')
    parser.add_argument('--semantic',type=float);parser.add_argument('--rerank',type=float)
    args=parser.parse_args()
    values={k:format(v,'.6g') for k,v in [('SEMANTIC_MIN_SIMILARITY',args.semantic),('RERANK_MIN_SCORE',args.rerank)] if v is not None}
    if any(not 0<=float(v)<=1 for v in values.values()):parser.error('阈值必须在0到1之间')
    path=ROOT/'.env'
    if not path.is_file() or path.is_symlink():raise SystemExit('未找到普通.env文件，未修改')
    original=path.read_text()
    if not values:
        print('未指定阈值，已保留.env。执行 sh scripts/v3.sh start 重新加载现有配置。');return
    backup=ROOT/'backups'/('retrieval-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True,mode=0o700)
    shutil.copy2(path,backup/'env.before');(backup/'env.before').chmod(0o600)
    lines=[]
    for line in original.splitlines():
        match=re.match(r'^\s*(?:export\s+)?([A-Z_]+)\s*=',line)
        if not match or match.group(1) not in values:lines.append(line)
    text='\n'.join(lines).rstrip()+'\n\n# Retrieval thresholds\n'+''.join(k+'='+v+'\n' for k,v in values.items())
    fd,temp=tempfile.mkstemp(prefix='.retrieval-',dir=ROOT)
    try:
        with os.fdopen(fd,'w') as f:f.write(text)
        os.chmod(temp,0o600);os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    print('已更新显式指定的阈值：'+', '.join(k+'='+v for k,v in values.items())+'；其他配置保持。原.env已备份。')
    print('执行 sh scripts/v3.sh start 重建容器加载配置，无需重新入库。')

if __name__=='__main__':main()
