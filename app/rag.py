"""Versioned RAG metadata in PostgreSQL/SQLite; indexed Milvus or local cosine search."""
from dataclasses import dataclass,field
from pathlib import Path
import hashlib
from contextlib import contextmanager
import ipaddress
import json
import math
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from .ingestion import PIPELINE_VERSION,SUPPORTED,parse_document
from .retrieval import TEXT_VERSION,retrieval_text,fuse

BASE=Path(__file__).resolve().parent.parent

class RAGError(Exception):pass

@dataclass
class RAGSettings:
    database_url: str=field(default_factory=lambda:os.getenv('DATABASE_URL',''))
    vector_backend: str=field(default_factory=lambda:os.getenv('VECTOR_BACKEND','sqlite'))
    milvus_uri: str=field(default_factory=lambda:os.getenv('MILVUS_URI','http://127.0.0.1:19530'))
    milvus_token: str=field(default_factory=lambda:os.getenv('MILVUS_TOKEN',''))
    milvus_collection: str=field(default_factory=lambda:os.getenv('MILVUS_COLLECTION','smarttitu_knowledge'))
    index_path: str=field(default_factory=lambda:os.getenv('RAG_INDEX_PATH',str(BASE/'var/rag.sqlite3')))
    source_dir: str=field(default_factory=lambda:os.getenv('KNOWLEDGE_SOURCE_DIR',str(BASE/'knowledge_sources')))
    embedding_url: str=field(default_factory=lambda:os.getenv('EMBEDDING_URL','http://127.0.0.1:11434/api/embed'))
    embedding_provider: str=field(default_factory=lambda:os.getenv('EMBEDDING_PROVIDER','ollama'))
    embedding_model: str=field(default_factory=lambda:os.getenv('EMBEDDING_MODEL','bge-m3:latest'))
    embedding_revision: str=field(default_factory=lambda:os.getenv('EMBEDDING_REVISION','v1'))
    embedding_key: str=field(default_factory=lambda:os.getenv('EMBEDDING_API_KEY',''))
    rerank_url: str=field(default_factory=lambda:os.getenv('RERANK_URL',''))
    rerank_model: str=field(default_factory=lambda:os.getenv('RERANK_MODEL','Qwen3-Reranker-4B'))
    rerank_key: str=field(default_factory=lambda:os.getenv('RERANK_API_KEY',''))
    rerank_enabled: bool=field(default_factory=lambda:os.getenv('RERANK_ENABLED','true').lower()=='true')
    http_origins: tuple=field(default_factory=lambda:tuple(v.strip().rstrip('/') for v in os.getenv('MODEL_HTTP_ORIGINS','').split(',') if v.strip()))
    min_similarity: float=field(default_factory=lambda:float(os.getenv('SEMANTIC_MIN_SIMILARITY','0.45')))
    rerank_min_score: float=field(default_factory=lambda:float(os.getenv('RERANK_MIN_SCORE','0')))
    top_k: int=field(default_factory=lambda:int(os.getenv('RAG_TOP_K','12')))
    context_k: int=field(default_factory=lambda:int(os.getenv('RAG_CONTEXT_K','3')))
    embedding_timeout: float=field(default_factory=lambda:float(os.getenv('EMBEDDING_TIMEOUT','30')))
    rerank_timeout: float=field(default_factory=lambda:float(os.getenv('RERANK_TIMEOUT','30')))
    chunk_chars: int=1000
    overlap_chars: int=100

    def validate(self):
        if not all(math.isfinite(v) and 1<=v<=120 for v in (self.embedding_timeout,self.rerank_timeout)):raise ValueError('模型超时须为1至120秒')
        if self.vector_backend not in ('sqlite','milvus'):raise ValueError('VECTOR_BACKEND仅支持sqlite/milvus')
        if self.vector_backend=='milvus' and not self.milvus_token:raise ValueError('Milvus部署必须设置MILVUS_TOKEN')
        if self.embedding_provider not in ('ollama','openai'):raise ValueError('EMBEDDING_PROVIDER仅支持ollama/openai')
        if not self.embedding_model:raise ValueError('请设置EMBEDDING_MODEL')
        if not -1<=self.min_similarity<=1 or not math.isfinite(self.rerank_min_score):raise ValueError('语义或重排门槛无效')
        if not 1<=self.context_k<=self.top_k<=100:raise ValueError('RAG_CONTEXT_K必须不大于RAG_TOP_K,上限100')
        validate_endpoint(self.embedding_url,self.http_origins)
        if self.rerank_enabled:
            if not self.rerank_url:raise ValueError('请设置RERANK_URL,或显式设置RERANK_ENABLED=false')
            validate_endpoint(self.rerank_url,self.http_origins)

    @property
    def fingerprint(self):
        data=[PIPELINE_VERSION,TEXT_VERSION,self.embedding_provider,self.embedding_url,self.embedding_model,self.embedding_revision,self.chunk_chars,self.overlap_chars]
        return hashlib.sha256(json.dumps(data).encode()).hexdigest()


