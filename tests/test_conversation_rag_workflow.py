"""Exercise the session and RAG workflow with controlled model responses."""
import json
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from app.business_flows import GUIDED_FLOWS
from app.chains import retrieve
from app.core import APIError, Service, Settings
from app.ingestion import parse_document
from app.image_policy import ImagePolicy
from app.query_context import interpret


ACTOR = {'tenant_id': 'tenant', 'sub': 'alice'}


@pytest.fixture(scope='module')
def current_knowledge(tmp_path_factory):
    source = Path(__file__).resolve().parents[1] / 'knowledge_sources' / 'SmartTITU客户问答.docx'
    document = parse_document(source)
    path = tmp_path_factory.mktemp('current-knowledge') / 'knowledge.jsonl'
    rows = [dict(chunk, id=f'KB-{index:06d}', source_file=document.filename,
                 audience='customer', status='source_based')
            for index, chunk in enumerate(document.chunks, 1)]
    path.write_text('\n'.join(json.dumps(row, ensure_ascii=False) for row in rows), encoding='utf-8')
    return str(path)


@pytest.fixture
def service(tmp_path, current_knowledge):
    app = Service(Settings(secret='x'*40, db=str(tmp_path/'chat.db'), retrieval_backend='lexical',
                           knowledge=current_knowledge))
    app.config.mode = 'llm'
    app.model = Mock()
    try:
        with patch('app.image_policy.ImagePolicy.propose', return_value=ImagePolicy.unavailable()):
            yield app
    finally:
        app.close()


def plan(intent, kind='independent', **values):
    return json.dumps(dict(intent=intent, kind=kind, **values), ensure_ascii=False)


def chat(service, sid, question, request, **fields):
    return service.chat(ACTOR, sid, {'message': question, 'request_id': request, **fields})


def evidence_answer(question, history, evidence, context):
    return {'answerable': bool(evidence), 'answer': evidence[0]['content'] if evidence else '',
            'citation_ids': [item['id'] for item in evidence], 'image_ids': []}


@pytest.mark.parametrize('question', ['今天天气怎么样？', '聊聊你喜欢的足球队',
                                     '推荐色情网站', '给我一个通用 Flask API 示例'])
def test_out_of_scope_skips_retrieval_and_offers_product_questions(service, question):
    service.model.complete.return_value = plan('out_of_scope')
    sid = service.create(ACTOR, {})['session_id']
    with patch.object(service, 'reserve_rag_quota', side_effect=AssertionError('scope bypass')):
        answer = chat(service, sid, question, 'scope-request')
    assert answer['reason'] == 'out_of_scope'
    assert answer['citations'] == []
    assert '企业认证流程' in answer['suggestions']
    assert any(action['type'] == 'handoff' for action in answer['actions'])
    assert len(service.history(ACTOR, sid)['items']) == 2


def test_handoff_buttons_work_with_classifier_unavailable(service):
    service.model.complete.side_effect = TimeoutError
    sid = service.create(ACTOR, {})['session_id']
    result = chat(service, sid, '转人工客服', 'human-button-request', client_action='handoff')
    service.model.complete.assert_not_called()
    assert result['handoff'] and result['contact']['phone'] == '4008841883'
    assert chat(service, sid, '转人工客服', 'human-button-request', client_action='handoff') == result
    with pytest.raises(APIError, match='相同request_id'):
        chat(service, sid, '转人工客服', 'human-button-request')


def test_complaint_followed_by_product_question(service):
    service.model.complete.side_effect = [plan('complaint', evidence='我要投诉'), plan('knowledge', retry_query='API 密钥管理')]
    service.model.answer.side_effect = evidence_answer
    sid = service.create(ACTOR, {})['session_id']
    assert chat(service, sid, '我要投诉，客服一直没解决', 'current-complaint')['handoff']
    response = chat(service, sid, 'API 密钥管理', 'subsequent-api-key')
    assert not response['handoff']
    assert any('API' in item['title'] and '密钥' in item['title'] for item in response['citations'])
    assert service.model.answer.call_args.args[1] == []


