"""Local operations; never executes .env as code. PDF parsing uses pypdf."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import sqlite3
from datetime import datetime
from app.core import BASE, Settings, Knowledge, issue_token


def load_env(path):
    path=Path(path)
    if not path.is_file():
        raise ValueError('未找到.env,请先执行 python3 manage.py init')
    for number,line in enumerate(path.read_text(encoding='utf-8').splitlines(),1):
        line=line.strip()
        if not line or line.startswith('#'):continue
        if '=' not in line:raise ValueError('配置第%d行缺少等号'%number)
        name,value=line.split('=',1);name=name.strip()
        if not re.fullmatch('[A-Z][A-Z0-9_]*',name):raise ValueError('配置第%d行变量名无效'%number)
        parts=shlex.split(value,comments=True,posix=True)
        if len(parts)>1:raise ValueError('配置第%d行含空格,请用引号包裹'%number)
        os.environ.setdefault(name,parts[0] if parts else '')


def init_env(path):
    text=(BASE/'.env.example').read_text().replace('AUTH_SECRET=\n','AUTH_SECRET='+secrets.token_urlsafe(48)+'\n')
    fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(text)


def backup_database(database, destination):
    database=Path(database)
    if not database.is_file():raise ValueError('数据库不存在,请先启动并使用服务')
    destination=Path(destination)
    if destination.exists():raise ValueError('备份路径已经存在,请使用新文件名')
    destination.parent.mkdir(parents=True,exist_ok=True)
    # Reserve filename exclusively; SQLite backup handles WAL and a live server.
    fd=os.open(str(destination),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
    source=sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)
    target=sqlite3.connect(str(destination))
    try:
        source.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('备份校验失败')
    finally:target.close();source.close()
    return destination


def main():
    parser=argparse.ArgumentParser(description='SmartTITU客服服务管理')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('init',help='创建.env并生成随机签名密钥,不覆盖已有文件')
    run=sub.add_parser('serve',help='加载.env并启动服务')
    run.add_argument('--host');run.add_argument('--port',type=int)
    token=sub.add_parser('token',help='可信后端本地调试签发器')
    token.add_argument('--tenant',required=True);token.add_argument('--user',required=True);token.add_argument('--ttl',type=int,default=3600)
    ingest=sub.add_parser('ingest',help='增量读取Word/PDF/Markdown/TXT,生成语义索引')
    ingest.add_argument('--rebuild',action='store_true',help='模型或切分变化时全量重建')
    sub.add_parser('documents',help='列出文档及当前版本')
    revisions=sub.add_parser('revisions',help='查看文档修订记录');revisions.add_argument('document_id')
    disable=sub.add_parser('deactivate',help='显式停用文档,保留历史引用');disable.add_argument('document_id')
    activate=sub.add_parser('activate',help='切换已保存修订,保留原文件');activate.add_argument('document_id');activate.add_argument('--revision',required=True)
    sub.add_parser('check',help='校验配置和知识,不发送外网请求')
    backup=sub.add_parser('backup',help='一致性备份SQLite,默认写入backups目录')
    backup.add_argument('--output')
    args=parser.parse_args()
    try:
        if args.command=='init':
            init_env(BASE/'.env');print('已创建.env并生成随机AUTH_SECRET,请按需编辑配置。');return
        # Containers receive configuration through env_file, without copying the secret file into the image.
        if (BASE/'.env').is_file():load_env(BASE/'.env')
        elif not os.getenv('AUTH_SECRET'):raise ValueError('未找到.env或AUTH_SECRET环境变量,请先初始化配置')
        config=Settings();config.validate()
        if args.command=='check':
            if config.retrieval_backend=='semantic':
                from app.rag import RAGSettings,SemanticKnowledge
                rag=RAGSettings();rag.validate();kb=SemanticKnowledge(rag)
            else:kb=Knowledge(config.knowledge)
            from importlib.metadata import version
            frameworks={name:version(name) for name in ('fastapi','uvicorn','langchain-core')}
            print(json.dumps({'frameworks':frameworks,'configuration':'valid','mode':config.mode,'retrieval_backend':config.retrieval_backend,'model_configured':bool(config.model_key and config.model),'knowledge_count':len(kb.rows),'database':config.db,'next_step':'知识数量为0时先执行ingest' if not kb.rows else '可以启动服务'},ensure_ascii=False,indent=2))
        elif args.command in ('ingest','documents','revisions','deactivate','activate'):
            from app.rag import RAGSettings,DocumentStore,ingest_documents
            rag=RAGSettings();store=DocumentStore(rag.index_path)
            if args.command=='ingest':result=ingest_documents(rag,rebuild=args.rebuild)
            elif args.command=='documents':result=store.documents()
            elif args.command=='revisions':result=store.revisions(args.document_id)
            elif args.command=='activate':store.activate(args.document_id,args.revision);result={'activated':args.document_id,'revision':args.revision}
            else:store.deactivate(args.document_id);result={'deactivated':args.document_id}
            print(json.dumps(result,ensure_ascii=False,indent=2))
        elif args.command=='token':print(issue_token(config.secret,args.tenant,args.user,args.ttl))
        elif args.command=='backup':
            output=args.output or str(BASE/'backups'/('assistant-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.sqlite3'))
            print('会话备份已校验:'+str(backup_database(config.db,output)))
            from app.rag import RAGSettings
            index=RAGSettings().index_path
            if Path(index).is_file():
                target=Path(output).with_name(Path(output).stem+'-knowledge.sqlite3')
                print('知识索引及原文版本备份已校验:'+str(backup_database(index,target)))
        elif args.command=='serve':
            from app.server import main as serve
            import sys
            sys.argv=[sys.argv[0]]+(['--host',args.host] if args.host else [])+(['--port',str(args.port)] if args.port else [])
            serve()
    except Exception as error:
        from app.rag import RAGError
        from importlib.metadata import PackageNotFoundError
        if isinstance(error,PackageNotFoundError):
            parser.exit(2,'缺少新框架依赖，请重新构建镜像，或安装requirements.lock。\n')
        if not isinstance(error,(ValueError,FileExistsError,RAGError)):raise
        parser.exit(2,str(error)+'\n')

if __name__=='__main__':main()