def validate_endpoint(url,allowed):
    p=urllib.parse.urlsplit(url)
    if not p.hostname or p.username or p.password or p.fragment:raise ValueError('模型接口地址无效')
    if p.scheme=='https':return
    try:private=ipaddress.ip_address(p.hostname).is_private
    except ValueError:private=p.hostname in ('localhost','host.docker.internal') or '.' not in p.hostname
    if p.scheme!='http' or not private or p.scheme+'://'+p.netloc not in allowed:
        raise ValueError('HTTP接口必须是MODEL_HTTP_ORIGINS中显式允许的内网来源')


def post_json(url,payload,key,timeout=60):
    from .transport import post_json as request_json
    try:return request_json(url,payload,key,timeout)
    except Exception as error:
        import httpx
        if isinstance(error,httpx.HTTPStatusError):raise RAGError('模型接口返回HTTP '+str(error.response.status_code)) from None
        raise RAGError('模型接口连接或JSON响应异常') from None


def normalized_vector(values):
    if not isinstance(values,list) or not values or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):
        raise RAGError('Embedding返回无效向量')
    norm=math.sqrt(sum(v*v for v in values))
    if norm==0 or not math.isfinite(norm):raise RAGError('Embedding返回零向量或数值溢出')
    return [v/norm for v in values]

class EmbeddingClient:
    def __init__(self,config):self.config=config
    def embed(self,texts):
        c=self.config
        payload={'model':c.embedding_model,'input':texts}
        if c.embedding_provider=='ollama':payload['truncate']=False
        data=post_json(c.embedding_url,payload,c.embedding_key,timeout=c.embedding_timeout)
        if c.embedding_provider=='ollama':values=data.get('embeddings')
        else:
            items=data.get('data',[])
            if not isinstance(items,list) or {x.get('index') for x in items}!={*range(len(texts))}:raise RAGError('Embedding响应索引无效')
            values=[x['embedding'] for x in sorted(items,key=lambda r:r['index'])]
        if not isinstance(values,list) or len(values)!=len(texts):raise RAGError('Embedding返回数量不匹配')
        vectors=[normalized_vector(v) for v in values]
        if len({len(v) for v in vectors})!=1:raise RAGError('Embedding维度不一致')
        return vectors

class RerankerClient:
    def __init__(self,config):self.config=config
    def rank(self,question,documents):
        c=self.config
        data=post_json(c.rerank_url,{'model':c.rerank_model,'query':question,'documents':documents,'top_n':len(documents)},c.rerank_key,timeout=c.rerank_timeout)
        results=data.get('results');seen=set();ranked=[]
        if not isinstance(results,list):raise RAGError('Reranker没有返回results数组')
        for row in results:
            index=row.get('index');score=row.get('relevance_score')
            if isinstance(index,bool) or not isinstance(index,int) or not 0<=index<len(documents) or index in seen:raise RAGError('Reranker返回无效或重复索引')
            if isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score):raise RAGError('Reranker评分无效')
            seen.add(index);ranked.append((index,float(score)))
        if len(seen)!=len(documents):raise RAGError('Reranker未返回全部候选,请核对接口')
        return sorted(ranked,key=lambda r:r[1],reverse=True)

