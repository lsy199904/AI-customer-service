"""Build standalone HTML from the production widget and the customer KB.
The replacement transport is explicitly local and has no network/model calls.
"""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parent.parent

TRANSPORT=r'''
  const prototypeKnowledge = __KNOWLEDGE__;
  const prototypeSessions = new Map();
  const prototypeMessages = new Map();
  function prototypeTerms(text) {
    text=text.toLowerCase().replace(/apikey/g,'api key').replace(/密钥/g,'api key').replace(/收费/g,'计费').replace(/报错/g,'错误');
    for(const stop of ['请问','如何','怎么','什么','可以','是否','你们','我们','这个','那个','的','了','吗','呢','我','想','请','是','有','在','要'])text=text.split(stop).join(' ');
    const out=text.match(/[a-z0-9_]+/g)||[];
    for(const run of text.match(/[\u3400-\u9fff]+/g)||[])for(let i=0;i<run.length-1;i++)out.push(run.slice(i,i+2));
    return [...new Set(out)];
  }
  function prototypeCitation(row) {return {id:row.id,title:row.title,source_file:row.source_file,pages:row.source_pages,version:row.version,url:'/v1/sources/'+row.id,document_url:null};}
  async function request(path, method='GET', body) {
    // Offline transport only. The deployable widget retains real authenticated fetch calls.
    const contact={phone:'4008841883',email:'help@china-entercom.net',wechat_qr_url:null};
    if(path==='/v1/bootstrap')return {welcome:'您好，我是 SmartTITU 智能客服。您可以询问产品、接入、计费或常见故障。当前为离线原型，回答来自本地知识摘录。',quick_questions:['如何开通账号?','如何创建 API 密钥?','平台如何计费?','调用出现429错误怎么办?','如何联系人工客服?'],idle_timeout_seconds:1800,contact,answer_mode:'extractive'};
    if(path==='/v1/sessions'&&method==='GET')return {items:[...prototypeSessions.values()].sort((a,b)=>b.updated_at-a.updated_at)};
    if(path==='/v1/sessions'&&method==='POST') {
      const id='offline-'+Date.now()+'-'+Math.random().toString(36).slice(2);
      prototypeSessions.set(id,{session_id:id,context:body.context,updated_at:Date.now()/1000});prototypeMessages.set(id,[]);return {session_id:id};
    }
    if(path.startsWith('/v1/sources/')) {
      const row=prototypeKnowledge.find(r=>r.id===decodeURIComponent(path.split('/').pop()));if(!row)throw new Error('来源不存在');return {...prototypeCitation(row),content:row.content};
    }
    const match=path.match(/^\/v1\/sessions\/([^/]+)(\/messages)?/);
    if(!match)throw new Error('离线原型不支持该操作');
    const id=match[1];if(!prototypeSessions.has(id))throw new Error('会话不存在');
    if(!match[2]&&method==='DELETE'){prototypeSessions.delete(id);prototypeMessages.delete(id);return {deleted:true};}
    const messages=prototypeMessages.get(id);
    if(method==='GET')return {items:messages,next_before:null};
    const question=body.message;
    const cached=messages.find(m=>m.response?.request_id===body.request_id);if(cached)return cached.response;
    let query=question;
    if(question.length<18&&/它|这个|那个|还有|然后|怎么办|怎么配置/.test(question)){
      const prior=[...messages].reverse().find(m=>m.role==='user');if(prior)query=prior.content+' '+question;
    }
    const terms=prototypeTerms(query);
    const ranked=prototypeKnowledge.map(row=>{
      const title=new Set(prototypeTerms(row.title)),content=new Set(prototypeTerms(row.content));
      let shared=0,score=0;
      for(const term of terms){if(title.has(term)||content.has(term))shared++;if(title.has(term))score+=4;if(content.has(term))score++;}
      return {row,score:score*(terms.length?shared/terms.length:0),coverage:terms.length?shared/terms.length:0};
    }).filter(r=>r.coverage>=.5&&r.score>=4).sort((a,b)=>b.score-a.score);
    let selected=ranked[0]?.row;
    let answer='当前知识库没有足够信息回答这个问题。请联系人工客服进一步确认。';let reason='no_knowledge';
    if(/转人工|人工客服|联系人工|联系客服/.test(question)){selected=null;answer='您可以通过以下渠道联系人工客服。';reason='requested_handoff';}
    else if(/(我的|我们|本企业|本公司|当前).{0,15}(余额|订单|认证状态|剩余)|创建.{0,5}工单/.test(question)) {selected=null;answer='一期助手未连接实时业务查询或工单系统，请联系人工客服确认。';reason='business_tool_unavailable';}
    else if(selected){answer='以下为本地知识摘录（离线原型，未调用大模型）：\n'+selected.content;reason='extractive';}
    const result={session_id:id,request_id:body.request_id,message_id:'p-'+Date.now(),answer,status:selected?'answered':'handoff',reason,answer_mode:'extractive',citations:selected?[prototypeCitation(selected)]:[],handoff:!selected,contact:selected?null:contact,created_at:Date.now()/1000};
    messages.push({message_id:'u-'+Date.now(),role:'user',content:question},{message_id:result.message_id,role:'assistant',content:answer,response:result});prototypeSessions.get(id).updated_at=Date.now()/1000;
    return result;
  }
'''

def build():
    rows=[json.loads(x) for x in (ROOT/'data/knowledge.jsonl').read_text().splitlines() if x.strip()]
    rows=[r for r in rows if r.get('audience')=='customer' and r.get('status')=='source_based']
    widget=(ROOT/'app/static/widget.js').read_text()
    start=widget.index('  async function request(');end=widget.index('  function scroll()',start)
    transport=TRANSPORT.replace('__KNOWLEDGE__',json.dumps(rows,ensure_ascii=False).replace('<','\\u003c'))
    # Double escaping in raw strings is needed in Python source only; output uses JS regex escapes.
    transport=transport.replace('\\\\','\\')
    widget=widget[:start]+transport+'\n'+widget[end:]
    html=(ROOT/'prototype/layout.template').read_text().replace('/*__OFFLINE_WIDGET__*/',widget.replace('</script','<\\/script'))
    output=ROOT/'prototype/SmartTITU_功能原型.html';output.write_text(html)
    print('Generated standalone prototype:',output)
    return output
if __name__=='__main__':build()
