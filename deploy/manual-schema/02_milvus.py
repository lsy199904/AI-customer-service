"""Milvus SDK建集合参考，不调用应用初始化，不写入知识向量。
环境变量：MILVUS_URI、MILVUS_TOKEN、MILVUS_DATABASE、MILVUS_COLLECTION、MILVUS_INDEX_TYPE。
用法：python 02_milvus.py --collection 前缀_实际配置指纹前16位 --dimension 1024
必须使用与应用镜像匹配的pymilvus（当前锁定2.6.17）。
"""
import argparse
import os
import re


def main():
    parser=argparse.ArgumentParser(description='创建或核对SmartTITU知识向量集合，不创建云实例、不迁移数据')
    parser.add_argument('--collection',required=True,help='必须是App实际使用的完整集合名，不是前缀')
    parser.add_argument('--dimension',type=int,default=1024,help='必须与实际Embedding输出相同；BGE-M3为1024')
    args=parser.parse_args()
    prefix=os.environ.get('MILVUS_COLLECTION','')
    if not prefix or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,39}',prefix):
        parser.error('请配置与App一致的MILVUS_COLLECTION前缀')
    if not re.fullmatch(re.escape(prefix)+r'_[0-9a-f]{16}',args.collection):
        parser.error('完整集合名须为配置前缀+下划线+实际fingerprint前16位')
    if not os.environ.get('MILVUS_URI') or not os.environ.get('MILVUS_TOKEN'):
        parser.error('请注入MILVUS_URI和MILVUS_TOKEN，不在本文件填写密钥')
    if args.dimension<=0:parser.error('向量维度必须大于0')
    kind=os.getenv('MILVUS_INDEX_TYPE','HNSW')
    if kind not in ('HNSW','AUTOINDEX'):parser.error('索引只支持HNSW/AUTOINDEX')
    from pymilvus import MilvusClient,DataType
    client=MilvusClient(uri=os.environ['MILVUS_URI'],token=os.environ['MILVUS_TOKEN'],
                        db_name=os.getenv('MILVUS_DATABASE','default'),timeout=30)
    try:
        if client.has_collection(args.collection):
            fields=client.describe_collection(args.collection)['fields']
            by_name={f['name']:f for f in fields}
            if set(by_name)!={'id','document_id','revision','vector'}:
                raise ValueError('已有集合字段不一致，请停止核对，不覆盖')
            for name,size in (('id',80),('document_id',80),('revision',64)):
                field=by_name[name]
                if int(field['type'])!=int(DataType.VARCHAR) or int(field.get('params',{}).get('max_length',0))!=size:
                    raise ValueError('已有集合文本字段类型或长度不一致')
            if not by_name['id'].get('is_primary') or int(by_name['vector']['type'])!=int(DataType.FLOAT_VECTOR):
                raise ValueError('已有集合主键或向量类型不一致')
            if int(by_name['vector']['params']['dim'])!=args.dimension:
                raise ValueError('已有集合向量维度不一致')
            indexes=client.list_indexes(collection_name=args.collection)
            index=next((client.describe_index(collection_name=args.collection,index_name=name) for name in indexes
                        if client.describe_index(collection_name=args.collection,index_name=name).get('field_name')=='vector'),None)
            if not index or index.get('metric_type')!='COSINE' or index.get('index_type')!=kind:
                raise ValueError('已有集合索引与配置不一致；不自动修改')
            if kind=='HNSW' and (int(index.get('M',0))!=16 or int(index.get('efConstruction',0))!=128):
                raise ValueError('已有HNSW参数不一致；不自动修改')
            print('已有集合结构与索引核对通过，不清空、不重建：'+args.collection)
        else:
            schema=client.create_schema(auto_id=False,enable_dynamic_field=False)
            schema.add_field('id',DataType.VARCHAR,is_primary=True,max_length=80)
            schema.add_field('document_id',DataType.VARCHAR,max_length=80)
            schema.add_field('revision',DataType.VARCHAR,max_length=64)
            schema.add_field('vector',DataType.FLOAT_VECTOR,dim=args.dimension)
            index=client.prepare_index_params()
            options={'params':{'M':16,'efConstruction':128}} if kind=='HNSW' else {}
            index.add_index(field_name='vector',index_type=kind,metric_type='COSINE',**options)
            client.create_collection(collection_name=args.collection,schema=schema,index_params=index,consistency_level='Strong')
            print('空集合及索引创建完成：'+args.collection)
        client.load_collection(collection_name=args.collection)
        print('未调用模型、未写入知识数据；下一步仍需执行知识入库。')
    finally:client.close()


if __name__=='__main__':
    try:main()
    except Exception as error:
        # SDK异常可能包含连接凭证，交付脚本不直接打印底层错误。
        raise SystemExit('Milvus建集合/核对失败：'+type(error).__name__+'；请检查连接、权限、名称、维度及索引配置；未输出底层凭证信息。') from None