SCHEMA='''
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS rag_state(id INTEGER PRIMARY KEY CHECK(id=1),fingerprint TEXT,generation INTEGER NOT NULL);
INSERT OR IGNORE INTO rag_state VALUES(1,'',0);
CREATE TABLE IF NOT EXISTS rag_documents(id TEXT PRIMARY KEY,path TEXT UNIQUE,title TEXT,current_revision TEXT,active INTEGER,updated REAL);
CREATE TABLE IF NOT EXISTS rag_revisions(document_id TEXT,revision TEXT,filename TEXT,raw BLOB,metadata TEXT,created REAL,PRIMARY KEY(document_id,revision));
CREATE TABLE IF NOT EXISTS rag_chunks(id TEXT PRIMARY KEY,document_id TEXT,revision TEXT,ordinal INTEGER,record TEXT,vector TEXT);
CREATE INDEX IF NOT EXISTS rag_chunk_doc ON rag_chunks(document_id,revision);
CREATE TABLE IF NOT EXISTS rag_events(id INTEGER PRIMARY KEY,document_id TEXT,action TEXT,revision TEXT,created REAL);
CREATE TABLE IF NOT EXISTS rag_embedding_cache(fingerprint TEXT,text_hash TEXT,vector TEXT,PRIMARY KEY(fingerprint,text_hash));
'''

