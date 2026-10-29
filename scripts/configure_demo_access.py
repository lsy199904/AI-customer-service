"""Enable the explicitly opt-in demo identity endpoint without exposing deployment secrets."""
import argparse
from datetime import datetime
from pathlib import Path
import re
import shutil


def main():
    parser=argparse.ArgumentParser(description='开启或关闭测试页自动凭证')
    parser.add_argument('mode',choices=('enable','disable'))
    args=parser.parse_args()
    root=Path(__file__).resolve().parent.parent;path=root/'.env'
    if not path.is_file() or path.is_symlink():parser.exit(1,'未找到普通.env文件，未修改。\n')
    directory=root/'backups'/('demo-access-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    directory.mkdir(parents=True,mode=0o700)
    backup=directory/'env.before';shutil.copy2(path,backup);backup.chmod(0o600)
    text=re.sub(r'^[ \t]*(?:export[ \t]+)?DEMO_AUTO_LOGIN[ \t]*=.*(?:\n|$)','',path.read_text(),flags=re.M)
    temp=path.with_name('.env.demo-tmp');temp.write_text(text.rstrip()+'\nDEMO_AUTO_LOGIN='+('true' if args.mode=='enable' else 'false')+'\n');temp.chmod(0o600);temp.replace(path)
    print('已更新测试页自动凭证配置，原.env已安全备份。')
    print('执行 sh scripts/enterprise.sh start 重新创建客服容器后生效。')

if __name__=='__main__':main()
