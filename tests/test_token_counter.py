from types import SimpleNamespace

import pytest

from app.core.context_manager import TokenCounter


@pytest.mark.parametrize("error", [KeyError("unknown model"), OSError("cache unavailable")])
def test_model_encoder_failure_uses_cached_fallback(monkeypatch, error):
    def unavailable(_model):
        raise error

    monkeypatch.setattr("app.core.context_manager.tiktoken.encoding_for_model", unavailable)
    monkeypatch.setattr(
        "app.core.context_manager.tiktoken.get_encoding",
        lambda _name: SimpleNamespace(encode=lambda _text: [1, 2, 3]),
    )

    assert TokenCounter().count("hello") == 3


def test_uncached_encoders_use_estimate_offline(monkeypatch):
    def unavailable(_name):
        raise ConnectionError("offline")

    monkeypatch.setattr("app.core.context_manager.tiktoken.encoding_for_model", unavailable)
    monkeypatch.setattr("app.core.context_manager.tiktoken.get_encoding", unavailable)

    counter = TokenCounter()
    assert counter.count("") == 0
    assert counter.count("hello world") == 6
    assert counter.count_messages([{"role": "user", "content": "hello world"}]) == 14


def test_available_model_encoder_keeps_exact_count(monkeypatch):
    monkeypatch.setattr(
        "app.core.context_manager.tiktoken.encoding_for_model",
        lambda _model: SimpleNamespace(encode=lambda _text: [1, 2]),
    )
    assert TokenCounter().count("hello") == 2