class DocumentStore:
    def __init__(self,path,database_url=None):
        self.path=str(path);self.database_url=os.getenv('DATABASE_URL','') if database_url is None else database_url
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            if self.database_url:db.execute('SELECT pg_advisory_xact_lock(?)',(729630043,))
            db.executescript(SCHEMA)
    @contextmanager
    def connect(self):
        from .storage import document_connection
        with document_connection(self.path,self.database_url) as db:yield db
    def documents(self):
        with self.connect() as db:return [dict(r) for r in db.execute('SELECT * FROM rag_documents ORDER BY path')]
    def revisions(self,document_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT document_id,revision,filename,metadata,created FROM rag_revisions WHERE document_id=? ORDER BY created DESC',(document_id,))]
    def get(self,key):
        with self.connect() as db:
            row=db.execute('SELECT record FROM rag_chunks WHERE id=?',(key,)).fetchone()
            return json.loads(row['record']) if row else None
    def download(self,document_id,revision):
        with self.connect() as db:
            row=db.execute('SELECT filename,raw FROM rag_revisions WHERE document_id=? AND revision=?',(document_id,revision)).fetchone()
            return (row['filename'],bytes(row['raw'])) if row else None
    def deactivate(self,document_id):
        with self.connect() as db:
            row=db.execute('SELECT * FROM rag_documents WHERE id=?',(document_id,)).fetchone()
            if not row:raise ValueError('文档ID不存在')
            db.execute('UPDATE rag_documents SET active=0,updated=? WHERE id=?',(time.time(),document_id))
            db.execute('UPDATE rag_state SET generation=generation+1 WHERE id=1')
            db.execute('INSERT INTO rag_events(document_id,action,revision,created) VALUES(?,?,?,?)',(document_id,'deactivate',row['current_revision'],time.time()))
    def activate(self,document_id,revision,vector_index=None):
        with self.connect() as db:
            row=db.execute('SELECT metadata FROM rag_revisions WHERE document_id=? AND revision=?',(document_id,revision)).fetchone()
            if not row:raise ValueError('文档修订不存在')
            fingerprint=db.execute('SELECT fingerprint FROM rag_state WHERE id=1').fetchone()[0]
            if json.loads(row['metadata'])['fingerprint']!=fingerprint:raise ValueError('旧修订使用不同Embedding配置,不能混用向量,请恢复原文件后重建')
            if vector_index is not None:
                if vector_index.config.fingerprint!=fingerprint:raise ValueError('激活版本与当前Embedding配置不一致')
                chunks=db.execute('SELECT record,vector FROM rag_chunks WHERE document_id=? AND revision=?',(document_id,revision)).fetchall()
                vector_index.upsert([(json.loads(r['record']),json.loads(r['vector'])) for r in chunks])
            db.execute('UPDATE rag_documents SET current_revision=?,active=1,updated=? WHERE id=?',(revision,time.time(),document_id))
            db.execute('UPDATE rag_state SET generation=generation+1 WHERE id=1')
            db.execute('INSERT INTO rag_events(document_id,action,revision,created) VALUES(?,?,?,?)',(document_id,'activate',revision,time.time()))
    def snapshot(self,include_vectors=True):
        with self.connect() as db:
            db.execute('BEGIN')
            if self.database_url:db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            state=dict(db.execute('SELECT * FROM rag_state WHERE id=1').fetchone())
            columns='c.record,c.vector' if include_vectors else 'c.record'
            rows=db.execute('SELECT '+columns+' FROM rag_chunks c JOIN rag_documents d ON d.id=c.document_id AND d.current_revision=c.revision WHERE d.active=1').fetchall()
            return state,[(json.loads(r['record']),json.loads(r['vector']) if include_vectors else None) for r in rows]


def ingest_documents(config,rebuild=False,embedder=None):
    config.validate();store=DocumentStore(config.index_path,config.database_url);embedder=embedder or EmbeddingClient(config)
    root=Path(config.source_dir)
    if root.is_symlink():raise ValueError('来源根目录不接受符号链接')
    if not root.is_dir():raise ValueError('文档目录不存在:'+str(root))
    files=sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in SUPPORTED and not p.name.startswith('~$'))
    if not files:raise ValueError('没有找到可入库文档,现有索引不会被删除')
    state,_=store.snapshot();existing={d['path']:d for d in store.documents()}
    if state['fingerprint'] and state['fingerprint']!=config.fingerprint and not rebuild:
        raise ValueError('Embedding模型或切分配置已变化,请执行ingest --rebuild')
    file_paths={p.relative_to(root).as_posix() for p in files}
    if rebuild and any(d['active'] and path not in file_paths for path,d in existing.items()):
        raise ValueError('全量重建前请补回缺失的活动文档,或显式停用缺失文档')
    staged=[];unchanged=0;inactive=0;dimensions=set()
    for path in files:
        relative=path.relative_to(root).as_posix()
        old=existing.get(relative)
        if old and not old['active']:
            inactive+=1;continue
        if any(p.is_symlink() for p in [path,*list(path.parents)[:len(path.relative_to(root).parts)-1]]):raise ValueError('不接受符号链接来源:'+relative)
        parsed=parse_document(path,config.chunk_chars,config.overlap_chars)
        required_images={key for chunk in parsed.chunks for key in chunk.get('image_ids',[])}
        if required_images:
            from .conversation import MediaCatalog
            catalog=MediaCatalog(os.getenv('MEDIA_PATH',str(BASE/'data/media.json')),BASE/'app/static/media')
            if required_images-catalog.rows.keys():
                raise ValueError('文档配图ID未在data/media.json登记:'+','.join(sorted(required_images-catalog.rows.keys())))
        revision=hashlib.sha256((parsed.sha256+config.fingerprint).encode()).hexdigest()
        old=existing.get(relative)
        if old and old['active'] and old['current_revision']==revision and not rebuild:
            unchanged+=1;continue
        document_id=old['id'] if old else 'DOC-'+hashlib.sha256(relative.encode()).hexdigest()[:20]
        records=[];texts=[]
        for number,chunk in enumerate(parsed.chunks):
            chunk_id='KB-'+hashlib.sha256((document_id+revision+str(number)).encode()).hexdigest()[:24]
            record={**chunk,'id':chunk_id,'document_id':document_id,'revision':revision,'source_file':parsed.filename,
                    'version':parsed.version,'product':'SmartTITU','audience':'customer','status':'source_based',
                    'download_url':'/v1/documents/'+document_id+'/revisions/'+revision+'/download'}
            records.append(record);texts.append(retrieval_text(record))
        vectors=[None]*len(texts);missing=[]
        with store.connect() as db:
            for number,text in enumerate(texts):
                row=db.execute('SELECT vector FROM rag_embedding_cache WHERE fingerprint=? AND text_hash=?',(config.fingerprint,hashlib.sha256(text.encode()).hexdigest())).fetchone()
                if row:vectors[number]=json.loads(row['vector'])
                else:missing.append(number)
        for start in range(0,len(missing),8):
            batch=missing[start:start+8];fresh=embedder.embed([texts[i] for i in batch])
            if len(fresh)!=len(batch):raise RAGError('Embedding数量不匹配')
            with store.connect() as db:
                for number,vector in zip(batch,fresh):
                    vector=normalized_vector(vector);vectors[number]=vector
                    db.execute('INSERT INTO rag_embedding_cache VALUES(?,?,?) ON CONFLICT(fingerprint,text_hash) DO UPDATE SET vector=excluded.vector',(config.fingerprint,hashlib.sha256(texts[number].encode()).hexdigest(),json.dumps(vector)))
        dimensions.update(len(v) for v in vectors)
        staged.append((document_id,relative,revision,parsed,records,vectors))
    if len(dimensions)>1:raise RAGError('本次文档向量维度不一致,未发布新版本')
    if not staged:return {'updated':0,'unchanged':unchanged,'inactive_skipped':inactive,'chunks':0,'documents':store.documents()}
    if not rebuild:
        _,old_chunks=store.snapshot()
        if old_chunks:dimensions.update(len(v) for _,v in old_chunks)
        if len(dimensions)>1:raise RAGError('向量维度与既有索引不同,请更换EMBEDDING_REVISION并全量重建')
    # Publish staged vectors before the relational revision pointer. Until the pointer
    # commits, Milvus active filters continue selecting the previous revision.
    if config.vector_backend=='milvus':
        from .vectors import MilvusVectors
        index=MilvusVectors(config)
        try:index.upsert([(r,v) for _,_,_,_,records,vectors in staged for r,v in zip(records,vectors)])
        finally:index.close()
    # All extraction and external inference succeeded before publishing any current revision.
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        generation=db.execute('SELECT generation FROM rag_state WHERE id=1'+(' FOR UPDATE' if config.database_url else '')).fetchone()[0]
        if generation!=state['generation']:raise RAGError('入库期间索引被其他命令更新,本次未发布,请重试')
        for doc_id,path,revision,parsed,records,vectors in staged:
            metadata=json.dumps({'sha256':parsed.sha256,'fingerprint':config.fingerprint,'version':parsed.version,'chunks':len(records),'title':parsed.title},ensure_ascii=False)
            db.execute('INSERT OR IGNORE INTO rag_revisions VALUES(?,?,?,?,?,?)',(doc_id,revision,parsed.filename,parsed.raw,metadata,time.time()))
            for number,(record,vector) in enumerate(zip(records,vectors)):
                db.execute('INSERT OR IGNORE INTO rag_chunks VALUES(?,?,?,?,?,?)',(record['id'],doc_id,revision,number,json.dumps(record,ensure_ascii=False),json.dumps(vector)))
            db.execute('INSERT INTO rag_documents VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET path=excluded.path,title=excluded.title,current_revision=excluded.current_revision,active=1,updated=excluded.updated',(doc_id,path,parsed.title,revision,1,time.time()))
            db.execute('INSERT INTO rag_events(document_id,action,revision,created) VALUES(?,?,?,?)',(doc_id,'rebuild' if rebuild else 'upsert',revision,time.time()))
        db.execute('UPDATE rag_state SET fingerprint=?,generation=generation+1 WHERE id=1',(config.fingerprint,))
    return {'updated':len(staged),'unchanged':unchanged,'inactive_skipped':inactive,'chunks':sum(len(x[4]) for x in staged),'documents':store.documents()}

