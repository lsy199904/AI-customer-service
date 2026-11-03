"""Literal enumerations in source prose, not generated answers or question aliases."""
import re
import unicodedata

NUMBERS={'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
PATTERN=re.compile(r'(?:围绕|包含|包括|打造|覆盖)([^。；;！？]{4,120}?)([一二三四五六七八九1-9])([大类项个])((?:核心)?(?:价值|能力|场景|功能|服务))')


def extract_lists(content):
    text=re.sub(r'\s+','',unicodedata.normalize('NFKC',content));result=[]
    for match in PATTERN.finditer(text):
        values=[v.strip() for v in re.split('[、,，]',match[1])]
        number=NUMBERS.get(match[2],int(match[2]) if match[2].isdigit() else 0)
        if len(values)!=number or any(not 2<=len(v)<=35 for v in values):continue
        result.append({'label':match[2]+match[3]+match[4],'items':values,'quote':match[0]})
    return result


def explicit_list_request(question,record):
    text=re.sub(r'\s+','',unicodedata.normalize('NFKC',question)).lower()
    names=set(re.findall('[a-z][a-z0-9]{2,}',text))
    source_names=set(re.findall('[a-z][a-z0-9]{2,}',(record.get('document_title','')+' '+record['title']+' '+record['content'][:250]).lower()))
    for item in extract_lists(record['content']):
        noun=re.sub(r'^[一二三四五六七八九1-9][大类项个]','',item['label'])
        target=item['label'] if item['label'].lower() in text else noun if len(noun)>=4 and noun in text else None
        if not target:continue
        requested=re.search(r'([一二三四五六七八九1-9])[大类项个]'+re.escape(noun),text)
        if requested and requested[1]!=item['label'][0]:continue
        if names & source_names or re.fullmatch(r'(?:请问|介绍一下)?'+re.escape(target)+r'(?:是什么|有哪些|包括什么)?[？?]?',text):return True
    return False
