"""Check live model routing or replay regression conversations on a test service."""
import argparse
import json
import os
import re
from pathlib import Path
import sys
import time
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from app.business_flows import FLOW_TITLES
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
 ('明确代操作改走指引','帮我创建一个API Key，并替我把账单付掉。',INVOICE,'knowledge',None),
 ('直接投诉','我要投诉，客服一直没有解决我的问题',INVOICE,'complaint',None),
 ('投诉方法咨询','投诉流程是什么',COMPLAINT,'knowledge',None),
 ('开票追问','是否能多次申请',INVOICE,'knowledge','开票'),
 ('切换到注册','注册流程是什么',INVOICE,'knowledge',None),
 ('聊天回顾','我刚才问了哪些问题',INVOICE,'history',None),
 ('自然回顾表达','概括一下咱们到现在聊过的内容',INVOICE,'history',None),
 ('创建方法','如何创建API Key',COMPLAINT,'knowledge',None),
 ('预开票完整问句','最高2万元的提前开票，可以申请多次吗？',[], 'knowledge',None),
 ('口语充值','钱不够了，余额怎么充进去？',[], 'knowledge',None),
 ('注册完成后的下一步','我已经注册好了，下一步该点哪里？',[], 'knowledge',None),
 ('余额不足是情况描述','我没有钱了',[{'role':'user','content':'平台余额不足怎么充值？'},
    {'role':'assistant','content':'可以查看客户充值流程。'}], 'knowledge','充值'),
 ('无关天气','今天天气怎么样？',INVOICE,'out_of_scope',None),
 ('无关闲聊','陪我聊聊足球比赛吧',INVOICE,'out_of_scope',None),
 ('无关成人内容','给我推荐色情网站',[], 'out_of_scope',None),
 ('明确人工','帮我转人工',INVOICE,'handoff',None),
 ('实时账户状态','帮我查一下本企业现在还有多少余额。',[], 'account_status',None),
]

def redact(value, key=''):
    value=str(value)
    if key:value=value.replace(key,'[REDACTED]')
    return re.sub(r'\bsk-[A-Za-z0-9_\-]{6,}', '[REDACTED]',value)[:6000]


class TracedModel:
    def __init__(self,model):
        self.model=model;self.calls=[]
    def complete(self,messages):
        row={'stage':'classification' if not self.calls else 'older_history_resolution'}
        self.calls.append(row)
        try:
            raw=self.model.complete(messages)
            row['model_output']=redact(raw,getattr(self.model.config,'model_key',''))
            return raw
        except Exception as error:
            row.update(error_type=type(error).__name__,reason=resolution_error_code(error),**safe_provider_error(error))
            raise


def check_service(base_url):
    import httpx

    def title_contains(reply, *terms):
        return any(term.casefold() in item['title'].casefold()
                   for item in reply.get('citations', []) for term in terms)

    def payment_choices(reply):
        return {'账单支付流程', '客户充值流程'} <= {
            action['message'] for action in reply.get('actions', []) if action['type']=='clarify'}

    cases = [
        ('服务边界和支付投诉', [
            ('今天天气怎么样？', lambda r: r['reason']=='out_of_scope' and '天气' in r['answer']),
            ('支付不了', payment_choices),
            ('我要投诉，客服一直没有解决我的问题。', lambda r: r['reason']=='complaint_handoff' and r['handoff']),
        ]),
        ('开票追问和换主题', [
            ('提前开票最高多少？', lambda r: title_contains(r, '开票')),
            ('那可以申请几次？', lambda r: title_contains(r, '开票')),
            ('API 密钥在哪里创建？', lambda r: title_contains(r, 'API Key', 'API 密钥') and not title_contains(r, '开票')),
        ]),
        ('残缺输入和新产品主题', [
            ('企业认证流程', lambda r: title_contains(r, '企业认证')),
            ('to', lambda r: r['reason']=='unclear_input' and not r.get('citations') and not r.get('images')),
            ('API 密钥在哪里创建？', lambda r: title_contains(r, 'API Key', 'API 密钥')),
            ('SmartTITU 是什么？', lambda r: r['status']=='answered' and 'SmartTITU' in r['answer']
             and title_contains(r, '产品介绍', '产品定位', 'SmartTITU是什么')
             and not title_contains(r, 'API 密钥', '获取 API Key')),
        ]),
        ('开票和 cURL 示例', [
            ('怎么开票？再给一个 API 调用的 cURL 示例。', lambda r:
             title_contains(r, '开票') and title_contains(r, 'cURL')
             and bool(re.search(r'\bcurl\s+(?:-\w|https?://)', r['answer'], re.I))),
        ]),
    ]
    failed = 0
    with httpx.Client(base_url=base_url.rstrip('/')+'/', timeout=90, trust_env=False) as client:
        def post(path, body):
            response=client.post(path,json=body)
            response.raise_for_status()
            return response.json()

        token=os.getenv('SMARTTITU_TEST_TOKEN') or post('widget/anonymous-auth',{})['token']
        client.headers['Authorization']='Bearer '+token
        for name,turns in cases:
            session=post('v1/sessions',{'context':{'page_title':'客服回归测试'}})['session_id']
            for number,(question,passed) in enumerate(turns,1):
                result=post(f'v1/sessions/{session}/messages',{'message':question,'request_id':uuid4().hex})
                ok=bool(passed(result))
                failed+=not ok
                print(json.dumps({'case':name,'turn':number,'passed':ok,'reason':result['reason'],
                                  'retrieval':result.get('retrieval',{}).get('method'),
                                  'actions':[item['label'] for item in result.get('actions',[])],
                                  'sources':[item['title'] for item in result.get('citations',[])]},ensure_ascii=False),flush=True)
    print(json.dumps({'total':sum(len(turns) for _,turns in cases),'failed':failed}))
    return int(bool(failed))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rounds',type=int,default=2)
    parser.add_argument('--case',choices=[case[0] for case in CASES],help='只运行指定场景')
    parser.add_argument('--base-url',help='测试服务地址，包含 /smart-bot 前缀')
    args=parser.parse_args()
    if args.base_url:
        return check_service(args.base_url)
    if not 1<=args.rounds<=10:parser.error('--rounds must be 1..10')
    model=Model(Settings());failed=0
    cases=[case for case in CASES if not args.case or case[0]==args.case]
    for round_no in range(1,args.rounds+1):
        for name,question,history,expected,subject in cases:
            started=time.monotonic();trace=TracedModel(model);diagnostics=[];result=None
            try:
                result=interpret(trace,question,history,diagnostics=diagnostics)
                ok=result['intent']==expected and result['kind']!='clarify'
                if subject:
                    targets=(result['question'],result.get('retry_query',''),FLOW_TITLES.get(result.get('flow_id'),''))
                    ok=ok and any(subject in target for target in targets)
                if not subject and expected=='knowledge':
                    ok=ok and (question in result['question'] or bool(result.get('normalized_query')))
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
