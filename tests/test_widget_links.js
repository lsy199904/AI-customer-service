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
console.log('Clickable links: plain and Markdown URLs, punctuation, query strings, safe DOM, protocols and code blocks passed');
