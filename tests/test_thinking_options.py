"""Provider thinking options must use the selected wire format without changing old defaults."""
import pytest
from app.core import thinking_options,Settings


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
