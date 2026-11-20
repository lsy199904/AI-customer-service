"""Offline checks for the development migration bridge; never calls Docker."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('run_pg_migration', ROOT/'scripts/run_pg_migration.py')
# configure_external is a sibling import used by the executable.
import sys
sys.path.insert(0, str(ROOT/'scripts'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MigrationRunnerTests(unittest.TestCase):
    def values(self):
        return dict(DATABASE_URL='postgresql://app:p%40ss@127.0.0.1:5433/isolated?sslmode=require',
                    DEPLOYMENT_ID='new', MILVUS_URI='http://localhost:19530',
                    MILVUS_DATABASE='default', MILVUS_COLLECTION='independent',
                    MODEL_API_KEY='must-not-map')

    def test_urls_credentials_and_identity_are_mapped_without_model_keys(self):
        result = module.migration_environment(self.values())
        self.assertEqual(result['FLYWAY_URL'], 'jdbc:postgresql://127.0.0.1:5433/isolated?sslmode=require')
        self.assertEqual(result['FLYWAY_PASSWORD'], 'p@ss')
        self.assertEqual(result['FLYWAY_PLACEHOLDERS_MILVUS_PREFIX'], 'independent')
        self.assertNotIn('must-not-map', str(result))
        self.assertEqual(result['FLYWAY_IMAGE'], 'flyway/flyway:11.20.3-alpine')

    def test_system_database_and_unsafe_sql_placeholder_are_rejected(self):
        for updates in [dict(DATABASE_URL='postgresql://app:p@pg/postgres'),
                        dict(DEPLOYMENT_ID="unsafe'quote"), dict(MILVUS_COLLECTION='')]:
            with self.assertRaises(ValueError):
                module.migration_environment({**self.values(), **updates})

    def test_development_paths_exist(self):
        self.assertTrue((ROOT/'manage.py').is_file())
        self.assertTrue((ROOT/'database/milvus/manage.py').is_file())
        self.assertTrue((ROOT/'.env.example').is_file())
        self.assertIn('/deploy/compose/compose.dev.yaml', (ROOT/'scripts/dev.sh').read_text())
        self.assertTrue((ROOT/'deploy/compose/compose.dev.yaml').is_file())
