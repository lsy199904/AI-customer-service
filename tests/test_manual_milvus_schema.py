"""Exercise the unchanged handoff SDK without connecting to Milvus."""
import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('manual_milvus', ROOT/'database/milvus/02_milvus.py')
manual = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manual)


class ManualMilvusTests(unittest.TestCase):
    def test_create_then_validate_and_reject_dimension_drift(self):
        for kind in ('HNSW', 'AUTOINDEX'):
            with self.subTest(kind=kind):
                state = {'fields': [], 'created': False, 'loads': 0}
                class Schema:
                    def add_field(self, name, dtype, **kw):
                        state['fields'].append(dict(name=name, type=dtype,
                            is_primary=kw.pop('is_primary', False), params=kw))
                class Index:
                    def add_index(self, **kw):
                        params = kw.pop('params', {})
                        state['index'] = {**kw, **params}
                class Client:
                    def __init__(self, **kw): state['connection'] = kw
                    def has_collection(self, *a): return state['created']
                    def create_schema(self, **kw): return Schema()
                    def prepare_index_params(self): return Index()
                    def create_collection(self, **kw): state['created'] = True
                    def load_collection(self, *a, **kw): state['loads'] += 1
                    def describe_collection(self, *a): return {'fields': state['fields']}
                    def list_indexes(self, **kw): return ['vector']
                    def describe_index(self, **kw): return state['index']
                    def close(self): pass
                env = dict(MILVUS_URI='https://milvus.example.com', MILVUS_TOKEN='test',
                           MILVUS_DATABASE='isolated', MILVUS_COLLECTION='unique', MILVUS_INDEX_TYPE=kind)
                with patch.dict(os.environ, env, clear=True), patch.dict(sys.modules,
                        {'pymilvus': types.SimpleNamespace(MilvusClient=Client,
                            DataType=types.SimpleNamespace(VARCHAR=1, FLOAT_VECTOR=2))}), \
                        patch.object(sys, 'argv', ['02_milvus.py', '--collection', 'unique_'+'a'*16]):
                    manual.main()
                    manual.main()
                    self.assertEqual(state['loads'], 2)
                    self.assertEqual(state['index']['metric_type'], 'COSINE')
                    self.assertEqual(state['connection']['db_name'], 'isolated')
                    state['fields'][-1]['params']['dim'] = 256
                    with self.assertRaises(ValueError): manual.main()