def test_realtime_status_and_delegate_action_never_invoke_business_tools(service):
    sid = service.create(ACTOR, {})['session_id']
    service.model.complete.side_effect = [
        plan('account_status', evidence='还有多少余额'),
        plan('account_status', evidence='还有多少余额'),
        plan('action', evidence='替我付掉这笔账单'),
        plan('action', evidence='替我付掉这笔账单'),
    ]
    with patch.object(service.tools, 'invoke', side_effect=AssertionError('business tool called')), \
         patch.object(service, 'reserve_rag_quota', side_effect=AssertionError('retrieval called')):
        status = chat(service, sid, '帮我查一下本企业现在还有多少余额。', 'actual-balance')
        action = chat(service, sid, '替我付掉这笔账单', 'delegate-payment')
    assert status['reason'] == 'account_status_unavailable'
    assert action['reason'] == 'action_unavailable'
    assert '实时' in status['answer'] and '自行办理' in action['answer']


def test_overnight_followup_uses_same_session_and_can_be_recalled(service):
    sid = service.create(ACTOR, {})['session_id']
    service.model.complete.side_effect = [
        plan('knowledge', flow_id='invoice'),
        plan('knowledge', 'followup', question='提前开票可以多次申请吗？', retry_query='在线开票流程'),
        plan('history'),
    ]
    service.model.answer.side_effect = [
        {'answerable': True, 'answer': '最高2万元。', 'citation_ids': [], 'image_ids': []},
        {'answerable': True, 'answer': '仅可预开一次。', 'citation_ids': [], 'image_ids': []},
        {'answerable': True, 'answer': '您问了提前开票和申请次数。', 'citation_ids': [], 'image_ids': []},
    ]
    chat(service, sid, '在线开票流程是什么？', 'invoice-question')
    with service.db:
        service.db.execute('UPDATE messages SET created=created-86400 WHERE session=?', (sid,))
        service.db.execute('UPDATE sessions SET updated=updated-86400 WHERE id=?', (sid,))
    answer = chat(service, sid, '那这个额度可以多次申请吗？', 'overnight-followup')
    assert '一次' in answer['answer']
    assert '开票' in answer['retrieval']['query']
    assert service.model.answer.call_args.args[1] == []
    assert service.model.answer.call_args.args[3]['_resolved_question'] == '提前开票可以多次申请吗？'
    recent = json.loads(service.model.complete.call_args_list[1].args[0][-1]['content'])['recent_messages']
    assert [item['role'] for item in recent] == ['user', 'assistant']
    recalled = chat(service, sid, '我刚才问了什么？', 'history-recall')
    assert recalled['reason'] == 'history'
    assert any(item['content'] == '最高2万元。' for item in service.model.answer.call_args.args[1])
    assert len(service.history(ACTOR, sid)['items']) == 6


def test_lookup_reads_leaf_turns_beyond_window_but_obeys_visibility_and_owner(service):
    sid = service.create(ACTOR, {})['session_id']
    other = {'tenant_id': 'tenant', 'sub': 'bob'}
    other_sid = service.create(other, {})['session_id']
    service.config.context_rounds = 2
    now = time.time()
    with service.db:
        turns = [(sid, 'window-old', 'cURL 调用示例', now-86400),
                 (sid, 'window-expired', '查找用不到的过期 cURL', now-8*86400),
                 (other_sid, 'window-bob', 'cURL 私有测试', now-86400)]
        turns += [(sid, f'window-recent-{index}', f'新问题 {index}', now-index) for index in range(5, 0, -1)]
        for session, request, content, created in turns:
            for role, text in [('user', content), ('assistant', '回复 '+content)]:
                service.db.execute('INSERT INTO messages(id,session,request_id,role,content,payload,created) VALUES(?,?,?,?,?,?,?)',
                                   (request+role, session, request, role, text, '{}', created))
    recent = service.context_history(ACTOR, sid)
    assert len(recent) == 4 and all('cURL' not in item['content'] for item in recent)
    service.model.complete.side_effect = [plan('history', 'lookup', history_query='cURL'), plan('history')]
    service.model.answer.return_value = {'answerable': True, 'answer': '此前聊过 cURL 调用示例。',
                                         'citation_ids': [], 'image_ids': []}
    answer = chat(service, sid, '昨天那个 cURL 示例是什么？', 'lookup-older-curl')
    assert answer['reason'] == 'history'
    older = json.loads(service.model.complete.call_args.args[0][-1]['content'])['older_messages']
    assert [item['content'] for item in older] == ['cURL 调用示例', '回复 cURL 调用示例']
    assert service.model.answer.call_args.args[1][0]['content'] == 'cURL 调用示例'
    with pytest.raises(APIError):
        service.lookup_context_history(other, sid, 'cURL')
    new_session = service.create(ACTOR, {})['session_id']
    assert service.lookup_context_history(ACTOR, new_session, 'cURL') == []


