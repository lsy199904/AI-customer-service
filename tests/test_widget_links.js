'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('app/static/widget.js','utf8');
function element(tag,cls,text='') {
 return {tag,text,children:[],append(child){this.children.push(child);}};
}
const context={URL,element,document:{createTextNode:text=>({tag:'#text',text})}};
vm.runInNewContext(source.slice(source.indexOf('  function appendLinkedText('),source.indexOf('  function safeImage(')),context);
function render(text){const parent=element('div');context.renderText(parent,text);return parent;}
function links(parent){return parent.children.filter(child=>child.tag==='a');}
function text(parent){return parent.children.map(child=>child.text).join('');}
let result=render('产品介绍：https://www.smarttitu.cn，欢迎查看。');
assert.equal(links(result).length,1);assert.equal(links(result)[0].href,'https://www.smarttitu.cn');
assert.equal(text(result),'产品介绍：https://www.smarttitu.cn，欢迎查看。');
assert.equal(links(result)[0].target,'_blank');assert.equal(links(result)[0].rel,'noopener noreferrer');
result=render('请看[产品官网](https://www.smarttitu.cn)和 http://example.com/help?a=1&b=2。');
assert.equal(links(result).length,2);assert.equal(links(result)[0].text,'产品官网');
assert.equal(links(result)[1].href,'http://example.com/help?a=1&b=2');
result=render('(https://example.com/help). https://example.com/a_(b)');
assert.equal(links(result)[0].href,'https://example.com/help');
assert.equal(links(result)[1].href,'https://example.com/a_(b)');
assert.equal(text(result),'(https://example.com/help). https://example.com/a_(b)');
result=render('<img src=x onerror=alert(1)> https://example.com/<script>');
assert.equal(result.children.filter(child=>child.tag!=='#text'&&child.tag!=='a').length,0);
assert(text(result).includes('<img src=x onerror=alert(1)>'));
result=render('[恶意链接](javascript:alert(1)) data:text/html,hello https://user:secret@example.com http://');
assert.equal(links(result).length,0);
result=render('```text\nhttps://example.com/\n```\nhttps://www.smarttitu.cn');
assert.equal(result.children[0].tag,'pre');assert.equal(links(result).length,1);
assert.equal(result.children[0].text,'https://example.com/\n');
assert.equal(text(render('普通文字\n保持换行')),'普通文字\n保持换行');
const customer={};
vm.runInNewContext(source.slice(source.indexOf('  function customerText('),source.indexOf('  function appendLinkedText(')),customer);
let cleaned=customer.customerText('套餐版本说明。\n\n图片展示：\n![套餐订购-套餐版本介绍](https://example.com/plan.png)\n\n更多详情请参考手册：[下载手册](https://example.com/manual.pdf)');
assert(!cleaned.includes('图片展示'));assert(!cleaned.includes('plan.png'));assert(!cleaned.includes('!['));
assert(cleaned.includes('套餐版本说明。'));assert(!cleaned.includes('下载手册'));assert(!cleaned.includes('manual.pdf'));
assert.equal(customer.customerText('前文\n**图片展示：**\n![图](https://example.com/a_(b).png)\n后文'),'前文\n\n后文');
assert(!customer.customerText('前文\n<img src="https://example.com/plan.png">\n图片URL：https://example.com/plan.png\n后文').includes('plan.png'));
assert(customer.customerText('```markdown\n![示例](https://example.com/example.png)\n```').includes('![示例]'));
assert.equal(customer.customerText('图片展示：这里解释展示方式。'),'图片展示：这里解释展示方式。');
cleaned=customer.customerText('1. 企业基础版。\n2. 企业专业版。\n\n更多详情请参考手册：\nhttps://raw.githubusercontent.com/lsy199904/AI-customer-service/main/docs/sources/11.TITU Hub用户操作手册.pdf');
assert.equal(cleaned,'1. 企业基础版。\n2. 企业专业版。');
assert.equal(customer.customerText('官网入口：https://www.smarttitu.cn'),'官网入口：https://www.smarttitu.cn');
assert(customer.customerText('在线文档入口：[在线文档](https://doc.smarttitu.cn)').includes('https://doc.smarttitu.cn'));
console.log('Clickable links: plain and Markdown URLs, punctuation, query strings, safe DOM, protocols and code blocks passed');
