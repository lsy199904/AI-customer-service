"""Exercise the session and RAG workflow with controlled model responses."""
import json
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from app.business_flows import GUIDED_FLOWS
from app.chains import retrieve
from app.core import APIError, Model, Service, Settings
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


@pytest.mark.parametrize('has_curl', [True, False])
def test_combined_invoice_and_curl_search_independently_and_keep_per_part_evidence(service, has_curl):
    sid = service.create(ACTOR, {})['session_id']
    questions = ['在线开票流程是什么？', 'SmartTITU API 怎么用 cURL 调用？']
    invoice = next(row for row in service.knowledge.rows.values() if row['title'].endswith('在线开票流程'))
    curl = next(row for row in service.knowledge.rows.values() if 'curl' in row['title'].lower())
    model = Model(service.config)
    reply = f"1. {invoice['content'][:180]}\n2. " + (curl['content'][:220] if has_curl else '未找到 cURL 示例。')
    model.complete = Mock(side_effect=[plan('knowledge', subqueries=questions), reply])
    service.model = model
    with patch('app.chains.retrieve', side_effect=[
        {'evidence': [invoice]}, {'evidence': [curl] if has_curl else []},
    ]) as search:
        result = chat(service, sid, '怎么开票？再给一个 API 调用的 cURL 示例。', 'invoice-and-curl')
    assert [call.args[1] for call in search.call_args_list] == questions
    payload = json.loads(model.complete.call_args.args[0][-1]['content'])
    assert [part['matched'] for part in payload['question_parts']] == [True, has_curl]
    assert [item['parts'] for item in payload['evidence']] == ([[1], [2]] if has_curl else [[1]])
    assert result['status'] == 'answered' and result['retrieval']['method'] == 'decomposed'
    assert len(result['citations']) == (2 if has_curl else 1)
    assert ('未找到 cURL 示例' in result['answer']) is not has_curl


def test_a_split_that_drops_the_new_amount_falls_back_to_the_unsplit_question():
    model = Mock()
    model.complete.return_value = plan('knowledge', subqueries=['怎么提前开票？', '怎么创建 API 密钥？'])
    question = '如何提前开票2万元，还要去哪创建 API 密钥？'
    result = interpret(model, question, [])
    assert result['question'] == question
    assert 'subqueries' not in result


def test_two_excerpts_from_the_same_source_keep_their_own_parts(service):
    sid = service.create(ACTOR, {})['session_id']
    model = Model(service.config)
    model.complete = Mock(side_effect=[
        plan('knowledge', subqueries=['Token是什么？', 'RPM是什么？']),
        'Token 是词元。RPM 是每分钟请求数。',
    ])
    service.model = model
    result = chat(service, sid, 'Token是什么？RPM是什么？', 'same-source-separate-parts')
    payload = json.loads(model.complete.call_args.args[0][-1]['content'])
    assert [item['parts'] for item in payload['evidence']] == [[1], [2]]
    assert 'Token(词元)' in payload['evidence'][0]['content']
    assert 'RPM(每分钟请求数)' in payload['evidence'][1]['content']
    assert len(result['citations']) == 1


def test_weather_payment_and_followup_after_split_use_each_new_turn(service):
    sid = service.create(ACTOR, {})['session_id']
    service.model.complete.side_effect = [
        plan('knowledge', subqueries=['Token是什么？', 'RPM是什么？']),
        plan('out_of_scope'),
        plan('knowledge', flow_id='recharge'),
        plan('knowledge', 'followup', question='充值时支付失败怎么办？', flow_id='recharge'),
    ]
    def answer(question, history, evidence, context):
        if context['_intent']=='out_of_scope':
            assert not context['_question_parts'] and not history and not evidence
            return {'answerable':True, 'answer':'天气查询超出 SmartTITU 客服服务范围。',
                    'citation_ids':[], 'image_ids':[]}
        return evidence_answer(question, history, evidence, context)

    service.model.answer.side_effect = answer
    first = chat(service, sid, 'Token是什么？RPM是什么？', 'split-before-other-turns')
    assert first['retrieval']['method']=='decomposed'
    with patch.object(service, 'reserve_rag_quota', side_effect=AssertionError('scope and clarification skip retrieval')):
        weather = chat(service, sid, '今天天气怎么样？', 'weather-after-split')
        payment = chat(service, sid, '支付不了', 'payment-after-weather')
    assert weather['reason']=='out_of_scope' and weather['citations']==[]
    assert [action['message'] for action in payment['actions']]==['账单支付流程', '客户充值流程']
    selected = chat(service, sid, '客户充值流程', 'choose-recharge-after-split')
    assert selected['retrieval']['method']=='registered_flow'
    with patch('app.chains.retrieve', return_value={'evidence':[], 'retrieval':{'matched':False,'hits':[]}}):
        followup = chat(service, sid, '还是支付不了怎么办？', 'recharge-followup-after-split')
    assert [item['section_title'] for item in followup['citations']]==['客户充值流程']
    context = service.model.answer.call_args.args[3]
    assert context['_resolved_question']=='充值时支付失败怎么办？' and not context['_question_parts']


