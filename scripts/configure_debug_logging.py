"""Toggle local content debugging without printing or executing .env secrets."""
import argparse
from datetime import datetime
from pathlib import Path
import re
import shutil


def main():
    parser=argparse.ArgumentParser(description='开启或关闭临时问答节点正文日志')
    parser.add_argument('mode',choices=('enable','disable'))
    parser.add_argument('--days',type=int,default=3,help='调试正文保留天数，1..30，默认3')
    args=parser.parse_args()
    if not 1<=args.days<=30:parser.error('--days 范围为1..30')
    root=Path(__file__).resolve().parent.parent
    path=root/'.env'
    if not path.is_file():parser.exit(1,'未找到项目 .env，未修改。\n')
    if path.is_symlink():parser.exit(1,'不接受符号链接 .env，未修改。\n')
    directory=root/'backups'/('debug-log-config-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    directory.mkdir(parents=True,mode=0o700)
    backup=directory/'env.before';shutil.copy2(path,backup);backup.chmod(0o600)
    text=path.read_text()
    for key,value in {'LOG_DEBUG_CONTENT':'true' if args.mode=='enable' else 'false',
                      'LOG_DEBUG_RETENTION_DAYS':str(args.days)}.items():
        text=re.sub(r'^[ \t]*(?:export[ \t]+)?'+key+r'[ \t]*=.*(?:\n|$)','',text,flags=re.M)
        text=text.rstrip()+'\n'+key+'='+value+'\n'
    temp=path.with_name('.env.debug-log-tmp');temp.write_text(text);temp.chmod(0o600);temp.replace(path)
    print('已'+('开启' if args.mode=='enable' else '关闭')+'临时问答正文日志配置，原配置已安全备份。')
    print('执行 sh scripts/enterprise.sh start 重建应用容器后生效；仅 docker restart 不会加载新增环境变量。')

if __name__=='__main__':main()
