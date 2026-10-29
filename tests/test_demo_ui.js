'use strict';
const assert=require('assert'),fs=require('fs'),{chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 try{
  let enabled=true,tokens=0;const auths=[];
  const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('https://demo.test/**',async route=>{
   const request=route.request(),path=new URL(request.url()).pathname;
   if(path==='/')return route.fulfill({contentType:'text/html',body:'<!doctype html><meta charset="utf-8"><button data-connect>打开客服</button><dialog id="connection-dialog"><form id="connection-form"><button id="connection-close" type="button">关闭</button><textarea id="token"></textarea><button id="connect" type="submit">连接</button><p id="status"></p></form></dialog><script src="/widget.js"></script><script src="/widget/demo.js"></script>'});
   if(['/widget.js','/widget/demo.js'].includes(path))return route.fulfill({contentType:'text/javascript; charset=utf-8',body:fs.readFileSync('app/static/'+(path==='/widget.js'?'widget.js':'demo.js'),'utf8')});
   let data;
   if(path==='/widget/config')data={demo_auto_login:enabled,frame_origins:[]};
   else if(path==='/widget/demo-auth'){tokens++;data={token:'test-automatic-token',expires_in:3600};}
   else{
    auths.push(request.headers().authorization);
    if(path==='/v1/bootstrap')data={welcome:'您好，可以开始测试。',capabilities:{streaming:false},quick_questions:[]};
    else if(path==='/v1/sessions')data=request.method()==='GET'?{items:[]}:{session_id:'test-session'};
    else if(path.endsWith('/messages'))data={answer:'已收到测试问题。',status:'answered'};
    else return route.fulfill({status:404,body:''});
   }
   return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.goto('https://demo.test/');await page.locator('[data-connect]').click();
  await page.getByRole('textbox',{name:'客服问题'}).waitFor();
  assert.equal(await page.locator('#connection-dialog').evaluate(el=>el.open),false);
  await page.getByRole('textbox',{name:'客服问题'}).fill('你好');await page.getByRole('button',{name:'发送',exact:true}).click();
  await page.getByText('已收到测试问题。',{exact:true}).waitFor();
  assert.equal(tokens,1);assert(auths.every(value=>value==='Bearer test-automatic-token'));
  enabled=false;await page.reload();await page.locator('[data-connect]').click();
  await page.waitForFunction(()=>document.getElementById('connection-dialog').open);
  assert.equal(tokens,1);assert.deepEqual(errors,[]);
  console.log('Demo UI: auto token, cached auth, no manual dialog, chat and disabled fallback passed');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
