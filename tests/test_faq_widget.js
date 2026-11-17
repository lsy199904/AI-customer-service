'use strict';
const fs=require('fs'),assert=require('assert');
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 try{
  const page=await browser.newPage({viewport:{width:1100,height:900}}),calls=[],errors=[];
  const items=JSON.parse(fs.readFileSync('data/faq.json','utf8')).items;
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('https://widget.test/**',async route=>{
   const req=route.request(),url=new URL(req.url()),path=url.pathname.replace(/^\/smart-bot(?=\/)/,'');
   if(path==='/')return route.fulfill({contentType:'text/html',body:'<!doctype html><html lang="zh"><head><meta charset="utf-8"></head><body><script src="/widget.js"></script></body></html>'});
   if(path==='/widget.js')return route.fulfill({contentType:'application/javascript',body:fs.readFileSync('app/static/widget.js','utf8')});
   if(path.startsWith('/media/')){
    const local='app/static'+path;
    return route.fulfill(fs.existsSync(local)?{contentType:'image/png',body:fs.readFileSync(local)}:{status:404,body:''});
   }
   let data;
   if(path==='/v1/bootstrap')data={welcome:'您好，我是SmartTITU智能客服。',faq:{total:24,items:items.slice(0,6)},quick_questions:['注册流程','企业认证流程','服务订购流程','客户充值流程','账单支付流程','在线开票流程'],capabilities:{streaming:false}};
   else if(path==='/v1/faq')data={total:24,items:items.slice(6,12)};
   else if(path==='/v1/sessions')data=req.method()==='GET'?{items:[]}:{session_id:'faq-preview'};
   else if(path.endsWith('/faq')){
    calls.push({path,body:req.postDataJSON()});const row=items.find(i=>i.id===req.postDataJSON().faq_id);
    data={answer:row.answer,status:'answered',answer_mode:'fixed',reason:'standard_faq',faq_id:row.id,images:[]};
   }else if(path.endsWith('/messages')){calls.push({path,body:req.postDataJSON()});data={answer:'原有RAG问答路径',status:'answered',images:[]};}
   else return route.fulfill({status:404,body:''});
   return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.goto('https://widget.test/');
  await page.evaluate(async()=>{window.SmartTITUAssistant.configure({getToken:async()=> 'preview-token'});await window.SmartTITUAssistant.open();});
  assert.equal(await page.locator('.faq-question').count(),6);
  assert.equal(await page.locator('.composer .quick button').count(),6);
  assert.equal(await page.locator('.composer .faq-panel').count(),1);
  assert.equal(await page.locator('details.faq-panel').count(),0);
  const placement=await page.locator('.faq-panel').evaluate(el=>({faq:el.getBoundingClientRect().top,transcript:el.closest('#smarttitu-panel').querySelector('[role=log]').getBoundingClientRect().bottom}));
  assert(placement.faq>=placement.transcript-1,'FAQ must be below conversation');
  const old=await page.locator('.faq-question').allTextContents();
  await page.getByRole('button',{name:'换一批',exact:true}).click();
  await page.getByRole('button',{name:'忘记密码怎么办？',exact:true}).waitFor();
  assert((await page.locator('.faq-question').allTextContents()).every(q=>!old.includes(q)));
  await page.locator('.faq-question').first().click();
  await page.locator('.faq-answer-tag').waitFor();
  assert.equal(calls.length,1);assert(calls[0].path.endsWith('/faq'));assert.equal(calls[0].body.faq_id,'faq-07');
  assert(!('answer' in calls[0].body)&&!('message' in calls[0].body));
  await page.waitForTimeout(350);
  if(process.env.UI_SCREENSHOT){
   await page.locator('#smarttitu-panel').screenshot({path:process.env.UI_SCREENSHOT});
   await page.locator('.faq-panel').screenshot({path:process.env.UI_SCREENSHOT.replace(/\.png$/,'-faq-only.png')});
  }
  await page.locator('textarea').fill(items[6].question);await page.getByRole('button',{name:'发送',exact:true}).click();
  await page.getByText('原有RAG问答路径',{exact:true}).waitFor();
  assert(calls[1].path.endsWith('/messages'));
  assert.equal(calls[1].body.message,items[6].question);
  assert(!('faq_id' in calls[1].body));
  assert.equal(errors.length,0,errors.join('\n'));
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.locator('.faq-list').evaluate(el=>getComputedStyle(el).gridTemplateColumns.split(' ').length),2);
  await page.waitForTimeout(350);
  if(process.env.UI_SCREENSHOT)await page.locator('#smarttitu-panel').screenshot({path:process.env.UI_SCREENSHOT.replace(/\.png$/,'-mobile.png')});
  console.log('FAQ UI passed: bottom six-question bubbles, swap, direct ID endpoint, typed RAG unchanged, mobile layout.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
