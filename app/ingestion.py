"""Human-managed documents -> clean, traceable text chunks. No model inference here."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import io
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET

PIPELINE_VERSION='documents-v3'
MAX_FILE_BYTES=25*1024*1024
SUPPORTED={'.docx','.pdf','.md','.txt'}
NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}

@dataclass
class ParsedDocument:
    filename: str
    title: str
    version: str
    sha256: str
    raw: bytes
    chunks: list


def clean_text(value):
    value=unicodedata.normalize('NFKC',value)
    value=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\u200b\ufeff]','',value)
    return '\n'.join(re.sub(r'[ \t]+',' ',line).strip() for line in value.splitlines()).strip()


def _paragraph(p):
    return clean_text(''.join((n.text or '') if n.tag==f"{{{NS['w']}}}t" else '\n' if n.tag in {f"{{{NS['w']}}}br",f"{{{NS['w']}}}cr"} else '\t' if n.tag==f"{{{NS['w']}}}tab" else '' for n in p.iter()))


def _docx(path,raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(x.file_size for x in archive.infolist())>60*1024*1024:raise ValueError('Word解压体积过大')
        xml=archive.read('word/document.xml')
        # Word/WPS may rename built-in style IDs to numeric IDs on save.
        styles={}
        if 'word/styles.xml' in archive.namelist():
            style_xml=archive.read('word/styles.xml')
            if b'<!DOCTYPE' in style_xml:raise ValueError('不接受带DOCTYPE的Word XML')
            for item in ET.fromstring(style_xml).findall('w:style',NS):
                name=item.find('w:name',NS)
                if name is not None:styles[item.get(f"{{{NS['w']}}}styleId",'')]=name.get(f"{{{NS['w']}}}val",'')
    if b'<!DOCTYPE' in xml:raise ValueError('不接受带DOCTYPE的Word XML')
    body=ET.fromstring(xml).find('w:body',NS)
    blocks=[];title=path.stem;version='未标注';paragraph_no=0
    for node in body:
        if node.tag==f"{{{NS['w']}}}p":
            paragraph_no+=1;text=_paragraph(node)
            if not text:continue
            style=node.find('w:pPr/w:pStyle',NS);style=style.get(f"{{{NS['w']}}}val",'') if style is not None else ''
            style=styles.get(style,style)
            if style.lower()=='title':title=text;continue
            if re.match(r'^版本[:：]',text):version=text.split(':',1)[-1].strip()
            if '\n版本:' in text:version=text.split('\n版本:',1)[1].split('\n',1)[0].strip()
            heading=re.match(r'^(Heading|标题)[ _-]?([1-6])$',style,re.I)
            blocks.append({'text':text,'heading':bool(heading),'level':int(heading.group(2)) if heading else None,'page':None,'locator':'段落 '+str(paragraph_no)})
        elif node.tag==f"{{{NS['w']}}}tbl":
            rows=[]
            for row in node.findall('w:tr',NS):
                rows.append([' / '.join(_paragraph(p) for p in cell.findall('.//w:p',NS) if _paragraph(p)) for cell in row.findall('w:tc',NS)])
            if rows:
                header=rows[0]
                for number,row in enumerate(rows[1:] or rows,1):
                    text='; '.join((header[i]+': ' if len(rows)>1 and i<len(header) else '')+v for i,v in enumerate(row) if v)
                    blocks.append({'text':text,'heading':False,'page':None,'locator':'表格行 '+str(number)})
    return title,version,blocks


def _pdf(path,raw):
    try:from pypdf import PdfReader
    except ImportError:raise ValueError('PDF入库需要pypdf,请先安装requirements.txt')
    reader=PdfReader(io.BytesIO(raw))
    if reader.is_encrypted:raise ValueError('请先提供可读取的非加密PDF')
    blocks=[]
    for page_no,page in enumerate(reader.pages,1):
        text=clean_text(page.extract_text() or '')
        if not text:continue
        blocks.append({'text':path.stem+' 第'+str(page_no)+'页','heading':True,'page':page_no,'locator':'PDF物理第'+str(page_no)+'页'})
        for paragraph in re.split(r'\n\s*\n',text):
            blocks.append({'text':paragraph,'heading':False,'page':page_no,'locator':'PDF物理第'+str(page_no)+'页'})
    if sum(len(b['text']) for b in blocks)<30:raise ValueError('PDF没有足够可提取文字,扫描件请先OCR或改用Word')
    return path.stem,'未标注',blocks


def _plain(path,raw):
    blocks=[]
    for line in raw.decode('utf-8-sig').splitlines():
        line=clean_text(line)
        if not line:continue
        heading=bool(re.match(r'^#{1,6}\s+',line))
        blocks.append({'text':re.sub(r'^#{1,6}\s+','',line),'heading':heading,'level':len(line.split()[0]) if heading else None,'page':None,'locator':'文本章节'})
    return path.stem,'未标注',blocks


def split_sections(blocks,title,max_chars=1000,overlap=100):
    if max_chars<200 or overlap<0 or overlap>=max_chars:raise ValueError('切分参数无效')
    has_headings=any(b['heading'] for b in blocks)
    sections=[];current=None;chapter=title
    for block in blocks:
        if block['heading']:
            if block.get('level')==1:chapter=block['text']
            current={'title':block['text'],'chapter':chapter,'blocks':[],'refs':[],'image_ids':[]};sections.append(current)
        elif current is None and not has_headings:
            current={'title':title,'chapter':chapter,'blocks':[],'refs':[],'image_ids':[]};sections.append(current)
        if current is not None and not block['heading']:
            if re.match(r'^来源[:：]',block['text']):current['refs'].append(block['text']);continue
            if re.match(r'^配图[:：]',block['text']):
                image_ids=re.split(r'[,，\s]+',re.split('[:：]',block['text'],maxsplit=1)[1].strip())
                if not image_ids or any(not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}',key) for key in image_ids):
                    raise ValueError('配图必须填写已登记的图片ID,多个ID用逗号分隔')
                current['image_ids']=list(dict.fromkeys(current['image_ids']+image_ids));continue
            current['blocks'].append(block)
    chunks=[]
    for section in sections:
        text='\n'.join(b['text'] for b in section['blocks']).strip()
        pages=sorted({b['page'] for b in section['blocks'] if b.get('page') is not None})
        start=0
        while start<len(text):
            end=min(start+max_chars,len(text))
            if end<len(text):
                boundary=max(text.rfind(mark,start+max_chars//2,end) for mark in ('\n','。',';','；'))
                if boundary>start:end=boundary+1
            content=text[start:end].strip()
            if content:
                chunks.append({'title':section['title'],'section_title':section['chapter'],'content':content,'source_pages':pages,
                               'source_locator':section['title']+' / '+(', '.join(dict.fromkeys(b['locator'] for b in section['blocks']))),
                               'source_references':section['refs'],'image_ids':section['image_ids']})
            if end==len(text):break
            start=max(start+1,end-overlap)
    return chunks


def parse_document(path,max_chars=1000,overlap=100):
    path=Path(path)
    if path.is_symlink():raise ValueError('原文档不接受符号链接:'+path.name)
    if path.suffix.lower() not in SUPPORTED:raise ValueError('只支持docx、文字PDF、Markdown和TXT;旧版doc请另存为docx')
    if path.stat().st_size>MAX_FILE_BYTES:raise ValueError('文档超过25MB:'+path.name)
    raw=path.read_bytes()
    if path.suffix.lower()=='.docx':title,version,blocks=_docx(path,raw)
    elif path.suffix.lower()=='.pdf':title,version,blocks=_pdf(path,raw)
    else:title,version,blocks=_plain(path,raw)
    chunks=split_sections(blocks,title,max_chars,overlap)
    if not chunks:raise ValueError('没有可入库的正文:'+path.name)
    return ParsedDocument(path.name,title,version,hashlib.sha256(raw).hexdigest(),raw,chunks)
