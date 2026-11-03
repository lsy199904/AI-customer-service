"""Deterministic, checkpointed LangGraph support workflow.

Customer-facing facts only come from current evidence or registered business tools.
No autonomous write tools or unbounded agent loops are enabled.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from contextvars import copy_context
from concurrent.futures import ThreadPoolExecutor,TimeoutError as FutureTimeout
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
    suggestion_sources:list
    actions:list
    assistance:dict
    guidance:dict
    guide_context:dict
    resolved_question:str

@dataclass
class Context:
    observer:object=None
    cancelled:object=None
    def check(self):
        if self.cancelled is not None and self.cancelled.is_set():raise RequestCancelled()
    def delta(self,text):
        self.check()
        if self.observer:self.observer({'type':'delta','text':text})

    def metadata(self,**fields):
        self.check()
        if self.observer:self.observer({'type':'metadata',**fields})

    def emit(self,stage):
        self.check()
        if self.observer:self.observer({'type':'status','stage':stage})


class SupportWorkflow:
    def __init__(self,service):
        from .image_policy import ImagePolicy
        self.image_policy=ImagePolicy()
        self.service=service;self._resource=None
        self._visual_pool=ThreadPoolExecutor(max_workers=4,thread_name_prefix="visual-plan")
        self._visual_slots=threading.BoundedSemaphore(4);self._visual_lock=threading.Lock();self._visual_jobs={}
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
                        ('generate',self.generate),('clarify',self.clarify),('guide_ack',self.guide_ack),('guide_end',self.guide_end),('validate',self.validate)]:graph.add_node(name,fn)
        graph.add_edge(START,'route')
        graph.add_conditional_edges('route',lambda s:'guide_ack' if s.get('assistance',{}).get('kind')=='ack' else 'clarify' if s.get('assistance',{}).get('kind')=='clarify' else 'guide_end' if s.get('assistance',{}).get('kind') in ('end','complete') else 'validate' if s['intent'] in ('handoff','sensitive') else 'business' if s['intent']=='business' else 'generate' if s['intent'] in REPLIES else 'retrieve')
        graph.add_conditional_edges('retrieve',lambda s:'generate' if s['evidence'] or s['candidates'] else 'validate')
        graph.add_edge('guide_ack','validate');graph.add_edge('clarify','validate');graph.add_edge('guide_end','validate')
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
        values.update(assistance={},guidance=None,guide_context=None)
        if intent in ('knowledge','thanks'):
            from .assistance import plan
            try:
                from .query_context import guidance_history
                values['assistance']=plan(state['question'],guidance_history(state['question'],state['history']),list(self.service.knowledge.rows.values()))
            except Exception as error:event('assistance_unavailable',level='WARNING',**error_fields(error))
        if values['assistance']:
            event('assistance_planned',mode=values.get('assistance',{}).get('kind'),flow_id=(values.get('assistance',{}).get('guidance') or {}).get('flow_id') or values.get('assistance',{}).get('flow_id'))
        event('question_classified',intent=intent,history_messages=len(state['history']))
        return values

    def clarify(self,state:State,runtime:Runtime[Context]):
        runtime.context.emit('clarifying')
        plan=state.get('assistance',{})
        event('clarification_requested',choice_count=len(plan['choices']))
        return {'answer':plan['answer'],'success':True,'reason':'clarification','intent':'clarification'}

    def guide_ack(self,state:State,runtime:Runtime[Context]):
        return {'answer':'好的，当前步骤已保留。您可以继续操作，完成后告诉我，或点“这一步怎么做”继续了解。',
                'success':True,'reason':'guidance_ack','guidance':state['assistance']['guidance']}

    def guide_end(self,state:State,runtime:Runtime[Context]):
        guidance=state['assistance']['guidance']
        completed=guidance['status']=='completed'
        event('guidance_closed',flow_id=guidance['flow_id'],completed=completed)
        return {'answer':'这段流程指引已走完。实际办理结果请以平台页面或人工确认为准，我没有查询后台状态。' if completed else '已结束这段分步指导，您可以继续问其他问题。',
                'success':True,'reason':'guidance_complete' if completed else 'guidance_ended','guidance':guidance}

    def retrieve(self,state:State,runtime:Runtime[Context]):
        runtime.context.emit('retrieving');started=time.monotonic()
        try:
            from .chains import retrieve
            from .deadlines import run,check
            def retrieve_current():
                from .query_context import resolve,local_query
                from .conversation import recommended_selection
                try:
                    resolution=resolve(self.service.model if self.service.config.mode=='llm' and hasattr(self.service.model,'complete') else None,
                        state['question'],state['history'])
                except Exception as error:
                    check()
                    event('question_resolution_unavailable',level='WARNING',**error_fields(error))
                    resolution={'kind':'followup','question':local_query(state['question'],state['history']),'clarification':''}
                check()
                event('question_resolved',resolution_kind=resolution['kind'],used_context=resolution['question']!=state['question'])
                debug_event('resolved_question',original_question=state['question'],**resolution)
                if resolution['kind']=='clarify':return {'clarification':resolution['clarification']}
                query=state.get('assistance',{}).get('query') or resolution['question']
                if self.service.config.retrieval_backend!='semantic' and resolution['kind']=='independent':query=retrieval_query(query,[])
                resolved,preferred=recommended_selection(self.service.knowledge,query,state['history'])
                found=retrieve(self.service.knowledge,resolved,preferred_id=preferred) if preferred else retrieve(self.service.knowledge,resolved)
                found['retrieval'].setdefault('query',resolved)
                return found
            found=run(retrieve_current,self.service.config.retrieval_timeout)
            if found.get('clarification'):
                return {'success':True,'intent':'clarification','reason':'followup_clarification','answer':found['clarification'],'evidence':[],'candidates':[]}
            runtime.context.check()
            report=found['retrieval']
            evidence=found['evidence'];candidates=self.service.media.candidates(report.get('query',state['question']),evidence)
            hits=report.get('hits',[])
            event('retrieval_candidates',selection_policy=report.get('selection_policy'),
                similarity_knowledge_id=report.get('similarity_knowledge_id'),
                candidates=report.get('_candidate_decisions',[]),configuration=report.get('_configuration'))
            debug_event('retrieval_evidence',query=report.get('query'),evidence=evidence,report={k:v for k,v in report.items() if k!='hits'})
            event('retrieval_completed',matched=report.get('matched'),similarity=report.get('similarity'),
                  threshold=report.get('threshold'),title_matched=report.get('title_matched'),
                  evidence_count=len(evidence),evidence_ids=[r['id'] for r in evidence],
                  rerank_scores=[round(float(hit[0]),6) for hit in hits],
                  elapsed_ms=round((time.monotonic()-started)*1000,2))
            values={'retrieval':report,'evidence':evidence,'candidates':candidates,'resolved_question':report.get('query',state['question'])}
            if state.get('assistance',{}).get('kind')=='guide':
                from .assistance import stage_context
                guidance=state['assistance']['guidance'];current=stage_context(guidance,evidence)
                from .assistance import chapter,revision,guide_state
                row=chapter(evidence,guidance['flow_id'])
                if row and guidance['source_revision']!=revision(row):
                    guidance=guide_state(guidance['flow_id'],0,row,notice='知识内容已更新，已回到第一步。');current=stage_context(guidance,evidence)
                if current:
                    values.update(guidance=guidance,guide_context=current)
                    event('guidance_step_selected',flow_id=guidance['flow_id'],step=guidance['step']+1,total=guidance['total'])
                else:
                    # Never advance a stale guide using a different chapter or no evidence.
                    values.update(evidence=[],candidates=[],retrieval={**report,'matched':False,'reason':'guidance_source_unavailable'})
                    event('guidance_source_unavailable',level='WARNING',flow_id=guidance['flow_id'])
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
        from .pdf_media import reserved_qr,generation_evidence
        qr=reserved_qr(state.get('resolved_question') or state['question'],state['candidates'])
        self.start_visual(state)
        # The product identity is owned by the service, independent of the model vendor.
        if intent=='identity':return {'answer':REPLIES[intent],'reason':intent,'success':True}
        if s.config.mode!='llm':
            if conversation:return {'answer':REPLIES[intent],'reason':intent,'success':True}
            if state['candidates'] and intent=='image':return {'answer':'找到这些相关图片，您可以点击放大查看。还想了解哪一部分呢？','reason':'image','success':True,'selected':state['evidence']}
            if state['evidence']:
                cleaned=generation_evidence(state['evidence'],bool(qr))
                text=state['guide_context']['stage_evidence'] if state.get('guide_context') else cleaned[0]['content']
                supported=[r for r in state['evidence'] if qr and qr['id'] in r.get('image_ids',[])]
                if qr:text='可以使用下方'+qr['title']+'查看资料提供的入口。'
                return {'selected':supported[:1] or [state['evidence'][0]],'answer':text,'reason':'guidance' if state.get('guide_context') else 'extractive','success':True}
            return {}
        started=time.monotonic()
        try:
            # Forward every token immediately. Grounding diagnostics never replace successful prose.
            context={**state['page_context'],'_intent':intent,'_media':state['candidates'],
                '_resolved_question':state['retrieval'].get('query',state['question']),
                '_on_delta':runtime.context.delta if runtime.context.observer else None,
                '_guidance':state.get('guide_context'),'_reserved_qr':bool(qr)}
            result=s.model.answer(state.get('assistance',{}).get('resolved_question') or state['question'],state['history'],generation_evidence(state['evidence'],bool(qr)),context)
            runtime.context.check()
            event('generation_completed',citations=len(result.get('citation_ids',[])),
                  history_messages=len(state['history']),elapsed_ms=round((time.monotonic()-started)*1000,2))
            if not result['answerable']:return {'reason':'insufficient_evidence'}
            selected=[r for r in state['evidence'] if r['id'] in result['citation_ids']]
            if not conversation:
                from .grounding import unsupported_literals,citation_ids
                from .observability import grounding_warning
                # Diagnostics are advisory, including checker failures; model/transport errors above remain errors.
                try:
                    violations=unsupported_literals(result['answer'],state['evidence'],state.get('guide_context'))
                    if violations:grounding_warning(violations,state['evidence'],state.get('guide_context'))
                except Exception as error:event('generation_grounding_check_unavailable',level='WARNING',**error_fields(error))
                supporting=set(citation_ids(result['answer'],selected))
                narrowed=[r for r in selected if r['id'] in supporting]
                if narrowed:selected=narrowed
                if qr:
                    supported=[r for r in state['evidence'] if qr['id'] in r.get('image_ids',[])]
                    selected=list({r['id']:r for r in [*selected,*supported]}.values())
                runtime.context.metadata(citations=[s.citation(r) for r in selected],images=[],media_pending=self.visual_pending(state))
            return {'selected':selected,'images':[],'answer':result['answer'],'reason':'guidance' if state.get('guide_context') else intent,'success':True}
        except RequestCancelled:raise
        except Exception as error:
            event('generation_failed',level='ERROR',evidence_count=len(state['evidence']),
                  history_messages=len(state['history']),elapsed_ms=round((time.monotonic()-started)*1000,2),**error_fields(error))
            s.observe('generation_failed',0)
            if conversation:return {'answer':REPLIES[intent],'success':True,'reason':'conversation_fallback'}
            return {'reason':'model_unavailable','answer':'我这边暂时没能完成回答，请稍后重试，也可以试试下面的问题。'}
        finally:s.observe('generation',time.monotonic()-started)

    def validate(self,state:State,runtime:Runtime[Context]):
        runtime.context.emit('assembling');s=self.service
        # Citations, visual intent and asset choice are separate decisions. Never re-add bound images.
        selected=state['selected'];images=[]
        if state['success'] and state['candidates']:
            event('image_selection_started')
            if self.image_policy.parallel(s.config.mode,s.model):
                decision=self.finish_visual(state)
            else:
                decision=self.image_policy.propose(s.config.mode,s.model,state['question'],state['answer'],state['history'],selected,state['candidates'],state.get('guide_context'),state.get('resolved_question'))
            from .pdf_media import reserved_qr
            qr=reserved_qr(state.get('resolved_question') or state['question'],state['candidates'])
            decision=self.image_policy.guard(state['question'],decision)
            if qr:decision={'need_images':True,'reason':'explicit_image','flow_ids':[],'multiple_flows':False,'image_ids':[qr['id']]}
            runtime.context.check()
            chosen,report=self.image_policy.assemble(decision,state['candidates'],selected,state['evidence'])
            images=[s.media.public(r) for r in chosen]
            if s.config.mode!='llm' and state['reason']=='image':
                chosen_ids={r['id'] for r in chosen}
                selected=[r for r in selected if chosen_ids & set(r.get('image_ids',[]))]
            event('image_selection_completed',**report)
        else:
            self.discard_visual(state)
            event('image_selection_completed',need_images=False,reason='no_successful_visual_evidence',
                primary_flows=[],candidates=[],selected_images=[],excluded_images=[])
        values={'selected':selected,'images':images,'suggestions':[],'suggestion_sources':[],'actions':[]}
        if not state['success'] and state['intent']!='handoff':
            values.update(images=[],selected=[],suggestions=recommended_questions(s.knowledge,state['question'],
                state['evidence'],sensitive=state['intent']=='sensitive' or state['retrieval_failed'],
                related_titles=state['retrieval'].get('_suggestion_titles',[])),
                actions=[{'type':'handoff','label':'以上都不是，转人工','message':'转人工客服'}])
            if state['reason'] in ('no_knowledge','insufficient_evidence','sensitive_topic'):values['answer']=NO_ANSWER
        if values['suggestions'] and state['intent']!='sensitive' and not state['retrieval_failed']:
            from .conversation import suggestion_sources
            try:values['suggestion_sources']=suggestion_sources(s.knowledge,values['suggestions'])
            except Exception:pass
        from .assistance import FLOWS,actions_for,chapter
        plan=state.get('assistance',{})
        if state['success'] and plan.get('kind')=='clarify':
            values['actions']=[{'type':'clarify','label':q,'message':q} for q in plan['choices']]
        elif state['success'] and state.get('guidance'):
            values['actions']=actions_for(state['guidance'],list(s.knowledge.rows.values()))
        elif state['success'] and plan.get('kind') in ('offer','choice') and plan.get('flow_id') and chapter(state['selected'],plan['flow_id']):
            flow=FLOWS[plan['flow_id']]
            values['actions']=[{'type':'guide','label':'带我一步步办理','message':'分步指导：'+flow['title']}]
        if not state['success']:values['guidance']=None
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
        try:
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
        finally:self.discard_visual(state)
        return result,key

    def start_visual(self,state):
        s=self.service
        from .pdf_media import reserved_qr
        if reserved_qr(state.get('resolved_question') or state['question'],state['candidates']):return
        if not [r for r in state['candidates'] if r.get('kind')!='qr'] or not self.image_policy.parallel(s.config.mode,s.model):return
        if not self._visual_slots.acquire(blocking=False):
            event('image_planning_unavailable',reason='visual_capacity');return
        ctx=copy_context();key=self.key(state)
        event('image_planning_started',parallel=True)
        try:
            job=self._visual_pool.submit(ctx.run,self.image_policy.propose,s.config.mode,s.model,state['question'],'',state['history'],
                state['evidence'],state['candidates'],state.get('guide_context'),state.get('resolved_question'))
        except Exception:
            self._visual_slots.release();return
        job.add_done_callback(lambda future:self._visual_slots.release())
        with self._visual_lock:self._visual_jobs[key]=job

    def visual_pending(self,state):
        with self._visual_lock:job=self._visual_jobs.get(self.key(state))
        return job is not None and not job.done()

    def finish_visual(self,state):
        with self._visual_lock:job=self._visual_jobs.pop(self.key(state),None)
        if job is not None:
            try:return job.result(timeout=min(2.0,max(0.0,float(os.getenv('MEDIA_FINAL_WAIT_SECONDS','0.35')))))
            except FutureTimeout:
                job.cancel();event('image_planning_unavailable',reason='visual_wait_timeout')
            except Exception as error:event('image_planning_unavailable',level='WARNING',**error_fields(error))
        return self.image_policy.unavailable()

    def discard_visual(self,state):
        with self._visual_lock:job=self._visual_jobs.pop(self.key(state),None)
        if job is not None:job.cancel()

    @staticmethod
    def key(state):
        return hashlib.sha256(json.dumps([state['actor']['tenant_id'],state['actor']['sub'],state['session_id'],state['request_id']],ensure_ascii=False).encode()).hexdigest()

    def close(self):
        with self._visual_lock:
            for job in self._visual_jobs.values():job.cancel()
            self._visual_jobs.clear()
        self._visual_pool.shutdown(wait=False,cancel_futures=True)
        if self._resource is not None:self._resource.close();self._resource=None
