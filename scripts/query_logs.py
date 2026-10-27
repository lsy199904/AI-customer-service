"""Read operational JSONL files locally; does not load credentials or contact services."""
import argparse
import json
from pathlib import Path
import re


def main():
    parser=argparse.ArgumentParser(description='按日期、请求、用户、会话或窗口查运营日志')
    parser.add_argument('--directory',default=str(Path(__file__).resolve().parent.parent/'var/logs'))
    parser.add_argument('--date',help='日期 YYYY-MM-DD（北京时间）')
    for name in ('request-id','http-request-id','user-ref','tenant-ref','session-ref','window-id','question-category','event'):
        parser.add_argument('--'+name)
    parser.add_argument('--errors',action='store_true',help='只看 WARNING / ERROR')
    args=parser.parse_args()
    if args.date and not re.fullmatch(r'\d{4}-\d{2}-\d{2}',args.date):parser.error('日期格式应为 YYYY-MM-DD')
    directory=Path(args.directory)
    if not directory.is_dir():parser.exit(1,'日志目录不存在；确认服务已更新并启动。\n')
    filters={key:value for key,value in vars(args).items() if value is not None and key not in ('directory','date','errors')}
    paths=sorted(directory.glob('app-'+(args.date or '*')+'-*.jsonl*'))
    for path in paths:
        if not re.fullmatch(r'app-\d{4}-\d{2}-\d{2}-\d+\.jsonl(?:\.[1-4])?',path.name):continue
        if path.is_symlink():continue
        with path.open(encoding='utf-8') as source:
            for line in source:
                try:record=json.loads(line)
                except (ValueError,UnicodeError):continue
                if args.errors and record.get('level') not in ('WARNING','ERROR','CRITICAL'):continue
                def matches(key,value):
                    if key=='request_id':return value in (record.get('request_id'),record.get('http_request_id'))
                    return record.get(key)==value
                if all(matches(key,value) for key,value in filters.items()):print(json.dumps(record,ensure_ascii=False))

if __name__=='__main__':main()
