"""Run on the Linux model host. Read existing Docker metadata, update local .env.
Never prints or commits API keys; does not move/restart existing model services.
"""
from pathlib import Path
import json
import os
import re
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parent.parent

def inspect(name):
    return json.loads(subprocess.check_output(['docker','inspect',name]))[0]

def main():
    env=ROOT/'.env'
    if not env.is_file():raise SystemExit('先执行python3 manage.py init')
    info=inspect('qwen3-reranker-4b');c=info['Config'];args=(c.get('Entrypoint') or [])+(c.get('Cmd') or [])
    key=None
    for i,arg in enumerate(args):
        if arg=='--api-key' and i+1<len(args):key=args[i+1];break
        if arg.startswith('--api-key='):key=arg.split('=',1)[1];break
    if not key:
        key=next((item.split('=',1)[1] for item in c.get('Env') or [] if item.startswith('VLLM_API_KEY=')),None)
    if not key:raise SystemExit('未发现重排密钥,请联系服务管理员;没有修改.env')
    networks=info['NetworkSettings']['Networks'];network=networks.get('model-serving_model-net') or next(iter(networks.values()),{})
    ip=network.get('IPAddress')
    if not ip:raise SystemExit('未找到重排容器IP,请配置实际地址;没有修改.env')
    update={'RETRIEVAL_BACKEND':'semantic','EMBEDDING_PROVIDER':'ollama','EMBEDDING_URL':'http://127.0.0.1:11434/api/embed','EMBEDDING_MODEL':'bge-m3:latest','EMBEDDING_REVISION':'v1','RERANK_ENABLED':'true','RERANK_URL':'http://'+ip+':8001/v1/rerank','RERANK_MODEL':'Qwen3-Reranker-4B','RERANK_API_KEY':key}
    lines=env.read_text().splitlines();old_origins=''
    for line in lines:
        if line.startswith('MODEL_HTTP_ORIGINS='):old_origins=line.split('=',1)[1].strip().strip('"\'')
    origins=[v for v in old_origins.split(',') if v]+['http://127.0.0.1:11434','http://'+ip+':8001']
    update['MODEL_HTTP_ORIGINS']=','.join(dict.fromkeys(origins))
    result=[];written=set()
    for line in lines:
        name=line.split('=',1)[0] if '=' in line and not line.lstrip().startswith('#') else ''
        if name in update:
            if name not in written:result.append(name+'='+json.dumps(update[name],ensure_ascii=False));written.add(name)
        else:result.append(line)
    for name,value in update.items():
        if name not in written:result.append(name+'='+json.dumps(value,ensure_ascii=False))
    fd,tmp=tempfile.mkstemp(prefix='.env.update-',dir=ROOT)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w') as f:f.write('\n'.join(result)+'\n')
        os.replace(tmp,env)
    finally:
        if Path(tmp).exists():Path(tmp).unlink()
    print('已配置Embedding和Reranker,密钥仅写入本机.env,没有打印。')
    print('保留现有聊天模型和AUTH_SECRET;请确认ANSWER_MODE=llm,再执行check和ingest。')
if __name__=='__main__':main()