class SemanticKnowledge:
    def __init__(self,config,embedder=None,reranker=None):
        config.validate();self.config=config;self.store=DocumentStore(config.index_path,config.database_url)
        self.embedder=embedder or EmbeddingClient(config);self.reranker=reranker or RerankerClient(config)
        self.vectors=None
        if config.vector_backend=='milvus':
            from .vectors import MilvusVectors
            self.vectors=MilvusVectors(config)
    @property
    def rows(self):return {r['id']:r for r,_ in self.store.snapshot(include_vectors=False)[1]}
    def get(self,key):return self.store.get(key)
    def assess(self,question,diagnostics=False):
        c=self.config;state,rows=self.store.snapshot(include_vectors=self.vectors is None)
        report={'matched':False,'hits':[],'method':'hybrid_rrf_rerank' if c.rerank_enabled else 'hybrid_rrf',
                'threshold':c.min_similarity,'similarity':None,'generation':state['generation']}
        if not rows:report['reason']='index_empty';return report
        if state['fingerprint']!=c.fingerprint:raise RAGError('当前Embedding配置与索引不一致,请先重建')
        query=normalized_vector(self.embedder.embed([question])[0])
        if self.vectors is None:
            if any(len(vector)!=len(query) for _,vector in rows):raise RAGError('查询向量与索引维度不同,请重建')
            ranked=sorted([(sum(a*b for a,b in zip(query,vector)),record) for record,vector in rows],key=lambda x:x[0],reverse=True)
        else:
            scores=self.vectors.search(query,[r for r,_ in rows],c.top_k)
            ranked=sorted([(scores.get(record['id'],-1.0),record) for record,_ in rows],key=lambda x:x[0],reverse=True)
        report['similarity']=round(ranked[0][0],4)
        candidates=fuse(question,ranked,c.min_similarity,c.top_k)
        if diagnostics:
            report['_diagnostics']={'dense_top':[{'id':r['id'],'title':r['title'],'score':round(score,6)} for score,r in ranked[:c.top_k]],
                'candidates':[{'id':s['row']['id'],'title':s['row']['title'],'dense':round(s['dense'],6),
                               'bm25':round(s['lexical'],6),'rrf':round(s['rrf'],6),'title_match':s['title_match']} for s in candidates]}
        if not candidates:report['reason']='no_candidates';return report
        if c.rerank_enabled:
            order=self.reranker.rank(question,[retrieval_text(s['row']) for s in candidates])
            ranked_candidates=[{**candidates[index],'score':score} for index,score in order]
            eligible=[s for s in ranked_candidates if s['score']>=c.rerank_min_score]
        else:
            ranked_candidates=[{**s,'score':s['rrf']} for s in candidates]
            eligible=ranked_candidates
        # A complete chapter-title request should not be replaced by related feature sections.
        # Semantic and lexical candidates still compete normally for all other questions.
        anchors=[s for s in eligible if s['title_match']]
        final=(anchors or eligible)[:c.context_k]
        report['title_matched']=bool(anchors)
        report['hits']=[(s['score'],{**s['row'],'_similarity':round(s['dense'],4),
                         '_rerank_score':s['score'] if c.rerank_enabled else None,
                         '_title_match':s['title_match']},s['dense']) for s in final]
        report['matched']=bool(report['hits'])
        if diagnostics:report['_diagnostics']['reranked']=[{'id':s['row']['id'],'title':s['row']['title'],
            'score':s['score'],'title_match':s['title_match'],'selected':s in final} for s in ranked_candidates]
        return report


def sync_vectors(config):
    """Reuse existing embeddings when moving from SQLite to Milvus; no model calls."""
    config.validate()
    if config.vector_backend!='milvus':raise ValueError('sync-vectors需要VECTOR_BACKEND=milvus')
    from .vectors import MilvusVectors
    state,rows=DocumentStore(config.index_path,config.database_url).snapshot()
    if state['fingerprint']!=config.fingerprint:raise ValueError('Embedding配置与已有索引不一致，请先重建')
    index=MilvusVectors(config)
    try:count=index.upsert(rows)
    finally:index.close()
    return {'synced_vectors':count,'collection':index.collection,'embedding_calls':0}
