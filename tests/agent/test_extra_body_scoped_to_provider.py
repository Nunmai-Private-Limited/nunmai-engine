"""A session switched from a custom provider to a hosted one must not carry the custom provider's extra_body.

Seen 2026-09-23: meetings answer on a profile whose default is a local vLLM with
``extra_body: {chat_template_kwargs: {enable_thinking: false}}``; locking a turn to openai-codex kept that field
and ChatGPT rejected every turn with HTTP 400 "Unsupported parameter: chat_template_kwargs".
"""
from types import SimpleNamespace

from agent.chat_completion_helpers import _scope_extra_body_to_provider

NODE1 = {"name": "Nunmai Node 1", "provider_key": "node1", "base_url": "http://127.0.0.1:8000/v1", "extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}


def _agent(provider, base_url, model="gpt-6-luna"):
    return SimpleNamespace(provider=provider, model=model, base_url=base_url, _custom_providers=[NODE1])


def test_hosted_provider_drops_other_providers_extra_body():
    agent = _agent("openai-codex", "https://chatgpt.com/backend-api/codex")
    out = _scope_extra_body_to_provider(agent, {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}})
    assert "extra_body" not in out


def test_caller_value_and_other_keys_survive():
    agent = _agent("openai-codex", "https://chatgpt.com/backend-api/codex")
    overrides = {"service_tier": "priority",
                 "extra_body": {"chat_template_kwargs": {"enable_thinking": True}, "prompt_cache_key": "x"}}
    out = _scope_extra_body_to_provider(agent, overrides)
    assert out == overrides          # a different value was set on purpose; unrelated keys untouched


def test_own_custom_provider_keeps_its_extra_body():
    agent = _agent("custom", "http://127.0.0.1:8000/v1", model="nunmai-local")   # how node1 resolves at runtime
    overrides = {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}
    assert _scope_extra_body_to_provider(agent, overrides) == overrides


def test_no_custom_providers_is_a_no_op():
    agent = SimpleNamespace(provider="openai-codex", model="m", base_url="https://x", _custom_providers=[])
    overrides = {"extra_body": {"chat_template_kwargs": {}}}
    assert _scope_extra_body_to_provider(agent, overrides) is overrides
