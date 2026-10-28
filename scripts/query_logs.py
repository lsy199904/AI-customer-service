"""Read local logs; --report summarizes one request and optional content snapshots."""
import argparse
import json
from pathlib import Path
import re

_LABELS = {
    'assistance_planned':'对话协助路径','clarification_requested':'澄清问题','guidance_step_selected':'陪办步骤','guidance_closed':'陪办结束','guidance_source_unavailable':'陪办知识不可用',
    'chat_started':'收到问题', 'chat_cache_hit':'复用已保存回答',
    'question_classified':'问题分类', 'retrieval_model_started':'开始检索模型调用',
    'retrieval_model_completed':'检索模型完成', 'retrieval_model_failed':'检索模型失败',
    'retrieval_completed':'知识检索完成', 'retrieval_failed':'知识检索失败',
    'model_request_started':'开始生成回答', 'model_first_token':'模型首段文字到达','response_assembled':'回复与配图组装完成','model_finish':'模型停止原因',
    'model_usage':'模型用量', 'model_request_completed':'收到模型返回',
    'model_request_failed':'模型请求失败', 'answer_validation_completed':'回答格式及引用校验通过',
    'answer_validation_failed':'回答格式或引用校验失败', 'generation_completed':'生成处理完成',
    'generation_failed':'生成处理失败', 'final_validation_completed':'最终内容校验完成',
    'response_persist_started':'开始保存问答', 'response_persist_completed':'问答保存完成','response_persist_failed':'问答保存失败',
    'checkpoint_cleanup_failed':'工作流检查点清理失败',
    'chat_completed':'问答处理结束', 'chat_failed':'问答异常', 'response_ready':'准备发送页面',
    'stream_completed':'服务端流式发送结束', 'stream_cancelled':'流式发送中断',
    'stream_failed':'流式发送失败', 'http_completed':'HTTP 请求结束', 'http_failed':'HTTP 请求异常',
}
_FIELDS = {
    'model_stage':'子阶段','intent':'意图','matched':'命中','similarity':'向量相似度',
    'evidence_count':'命中条数','evidence_ids':'知识ID','rerank_scores':'重排分数',
    'history_messages':'历史消息数','answerable':'模型判断可回答','citations':'引用数',
    'finish_reason':'停止原因','outcome':'处理结果','reason':'原因',
    'error_code':'错误分类','error_type':'异常类型','upstream_status':'上游HTTP状态',
    'answer_chars':'回复字数','elapsed_ms':'耗时毫秒','status':'HTTP状态',
    'completed':'HTTP发送完成','success':'校验成功',
}
_ERRORS = {
    'cancelled':'请求被取消或连接已断开', 'timeout':'请求超时', 'connection':'连接失败', 'upstream_http':'上游模型接口返回错误',
    'invalid_json':'模型没有返回有效 JSON', 'answer_schema':'模型回答字段或类型不正确',
    'citation_schema':'引用字段格式不正确', 'citation_validation':'引用缺失或引用了本轮未提供的知识',
    'image_validation':'图片字段不正确或使用了未提供的图片ID',
    'empty_answer':'模型回答为空', 'unexpected':'未分类异常，结合节点及异常类型定位',
    'model_unavailable':'模型生成或校验失败', 'insufficient_evidence':'模型判断资料不足',
    'no_knowledge':'未找到可用知识', 'knowledge':'知识问答', 'extractive':'知识原文回答',
}


