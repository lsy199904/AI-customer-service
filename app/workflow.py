"""Deterministic, checkpointed LangGraph support workflow.

Customer-facing facts only come from current evidence or registered business tools.
No autonomous write tools or unbounded agent loops are enabled.
"""
from dataclasses import dataclass
import hashlib
import json
import sqlite3
import threading
import time
from typing import TypedDict
from langgraph.graph import StateGraph,START,END
from langgraph.runtime import Runtime
from langsmith import tracing_context
from .conversation import REPLIES,NO_ANSWER,intent_of,contextual_query,retrieval_query,sensitive_topic,rejected_recommendations,recommended_questions
from .observability import event,error_fields,debug_event
from .tools import ToolContext

FALLBACK=NO_ANSWER

class RequestCancelled(Exception):pass
class WorkflowConflict(Exception):pass

class State(TypedDict,total=False):
    question:str
    history:list
    page_context:dict
    actor:dict
    session_id:str
    request_id:str
    intent:str
    answer:str
    reason:str
    success:bool
    evidence:list
    candidates:list
    selected:list
    images:list
    retrieval:dict
    retrieval_failed:bool
    result:dict
    suggestions:list
    actions:list

@dataclass
class Context:
    observer:object=None
    cancelled:object=None
    def check(self):
        if self.cancelled is not None and self.cancelled.is_set():raise RequestCancelled()
    def delta(self,text):
        self.check()
        if self.observer:self.observer({'type':'delta','text':text})

    def emit(self,stage):
        self.check()
        if self.observer:self.observer({'type':'status','stage':stage})


