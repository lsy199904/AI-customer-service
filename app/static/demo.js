 'use strict';
let cachedToken='',expires=0,pending=null;
// Old manually entered test IDs are no longer used to select visitor identity.
try{localStorage.removeItem('smarttitu-v3-user-id');}catch{}
async function getToken(){
  if(cachedToken&&Date.now()<expires-60000)return cachedToken;
  if(!pending)pending=(async()=>{
    const response=await fetch('/widget/demo-auth',{cache:'no-store',credentials:'same-origin',headers:cachedToken?{Authorization:'Bearer '+cachedToken}:{},signal:AbortSignal.timeout(10000)});
    const data=await response.json();
    if(!response.ok)throw new Error(data.error?.message||'客服暂时不可用，请稍后重试');
    if(typeof data.token!=='string'||!data.token)throw new Error('客服连接失败，请稍后重试');
    cachedToken=data.token;expires=Date.now()+Math.min(3600,Number(data.expires_in)||3600)*1000;return cachedToken;
  })().finally(()=>{pending=null;});
  return pending;
}
window.SmartTITUAssistant.configure({apiBase:location.origin,getToken});
async function openSupport(question=''){
  if(question)await window.SmartTITUAssistant.ask(question);else await window.SmartTITUAssistant.open();
}
document.querySelectorAll('[data-connect]').forEach(b=>b.addEventListener('click',()=>openSupport()));
document.querySelectorAll('[data-ask]').forEach(b=>b.addEventListener('click',()=>openSupport(b.dataset.ask)));

// Establish or renew the visitor cookie on each page visit, without creating a chat session.
getToken().catch(()=>{});
