"""V2 conversational guidance. Stage text always comes from the active knowledge revision."""
import hashlib
import re
from .retrieval import title_text,terms

FLOWS={
 'register':{'title':'注册流程','aliases':['注册','开户'], 'stages':[('填写注册信息',[1]),('提交与校验',[2,3]),('登录与后续办理',[4])]},
 'verification':{'title':'企业认证流程','aliases':['企业认证','企业实名'], 'stages':[('完善企业资料',[1]),('选择认证方式',[2]),('办理认证与审核',[3,4,5]),('查看认证结果',[6])]},
 'subscription':{'title':'服务订购流程','aliases':['服务订购','套餐订购','订购'], 'stages':[('选择服务与模型',[1]),('办理签约',[2,3]),('查看生效与服务开通',[4,5])]},
 'recharge':{'title':'客户充值流程','aliases':['充值'], 'stages':[('选择充值方式',[1]),('完成支付或汇款',[2,3]),('核对充值结果',[4,5])]},
 'payment':{'title':'账单支付流程','aliases':['账单支付','账单付款','付账单'], 'stages':[('选择待支付账单',[1]),('完成支付或汇款',[2,3]),('核对账单结算结果',[4,5])]},
 'invoice':{'title':'在线开票流程','aliases':['在线开票','开票','发票申请'], 'stages':[('维护开票信息',[1]),('选择记录与抬头',[2,3]),('提交申请与核对',[4,5]),('查看或下载发票',[6])]},
}
NOTE='进度仅根据您的反馈记录，未查询或办理后台业务。'
NEXT={'register':['verification'],'verification':['subscription'],'subscription':['recharge'],'recharge':['payment'],'payment':['invoice'],'invoice':[]}


def chapter(rows,flow_id):
    title=FLOWS[flow_id]['title']
    return next((row for row in rows if title_text(row.get('title',''))==title),None)


def numbered_steps(row):
    if not row:return {}
    text=row.get('content','')
    return {int(match[1]):match[2].strip() for match in re.finditer(r'(?:^|\n)\s*(\d+)[.、．]\s*(.*?)(?=\n\s*\d+[.、．]|\n\s*(?:图片URL|原文链接|来源)[:：]|\Z)',text,re.S)}


def revision(row):
    return row.get('revision') or hashlib.sha256(row.get('content','').encode()).hexdigest()


def available(rows):
    return {key:row for key in FLOWS if (row:=chapter(rows,key)) and
            all(number in numbered_steps(row) for _,numbers in FLOWS[key]['stages'] for number in numbers)}


def flow_match(question,keys):
    text=re.sub(r'\s+','',question)
    # Prefer explicit subjects rather than incidental references to another process.
    matches=[(len(alias),key) for key in keys for alias in [FLOWS[key]['title'],*FLOWS[key]['aliases']] if alias in text]
    return max(matches,default=(0,None))[1]


def last_response(history):
    return next((item.get('response') or {} for item in reversed(history) if item['role']=='assistant'),{})


def guide_state(key,index,row,status='active',notice=None):
    flow=FLOWS[key]
    return {'flow_id':key,'title':flow['title'],'step':index,'total':len(flow['stages']),
            'stages':[title for title,_ in flow['stages']],'status':status,'source_revision':revision(row),
            'note':NOTE,**({'notice':notice} if notice else {})}


