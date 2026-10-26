'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const code=fs.readFileSync('app/static/widget.js','utf8');
const selected=[],transcript={children:[],append(child){this.children.push(child);}};
function element(tag,cls,text){return {tag,cls,text,children:[],events:{},append(...children){this.children.push(...children);},addEventListener(name,fn){this.events[name]=fn;}};}
const context={element,transcript,renderText:(node,text)=>{node.text=text;},customerText:x=>x,scroll(){},showSource:source=>selected.push(source)};
vm.runInNewContext(code.slice(code.indexOf('  function message('),code.indexOf('  function renderSuggestions(')),context);
const source={id:'question-register',title:'问题4 注册流程',section_title:'业务流程',display_title:'用户手册-业务流程',url:'/v1/sources/question-register'};
const row=context.message('assistant','请按步骤注册。',{citations:[source]});
const button=row.children[1].children[0];assert.equal(button.text,'用户手册-业务流程');assert.equal(button.title,'问题4 注册流程');button.events.click();
assert.equal(selected[0].id,'question-register');assert.equal(selected[0].url,source.url);
const link=context.message('assistant','查看官网。',{citations:[{title:'问题1 产品介绍网页',display_title:'用户手册-常用外部链接'}]});
assert.equal(link.children[1].children[0].text,'用户手册-常用外部链接');
const history=context.message('assistant','历史回答。',{citations:[source]});assert.equal(history.children[1].children[0].text,'用户手册-业务流程');
console.log('Chapter source labels, question tooltips, original source routing and history rendering passed');
