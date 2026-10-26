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
    diagnostic=sub.add_parser('retrieve',help='运维检索诊断,不调用聊天模型,不打印密钥')
    diagnostic.add_argument('--query',required=True)
    diagnostic.add_argument('--no-rerank',action='store_true')
    sub.add_parser('documents',help='列出文档及当前版本')
    revisions=sub.add_parser('revisions',help='查看文档修订记录');revisions.add_argument('document_id')
    disable=sub.add_parser('deactivate',help='显式停用文档,保留历史引用');disable.add_argument('document_id')
    activate=sub.add_parser('activate',help='切换已保存修订,保留原文件');activate.add_argument('document_id');activate.add_argument('--revision',required=True)
    evaluation=sub.add_parser('evaluate',help='使用本地私有评测集评估语义召回、引用与图片')
    evaluation.add_argument('--dataset',required=True);evaluation.add_argument('--output',required=True)
    evaluation.add_argument('--answers',action='store_true');evaluation.add_argument('--allow-unreviewed',action='store_true')
    preparation=sub.add_parser('prepare-evaluation',help='为全部知识生成待人工审阅的多样问法，不进入客户检索逻辑')
    preparation.add_argument('--output',required=True);preparation.add_argument('--variants',type=int,default=5)
    sub.add_parser('sync-vectors',help='将已有活动向量同步到Milvus，不调用Embedding')
    doctor=sub.add_parser('doctor',help='检查实际数据库与向量服务；可选检查模型')
    doctor.add_argument('--models',action='store_true')
    migrate=sub.add_parser('migrate-storage',help='停止旧服务后将SQLite历史和知识版本迁移到PostgreSQL')
    migrate.add_argument('--chat');migrate.add_argument('--knowledge');migrate.add_argument('--backup-dir')
    export=sub.add_parser('export-storage',help='维护窗口内将PostgreSQL聊天及知识导出至新SQLite文件供回退')
    export.add_argument('--output-dir',required=True)
    prune=sub.add_parser('prune-checkpoints',help='清理过期工作流检查点，保留聊天消息')
    prune.add_argument('--days',type=int,default=30)
    sub.add_parser('prune-sessions',help='按会话保留期限清理在线历史及检查点')
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
            frameworks={name:version(name) for name in ('fastapi','uvicorn','langchain','langchain-core','langgraph')}
            print(json.dumps({'frameworks':frameworks,'configuration':'valid','mode':config.mode,'retrieval_backend':config.retrieval_backend,'model_configured':bool(config.model_key and config.model),'knowledge_count':len(kb.rows),'database':config.db if not config.database_url else 'postgresql',
                'vector_backend':rag.vector_backend if config.retrieval_backend=='semantic' else 'lexical',
                'policies':{'semantic_min_similarity':rag.min_similarity if config.retrieval_backend=='semantic' else None,
                    'session_retention_days':config.retention_days,'session_context_rounds':config.context_rounds,
                    'tenant_messages_per_minute':config.requests_per_minute,'retrieval_timeout_seconds':config.retrieval_timeout},
                'workflow':'langgraph','next_step':'知识数量为0时先执行ingest' if not kb.rows else '可以启动服务'},ensure_ascii=False,indent=2))
        elif args.command=='prepare-evaluation':
            from app.evaluation import prepare
            print(json.dumps(prepare(config,args.output,args.variants),ensure_ascii=False,indent=2))
        elif args.command=='evaluate':
            from app.evaluation import evaluate
            result=evaluate(config,args.dataset,args.output,args.answers,args.allow_unreviewed)
            print(json.dumps(result,ensure_ascii=False,indent=2))
            if result['failed']:parser.exit(1,'评测存在失败，请查看本地报告。\n')
        elif args.command=='sync-vectors':
            from app.rag import RAGSettings,sync_vectors
            print(json.dumps(sync_vectors(RAGSettings()),ensure_ascii=False,indent=2))
        elif args.command=='migrate-storage':
            from app.migration import migrate
            from app.rag import RAGSettings
            result=migrate(config,args.chat or config.db,args.knowledge or RAGSettings().index_path,
                args.backup_dir or str(BASE/'backups'/('migration-'+datetime.now().strftime('%Y%m%d-%H%M%S'))))
            print(json.dumps(result,ensure_ascii=False,indent=2))
        elif args.command=='export-storage':
            from app.migration import export_sqlite
            print(json.dumps(export_sqlite(config,args.output_dir),ensure_ascii=False,indent=2))
        elif args.command=='doctor':
            from app.core import Service,Model
            from app.rag import RAGSettings,EmbeddingClient,RerankerClient
            service=Service(config)
            try:
                service.db.execute('SELECT 1').fetchone()
                result={'database':'ok','workflow':'langgraph','knowledge_count':len(service.knowledge.rows)}
                from app.workflow import SupportWorkflow
                service._workflow=SupportWorkflow(service)
                result['checkpoints']='persistent'
                if config.retrieval_backend=='semantic' and getattr(service.knowledge,'vectors',None):
                    vector=service.knowledge.vectors
                    if not vector.client.has_collection(vector.collection):raise ValueError('Milvus尚无当前索引，请先sync-vectors或ingest')
                    result['milvus']='ok'
                if not result['knowledge_count']:raise ValueError('活动知识为空，请先入库')
                if args.models and config.retrieval_backend=='semantic':
                    rag=RAGSettings();vectors=EmbeddingClient(rag).embed(['连接检查'])
                    result['embedding_dimensions']=len(vectors[0])
                    if getattr(service.knowledge,'vectors',None):
                        vector.search(vectors[0],list(service.knowledge.rows.values()),1)
                        result['vector_search']='ok'
                    if rag.rerank_enabled:
                        RerankerClient(rag).rank('如何注册企业账号',['使用手机号注册企业账号。','查询账单。']);result['reranker']='ok'
                    if config.mode=='llm':Model(config).answer('你好',[],[],{'_intent':'greeting'});result['chat_model']='ok'
                print(json.dumps(result,ensure_ascii=False,indent=2))
            finally:service.close()
        elif args.command=='prune-sessions':
            from app.core import Service
            service=Service(config)
            try:
                totals={'deleted_sessions':0,'deleted_messages':0,'deleted_checkpoints':0,'skipped_busy':0}
                while True:
                    result=service.prune_sessions()
                    for key in totals:totals[key]+=result[key]
                    if not result['batch_full'] or result['skipped_busy']:break
                print(json.dumps(totals,ensure_ascii=False,indent=2))
            finally:service.close()
        elif args.command=='prune-checkpoints':
            if args.days<1:raise ValueError('至少保留1天检查点')
            from app.core import Service
            from app.workflow import SupportWorkflow
            import time
            service=Service(config);count=0
            try:
                service._workflow=SupportWorkflow(service)
                rows=service.db.execute('SELECT id,session FROM workflow_runs WHERE updated<?',(time.time()-args.days*86400,)).fetchall()
                from contextlib import nullcontext
                for row in rows:
                    lock=service.db.session_lock(row['session']) if config.database_url else nullcontext()
                    with lock:
                        service._workflow.saver.delete_thread(row['id'])
                        with service.db:service.db.execute('DELETE FROM workflow_runs WHERE id=?',(row['id'],))
                        count+=1
                print(json.dumps({'pruned_checkpoints':count,'chat_messages':'preserved'}))
            finally:service.close()
        elif args.command=='retrieve':
            from app.rag import RAGSettings,SemanticKnowledge
            rag=RAGSettings()
            if args.no_rerank:rag.rerank_enabled=False
            report=SemanticKnowledge(rag).assess(args.query,diagnostics=True)
            selected=[{'id':row['id'],'title':row['title'],'source_file':row['source_file'],
                       'image_ids':row.get('image_ids',[]),'similarity':similarity,'score':score} for score,row,similarity in report['hits']]
            print(json.dumps({'query':args.query,'retrieval':{k:v for k,v in report.items() if k not in ('hits','_diagnostics')},
                'selected':selected,'diagnostics':report.get('_diagnostics',{})},ensure_ascii=False,indent=2))
        elif args.command in ('ingest','documents','revisions','deactivate','activate'):
            from app.rag import RAGSettings,DocumentStore,ingest_documents
            rag=RAGSettings();store=DocumentStore(rag.index_path,rag.database_url)
            if args.command=='ingest':result=ingest_documents(rag,rebuild=args.rebuild)
            elif args.command=='documents':result=store.documents()
            elif args.command=='revisions':result=store.revisions(args.document_id)
            elif args.command=='activate':
                from app.vectors import MilvusVectors
                vector=MilvusVectors(rag) if rag.vector_backend=='milvus' else None
                try:store.activate(args.document_id,args.revision,vector)
                finally:
                    if vector is not None:vector.close()
                result={'activated':args.document_id,'revision':args.revision}
            else:store.deactivate(args.document_id);result={'deactivated':args.document_id}
            print(json.dumps(result,ensure_ascii=False,indent=2))
        elif args.command=='token':print(issue_token(config.secret,args.tenant,args.user,args.ttl))
        elif args.command=='backup':
            if config.database_url:raise ValueError('PostgreSQL模式请使用 sh scripts/enterprise.sh backup，备份包含工作流检查点')
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
        import httpx
        import psycopg
        from psycopg_pool import PoolTimeout
        from pymilvus.exceptions import MilvusException
        if isinstance(error,(httpx.HTTPError,psycopg.Error,PoolTimeout,MilvusException)):
            parser.exit(2,'数据库、向量服务或模型连接失败；请检查服务状态及本机配置（凭证未输出）。\n')
        if not isinstance(error,(ValueError,FileExistsError,RAGError)):raise
        parser.exit(2,str(error)+'\n')

if __name__=='__main__':main()
