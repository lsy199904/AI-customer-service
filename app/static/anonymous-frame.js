(() => {
  'use strict';
  const embedded=window.parent!==window;
  const panel=document.getElementById('connection'),status=document.getElementById('status');
  let parentOrigin=null,token='',expires=0,pending=null;
  function tell(type,data={}){if(parentOrigin)window.parent.postMessage({type,...data},parentOrigin);}
  async function getToken(){
    if(token&&Date.now()<expires-60000)return token;
    if(!pending)pending=(async()=>{
      const response=await fetch('/smart-bot/widget/anonymous-auth',{
        method:'POST',credentials:'same-origin',cache:'no-store',
        headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},body:'{}',signal:AbortSignal.timeout(10000)});
      const data=await response.json();
      if(!response.ok)throw new Error(data.error?.message||'客服暂时不可用，请稍后重试');
      if(typeof data.token!=='string'||!data.token)throw new Error('客服连接失败，请稍后重试');
      token=data.token;expires=Date.now()+Math.min(3600,Number(data.expires_in)||3600)*1000;
      return token;
    })().finally(()=>{pending=null;});
    return pending;
  }
  async function connect(){
    const response=await fetch('/smart-bot/widget/config',{cache:'no-store',credentials:'omit'});
    if(!response.ok)throw new Error('无法读取客服接入配置');
    const config=await response.json();
    if(!config.anonymous_widget_enabled)throw new Error('匿名客服入口未开启，请联系服务提供方');
    const candidate=new URLSearchParams(location.search).get('parent_origin');
    if(embedded&&candidate){
      let parsed;try{parsed=new URL(candidate);}catch{throw new Error('嵌入来源无效');}
      if(parsed.origin!==candidate||!['https:','http:'].includes(parsed.protocol)||
          (candidate!==location.origin&&!config.frame_origins.includes(candidate)))throw new Error('当前页面尚未获授权');
      parentOrigin=candidate;
    }
    // Without parent_origin, direct iframe embedding needs no parent JS at all.
    // The response CSP frame-ancestors still restricts every ancestor.
    if(parentOrigin)window.addEventListener('message',event=>{
      if(event.source!==window.parent||event.origin!==parentOrigin)return;
      const data=event.data;if(!data||typeof data!=='object')return;
      if(data.type==='smarttitu:reset')window.SmartTITUAssistant.reset();
      else if(data.type==='smarttitu:open')window.SmartTITUAssistant.open();
    });
    await getToken();
    window.SmartTITUAssistant.configure({apiBase:location.origin,layout:'iframe',getToken,
      onResize:parentOrigin?(expanded)=>tell('smarttitu:resize',{expanded}):null,
      onClose:parentOrigin?()=>tell('smarttitu:close'):null});
    panel.hidden=true;tell('smarttitu:ready');window.SmartTITUAssistant.open();
  }
  connect().catch(error=>{status.textContent=error.message;});
})();
