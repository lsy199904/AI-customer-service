
'use strict';
let demoToken='',connectVersion=0;
document.getElementById('connect').addEventListener('click',async()=>{
  const token=document.getElementById('token'),status=document.getElementById('status');
  const entered=token.value.trim().replace(/^Bearer\s+/i,'');
  if(entered)demoToken=entered;
  if(!demoToken){status.textContent='请先填写短期凭证';return;}
  const version=++connectVersion;
  token.value='';
  window.SmartTITUAssistant.configure({apiBase:location.origin,getToken:async()=>demoToken});
  status.textContent='正在连接客服，请稍候…';
  try {
    const connected=await window.SmartTITUAssistant.open();
    if(version!==connectVersion)return;
    status.textContent=connected ? '已连接，可以开始咨询' : '连接未成功，请查看客服窗口中的提示后重试';
  }catch{if(version===connectVersion)status.textContent='连接未成功，请刷新页面重试';}
});