def test_bare_english_fragment_cannot_restart_the_previous_certification_topic(service):
    sid = service.create(ACTOR, {})['session_id']
    service.model.answer.side_effect = evidence_answer
    chat(service, sid, '企业认证流程', 'certification-before-fragment')
    service.model.complete.return_value = plan(
        'knowledge', 'followup', question='企业认证流程是什么？', flow_id='verification')
    with patch.object(service, 'reserve_rag_quota', side_effect=AssertionError('fragment must not retrieve')):
        result = chat(service, sid, 'to', 'bare-english-fragment')
    assert result['reason']=='unclear_input' and not result['citations'] and not result['images']
    payload = json.loads(service.model.complete.call_args.args[0][-1]['content'])
    assert not payload['recent_messages'] and not payload['older_user_topics']


@pytest.mark.parametrize('wrong_plan', [
    plan('knowledge', 'followup', question='如何创建 API Key？'),
    plan('knowledge', normalized_query='如何创建 API Key？'),
])
def test_product_definition_cannot_be_rewritten_as_previous_api_key_task(service, wrong_plan):
    sid = service.create(ACTOR, {})['session_id']
    service.model.complete.side_effect = [plan('knowledge'), wrong_plan]
    service.model.answer.side_effect = evidence_answer
    api = next(row for row in service.knowledge.rows.values() if 'API 密钥管理' in row['title'])
    with patch('app.chains.retrieve', return_value={'evidence':[api], 'retrieval':{'matched':True,'hits':[]}}) as search:
        chat(service, sid, 'API 密钥在哪里创建？', 'api-before-product')
        search.return_value={'evidence':[], 'retrieval':{'matched':False,'hits':[]}}
        result = chat(service, sid, 'SmartTITU 是什么？', 'independent-product-definition')
    assert search.call_args.args[1]=='SmartTITU 是什么？'
    assert not result['citations'] and result['suggestions']
    service.model.answer.assert_called_once()


def test_new_api_how_to_does_not_reuse_previous_invoice_topic():
    model = Mock()
    model.complete.return_value = plan('knowledge', 'followup', question='提前开票怎么申请？',
                                      context_reference='提前开票流程')
    result = interpret(model, 'API 密钥在哪里创建？', [{'role':'user','content':'提前开票流程'}])
    assert result['kind']=='independent' and result['question']=='API 密钥在哪里创建？'


@pytest.mark.parametrize('question', ['提前开票最高多少？', '模型调用限额是多少？'])
def test_explicit_limit_question_ignores_stale_followup_plan(question):
    model = Mock()
    model.complete.return_value = plan(
        'knowledge', 'followup', question='如何提升充值上限？',
        context_reference='充值上限', retry_query='充值申请上限是多少？',
    )
    result = interpret(model, question, [{'role': 'user', 'content': '充值上限怎么查？'}])
    assert result['kind'] == 'independent'
    assert result['question'] == question
    assert not result['retry_query']


@pytest.mark.parametrize('topic,older', [('提前开票', '模型调用限额'), ('模型调用限额', '提前开票')])
def test_ambiguous_limit_followup_keeps_resolved_topic(topic, older):
    model = Mock()
    rewritten = f'{topic}可以多次申请吗？'
    model.complete.return_value = plan(
        'knowledge', 'followup', question=rewritten, context_reference=topic,
    )
    result = interpret(model, '那这个额度可以多次申请吗？', [
        {'role': 'user', 'content': f'{older}是多少？'},
        {'role': 'assistant', 'content': f'刚才讨论的是{older}。'},
        {'role': 'user', 'content': f'{topic}最高多少？'},
        {'role': 'assistant', 'content': f'这里说的是{topic}。'},
    ])
    assert result['kind'] == 'followup'
    assert result['question'] == rewritten


