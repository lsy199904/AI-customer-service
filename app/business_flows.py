"""Single registry for flow names, guide stages and diagram ownership.

Stage entries select numbered evidence; they never contain business answers.
"""
import json
import re
from pathlib import Path


def load_registry(path):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    flows=data['flows'];images=data['images']
    if not isinstance(flows,dict) or not isinstance(images,dict):raise ValueError('invalid flow registry')
    for key,row in flows.items():
        if not re.fullmatch('[a-z][a-z0-9_]*',key) or not isinstance(row.get('title'),str):raise ValueError('invalid flow')
        for field in ('aliases','visual_aliases_extra'):
            if not isinstance(row.get(field,[]),list) or any(not isinstance(v,str) or not v for v in row.get(field,[])):raise ValueError('invalid flow aliases')
        if set(row.get('next',[]))-flows.keys():raise ValueError('unknown next flow')
        for title,numbers in row.get('stages',[]):
            if not isinstance(title,str) or not numbers or any(type(n) is not int or n<1 for n in numbers):raise ValueError('invalid guide stage')
    for row in images.values():
        if not isinstance(row.get('flow_ids'),list) or not row['flow_ids'] or any(v not in flows for v in row['flow_ids']):raise ValueError('unknown image flow')
        if type(row.get('flow_priority',0)) is not int:raise ValueError('invalid image priority')
    return flows,images

FLOWS,IMAGE_BINDINGS=load_registry(Path(__file__).resolve().parent.parent/'data/business_flows.json')
FLOW_TITLES={k:v['title'] for k,v in FLOWS.items()}
GUIDED_FLOWS={k:{'title':v['title'],'aliases':v.get('aliases',[]),'stages':v['stages']} for k,v in FLOWS.items() if v.get('stages')}
NEXT={k:FLOWS[k].get('next',[]) for k in GUIDED_FLOWS}
VISUAL_ALIASES={k:[v['title'],*v.get('aliases',[]),*v.get('visual_aliases_extra',[])] for k,v in FLOWS.items()}
QUICK_QUESTIONS=[v['title'] for v in FLOWS.values() if v.get('recommended')]


def image_binding(key):
    # Registry ownership takes precedence over legacy duplicated media fields.
    return {k:list(v) if isinstance(v,list) else v for k,v in IMAGE_BINDINGS.get(key,{}).items()}
