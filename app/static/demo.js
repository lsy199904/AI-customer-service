
'use strict';
let demoToken='',connectVersion=0,pendingQuestion='';
const connectionDialog=document.getElementById('connection-dialog');
function showConnection(question='') {
  pendingQuestion=question;
  if(!connectionDialog.open)connectionDialog.showModal();
  document.getElementById('token').focus();
}
async function openSupport(question='') {
  if(!demoToken){showConnection(question);return;}
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
  if(!demoToken){showConnection();throw new Error('请先连接客服。');}
  return demoToken;
}});
