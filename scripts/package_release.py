"""Package an auditable source release without credentials, live databases or backups."""
from pathlib import Path
import hashlib
import zipfile
ROOT=Path(__file__).resolve().parent.parent
SKIP_DIRS={'.git','__pycache__','var','backups','.venv','node_modules','models'}

def files():
 for path in sorted(ROOT.rglob('*')):
  relative=path.relative_to(ROOT)
  if not path.is_file() or any(x in SKIP_DIRS for x in relative.parts):continue
  if (path.name.startswith('.env') and path.name!='.env.example') or path.name=='SHA256SUMS' or path.suffix in {'.pyc','.db','.sqlite3','.zip'}:continue
  yield path

def build():
 selected=list(files())
 sums=''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(ROOT).as_posix()+'\n' for p in selected)
 manifest=ROOT/'SHA256SUMS';manifest.write_text(sums)
 output=ROOT.parent/'SmartTITU_智能客服_MVP_交付包_20261022.zip'
 with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
  for path in selected+[manifest]:z.write(path,Path('smarttitu-assistant')/path.relative_to(ROOT))
 with zipfile.ZipFile(output) as z:
  assert z.testzip() is None
  assert not any('/.env'==name[-5:] for name in z.namelist())
 print('Release:',output,'files:',len(selected)+1,'bytes:',output.stat().st_size)
 return output
if __name__=='__main__':build()
