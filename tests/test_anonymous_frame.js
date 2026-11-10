'use strict';
const vm=require('vm'),fs=require('fs'),assert=require('assert');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
async function setup({enabled=true,parent='https://portal.example',blocked=false}={}){
 let calls=[],messages=[],configured,opened=0,listener,clock=1000;
 const winParent={postMessage:(...x)=>messages.push(x)};
 const window={parent:winParent,addEventListener:(_,fn)=>listener=fn,
   SmartTITUAssistant:{configure:c=>configured=c,open:()=>opened++,reset:()=>{}}};
 const status={},panel={};
 const context={window,document:{getElementById:id=>id==='connection'?panel:status},URL,URLSearchParams,
   location:{origin:'https://assistant.example',search:parent?'?parent_origin='+encodeURIComponent(parent):''},
   Date:{now:()=>clock},AbortSignal:{timeout:()=>({})},
   fetch:async(url,options)=>{calls.push([url,options]);
     if(url==='/smart-bot/widget/config')return {ok:true,json:async()=>({anonymous_widget_enabled:enabled,frame_origins:['https://portal.example']})};
     assert.equal(url,'/smart-bot/widget/anonymous-auth');assert.equal(options.method,'POST');assert.equal(options.body,'{}');
     assert.equal(options.headers['Content-Type'],'application/json');
     return {ok:!blocked,json:async()=>blocked?{error:{message:'blocked'}}:{token:'signed-token',expires_in:3600}};
   }};
 vm.runInNewContext(fs.readFileSync('app/static/anonymous-frame.js','utf8'),context);
 await flush();await flush();
 return {calls,messages,configured,status,opened,expire:()=>clock+=3600*1000,listener};
}
(async()=>{
 const x=await setup();assert.equal(x.opened,1);assert(x.configured);
 assert(!x.messages.some(([m])=>m.type==='smarttitu:token-request'));
 assert.equal(await x.configured.getToken(),'signed-token');assert.equal(x.calls.length,2);
 x.expire();await Promise.all([x.configured.getToken(),x.configured.getToken()]);
 assert.equal(x.calls.length,3);assert.equal(x.calls[2][1].headers.Authorization,'Bearer signed-token');
 const plain=await setup({parent:null});assert.equal(plain.opened,1);assert.equal(plain.messages.length,0);
 const disabled=await setup({enabled:false});assert.equal(disabled.opened,0);assert.equal(disabled.calls.length,1);
 const evil=await setup({parent:'https://evil.example'});assert.equal(evil.opened,0);assert.equal(evil.calls.length,1);
 const fail=await setup({blocked:true});assert.equal(fail.opened,0);assert.equal(fail.status.textContent,'blocked');
 // The optional launcher only opens/closes an anonymous frame: it never fetches a parent token.
 let listener;const elements=[];const window={addEventListener:(_,f)=>listener=f,removeEventListener(){}};
 vm.runInNewContext(fs.readFileSync('app/static/iframe-anonymous.js','utf8'),{
   window,URL,location:{origin:'https://portal.example'},
   document:{currentScript:{src:'https://assistant.example/iframe-anonymous.js'},readyState:'complete',
      createElement:tag=>{const e={tag,style:{},setAttribute(k,v){this[k]=v;},focus(){},remove(){this.removed=true;},append(){},replaceChildren(){},attachShadow(){return {append(){}};},contentWindow:{postMessage(){}}};elements.push(e);return e;},body:{append(){}}}});
 const frame=elements.find(e=>e.tag==='iframe'),button=elements.find(e=>e.tag==='button'),mascot=elements.find(e=>e.tag==='img');
 assert(frame.src.includes('/smart-bot/chatbot/anonymous?parent_origin='));
 assert.equal(mascot.src,'https://assistant.example/smart-bot/media/support-robot-b.png');
 assert.equal(mascot.width,88);assert.equal(mascot.height,80);
 window.SmartTITUAnonymousEmbed.open();assert.equal(frame.hidden,false);assert.equal(button['aria-expanded'],'true');
 window.SmartTITUAnonymousEmbed.close();assert.equal(frame.hidden,true);assert.equal(button['aria-expanded'],'false');
 assert(window.SmartTITUAnonymousEmbed);assert.equal(typeof listener,'function');
 console.log('Anonymous frame: plain iframe, trusted optional bridge, own credentials, renewal dedup and failure isolation passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
