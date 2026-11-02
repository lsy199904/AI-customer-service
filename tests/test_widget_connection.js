'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('app/static/widget.js','utf8');
const code=source.slice(source.indexOf('  async function request('),source.indexOf('  function scroll()'));
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const customer={};vm.runInNewContext(source.slice(source.indexOf('  function customerText('),source.indexOf('  function renderText(')),customer);
assert(!customer.customerText('统一接入（KB-0f567c3f2b830588627d13d2）。').includes('KB-'));
function setup(override={}){
 const timers=new Map();let number=0;
 const context={windowId:'window-test-123',AbortController,TextDecoder,controller:new AbortController(),token:async()=>'test-only-token',apiURL:path=>'https://assistant.example'+path,
 fetch:async()=>({ok:true,json:async()=>({welcome:'hello'})}),
 setTimeout:(callback,delay)=>{timers.set(++number,{callback,delay});return number;},clearTimeout:id=>timers.delete(id),...override};
 vm.runInNewContext(code,context);return {context,timers,expire(){assert.equal(timers.size,1);[...timers.values()][0].callback();}};
}
(async()=>{
 let s=setup();assert.equal((await s.context.request('/v1/bootstrap')).welcome,'hello');assert.equal(s.timers.size,0);
 for(const override of [
  {token:()=>new Promise(()=>{})},
  {fetch:()=>new Promise(()=>{})},
  {fetch:async()=>({ok:true,json:()=>new Promise(()=>{})})}
 ]){
  s=setup(override);const p=s.context.request('/v1/bootstrap');const rejected=assert.rejects(p,/连接超时/);await flush();
  assert.equal([...s.timers.values()][0].delay,15000);s.expire();await rejected;assert.equal(s.timers.size,0);
 }
 s=setup({fetch:()=>new Promise(()=>{})});let p=s.context.request('/v1/sessions/test/messages','POST',{message:'hello'});
 let rejected=assert.rejects(p,/连接超时/);await flush();assert.equal([...s.timers.values()][0].delay,180000);s.expire();await rejected;
 s=setup({fetch:()=>new Promise(()=>{})});p=s.context.request('/v1/bootstrap');rejected=assert.rejects(p,/请求已取消/);s.context.controller.abort();await rejected;assert.equal(s.timers.size,0);
 s=setup({fetch:async()=>{throw new TypeError('Failed to fetch');}});await assert.rejects(s.context.request('/v1/bootstrap'),/无法连接客服/);assert.equal(s.timers.size,0);
 s=setup({fetch:async()=>({ok:false,json:async()=>({error:{message:'登录凭证已过期'}})})});await assert.rejects(s.context.request('/v1/bootstrap'),/登录凭证已过期/);
 const bytes=new TextEncoder().encode('event: status\ndata: {"stage":"retrieving"}\n\nevent: complete\ndata: {"answer":"你好"}\n\n');
 let offset=0;const stages=[];
 s=setup({fetch:async()=>({ok:true,body:{getReader:()=>({read:async()=>offset<bytes.length?{value:bytes.slice(offset,offset+=7),done:false}:{done:true}})}})});
 assert.equal((await s.context.streamReply('/v1/sessions/test/messages',{},stage=>stages.push(stage))).answer,'你好');assert.equal(stages.join(','),'retrieving');assert.equal(s.timers.size,0);
 s=setup({token:()=>new Promise(()=>{})});p=s.context.streamReply('/v1/sessions/test/messages',{},()=>{});rejected=assert.rejects(p,/取消或超时/);await flush();s.expire();await rejected;
 s=setup({token:()=>new Promise(()=>{})});s.context.controller.abort();await assert.rejects(s.context.streamReply('/v1/sessions/test/messages',{},()=>{}),/取消或超时/);assert.equal(s.timers.size,0);
 const sent=[],parent={children:[],append(child){this.children.push(child);}},buttonElement=(tag,cls,text)=>({tag,cls,text,children:[],append(child){this.children.push(child);},setAttribute(){}});
 const suggestionsContext={element:buttonElement,send:text=>sent.push(text)};
 vm.runInNewContext(source.slice(source.indexOf('  function renderSuggestions('),source.indexOf('  function customerText(')),suggestionsContext);
 suggestionsContext.renderSuggestions(parent,{suggestions:['如何开发票'],actions:[{type:'handoff',message:'ignored-untrusted-value'}]});
 assert.equal(parent.children[0].children.length,2);parent.children[0].children[0].onclick();parent.children[0].children[1].onclick();
 assert.equal(sent.join('|'),'如何开发票|转人工客服');
 let configured=null,opens=0,asked='';const demo={location:{origin:'https://assistant.example'},localStorage:{removeItem(){}},
 AbortSignal,Date,fetch:async()=>({ok:true,json:async()=>({token:'visitor-token',expires_in:3600})}),
 document:{querySelectorAll:()=>[]},window:{SmartTITUAssistant:{configure(options){configured=options;},open:async()=>{opens++;},ask:async q=>{asked=q;}}}};
 vm.runInNewContext(fs.readFileSync('app/static/demo.js','utf8'),demo);
 await flush();assert.equal(await configured.getToken(),'visitor-token');
 await demo.openSupport();await demo.openSupport('注册流程');assert.equal(opens,1);assert.equal(asked,'注册流程');
 console.log('Connection regression checks passed: token/fetch/body deadlines, cancel, network/auth errors, anonymous demo access');
})().catch(error=>{console.error(error);process.exitCode=1;});