def report(records, request_id, content_enabled=False):
    records.sort(key=lambda row:row.get('timestamp',''))
    print('问答排查报告\n问题编号：'+request_id)
    if not records:
        print('没有找到日志。请确认编号、日期、日志目录和保留期限。');return
    metadata=next((r for r in records if r.get('session_ref')),records[0])
    print('会话：'+str(metadata.get('session_ref','未知'))+'  窗口：'+str(metadata.get('window_id','未知')))
    print('\n处理节点：')
    for row in records:
        name=row.get('event','')
        if name not in _LABELS:continue
        values=[]
        for key,label in _FIELDS.items():
            if key not in row:continue
            value=row[key]
            if key in ('error_code','reason'):value=_ERRORS.get(str(value),value)
            if key=='outcome':value={'answered':'回答成功','suggestions':'降级为推荐问题','handoff':'人工服务'}.get(str(value),value)
            if key=='finish_reason':value={'stop':'正常结束','length':'达到输出长度上限','content_filter':'内容过滤'}.get(str(value),value)
            if isinstance(value,bool):value='是' if value else '否'
            values.append(label+'='+str(value))
        print(row.get('timestamp','')+'  '+_LABELS[name]+'  '+'；'.join(values))
    failures=[r for r in records if r.get('event') in (
        'retrieval_model_failed','retrieval_failed','model_request_failed','answer_validation_failed',
        'generation_failed','response_persist_failed','chat_failed','stream_failed','stream_cancelled')]
    print('\n定位结论：')
    if failures:
        first=failures[0]
        print('首个记录到的失败节点：'+_LABELS[first['event']])
        print('原因：'+_ERRORS.get(first.get('error_code'),str(first.get('error_code','发送中断'))))
    else:
        last=next((r for r in reversed(records) if r.get('event')=='chat_completed'),None)
        if last and last.get('outcome')=='answered':print('后端已生成有效回答。若页面未显示，继续看发送节点和浏览器网络/控制台。')
        elif last:print('后端返回了降级结果，原因：'+_ERRORS.get(last.get('reason'),str(last.get('reason'))))
        else:print('尚未找到问答结束记录，可能仍在处理、进程中断或日志不完整。最后节点不能单独证明失败原因。')
    if not content_enabled:
        print('\n要查看已采集的输入输出，加 --debug-content；采集需预先开启 LOG_DEBUG_CONTENT=true。');return
    snapshots=[r for r in records if 'snapshot' in r]
    if not snapshots:
        print('\n没有调试正文。需先开启 LOG_DEBUG_CONTENT=true 并重建应用容器，再复现；旧请求无法补录。');return
    names={'chat_input':'用户输入','retrieval_evidence':'命中知识及内容','model_output':'模型原始返回',
           'answer_validation_context':'校验失败上下文','answer_validated':'校验后的模型结果','chat_output':'最终对外回复'}
    for row in snapshots:
        if row.get('event') not in names:continue
        print('\n【'+names[row['event']]+'】')
        try:
            value=json.loads(row['snapshot'])
            name=row['event']
            if name=='chat_input':print('问题：'+str(value.get('question','')))
            elif name=='retrieval_evidence':
                print('实际检索问题：'+str(value.get('query','')))
                for index,item in enumerate(value.get('evidence',[]),1):
                    print('命中'+str(index)+'：'+str(item.get('title',''))+'（'+str(item.get('id',''))+'）')
                    print('知识内容：'+str(item.get('content','')))
            elif name=='model_output':print(value.get('text',''))
            elif name=='chat_output':
                response=value.get('response',{})
                print('返回状态：'+str(response.get('status'))+'；原因：'+str(response.get('reason')))
                print('页面回复：'+str(response.get('answer','')))
            elif name=='answer_validated':
                result=value.get('result',{})
                print('模型判断可回答：'+str(result.get('answerable')))
                print('回答：'+str(result.get('answer','')))
                print('引用知识：'+str(result.get('citation_ids',[])))
                print('引用图片：'+str(result.get('image_ids',[])))
            else:
                print('本轮允许的知识ID：'+str(value.get('evidence_ids',[])))
                print('本轮允许的图片ID：'+str(value.get('allowed_images',[])))
                print('错误：'+_ERRORS.get(value.get('error_code'),str(value.get('error_code'))))
                print('待校验原文：'+str(value.get('response','')))
        except (ValueError,AttributeError,TypeError):print(row['snapshot'])
        if row.get('truncated'):print('（内容达到调试长度上限，已截断）')
    print('\n提示：发送结束只代表服务端已交付响应，不证明浏览器已经渲染。完整模型输入可用 --event model_input --debug-content 单独查。')


def is_document(record):
    return all(key in record for key in ('时间','输入','处理流程','输出'))


def field(record,key):
    if not is_document(record):return record.get(key)
    names={'request_id':'请求编号','http_request_id':'接口请求编号','session_ref':'会话编号',
           'window_id':'窗口编号','tenant_ref':'企业标识','user_ref':'用户标识','question_category':'问题分类'}
    if key in names:
        value=record['输入'].get(names[key])
        return value or (record['输入'].get('请求编号') if key=='http_request_id' else None)
    if key=='event':return [step.get('事件') for step in record['处理流程']]
    if key=='question_category':
        return next((step.get('详情',{}).get('question_category') for step in record['处理流程'] if step.get('详情',{}).get('question_category')),None)
    return record.get(key)