def test_ambiguous_payment_has_real_options_and_selection_is_independent(service):
    sid = service.create(ACTOR, {})['session_id']
    service.model.complete.side_effect = [
        plan('knowledge', 'clarify', clarification='请问是账单支付还是充值支付？',
             choices=['payment','recharge','invalid']),
        AssertionError('an explicit flow must not be classified again'),
    ]
    service.model.answer.side_effect = evidence_answer
    response = chat(service, sid, '支付不了', 'ambiguous-payment')
    assert response['reason'] == 'clarification'
    assert response['suggestions'] == []
    assert [action['message'] for action in response['actions']] == ['账单支付流程', '客户充值流程']
    result = chat(service, sid, '账单支付流程', 'chosen-payment')
    assert any('账单支付流程' in item['title'] for item in result['citations'])
    assert result['retrieval']['method']=='registered_flow'
    service.model.complete.assert_called_once()


def test_payment_failure_after_recharge_uses_recharge_context(service):
    sid = service.create(ACTOR, {})['session_id']
    service.model.complete.return_value = plan(
        'knowledge', 'followup', question='客户充值时支付失败怎么办？', flow_id='recharge')
    service.model.answer.side_effect = evidence_answer
    chat(service, sid, '客户充值流程', 'recharge-before-failure')
    with patch('app.chains.retrieve', return_value={'evidence': [], 'retrieval': {'matched': False, 'hits': []}}):
        result = chat(service, sid, '支付不了', 'recharge-payment-failure')
    assert result['reason'] == 'knowledge'
    assert result['citations'][0]['section_title'] == '客户充值流程'
    assert service.model.answer.call_args.args[3]['_resolved_question'] == '客户充值时支付失败怎么办？'
    assert result['suggestions'] == []


@pytest.mark.parametrize('flow_id', tuple(GUIDED_FLOWS))
def test_every_registered_choice_skips_reclassification(service, flow_id):
    title = GUIDED_FLOWS[flow_id]['title']
    sid = service.create(ACTOR, {})['session_id']
    service.model.complete.side_effect = [
        plan('knowledge', 'clarify', clarification='您想了解哪项办理流程？', choices=[flow_id]),
        AssertionError('The selected flow was sent to the classifier again'),
    ]
    service.model.answer.side_effect = evidence_answer

    clarification = chat(service, sid, '接下来要怎么办理？', 'registered-flow-clarify')
    assert clarification['actions'] == [{'type': 'clarify', 'label': title, 'message': title}]

    with patch('app.chains.retrieve', side_effect=AssertionError('The selected flow was searched again')):
        result = chat(service, sid, clarification['actions'][0]['message'], 'registered-flow-choice')

    assert result['status'] == 'answered'
    assert result['retrieval']['method'] == 'registered_flow'
    assert [citation['section_title'] for citation in result['citations']] == [title]
    service.model.complete.assert_called_once()


