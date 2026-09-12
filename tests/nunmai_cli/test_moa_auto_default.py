"""The shipped ``default`` MoA preset is credential-aware (``auto: true``).

It must resolve to aggregator = the user's main model and references = main
model + up to AUTO_DEFAULT_EXTRA_REFERENCES other authenticated providers,
fall back to the static defaults when no main model is configured, and never
override explicit slots.
"""
import pytest

from nunmai_cli import moa_config
from nunmai_cli.moa_config import (
    AUTO_DEFAULT_EXTRA_REFERENCES,
    DEFAULT_MOA_AGGREGATOR,
    DEFAULT_MOA_REFERENCE_MODELS,
    build_auto_default_slots,
    normalize_moa_config,
    reset_auto_default_cache,
    validate_moa_payload,
)


@pytest.fixture(autouse=True)
def _fresh_cache():
    reset_auto_default_cache()
    yield
    reset_auto_default_cache()


def _wire(monkeypatch, *, provider="openai-codex", model="gpt-5.6-sol", rows=None):
    import nunmai_cli.config as config_mod
    import nunmai_cli.model_switch as switch_mod

    monkeypatch.setattr(config_mod, "load_config", lambda: {"model": {"provider": provider, "default": model}})
    monkeypatch.setattr(switch_mod, "list_authenticated_providers", lambda **kw: list(rows or []))


def test_auto_default_uses_main_model_and_other_authenticated_providers(monkeypatch):
    _wire(monkeypatch, rows=[
        {"slug": "openai-codex", "models": ["gpt-5.6-sol"]},   # main → skipped (already first)
        {"slug": "moa", "models": ["default"]},                 # virtual → skipped
        {"slug": "opencode-free", "models": ["x-preview"]},     # free tier → skipped
        {"slug": "anthropic", "models": ["claude-fable-5", "claude-sonnet-5"]},
        {"slug": "gemini", "models": ["gemini-3.1-pro-preview"]},
        {"slug": "kimi-coding", "models": ["kimi-k3"]},         # beyond the cap
    ])
    slots = build_auto_default_slots(use_cache=False)
    assert slots["aggregator"] == {"provider": "openai-codex", "model": "gpt-5.6-sol"}
    assert slots["reference_models"] == [
        {"provider": "openai-codex", "model": "gpt-5.6-sol", "enabled": True},
        {"provider": "anthropic", "model": "claude-fable-5", "enabled": True},
        {"provider": "gemini", "model": "gemini-3.1-pro-preview", "enabled": True},
    ]
    assert len(slots["reference_models"]) == 1 + AUTO_DEFAULT_EXTRA_REFERENCES


def test_auto_default_with_only_main_provider_still_works(monkeypatch):
    _wire(monkeypatch, rows=[{"slug": "openai-codex", "models": ["gpt-5.6-sol"]}])
    slots = build_auto_default_slots(use_cache=False)
    assert slots["reference_models"] == [{"provider": "openai-codex", "model": "gpt-5.6-sol", "enabled": True}]


def test_auto_default_falls_back_to_static_when_no_main_model(monkeypatch):
    _wire(monkeypatch, provider="", model="", rows=[{"slug": "anthropic", "models": ["claude-fable-5"]}])
    assert build_auto_default_slots(use_cache=False) is None
    cfg = normalize_moa_config({"presets": {"default": {"auto": True}}})
    preset = cfg["presets"]["default"]
    assert preset["aggregator"] == DEFAULT_MOA_AGGREGATOR
    assert [{k: v for k, v in r.items() if k != "enabled"} for r in preset["reference_models"]] == DEFAULT_MOA_REFERENCE_MODELS


def test_normalize_resolves_auto_preset(monkeypatch):
    _wire(monkeypatch, rows=[{"slug": "anthropic", "models": ["claude-fable-5"]}])
    cfg = normalize_moa_config({"presets": {"default": {"auto": True, "max_tokens": 4096, "enabled": True}}})
    preset = cfg["presets"]["default"]
    assert preset["auto"] is True
    assert preset["aggregator"] == {"provider": "openai-codex", "model": "gpt-5.6-sol"}
    assert [r["provider"] for r in preset["reference_models"]] == ["openai-codex", "anthropic"]


def test_explicit_slots_win_over_auto(monkeypatch):
    _wire(monkeypatch, rows=[{"slug": "anthropic", "models": ["claude-fable-5"]}])
    cfg = normalize_moa_config({"presets": {"default": {
        "auto": True,
        "reference_models": [{"provider": "gemini", "model": "gemini-3.1-pro-preview"}],
        "aggregator": {"provider": "kimi-coding", "model": "kimi-k3"},
    }}})
    preset = cfg["presets"]["default"]
    assert preset["aggregator"] == {"provider": "kimi-coding", "model": "kimi-k3"}
    assert [r["provider"] for r in preset["reference_models"]] == ["gemini"]


def test_empty_config_stays_static(monkeypatch):
    _wire(monkeypatch, rows=[{"slug": "anthropic", "models": ["claude-fable-5"]}])
    cfg = normalize_moa_config({})
    assert cfg["aggregator"] == DEFAULT_MOA_AGGREGATOR


def test_validate_accepts_slotless_auto_preset_and_rejects_slotless_manual():
    assert validate_moa_payload({"presets": {"default": {"auto": True, "enabled": True}}}) == []
    assert validate_moa_payload({"presets": {"default": {"enabled": True}}})


def test_auto_default_cache_is_used_until_reset(monkeypatch):
    calls = []
    import nunmai_cli.model_switch as switch_mod
    _wire(monkeypatch, rows=[{"slug": "anthropic", "models": ["claude-fable-5"]}])
    real = switch_mod.list_authenticated_providers
    monkeypatch.setattr(switch_mod, "list_authenticated_providers", lambda **kw: calls.append(1) or real(**kw))
    build_auto_default_slots(); build_auto_default_slots()
    assert len(calls) == 1
    reset_auto_default_cache(); build_auto_default_slots()
    assert len(calls) == 2
