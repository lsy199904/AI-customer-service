"""Compatibility entry point; the maintained CLI lives in database/milvus/manage.py."""
from pathlib import Path
import runpy

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().parent / 'database/milvus/manage.py'), run_name='__main__')
