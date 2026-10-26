"""Offline, transactional SQLite -> PostgreSQL migration. Existing data is never overwritten.

Stop writers first. SQLite backup snapshots include WAL. Run after deploying dependencies,
then sync Milvus from the migrated vectors; the original SQLite files remain available.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from .storage import PostgresDB

TABLES={
 'assistant':{
  'sessions':['id','tenant','user','context','created','updated'],
  'messages':['id','session','request_id','role','content','payload','created'],
  'workflow_runs':['id','session','request_id','status','created','updated'],
 },
 'knowledge':{
  'rag_state':['id','fingerprint','generation'],
  'rag_documents':['id','path','title','current_revision','active','updated'],
  'rag_revisions':['document_id','revision','filename','raw','metadata','created'],
  'rag_chunks':['id','document_id','revision','ordinal','record','vector'],
  'rag_events':['id','document_id','action','revision','created'],
  'rag_embedding_cache':['fingerprint','text_hash','vector'],
 }}
KEYS={'rag_revisions':['document_id','revision'],'rag_embedding_cache':['fingerprint','text_hash']}

def migrate(config,source_chat,source_knowledge,backup_dir):
    if not config.database_url:raise ValueError('迁移需要DATABASE_URL；原SQLite不会被删除')
    from .core import Service
    from .rag import DocumentStore,RAGSettings
    # Initialize destination schemas without calling any external model.
    service=Service(config);service.close();rag=RAGSettings()
    DocumentStore(rag.index_path,config.database_url)
    backup=Path(backup_dir);backup.mkdir(parents=True,exist_ok=False,mode=0o700)
    snapshots={};connections=[]
    try:
        for schema,path in [('assistant',source_chat),('knowledge',source_knowledge)]:
            path=Path(path)
            if not path.is_file():raise ValueError('迁移来源不存在:'+str(path))
            source=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
            snapshot=backup/(schema+'.sqlite3');snapshot.touch(mode=0o600)
            target=sqlite3.connect(snapshot);target.row_factory=sqlite3.Row
            source.backup(target);source.close();target.execute('PRAGMA foreign_keys=ON')
            if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('来源SQLite校验失败')
            snapshots[schema]=target;connections.append(target)
        destination=PostgresDB(config.database_url,'assistant',max_size=2);counts={}
        try:
            with destination:
                # One PostgreSQL transaction covers both schemas. No partially migrated history.
                for schema,tables in TABLES.items():
                    old=snapshots[schema]
                    existing={r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    for table,columns in tables.items():
                        if table not in existing:continue
                        names=','.join('"'+c+'"' for c in columns)
                        extra=',rowid AS _seq' if table=='messages' else ''
                        rows=old.execute('SELECT '+names+extra+' FROM '+table+(' ORDER BY rowid' if table=='messages' else '')).fetchall()
                        for row in rows:
                            keys=KEYS.get(table,['id']);where=' AND '.join('"'+k+'"=?' for k in keys)
                            current=destination.execute('SELECT '+names+' FROM '+schema+'.'+table+' WHERE '+where,tuple(row[k] for k in keys)).fetchone()
                            if current is not None:
                                if table=='rag_state' and not current['fingerprint'] and current['generation']==0:
                                    destination.execute('UPDATE knowledge.rag_state SET fingerprint=?,generation=? WHERE id=1',(row['fingerprint'],row['generation']));continue
                                if any(current[k]!=row[k] for k in columns):raise ValueError('目标已有不同数据，已回滚本次迁移:'+schema+'.'+table)
                                continue
                            used=columns+(['seq'] if table=='messages' else [])
                            values=[row[k] for k in columns]+([row['_seq']] if table=='messages' else [])
                            destination.execute('INSERT INTO '+schema+'.'+table+'('+','.join('"'+c+'"' for c in used)+') VALUES('+','.join('?' for _ in used)+')',values)
                        counts[schema+'.'+table]=len(rows)
                for table,column in [('assistant.messages','seq'),('knowledge.rag_events','id')]:
                    # Fixed internal identifiers; set the sequence after preserving legacy ordering.
                    destination.execute("SELECT setval(pg_get_serial_sequence('"+table+"','"+column+"'),GREATEST(COALESCE((SELECT MAX("+column+") FROM "+table+"),0),1),EXISTS(SELECT 1 FROM "+table+"))")
        finally:destination.close()
        (backup/'migration.json').write_text(json.dumps({'counts':counts,'created':time.time()},indent=2))
        return {'migration':'complete','counts':counts,'sqlite_backups':str(backup),'next_step':'sync-vectors，然后核对check与doctor，再启动服务'}
    finally:
        for connection in connections:connection.close()


def export_sqlite(config,directory):
    """Stopped-service rollback export. New files only; never overwrite original SQLite.

    Chat history and versioned knowledge survive post-cutover writes. In-flight graph
    checkpoints are not portable; finish/drain requests before calling this command.
    """
    if not config.database_url:raise ValueError('当前并非PostgreSQL模式')
    from dataclasses import replace
    from .core import Service
    from .rag import DocumentStore
    output=Path(directory);output.mkdir(parents=True,exist_ok=False,mode=0o700)
    chat=output/'assistant.db';knowledge=output/'rag.sqlite3'
    chat.touch(mode=0o600);knowledge.touch(mode=0o600)
    # The relational schema initialization does not perform inference or modify sources.
    service=Service(replace(config,database_url='',db=str(chat),mode='extractive',retrieval_backend='lexical'));service.close()
    DocumentStore(knowledge,database_url='')
    destination={key:sqlite3.connect(path) for key,path in [('assistant',chat),('knowledge',knowledge)]}
    source=PostgresDB(config.database_url,'assistant',max_size=2);counts={}
    try:
        with source:
            source.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            for schema,tables in TABLES.items():
                db=destination[schema]
                for table,columns in tables.items():
                    names=','.join('"'+c+'"' for c in columns)
                    rows=source.execute('SELECT '+names+' FROM '+schema+'.'+table+(' ORDER BY seq' if table=='messages' else '')).fetchall()
                    db.execute('DELETE FROM '+table)
                    db.executemany('INSERT INTO '+table+'('+names+') VALUES('+','.join('?' for _ in columns)+')',[tuple(row[k] for k in columns) for row in rows])
                    counts[schema+'.'+table]=len(rows)
                db.commit()
                if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('导出完整性检查失败，请保留PostgreSQL继续排查')
        (output/'export.json').write_text(json.dumps({'counts':counts,'created':time.time()},indent=2))
        return {'export':'complete','directory':str(output),'counts':counts,'checkpoint_note':'仅迁移完成的聊天及知识；切换前须停止流量并等待在途请求结束'}
    finally:
        source.close()
        for db in destination.values():db.close()
