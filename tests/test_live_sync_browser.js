'use strict';
const assert=require('assert'),fs=require('fs'),http=require('http');
const {chromium}=require('playwright');
(async()=>{
 const clients=new Set(),history=[],faq=JSON.parse(fs.readFileSync('data/faq.json','utf8')).items;
 let release,question,requestId,port,faqFailures=0;const faqAttempts=[];
 const publish=item=>{for(const res of clients)res.write('event: sync\ndata: '+JSON.stringify(item)+'\n\n');};
 const result=(q,rid,answer)=>({session_id:'sync-session',request_id:rid,answer,status:'answered',images:[],citations:[],suggestions:[]});
 const append=(q,r)=>history.push({role:'user',content:q},{role:'assistant',content:r.answer,response:r});
 const server=http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://localhost');const path=url.pathname.replace(/^\/smart-bot/,'');
  const json=data=>{res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(data));};
  if(path==='/'){res.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});return res.end('<!doctype html><html><head><meta charset="utf-8"></head><body><script src="/widget.js"></script><script>SmartTITUAssistant.configure({layout:"iframe",getToken:async()=>"test"});SmartTITUAssistant.open();</script></body></html>');}
  if(path==='/widget.js'){res.writeHead(200,{'Content-Type':'application/javascript; charset=utf-8'});return res.end(fs.readFileSync('app/static/widget.js'));}
  if(path==='/v1/bootstrap')return json({welcome:'欢迎',capabilities:{streaming:true,live_sync:true},faq:{items:faq.slice(0,6)},link_policy:{hosts:[]}});
  if(path==='/v1/events'){
   res.writeHead(200,{'Content-Type':'text/event-stream','Cache-Control':'no-store'});res.write('event: ready\ndata: {}\n\n');clients.add(res);req.on('close',()=>clients.delete(res));return;
  }
  if(path==='/v1/sessions')return json({items:[{session_id:'sync-session'}]});
  if(path.endsWith('/messages')&&req.method==='GET')return json({items:history});
  if(path==='/v1/faq')return json({items:faq.slice(6,12)});
  if(req.method==='POST'){
   let raw='';for await(const chunk of req)raw+=chunk;const body=JSON.parse(raw);
   if(path.endsWith('/messages/stream')){
    question=body.message;requestId=body.request_id;
    res.writeHead(200,{'Content-Type':'text/event-stream'});
    publish({type:'start',session_id:'sync-session',request_id:requestId,question});
    res.write('event: delta\ndata: '+JSON.stringify({text:'第一段正在同步'})+'\n\n');
    publish({type:'delta',session_id:'sync-session',request_id:requestId,text:'第一段正在同步'});
    release=()=>{const r=result(question,requestId,'第一段正在同步，回答完成。');append(question,r);publish({type:'finish',session_id:'sync-session',request_id:requestId});res.end('event: complete\ndata: '+JSON.stringify(r)+'\n\n');};return;
   }
   if(path.endsWith('/faq')){
    faqAttempts.push(body.request_id);
    if(faqFailures>0){faqFailures--;res.writeHead(502,{'Content-Type':'text/html'});return res.end('<html>upstream restarting</html>');}
    const row=faq.find(row=>row.id===body.faq_id);const r={...result(row.question,body.request_id,row.answer),answer_mode:'fixed'};append(row.question,r);
    publish({type:'start',session_id:'sync-session',request_id:body.request_id,question:row.question});publish({type:'finish',session_id:'sync-session',request_id:body.request_id});return json(r);
   }
  }
  res.writeHead(404);res.end();
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));port=server.address().port;
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 try{
  const ca=await browser.newContext(),cb=await browser.newContext(),a=await ca.newPage(),b=await cb.newPage();
  const errors=[];for(const page of [a,b])page.on('pageerror',e=>{errors.push(e.message);console.error('pageerror',e.message);});
  await Promise.all([a.goto(`http://127.0.0.1:${port}`),b.goto(`http://127.0.0.1:${port}`)]);
  await a.getByPlaceholder('输入您的问题…').waitFor();await b.getByPlaceholder('输入您的问题…').waitFor();
  await a.waitForFunction(()=>!document.querySelector('#smarttitu-assistant-widget').shadowRoot.querySelector('textarea').disabled).catch(()=>{});
  await new Promise(resolve=>setTimeout(resolve,500));assert.equal(clients.size,2);
  await a.getByPlaceholder('输入您的问题…').fill('测试同步');await a.getByRole('button',{name:'发送',exact:true}).click();
  await b.getByText('第一段正在同步',{exact:true}).waitFor();assert.equal(history.length,0,'remote delta must arrive before persistence');
  release();await b.getByText('第一段正在同步，回答完成。',{exact:true}).waitFor();
  assert.equal(await b.locator('.message.user').count(),1);assert.equal(await a.locator('.message.user').count(),1);
  faqFailures=2;
  await a.getByRole('button',{name:'如何创建和管理API Key？',exact:true}).click();
  await a.getByText('连接暂时中断，正在重新连接…',{exact:true}).waitFor();
  await b.getByText(/再次获取完整API Key/).waitFor();
  assert.equal(faqAttempts.length,3);assert.equal(new Set(faqAttempts).size,1);
  assert.equal(await a.getByText(/客服服务返回异常/).count(),0);
  assert.equal(await a.locator('.faq-question').count(),6);assert.equal(await a.getByText('24个问题').count(),0);
  await a.getByRole('button',{name:'换一批',exact:true}).click();assert.equal(await a.locator('.faq-question').count(),6);
  for(const res of [...clients])res.end();
  await a.getByRole('button',{name:faq[6].question,exact:true}).click();
  await b.getByText(faq[6].answer,{exact:true}).waitFor();
  await b.getByRole('button',{name:'新建会话',exact:true}).click();
  publish({type:'start',session_id:'sync-session',request_id:'other-conversation-test',question:'不应串到新会话'});
  await new Promise(resolve=>setTimeout(resolve,200));assert.equal(await b.getByText('不应串到新会话',{exact:true}).count(),0);
  assert.deepEqual(errors,[]);
  console.log('Two isolated browsers: incremental streaming before commit, final reconciliation, no duplicates, FAQ direct answer and batch switch passed');
 }finally{for(const res of clients)res.end();await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exit(1);});
