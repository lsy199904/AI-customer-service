"""Standalone, explicitly offline prototype using the same retrieval index and widget."""
from pathlib import Path
import base64
import json
import sys
ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from app.core import Knowledge,STOP,ALIASES,tokens
from app.conversation import REPLIES,WELCOME

TRANSPORT=r'''
  const prototypeKnowledge=__KNOWLEDGE__;
  const prototypeIndex=__INDEX__;
  const prototypeReplies=__REPLIES__;
  const prototypeMedia=__MEDIA__;
  const prototypeSessions=new Map(),prototypeMessages=new Map();
  function prototypeTerms(text) {
    text=text.toLowerCase();
    for(const [a,b] of __ALIASES__)text=text.split(a).join(b);
    for(const stop of __STOP__)text=text.split(stop).join(' ');
    const out=text.match(/[a-z0-9_]+/g)||[];
    for(const run of text.match(/[\u3400-\u9fff]+/g)||[])for(let i=0;i<run.length-1;i++)out.push(run.slice(i,i+2));
    return [...new Set(out)];
  }
  function prototypeSearch(query) {
    const terms=prototypeTerms(query),n=prototypeKnowledge.length;if(!terms.length)return [];
    const qnorm=Math.sqrt(terms.reduce((s,t)=>s+Math.pow(prototypeIndex.idf[t]||Math.log(n+1)+1,2),0));
    return prototypeKnowledge.map(row=>{
      const doc=prototypeIndex.docs[row.id],common=terms.filter(t=>doc.counts[t]);
      const coverage=common.length/terms.length,title=terms.filter(t=>doc.title.includes(t)).length/terms.length;
      const similarity=common.reduce((s,t)=>s+prototypeIndex.idf[t]*doc.vector[t],0)/(qnorm*doc.norm);
      let score=common.reduce((s,t)=>s+Math.log(1+(n-prototypeIndex.df[t]+.5)/(prototypeIndex.df[t]+.5))*doc.counts[t]*2.2/(doc.counts[t]+1.2*(.25+.75*doc.length/prototypeIndex.avg)),0);
      score=score*(.5+coverage)+title*5;
      return {row,score,coverage,similarity,title};
    }).filter(r=>r.coverage>=.5&&r.title>0&&r.similarity>=.14&&r.score>=5).sort((a,b)=>b.score-a.score);
  }
  function prototypeIntent(question) {
    const compact=question.toLowerCase().replace(/[^\u3400-\u9fffa-z0-9]/g,'');
    if(/^(你好|您好|哈喽|嗨|hello|hi|早上好|早安|下午好|晚上好|在吗|有人吗|你在吗)+(呀|啊|呢|哦|哇|哟)?$/.test(compact))return 'greeting';
    if(['你是谁','你叫什么','你是什么助手','你是什么','介绍一下你自己','你是机器人吗','你是人工吗'].includes(compact))return 'identity';
    if(['你能做什么','你有什么功能','你可以做什么','你能帮我什么','你会什么','怎么使用你'].includes(compact))return 'capabilities';
    if(/^(好的|好|嗯|嗯嗯)?(谢谢|谢谢你|感谢|多谢|谢谢啦|谢谢您)+(啦|了|呀|哦)?$/.test(compact))return 'thanks';
    if(['再见','拜拜','下次聊','bye','goodbye','先这样','没问题了'].includes(compact))return 'farewell';
    if(/转人工|人工客服|联系人工|联系客服/.test(question))return 'handoff';
    if(/(我的|我们|本企业|本公司|当前).{0,15}(余额|订单|认证状态|剩余)|创建.{0,5}工单/.test(question)&&!/如何|怎么|哪里/.test(question))return 'business';
    if(/图片|截图|示意图|架构图|产品图|流程图|二维码|logo|标识|来张图|给.*图/i.test(question))return 'image';
    return 'knowledge';
  }
  function prototypeCitation(row) {return {id:row.id,title:row.title,source_file:row.source_file,pages:row.source_pages,version:row.version,url:'/v1/sources/'+row.id,document_url:null};}
  async function request(path,method='GET',body) {
    const contact={phone:'4008841883',email:'help@china-entercom.net',wechat_qr_url:null};
    if(path==='/v1/bootstrap')return {welcome:prototypeReplies.greeting,quick_questions:['如何开通账号?','如何创建 API 密钥?','平台如何计费?','调用出现429错误怎么办?','如何联系人工客服?'],idle_timeout_seconds:1800,contact,answer_mode:'extractive'};
    if(path==='/v1/sessions'&&method==='GET')return {items:[...prototypeSessions.values()].sort((a,b)=>b.updated_at-a.updated_at)};
    if(path==='/v1/sessions'&&method==='POST') {
      const id='offline-'+Date.now()+'-'+Math.random().toString(36).slice(2);
      prototypeSessions.set(id,{session_id:id,context:body.context,updated_at:Date.now()/1000});prototypeMessages.set(id,[]);return {session_id:id};
    }
    if(path.startsWith('/v1/sources/')) {
      const row=prototypeKnowledge.find(r=>r.id===decodeURIComponent(path.split('/').pop()));if(!row)throw new Error('来源不存在');return {...prototypeCitation(row),content:row.content};
    }
    const match=path.match(/^\/v1\/sessions\/([^/]+)(\/messages)?/);if(!match)throw new Error('离线原型不支持该操作');
    const id=match[1];if(!prototypeSessions.has(id))throw new Error('会话不存在');
    if(!match[2]&&method==='DELETE'){prototypeSessions.delete(id);prototypeMessages.delete(id);return {deleted:true};}
    const messages=prototypeMessages.get(id);if(method==='GET')return {items:messages,next_before:null};
    const question=body.message,cached=messages.find(m=>m.response?.request_id===body.request_id);if(cached)return cached.response;
    const intent=prototypeIntent(question);let selected=null,images=[],success=false;
    let answer='这个问题暂时没有找到足够准确的资料，为了不误导您，建议通过下方电话或邮箱联系人工客服进一步确认。';let reason='no_knowledge';
    if(prototypeReplies[intent]){answer=prototypeReplies[intent];success=true;reason=intent;}
    else if(intent==='handoff'){answer='好的，您可以通过以下方式联系人工客服。';reason='requested_handoff';}
    else if(intent==='business'){answer='我暂时还无法直接查询企业实时数据，您可以通过下方方式联系人工客服。';reason='business_tool_unavailable';}
    else {
      let query=question;
      if(question.length<24&&/这个|那个|它|上述|刚才|然后|接下来|还有呢/.test(question)){
        const prior=[...messages].reverse().find(m=>m.role==='user');if(prior)query=prior.content+' '+question;
      }
      if(/调用失败|调用不了|不能调用|无法调用|鉴权失败|报错|错误码|\b(?:400|401|403|404|429|500|503|504)\b/i.test(question))query=question+' 调用报错 错误 排查';
      const ranked=prototypeSearch(query);selected=ranked[0]?.row;
      const candidates=prototypeMedia.filter(m=>(m.keywords||[]).some(k=>question.toLowerCase().includes(k.toLowerCase()))||(m.knowledge_ids||[]).some(k=>ranked.some(r=>r.row.id===k)));
      if(intent==='image'&&candidates.length){images=candidates;answer='找到这些相关图片，您可以点击放大查看。还想了解哪一部分呢？';success=true;reason='image';selected=null;}
      else if(selected){answer=selected.content;success=true;reason='extractive';}
    }
    const result={session_id:id,request_id:body.request_id,message_id:'p-'+Date.now(),answer,status:success?'answered':'handoff',intent,reason,answer_mode:'extractive',citations:selected?[prototypeCitation(selected)]:[],images,handoff:!success,contact:success?null:contact,created_at:Date.now()/1000};
    messages.push({message_id:'u-'+Date.now(),role:'user',content:question},{message_id:result.message_id,role:'assistant',content:answer,response:result});prototypeSessions.get(id).updated_at=Date.now()/1000;
    return result;
  }
'''