def plan(question,history,rows):
    """Only plans control flow; no answers or transaction results are encoded here."""
    options=available(rows)
    if not options:return {}
    text=re.sub(r'[\s。！!？?，,]+','',question)
    previous=last_response(history);active=previous.get('guidance') or {}
    key=active.get('flow_id') if active.get('status')=='active' else None
    if key not in options:key=None
    matched=flow_match(question,options)
    if previous.get('intent')=='clarification':
        choices=[item.get('message') for item in previous.get('actions',[]) if item.get('type')=='clarify']
        ordinals={'第一个':0,'第一种':0,'1':0,'第二个':1,'第二种':1,'2':1}
        choice=choices[ordinals[text]] if text in ordinals and ordinals[text]<len(choices) else None
        partial=[item for item in choices if isinstance(item,str) and len(text)>=2 and text in item]
        if not choice and len(partial)==1:choice=partial[0]
        if choice:return {'kind':'choice','query':choice,'resolved_question':choice,'flow_id':flow_match(choice,options)}
    compact=re.sub(r'\s+','',question)
    if key and text in {'结束指导','结束陪办','退出指导','取消指导','先不办了','不办了'}:
        return {'kind':'end','guidance':guide_state(key,active['step'],options[key],status='ended')}
    # A normal named chapter remains a normal question; guidance is opt-in.
    start=bool(re.search(r'带我|一步步|分步指导|陪我|我要办理|我想办理|开始办理|开始指导',compact))
    if start and matched:
        return {'kind':'guide','query':FLOWS[matched]['title'],'guidance':guide_state(matched,0,options[matched])}
    if matched and text==FLOWS[matched]['title']:return {'kind':'offer','flow_id':matched}
    if key and text in {'好','好的','明白了','知道了','谢谢','谢谢你','谢谢您','好的谢谢'}:
        changed=active.get('source_revision')!=revision(options[key])
        current=guide_state(key,0 if changed else active['step'],options[key],notice='知识内容已更新，已回到第一步。' if changed else None)
        return {'kind':'ack','guidance':current}
    if key and (matched is None or matched==key):
        moves={'这一步已完成':1,'完成了':1,'已完成':1,'下一步':1,'继续下一步':1,'返回上一步':-1,'上一步':-1,'重新开始':0,'这一步怎么做':0,'没完成':0,'还是不行':0,'失败了':0,'看不懂':0}
        related=bool(set(terms(question)) & set(terms(FLOWS[key]['title']+' '+active['stages'][active['step']])))
        if text in moves or (matched==key and text!=FLOWS[key]['title'] and not re.search(r'完整流程|全部步骤|总体|概况',text)) or (related and len(text)<100):
            changed=active.get('source_revision')!=revision(options[key])
            index=0 if changed or text=='重新开始' else max(0,active['step']+moves.get(text,0))
            if index>=len(FLOWS[key]['stages']):
                return {'kind':'complete','guidance':guide_state(key,len(FLOWS[key]['stages'])-1,options[key],status='completed')}
            return {'kind':'guide','query':FLOWS[key]['title'],'guidance':guide_state(key,index,options[key],notice='知识内容已更新，已回到第一步。' if changed else None)}
    if text in {'这一步已完成','完成了','下一步','上一步','继续下一步','这一步怎么做'} and not key:
        return {'kind':'clarify','answer':'您想继续哪个业务流程？请先选择，我再按步骤陪您操作。',
                'choices':[FLOWS[item]['title'] for item in options]}
    if re.search(r'支付|付款',text) and not re.search(r'账单|充值|接口|API|api|模型|发票',text) and len(text)<36:
        choices=[FLOWS[item]['title'] for item in ('payment','recharge') if item in options]
        if len(choices)>1:return {'kind':'clarify','answer':'您遇到的是账单支付，还是充值支付的问题？先选一下，我再给您对应的处理说明。','choices':choices}
    if text in {'认证失败','认证不了','认证有问题'} and 'verification' in options:
        api=next((title_text(row['title']) for row in rows if 'API' in row.get('title','').upper() and '密钥' in row['title']),None)
        if api:return {'kind':'clarify','answer':'您说的是企业认证，还是 API 密钥与接口鉴权的问题？请选一下对应场景。','choices':[FLOWS['verification']['title'],api]}
    if text in {'怎么办','怎么弄','有问题','出问题了','不知道怎么操作','怎么操作'}:
        return {'kind':'clarify','answer':'您正在办理哪个流程？选一个入口，或直接描述遇到的问题。','choices':[FLOWS[item]['title'] for item in options]}
    return {'kind':'offer','flow_id':matched} if matched else {}


def stage_context(guidance,evidence):
    key=guidance['flow_id'];row=chapter(evidence,key)
    if not row:return None
    steps=numbered_steps(row);label,numbers=FLOWS[key]['stages'][guidance['step']]
    if any(number not in steps for number in numbers):return None
    return {'flow':FLOWS[key]['title'],'stage':label,'step':guidance['step']+1,'total':guidance['total'],
            'instructions':'仅解释当前阶段，不自动跳到后续阶段。用户说已完成仅代表其自述，不代表后台核实。不要索要密码、验证码或完整API密钥。',
            'stage_evidence':'\n'.join(steps[number] for number in numbers),'note':NOTE}


def actions_for(guidance,rows):
    key=guidance['flow_id'];options=available(rows)
    if guidance['status']=='active':
        actions=[{'type':'guide','label':'这一步已完成','message':'这一步已完成'},
                 {'type':'guide','label':'这一步怎么做','message':'这一步怎么做'}]
        if guidance['step']>0:actions.append({'type':'guide','label':'返回上一步','message':'返回上一步'})
        actions.append({'type':'guide','label':'结束指导','message':'结束指导'})
        return actions
    return [{'type':'guide','label':FLOWS[item]['title'],'message':FLOWS[item]['title']} for item in NEXT[key] if item in options]
