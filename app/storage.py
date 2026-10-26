"""Relational persistence with a SQLite compatibility adapter and pooled PostgreSQL.

Only internal, parameterized SQL reaches this adapter. Customer text is never SQL.
PostgreSQL uses separate schemas for conversations and knowledge metadata.
"""
from contextlib import contextmanager,nullcontext
import hashlib
import re
import sqlite3
import threading


class BusySession(Exception):
    pass


class Row(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class Result:
    def __init__(self, rows=(), rowcount=0):
        self.rows=list(rows);self.rowcount=rowcount
    def fetchone(self):
        return self.rows.pop(0) if self.rows else None
    def fetchall(self):
        rows=self.rows;self.rows=[];return rows
    def __iter__(self):return iter(self.rows)


def postgres_sql(sql):
    def identifiers(part):
        part=re.sub(r'(?<!")\buser\b(?!")','"user"',part,flags=re.I)
        part=re.sub(r'(?<!")\bwindow\b(?!")','"window"',part,flags=re.I)
        part=re.sub(r'\browid\b','seq',part,flags=re.I)
        part=re.sub(r'\bBLOB\b','BYTEA',part,flags=re.I)
        part=re.sub(r'\bREAL\b','DOUBLE PRECISION',part,flags=re.I)
        return part.replace('id INTEGER PRIMARY KEY,document_id','id BIGSERIAL PRIMARY KEY,document_id')
    # Preserve SQL string literals such as role='user'; only identifiers are translated.
    parts=re.split(r"('(?:[^']|'')*')",sql)
    sql=''.join(part if i%2 else identifiers(part) for i,part in enumerate(parts))
    if re.match(r'\s*INSERT OR IGNORE',sql,re.I):
        sql=re.sub(r'INSERT OR IGNORE','INSERT',sql,flags=re.I)+' ON CONFLICT DO NOTHING'
    return sql.replace('?','%s')


class PostgresDB:
    """A connection is borrowed only for a query or transaction, never shared by threads."""
    dialect='postgres'
    def __init__(self,url,schema,max_size=40):
        from psycopg_pool import ConnectionPool
        from psycopg.rows import dict_row
        if schema not in ('assistant','knowledge'):raise ValueError('Invalid database schema')
        self.schema=schema;self.local=threading.local()
        self.pool=ConnectionPool(url,min_size=1,max_size=max_size,timeout=10,
            kwargs={'autocommit':True,'row_factory':dict_row,'connect_timeout':10},open=True)
        try:self.pool.wait(timeout=15)
        except Exception:
            self.pool.close();raise
        with self.pool.connection() as c:
            key=int.from_bytes(hashlib.sha256(('schema:'+schema).encode()).digest()[:8],'big',signed=True)
            c.execute('SELECT pg_advisory_lock(%s)',(key,))
            try:c.execute('CREATE SCHEMA IF NOT EXISTS '+schema)
            finally:c.execute('SELECT pg_advisory_unlock(%s)',(key,))
        def configure(c):
            c.execute('SET search_path TO '+schema+', public')
            c.execute("SET statement_timeout TO '15000ms'")
            c.execute("SET lock_timeout TO '5000ms'")
        # Configure every borrowed connection; no reliance on persistent search_path.
        self.configure=configure

    @contextmanager
    def connection(self):
        with self.pool.connection() as c:
            self.configure(c)
            yield c

    def execute(self,sql,params=()):
        # SQLite PRAGMAs and explicit BEGIN are supplied by the legacy schema layer.
        if sql.strip().upper().startswith(('PRAGMA ','BEGIN')):return Result()
        def run(c):
            cur=c.execute(postgres_sql(sql),params)
            rows=[Row(r) for r in cur.fetchall()] if cur.description else []
            return Result(rows,cur.rowcount)
        c=getattr(self.local,'connection',None)
        if c is not None:return run(c)
        with self.connection() as c:return run(c)

    def executescript(self,script):
        with (nullcontext() if getattr(self.local,'connection',None) is not None else self):
            for sql in script.split(';'):
                if sql.strip():self.execute(sql)

    def __enter__(self):
        if getattr(self.local,'connection',None) is not None:raise RuntimeError('Nested transaction')
        cm=self.connection();c=cm.__enter__();tx=c.transaction();tx.__enter__()
        self.local.connection=c;self.local.context=(cm,tx)
        return self
    def __exit__(self,*exc):
        cm,tx=self.local.context
        try:return tx.__exit__(*exc)
        finally:
            self.local.connection=None;self.local.context=None;cm.__exit__(*exc)
    def close(self):self.pool.close()

    @contextmanager
    def schema_lock(self):
        key=int.from_bytes(hashlib.sha256(('ddl:'+self.schema).encode()).digest()[:8],'big',signed=True)
        with self.connection() as c:
            c.execute('SELECT pg_advisory_lock(%s)',(key,))
            try:yield
            finally:c.execute('SELECT pg_advisory_unlock(%s)',(key,))

    @contextmanager
    def session_lock(self,sid):
        key=int.from_bytes(hashlib.sha256(('chat:'+sid).encode()).digest()[:8],'big',signed=True)
        with self.connection() as c:
            if not c.execute('SELECT pg_try_advisory_lock(%s)',(key,)).fetchone()['pg_try_advisory_lock']:
                raise BusySession()
            try:yield
            finally:c.execute('SELECT pg_advisory_unlock(%s)',(key,))


def open_database(path,url='',schema='assistant'):
    if url:return PostgresDB(url,schema)
    db=sqlite3.connect(str(path),check_same_thread=False,timeout=30)
    db.row_factory=sqlite3.Row
    return db


@contextmanager
def document_connection(path,url=''):
    if url:
        # Reuse a bounded process-local pool for each URL/schema.
        with _pool_lock:
            if url not in _knowledge_pools:_knowledge_pools[url]=PostgresDB(url,'knowledge',max_size=12)
            db=_knowledge_pools[url]
        with db:yield db
    else:
        db=sqlite3.connect(str(path),timeout=30);db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()


_pool_lock=threading.Lock()
_knowledge_pools={}

def close_knowledge_pools():
    with _pool_lock:
        for pool in _knowledge_pools.values():pool.close()
        _knowledge_pools.clear()