@pytest.mark.parametrize('flow_id', tuple(GUIDED_FLOWS))
def test_every_guided_flow_stays_on_its_own_steps(service, flow_id):
    flow = GUIDED_FLOWS[flow_id]
    sid = service.create(ACTOR, {})['session_id']
    service.model.complete.return_value = plan('guide')
    service.model.answer.side_effect = evidence_answer
    result = chat(service, sid, '分步指导：' + flow['title'], 'start-guided-flow')
    assert result['guidance']['flow_id'] == flow_id and result['guidance']['step'] == 0
    service.model.complete.side_effect = AssertionError('guide control reclassified')
    service.model.answer.side_effect = AssertionError('guide control regenerated from history')
    with patch('app.chains.retrieve', side_effect=AssertionError('guide control used general search')):
        for step, (stage, _) in enumerate(flow['stages']):
            if step:
                result = chat(service, sid, '这一步已完成', f'guide-advance-{step}')
                assert result['guidance']['flow_id'] == flow_id and result['guidance']['step'] == step
                assert result['answer'].startswith(f'第 {step + 1} 步 · {stage}')
            current = chat(service, sid, '这一步怎么做', f'guide-read-{step}')
            assert current['guidance']['step'] == step
            assert current['answer'].startswith(f'第 {step + 1} 步 · {stage}')
            assert [item['section_title'] for item in current['citations']] == [flow['title']]
        backed = chat(service, sid, '返回上一步', 'guide-step-back')
        assert backed['guidance']['flow_id'] == flow_id
        assert backed['guidance']['step'] == len(flow['stages']) - 2
        ended = chat(service, sid, '结束指导', 'guide-step-end')
        assert ended['guidance']['status'] == 'ended'
    service.model.complete.assert_called_once()


def test_new_conditions_take_precedence_and_numeric_guard_is_enforced():
    model = Mock()
    model.complete.return_value = plan('knowledge', 'followup', question='28号调整星级的已订购服务何时生效')
    history = [{'role': 'user', 'content': '15号提交星级权益调整，已订购服务什么时候生效？'}]
    result = interpret(model, '我是28号提交的', history)
    assert '28号' in result['question'] and '15号' not in result['question']
    model.complete.return_value = plan('knowledge', 'followup', question='15号调整星级的已订购服务何时生效')
    with pytest.raises(ValueError, match='lost current numeric condition'):
        interpret(model, '我是28号提交的', history)


def test_retrieval_retries_once_and_uses_the_qualified_evidence(service):
    sid = service.create(ACTOR, {})['session_id']
    service.model.complete.return_value = plan('knowledge', retry_query='客户充值流程')
    service.model.answer.side_effect = evidence_answer
    entry = next(row for row in service.knowledge.rows.values() if '客户充值流程' in row['title'])
    with patch('app.chains.retrieve', side_effect=[
        {'evidence': [], 'retrieval': {'matched': False, 'hits': []}},
        {'evidence': [entry], 'retrieval': {'matched': True, 'hits': [(1, entry, 1)]}},
    ]) as retrieve:
        result = chat(service, sid, '钱不够了，余额怎么充进去？', 'recharge-bounded-retry')
    assert [args.args[1] for args in retrieve.call_args_list] == ['钱不够了，余额怎么充进去？', '客户充值流程']
    assert result['citations'][0]['id'] == entry['id']

@pytest.mark.parametrize(('question','flow_id','title'), [
    ('钱不够了，余额怎么充进去？','recharge','客户充值流程'),
    ('我已经注册好了，下一步该点哪里？','register','注册流程'),
    ('我没有钱了','recharge','客户充值流程'),
])
def test_recover_model_output_then_ground_general_flow_if_search_misses(service, question, flow_id, title):
    sid=service.create(ACTOR,{})['session_id']
    service.model.complete.side_effect=['invalid JSON',plan('knowledge',flow_id=flow_id)]
    service.model.answer.side_effect=evidence_answer
    with patch('app.chains.retrieve',return_value={'evidence':[],'retrieval':{'matched':False,'hits':[]}}):
        result=chat(service,sid,question,'recover-general-flow')
    assert result['retrieval']['method']=='registered_flow'
    assert any(title in row['title'] for row in result['citations'])
    assert service.model.answer.call_args.args[0]==question
    assert service.model.complete.call_count==2


@pytest.mark.parametrize('question, heading', [
    ('Token是什么', 'Token(词元)'),
    ('Token是什么？', 'Token(词元)'),
    ('TOKEN 是什么意思？？', 'Token(词元)'),
    ('什么是 Token', 'Token(词元)'),
    ('词元是什么', 'Token(词元)'),
    ('RAG是什么', 'RAG(检索增强生成)'),
])
def test_definition_questions_use_the_glossary_for_multiple_terms(service, question, heading):
    sid = service.create(ACTOR, {})['session_id']
    service.model.complete.return_value = plan('knowledge')
    service.model.answer.side_effect = evidence_answer
    result = chat(service, sid, question, 'glossary-definition')
    assert result['status'] == 'answered'
    assert result['retrieval']['method'] == 'glossary_definition'
    assert '名词解释' in result['citations'][0]['title']
    assert result['answer'].startswith(heading)
    assert result['suggestions'] == []


