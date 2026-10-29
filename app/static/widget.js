(() => {
  'use strict';
  if (window.SmartTITUAssistant) return;
  const script = document.currentScript;
  let config = {
    apiBase: script?.dataset.apiBase || new URL(script?.src || location.href).origin,
    tokenEndpoint: script?.dataset.authUrl || '/api/assistant/token',
    layout: 'floating',
    onClose: null,
    onResize: null,
    getToken: null
  };
  let host, root, panel, launcher, transcript, input, sendButton, quick, status, sourcePane;
  const windowId='window-'+(crypto.randomUUID?.() || Date.now()+'-'+Math.random().toString(36).slice(2));
  let sessionId = null, initialized = false, busy = false, opened = false, expanded = false;
  let idleTimer, controller, generation = 0, retry = null, lastFocus;
  let idleSeconds = 1800;
  const style = `
    :host{all:initial;font-family:Inter,-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;color:#17283b;font-size:14px;line-height:1.6}
    *{box-sizing:border-box}button,input,textarea{font:inherit}button{cursor:pointer}button:disabled{cursor:wait;opacity:.55}button:focus-visible,a:focus-visible,textarea:focus-visible{outline:3px solid #80bbff;outline-offset:3px}
    [hidden]{display:none!important}.launch{position:fixed;right:26px;bottom:24px;z-index:2147483001;border:0;border-radius:999px;background:#135de4;color:white;padding:15px 22px;box-shadow:0 8px 28px #155ce53b;display:flex;align-items:center;gap:10px;font-weight:600;transition:transform .2s}.launch:hover{transform:translateY(-2px)}
    .icon{width:22px;height:22px;display:inline-grid;place-items:center;font-size:19px}.panel{position:fixed;right:26px;bottom:94px;z-index:2147483002;width:414px;height:min(680px,calc(100dvh - 126px));min-height:300px;background:#fff;border:1px solid #dfe7f0;border-radius:22px;box-shadow:0 18px 80px #203c6530;display:flex;flex-direction:column;overflow:hidden}
    .panel.expanded{right:16px;bottom:84px;width:min(860px,calc(100vw - 32px));height:calc(100dvh - 100px);min-height:0}header>div:not(.head-actions):not(.avatar){min-width:0}h2,.subtitle{white-space:nowrap}.head-actions{flex-shrink:0}
    header{padding:19px 20px;display:flex;align-items:center;gap:11px;background:linear-gradient(115deg,#edf5ff,#f9fcff);border-bottom:1px solid #e8eef6}.avatar{height:42px;width:42px;border-radius:14px;background:#155de6;display:grid;place-items:center;color:#fff;font-size:22px}h2{font-size:16px;line-height:1.4;margin:0;font-weight:650}.subtitle{font-size:11px;color:#6b809a}.head-actions{margin-left:auto;display:flex;gap:4px}.ghost{border:0;background:transparent;color:#62778f;border-radius:8px;padding:7px 9px}.ghost:hover{background:#e1edff;color:#135de4}
    .body{flex:1;overflow:auto;padding:20px;background:#f7f9fc;overscroll-behavior:contain}.welcome-label{font-size:11px;letter-spacing:.12em;color:#547491;margin-bottom:10px}.message{margin-bottom:17px;display:flex;flex-direction:column;align-items:flex-start}.message.user{align-items:flex-end}.message-role{display:flex;align-items:center;gap:7px;margin:0 2px 7px;color:#61758f;font-size:11px;font-weight:500}.user .message-role{flex-direction:row-reverse}.message-avatar{width:28px;height:28px;display:grid;place-items:center;border-radius:9px;background:#e6efff;color:#155de6;flex-shrink:0}.message-avatar svg{width:18px;height:18px}.user .message-avatar{background:#edf0f5;color:#65748a}.message .bubble{margin-left:2px}.message.user .bubble{margin-left:0;margin-right:2px}.bubble{white-space:pre-wrap;overflow-wrap:anywhere;max-width:94%;border-radius:3px 15px 15px 15px;padding:12px 14px;background:#fff;box-shadow:0 2px 8px #192c4a05;border:1px solid #e6ecf4;font-size:13px}.bubble a{color:#155de6;text-decoration:underline;text-underline-offset:2px}.user .bubble a{color:inherit}.bubble a:focus-visible{outline:2px solid currentColor;outline-offset:3px}.bubble pre{white-space:pre;overflow:auto;max-width:100%;background:#f1f5fa;border-radius:7px;padding:10px;font:11px/1.7 monospace}.reply-images{max-width:94%;display:flex;flex-direction:column;gap:8px;margin-top:9px}.image-button{border:1px solid #e0e8f4;border-radius:11px;background:#fff;padding:8px;text-align:left}.image-button img{display:block;max-width:100%;max-height:220px;object-fit:contain;border-radius:7px}.image-caption{color:#6380a0;font-size:11px;padding-top:5px}.preview-image{display:block;max-width:100%;max-height:75vh;object-fit:contain}.user .bubble{background:#155de6;color:#fff;border-color:#155de6;border-radius:15px 3px 15px 15px}.meta{font-size:10px;color:#73879d;margin:5px 3px}.sources{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px;max-width:100%}.source{background:#eff5ff;color:#245ba4;border:1px solid #dae7fb;border-radius:7px;font-size:11px;padding:5px 8px;text-align:left;max-width:100%}
    .quick{display:flex;flex-wrap:wrap;gap:7px;padding-top:2px;margin-bottom:18px}.quick button{border:1px solid #dce6f4;border-radius:999px;background:white;color:#34577f;font-size:12px;padding:7px 10px}.quick button:hover{border-color:#7ba6ef;background:#f0f6ff}.notice{font-size:12px;color:#9a611c;white-space:pre-wrap;margin:12px 0}.composer{padding:12px 16px 10px;border-top:1px solid #e7edf5;background:#fff}.entry{display:flex;gap:8px;align-items:flex-end;border:1px solid #d7e1ed;border-radius:13px;padding:8px}.entry:focus-within{border-color:#6797ee;box-shadow:0 0 0 2px #eaf1ff}textarea{resize:none;border:0;outline:0!important;background:transparent;flex:1;min-width:0;width:auto;height:44px;max-height:100px;font-size:13px;padding:3px 5px;color:#17283b}.send{flex-shrink:0;white-space:nowrap;border:0;border-radius:9px;color:#fff;background:#155de6;padding:9px 12px;font-size:12px}.foot{display:flex;align-items:center;justify-content:space-between;margin-top:7px;font-size:10px;color:#8a99ab}.human{border:0;padding:0;background:transparent;color:#5d789c;font-size:11px}.contact{background:#f1f6ff;border-radius:10px;padding:11px 12px;margin-top:9px;font-size:12px;max-width:100%}.contact a{display:block;color:#235cac}.contact img{display:block;width:128px;height:128px;object-fit:contain;margin-top:9px}.contact .hint{font-size:11px;color:#6b809a}
    .suggestions{margin:10px 0 0;max-width:100%}.suggestions .handoff-choice{border-color:#9cb8e6;color:#155de6;font-weight:600}
    .source-pane{position:absolute;inset:0;background:#fff;z-index:2;padding:20px;overflow:auto}.source-pane h3{font-size:15px;margin:10px 0}.source-content{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}.source-back{border:1px solid #dce6f4;background:#f5f8fc;color:#34577f;padding:6px 10px;border-radius:8px}.loading{color:#73879d;font-size:12px;padding:10px 0}.retry{border:1px solid #ddd;background:#fff;color:#9a611c;border-radius:7px;padding:5px 10px}
    @media(max-width:500px){.panel{right:12px;bottom:86px;width:calc(100vw - 24px);height:calc(100dvh - 105px);border-radius:18px}header{padding:14px 10px;gap:7px}.ghost{padding:7px}.avatar{width:32px;height:32px}h2{font-size:14px}.subtitle{font-size:10px}.launch{right:15px;bottom:18px;padding:12px 18px}}
    .panel{box-shadow:0 24px 90px #18386b26,0 2px 10px #18386b08;border-color:#e1e9f5}
    header{background:radial-gradient(ellipse at top left,#e5eeff,transparent 75%),linear-gradient(120deg,#f4f8ff,#fff)}
    .avatar{position:relative;background:linear-gradient(145deg,#4b8bff,#155de6 60%,#164ac4);box-shadow:inset 0 1px 0 #ffffff70,0 5px 14px #155de626;border-radius:14px}
    .avatar:after{content:'';position:absolute;right:-2px;bottom:-2px;width:8px;height:8px;border:3px solid #f3f7ff;border-radius:50%;background:#36c99a}
    .body{background:radial-gradient(ellipse at top right,#edf3ff85,transparent 55%),#f7f9fc}
    .message{animation:message-in .22s ease-out}.message-role{letter-spacing:.02em;margin-bottom:8px}.message-avatar{width:30px;height:30px;border-radius:10px;background:linear-gradient(145deg,#fff,#e9f0ff);border:1px solid #dbe6fc;box-shadow:0 3px 8px #244a8c09;color:#3264c8}.message-avatar svg{width:20px;height:20px;stroke-width:1.5}
    .user .message-avatar{color:#697899;background:linear-gradient(145deg,#fff,#eef0f8);border-color:#e0e4f0}.bubble{box-shadow:0 3px 12px #18386b04;border-color:#e5ebf5;padding:13px 15px}.user .bubble{background:linear-gradient(130deg,#246cf0,#1558df);box-shadow:0 4px 12px #155de61a}
    .reply-images{width:94%;gap:10px;margin-top:12px}.media-card{overflow:hidden;border:1px solid #e0e7f2;border-radius:14px;background:#fff;box-shadow:0 4px 16px #203c6507}
    .image-button{position:relative;display:block;width:100%;border:0;border-radius:0;padding:10px;background:linear-gradient(135deg,#f7faff,#eff4fb);cursor:zoom-in;overflow:hidden}.image-button img{width:100%;max-height:220px;transition:transform .25s ease}.image-button:hover img{transform:scale(1.025)}.image-zoom{position:absolute;right:16px;bottom:15px;font-size:10px;color:#375582;background:#fffffff2;padding:3px 8px;border:1px solid #e5ecf5;border-radius:6px;box-shadow:0 2px 7px #203c650c}
    .media-footer{display:flex;align-items:center;gap:10px;padding:10px 12px}.media-footer .image-caption{flex:1;min-width:0;padding:0;font-size:11px;font-weight:500;color:#526681;overflow-wrap:anywhere}.original-link{font-size:10px;white-space:nowrap;color:#5274ac;text-decoration:none;padding:3px 0}.original-link:hover{color:#155de6;text-decoration:underline}
    .sources{gap:7px;margin-top:10px}.sources .source{display:flex;align-items:center;gap:7px;border:1px solid #e2e9f4;border-radius:9px;padding:8px 10px;background:linear-gradient(120deg,#fff,#f5f8ff);box-shadow:0 2px 6px #203c6503;color:#536c94;transition:border-color .18s,box-shadow .18s}.sources .source:hover{border-color:#aac3ef;box-shadow:0 3px 9px #155de610}.source-title{min-width:0;overflow-wrap:anywhere}.source-symbol{color:#7495c6;width:14px;height:16px;flex-shrink:0}.source-arrow{color:#9bb0cf;margin-left:3px}
    .composer{padding-top:13px;background:linear-gradient(180deg,#fff,#fbfcff)}.composer .quick{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin-bottom:10px}.composer .quick button{position:relative;border-radius:9px;border-color:#e4ebf6;background:linear-gradient(130deg,#f8faff,#f1f5fd);font-size:11px;padding:8px 4px;color:#506b94;transition:background .18s,border-color .18s,transform .18s;min-width:0;white-space:nowrap}.composer .quick button:hover{background:#eaf1ff;border-color:#aac4f2;color:#155de6;transform:translateY(-1px)}
    .suggestions{gap:6px}.suggestions button{border-radius:8px;background:#fff;border-color:#e0e8f5;color:#5b7296;font-size:11px;padding:6px 9px;transition:border-color .18s,background .18s}.suggestions button:hover{border-color:#aac4f2;background:#f0f5ff}.suggestions .handoff-choice{background:#f3f7ff;border-style:dashed}
    .entry{background:#fff;border-radius:12px;box-shadow:0 2px 8px #203c6503}.send{background:linear-gradient(135deg,#3478f4,#155de6);box-shadow:0 3px 7px #155de620}.ghost:focus-visible,.quick button:focus-visible,.source:focus-visible,.image-button:focus-visible,.original-link:focus-visible{outline:2px solid #5c91e9;outline-offset:3px}.ghost,.send{transition:background .18s,box-shadow .18s}.loading{display:flex;gap:8px;align-items:center}.loading:before{content:'';width:7px;height:7px;background:#6393eb;border-radius:50%;animation:status-glow 1.2s ease-in-out infinite}
    .assistant-actions{display:flex;flex-wrap:wrap;gap:7px;max-width:94%;margin-top:10px}.assistant-actions button{border:1px solid #d6e4fb;border-radius:9px;padding:8px 11px;background:linear-gradient(125deg,#f4f8ff,#eaf2ff);color:#3566b4;font-size:12px;transition:background .18s,border-color .18s}.assistant-actions button:hover{background:#e4efff;border-color:#98b9ef}.assistant-actions button:first-child{background:#eaf2ff;color:#155de6;font-weight:600}.assistant-actions button:disabled{background:#f6f8fb;color:#9da9bc;border-color:#e9edf4;cursor:default}.assistant-actions button:focus-visible{outline:2px solid #5c91e9;outline-offset:3px}
    .guidance-media{width:94%;margin-top:12px}.guidance-media summary{font-size:11px;color:#6e88ad;cursor:pointer;padding:7px 0}.guidance-media .reply-images{width:100%;max-width:100%}
    .guidance-card{box-sizing:border-box;width:94%;margin-top:12px;padding:13px;background:linear-gradient(135deg,#fff,#f4f8ff);border:1px solid #dce7f8;border-radius:13px}.guidance-heading{display:flex;justify-content:space-between;align-items:center;gap:8px;color:#35547f;font-size:12px;font-weight:600}.guidance-badge{font-size:10px;font-weight:500;background:#eaf1ff;color:#5980b9;padding:2px 7px;border-radius:5px;white-space:nowrap}.guidance-stages{list-style:none;padding:0;margin:11px 0;display:grid;gap:7px}.guidance-stages li{display:flex;align-items:center;gap:8px;color:#96a4b9;font-size:11px}.stage-dot{display:grid;place-items:center;width:18px;height:18px;flex-shrink:0;border-radius:50%;background:#edf1f8;font-size:10px}.guidance-stages .current{color:#235eb9;font-weight:600}.current .stage-dot{background:#2468e6;color:#fff;box-shadow:0 0 0 3px #e7efff}.guidance-stages .done{color:#6d8ba7}.done .stage-dot{background:#e5f4ef;color:#409a7f}.guidance-note{font-size:10px;line-height:1.6;color:#8798b0;margin:8px 0 0}
    .streaming .bubble:after{content:'';display:inline-block;width:2px;height:1em;background:#3979df;margin-left:3px;vertical-align:-2px;animation:status-glow .8s ease-in-out infinite}
    @keyframes message-in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}@keyframes status-glow{50%{opacity:.35;box-shadow:0 0 0 4px #6393eb15}}
    @media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
  `;
  function element(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function apiURL(path) {
    const base = new URL(config.apiBase, location.href);
    if (!['http:', 'https:'].includes(base.protocol)) throw new Error('服务地址无效');
    return base.href.replace(/\/$/, '') + path;
  }
  async function token() {
    if (config.getToken) {
      const value = await config.getToken();
      if (typeof value !== 'string' || !value) throw new Error('请先登录企业控制台');
      return value;
    }
    const url = new URL(config.tokenEndpoint, location.href);
    if (url.origin !== location.origin) throw new Error('登录凭证接口必须与业务页面同源');
    const r = await fetch(url, {credentials:'same-origin', cache:'no-store'});
    if (!r.ok) throw new Error('请先登录，或由管理员配置客服登录凭证接口');
    const value = (await r.json()).token;
    if (typeof value !== 'string' || !value) throw new Error('登录凭证接口未返回 token');
    return value;
  }
  async function request(path, method = 'GET', body, correlationId) {
    const parent=controller?.signal,scope=new AbortController();
    const limit=method==='POST' && /\/messages$/.test(path) ? 180000 : 15000;
    let timedOut=false,timer;
    const onAbort=()=>scope.abort();
    const stopped=new Promise((resolve,reject)=>{
      scope.signal.addEventListener('abort',()=>reject(new Error(timedOut
        ? '连接超时，请检查网络后点击重试。'
        : '请求已取消。')),{once:true});
    });
    parent?.addEventListener('abort',onAbort,{once:true});
    if(parent?.aborted)scope.abort();
    timer=setTimeout(()=>{timedOut=true;scope.abort();},limit);
    try {
      return await Promise.race([stopped,(async()=>{
        const auth=await token();
        if(scope.signal.aborted)throw new Error('请求已取消。');
        let response;
        try {
          response=await fetch(apiURL(path), {
            method, headers:{Authorization:'Bearer ' + auth,'X-Widget-ID':windowId,...((body?.request_id || correlationId)?{'X-Request-ID':body?.request_id || correlationId}:{}), ...(body ? {'Content-Type':'application/json'} : {})},
            body:body ? JSON.stringify(body) : undefined, signal:scope.signal, credentials:'omit', cache:'no-store'
          });
        } catch(error) {
          if(scope.signal.aborted)throw error;
          throw new Error('无法连接客服，请检查网络后点击重试。');
        }
        let data;
        try {data=await response.json();}
        catch {throw new Error('客服服务返回异常，请稍后重试。');}
        if(!response.ok)throw new Error(data.error?.message || '连接暂时不可用，请稍后重试');
        return data;
      })()]);
    } finally {
      clearTimeout(timer);parent?.removeEventListener('abort',onAbort);
    }
  }
  async function streamReply(path,body,onStage,onDelta=()=>{}) {
    const scope=new AbortController(),parent=controller?.signal;
    const abort=()=>scope.abort();parent?.addEventListener('abort',abort,{once:true});
    if(parent?.aborted)scope.abort();
    const timer=setTimeout(abort,180000);
    try {
      const stopped=new Promise((resolve,reject)=>scope.signal.addEventListener('abort',()=>reject(new Error('请求已取消或超时，请稍后重试')),{once:true}));
      if(scope.signal.aborted)throw new Error('请求已取消');
      const auth=await Promise.race([token(),stopped]);
      if(scope.signal.aborted)throw new Error('请求已取消');
      const response=await fetch(apiURL(path+'/stream'),{method:'POST',headers:{Authorization:'Bearer '+auth,'Content-Type':'application/json','X-Widget-ID':windowId,'X-Request-ID':body.request_id},body:JSON.stringify(body),signal:scope.signal,credentials:'omit',cache:'no-store'});
      if(!response.ok){const data=await response.json();throw new Error(data.error?.message || '客服连接失败');}
      if(!response.body)throw new Error('浏览器不支持流式响应');
      const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',result=null;
      while(true){
        const part=await reader.read();buffer+=decoder.decode(part.value || new Uint8Array(),{stream:!part.done});
        let boundary;
        while((boundary=buffer.indexOf('\n\n'))>=0){
          const frame=buffer.slice(0,boundary);buffer=buffer.slice(boundary+2);
          const kind=frame.split('\n').find(line=>line.startsWith('event: '))?.slice(7);
          const raw=frame.split('\n').filter(line=>line.startsWith('data: ')).map(line=>line.slice(6)).join('\n');
          if(raw){const payload=JSON.parse(raw);if(kind==='status')onStage(payload.stage);if(kind==='delta'&&typeof payload.text==='string')onDelta(payload.text);if(kind==='complete')result=payload;if(kind==='error')throw new Error(payload.message || '服务暂时不可用');}
        }
        if(buffer.length>1000000)throw new Error('客服响应过大');
        if(part.done)break;
      }
      if(!result)throw new Error('回答传输中断，请重试');return result;
    } catch(error){if(scope.signal.aborted)throw new Error('请求已取消或超时，请稍后重试');if(error instanceof TypeError)throw new Error('无法连接客服，请检查网络后点击重试。');throw error;}
    finally{clearTimeout(timer);parent?.removeEventListener('abort',abort);}
  }
  function scroll() { transcript.scrollTop = transcript.scrollHeight; }
  function activity() {
    clearTimeout(idleTimer);
    if (opened) idleTimer = setTimeout(close, idleSeconds * 1000);
  }
  function sourceLabel(source) {
    const raw=source.section_title || source.title || '知识说明';
    const title=String(raw).replace(/^用户手册[：:\s-]*/, '')
      .replace(/^问题\s*\d+\s*(?:第\s*\d+\s*页\s*)?/, '')
      .replace(/^\d+(?:\.\d+)*[.、\s]+/, '').trim();
    return '用户手册：'+(title || '知识说明');
  }
  function roleAvatar(role) {
    const holder=element('span','message-avatar');holder.setAttribute('aria-hidden','true');
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    for(const [key,value] of Object.entries({viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.6','stroke-linecap':'round','stroke-linejoin':'round'}))svg.setAttribute(key,value);
    const path=document.createElementNS('http://www.w3.org/2000/svg','path');
    path.setAttribute('d',role==='assistant'
      ?'M12 3v3m-6 0h12a2 2 0 0 1 2 2v9a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3V8a2 2 0 0 1 2-2ZM8 11v2m8-2v2m-8 3c2 1.5 6 1.5 8 0M1.5 10v5m21-5v5M11 2h2'
      :'M16 8a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM4.5 21v-2a7.5 7.5 0 0 1 15 0v2M9 16.2l3 2.3 3-2.3');
    svg.append(path);holder.append(svg);return holder;
  }
  function message(role, text, response) {
    if(role==='assistant')transcript.querySelectorAll('.assistant-actions button').forEach(button=>{button.disabled=true;});
    const row = element('div', 'message ' + role);
    const identity=element('div','message-role');
    identity.append(roleAvatar(role),element('span','',role==='assistant'?'SmartTITU 智能客服':'您'));
    row.append(identity);
    const bubble=element('div','bubble');
    const displayText=role==='assistant' ? customerText(text) : text;
    if(String(displayText || '').trim() || !response?.images?.length) {
      renderText(bubble,displayText);row.append(bubble);
    }
    let evidenceParent=row;
    if(response?.guidance){
      renderGuidance(row,response.guidance);
      if(response?.actions?.length)renderAssistantActions(row,response.actions);
      if(response.guidance.status==='active'&&(response.images?.length||response.citations?.length)){
        evidenceParent=element('details','guidance-media');evidenceParent.append(element('summary','','查看流程图与用户手册'));row.append(evidenceParent);
      }
    }
    if(response?.images?.length)renderImages(evidenceParent,response.images);
    if (response?.citations?.length) {
      const list = element('div', 'sources');
      response.citations.forEach((source, i) => {
        const b = element('button', 'source');b.setAttribute('aria-label',sourceLabel(source));
        const symbol=element('span','source-symbol','▤');symbol.setAttribute('aria-hidden','true');
        const arrow=element('span','source-arrow','›');arrow.setAttribute('aria-hidden','true');
        b.append(symbol,element('span','source-title',sourceLabel(source)),arrow);
        b.type = 'button'; b.addEventListener('click', () => showSource(source)); list.append(b);
      });
      evidenceParent.append(list);
    }
    if(!response?.guidance&&response?.status!=='suggestions'&&response?.actions?.length)renderAssistantActions(row,response.actions);
    if(response?.status==='suggestions')renderSuggestions(row,response);
    if (response?.handoff && response.contact) renderContact(row, response.contact);
    if(role==='assistant'&&response?.status==='suggestions')renderRequestReference(row,response.request_id);
    transcript.append(row); scroll(); return row;
  }
  function renderAssistantActions(parent,actions) {
    const group=element('div','assistant-actions');group.setAttribute('aria-label','对话操作');
    for(const action of actions.slice(0,6)) {
      if(!['guide','clarify'].includes(action.type)||typeof action.label!=='string'||typeof action.message!=='string'||action.label.length>80||action.message.length>200)continue;
      const button=element('button','',action.label);button.type='button';button.onclick=()=>send(action.message);group.append(button);
    }
    if(group.childNodes.length)parent.append(group);
  }
  function renderGuidance(parent,guide) {
    if(!Array.isArray(guide.stages)||!Number.isInteger(guide.step)||guide.step<0||guide.step>=guide.stages.length||guide.stages.length>8)return;
    const card=element('section','guidance-card');card.setAttribute('aria-label','流程陪办');
    const header=element('div','guidance-heading');
    header.append(element('span','',guide.title || '分步指导'),element('span','guidance-badge',guide.status==='completed'?'指导已完成':guide.status==='ended'?'已结束':`${guide.step+1} / ${guide.stages.length}`));
    card.append(header);
    const stages=element('ol','guidance-stages');
    guide.stages.forEach((title,index)=>{
      const done=guide.status==='completed'||index<guide.step;
      const item=element('li',done?'done':index===guide.step?'current':'');
      item.append(element('span','stage-dot',done?'✓':String(index+1)),element('span','',String(title).slice(0,80)));
      if(index===guide.step&&guide.status==='active')item.setAttribute('aria-current','step');stages.append(item);
    });
    card.append(stages);
    if(guide.notice)card.append(element('p','guidance-note',String(guide.notice).slice(0,200)));
    card.append(element('p','guidance-note','进度依据您的反馈记录，未连接后台办理或核实状态。'));parent.append(card);
  }
  function renderRequestReference(parent,id) {
    if(typeof id!=='string'||!/^[-a-zA-Z0-9_]{8,80}$/.test(id))return;
    const details=element('details','meta');
    details.append(element('summary','','反馈问题'));
    details.append(element('div','','问题编号：'+id));
    const copy=element('button','source','复制问题编号');copy.type='button';
    copy.onclick=async()=>{
      try {await navigator.clipboard.writeText(id);copy.textContent='已复制';}
      catch {copy.textContent='请选中上方编号复制';}
    };
    details.append(copy);parent.append(details);
  }
  function renderSuggestions(parent,response) {
    const group=element('div','quick suggestions');group.setAttribute('aria-label','推荐问题');
    for(const question of (Array.isArray(response.suggestions)?response.suggestions:[]).slice(0,6)) {
      if(typeof question!=='string'||question.length>120||!question.trim())continue;
      const button=element('button','',question);button.type='button';button.onclick=()=>send(question);group.append(button);
    }
    if(Array.isArray(response.actions)&&response.actions.some(action=>action?.type==='handoff')) {
      const button=element('button','handoff-choice','以上都不是，转人工');button.type='button';button.onclick=()=>send('转人工客服');group.append(button);
    }
    parent.append(group);
  }
  function customerText(text) {
    // Saved answers keep their payload; render registered images only in the bottom gallery.
    const cleaned=String(text || '').replace(/^以下为(?:知识库原文摘录|本地知识摘录|知识原文摘录)[（(][^）)]*[）)][：:]?\s*/,'')
      .replace(/[（(]\s*(?:KB|DOC)-[a-f0-9]{3,64}\s*[）)]/gi,'')
      .replace(/\b(?:KB|DOC)-[a-f0-9]{3,64}\b/gi,'');
    return cleaned.split(/(```[\s\S]*?```)/g).map((part,index)=>index%2?part:part
      .replace(/(?:\*\*)?适用版本[：:][ \t]*(?:\*\*)?\d{4}[-/]\d{1,2}[-/]\d{1,2}[ \t]*[vV]\d+(?:\.\d+)*(?:\*\*)?[。.]?/g,'')
      .replace(/^[ \t]*(?:更多详情|更多信息|详细内容|详情)[^\n]*(?:手册|原文档|原始文档|PDF)[^\n]*(?:\n[ \t]*)*(?:https?:\/\/[^\n]+|\[[^\]\n]+\]\(https?:\/\/[^\n]+\))?/gim,'')
      .replace(/\[[^\]\n]*\]\(https?:\/\/raw\.githubusercontent\.com\/lsy199904\/AI-customer-service\/[^)\n]*docs\/sources\/[^)\n]*\)/gi,'')
      .replace(/^[ \t]*https?:\/\/raw\.githubusercontent\.com\/lsy199904\/AI-customer-service\/[^\n]*docs\/sources\/[^\n]*$/gim,'')
      .replace(/![ \t]*\[[^\]\n]*\]\((?:[^()\n]|\([^()\n]*\))*\)/g,'')
      .replace(/![ \t]*\[[^\]\n]*\]\[[^\]\n]*\]/g,'')
      .replace(/<img\b[^>]*>/gi,'')
      .replace(/^[ \t]*(?:图片\s*URL|图片链接|配图链接)[ \t]*[:：][ \t]*https?:\/\/\S+[ \t]*$/gim,'')
      .replace(/^[ \t]*(?:#{1,6}[ \t]*)?(?:\*\*)?(?:图片展示|配图展示|相关配图|图片预览|相关图片|配图|图片)(?:\*\*)?[ \t]*[:：]?[ \t]*(?:\*\*)?[ \t]*$/gm,'')
    ).join('').replace(/\n[ \t]*\n(?:[ \t]*\n)+/g,'\n\n').trim();
  }
  function appendLinkedText(parent,text) {
    const pattern=/\[([^\]\n]+)\]\((https?:\/\/[^\s<>"`\(\)]+)\)|https?:\/\/[^\s<>"`，。；！？、（）【】]+/gi;
    let offset=0;
    for(const match of text.matchAll(pattern)) {
      parent.append(document.createTextNode(text.slice(offset,match.index)));
      const markdown=match[1]!==undefined;
      let address=markdown?match[2]:match[0],suffix='';
      if(!markdown) {
        while(/[.,;!?:]$/.test(address)||(/[)\]]$/.test(address)&&
          (address.split(address.endsWith(')')?'(':'[').length<address.split(address.endsWith(')')?')':']').length))) {
          suffix=address.slice(-1)+suffix;address=address.slice(0,-1);
        }
      }
      let valid=false;
      try {const url=new URL(address);valid=['http:','https:'].includes(url.protocol)&&!!url.hostname&&!url.username&&!url.password;}catch {}
      if(valid) {
        const link=element('a','',markdown?match[1]:address);
        link.href=address;link.target='_blank';link.rel='noopener noreferrer';
        parent.append(link);
        if(suffix)parent.append(document.createTextNode(suffix));
      } else parent.append(document.createTextNode(match[0]));
      offset=match.index+match[0].length;
    }
    parent.append(document.createTextNode(text.slice(offset)));
  }
  function renderText(parent,text) {
    const parts=String(text || '').split(/```(?:[a-zA-Z0-9_-]+)?\n([\s\S]*?)```/g);
    parts.forEach((part,index)=>{
      if(!part)return;
      if(index%2)parent.append(element('pre','',part));
      else appendLinkedText(parent,part);
    });
  }
  function safeImage(value) {
    if(typeof value!=='string')return null;
    if(/^data:image\/(?:png|jpeg|webp|gif);base64,[a-zA-Z0-9+/=]+$/.test(value)&&value.length<2*1024*1024)return value;
    if(/^\/media\/[a-zA-Z0-9][a-zA-Z0-9_.-]*$/.test(value)) {
      try{return apiURL(value);}catch{return null;}
    }
    return safeHTTPS(value);
  }
  function renderImages(parent,images) {
    const group=element('div','reply-images'),seen=new Set();
    images.slice(0,4).forEach(picture=>{
      const url=safeImage(picture.url);if(!url)return;let key=url;try{const path=new URL(url).pathname;const media=path.match(/\/(?:app\/static\/)?media\/([^/]+)$/);if(media)key='media/'+media[1];}catch{}if(seen.has(key))return;seen.add(key);
      const button=element('button','image-button');button.type='button';button.setAttribute('aria-label','查看图片：'+(picture.title || picture.alt || '相关图片'));
      const image=element('img');image.src=url;image.alt=picture.alt || picture.title || '相关图片';image.loading='lazy';image.referrerPolicy='no-referrer';
      image.onerror=()=>{button.replaceChildren(element('span','image-caption','图片暂时无法显示，请稍后重试。'));button.disabled=true;};
      const hint=element('span','image-zoom','⤢ 点击放大');hint.setAttribute('aria-hidden','true');
      button.append(image,hint);
      const card=element('article','media-card'),footer=element('div','media-footer');
      footer.append(element('div','image-caption',picture.title || '相关图片'));
      button.onclick=()=>{
        sourcePane.hidden=false;sourcePane.replaceChildren();
        const back=element('button','source-back','← 返回对话');back.onclick=()=>{sourcePane.hidden=true;input.focus();};
        const large=element('img','preview-image');large.src=url;large.alt=image.alt;large.referrerPolicy='no-referrer';
        sourcePane.append(back,element('h3','',picture.title || '图片详情'),large);back.focus();
      };card.append(button,footer);group.append(card);
      if(!url.startsWith('data:')) {
        const original=element('a','original-link','查看原图 ↗');original.href=url;original.target='_blank';original.rel='noopener noreferrer';
        footer.append(original);
      }
    });
    if(group.childNodes.length)parent.append(group);
  }
  function safeHTTPS(value) {
    try { const u = new URL(value); return u.protocol === 'https:' && !u.username && !u.password ? u.href : null; }
    catch { return null; }
  }
  function renderContact(parent, contact) {
    const box = element('div', 'contact');box.append(element('div', '', '联系人工客服'));
    function copyRow(label,value) {
      const line=element('div','contact-row');const text=element('span','contact-value',label+'：'+value);
      const copy=element('button','contact-copy','复制');copy.type='button';copy.setAttribute('aria-label','复制'+label);
      const result=element('span','hint');result.setAttribute('role','status');
      copy.onclick=async()=>{
        let copied=false;
        try{await navigator.clipboard.writeText(value);copied=true;}catch{
          const field=element('textarea');field.value=value;field.setAttribute('readonly','');field.style.cssText='position:fixed;left:0;top:0;width:1px;height:1px;opacity:0';box.append(field);
          try{field.focus();field.select();copied=document.execCommand('copy');}catch{}finally{field.remove();copy.focus();}
        }
        copy.textContent=copied?'已复制':'复制';result.textContent=copied?'':'复制失败，请选中号码或邮箱手动复制';
      };
      line.append(text,copy);box.append(line,result);
    }
    if (/^[+\d -]{3,30}$/.test(contact.phone || '')) copyRow('电话',contact.phone);
    if (/^[a-zA-Z0-9_.+%-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/.test(contact.email || '')) copyRow('邮箱',contact.email);
    const qr = safeImage(contact.wechat_qr_url);
    if (qr) {
      const img = element('img');img.src=qr;img.alt='企业微信人工客服二维码';img.referrerPolicy='no-referrer';box.append(img);
      box.append(element('div', 'hint', '微信扫码联系人工客服'));
    }
    box.append(element('div', 'hint', '也可以联系您的专属客户经理，我们会协助您进一步处理。'));
    parent.append(box);
  }
  function notice(text, retryAction) {
    status.textContent = text; status.hidden=false;
    if (retryAction) {
      const b=element('button','retry','重试'); b.type='button'; b.onclick=retryAction;status.append(document.createTextNode(' '),b);
    }
    scroll();
  }
  function clearStatus() { status.textContent='';status.hidden=true; }
  function setBusy(value) { busy=value;sendButton.disabled=value;input.disabled=value; }
  async function initialize(version) {
    setBusy(true); transcript.replaceChildren();quick.replaceChildren();clearStatus();
    transcript.append(element('div','loading','正在连接客服…'));
    try {
      const boot=await request('/v1/bootstrap');
      config.streaming=boot.capabilities?.streaming===true;
      if (version !== generation) return;
      idleSeconds=boot.idle_timeout_seconds || 1800;
      // Restore only the most recent session belonging to the authenticated user, as verified by the backend.
      transcript.firstChild.textContent='正在加载您的会话…';
      const sessions=await request('/v1/sessions');
      if (version !== generation) return;
      sessionId=sessions.items?.[0]?.session_id || null;
      let history={items:[]};
      if (sessionId) {transcript.firstChild.textContent='正在恢复历史对话…';history=await request(`/v1/sessions/${sessionId}/messages`);}
      if (version !== generation) return;
      transcript.replaceChildren();
      transcript.append(element('div','welcome-label','SMARTTITU · 企业智能服务'));
      message('assistant',boot.welcome);
      renderHistory(history);
      (boot.quick_questions || []).forEach(q => {
        const b=element('button','',q);b.type='button';b.onclick=()=>send(q);quick.append(b);
      });
      initialized=true;activity();return true;
    } catch (err) {
      if (version !== generation) return;
      transcript.replaceChildren();notice(err.message,()=>refresh());return false;
    } finally { if(version === generation) { setBusy(false);input.focus(); } }
  }
  async function refresh() {
    controller?.abort();controller=new AbortController();const v=++generation;
    return initialize(v);
  }
  async function send(value, retrying=false) {
    const text=(value ?? input.value).trim();
    if (!text || busy) return;
    if (!initialized) { notice('请先完成客服连接。',()=>refresh());return; }
    if (text.length>2000) { notice('问题不能超过2000字');return; }
    const v=generation;setBusy(true);clearStatus();activity();
    const rid=retrying && retry?.text===text ? retry.id : ('msg-'+(crypto.randomUUID?.() || Date.now()+'-'+Math.random().toString(36).slice(2)));
    if (!retrying) message('user',text);
    input.value='';retry={text,id:rid};
    let live=null,liveText='';
    const loading=element('div','loading','正在为您解答…');transcript.append(loading);scroll();
    try {
      if (!sessionId) {
        const created=await request('/v1/sessions','POST',{context:{page_path:location.pathname.slice(0,200),page_title:document.title.slice(0,200)}},rid);
        if (v!==generation) return;sessionId=created.session_id;
      }
      const path=`/v1/sessions/${sessionId}/messages`,payload={message:text,request_id:rid};
      const r=config.streaming ? await streamReply(path,payload,stage=>{
        if(v!==generation)return;
        const labels={connected:'已连接，正在处理…',routing:'正在理解您的问题…',retrieving:'正在查询相关资料…',generating:'正在整理答案…',assembling:'正在附加配图与来源…',business:'正在查询业务信息…',clarifying:'正在确认您的问题…'};
        loading.textContent=labels[stage] || '正在为您解答…';
      },delta=>{
        if(v!==generation)return;
        loading.hidden=true;
        if(!live){live=message('assistant','');live.classList.add('streaming');}
        liveText+=delta;live.querySelector('.bubble').textContent=liveText;scroll();
      }) : await request(path,'POST',payload);
      if (v!==generation) return;
      const finished=message('assistant',r.answer,r);if(live){live.remove();live=null;finished.style.animation='none';}retry=null;activity();
    } catch(err) {
      if (v===generation) notice(err.message+'（问题编号：'+rid+'）',()=>send(text,true));
    } finally {
      live?.remove();loading.remove();if(v===generation) {setBusy(false);input.focus();scroll();}
    }
  }
  async function showSource(source) {
    const v=generation;sourcePane.hidden=false;sourcePane.replaceChildren();
    const back=element('button','source-back','← 返回对话');back.onclick=()=>{sourcePane.hidden=true;input.focus();};sourcePane.append(back);back.focus();
    const content=element('div','source-content','正在加载来源…');sourcePane.append(content);
    try {
      const r=await request('/v1/sources/'+encodeURIComponent(source.id));
      if(v!==generation) return;
      content.replaceChildren(element('h3','',sourceLabel(r)),element('div','meta',`${r.source_file} · ${r.version || ''} · 页码 ${(r.pages || []).join(', ') || '不适用'}`),element('p','',String(r.content || '').split('\n').filter(line=>!/^\s*(?:图片\s*URL|原文链接|来源)\s*[:：]/i.test(line)).join('\n').replace(/https?:\/\/raw\.githubusercontent\.com\/[^\s<>]+/gi,'[内部地址已隐藏]')));
    } catch(err) {if(v===generation) content.textContent=err.message;}
  }
  function renderHistory(data, earlier=false) {
    const previous=transcript.querySelector('.older');if(previous)previous.remove();
    const rows=[];
    for(const h of data.items || []) rows.push(message(h.role,h.content,h.response));
    if(earlier) {
      // Move freshly rendered rows to the top without interpreting message content as HTML.
      const first=transcript.firstChild;
      for(const row of rows) transcript.insertBefore(row,first);
    }
    if(data.next_before) {
      const more=element('button','source older','加载更早消息');more.onclick=async()=>{
        const v=generation;more.disabled=true;
        try {
          const older=await request(`/v1/sessions/${sessionId}/messages?before=${encodeURIComponent(data.next_before)}`);
          if(v===generation)renderHistory(older,true);
        } catch(err) {if(v===generation)notice(err.message);more.disabled=false;}
      };transcript.prepend(more);
    }
    if(earlier) transcript.scrollTop=0;
  }
  async function historyPanel() {
    if(busy)return;
    const v=generation;sourcePane.hidden=false;sourcePane.replaceChildren();
    const back=element('button','source-back','← 返回对话');back.onclick=()=>{sourcePane.hidden=true;input.focus();};sourcePane.append(back,element('h3','','历史会话'));back.focus();
    const list=element('div','source-content','正在加载…');sourcePane.append(list);
    try {
      const data=await request('/v1/sessions');if(v!==generation)return;
      list.replaceChildren();if(!data.items?.length)list.textContent='还没有保存的会话。';
      for(const item of data.items || []) {
        const row=element('div','contact');
        row.append(element('div','',new Date(item.updated_at*1000).toLocaleString('zh-CN')),element('div','hint',item.context?.page_title || '客服会话'));
        const load=element('button','source','打开');load.onclick=async()=>{
          if(busy)return;setBusy(true);
          try {
            const history=await request(`/v1/sessions/${item.session_id}/messages`);if(v!==generation)return;
            sessionId=item.session_id;transcript.replaceChildren();renderHistory(history);sourcePane.hidden=true;retry=null;clearStatus();scroll();
          } catch(err){if(v===generation)notice(err.message);}
          finally{if(v===generation)setBusy(false);}
        };
        const remove=element('button','ghost','删除');let armed=false;
        remove.onclick=async()=>{
          if(!armed){armed=true;remove.textContent='确认删除';return;}
          remove.disabled=true;
          try {
            await request(`/v1/sessions/${item.session_id}`,'DELETE');if(v!==generation)return;
            row.remove();if(sessionId===item.session_id){sessionId=null;retry=null;transcript.replaceChildren();message('assistant','会话已删除。您可以开始新对话。');}
          } catch(err){if(v===generation){remove.disabled=false;remove.textContent='删除失败，重试';}}
        };
        row.append(load,remove);list.append(row);
      }
    }catch(err){if(v===generation)list.textContent=err.message;}
  }
  function close(notify=true) {
    if(!panel) return;
    if(notify && config.layout==='iframe' && opened && config.onClose){config.onClose();return;}
    opened=false;panel.hidden=true;launcher.setAttribute('aria-expanded','false');clearTimeout(idleTimer);lastFocus?.focus?.();
  }
  function open() {
    mount();lastFocus=document.activeElement;opened=true;panel.hidden=false;launcher.setAttribute('aria-expanded','true');sourcePane.hidden=true;activity();
    // Re-authenticate and reload on every open; no credentials or transcripts in localStorage.
    initialized=false;sessionId=null;return refresh();
  }
  function reset() {
    generation++;controller?.abort();controller=new AbortController();sessionId=null;initialized=false;retry=null;busy=false;
    if(transcript) transcript.replaceChildren();if(quick) quick.replaceChildren();if(sourcePane) {sourcePane.replaceChildren();sourcePane.hidden=true;}
    if(input) input.value='';if(status) clearStatus();close(false);
  }
  function brandLogo(className) {
    const img=element('img',className);img.src=new URL('/media/smarttitu-logo.png',config.apiBase).href;img.alt='SmartTITU';img.width=150;img.height=40;return img;
  }
  function mount() {
    if(host) return;
    host=document.createElement('div');host.id='smarttitu-assistant-widget';root=host.attachShadow({mode:'open'});
    const css=element('style');css.textContent=style;
    if(config.layout==='iframe')css.textContent+=`
      .launch{display:none!important}.panel{position:fixed;inset:0;width:100%;height:100dvh;min-height:0;border:0;border-radius:0;box-shadow:none}
      @media(max-width:500px){.panel{inset:0;width:100%;height:100dvh;min-height:0;border-radius:0}}
    `;
    css.textContent+=`
      .header-logo{display:block;width:150px;height:40px;object-fit:contain;object-position:left center}.brand-heading .subtitle{margin-top:4px;font-size:10px}
      .launch{width:88px;height:80px;padding:0;border:0;border-radius:20px;background:transparent;box-shadow:none;display:grid;place-items:center}.launch[aria-expanded="true"]{width:56px;height:52px}.launch:hover{background:transparent;transform:none}.launch:focus-visible{outline:3px solid #709cff;outline-offset:5px}.launch-mascot{display:block;width:100%;height:100%;object-fit:contain;filter:drop-shadow(0 6px 5px #2455ad22);animation:mascot-hop 3.6s ease-in-out infinite;transform-origin:50% 100%;pointer-events:none}.launch:hover .launch-mascot,.launch:focus-visible .launch-mascot,.launch[aria-expanded="true"] .launch-mascot{animation:none}
      .contact-row{display:flex;align-items:center;gap:10px;margin-top:8px}.contact-value{flex:1;min-width:0;overflow-wrap:anywhere;user-select:text}.contact-copy{flex-shrink:0;border:1px solid #d5e1f5;border-radius:7px;padding:4px 10px;background:#fff;color:#245ba4;font-size:11px}.contact-copy:hover{background:#e7efff}
      .launch-fallback{width:64px;height:64px;border-radius:22px;background:#155de6;color:#fff;border:0;box-shadow:0 8px 24px #155de633}.launch-fallback svg{width:40px;height:40px}
      @keyframes mascot-hop{0%,100%{transform:translateY(0)}50%{transform:translateY(-6px)}}
      @media(max-width:500px){.header-logo{width:128px;height:34px}.brand-heading .subtitle{font-size:9px}.launch{width:62px;height:56px;padding:0}}
      @media(prefers-reduced-motion:reduce){.launch-mascot{animation:none}}
    `;
    root.append(css);
    launcher=element('button','launch');launcher.type='button';launcher.setAttribute('aria-label','打开智能客服');launcher.setAttribute('aria-expanded','false');launcher.setAttribute('aria-controls','smarttitu-panel');
    const mascot=element('img','launch-mascot');mascot.src=new URL('/media/support-robot-b.png',config.apiBase).href;mascot.alt='';mascot.width=88;mascot.height=80;launcher.title='智能客服';mascot.onerror=()=>{const fallback=roleAvatar('assistant');fallback.classList.add('launch-fallback');launcher.replaceChildren(fallback);};launcher.append(mascot);launcher.onclick=()=>opened?close():open();root.append(launcher);
    panel=element('section','panel');panel.id='smarttitu-panel';panel.hidden=true;panel.setAttribute('role','dialog');panel.setAttribute('aria-label','SmartTITU智能客服');
    const header=element('header');const title=element('div');title.className='brand-heading';title.append(brandLogo('header-logo'),element('div','subtitle','智能客服 · 产品答疑与接入指引'));
    const actions=element('div','head-actions');
    const fresh=element('button','ghost','＋');fresh.title='新建会话';fresh.setAttribute('aria-label','新建会话');fresh.onclick=()=>{
      if(busy) return;sessionId=null;retry=null;transcript.replaceChildren();message('assistant','新对话已开始。请问有什么可以帮您？');input.focus();
    };
    const historyButton=element('button','ghost','≡');historyButton.title='历史会话';historyButton.setAttribute('aria-label','历史会话');historyButton.onclick=historyPanel;
    const minimize=element('button','ghost','—');minimize.title='收起';minimize.setAttribute('aria-label','收起客服');minimize.onclick=()=>close();if(config.layout==='iframe'&&!config.onClose)minimize.hidden=true;const resize=element('button','ghost','⛶');resize.type='button';
    function resizeLabel(){resize.title=expanded?'还原窗口':'放大窗口';resize.setAttribute('aria-label',resize.title);resize.setAttribute('aria-pressed',String(expanded));resize.textContent=expanded?'⤢':'⛶';}
    resizeLabel();resize.onclick=()=>{expanded=!expanded;if(config.layout==='iframe')config.onResize?.(expanded);else panel.classList.toggle('expanded',expanded);resizeLabel();};
    if(config.layout==='iframe'&&!config.onResize)resize.hidden=true;
    actions.append(fresh,historyButton,resize,minimize);
    header.append(title,actions);panel.append(header);
    transcript=element('div','body');transcript.setAttribute('role','log');transcript.setAttribute('aria-live','polite');panel.append(transcript);
    const composer=element('div','composer');quick=element('div','quick');status=element('div','notice');status.setAttribute('role','status');status.hidden=true;
    const entry=element('div','entry');input=element('textarea');input.placeholder='输入您的问题…';input.maxLength=2000;input.setAttribute('aria-label','客服问题');
    input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();send();}});
    sendButton=element('button','send','发送');sendButton.type='button';sendButton.onclick=()=>send();entry.append(input,sendButton);
    const foot=element('div','foot');foot.append(element('span','','AI 回答仅供参考 · Enter 发送'));
    const human=element('button','human','联系人工');human.type='button';human.onclick=()=>send('转人工客服');foot.append(human);
    composer.append(quick,status,entry,foot);panel.append(composer);
    sourcePane=element('div','source-pane');sourcePane.hidden=true;panel.append(sourcePane);root.append(panel);
    panel.addEventListener('pointerdown',activity);panel.addEventListener('keydown',e=>{
      activity();if(e.key==='Escape'){e.preventDefault();if(!sourcePane.hidden)sourcePane.hidden=true;else close();}
    });
    document.body.append(host);
  }
  window.SmartTITUAssistant={
    open,close,reset,
    async ask(text) {await open();await send(text);},
    configure(options) {reset();const changed=options.layout && options.layout!==config.layout;config={...config,...options};if(changed){host?.remove();host=null;root=null;mount();}},
    destroy() {reset();host?.remove();host=null;root=null;}
  };
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
})();
