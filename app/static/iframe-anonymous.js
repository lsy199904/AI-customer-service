(() => {
  'use strict';
  if(window.SmartTITUAnonymousEmbed)return;
  const script=document.currentScript,base=new URL(script.src).origin;
  let host,frame,button,opened=false,ready=false,generation=0;
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
    host=document.createElement('div');host.id='smarttitu-anonymous-embed';
    const root=host.attachShadow({mode:'open'}),css=document.createElement('style');
    css.textContent=`
      :host{all:initial;font-family:Inter,-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;color:#17283b;font-size:14px;line-height:1.6}
      *{box-sizing:border-box}[hidden]{display:none!important}button{font:inherit;cursor:pointer}
      .launch{position:fixed;right:26px;bottom:24px;z-index:2147483001;color:white;font-weight:600;transition:transform .2s;width:88px;height:80px;padding:0;border:0;border-radius:20px;background:transparent;box-shadow:none;display:grid;place-items:center}
      .launch[aria-expanded="true"]{width:56px;height:52px}.launch:hover{background:transparent;transform:none}.launch:focus-visible{outline:3px solid #709cff;outline-offset:5px}
      .launch-mascot{display:block;width:100%;height:100%;object-fit:contain;filter:drop-shadow(0 6px 5px #2455ad22);animation:mascot-hop 3.6s ease-in-out infinite;transform-origin:50% 100%;pointer-events:none}
      .launch:hover .launch-mascot,.launch:focus-visible .launch-mascot,.launch[aria-expanded="true"] .launch-mascot{animation:none}
      .launch-fallback{width:64px;height:64px;border-radius:22px;background:#155de6;color:#fff;display:grid;place-items:center;font-size:32px;box-shadow:0 8px 24px #155de633}
      @keyframes mascot-hop{0%,100%{transform:translateY(0)}50%{transform:translateY(-6px)}}
      @media(max-width:500px){.launch{right:15px;bottom:18px;width:62px;height:56px;padding:0}}
      @media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
    `;
    button=document.createElement('button');button.type='button';button.className='launch';button.title='智能客服';button.setAttribute('aria-expanded','false');button.setAttribute('aria-label','打开智能客服');button.setAttribute('aria-controls','smarttitu-anonymous-panel');
    const mascot=document.createElement('img');mascot.className='launch-mascot';mascot.src=base+'/smart-bot/media/support-robot-b.png';mascot.alt='';mascot.width=88;mascot.height=80;
    mascot.onerror=()=>{const fallback=document.createElement('span');fallback.className='launch-fallback';fallback.textContent='✦';button.replaceChildren(fallback);};button.append(mascot);
    frame=document.createElement('iframe');frame.id='smarttitu-anonymous-panel';frame.title='SmartTITU 智能客服';frame.hidden=true;frame.referrerPolicy='no-referrer';
    frame.style.cssText='position:fixed;right:16px;bottom:84px;z-index:2147483002;width:min(414px,calc(100vw - 32px));height:min(680px,calc(100dvh - 100px));border:1px solid #dfe7f0;border-radius:18px;background:white;box-shadow:0 18px 60px #203c6530';
    frame.src=base+'/smart-bot/chatbot/anonymous?parent_origin='+encodeURIComponent(location.origin);
    button.onclick=()=>opened?close():open();window.addEventListener('message',message);
    root.append(css,button,frame);document.body.append(host);
  }
  window.SmartTITUAnonymousEmbed={open:()=>open(),close:()=>close(),reset:()=>reset(),destroy(){reset();window.removeEventListener('message',message);host.remove();delete window.SmartTITUAnonymousEmbed;}};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
})();
