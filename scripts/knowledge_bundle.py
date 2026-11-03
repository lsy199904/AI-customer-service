"""Portable knowledge and local media; optional completed PostgreSQL export, never .env/models."""
import argparse
import hashlib
import io
import json
import os
import re
from pathlib import Path,PurePosixPath
import tarfile
import tempfile
import subprocess

ROOTS=('knowledge_sources','app/static/media','data/media.json','var/pdf_media')
STORAGE=('assistant.db','rag.sqlite3','export.json')

def digest(raw):return hashlib.sha256(raw).hexdigest()
def allowed(name):
    if '\\' in name:return False
    path=PurePosixPath(name)
    return not path.is_absolute() and '..' not in path.parts and (name in ('data/media.json',) or any(name.startswith(root+'/') for root in ('knowledge_sources','app/static/media','var/pdf_media')) or name in ['migration-storage/'+x for x in STORAGE])
def pack(root,output,storage=None):
    root=Path(root).resolve();output=Path(output)
    if output.exists():raise ValueError('迁移包已存在，不覆盖')
    env_file=root/'.env'
    if env_file.exists():
        configuration=env_file.read_text()
        for key,relative in [('PDF_MEDIA_DIR','var/pdf_media'),('MEDIA_PATH','data/media.json')]:
            found=re.search(r'^\s*(?:export\s+)?'+key+r'\s*=\s*(.*?)\s*$',configuration,re.M)
            value=found[1].strip('\"\'') if found else ''
            if value and value not in (relative,str(root/relative),'/ai_customer/'+relative):
                raise ValueError(key+'使用了自定义目录，请先将相关资源同步到项目内标准目录再打包，避免漏拷')
    files={}
    for entry in ROOTS:
        source=root/entry
        if source.is_symlink():raise ValueError('迁移来源不接受符号链接:'+entry)
        paths=[source] if source.is_file() else sorted(source.rglob('*')) if source.exists() else []
        for path in paths:
            if path.is_symlink() or root not in path.resolve().parents:raise ValueError('迁移来源不接受符号链接或项目外目录')
            relative=path.relative_to(root)
            if any(part.startswith('.') for part in relative.parts):continue
            if entry=='knowledge_sources' and path.suffix.lower() not in ('.docx','.pdf','.md','.txt'):continue
            if entry=='var/pdf_media' and path.suffix.lower() not in ('.png','.json'):continue
            if path.is_file() and not path.name.endswith('.tmp'):
                files[relative.as_posix()]=path.read_bytes()
    for required in ('data/media.json',):
        if required not in files:raise ValueError('缺少图片登记表')
    if storage:
        for name in STORAGE:
            path=Path(storage)/name
            if not path.is_file() or path.is_symlink():raise ValueError('数据库导出不完整')
            files['migration-storage/'+name]=path.read_bytes()
    if len(files)>5000 or sum(len(raw) for raw in files.values())>2*1024**3-1024**2:raise ValueError('迁移包体积或文件数超限，请分批迁移')
    try:
        revision=subprocess.run(['git','-C',str(root),'rev-parse','HEAD'],capture_output=True,text=True,timeout=2).stdout.strip() or None
    except (OSError,subprocess.TimeoutExpired):revision=None
    manifest={'version':1,'code_revision':revision,'files':{name:digest(raw) for name,raw in files.items()},'database_export':bool(storage)}
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent,delete=False) as temp:tmp=Path(temp.name)
    try:
        with tarfile.open(tmp,'w:gz') as archive:
            for name,raw in {**files,'bundle-manifest.json':json.dumps(manifest,ensure_ascii=False,indent=2).encode()}.items():
                info=tarfile.TarInfo(name);info.size=len(raw);info.mode=0o600;archive.addfile(info,io.BytesIO(raw))
        os.link(tmp,output) # Exclusive creation; a concurrent export cannot be overwritten.
    finally:tmp.unlink(missing_ok=True)
    return {'archive':str(output),'files':len(files),'database_export':bool(storage),'code_revision':revision}
def restore(root,archive):
    root=Path(root).resolve();files={}
    with tarfile.open(archive,'r:gz') as source:
        total=0
        for member in source:
            total+=member.size
            if len(files)>5000 or total>2*1024**3:raise ValueError('迁移包体积或文件数超限')
            if not member.isfile() or member.name in files or (member.name!='bundle-manifest.json' and not allowed(member.name)):raise ValueError('迁移包包含不允许的路径或类型')
            files[member.name]=source.extractfile(member).read()
    manifest=json.loads(files.pop('bundle-manifest.json'))
    if manifest.get('version')!=1 or manifest['files']!={name:digest(raw) for name,raw in files.items()}:raise ValueError('迁移包校验失败')
    # Validate all paths and conflicts before writing the first file.
    for name,raw in files.items():
        path=root/name
        if path.is_symlink() or root not in path.resolve().parents or any(parent.is_symlink() for parent in path.parents if parent!=root and root in parent.parents):raise ValueError('目标路径越界或包含符号链接')
        if path.exists() and (not path.is_file() or path.read_bytes()!=raw):raise ValueError('目标已有不同内容，请使用相同代码版本的干净目录:'+name)
    count=0
    for name,raw in files.items():
        path=root/name
        if path.exists():continue
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as target:os.chmod(path,0o600);target.write(raw)
        count+=1
    return {'restored_files':count,'database_export':manifest.get('database_export',False),'next_step':'配置新主机.env；数据库导出需使用migrate-storage导入空PostgreSQL，再sync-vectors，不要直接启动空数据库'}
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('operation',choices=('pack','restore'));parser.add_argument('--root',default=str(Path(__file__).resolve().parent.parent));parser.add_argument('--output');parser.add_argument('--archive');parser.add_argument('--storage-dir');args=parser.parse_args()
    if args.operation=='pack':
        if not args.output:parser.error('pack需要--output')
        result=pack(args.root,args.output,args.storage_dir)
    else:
        if not args.archive:parser.error('restore需要--archive')
        result=restore(args.root,args.archive)
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