def test_business_fact_checks_accept_equivalent_amount_and_count_and_reject_extra_limit():
    from app.grounding import unsupported_business_facts
    evidence = [{'content':'最高20,000元，可申请1次。限流指标为每分钟请求数和每分钟 Token 数。'}]
    assert not unsupported_business_facts('最高2万元，可申请一次。限流指标为 RPM 和 TPM。', evidence)
    assert unsupported_business_facts('最高2万元，可申请2次，平台额外限制QPS。', evidence)==['QPS', '申请2次']


@pytest.mark.parametrize('valid_revision', [True, False])
def test_unsupported_payment_details_never_reach_stream_and_supported_steps_survive(service, valid_revision):
    sid = service.create(ACTOR, {})['session_id']
    service.model.complete.return_value = plan('knowledge')
    source = next(row for row in service.knowledge.rows.values() if row['title'].endswith('客户充值流程'))
    row = {**source, 'content':'进入费用中心，在充值页面选择在线充值或对公汇款。'}
    unverified = '在费用中心选择【中信银行】，要求最低充值 500 元。'
    corrected = '进入费用中心，在充值页面选择在线充值或对公汇款。资料没有明确银行或最低金额。'
    stream = []

    def answer(question, history, evidence, context):
        if context.get('_on_delta'):
            context['_on_delta'](unverified)
            text = unverified
        else:
            assert context['_grounding_feedback']==['中信银行', '500 元']
            text = corrected if valid_revision else unverified
        return {'answerable':True, 'answer':text, 'citation_ids':[row['id']], 'image_ids':[]}

    service.model.answer.side_effect = answer
    with patch('app.chains.retrieve', return_value={'evidence':[row], 'retrieval':{'matched':True,'hits':[]}}):
        result = service.chat(ACTOR, sid, {'message':'充值支持什么方式？','request_id':'guard-payment-details'}, observer=stream.append)
    assert not any('中信银行' in event.get('text','') for event in stream)
    if valid_revision:
        assert result['answer']==corrected and result['citations']
        assert any(event.get('text')==corrected for event in stream)
    else:
        assert result['reason']=='insufficient_evidence' and result['suggestions']


@pytest.mark.parametrize('question', ['今天天气怎么样？', '聊聊你喜欢的足球队',
                                     '推荐色情网站', '给我一个通用 Flask API 示例', '淘宝订单支付不了'])
def test_out_of_scope_skips_retrieval_and_offers_product_questions(service, question):
    service.model.complete.return_value = plan('out_of_scope')
    service.model.answer.return_value = {
        'answerable': True, 'answer': '这类请求超出客服服务范围。您可以咨询 SmartTITU 的产品使用或计费。',
        'citation_ids': [], 'image_ids': [],
    }
    sid = service.create(ACTOR, {})['session_id']
    with patch.object(service, 'reserve_rag_quota', side_effect=AssertionError('scope bypass')):
        answer = chat(service, sid, question, 'scope-request')
    assert answer['reason'] == 'out_of_scope'
    assert answer['citations'] == []
    assert '企业认证流程' in answer['suggestions']
    assert any(action['type'] == 'handoff' for action in answer['actions'])
    assert service.model.answer.call_args.args[:3] == (question, [], [])
    assert len(service.history(ACTOR, sid)['items']) == 2


@pytest.mark.parametrize('question', ['支付不了', '付款失败了', '我这边无法支付，怎么办？'])
def test_payment_failure_mislabeled_out_of_scope_still_offers_both_choices(service, question):
    sid = service.create(ACTOR, {})['session_id']
    service.model.complete.return_value = plan('out_of_scope')
    with patch.object(service, 'reserve_rag_quota', side_effect=AssertionError('clarify without retrieval')):
        result = chat(service, sid, question, 'payment-mislabeled-out-of-scope')
    assert result['reason']=='clarification' and result['intent']=='clarification'
    assert [item['message'] for item in result['actions']]==['账单支付流程', '客户充值流程']
    assert not result['suggestions'] and not result['handoff']
    service.model.answer.assert_not_called()


