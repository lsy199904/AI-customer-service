'use strict';
// Optional browser check: NODE_PATH=<directory containing playwright> node tests/test_widget_ui.js
const assert=require('assert'),fs=require('fs');
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 try {
  const page=await browser.newPage({viewport:{width:1100,height:900}}),requests=[],errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('https://widget.test/**',async route=>{
   const req=route.request(),path=new URL(req.url()).pathname;
   if(path==='/')return route.fulfill({contentType:'text/html',body:'<!doctype html><html lang="zh"><head><meta charset="utf-8"></head><body style="background:#eef3fb"><script src="/widget.js"></script></body></html>'});
   if(path==='/widget.js')return route.fulfill({contentType:'text/javascript',body:fs.readFileSync('app/static/widget.js','utf8')});
   let data;
   if(path==='/v1/bootstrap')data={welcome:'您好，我是 SmartTITU 智能客服。',quick_questions:['操作审计','账单支付流程'],capabilities:{streaming:false}};
   else if(path==='/v1/sessions'&&req.method()==='GET')data={items:[]};
   else if(path==='/v1/sessions')data={session_id:'preview-session'};
   else if(path.endsWith('/messages')){
    const body=req.postDataJSON();requests.push({headers:req.headers(),body});
    data={answer:'您可以在操作审计页面查看平台操作记录。\n详情：https://www.smarttitu.cn',status:'answered',request_id:body.request_id,
      citations:[{id:'KB-test','title':'问题44 操作审计'}]};
    if(body.message==='测试失败')data={answer:'暂时无法完成回答，请稍后重试。',status:'suggestions',request_id:body.request_id,suggestions:['操作审计']};
   }else if(path==='/v1/sources/KB-test')data={id:'KB-test',title:'问题44 操作审计',content:'审计说明',source_file:'用户手册.docx'};
   else return route.fulfill({status:404,body:''});
   return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.goto('https://widget.test/');
  await page.evaluate(async()=>{window.SmartTITUAssistant.configure({getToken:async()=> 'preview-only'});await window.SmartTITUAssistant.ask('操作审计');});
  assert.equal(await page.locator('.message.user .message-avatar svg').count(),1);
  assert.equal(await page.locator('.message.user .message-role').innerText(),'您');
  assert.equal(await page.locator('.message.assistant .message-avatar svg').count(),2);
  assert.equal(await page.getByRole('button',{name:'用户手册：操作审计',exact:true}).count(),1);
  assert.equal(await page.locator('.bubble a').getAttribute('target'),'_blank');
  assert.equal(requests[0].headers['x-request-id'],requests[0].body.request_id);
  assert(requests[0].headers['x-widget-id'].startsWith('window-'));
  if(process.env.UI_SCREENSHOT)await page.locator('#smarttitu-panel').screenshot({path:process.env.UI_SCREENSHOT});
  await page.getByRole('button',{name:'用户手册：操作审计',exact:true}).click();
  assert.equal(await page.locator('.source-content h3').innerText(),'用户手册：操作审计');
  await page.getByRole('button',{name:'← 返回对话'}).click();
  await page.evaluate(()=>window.SmartTITUAssistant.ask('测试失败'));
  await page.getByText('反馈问题',{exact:true}).click();
  assert.equal(await page.getByRole('button',{name:'复制问题编号',exact:true}).count(),1);
  assert((await page.locator('details').innerText()).includes(requests[1].body.request_id));
  await page.setViewportSize({width:375,height:812});
  assert(await page.locator('#smarttitu-panel').evaluate(el=>el.getBoundingClientRect().width<=window.innerWidth));
  assert.deepEqual(errors,[]);
  console.log('Browser checks passed: message avatars and roles, manual labels, clickable URLs, correlation headers, feedback IDs and mobile width');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
