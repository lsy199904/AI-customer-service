 'use strict';
let userId='';
try{userId=localStorage.getItem('smarttitu-v3-user-id')||'';}catch{}
let cachedToken='',expires=0,pendingQuestion='';
const dialog=document.getElementById('connection-dialog');
const field=document.getElementById('token');
function showConnection(question=''){pendingQuestion=question;field.value=userId;if(!dialog.open)dialog.showModal();field.focus();}
async function getToken(){
  if(!userId){showConnection();throw new Error('请先输入用户ID');}
  if(cachedToken&&Date.now()<expires-60000)return cachedToken;
  const response=await fetch('/widget/user-auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:userId}),cache:'no-store',signal:AbortSignal.timeout(10000)});
  const data=await response.json();
  if(!response.ok)throw new Error(data.error?.message||'身份入口不可用');
  cachedToken=data.token;expires=Date.now()+data.expires_in*1000;return cachedToken;
}
window.SmartTITUAssistant.configure({apiBase:location.origin,getToken});
async function openSupport(question=''){
 if(!userId){showConnection(question);return;}
 if(question)await window.SmartTITUAssistant.ask(question);else await window.SmartTITUAssistant.open();
}
document.querySelectorAll('[data-connect]').forEach(b=>b.addEventListener('click',()=>openSupport()));
document.querySelectorAll('[data-ask]').forEach(b=>b.addEventListener('click',()=>openSupport(b.dataset.ask)));
document.getElementById('connection-close').onclick=()=>dialog.close();
document.getElementById('switch-user').onclick=()=>{try{localStorage.removeItem('smarttitu-v3-user-id');}catch{}location.reload();};
document.getElementById('connection-form').onsubmit=async event=>{
 event.preventDefault();const value=field.value.trim(),status=document.getElementById('status'),button=document.getElementById('connect');
 if(!/^[A-Za-z0-9][A-Za-z0-9_.@-]{0,63}$/.test(value)){status.textContent='请输入1至64位用户ID，支持字母、数字及_.@-';return;}
 userId=value;cachedToken='';button.disabled=true;
 try{await getToken();try{localStorage.setItem('smarttitu-v3-user-id',userId);}catch{}
 dialog.close();await openSupport(pendingQuestion);pendingQuestion='';}
 catch(error){status.textContent=error.message;}finally{button.disabled=false;}
};
