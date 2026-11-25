"""Regression for the observed API Key timeout: keep strong upstream evidence."""
import json
from types import SimpleNamespace
from unittest.mock import Mock,patch
import pytest
from app.evidence_selection import EvidenceSelector, fallback_evidence, model_options, evidence_timeout
from app.rag import SemanticKnowledge


def candidates():
    rows=[
        ('api-management','问题42 API 密钥管理','路径：企业接入管理 → API Key管理。创建时填写名称，管理密钥并复制完整API Key。',.998736),
        ('api-create','问题353 企业服务门户-创建 API Key','进入API Key管理，点击创建，设置名称及白名单。',.995135),
        ('api-steps','问题81 获取 API Key-操作步骤','创建API Key后可在密钥列表复制。',.993473),
        ('delivery','问题10 客户交付流程','完成签约，创建和管理API Key，交付资料，接入使用。',.886567),
        ('subscription','问题8 服务订购流程','选择套餐，确认订购，按开通指引创建和管理API Key。',.659817),
    ]
    return [dict(row=dict(id=i,title=t,content=b,document_id='doc',revision='v1'),score=score,
                 dense=.74,lexical=1.,rrf=.1,strong_title=False,title_match=False,title_match_type='none',channels=['dense'])
            for i,t,b,score in rows]


@pytest.mark.parametrize('query',['如何创建和管理API KEY','如何创建和管理 API Key？','API密钥怎么创建和管理？'])
def test_timeout_does_not_promote_incidental_workflow_wording(query):
    selected,policy=fallback_evidence(query,candidates(),2)
    assert selected[0]['row']['id']=='api-management'
    assert not {'delivery','subscription'} & {x['row']['id'] for x in selected}
    assert policy=='ranked_query_support_fallback'


def test_no_lexical_support_returns_no_evidence():
    assert fallback_evidence('海底火山形成原因',candidates(),4)==([],'fallback_no_support')


def test_unrelated_high_score_does_not_prove_support():
    rows=[{**candidates()[0],'row':dict(id='bad',title='天气',content='晴天。'),'score':1.}]+candidates()
    assert fallback_evidence('如何创建和管理API KEY',rows,1)[0][0]['row']['id']=='api-management'


def test_two_explicit_topics_keep_complementary_evidence():
    rows=[dict(row=dict(id='curl',title='cURL调用示例',content='使用cURL调用接口的示例。'),score=.99),
          dict(row=dict(id='invoice',title='在线开票流程',content='在线开票，填写抬头并提交申请。'),score=.98)]
    assert {c['row']['id'] for c in fallback_evidence('给一个cURL调用示例；在线开票流程是什么',rows,2)[0]}=={'curl','invoice'}


@pytest.mark.parametrize('error',[TimeoutError(),ValueError('invalid evidence selection')])
def test_real_retrieval_fallback_keeps_api_source_and_thresholds(error):
    rows=candidates();kb=object.__new__(SemanticKnowledge)
    kb.config=SimpleNamespace(rerank_enabled=True,min_similarity=.6,rerank_min_score=0.,fingerprint='same',top_k=24,context_k=2)
    kb.store=Mock();kb.store.snapshot.return_value=({'generation':1,'fingerprint':'same'},[(c['row'],[1.,0.]) for c in rows])
    kb.vectors=None;kb.embedder=Mock();kb.embedder.embed.return_value=[[1.,0.]]
    kb.reranker=Mock();kb.reranker.rank.return_value=[(i,c['score']) for i,c in enumerate(rows)]
    kb.evidence_selector=Mock(side_effect=error)
    with patch('app.rag.fuse',return_value=rows):report=kb._assess('如何创建和管理API KEY')
    assert report['matched']
    assert report['hits'][0][1]['title']=='问题42 API 密钥管理'
    assert report['selection_policy']=='ranked_query_support_fallback'
    assert not {'问题10 客户交付流程','问题8 服务订购流程'} & {r['title'] for _,r,_ in report['hits']}
    # The same fallback must never rescue a record rejected by the rerank gate.
    kb.config.rerank_min_score=.999
    with patch('app.rag.fuse',return_value=rows):assert not kb._assess('如何创建和管理API KEY')['matched']


def test_empty_semantic_selection_is_not_replaced_by_fallback():
    model=Mock();model.complete.return_value='{"evidence":[]}'
    assert EvidenceSelector(model)('如何创建API Key',candidates(),2)==[]


def test_timeout_budget_config_and_restoration():
    observed=[]
    def complete(messages):
        observed.append(dict(model_options()))
        return '{"evidence":[]}'
    with patch.dict('os.environ',{'EVIDENCE_SELECTION_TIMEOUT_SECONDS':'12'}):
        assert EvidenceSelector(Mock(complete=complete))('如何创建API Key',candidates(),2)==[]
    assert observed[0]['timeout']==12
    assert model_options() is None
    for value in ('0','nan','inf','61','bad'):
        with patch.dict('os.environ',{'EVIDENCE_SELECTION_TIMEOUT_SECONDS':value}),pytest.raises(ValueError):evidence_timeout()

@pytest.mark.parametrize('raw',['','not JSON','{"evidence":[{"id":"invented"}]}'])
def test_invalid_model_output_uses_same_safe_fallback(raw):
    selector=EvidenceSelector(Mock(complete=Mock(return_value=raw)))
    with pytest.raises(ValueError):selector('如何创建和管理API KEY',candidates(),2)
    assert fallback_evidence('如何创建和管理API KEY',candidates(),2)[0][0]['row']['id']=='api-management'
