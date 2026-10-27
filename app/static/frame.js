(() => {
  'use strict';
  const embedded=window.parent!==window;
  const panel=document.getElementById('connection'),status=document.getElementById('status');
  let parentOrigin=null, pending=new Map(), counter=0, tokenValue='';
  function cancelPending(){for(const p of pending.values()){clearTimeout(p.timer);p.reject(new Error('身份已更新，请重新连接'));}pending.clear();}
  function tell(type,data={}){if(parentOrigin)window.parent.postMessage({type,...data},parentOrigin);}
  function getToken(){
    if(!embedded)return Promise.resolve(tokenValue);
    return new Promise((resolve,reject)=>{
      const id=String(++counter),timer=setTimeout(()=>{pending.delete(id);reject(new Error('客服登录连接超时，请重新登录'));},15000);
      pending.set(id,{resolve,reject,timer});tell('smarttitu:token-request',{id});
    });
  }
  function start(){
    window.SmartTITUAssistant.configure({apiBase:location.origin,layout:'iframe',getToken,onResize:embedded?(expanded)=>tell('smarttitu:resize',{expanded}):null,onClose:embedded?()=>tell('smarttitu:close'):null});
    panel.hidden=true;window.SmartTITUAssistant.open();
  }
  async function connect(){
    if(!embedded){status.textContent='请输入短期测试凭证以体验完整对话。';document.getElementById('login').hidden=false;return;}
    const candidate=new URLSearchParams(location.search).get('parent_origin');
    let parsed;try{parsed=new URL(candidate);}catch{throw new Error('嵌入地址缺少有效的 parent_origin');}
    if(!['http:','https:'].includes(parsed.protocol)||parsed.origin!==candidate)throw new Error('嵌入来源无效');
    const response=await fetch('/widget/config',{cache:'no-store',credentials:'omit'});
    if(!response.ok)throw new Error('无法读取客服接入配置');
    const config=await response.json();
    if(candidate!==location.origin && !config.frame_origins.includes(candidate))throw new Error('当前企业页面尚未获授权，请联系管理员配置 FRAME_ORIGINS');
    parentOrigin=candidate;
    window.addEventListener('message',event=>{
      if(event.source!==window.parent||event.origin!==parentOrigin)return;
      const data=event.data;if(!data||typeof data!=='object')return;
      if(data.type==='smarttitu:token-response'){
        const request=pending.get(data.id);if(!request)return;
        pending.delete(data.id);clearTimeout(request.timer);
        if(typeof data.token==='string' && data.token.length>0 && data.token.length<=4096)request.resolve(data.token);
        else request.reject(new Error('登录已失效，请重新登录企业控制台'));
      }else if(data.type==='smarttitu:reset'){cancelPending();window.SmartTITUAssistant.reset();}
      else if(data.type==='smarttitu:open'){start();}
    });
    tell('smarttitu:ready');start();
  }
  document.getElementById('login').addEventListener('submit',event=>{
    event.preventDefault();const field=document.getElementById('token');tokenValue=field.value.trim().replace(/^Bearer\s+/i,'');field.value='';if(tokenValue)start();
  });
  connect().catch(error=>{status.textContent=error.message;});
})();
