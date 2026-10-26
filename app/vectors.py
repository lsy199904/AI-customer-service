"""Milvus adapter with immutable revision filtering and cosine score semantics.

New vectors are staged before publishing relational metadata. Failed ingestion leaves
old revisions searchable; unpublished vectors cannot match the active revision filter.
"""
import json
import re
import threading

class MilvusVectors:
    def __init__(self,config,client=None):
        self.config=config;self._client=client;self.lock=threading.Lock()
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,39}',config.milvus_collection):raise ValueError('Milvus集合前缀无效')
        self.collection=config.milvus_collection+'_'+config.fingerprint[:16]

    @property
    def client(self):
        with self.lock:
            if self._client is None:
                from pymilvus import MilvusClient
                self._client=MilvusClient(uri=self.config.milvus_uri,token=self.config.milvus_token,timeout=15)
            return self._client

    def ensure(self,dimension):
        from pymilvus import DataType
        c=self.client
        if c.has_collection(self.collection):
            fields=c.describe_collection(self.collection)['fields']
            actual=next(int(f['params']['dim']) for f in fields if f['name']=='vector')
            if actual!=dimension:raise ValueError('Milvus维度与Embedding不一致，请修改模型版本并重建')
            return
        schema=c.create_schema(auto_id=False,enable_dynamic_field=False)
        schema.add_field('id',DataType.VARCHAR,is_primary=True,max_length=80)
        schema.add_field('document_id',DataType.VARCHAR,max_length=80)
        schema.add_field('revision',DataType.VARCHAR,max_length=64)
        schema.add_field('vector',DataType.FLOAT_VECTOR,dim=dimension)
        index=c.prepare_index_params();index.add_index(field_name='vector',index_type='HNSW',metric_type='COSINE',params={'M':16,'efConstruction':128})
        c.create_collection(collection_name=self.collection,schema=schema,index_params=index,consistency_level='Strong')

    def upsert(self,rows):
        if not rows:return 0
        self.ensure(len(rows[0][1]))
        for start in range(0,len(rows),128):
            data=[{'id':r['id'],'document_id':r['document_id'],'revision':r['revision'],'vector':v} for r,v in rows[start:start+128]]
            self.client.upsert(collection_name=self.collection,data=data,timeout=30)
        self.client.flush(collection_name=self.collection,timeout=30)
        return len(rows)

    @staticmethod
    def active_filter(records):
        pairs=sorted({(r['document_id'],r['revision']) for r in records})
        return ' or '.join('(document_id == '+json.dumps(d)+' and revision == '+json.dumps(v)+')' for d,v in pairs)

    def search(self,vector,records,limit):
        if not records:return {}
        if not self.client.has_collection(self.collection):raise ValueError('Milvus索引尚未同步，请执行sync-vectors')
        # Strong consistency + active revision filters prevents newly inserted/stale data leaking.
        result=self.client.search(collection_name=self.collection,data=[vector],limit=min(limit,len(records)),
            filter=self.active_filter(records),output_fields=['id'],
            search_params={'metric_type':'COSINE','params':{'ef':max(64,limit*2)}},consistency_level='Strong',timeout=15)
        allowed={r['id'] for r in records}
        return {hit['id']:float(hit['distance']) for hit in result[0] if hit['id'] in allowed}

    def close(self):
        if self._client is not None:self._client.close();self._client=None
