
'use strict';
let demoToken='',connectVersion=0,pendingQuestion='';
let automaticCheck=null,automaticToken='',automaticExpires=0,automaticPending=null;
async function automaticEnabled(){
  if(!automaticCheck)automaticCheck=(async()=>{
    try{const response=await fetch('/widget/config',{cache:'no-store',credentials:'same-origin',signal:AbortSignal.timeout(10000)});return response.ok&&(await response.json()).demo_auto_login===true;}
    catch{return false;}
  })();
  return automaticCheck;
}
async function getAutomaticToken(){
  if(automaticToken&&Date.now()<automaticExpires-60000)return automaticToken;
  if(!automaticPending)automaticPending=(async()=>{
    const response=await fetch('/widget/demo-auth',{cache:'no-store',credentials:'same-origin',headers:automaticToken?{Authorization:'Bearer '+automaticToken}:{},signal:AbortSignal.timeout(10000)});
    if(!response.ok)throw new Error('测试入口已关闭或暂时不可用，请联系管理员。');
    const payload=await response.json();
    if(typeof payload.token!=='string'||!payload.token)throw new Error('测试凭证获取失败');
    automaticToken=payload.token;automaticExpires=Date.now()+Math.min(3600,Number(payload.expires_in)||3600)*1000;return automaticToken;
  })().finally(()=>{automaticPending=null;});
  return automaticPending;
}
const connectionDialog=document.getElementById('connection-dialog');
function showConnection(question='') {
  pendingQuestion=question;
  if(!connectionDialog.open)connectionDialog.showModal();
  document.getElementById('token').focus();
}
async function openSupport(question='') {
  if(!demoToken&&!await automaticEnabled()){showConnection(question);return;}
  if(question)await window.SmartTITUAssistant.ask(question);
  else await window.SmartTITUAssistant.open();
}
document.querySelectorAll('[data-connect]').forEach(button=>button.addEventListener('click',()=>openSupport()));
document.querySelectorAll('[data-ask]').forEach(button=>button.addEventListener('click',()=>openSupport(button.dataset.ask)));
document.getElementById('connection-close').addEventListener('click',()=>connectionDialog.close());
document.getElementById('connection-form').addEventListener('submit',async event=>{
  event.preventDefault();
  const token=document.getElementById('token'),status=document.getElementById('status'),button=document.getElementById('connect');
  const entered=token.value.trim().replace(/^Bearer\s+/i,'');
  if(entered)demoToken=entered;
  if(!demoToken){status.textContent='请先填写短期凭证';return;}
  const version=++connectVersion;button.disabled=true;token.value='';
  window.SmartTITUAssistant.configure({apiBase:location.origin,getToken:async()=>demoToken});
  status.textContent='正在连接客服，请稍候…';
  try {
    const connected=await window.SmartTITUAssistant.open();
    if(version!==connectVersion)return;
    status.textContent=connected ? '已连接，可以开始咨询' : '连接未成功，请查看客服窗口中的提示后重试';
    if(connected){connectionDialog.close();const question=pendingQuestion;pendingQuestion='';if(question)await window.SmartTITUAssistant.ask(question);}
  }catch{if(version===connectVersion)status.textContent='连接未成功，请刷新页面重试';}
  finally{if(version===connectVersion)button.disabled=false;}
});

// The floating launcher also uses the same credential dialog before authentication.
window.SmartTITUAssistant.configure({apiBase:location.origin,getToken:async()=>{
  if(demoToken)return demoToken;
  if(await automaticEnabled())return getAutomaticToken();
  showConnection();throw new Error('请先连接客服。');
}});
