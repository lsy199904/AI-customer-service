"""Conservative literal guard for operational answers; not a semantic truth oracle."""
import re
import unicodedata
from .retrieval import terms

URL=re.compile(r'https?://[^\s<>`"\'，。；）)\]]+')
VERSION=re.compile(r'(?<![a-zA-Z0-9_.])v?\d+\.\d+\.\d+(?:[-+][a-zA-Z0-9.-]+)?',re.I)
ADDRESS=re.compile(r'(?<![a-zA-Z0-9_.])(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?(?![a-zA-Z0-9_.])')
COMMAND=re.compile(r'^(?:\$\s*)?(?:sudo\s+)?(?:kubectl|helm|docker|curl|wget|systemctl|apt(?:-get)?|yum|pip3?|python3?|bash|sh)\s+\S',re.I)


def compact(text):return re.sub(r'\s+','',unicodedata.normalize('NFKC',str(text)))


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
    return [{'kind':kind} for kind,value in literal_checks(answer)
            if (value not in source_values[kind] if kind in source_values else compact(value) not in normalized)]


def citation_ids(answer,evidence):
    """Select per-paragraph supporting records, instead of citing every candidate."""
    if len(evidence)<=1:return [r['id'] for r in evidence]
    selected=set()
    for paragraph in re.split(r'\n+|(?<=[。！？；])',answer):
        query=set(terms(paragraph))
        scores=[len(query & set(terms(r['content']))) for r in evidence]
        best=max(scores,default=0)
        if best:
            # Prefer one record on ties; redundant mentions do not justify extra citations.
            selected.add(evidence[scores.index(best)]['id'])
    return [r['id'] for r in evidence if r['id'] in selected] or [evidence[0]['id']]
