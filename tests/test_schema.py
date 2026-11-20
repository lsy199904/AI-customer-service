"""Schema checks must fail before writes and work with raw and adapter rows."""
import unittest
from app.schema import SchemaNotReady, require_postgres_schema, require_checkpoint_schema


class Result:
    def __init__(self, row): self.row = row
    def fetchone(self): return self.row


class Database:
    def __init__(self, rows): self.rows = iter(rows); self.queries = []
    def execute(self, sql):
        self.queries.append(sql)
        if not sql.startswith('SELECT '): raise AssertionError('Schema checks must be read-only')
        return Result(next(self.rows))


class SchemaTests(unittest.TestCase):
    def test_compatible_tuple_and_dict_rows(self):
        for rows in [ [('history',), (0,), ('1.0.0',), (9,)],
                      [{'t': 'history'}, {'n': 0}, {'version': '1.0.0'}, {'v': 9}],
                      [('history',), (0,), ('1.1.0',), (10,)]]:
            db = Database(rows)
            require_postgres_schema(db)
            self.assertEqual(len(db.queries), 4)

    def test_unready_versions_fail_read_only(self):
        for rows in [[(None,)], [('history',), (1,)],
                     [('history',), (0,), None],
                     [('history',), (0,), ('0.9.0',)],
                     [('history',), (0,), ('invalid',)],
                     [('history',), (0,), ('1.0.0',), (8,)]]:
            with self.subTest(rows=rows), self.assertRaises(SchemaNotReady):
                require_postgres_schema(Database(rows))

    def test_checkpoint_contract(self):
        require_checkpoint_schema(Database([('checkpoint_migrations',), (9,)]))
        for rows in [[(None,)], [('checkpoint_migrations',), (None,)],
                     [('checkpoint_migrations',), (8,)]]:
            with self.assertRaises(SchemaNotReady):
                require_checkpoint_schema(Database(rows))


if __name__ == '__main__': unittest.main()