def main():
    parser=argparse.ArgumentParser(description='按问题编号查看节点排查报告或原始日志')
    parser.add_argument('--directory',default=str(Path(__file__).resolve().parent.parent/'var/logs'))
    parser.add_argument('--month',help='月份 YYYY-MM')
    parser.add_argument('--date',help='日期 YYYY-MM-DD（北京时间）')
    for name in ('request-id','http-request-id','user-ref','tenant-ref','session-ref','window-id','question-category','event'):
        parser.add_argument('--'+name)
    parser.add_argument('--list-sessions',action='store_true',help='列出匹配用户的会话时间、问答数量和文件位置')
    parser.add_argument('--errors',action='store_true',help='只看 WARNING / ERROR')
    parser.add_argument('--report',action='store_true',help='按时间生成中文节点排查报告，须提供 --request-id')
    parser.add_argument('--debug-content',action='store_true',help='读取会话文件或旧调试文件中的输入输出正文')
    args=parser.parse_args()
    if args.date and not re.fullmatch(r'\d{4}-\d{2}-\d{2}',args.date):parser.error('日期格式应为 YYYY-MM-DD')
    if args.month and not re.fullmatch(r'\d{4}-\d{2}',args.month):parser.error('月份格式应为 YYYY-MM')
    if args.report and not args.request_id:parser.error('--report 需要 --request-id')
    if args.debug_content and not (args.request_id or args.user_ref or args.session_ref):parser.error('--debug-content 需要 --request-id、--user-ref 或 --session-ref')
    directory=Path(args.directory)
    if not directory.is_dir():parser.exit(1,'日志目录不存在；确认服务已更新并启动。\n')
    ignored=('directory','date','month','errors','report','debug_content','list_sessions')
    filters={key:value for key,value in vars(args).items() if value is not None and key not in ignored}
    records=[];session_files={}
    for prefix in (('app','debug','conversation') if args.debug_content else ('app','conversation')):
        if prefix=='conversation':
            import sys
            sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
            from app.conversation_logs import conversation_paths
            paths=list(conversation_paths(directory))
        else:paths=sorted(directory.glob(prefix+'-'+(args.date or '*')+'-*.jsonl*'))
        for path in paths:
            if prefix!='conversation' and not re.fullmatch(prefix+r'-\d{4}-\d{2}-\d{2}-\d+\.jsonl(?:\.[1-4])?',path.name):continue
            if path.is_symlink():continue
            if prefix=='conversation':
                if args.month and path.parents[2].name!=args.month:continue
                if args.tenant_ref and path.parents[1].name!='tenant-'+args.tenant_ref:continue
                if args.user_ref and path.parent.name!='user-'+args.user_ref:continue
                if args.session_ref and path.stem!='session-'+args.session_ref:continue
            with path.open(encoding='utf-8') as source:
                for line in source:
                    try:record=json.loads(line)
                    except ValueError:continue
                    if not isinstance(record,dict):continue
                    stamp=record.get('时间',record.get('timestamp',''))
                    if args.date and prefix=='conversation' and not stamp.startswith(args.date):continue
                    if args.month and not (stamp or path.name[4:]).startswith(args.month):continue
                    if prefix=='conversation' and not args.debug_content and is_document(record):
                        record={**record,'输入':{k:v for k,v in record['输入'].items() if k!='问题'},
                                '处理流程':[step for step in record['处理流程'] if '数据' not in step],
                                '输出':{k:v for k,v in record['输出'].items() if k!='最终响应'}}
                    if args.errors:
                        failed=(bool(record['输出'].get('失败节点')) or any(step.get('级别') in ('WARNING','ERROR','CRITICAL') for step in record['处理流程'])) if is_document(record) else record.get('level') in ('WARNING','ERROR','CRITICAL')
                        if not failed:continue
                    def matches(key,value):
                        if key=='request_id':return value in (field(record,'request_id'),field(record,'http_request_id'))
                        if key=='event' and is_document(record):return value in field(record,'event')
                        return field(record,key)==value
                    if all(matches(key,value) for key,value in filters.items()):
                        if args.report or args.debug_content or args.list_sessions:
                            records.append(record)
                            if is_document(record):session_files[(field(record,'tenant_ref'),field(record,'user_ref'),field(record,'session_ref'),record['时间'][:7])]=str(path)
                        else:print(json.dumps(record,ensure_ascii=False))
    if args.list_sessions:
        sessions={};seen=set()
        for record in records:
            if not is_document(record):continue
            key=(field(record,'tenant_ref'),field(record,'user_ref'),field(record,'session_ref'),record['时间'][:7])
            identity=(key,record['时间'],field(record,'request_id'))
            if identity in seen:continue
            seen.add(identity)
            item=sessions.setdefault(key,{'企业':key[0],'用户':key[1],'会话':key[2],'月份':key[3],'开始时间':record['时间'],'最近时间':record['时间'],'问答数量':0,'文件':session_files[key]})
            item['开始时间']=min(item['开始时间'],record['时间']);item['最近时间']=max(item['最近时间'],record['时间']);item['问答数量']+=1
        for item in sorted(sessions.values(),key=lambda value:value['最近时间'],reverse=True):print(json.dumps(item,ensure_ascii=False))
        return
    documents={}
    legacy=[]
    for record in records:
        if is_document(record):documents[(record['时间'],field(record,'request_id'))]=record
        else:legacy.append(record)
    if documents:
        for key in sorted(documents,key=lambda value:(str(value[0]),str(value[1]))):print(json.dumps(documents[key],ensure_ascii=False,indent=2 if args.report else None))
    elif args.report:report(legacy,args.request_id,args.debug_content)
    else:
        for record in legacy:print(json.dumps(record,ensure_ascii=False))

if __name__=='__main__':main()
