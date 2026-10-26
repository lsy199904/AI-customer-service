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
from .conversation import REPLIES,intent_of,contextual_query,retrieval_query
from .tools import ToolContext

FALLBACK='这个问题暂时没有找到足够准确的资料，为了不误导您，建议联系人工客服进一步确认。您可以通过下方电话或邮箱联系我们～'

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

@dataclass
class Context:
    observer:object=None
    cancelled:object=None
    def check(self):
        if self.cancelled is not None and self.cancelled.is_set():raise RequestCancelled()
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
        graph.add_conditional_edges('route',lambda s:'validate' if s['intent']=='handoff' else 'business' if s['intent']=='business' else 'generate' if s['intent'] in REPLIES else 'retrieve')
        graph.add_conditional_edges('retrieve',lambda s:'generate' if s['evidence'] or s['candidates'] else 'validate')
        graph.add_edge('business','validate');graph.add_edge('generate','validate');graph.add_edge('validate',END)
        self.graph=graph.compile(checkpointer=self.saver,name='smarttitu_support')

    def route(self,state:State,runtime:Runtime[Context]):
        runtime.context.emit('routing');intent=intent_of(state['question'])
        values={'intent':intent,'answer':FALLBACK,'reason':'no_knowledge','success':False,
                'selected':[],'images':[],'evidence':[],'candidates':[],'retrieval_failed':False,
                'retrieval':{'matched':False,'method':'skipped','threshold':self.service.config.min_similarity,'similarity':None}}
        if intent=='handoff':values.update(answer='好的，您可以通过以下方式联系人工客服。',reason='requested_handoff')
        return values

    def retrieve(self,state:State,runtime:Runtime[Context]):
        runtime.context.emit('retrieving');started=time.monotonic()
        try:
            query=contextual_query(state['question'],state['history']) if self.service.config.retrieval_backend=='semantic' else retrieval_query(state['question'],state['history'])
            from .chains import retrieve
            found=retrieve(self.service.knowledge,query)
            runtime.context.check()
            evidence=found['evidence'];candidates=self.service.media.candidates(state['question'],evidence)
            values={'retrieval':found['retrieval'],'evidence':evidence,'candidates':candidates}
            if not evidence and not candidates and state['intent']=='image':
                values['answer']='暂时没有找到您需要的图片资料。您可以通过下方方式联系人工客服，我们帮您确认并提供合适的资料～'
            return values
        except RequestCancelled:raise
        except Exception:
            self.service.observe('retrieval_failed',0)
            return {'reason':'retrieval_unavailable','answer':'资料查询暂时不可用，您可以稍后再试，或通过下方方式联系人工客服。',
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
        except Exception:
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
            context={**state['page_context'],'_intent':intent,'_media':state['candidates']}
            result=s.model.answer(state['question'],state['history'],state['evidence'],context)
            runtime.context.check()
            if not result['answerable']:return {'reason':'insufficient_evidence'}
            selected=[r for r in state['evidence'] if r['id'] in result['citation_ids']]
            allowed=s.media.bound(selected) if selected else state['candidates'] if intent=='image' else []
            images=[s.media.public(r) for r in allowed if r['id'] in result.get('image_ids',[])]
            return {'selected':selected,'images':images,'answer':result['answer'],'reason':intent,'success':True}
        except RequestCancelled:raise
        except Exception:
            s.observe('generation_failed',0)
            if conversation:return {'answer':REPLIES[intent],'success':True,'reason':'conversation_fallback'}
            return {'reason':'model_unavailable','answer':'我这边暂时没能完成回答，您可以稍后重试，或通过以下方式联系人工客服。'}
        finally:s.observe('generation',time.monotonic()-started)

    def validate(self,state:State,runtime:Runtime[Context]):
        runtime.context.emit('validating');s=self.service;images=state['images']
        if state['success'] and state['selected']:
            bound=[s.media.public(r) for r in s.media.bound(state['selected'])]
            images=list({r['id']:r for r in bound+images}.values())[:4]
        return {'images':images}

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
                # Resume only the same authorized request; checkpoints never override identity checks.
                result=self.graph.invoke(None,config,context=context) if previous.next else previous.values
            else:result=self.graph.invoke(state,config,context=context)
        return result,key

    @staticmethod
    def key(state):
        return hashlib.sha256(json.dumps([state['actor']['tenant_id'],state['actor']['sub'],state['session_id'],state['request_id']],ensure_ascii=False).encode()).hexdigest()

    def close(self):
        if self._resource is not None:self._resource.close();self._resource=None
