"""Provider thinking options must use the selected wire format without changing old defaults."""
from contextlib import nullcontext
import sys
import pytest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock
from app.core import thinking_options,Model,Settings
from app.cost_metrics import purpose


def test_legacy_default(monkeypatch):
    monkeypatch.delenv('MODEL_THINKING_FORMAT',raising=False)
    monkeypatch.delenv('MODEL_DISABLE_THINKING',raising=False)
    assert thinking_options('Qwen/Qwen3-32B')=={'extra_body':{'chat_template_kwargs':{'enable_thinking':False}}}
    assert thinking_options('another-model')=={}


def test_siliconflow_top_level(monkeypatch):
    monkeypatch.setenv('MODEL_THINKING_FORMAT','enable_thinking')
    monkeypatch.setenv('MODEL_DISABLE_THINKING','true')
    assert thinking_options('Qwen/Qwen3-32B')=={'extra_body':{'enable_thinking':False}}


def test_disabled_or_unsupported_does_not_send_parameters(monkeypatch):
    for config in ({'MODEL_THINKING_FORMAT':'none','MODEL_DISABLE_THINKING':'true'},
                   {'MODEL_THINKING_FORMAT':'enable_thinking','MODEL_DISABLE_THINKING':'false'}):
        for key,value in config.items():monkeypatch.setenv(key,value)
        assert thinking_options('Qwen/Qwen3-32B')=={}


def test_invalid_format_fails_before_request(monkeypatch):
    monkeypatch.setenv('MODEL_THINKING_FORMAT','typo')
    with pytest.raises(ValueError):thinking_options('Qwen/Qwen3-32B')
    with pytest.raises(ValueError):Settings(secret='x'*40).validate()


def test_query_context_uses_a_separate_endpoint_and_model(monkeypatch):
    monkeypatch.setenv('MODEL_DISABLE_THINKING','true')
    monkeypatch.setenv('MODEL_THINKING_FORMAT','vllm')
    monkeypatch.setenv('QUERY_CONTEXT_MODEL_NAME','deepseek-ai/DeepSeek-V4.1-Flash')
    monkeypatch.setenv('QUERY_CONTEXT_BASE_URL','https://context.example/v1')
    monkeypatch.setenv('QUERY_CONTEXT_API_KEY','context-key')
    monkeypatch.setenv('QUERY_CONTEXT_THINKING_FORMAT','enable_thinking')
    provider=Mock()
    provider.return_value.invoke.return_value=SimpleNamespace(content='response')
    langchain=ModuleType('langchain')
    langchain.__path__=[]
    chat_models=ModuleType('langchain.chat_models')
    chat_models.init_chat_model=provider
    langsmith=ModuleType('langsmith')
    langsmith.tracing_context=lambda **kwargs: nullcontext()
    monkeypatch.setitem(sys.modules,'langchain',langchain)
    monkeypatch.setitem(sys.modules,'langchain.chat_models',chat_models)
    monkeypatch.setitem(sys.modules,'langsmith',langsmith)
    settings=Settings(secret='x'*40,mode='llm',model='Qwen/Qwen3-32B',
                      model_url='https://answer.example/v1',model_key='answer-key')
    settings.validate()
    model=Model(settings)
    messages=[{'role':'user','content':'如何创建 API 密钥？'}]
    with purpose('query_context'):
        assert model.complete(messages)=='response'
    assert model.complete(messages)=='response'
    context_call, answer_call=provider.call_args_list
    assert context_call.args==('deepseek-ai/DeepSeek-V4.1-Flash',)
    assert context_call.kwargs['base_url']=='https://context.example/v1'
    assert context_call.kwargs['api_key']=='context-key'
    assert context_call.kwargs['extra_body']=={'enable_thinking':False}
    assert answer_call.args==('Qwen/Qwen3-32B',)
    assert answer_call.kwargs['base_url']=='https://answer.example/v1'
    assert answer_call.kwargs['api_key']=='answer-key'
    assert answer_call.kwargs['extra_body']=={'chat_template_kwargs':{'enable_thinking':False}}


def test_context_endpoint_requires_its_own_key(monkeypatch):
    monkeypatch.setenv('QUERY_CONTEXT_BASE_URL','https://context.example/v1')
    monkeypatch.delenv('QUERY_CONTEXT_API_KEY',raising=False)
    with pytest.raises(ValueError,match='QUERY_CONTEXT_API_KEY'):
        Settings(secret='x'*40,model_key='answer-key').validate()


def test_explicit_context_thinking_format_overrides_answer_preference(monkeypatch):
    monkeypatch.setenv('MODEL_DISABLE_THINKING','false')
    assert thinking_options('deepseek-flash','deepseek')=={
        'extra_body':{'thinking':{'type':'disabled'}}}
    assert thinking_options('Qwen/Qwen3-32B')=={}