@pytest.mark.parametrize('question,topic', [('今天是多少号', '日期'), ('今天天气怎么样？', '天气')])
def test_question_misclassified_as_greeting_gets_a_topic_specific_scope_reply(service, question, topic):
    model = Model(service.config)
    model.complete = Mock(side_effect=[
        plan('greeting'), plan('out_of_scope'),
        json.dumps({'topic': f'{topic}查询',
                    'reply': '这项查询超出客服服务范围。您可以问我 SmartTITU 的产品使用或模型接入。'}, ensure_ascii=False),
    ])
    service.model = model
    sid = service.create(ACTOR, {})['session_id']
    with patch.object(service, 'reserve_rag_quota', side_effect=AssertionError('outside scope must not retrieve')):
        result = chat(service, sid, question, 'scope-instead-of-greeting')
    assert result['reason'] == 'out_of_scope' and result['answer'].startswith(topic)
    messages = model.complete.call_args.args[0]
    assert len(messages) == 2
    assert json.loads(messages[-1]['content']) == {'question': question}
    assert '先用简短、中性的类别名称' in messages[0]['content']


def test_scope_generation_failure_retains_safe_boundary(service):
    service.model.complete.return_value = plan('out_of_scope')
    service.model.answer.side_effect = TimeoutError
    sid = service.create(ACTOR, {})['session_id']
    result = chat(service, sid, '今天是多少号？', 'scope-model-timeout')
    assert result['reason'] == 'out_of_scope'
    assert '服务范围' in result['answer'] and result['suggestions']


@pytest.mark.parametrize('intent', ['complaint', 'handoff'])
def test_payment_report_after_out_of_scope_cannot_become_an_escalation(service, intent):
    service.model.complete.side_effect = [
        plan('out_of_scope'), plan(intent, evidence='支付不了'), plan(intent, evidence='支付不了'),
    ]
    service.model.answer.return_value = {
        'answerable': True, 'answer': '天气查询超出客服服务范围。您可以问我平台使用问题。',
        'citation_ids': [], 'image_ids': [],
    }
    sid = service.create(ACTOR, {})['session_id']
    with patch.object(service, 'reserve_rag_quota', side_effect=AssertionError('clarify before retrieval')):
        chat(service, sid, '今天天气怎么样', 'weather-before-payment')
        result = chat(service, sid, '支付不了', 'wrong-escalation')
    assert result['reason'] == 'clarification' and not result['handoff']
    assert [choice['message'] for choice in result['actions']] == ['账单支付流程', '客户充值流程']


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
    with patch.object(service, 'reserve_rag_quota', side_effect=AssertionError('complaint should not retrieve')):
        complaint = chat(service, sid, '我要投诉，客服一直没有解决我的问题。', 'current-complaint')
    assert complaint['handoff'] and complaint['reason'] == 'complaint_handoff'
    assert complaint['contact']['phone'] and complaint['contact']['email']
    assert '无法直接登记投诉' in complaint['answer']
    assert any(item['content'] == '我要投诉，客服一直没有解决我的问题。'
               for item in service.history(ACTOR, sid)['items'])
    response = chat(service, sid, 'API 密钥管理', 'subsequent-api-key')
    assert not response['handoff']
    assert any('API' in item['title'] and '密钥' in item['title'] for item in response['citations'])
    assert service.model.answer.call_args.args[1] == []


def test_realtime_status_and_operation_help_never_invoke_business_tools(service):
    sid = service.create(ACTOR, {})['session_id']
    service.model.complete.side_effect = [
        plan('account_status', evidence='还有多少余额'),
        plan('account_status', evidence='还有多少余额'),
        plan('action', evidence='替我付掉这笔账单'),
        plan('action', normalized_query='如何支付这笔账单？', flow_id='payment'),
    ]
    service.model.answer.side_effect = evidence_answer
    with patch.object(service.tools, 'invoke', side_effect=AssertionError('business tool called')):
        with patch.object(service, 'reserve_rag_quota', side_effect=AssertionError('retrieval called')):
            status = chat(service, sid, '帮我查一下本企业现在还有多少余额。', 'actual-balance')
        action = chat(service, sid, '替我付掉这笔账单', 'delegate-payment')
    assert status['reason'] == 'account_status_unavailable'
    assert '实时' in status['answer']
    assert action['reason'] == 'knowledge'
    assert action['citations'][0]['section_title'] == '账单支付流程'


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


