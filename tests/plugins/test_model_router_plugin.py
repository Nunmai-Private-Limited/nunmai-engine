"""Tests for the bundled ``model-router`` plugin and the ``resolve_turn_model`` hook.

Covers:

  * ``router.py`` heuristics — greetings/acks route ``simple``, code and
    engineering asks route ``complex``, the middle band defers to the
    classifier, slash commands and MoA markers are skipped.
  * Tier derivation — a MoA main model resolves to its aggregator for
    ``normal`` and the provider's fast sibling for ``simple``; user tiers win.
  * ``Router.route`` — respects ``/model`` session overrides, no-ops when the
    target equals the current brain, fails open when the classifier breaks.
  * Gateway seam — ``GatewayRunner._resolve_turn_agent_config`` applies the
    hook's override to the turn route and cache signature.
  * CLI seam — ``NunmaiCLI._apply_resolve_turn_model_hook`` stages a one-turn
    restore exactly like ``/model --once``.
  * Bundled-plugin discovery via ``PluginManager``.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path, monkeypatch):
    nunmai_home = tmp_path / ".nunmai"
    nunmai_home.mkdir()
    monkeypatch.setenv("NUNMAI_HOME", str(nunmai_home))
    yield nunmai_home


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_router():
    path = _repo_root() / "plugins" / "model-router" / "router.py"
    spec = importlib.util.spec_from_file_location("model_router_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses resolve annotations via sys.modules
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Heuristics + classifier
# ---------------------------------------------------------------------------

class TestClassify:
    @pytest.mark.parametrize("text", ["hi", "Hello!", "thanks", "ok", "yes", "good morning", "who are you?", "done"])
    def test_simple_heuristics(self, text):
        r = _load_router()
        d = r.classify_heuristic(text)
        assert d is not None and d.tier == "simple"

    @pytest.mark.parametrize(
        "text",
        [
            "```python\nprint(1)\n```",
            "deploy the ESAL app to the staging server and verify the health endpoint",
            "please investigate the root cause of the failing CI pipeline on main",
            "l1\nl2\nl3\nl4\nl5\nl6\nl7",
            "x" * 900,
        ],
    )
    def test_complex_heuristics(self, text):
        r = _load_router()
        d = r.classify_heuristic(text)
        assert d is not None and d.tier == "complex"

    def test_middle_band_defers(self):
        r = _load_router()
        assert r.classify_heuristic("What is the capital of Saudi Arabia?") is None

    def test_short_question_not_forced_simple(self):
        r = _load_router()
        # 3 words but a question mark → let the classifier decide
        assert r.classify_heuristic("why deployment failed?") is None

    def test_classifier_used_for_middle_band(self):
        r = _load_router()
        seen = []

        def fake_llm(snippet):
            seen.append(snippet)
            return "COMPLEX"

        d = r.classify("What is the capital of Saudi Arabia?", mode="auto", llm=fake_llm)
        assert d.tier == "complex" and d.via == "classifier" and seen

    def test_classifier_error_falls_back_to_normal(self):
        r = _load_router()

        def boom(_):
            raise RuntimeError("no model")

        d = r.classify("Summarize our meeting notes", mode="auto", llm=boom)
        assert d.tier == "normal" and d.via == "fallback"

    def test_heuristic_mode_never_calls_llm(self):
        r = _load_router()
        d = r.classify("Summarize our meeting notes", mode="heuristic", llm=lambda _: "SIMPLE")
        assert d.tier == "normal" and d.via == "fallback"

    @pytest.mark.parametrize("raw,expected", [("simple", "simple"), (" Normal.", "normal"), ("Tier: COMPLEX", "complex"), ("??", None), (None, None)])
    def test_parse_tier(self, raw, expected):
        r = _load_router()
        assert r.parse_tier(raw) == expected

    def test_skips(self):
        r = _load_router()
        assert r.should_skip("/model foo") == "slash-command"
        assert r.should_skip("   ") == "empty"
        assert r.should_skip(None) == "non-text"
        assert r.should_skip(r._MOA_MARKER_PREFIX + "\nhello") == "moa-marker"
        assert r.should_skip("hello") is None


# ---------------------------------------------------------------------------
# Tier resolution
# ---------------------------------------------------------------------------

_MOA_CFG = {
    "model": {"provider": "moa", "default": "default"},
    "moa": {
        "default_preset": "default",
        "presets": {
            "default": {
                "reference_models": [{"provider": "openai-codex", "model": "gpt-5.6-sol"}],
                "aggregator": {"provider": "anthropic", "model": "claude-fable-5"},
                "enabled": True,
            }
        },
    },
}


class TestTiers:
    def test_defaults_from_moa_main(self):
        r = _load_router()
        tiers = r.default_tiers(_MOA_CFG)
        assert tiers["normal"] == {"provider": "anthropic", "model": "claude-fable-5"}
        assert tiers["simple"] == {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"}
        assert tiers["complex"] == {"provider": "moa", "model": "default"}

    def test_defaults_from_single_main(self):
        r = _load_router()
        tiers = r.default_tiers({"model": {"provider": "openai-codex", "default": "gpt-5.6-sol"}})
        assert tiers["normal"] == {"provider": "openai-codex", "model": "gpt-5.6-sol"}
        assert tiers["simple"] == {"provider": "openai-codex", "model": "gpt-5.4-mini"}
        assert tiers["complex"]["provider"] == "moa"

    def test_user_tiers_override_and_disable(self):
        r = _load_router()
        settings = {"tiers": {"simple": {"provider": "gemini", "model": "gemini-3.6-flash"}, "complex": None}}
        tiers = r.resolve_tiers(settings, _MOA_CFG)
        assert tiers["simple"] == {"provider": "gemini", "model": "gemini-3.6-flash"}
        assert tiers["complex"] is None
        assert tiers["normal"]["model"] == "claude-fable-5"


# ---------------------------------------------------------------------------
# Router facade
# ---------------------------------------------------------------------------

def _make_router(r, settings=None, llm=None, config=None):
    settings = settings or {}
    return r.Router(
        settings_getter=lambda k, d=None: settings.get(k, d),
        config_loader=lambda: config or _MOA_CFG,
        llm=llm,
    )


class TestRouter:
    def test_simple_routes_to_fast_model(self, monkeypatch):
        r = _load_router()
        router = _make_router(r)
        monkeypatch.setattr(
            r.OverrideResolver, "_resolve_uncached",
            staticmethod(lambda p, m, *a: {"model": m, "runtime": {"provider": p, "api_key": "k", "base_url": "", "api_mode": "anthropic_messages"}}),
        )
        out = router.route("hi", current_model="default", current_runtime={"provider": "moa"})
        assert out["model"] == "claude-haiku-4-5-20251001"
        assert out["runtime"]["provider"] == "anthropic"
        assert out["reason"].startswith("simple")
        assert router.history[-1].tier == "simple"

    def test_complex_routes_to_moa_virtual_runtime(self):
        r = _load_router()
        router = _make_router(r, config={"model": {"provider": "anthropic", "default": "claude-fable-5"}})
        out = router.route("```py\nx=1\n```", current_model="claude-fable-5", current_runtime={"provider": "anthropic"})
        assert out["model"] == "default"
        assert out["runtime"] == dict(r.MOA_VIRTUAL_RUNTIME)

    def test_noop_when_already_on_target(self):
        r = _load_router()
        router = _make_router(r)
        # complex on a MoA-default session → already on moa/default
        assert router.route("```py\nx=1\n```", current_model="default", current_runtime={"provider": "moa"}) is None

    def test_respects_session_override(self):
        r = _load_router()
        router = _make_router(r)
        assert router.route("hi", current_model="default", current_runtime={"provider": "moa"}, has_session_override=True) is None
        assert router.history[-1].via == "skip"

    def test_off_and_skips(self):
        r = _load_router()
        assert _make_router(r, {"enabled": False}).route("hi", current_model="x", current_runtime={}) is None
        assert _make_router(r, {"mode": "off"}).route("hi", current_model="x", current_runtime={}) is None
        assert _make_router(r).route("/router", current_model="x", current_runtime={}) is None

    def test_credential_failure_fails_open(self, monkeypatch):
        r = _load_router()
        router = _make_router(r)
        monkeypatch.setattr(r.OverrideResolver, "_resolve_uncached", staticmethod(lambda *a: None))
        assert router.route("hi", current_model="default", current_runtime={"provider": "moa"}) is None


# ---------------------------------------------------------------------------
# Gateway seam
# ---------------------------------------------------------------------------

class TestGatewaySeam:
    def _runner(self, monkeypatch, hook_result):
        from gateway.run import GatewayRunner

        runner = object.__new__(GatewayRunner)
        runner._service_tier = None
        monkeypatch.setattr(GatewayRunner, "_peek_session_state", lambda self, key: None, raising=False)
        monkeypatch.setattr("nunmai_cli.lifecycle.has_hook", lambda name: name == "resolve_turn_model")
        captured = {}

        def fake_invoke(name, **kw):
            captured.update(kw)
            return [hook_result]

        monkeypatch.setattr("nunmai_cli.lifecycle.invoke_hook", fake_invoke)
        monkeypatch.setattr("gateway.run._credential_pool_for_provider", lambda p: f"pool:{p}")
        return runner, captured

    def test_override_applied_to_route(self, monkeypatch):
        runner, captured = self._runner(
            monkeypatch,
            {"model": "claude-haiku-4-5-20251001", "runtime": {"provider": "anthropic", "api_key": "k", "base_url": "", "api_mode": "anthropic_messages"}, "reason": "simple"},
        )
        route = runner._resolve_turn_agent_config(
            "hi", "default", {"provider": "moa", "api_mode": "chat_completions"}, session_key="agent:main:whatsapp:dm:1"
        )
        assert captured["surface"] == "gateway" and captured["text"] == "hi" and captured["has_session_override"] is False
        assert route["model"] == "claude-haiku-4-5-20251001"
        assert route["runtime"]["provider"] == "anthropic"
        assert route["runtime"]["requested_provider"] == "anthropic"
        assert route["runtime"]["credential_pool"] == "pool:anthropic"
        assert route["signature"][0] == "claude-haiku-4-5-20251001" and route["signature"][1] == "anthropic"

    def test_no_session_key_means_no_routing(self, monkeypatch):
        runner, captured = self._runner(monkeypatch, {"model": "x", "runtime": {"provider": "y"}})
        route = runner._resolve_turn_agent_config("hi", "default", {"provider": "moa"})
        assert route["model"] == "default" and not captured

    def test_multimodal_text_extracted(self, monkeypatch):
        runner, captured = self._runner(monkeypatch, None)
        runner._resolve_turn_agent_config(
            [{"type": "image_url"}, {"type": "text", "text": "describe"}], "m", {"provider": "p"}, session_key="s"
        )
        assert captured["text"] == "describe"


# ---------------------------------------------------------------------------
# CLI seam
# ---------------------------------------------------------------------------

class _FakeAgent:
    def __init__(self):
        self.calls = []
        self._primary_runtime = {"model": "default", "provider": "moa"}

    def switch_model(self, **kw):
        self.calls.append(kw)


class _StubCLI:
    model = "default"
    provider = "moa"
    requested_provider = "moa"
    api_key = "moa-virtual-provider"
    base_url = "moa://local"
    api_mode = "chat_completions"
    _explicit_api_key = None
    _explicit_base_url = None
    session_id = "sess"
    _pending_one_turn_model_restore = None
    agent = None


class TestCliSeam:
    def _stub(self):
        import cli as cli_mod

        stub = _StubCLI()
        stub.agent = _FakeAgent()
        stub._snapshot_model_runtime = cli_mod.NunmaiCLI._snapshot_model_runtime.__get__(stub)
        stub._apply_resolve_turn_model_hook = cli_mod.NunmaiCLI._apply_resolve_turn_model_hook.__get__(stub)
        return stub

    def test_stages_one_turn_restore(self, monkeypatch):
        stub = self._stub()
        monkeypatch.setattr("nunmai_cli.lifecycle.has_hook", lambda name: True)
        monkeypatch.setattr(
            "nunmai_cli.lifecycle.invoke_hook",
            lambda name, **kw: [{"model": "claude-haiku-4-5-20251001", "runtime": {"provider": "anthropic", "api_key": "k", "api_mode": "anthropic_messages"}}],
        )
        stub._apply_resolve_turn_model_hook("hi")
        assert stub.model == "claude-haiku-4-5-20251001" and stub.provider == "anthropic"
        assert stub.agent.calls and stub.agent.calls[0]["new_provider"] == "anthropic"
        assert stub._pending_one_turn_model_restore["model"] == "default"
        assert stub._pending_one_turn_model_restore["provider"] == "moa"

    def test_explicit_once_wins(self, monkeypatch):
        stub = self._stub()
        stub._pending_one_turn_model_restore = {"model": "user-choice"}
        monkeypatch.setattr("nunmai_cli.lifecycle.has_hook", lambda name: True)
        monkeypatch.setattr("nunmai_cli.lifecycle.invoke_hook", lambda name, **kw: [{"model": "x", "runtime": {"provider": "y"}}])
        stub._apply_resolve_turn_model_hook("hi")
        assert stub.model == "default" and not stub.agent.calls

    def test_first_turn_without_agent_sets_cli_fields(self, monkeypatch):
        stub = self._stub()
        stub.agent = None
        monkeypatch.setattr("nunmai_cli.lifecycle.has_hook", lambda name: True)
        monkeypatch.setattr(
            "nunmai_cli.lifecycle.invoke_hook",
            lambda name, **kw: [{"model": "claude-haiku-4-5-20251001", "runtime": {"provider": "anthropic", "api_key": "k"}}],
        )
        stub._apply_resolve_turn_model_hook("hi")
        assert stub.model == "claude-haiku-4-5-20251001" and stub.provider == "anthropic" and stub.api_key == "k"
        assert stub._pending_one_turn_model_restore["model"] == "default"

    def test_no_hook_no_change(self, monkeypatch):
        stub = self._stub()
        monkeypatch.setattr("nunmai_cli.lifecycle.has_hook", lambda name: False)
        stub._apply_resolve_turn_model_hook("hi")
        assert stub.model == "default" and stub._pending_one_turn_model_restore is None


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

class TestPluginDiscovery:
    def test_loads_via_plugin_manager(self, _isolate_env):
        import yaml

        (_isolate_env / "config.yaml").write_text(yaml.safe_dump({"plugins": {"enabled": ["model-router"]}}))
        for k in list(sys.modules):
            if k.startswith(("nunmai_plugins", "nunmai_cli.plugins")):
                del sys.modules[k]
        from nunmai_cli.plugins import VALID_HOOKS, _ensure_plugins_discovered

        assert "resolve_turn_model" in VALID_HOOKS
        mgr = _ensure_plugins_discovered(force=True)
        assert "model-router" in set(getattr(mgr, "_plugins", {}).keys())
        assert mgr.has_hook("resolve_turn_model") if hasattr(mgr, "has_hook") else True