class SupportWorkflow:
    def __init__(self,service):
        self.service=service;self._resource=None
        if service.config.database_url:
            from psycopg_pool import ConnectionPool
            from langgraph.checkpoint.postgres import PostgresSaver
            self._resource=ConnectionPool(service.config.database_url,min_size=1,max_size=8,
                kwargs={'autocommit':True,'prepare_threshold':0,'connect_timeout':10,'options':'-c search_path=assistant,public'})
            self._resource.wait(timeout=15)
            self.saver=PostgresSaver(self._resource)
            with self._resource.connection() as connection:
                connection.execute('SELECT pg_advisory_lock(729630041)')
                try:self.saver.setup()
                finally:connection.execute('SELECT pg_advisory_unlock(729630041)')
        else:
            from langgraph.checkpoint.sqlite import SqliteSaver
            self._resource=sqlite3.connect(service.config.db+'.checkpoints.sqlite3',check_same_thread=False)
            self.saver=SqliteSaver(self._resource);self.saver.setup()
        graph=StateGraph(State,context_schema=Context)
        for name,fn in [('route',self.route),('retrieve',self.retrieve),('business',self.business),
                        ('generate',self.generate),('validate',self.validate)]:graph.add_node(name,fn)
        graph.add_edge(START,'route')
        graph.add_conditional_edges('route',lambda s:'validate' if s['intent'] in ('handoff','sensitive') else 'business' if s['intent']=='business' else 'generate' if s['intent'] in REPLIES else 'retrieve')
        graph.add_conditional_edges('retrieve',lambda s:'generate' if s['evidence'] or s['candidates'] else 'validate')
        graph.add_edge('business','validate');graph.add_edge('generate','validate');graph.add_edge('validate',END)
        self.graph=graph.compile(checkpointer=self.saver,name='smarttitu_support')

    def route(self,state:State,runtime:Runtime[Context]):
        runtime.context.emit('routing');intent=intent_of(state['question'])
        if rejected_recommendations(state['question'],state['history']):intent='handoff'
        if intent!='handoff' and sensitive_topic(state['question']):intent='sensitive'
        values={'intent':intent,'answer':FALLBACK,'reason':'no_knowledge','success':False,
                'selected':[],'images':[],'evidence':[],'candidates':[],'retrieval_failed':False,
                'retrieval':{'matched':False,'method':'skipped','threshold':self.service.config.min_similarity,'similarity':None}}
        if intent=='sensitive':values['reason']='sensitive_topic'
        if intent=='handoff':values.update(answer='好的，您可以通过以下方式联系人工客服。',reason='requested_handoff')
        event('question_classified',intent=intent,history_messages=len(state['history']))
        return values

    def retrieve(self,state:State,runtime:Runtime[Context]):
        runtime.context.emit('retrieving');started=time.monotonic()
        try:
            query=contextual_query(state['question'],state['history']) if self.service.config.retrieval_backend=='semantic' else retrieval_query(state['question'],state['history'])
            from .chains import retrieve
            from .deadlines import run
            found=run(lambda:retrieve(self.service.knowledge,query),self.service.config.retrieval_timeout)
            runtime.context.check()
            evidence=found['evidence'];candidates=self.service.media.candidates(state['question'],evidence)
            report=found['retrieval']
            hits=report.get('hits',[])
            debug_event('retrieval_evidence',query=query,evidence=evidence,report={k:v for k,v in report.items() if k!='hits'})
            event('retrieval_completed',matched=report.get('matched'),similarity=report.get('similarity'),
                  threshold=report.get('threshold'),title_matched=report.get('title_matched'),
                  evidence_count=len(evidence),evidence_ids=[r['id'] for r in evidence],
                  rerank_scores=[round(float(hit[0]),6) for hit in hits],
                  elapsed_ms=round((time.monotonic()-started)*1000,2))
            values={'retrieval':report,'evidence':evidence,'candidates':candidates}
            if not evidence and not candidates and state['intent']=='image':
                values['answer']=NO_ANSWER
            return values
        except RequestCancelled:raise
        except Exception as error:
            event('retrieval_failed',level='WARNING',elapsed_ms=round((time.monotonic()-started)*1000,2),**error_fields(error))
            from .deadlines import RetrievalTimeout
            if isinstance(error,RetrievalTimeout):
                self.service.observe('retrieval_timeout',0)
                return {'reason':'retrieval_timeout','answer':'资料查询超时了，请稍后重试，也可以试试下面的问题。',
                    'retrieval_failed':True,'retrieval':{'matched':False,'method':self.service.config.retrieval_backend,'reason':'retrieval_timeout','timeout_seconds':self.service.config.retrieval_timeout,'similarity':None}}
            self.service.observe('retrieval_failed',0)
            return {'reason':'retrieval_unavailable','answer':'资料查询暂时不可用，请稍后再试，也可以试试下面的问题。',
                'retrieval_failed':True,'retrieval':{'matched':False,'method':self.service.config.retrieval_backend,'reason':'retrieval_unavailable','similarity':None}}
        finally:self.service.observe('retrieval',time.monotonic()-started)

    def business(self,state:State,runtime:Runtime[Context]):
        runtime.context.emit('business');q=state['question']
        name='create_ticket' if '工单' in q else 'query_balance' if '余额' in q or '剩余' in q else 'query_order' if '订单' in q else 'query_verification'
        ctx=ToolContext(state['actor']['tenant_id'],state['actor']['sub'],state['session_id'],state['request_id'])
        try:
            result=self.service.tools.invoke(name,{'question':q},ctx)
            return {'answer':result['answer'],'success':True,'reason':'business_tool'}
        except LookupError:
            return {'answer':'我暂时还无法直接查询企业的实时余额、订单或认证状态，也不能替您创建工单。您可以联系人工客服进一步处理。','reason':'business_tool_unavailable'}
        except Exception as error:
            event('business_tool_failed',level='ERROR',**error_fields(error))
            return {'answer':'业务查询暂时不可用，请稍后再试或联系人工客服。','reason':'business_tool_unavailable'}

    def generate(self,state:State,runtime:Runtime[Context]):
        runtime.context.emit('generating');s=self.service;intent=state['intent'];conversation=intent in REPLIES
        if s.config.mode!='llm':
            if conversation:return {'answer':REPLIES[intent],'reason':intent,'success':True}
            if state['candidates'] and intent=='image':return {'answer':'找到这些相关图片，您可以点击放大查看。还想了解哪一部分呢？','reason':'image','success':True,'images':[s.media.public(r) for r in state['candidates']]}
            if state['evidence']:return {'selected':[state['evidence'][0]],'answer':state['evidence'][0]['content'],'reason':'extractive','success':True}
            return {}
        started=time.monotonic()
        try:
            context={**state['page_context'],'_intent':intent,'_media':state['candidates'],'_on_delta':runtime.context.delta if runtime.context.observer else None}
            result=s.model.answer(state['question'],state['history'],state['evidence'],context)
            runtime.context.check()
            event('generation_completed',citations=len(result.get('citation_ids',[])),
                  history_messages=len(state['history']),elapsed_ms=round((time.monotonic()-started)*1000,2))
            if not result['answerable']:return {'reason':'insufficient_evidence'}
            selected=[r for r in state['evidence'] if r['id'] in result['citation_ids']]
            allowed=s.media.bound(selected) if selected else state['candidates'] if intent=='image' else []
            images=[s.media.public(r) for r in allowed if r['id'] in result.get('image_ids',[])]
            return {'selected':selected,'images':images,'answer':result['answer'],'reason':intent,'success':True}
        except RequestCancelled:raise
        except Exception as error:
            event('generation_failed',level='ERROR',evidence_count=len(state['evidence']),
                  history_messages=len(state['history']),elapsed_ms=round((time.monotonic()-started)*1000,2),**error_fields(error))
            s.observe('generation_failed',0)
            if conversation:return {'answer':REPLIES[intent],'success':True,'reason':'conversation_fallback'}
            return {'reason':'model_unavailable','answer':'我这边暂时没能完成回答，请稍后重试，也可以试试下面的问题。'}
        finally:s.observe('generation',time.monotonic()-started)

    def validate(self,state:State,runtime:Runtime[Context]):
        runtime.context.emit('assembling');s=self.service;images=state['images']
        if state['success'] and state['selected']:
            bound=[s.media.public(r) for r in s.media.bound(state['selected'])]
            images=list({r['id']:r for r in bound+images}.values())[:4]
        values={'images':images,'suggestions':[],'actions':[]}
        if not state['success'] and state['intent']!='handoff':
            values.update(images=[],selected=[],suggestions=recommended_questions(s.knowledge,state['question'],
                state['evidence'],sensitive=state['intent']=='sensitive' or state['retrieval_failed'],
                related_titles=state['retrieval'].get('_suggestion_titles',[])),
                actions=[{'type':'handoff','label':'以上都不是，转人工','message':'转人工客服'}])
            if state['reason'] in ('no_knowledge','insufficient_evidence','sensitive_topic'):values['answer']=NO_ANSWER
        event('response_assembled',success=state['success'],reason=state['reason'],
              selected_count=len(values.get('selected',state['selected'])),image_count=len(values['images']),
              suggestion_count=len(values['suggestions']))
        return values

    def invoke(self,state,observer=None,cancelled=None):
        key=self.key(state)
        now=time.time()
        with self.service.lock,self.service.db:
            self.service.db.execute('INSERT INTO workflow_runs VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated=excluded.updated',(key,state['session_id'],state['request_id'],'running',now,now))
        config={'configurable':{'thread_id':key},'recursion_limit':12}
        context=Context(observer,cancelled)
        with tracing_context(enabled=False):
            previous=self.graph.get_state(config)
            if previous.values:
                if previous.values.get('question')!=state['question']:raise WorkflowConflict('工作流请求编号冲突')
                if any(h.get('created_at',0)<self.service.cutoff() for h in previous.values.get('history',[])):
                    # A resumed request must never reintroduce expired conversation text.
                    self.saver.delete_thread(key)
                    previous=self.graph.get_state(config)
                # Resume only the same authorized request; checkpoints never override identity checks.
                result=(self.graph.invoke(state,config,context=context) if not previous.values else
                        self.graph.invoke(None,config,context=context) if previous.next else previous.values)
            else:result=self.graph.invoke(state,config,context=context)
        return result,key

    @staticmethod
    def key(state):
        return hashlib.sha256(json.dumps([state['actor']['tenant_id'],state['actor']['sub'],state['session_id'],state['request_id']],ensure_ascii=False).encode()).hexdigest()

    def close(self):
        if self._resource is not None:self._resource.close();self._resource=None
