"""Build a tracked-source snapshot without Git history or runtime secrets."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def package(output, root=ROOT):
    root=Path(root);output=Path(output).resolve()
    if output.exists():
        raise ValueError('交付包已存在，不覆盖：'+str(output))
    tracked=subprocess.run(['git','-C',str(root),'ls-files','-z'],check=True,capture_output=True).stdout.decode().split('\0')
    selected=[]
    excluded={'var','backups','models','migration-storage','.git','.venv','node_modules','__pycache__'}
    for name in sorted(filter(None,tracked)):
        p=root/name
        if not p.exists() or name=='SHA256SUMS':
            continue
        if p.is_symlink():
            raise ValueError('交付文件不允许符号链接：'+name)
        if any(part in excluded for part in Path(name).parts) or name.startswith('deploy/generated/'):
            continue
        if (p.name.startswith('.env') and name!='.env.example') or p.suffix in {'.dump','.db','.sqlite3','.pyc'}:
            raise ValueError('Git跟踪了不应交付的运行文件，请先移除：'+name)
        if p.is_file():
            selected.append((name,p))
    for required in ['README.md','compose.v3.yaml','.env.example','docs/部署说明.md',
                     'scripts/configure_release.py','knowledge_sources/SmartTITU客户问答.docx','data/media.json']:
        if required not in {name for name,_ in selected}:
            raise ValueError('缺少交付必需文件：'+required)
    checksums=''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+name+'\n' for name,p in selected)
    (root/'SHA256SUMS').write_text(checksums)
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as archive:
        for name,p in selected:
            archive.write(p,'smarttitu-assistant/'+name)
        archive.write(root/'SHA256SUMS','smarttitu-assistant/SHA256SUMS')
    print('交付快照：'+str(output)+'；不含Git历史、真实.env、数据库和运行数据。')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    package(args.output)
