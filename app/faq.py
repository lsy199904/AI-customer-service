"""Operator-maintained standard answers. No retrieval or model calls."""
import json
from pathlib import Path
import re
import secrets


class FAQCatalog:
    def __init__(self,path):
        self.version='';self.rows={}
        path=Path(path)
        if not path.exists():return
        data=json.loads(path.read_text(encoding='utf-8'))
        self.version=data['version']
        if not isinstance(self.version,str) or not self.version:raise ValueError('FAQ版本不能为空')
        for row in data['items']:
            key=row.get('id','');question=row.get('question');answer=row.get('answer')
            if not isinstance(key,str) or not re.fullmatch(r'faq-[a-z0-9-]{1,40}',key) or key in self.rows:
                raise ValueError('FAQ编号无效或重复')
            if not isinstance(question,str) or not 1<=len(question)<=2000 or not isinstance(answer,str) or not answer.strip():
                raise ValueError('FAQ问题或答案无效')
            if not isinstance(row.get('image_ids',[]),list) or not all(isinstance(key,str) for key in row.get('image_ids',[])):raise ValueError('FAQ配图编号须为字符串数组')
            self.rows[key]=row

    def batch(self,exclude=()):
        remaining=[row for key,row in self.rows.items() if key not in exclude]
        if len(remaining)<min(6,len(self.rows)):remaining=list(self.rows.values())
        selected=secrets.SystemRandom().sample(remaining,min(6,len(remaining)))
        return {'version':self.version,'total':len(self.rows),
                'items':[{'id':r['id'],'question':r['question']} for r in selected]}
