'use strict';
let demoToken='';
document.getElementById('connect').addEventListener('click',()=>{
  const token=document.getElementById('token');
  demoToken=token.value.trim().replace(/^Bearer\s+/i,'');
  if(!demoToken){document.getElementById('status').textContent='请先填写短期凭证';return;}
  token.value='';
  window.SmartTITUAssistant.configure({apiBase:location.origin,getToken:async()=>demoToken});
  document.getElementById('status').textContent='已设置凭证，请在客服中开始提问';
  window.SmartTITUAssistant.open();
});
