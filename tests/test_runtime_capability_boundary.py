"""Tool documentation is evidence for tutorials, not evidence of connected tools."""
import types
from unittest.mock import patch

from app.evidence_selection import example_only_for_execution
from app.rag import SemanticKnowledge
from app.conversation import recommended_questions

EXAMPLE={'id':'sdk','title':'用户手册：Node.js SDK-Function Calling 示例',
         'content':'使用get_weather函数查询城市天气。工具定义：{"tools": [{"parameters": {"city": "城市"}}]}',
         'document_id':'doc','revision':'one','image_ids':[]}
BUSINESS={'id':'business','title':'服务订购流程','content':'完成企业认证后选择套餐并签约。',
          'document_id':'doc','revision':'one','image_ids':[]}


def assess(question,rows,strong=False,selector=None):
    knowledge=SemanticKnowledge.__new__(SemanticKnowledge)
    knowledge.config=types.SimpleNamespace(fingerprint='same',rerank_enabled=False,
        min_similarity=.6,top_k=12,context_k=3,rerank_min_score=0)
    knowledge.store=types.SimpleNamespace(snapshot=lambda **kw:({'fingerprint':'same','generation':1},[(row,[1.,0.]) for row in rows]))
    knowledge.embedder=types.SimpleNamespace(embed=lambda texts:[[1.,0.]])
    knowledge.vectors=None
    if selector:knowledge.evidence_selector=selector
    candidates=[{'row':row,'dense':1.,'lexical':1.,'rrf':1.,'title_match':strong,'strong_title':strong} for row in rows]
    with patch('app.rag.fuse',return_value=candidates):return knowledge._assess(question)


def test_example_cannot_establish_live_execution():
    for question in ('今天天气怎么样？','查一下北京天气','帮我执行这个工具','What is the weather today?'):
        assert example_only_for_execution(question,EXAMPLE),question


def test_sdk_explanations_remain_supported():
    for question in ('如何用Function Calling实现天气查询？','Node.js SDK示例怎么用',
                     '这个函数是什么意思？','如何使用工具查询天气？','How to implement a weather query?'):
        assert not example_only_for_execution(question,EXAMPLE),question


def test_ordinary_business_evidence_is_unchanged():
    for question in ('如何订购服务','怎么注册','默认几星','如何开票','查询天气'):
        assert not example_only_for_execution(question,BUSINESS)


def test_plain_api_parameter_examples_are_not_treated_as_tool_definitions():
    row={'title':'SDK请求示例','content':'参数说明：{"parameters": {"max_tokens": 2048}}'}
    assert not example_only_for_execution('最大输出是多少',row)


def test_single_example_and_title_shortcut_cannot_bypass_boundary():
    for strong in (False,True):
        result=assess('今天天气怎么样？',[EXAMPLE],strong=strong)
        assert not result['matched']
        assert result['hits']==[]
        assert result['_suggestion_titles']==[]
        assert result['_candidate_decisions'][0]['reason']=='example_not_runtime_capability'


def test_selector_timeout_cannot_restore_excluded_examples():
    rows=[EXAMPLE]+[{**BUSINESS,'id':'business'+str(i)} for i in range(4)]
    def unavailable(question,candidates,limit):
        assert 'sdk' not in [c['row']['id'] for c in candidates]
        raise TimeoutError()
    result=assess('查询天气',rows,selector=unavailable)
    assert 'sdk' not in [row['id'] for _,row,_ in result['hits']]


def test_tutorial_and_business_retrieval_still_match():
    assert assess('如何用Function Calling查询天气',[EXAMPLE],strong=True)['matched']
    assert assess('如何订购服务',[BUSINESS],strong=True)['matched']


def test_suggestions_do_not_recommend_unexecutable_example():
    knowledge=types.SimpleNamespace(rows={'sdk':EXAMPLE,'business':BUSINESS})
    result=recommended_questions(knowledge,'今天天气怎么样',related_titles=[EXAMPLE['title']])
    assert not any('Function Calling' in title for title in result),result
    assert EXAMPLE['title'] not in result
    assert '用户手册：Node.js SDK-Function Calling 示例' not in result