def test_unanswered_product_question_offers_suggestions_and_human_support(service):
    sid = service.create(ACTOR, {})['session_id']
    service.model.complete.return_value = plan('knowledge')
    with patch('app.chains.retrieve', return_value={
        'evidence': [], 'retrieval': {'matched': False, 'hits': [], '_suggestion_titles': ['问题73 SmartTITU 名词解释']},
    }):
        result = chat(service, sid, '怎么配置模型的每日预算上限？', 'no-supported-answer')
    assert result['status'] == 'suggestions'
    assert 1 <= len(result['suggestions']) <= 6
    assert result['actions'][0]['type'] == 'handoff'
    service.model.answer.assert_not_called()

@pytest.mark.parametrize('value', ['，','?','！？','…','。  '])
def test_punctuation_asks_what_help_is_needed_without_inheriting_history(service,value):
    sid=service.create(ACTOR,{})['session_id']
    service.model.complete.side_effect=[plan('knowledge',flow_id='invoice'),plan('knowledge','lookup',history_query='开票')]
    service.model.answer.side_effect=evidence_answer
    chat(service,sid,'在线开票流程是什么？','prior-invoice')
    service.model.answer.reset_mock()
    with patch.object(service,'reserve_rag_quota',side_effect=AssertionError('unclear input must not retrieve')):
        response=chat(service,sid,value,'punctuation-only')
    assert response['reason']=='unclear_input'
    assert response['citations']==[] and response['suggestions']==[]
    assert '想了解' in response['answer']
    assert len(service.history(ACTOR,sid)['items'])==4
    payload=json.loads(service.model.complete.call_args.args[0][-1]['content'])
    assert payload['current_question']==value.strip() and payload['recent_messages']==[]
    service.model.answer.assert_not_called()


def test_typo_question_still_uses_model_and_does_not_mix_previous_topic(service):
    sid=service.create(ACTOR,{})['session_id']
    question='余额怎吗冲值？？'
    service.model.complete.side_effect=[
        plan('knowledge',flow_id='invoice'),plan('unclear_input'),plan('knowledge',flow_id='recharge'),
    ]
    service.model.answer.side_effect=evidence_answer
    chat(service,sid,'在线开票流程是什么？','prior-invoice')
    assert chat(service,sid,'asdf','unclear-typed')['reason']=='unclear_input'
    with patch('app.chains.retrieve',return_value={'evidence':[],'retrieval':{'matched':False,'hits':[]}}):
        response=chat(service,sid,question,'noisy-recharge')
    payload=json.loads(service.model.complete.call_args.args[0][-1]['content'])
    assert payload['current_question']==question
    assert len(payload['recent_messages'])==2 and '开票' in payload['recent_messages'][0]['content']
    assert service.model.answer.call_args.args[1]==[]
    assert any('客户充值流程' in item['title'] for item in response['citations'])


def test_incomplete_product_name_gets_a_focused_question_before_search(service):
    sid = service.create(ACTOR, {})['session_id']
    service.model.complete.return_value = plan(
        'knowledge', 'clarify', clarification='您可能想问 SmartTITU。您想了解产品功能，还是账号注册？')
    with patch.object(service, 'reserve_rag_quota', side_effect=AssertionError('ambiguous input must not retrieve')):
        result = chat(service, sid, 'samrtt', 'incomplete-product-name')
    assert result['reason'] == 'clarification'
    assert 'SmartTITU' in result['answer'] and result['suggestions'] == []
    service.model.answer.assert_not_called()


def test_clear_typo_is_corrected_before_search_and_original_remains_in_history(service):
    sid = service.create(ACTOR, {})['session_id']
    service.model.complete.return_value = plan('knowledge', normalized_query='Token 是什么？')
    service.model.answer.side_effect = evidence_answer
    with patch('app.chains.retrieve', wraps=retrieve) as search:
        result = chat(service, sid, 'toen是什么', 'corrected-term-question')
    assert search.call_args.args[1] == 'Token 是什么？' and search.call_count == 1
    assert result['retrieval']['method'] == 'glossary_definition'
    assert service.model.answer.call_args.args[0] == 'toen是什么'
    assert service.history(ACTOR, sid)['items'][0]['content'] == 'toen是什么'


