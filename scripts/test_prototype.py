"""Check offline transport with Node.js without browser, network, or filesystem access from JS."""
from pathlib import Path
import json
import subprocess
import shutil
import tempfile
import runpy
ROOT=Path(__file__).resolve().parent.parent
transport=runpy.run_path(str(ROOT/'scripts/build_prototype.py'))['TRANSPORT']
rows=[json.loads(x) for x in (ROOT/'data/knowledge.jsonl').read_text().splitlines()]
source=transport.replace('__KNOWLEDGE__',json.dumps(rows,ensure_ascii=False).replace('<','\\u003c')).replace('\\\\','\\')
checks=r'''
async function check(){
 function assert(test,name){if(!test)throw new Error(name);}
 const boot=await request('/v1/bootstrap');assert(boot.answer_mode==='extractive','offline mode');
 const created=await request('/v1/sessions','POST',{context:{page_title:'原型'}});
 const path='/v1/sessions/'+created.session_id+'/messages';
 const answer=await request(path,'POST',{message:'如何开通账号?',request_id:'test-001'});
 assert(answer.status==='answered'&&answer.citations.length===1,'knowledge answer');
 const source=await request('/v1/sources/'+answer.citations[0].id);assert(source.content&&source.source_file,'citation');
 const followup=await request(path,'POST',{message:'这个怎么操作?',request_id:'test-002'});assert(followup.status==='answered','context followup');
 const handoff=await request(path,'POST',{message:'转人工客服',request_id:'test-003'});assert(handoff.handoff&&handoff.contact.phone,'handoff');
 const unknown=await request(path,'POST',{message:'量子土豆驾驶火星飞船',request_id:'test-004'});assert(unknown.handoff,'unknown');
 const history=await request(path);assert(history.items.length===8,'history');
 await request(path,'POST',{message:'如何开通账号?',request_id:'test-001'});assert((await request(path)).items.length===8,'idempotency');
 assert((await request('/v1/sessions')).items.length===1,'list');
 await request('/v1/sessions/'+created.session_id,'DELETE');assert((await request('/v1/sessions')).items.length===0,'delete');
 console.log('Offline transport: 10 checks passed');
}
check().catch(error=>{console.error(error.message);process.exitCode=1;});
'''
node=shutil.which('node')
if not node:
 candidate=Path('/Users/1272722735qq.com/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')
 if candidate.is_file():node=str(candidate)
if not node:raise SystemExit('该验证脚本需本地Node.js,运行服务和打开原型不需要Node.js。')
with tempfile.TemporaryDirectory() as d:
 p=Path(d)/'transport.js';p.write_text(source+'\n'+checks)
 subprocess.run([node,str(p)],check=True)
