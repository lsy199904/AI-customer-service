"""Offline coverage for manage.py vector-init (no Milvus service required)."""
import importlib.util
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pymilvus import DataType

_spec = importlib.util.spec_from_file_location('milvus_manage', ROOT / 'database/milvus/manage.py')
manage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(manage)


class FakeSchema:
    def __init__(self):
        self.fields = []
        self.kwargs = None

    def add_field(self, name, data_type, **kwargs):
        self.fields.append({'name': name, 'type': data_type, **kwargs})


class FakeIndexParams:
    def __init__(self):
        self.indexes = []

    def add_index(self, **kwargs):
        self.indexes.append(kwargs)


class FakeClient:
    def __init__(self, exists=False, dim=1024, index_type='HNSW'):
        self.exists = exists
        self.dim = dim
        self.index_type = index_type
        self.schema = FakeSchema()
        self.index_params = FakeIndexParams()
        self.created = None
        self.loaded = None

    def has_collection(self, collection):
        return self.exists

    def describe_collection(self, collection):
        return {'fields': [
            {'name': 'id', 'type': DataType.VARCHAR, 'params': {'max_length': 80}, 'is_primary': True},
            {'name': 'document_id', 'type': DataType.VARCHAR, 'params': {'max_length': 80}},
            {'name': 'revision', 'type': DataType.VARCHAR, 'params': {'max_length': 64}},
            {'name': 'vector', 'type': DataType.FLOAT_VECTOR, 'params': {'dim': self.dim}},
        ]}

    def list_indexes(self, collection_name):
        return ['vector_idx']

    def describe_index(self, collection_name, index_name):
        return {'field_name': 'vector', 'metric_type': 'COSINE',
                'index_type': self.index_type, 'M': 16, 'efConstruction': 128}

    def create_schema(self, **kwargs):
        self.schema.kwargs = kwargs
        return self.schema

    def prepare_index_params(self):
        return self.index_params

    def create_collection(self, **kwargs):
        self.created = kwargs

    def load_collection(self, collection_name):
        self.loaded = collection_name


class FakeRAG:
    vector_backend = 'milvus'
    milvus_token = 'test-token'
    milvus_index_type = 'HNSW'
    milvus_collection = 'smarttitu_knowledge'
    fingerprint = 'a' * 64


def vectors_for(client):
    class FakeVectors:
        def __init__(self, rag):
            self.collection = rag.milvus_collection + '_' + rag.fingerprint[:16]
            self.client = client
            self.closed = False

        def close(self):
            self.closed = True

    return FakeVectors


class VectorInitTests(unittest.TestCase):
    def test_creates_collection_with_app_schema(self):
        client = FakeClient(exists=False)
        with patch('app.vectors.MilvusVectors', vectors_for(client)):
            result = manage.vector_init(FakeRAG(), 1024)
        self.assertEqual(result['status'], 'created')
        self.assertFalse(result['data_written'])
        self.assertEqual(result['collection'], 'smarttitu_knowledge_' + 'a' * 16)
        self.assertEqual(client.schema.kwargs, {'auto_id': False, 'enable_dynamic_field': False})
        self.assertEqual([f['name'] for f in client.schema.fields],
                         ['id', 'document_id', 'revision', 'vector'])
        self.assertEqual(client.index_params.indexes[0]['metric_type'], 'COSINE')
        self.assertIsNotNone(client.created)
        self.assertEqual(client.loaded, result['collection'])

    def test_existing_collection_is_only_verified(self):
        client = FakeClient(exists=True)
        with patch('app.vectors.MilvusVectors', vectors_for(client)):
            result = manage.vector_init(FakeRAG(), 1024)
        self.assertEqual(result['status'], 'checked')
        self.assertIsNone(client.created)

    def test_dimension_mismatch_fails_without_changes(self):
        client = FakeClient(exists=True, dim=768)
        with patch('app.vectors.MilvusVectors', vectors_for(client)):
            with self.assertRaisesRegex(ValueError, '维度不一致'):
                manage.vector_init(FakeRAG(), 1024)
        self.assertIsNone(client.created)
        self.assertIsNone(client.loaded)

    def test_check_only_fails_when_collection_missing(self):
        client = FakeClient(exists=False)
        with patch('app.vectors.MilvusVectors', vectors_for(client)):
            with self.assertRaisesRegex(ValueError, '集合不存在'):
                manage.vector_init(FakeRAG(), 1024, check_only=True)
        self.assertIsNone(client.created)


if __name__ == '__main__':
    unittest.main()