def test_corrected_query_can_fall_back_to_original(service):
    sid = service.create(ACTOR, {})['session_id']
    service.model.complete.return_value = plan('knowledge', normalized_query='如何为账户余额充值？')
    service.model.answer.side_effect = evidence_answer
    row = next(row for row in service.knowledge.rows.values() if '客户充值流程' in row['title'])
    with patch('app.chains.retrieve', side_effect=[
        {'evidence': [], 'retrieval': {'matched': False, 'hits': []}},
        {'evidence': [row], 'retrieval': {'matched': True, 'hits': []}},
    ]) as search:
        result = chat(service, sid, '我的余额咋往里加', 'search-original-fallback')
    assert [call.args[1] for call in search.call_args_list] == ['如何为账户余额充值？', '我的余额咋往里加']
    assert result['status'] == 'answered'


def test_independent_rewrite_does_not_change_error_code():
    model = Mock()
    model.complete.return_value = plan('knowledge', normalized_query='API 调用报错 403 怎么办？')
    result = interpret(model, 'API报401咋办', [])
    assert result['question'] == 'API报401咋办'
    assert 'normalized_query' not in result


def test_guided_progress_uses_registered_stage_even_after_unrelated_history(service):
    sid=service.create(ACTOR,{})['session_id']
    service.model.complete.return_value=plan('guide')
    service.model.answer.side_effect=evidence_answer
    chat(service,sid,'分步指导：注册流程','begin-registration')
    service.model.complete.return_value=plan('unclear_input')
    assert chat(service,sid,'，','guide-mistyped')['reason']=='unclear_input'
    calls=service.model.complete.call_count
    service.model.complete.side_effect=AssertionError('guide action must skip intent')
    service.model.answer.side_effect=AssertionError('guide action uses current stage evidence')
    with patch('app.chains.retrieve', side_effect=AssertionError('guide action must keep original flow')):
        second=chat(service,sid,'这一步已完成','register-submit')
        assert second['guidance']['step']==1
        assert second['answer'].startswith('第 2 步 · 提交与校验')
        third=chat(service,sid,'这一步已完成','register-login')
        assert third['guidance']['step']==2
        assert third['answer'].startswith('第 3 步 · 登录与后续办理')
        assert '注册流程' in third['citations'][0]['title'] and '重置密码' not in third['answer']
        back=chat(service,sid,'返回上一步','register-back')
        assert back['guidance']['step']==1
        assert back['answer'].startswith('第 2 步 · 提交与校验')
        assert any(action['message']=='这一步怎么做' for action in back['actions'])
    assert service.model.complete.call_count==calls


def test_classification_outage_offers_payment_choices_from_active_documents(service):
    sid=service.create(ACTOR,{})['session_id']
    service.model.complete.side_effect=TimeoutError
    with patch.object(service,'reserve_rag_quota',side_effect=AssertionError('outage should not run RAG')):
        first=chat(service,sid,'支付不了','payment-during-outage')
    assert first['reason']=='clarification'
    assert {item['message'] for item in first['actions']}=={'账单支付流程','客户充值流程'}
    service.model.answer.side_effect=evidence_answer
    second=chat(service,sid,'账单支付流程','payment-outage-choice')
    assert second['citations'][0]['section_title']=='账单支付流程'


def test_recheck_does_not_turn_recharge_instructions_into_delegation(service):
    sid=service.create(ACTOR,{})['session_id']
    service.model.complete.side_effect=[
        plan('action',evidence='余额怎么充进去'),
        plan('knowledge',flow_id='recharge',retry_query='客户充值流程'),
    ]
    service.model.answer.side_effect=evidence_answer
    result=chat(service,sid,'钱不够了，余额怎么充进去？','confirm-not-delegation')
    assert result['reason']=='knowledge'
    assert result['citations'][0]['section_title']=='客户充值流程'
    assert service.model.complete.call_count==2