def transport_source():
    kb=Knowledge(ROOT/'data/knowledge.jsonl')
    rows=list(kb.rows.values())
    index={'idf':kb.idf,'df':dict(kb.df),'avg':kb.avg,'docs':{
        k:{'counts':dict(kb.counts[k]),'vector':kb.vectors[k],'norm':kb.norms[k],
           'length':sum(kb.counts[k].values()),'title':sorted(set(tokens(r['title'])))} for k,r in kb.rows.items()}}
    media=[]
    for row in json.loads((ROOT/'data/media.json').read_text()):
        if not row['url'].startswith('/media/'):continue
        f=ROOT/'app/static/media'/row['url'][7:]
        mime={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.gif':'image/gif'}[f.suffix.lower()]
        media.append({**row,'url':'data:'+mime+';base64,'+base64.b64encode(f.read_bytes()).decode()})
    payloads={'KNOWLEDGE':rows,'INDEX':index,'REPLIES':REPLIES,'MEDIA':media,'ALIASES':ALIASES,'STOP':STOP}
    source=TRANSPORT
    for key,value in payloads.items():source=source.replace('__'+key+'__',json.dumps(value,ensure_ascii=False).replace('<','\\u003c'))
    return source


def build():
    widget=(ROOT/'app/static/widget.js').read_text()
    start=widget.index('  async function request(');end=widget.index('  function scroll()',start)
    widget=widget[:start]+transport_source()+'\n'+widget[end:]
    html=(ROOT/'prototype/layout.template').read_text().replace('/*__OFFLINE_WIDGET__*/',widget.replace('</script','<\\/script'))
    output=ROOT/'prototype/SmartTITU_功能原型.html';output.write_text(html)
    print('Generated standalone prototype:',output);return output
if __name__=='__main__':build()
