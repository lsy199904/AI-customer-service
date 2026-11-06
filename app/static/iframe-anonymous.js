(() => {
  'use strict';
  if(window.SmartTITUAnonymousEmbed)return;
  const script=document.currentScript,base=new URL(script.src).origin;
  let frame,button,opened=false,ready=false,generation=0;
  function post(type){if(ready)frame.contentWindow.postMessage({type},base);}
  function open(){opened=true;frame.hidden=false;button.setAttribute('aria-expanded','true');if(ready)post('smarttitu:open');}
  function close(){opened=false;frame.hidden=true;button.setAttribute('aria-expanded','false');button.focus();}
  function reset(){generation++;post('smarttitu:reset');close();}
  async function message(event){
    if(event.origin!==base||event.source!==frame.contentWindow)return;
    const data=event.data;if(!data||typeof data!=='object')return;
    if(data.type==='smarttitu:ready'){ready=true;}
    else if(data.type==='smarttitu:close')close();
    else if(data.type==='smarttitu:resize' && typeof data.expanded==='boolean'){
      frame.style.width=data.expanded?'min(860px,calc(100vw - 32px))':'min(414px,calc(100vw - 32px))';
      frame.style.height=data.expanded?'calc(100dvh - 100px)':'min(680px,calc(100dvh - 100px))';
    }

  }
  function mount(){
    button=document.createElement('button');button.type='button';button.textContent='✦ 智能客服';button.setAttribute('aria-expanded','false');button.setAttribute('aria-label','打开智能客服');
    button.style.cssText='position:fixed;right:24px;bottom:24px;z-index:2147483001;background:#135de4;color:white;border:0;border-radius:28px;padding:15px 22px;font:15px sans-serif;cursor:pointer;box-shadow:0 8px 28px #155ce53b';
    frame=document.createElement('iframe');frame.title='SmartTITU 智能客服';frame.hidden=true;frame.referrerPolicy='no-referrer';
    frame.style.cssText='position:fixed;right:16px;bottom:84px;z-index:2147483002;width:min(414px,calc(100vw - 32px));height:min(680px,calc(100dvh - 100px));border:1px solid #dfe7f0;border-radius:18px;background:white;box-shadow:0 18px 60px #203c6530';
    frame.src=base+'/chatbot/anonymous?parent_origin='+encodeURIComponent(location.origin);
    button.onclick=()=>opened?close():open();window.addEventListener('message',message);
    document.body.append(button,frame);
  }
  window.SmartTITUAnonymousEmbed={open:()=>open(),close:()=>close(),reset:()=>reset(),destroy(){reset();window.removeEventListener('message',message);frame.remove();button.remove();delete window.SmartTITUAnonymousEmbed;}};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
})();
