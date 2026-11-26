"""Conservative literal guard for operational answers; not a semantic truth oracle."""
import re
import unicodedata
from decimal import Decimal
from .retrieval import terms

URL=re.compile(r'https?://[^\s<>`"\'，。；）)\]]+')
VERSION=re.compile(r'(?<![a-zA-Z0-9_.])v?\d+\.\d+\.\d+(?:[-+][a-zA-Z0-9.-]+)?',re.I)
ADDRESS=re.compile(r'(?<![a-zA-Z0-9_.])(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?(?![a-zA-Z0-9_.])')
COMMAND=re.compile(r'^(?:\$\s*)?(?:sudo\s+)?(?:kubectl|helm|docker|curl|wget|systemctl|apt(?:-get)?|yum|pip3?|python3?|bash|sh)\s+\S',re.I)
BANK=re.compile(r'(?:【|\[|通过|选择|使用|汇款至|转账至|收款银行(?:为|是|[:：]))\s*([\u3400-\u9fff]{2,12}银行)(?!卡)')
AMOUNT=re.compile(r'(?<![\d.])(\d+(?:\.\d+)?)\s*(万)?\s*(?:人民币)?元')
LIMIT=re.compile(r'(?<![A-Za-z0-9_])(?:RPM|TPM|QPS)(?![A-Za-z0-9_])',re.I)
COUNT=re.compile(r'(?:申请|预开|开具|办理|提交|尝试)\s*(?:最多|仅限|只能)?\s*(\d+|[一二两三四五六七八九十])\s*次')
COUNT_VALUES=dict(zip('一二两三四五六七八九十',(1,2,2,3,4,5,6,7,8,9,10)))


def compact(text):return re.sub(r'\s+','',unicodedata.normalize('NFKC',str(text)))


def unsupported_business_facts(answer, evidence, guidance=None):
    """Check directly comparable values before sending business answers."""
    source = (guidance['stage_evidence'] if guidance and guidance.get('stage_evidence')
              else '\n'.join(row['content']+' '+row.get('title','') for row in evidence))
    source = re.sub(r'(?<=\d),(?=\d{3}(?!\d))', '', unicodedata.normalize('NFKC', source))
    text = re.sub(r'(?<=\d),(?=\d{3}(?!\d))', '', unicodedata.normalize('NFKC', answer))
    def amount(match):
        return Decimal(match[1]) * (10000 if match[2] else 1)
    amounts = {amount(match) for match in AMOUNT.finditer(source)}
    counts = {str(COUNT_VALUES.get(match[1], match[1])) for match in COUNT.finditer(source)}
    limits = {match[0].upper() for match in LIMIT.finditer(source)}
    normalized_source = compact(source)
    for label, descriptions in {
        'RPM': ('每分钟请求数', '每分钟请求次数'),
        'TPM': ('每分钟Token数', '每分钟词元数'),
        'QPS': ('每秒请求数', '每秒请求次数'),
    }.items():
        if any(description in normalized_source for description in descriptions):
            limits.add(label)
    missing = [
        match[1] for match in BANK.finditer(text)
        if match[1] not in source and not match[1].startswith(('指定','发卡','收款','付款','任意','对应'))
    ]
    missing.extend(match[0] for match in AMOUNT.finditer(text) if amount(match) not in amounts)
    missing.extend(match[0] for match in LIMIT.finditer(text) if match[0].upper() not in limits)
    missing.extend(match[0] for match in COUNT.finditer(text)
                   if str(COUNT_VALUES.get(match[1], match[1])) not in counts)
    return list(dict.fromkeys(missing))


def literal_checks(answer):
    """Values that must be present literally, rather than inferred from an overview."""
    checks=[]
    checks.extend(('url',m.group().rstrip('.,;:')) for m in URL.finditer(answer))
    checks.extend(('version',m.group().lower().removeprefix('v')) for m in VERSION.finditer(answer))
    checks.extend(('address',m.group()) for m in ADDRESS.finditer(answer))
    for block in re.findall(r'```[^\n]*\n(.*?)```',answer,re.S):
        for line in block.splitlines():
            line=line.strip().rstrip('\\').strip()
            if line and not line.startswith('#'):checks.append(('code',line.removeprefix('$ ').strip()))
    for line in answer.splitlines():
        line=re.sub(r'^\s*(?:\d+[.、)]\s*|[-*]\s*)?','',line).strip('` ')
        if COMMAND.match(line):checks.append(('command',line.removeprefix('$ ').rstrip('\\').strip()))
    for inline in re.findall(r'`([^`\n]+)`',answer):
        if COMMAND.match(inline.strip()):checks.append(('command',inline.strip().removeprefix('$ ')))
    return list(dict.fromkeys(checks))


def unsupported_literals(answer,evidence,guidance=None):
    sources=[guidance['stage_evidence']] if guidance and guidance.get('stage_evidence') else [r['content'] for r in evidence]
    source='\n'.join(sources)
    normalized=compact(source)
    source_values={kind:{value for k,value in literal_checks(source) if k==kind} for kind in ('url','version','address')}
    ids=[r.get('id') for r in evidence if r.get('id')]
    issues=[]
    for kind,value in literal_checks(answer):
        missing=value not in source_values[kind] if kind in source_values else compact(value) not in normalized
        if not missing:continue
        excerpt=next((line.strip() for line in answer.splitlines() if value in line or (kind=='version' and 'v'+value in line)),value)
        issues.append({'kind':kind,'text':value,'answer_excerpt':excerpt,
            'evidence_ids':ids,'evidence_scope':'current_stage' if guidance and guidance.get('stage_evidence') else 'current_turn',
            'reason':'literal_value_missing_from_current_evidence' if kind in source_values else 'command_or_config_line_missing_from_current_evidence'})
    return issues



def citation_ids(answer,evidence):
    """Select per-paragraph supporting records, instead of citing every candidate."""
    if len(evidence)<=1:return [r['id'] for r in evidence]
    selected=set()
    for paragraph in re.split(r'\n+|(?<=[。！？；，])',answer):
        query=set(terms(paragraph))
        scores=[len(query & set(terms(r['content']+' '+r.get('title','')))) for r in evidence]
        best=max(scores,default=0)
        if best:
            # Prefer one record on ties; redundant mentions do not justify extra citations.
            selected.add(evidence[scores.index(best)]['id'])
    return [r['id'] for r in evidence if r['id'] in selected] or [evidence[0]['id']]
