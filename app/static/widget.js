(() => {
  'use strict';
  if (window.SmartTITUAssistant) return;
  const script = document.currentScript;
  let config = {
    apiBase: script?.dataset.apiBase || new URL(script?.src || location.href).origin,
    tokenEndpoint: script?.dataset.authUrl || '/api/assistant/token',
    layout: 'floating',
    onClose: null,
    getToken: null
  };
  let host, root, panel, launcher, transcript, input, sendButton, quick, status, sourcePane;
  let sessionId = null, initialized = false, busy = false, opened = false;
  let idleTimer, controller, generation = 0, retry = null, lastFocus;
  let idleSeconds = 1800;
  const style = `
    :host{all:initial;font-family:Inter,-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;color:#17283b;font-size:14px;line-height:1.6}
    *{box-sizing:border-box}button,input,textarea{font:inherit}button{cursor:pointer}button:disabled{cursor:wait;opacity:.55}button:focus-visible,a:focus-visible,textarea:focus-visible{outline:3px solid #80bbff;outline-offset:3px}
    [hidden]{display:none!important}.launch{position:fixed;right:26px;bottom:24px;z-index:2147483001;border:0;border-radius:999px;background:#135de4;color:white;padding:15px 22px;box-shadow:0 8px 28px #155ce53b;display:flex;align-items:center;gap:10px;font-weight:600;transition:transform .2s}.launch:hover{transform:translateY(-2px)}
    .icon{width:22px;height:22px;display:inline-grid;place-items:center;font-size:19px}.panel{position:fixed;right:26px;bottom:94px;z-index:2147483002;width:414px;height:min(680px,calc(100dvh - 126px));min-height:300px;background:#fff;border:1px solid #dfe7f0;border-radius:22px;box-shadow:0 18px 80px #203c6530;display:flex;flex-direction:column;overflow:hidden}
    header{padding:19px 20px;display:flex;align-items:center;gap:11px;background:linear-gradient(115deg,#edf5ff,#f9fcff);border-bottom:1px solid #e8eef6}.avatar{height:42px;width:42px;border-radius:14px;background:#155de6;display:grid;place-items:center;color:#fff;font-size:22px}h2{font-size:16px;line-height:1.4;margin:0;font-weight:650}.subtitle{font-size:11px;color:#6b809a}.head-actions{margin-left:auto;display:flex;gap:4px}.ghost{border:0;background:transparent;color:#62778f;border-radius:8px;padding:7px 9px}.ghost:hover{background:#e1edff;color:#135de4}
    .body{flex:1;overflow:auto;padding:20px;background:#f7f9fc;overscroll-behavior:contain}.welcome-label{font-size:11px;letter-spacing:.12em;color:#547491;margin-bottom:10px}.message{margin-bottom:17px;display:flex;flex-direction:column;align-items:flex-start}.message.user{align-items:flex-end}.bubble{white-space:pre-wrap;overflow-wrap:anywhere;max-width:94%;border-radius:3px 15px 15px 15px;padding:12px 14px;background:#fff;box-shadow:0 2px 8px #192c4a05;border:1px solid #e6ecf4;font-size:13px}.bubble pre{white-space:pre;overflow:auto;max-width:100%;background:#f1f5fa;border-radius:7px;padding:10px;font:11px/1.7 monospace}.reply-images{max-width:94%;display:flex;flex-direction:column;gap:8px;margin-top:9px}.image-button{border:1px solid #e0e8f4;border-radius:11px;background:#fff;padding:8px;text-align:left}.image-button img{display:block;max-width:100%;max-height:220px;object-fit:contain;border-radius:7px}.image-caption{color:#6380a0;font-size:11px;padding-top:5px}.preview-image{display:block;max-width:100%;max-height:75vh;object-fit:contain}.user .bubble{background:#155de6;color:#fff;border-color:#155de6;border-radius:15px 3px 15px 15px}.meta{font-size:10px;color:#73879d;margin:5px 3px}.sources{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px;max-width:100%}.source{background:#eff5ff;color:#245ba4;border:1px solid #dae7fb;border-radius:7px;font-size:11px;padding:5px 8px;text-align:left;max-width:100%}
    .quick{display:flex;flex-wrap:wrap;gap:7px;padding-top:2px;margin-bottom:18px}.quick button{border:1px solid #dce6f4;border-radius:999px;background:white;color:#34577f;font-size:12px;padding:7px 10px}.quick button:hover{border-color:#7ba6ef;background:#f0f6ff}.notice{font-size:12px;color:#9a611c;white-space:pre-wrap;margin:12px 0}.composer{padding:12px 16px 10px;border-top:1px solid #e7edf5;background:#fff}.entry{display:flex;gap:8px;align-items:flex-end;border:1px solid #d7e1ed;border-radius:13px;padding:8px}.entry:focus-within{border-color:#6797ee;box-shadow:0 0 0 2px #eaf1ff}textarea{resize:none;border:0;outline:0!important;background:transparent;flex:1;min-width:0;width:auto;height:44px;max-height:100px;font-size:13px;padding:3px 5px;color:#17283b}.send{flex-shrink:0;white-space:nowrap;border:0;border-radius:9px;color:#fff;background:#155de6;padding:9px 12px;font-size:12px}.foot{display:flex;align-items:center;justify-content:space-between;margin-top:7px;font-size:10px;color:#8a99ab}.human{border:0;padding:0;background:transparent;color:#5d789c;font-size:11px}.contact{background:#f1f6ff;border-radius:10px;padding:11px 12px;margin-top:9px;font-size:12px;max-width:100%}.contact a{display:block;color:#235cac}.contact img{display:block;width:128px;height:128px;object-fit:contain;margin-top:9px}.contact .hint{font-size:11px;color:#6b809a}
    .source-pane{position:absolute;inset:0;background:#fff;z-index:2;padding:20px;overflow:auto}.source-pane h3{font-size:15px;margin:10px 0}.source-content{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}.source-back{border:1px solid #dce6f4;background:#f5f8fc;color:#34577f;padding:6px 10px;border-radius:8px}.loading{color:#73879d;font-size:12px;padding:10px 0}.retry{border:1px solid #ddd;background:#fff;color:#9a611c;border-radius:7px;padding:5px 10px}
    @media(max-width:500px){.panel{right:12px;bottom:86px;width:calc(100vw - 24px);height:calc(100dvh - 105px);border-radius:18px}.launch{right:15px;bottom:18px;padding:12px 18px}}
    @media(prefers-reduced-motion:reduce){*{transition:none!important}}
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
  async function request(path, method = 'GET', body) {
    const signal=controller?.signal;
    const auth = await token();
    const response = await fetch(apiURL(path), {
      method, headers:{Authorization:'Bearer ' + auth, ...(body ? {'Content-Type':'application/json'} : {})},
      body:body ? JSON.stringify(body) : undefined, signal, credentials:'omit', cache:'no-store'
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || '连接暂时不可用，请稍后重试');
    return data;
  }
  function scroll() { transcript.scrollTop = transcript.scrollHeight; }
  function activity() {
    clearTimeout(idleTimer);
    if (opened) idleTimer = setTimeout(close, idleSeconds * 1000);
  }
  function message(role, text, response) {
    const row = element('div', 'message ' + role);
    const bubble=element('div','bubble');
    renderText(bubble, role==='assistant' ? customerText(text) : text);
    row.append(bubble);
    if(response?.images?.length)renderImages(row,response.images);
    if (response?.citations?.length) {
      const list = element('div', 'sources');
      response.citations.forEach((source, i) => {
        const b = element('button', 'source', `参考资料 · ${source.title.replace(/^\d+(?:\.\d+)*\s+/, '')}`);
        b.type = 'button'; b.addEventListener('click', () => showSource(source)); list.append(b);
      });
      row.append(list);
    }
    if (response?.handoff && response.contact) renderContact(row, response.contact);
    transcript.append(row); scroll(); return row;
  }
  function customerText(text) {
    // Old saved responses keep their original database payload; hide legacy debug prefixes in customer UI.
    return String(text || '').replace(/^以下为(?:知识库原文摘录|本地知识摘录|知识原文摘录)[（(][^）)]*[）)][：:]?\s*/,'');
  }
  function renderText(parent,text) {
    const parts=String(text || '').split(/```(?:[a-zA-Z0-9_-]+)?\n([\s\S]*?)```/g);
    parts.forEach((part,index)=>{if(part)parent.append(index%2?element('pre','',part):document.createTextNode(part));});
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
    const group=element('div','reply-images');
    images.slice(0,4).forEach(picture=>{
      const url=safeImage(picture.url);if(!url)return;
      const button=element('button','image-button');button.type='button';button.setAttribute('aria-label','查看图片：'+(picture.title || picture.alt || '相关图片'));
      const image=element('img');image.src=url;image.alt=picture.alt || picture.title || '相关图片';image.loading='lazy';image.referrerPolicy='no-referrer';
      image.onerror=()=>{button.replaceChildren(element('span','image-caption','图片暂时无法显示，请稍后重试。'));button.disabled=true;};
      button.append(image,element('div','image-caption',(picture.title || '相关图片')+' · 点击放大'));
      button.onclick=()=>{
        sourcePane.hidden=false;sourcePane.replaceChildren();
        const back=element('button','source-back','← 返回对话');back.onclick=()=>{sourcePane.hidden=true;input.focus();};
        const large=element('img','preview-image');large.src=url;large.alt=image.alt;large.referrerPolicy='no-referrer';
        sourcePane.append(back,element('h3','',picture.title || '图片详情'),large);back.focus();
      };group.append(button);
      if(!url.startsWith('data:')) {
        const original=element('a','source','查看原图 ↗');original.href=url;original.target='_blank';original.rel='noopener noreferrer';
        group.append(original);
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
    if (/^[+\d -]{3,30}$/.test(contact.phone || '')) {
      const a = element('a', '', '电话：' + contact.phone); a.href='tel:'+contact.phone.replace(/[^+\d]/g,'');box.append(a);
    }
    if (/^[a-zA-Z0-9_.+%-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/.test(contact.email || '')) {
      const a = element('a', '', contact.email); a.href='mailto:'+contact.email;box.append(a);
    }
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
      if (version !== generation) return;
      idleSeconds=boot.idle_timeout_seconds || 1800;
      // Restore only the most recent session belonging to the authenticated user, as verified by the backend.
      const sessions=await request('/v1/sessions');
      if (version !== generation) return;
      sessionId=sessions.items?.[0]?.session_id || null;
      let history={items:[]};
      if (sessionId) history=await request(`/v1/sessions/${sessionId}/messages`);
      if (version !== generation) return;
      transcript.replaceChildren();
      transcript.append(element('div','welcome-label','SMARTTITU · 企业智能服务'));
      message('assistant',boot.welcome);
      renderHistory(history);
      (boot.quick_questions || []).forEach(q => {
        const b=element('button','',q);b.type='button';b.onclick=()=>send(q);quick.append(b);
      });
      initialized=true;activity();
    } catch (err) {
      if (version !== generation) return;
      transcript.replaceChildren();notice(err.message,()=>refresh());
    } finally { if(version === generation) { setBusy(false);input.focus(); } }
  }
  async function refresh() {
    controller?.abort();controller=new AbortController();const v=++generation;
    await initialize(v);
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
    const loading=element('div','loading','正在为您解答…');transcript.append(loading);scroll();
    try {
      if (!sessionId) {
        const created=await request('/v1/sessions','POST',{context:{page_path:location.pathname.slice(0,200),page_title:document.title.slice(0,200)}});
        if (v!==generation) return;sessionId=created.session_id;
      }
      const r=await request(`/v1/sessions/${sessionId}/messages`,'POST',{message:text,request_id:rid});
      if (v!==generation) return;
      message('assistant',r.answer,r);retry=null;activity();
    } catch(err) {
      if (v===generation) notice(err.message,()=>send(text,true));
    } finally {
      loading.remove();if(v===generation) {setBusy(false);input.focus();scroll();}
    }
  }
  async function downloadDocument(path,filename) {
    if(!/^\/v1\/documents\/DOC-[a-f0-9]+\/revisions\/[a-f0-9]{64}\/download$/.test(path))throw new Error('文档链接无效');
    const auth=await token();
    const response=await fetch(apiURL(path),{headers:{Authorization:'Bearer '+auth},cache:'no-store',credentials:'omit'});
    if(!response.ok)throw new Error('文档暂时无法下载');
    const blob=await response.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=url;a.download=filename || 'knowledge.docx';a.style.display='none';document.body.append(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),60000);
  }
  async function showSource(source) {
    const v=generation;sourcePane.hidden=false;sourcePane.replaceChildren();
    const back=element('button','source-back','← 返回对话');back.onclick=()=>{sourcePane.hidden=true;input.focus();};sourcePane.append(back);back.focus();
    const content=element('div','source-content','正在加载来源…');sourcePane.append(content);
    try {
      const r=await request('/v1/sources/'+encodeURIComponent(source.id));
      if(v!==generation) return;
      content.replaceChildren(element('h3','',r.title),element('div','meta',`${r.source_file} · ${r.version || ''} · 页码 ${(r.pages || []).join(', ') || '不适用'}`),element('p','',r.content));
      if(r.source_locator)content.append(element('div','meta',r.source_locator));
      if(r.source_references?.length)content.append(element('p','meta',r.source_references.join('\n')));
      if(r.download_url){const b=element('button','source-back','下载这份知识文档');b.onclick=async()=>{try{await downloadDocument(r.download_url,r.source_file);}catch(err){b.textContent=err.message;}};content.append(b);}
      const url=safeHTTPS(r.document_url);
      if(url) {const a=element('a','','查看原文档 ↗');a.href=url;a.target='_blank';a.rel='noopener noreferrer';content.append(a);}
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
  function mount() {
    if(host) return;
    host=document.createElement('div');host.id='smarttitu-assistant-widget';root=host.attachShadow({mode:'open'});
    const css=element('style');css.textContent=style;
    if(config.layout==='iframe')css.textContent+=`
      .launch{display:none!important}.panel{position:fixed;inset:0;width:100%;height:100dvh;min-height:0;border:0;border-radius:0;box-shadow:none}
      @media(max-width:500px){.panel{inset:0;width:100%;height:100dvh;min-height:0;border-radius:0}}
    `;
    root.append(css);
    launcher=element('button','launch');launcher.type='button';launcher.setAttribute('aria-label','打开智能客服');launcher.setAttribute('aria-expanded','false');launcher.setAttribute('aria-controls','smarttitu-panel');
    launcher.append(element('span','icon','✦'),element('span','','智能客服'));launcher.onclick=()=>opened?close():open();root.append(launcher);
    panel=element('section','panel');panel.id='smarttitu-panel';panel.hidden=true;panel.setAttribute('role','dialog');panel.setAttribute('aria-label','SmartTITU智能客服');
    const header=element('header');const title=element('div');title.append(element('h2','','SmartTITU 智能客服'),element('div','subtitle','产品答疑 · 接入指引 · 故障排查'));
    const actions=element('div','head-actions');
    const fresh=element('button','ghost','＋');fresh.title='新建会话';fresh.setAttribute('aria-label','新建会话');fresh.onclick=()=>{
      if(busy) return;sessionId=null;retry=null;transcript.replaceChildren();message('assistant','新对话已开始。请问有什么可以帮您？');input.focus();
    };
    const historyButton=element('button','ghost','≡');historyButton.title='历史会话';historyButton.setAttribute('aria-label','历史会话');historyButton.onclick=historyPanel;
    const minimize=element('button','ghost','—');minimize.title='收起';minimize.setAttribute('aria-label','收起客服');minimize.onclick=()=>close();if(config.layout==='iframe'&&!config.onClose)minimize.hidden=true;actions.append(fresh,historyButton,minimize);
    header.append(element('div','avatar','✦'),title,actions);panel.append(header);
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
