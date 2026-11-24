"""Daily RAG admission is persistent, shared and independent of fixed FAQ answers."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch,Mock
from zoneinfo import ZoneInfo

import pytest
from app.core import Settings,Service
from app.workflow import SupportWorkflow,Context

@pytest.fixture
def config(tmp_path):
    return Settings(secret='daily-quota-test-'+('x'*40),db=str(tmp_path/'chat.db'),
                    retrieval_backend='lexical',global_rag_questions_per_day=2)

@pytest.fixture
def service(config):
    service=Service(config)
    yield service
    service.close()

def test_quota_event_is_kept_in_compact_logs():
    from app.observability import compact_steps
    row={'事件':'global_rag_quota','级别':'INFO','详情':{'allowed':False,'limit':1000}}
    assert compact_steps([row])==[row]

def test_defaults_and_validation(monkeypatch,config):
    monkeypatch.delenv('GLOBAL_RAG_QUESTIONS_PER_DAY',raising=False)
    assert Settings().global_rag_questions_per_day==1000
    for value in (0,-1,10000001):
        config.global_rag_questions_per_day=value
        with pytest.raises(ValueError):config.validate()

def test_concurrent_connections_cannot_overshoot_and_restart_keeps_usage(config,service):
    other=Service(config)
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda i:(service if i%2 else other).reserve_rag_quota(),range(20)))
        assert sum(results)==2
    finally:other.close()
    restarted=Service(config)
    try:assert not restarted.reserve_rag_quota()
    finally:restarted.close()

def test_beijing_midnight_resets_without_deleting_previous_counter(service):
    before=datetime(2026,11,17,23,59,59,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
    with patch('app.core.time.time',return_value=before):
        assert service.reserve_rag_quota() and service.reserve_rag_quota()
        assert not service.reserve_rag_quota()
    with patch('app.core.time.time',return_value=before+1):assert service.reserve_rag_quota()
    assert service.db.execute('SELECT COUNT(*) FROM global_rag_daily_limits').fetchone()[0]==2

def test_exhaustion_blocks_before_query_resolution_or_any_model(service):
    for _ in range(2):service.reserve_rag_quota()
    workflow=object.__new__(SupportWorkflow);workflow.service=service
    with patch('app.query_context.resolve',side_effect=AssertionError('model-assisted resolution invoked')):
        result=workflow.retrieve({'question':'注册流程','history':[]},SimpleNamespace(context=Context()))
    assert result['reason']=='global_daily_limit'
    assert result['answer']=='请稍后重试，您仍可查看常见问题或选择相关问题获取解答。如需进一步帮助，请联系人工客服：4008841883，help@china-entercom.net。'
    assert result['evidence']==[]

def test_chat_quota_is_global_cached_and_handoff_still_works(config,service):
    config.global_rag_questions_per_day=1
    a={'tenant_id':'tenant-a','sub':'alice'};b={'tenant_id':'tenant-b','sub':'bob'}
    sa=service.create(a,{})['session_id'];sb=service.create(b,{})['session_id']
    # Let the first admitted RAG request finish locally without external APIs.
    service.model=Mock();service.model.answer.side_effect=AssertionError('external LLM')
    first=service.chat(a,sa,{'message':'注册流程','request_id':'daily-first-request'})
    assert service.db.execute('SELECT SUM(used) FROM global_rag_daily_limits').fetchone()[0]==1
    assert service.chat(a,sa,{'message':'注册流程','request_id':'daily-first-request'})==first
    blocked=service.chat(b,sb,{'message':'企业认证流程','request_id':'daily-blocked-request'})
    assert blocked['reason']=='global_daily_limit'
    handoff=service.chat(b,sb,{'message':'转人工客服','request_id':'daily-handoff-request'})
    assert handoff['intent']=='handoff'
    assert len(service.bootstrap()['faq']['items'])==6
    assert service.db.execute('SELECT SUM(used) FROM global_rag_daily_limits').fetchone()[0]==1
    service.model.answer.assert_not_called()