@pytest.mark.parametrize('earlier_topic', [None, '在线开票流程'])
@pytest.mark.parametrize('question', ['支付不了', '付款失败了'])
def test_payment_guess_without_user_context_still_offers_both_buttons(service, earlier_topic, question):
    sid = service.create(ACTOR, {})['session_id']
    service.model.answer.side_effect = evidence_answer
    if earlier_topic:
        chat(service, sid, earlier_topic, 'unrelated-earlier-topic')
    service.model.complete.return_value = plan('knowledge', flow_id='recharge', normalized_query='充值支付失败怎么办？')
    with patch.object(service, 'reserve_rag_quota', side_effect=AssertionError('clarify before retrieval')):
        result = chat(service, sid, question, 'ambiguous-with-model-guess')
    assert result['reason'] == 'clarification'
    assert [action['message'] for action in result['actions']] == ['账单支付流程', '客户充值流程']
    assert result['citations'] == []
    selected = chat(service, sid, '账单支付流程', 'resolve-ambiguous-payment')
    assert selected['citations'][0]['section_title'] == '账单支付流程'
    service.model.complete.assert_called_once()


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


@pytest.mark.parametrize('selection', ['api的token', 'api key里的token'])
def test_token_clarification_can_be_resolved_by_a_short_reply(service, selection):
    sid = service.create(ACTOR, {})['session_id']
    clarification = '您是指 API Key 中的 token，还是模型用量中的 Token（词元）？'
    repeated = plan('knowledge', 'clarify', clarification=clarification)
    service.model.complete.side_effect = [
        repeated, repeated, plan('knowledge', 'followup', question='SmartTITU API Key 鉴权凭证是什么？',
                                 retry_query='API 密钥管理'),
    ]
    service.model.answer.side_effect = evidence_answer
    first = chat(service, sid, 'tokn', 'token-first-clarification')
    assert first['reason']=='clarification'
    row = next(row for row in service.knowledge.rows.values() if 'API 密钥管理' in row['title'])
    with patch('app.chains.retrieve', return_value={'evidence':[row], 'retrieval':{'matched':True,'hits':[]}}) as search:
        result = chat(service, sid, selection, 'token-selection')
    assert result['reason']=='knowledge'
    assert 'API 密钥管理' in result['citations'][0]['title']
    assert search.call_args.args[1]=='SmartTITU API Key 鉴权凭证是什么？'
    review = json.loads(service.model.complete.call_args.args[0][-1]['content'])
    assert review['pending_clarification']==clarification and 'routing_feedback' in review


def test_repeated_clarification_uses_new_user_terms_for_search(service):
    sid = service.create(ACTOR, {})['session_id']
    repeated = plan('knowledge', 'clarify', clarification='您指注册还是企业认证？')
    service.model.complete.return_value = repeated
    assert chat(service, sid, '接下来怎么弄', 'general-clarification')['reason']=='clarification'
    with patch.object(service, 'reserve_rag_quota', side_effect=AssertionError('uncertain reply must not search')):
        assert chat(service, sid, '不知道', 'still-uncertain')['reason']=='clarification'
    empty = {'evidence':[], 'retrieval':{'matched':False,'hits':[]}}
    with patch('app.chains.retrieve', return_value=empty) as search:
        result = chat(service, sid, '企业实名认证', 'specific-topic')
    search.assert_called_once()
    assert search.call_args.args[1]=='企业实名认证'
    assert '您指注册还是企业认证' not in result['answer']


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
        plan('action',flow_id='recharge',normalized_query='如何为账户余额充值？'),
    ]
    service.model.answer.side_effect=evidence_answer
    result=chat(service,sid,'钱不够了，余额怎么充进去？','confirm-not-delegation')
    assert result['reason']=='knowledge'
    assert result['citations'][0]['section_title']=='客户充值流程'
    assert service.model.complete.call_count==2


def test_repeated_action_label_on_ambiguous_payment_offers_relevant_choices(service):
    sid = service.create(ACTOR, {})['session_id']
    service.model.complete.return_value = plan('action', evidence='支付不了')
    with patch('app.chains.retrieve', return_value={'evidence': [], 'retrieval': {'matched': False, 'hits': []}}):
        result = chat(service, sid, '支付不了', 'repeated-action-payment')
    assert result['intent'] == 'clarification'
    assert {item['message'] for item in result['actions']} == {'账单支付流程', '客户充值流程'}
    assert result['suggestions'] == []
