"""Paid live regression of the configured chat endpoint; no PG/Milvus writes."""
import argparse
import json
import re
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from app.core import Settings,Model
from app.query_context import interpret,resolution_error_code,safe_provider_error

COMPLAINT=[{'role':'user','content':'我要投诉，客服一直没解决问题'},
           {'role':'assistant','content':'请通过人工渠道反馈'}]
ACTION=[{'role':'user','content':'帮我创建API Key并替我付账单'},
        {'role':'assistant','content':'我不能代操作，可以提供步骤'}]
INVOICE=[{'role':'user','content':'提前开票最高多少'},
         {'role':'assistant','content':'最高2万元，且仅支持预开一次'}]
CASES=[
 ('投诉后问产品','数据不出域是不是已经在所有版本默认支持？',COMPLAINT,'knowledge',None),
 ('代操作后问流程','API创建流程',ACTION,'knowledge',None),
 ('明确代操作','帮我创建一个API Key，并替我把账单付掉。',INVOICE,'action',None),
 ('直接投诉','我要投诉，客服一直没有解决我的问题',INVOICE,'complaint',None),
 ('投诉方法咨询','投诉流程是什么',COMPLAINT,'knowledge',None),
 ('开票追问','是否能多次申请',INVOICE,'knowledge','开票'),
 ('切换到注册','注册流程是什么',INVOICE,'knowledge',None),
 ('聊天回顾','我刚才问了哪些问题',INVOICE,'history',None),
 ('自然回顾表达','概括一下咱们到现在聊过的内容',INVOICE,'history',None),
 ('创建方法','如何创建API Key',COMPLAINT,'knowledge',None),
]

def redact(value, key=''):
    value=str(value)
    if key:value=value.replace(key,'[REDACTED]')
    return re.sub(r'\bsk-[A-Za-z0-9_\-]{6,}', '[REDACTED]',value)[:6000]


class TracedModel:
    def __init__(self,model):
        self.model=model;self.calls=[]
    def complete(self,messages):
        row={'stage':'classification' if not self.calls else 'followup_resolution'}
        self.calls.append(row)
        try:
            raw=self.model.complete(messages)
            row['model_output']=redact(raw,getattr(self.model.config,'model_key',''))
            return raw
        except Exception as error:
            row.update(error_type=type(error).__name__,reason=resolution_error_code(error),**safe_provider_error(error))
            raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rounds',type=int,default=2)
    parser.add_argument('--case',choices=[case[0] for case in CASES],help='只运行指定场景')
    args=parser.parse_args()
    if not 1<=args.rounds<=10:parser.error('--rounds must be 1..10')
    model=Model(Settings());failed=0
    cases=[case for case in CASES if not args.case or case[0]==args.case]
    for round_no in range(1,args.rounds+1):
        for name,question,history,expected,subject in cases:
            started=time.monotonic();trace=TracedModel(model);diagnostics=[];result=None
            try:
                result=interpret(trace,question,history,diagnostics=diagnostics)
                ok=result['intent']==expected and result['kind']!='clarify'
                if subject:ok=ok and subject in result['question']
                if not subject and expected=='knowledge':ok=ok and question in result['question']
                row=dict(round=round_no,case=name,passed=bool(ok),expected=expected,actual=result['intent'],kind=result['kind'],query=result['question'])
            except Exception as error:
                ok=False;row=dict(round=round_no,case=name,passed=False,error_type=type(error).__name__,reason=resolution_error_code(error))
            if not ok:
                row['calls']=trace.calls
                row['diagnostics']=diagnostics
                if result is not None and diagnostics:row['clarification']=result.get('clarification','')
            failed+=not ok
            row['elapsed_ms']=round((time.monotonic()-started)*1000)
            print(json.dumps(row,ensure_ascii=False),flush=True)
    print(json.dumps({'total':len(cases)*args.rounds,'failed':failed},ensure_ascii=False))
    return 1 if failed else 0

if __name__=='__main__':sys.exit(main())
