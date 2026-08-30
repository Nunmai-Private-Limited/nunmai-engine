"""model-router plugin — pick the right brain for each turn.

Hooks ``resolve_turn_model`` (fired by the CLI and the gateway just before an
agent turn is built) and answers with a per-turn model/runtime override:

* simple messages  → a fast, cheap model
* normal messages  → the main model
* complex messages → the Nunmai Agent orchestrator (``moa`` provider)

The configured default model is never changed; every override lasts exactly
one turn.  ``/router`` shows the current mode, resolved tiers and the last
decisions; ``/router off|on|auto|heuristic`` flips the mode.

Settings live under ``plugins.entries.model-router.settings`` (see
``plugin.yaml``).  The classifier runs as auxiliary task ``model_router`` so it
can be pinned to any provider/model under ``auxiliary.model_router``; by default
it prefers the main provider's fast tier.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from . import router as _router

logger = logging.getLogger("nunmai.model_router")

_ctx = None
_ROUTER: Optional[_router.Router] = None


def _get_setting(key: str, default: Any = None) -> Any:
    if _ctx is None:
        return default
    try:
        value = _ctx.get_config(key, default)
    except Exception:
        return default
    return default if value is None else value


def _load_config() -> Dict[str, Any]:
    try:
        from nunmai_cli.config import load_config_readonly

        return load_config_readonly() or {}
    except Exception:
        try:
            from nunmai_cli.config import load_config

            return load_config() or {}
        except Exception:
            return {}


def _classify_with_llm(snippet: str) -> str:
    """Ask the fast auxiliary model for SIMPLE / NORMAL / COMPLEX."""
    timeout = float(_get_setting("classifier_timeout", 8) or 8)
    messages = [
        {"role": "system", "content": _router._CLASSIFIER_SYSTEM},
        {"role": "user", "content": snippet},
    ]
    if _ctx is not None and getattr(_ctx, "llm", None) is not None:
        result = _ctx.llm.complete(
            messages,
            task=_router.AUX_TASK,
            max_tokens=5,
            temperature=0,
            timeout=timeout,
            purpose="model-router tier classification",
        )
        return getattr(result, "text", "") or ""
    # Fallback for environments without the plugin LLM facade.
    from agent.auxiliary_client import call_llm

    response = call_llm(
        task=_router.AUX_TASK,
        messages=messages,
        max_tokens=5,
        temperature=0,
        timeout=timeout,
    )
    try:
        return response.choices[0].message.content or ""
    except Exception:
        return ""


def _get_router() -> _router.Router:
    global _ROUTER
    if _ROUTER is None:
        _ROUTER = _router.Router(
            settings_getter=_get_setting,
            config_loader=_load_config,
            llm=_classify_with_llm,
        )
    return _ROUTER


# ---------------------------------------------------------------------------
# Hook
# ---------------------------------------------------------------------------

def _on_resolve_turn_model(
    text: Any = None,
    model: str = "",
    runtime: Optional[Dict[str, Any]] = None,
    surface: str = "",
    session_key: str = "",
    has_session_override: bool = False,
    **_kwargs: Any,
) -> Optional[Dict[str, Any]]:
    try:
        return _get_router().route(
            text if isinstance(text, str) else None,
            current_model=str(model or ""),
            current_runtime=dict(runtime or {}),
            has_session_override=bool(has_session_override),
        )
    except Exception:  # never let routing break a turn
        logger.debug("model_router: route() failed", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# /router slash command
# ---------------------------------------------------------------------------

def _fmt_target(t: Optional[Dict[str, str]]) -> str:
    if not t:
        return "— (use main model)"
    if t["provider"] == "moa":
        return f"Nunmai Agent orchestrator (preset '{t['model']}')"
    return f"{t['provider']}/{t['model']}"


def _handle_router_command(raw_args: str = "") -> str:
    arg = (raw_args or "").strip().lower()
    router = _get_router()
    if arg in ("off", "on", "auto", "heuristic"):
        if _ctx is None:
            return "model-router: settings are not writable in this context."
        if arg == "off":
            _ctx.set_config("enabled", False)
        else:
            _ctx.set_config("enabled", True)
            _ctx.set_config("mode", "auto" if arg == "on" else arg)
        return f"model-router: mode is now **{router.mode}**."
    if arg and arg not in ("status", "show", ""):
        return "Usage: /router [status|on|off|auto|heuristic]"

    tiers = router.tiers()
    lines = [
        f"model-router: mode **{router.mode}**",
        f"  simple  → {_fmt_target(tiers.get('simple'))}",
        f"  normal  → {_fmt_target(tiers.get('normal'))}",
        f"  complex → {_fmt_target(tiers.get('complex'))}",
    ]
    if router.history:
        lines.append("Recent decisions:")
        now = time.time()
        for d in list(router.history)[-8:]:
            age = int(now - d.ts)
            lines.append(f"  {age:>4}s ago  {d.tier:<7} {d.via:<10} {d.reason}")
    else:
        lines.append("No decisions yet.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    global _ctx, _ROUTER
    _ctx = ctx
    _ROUTER = None
    try:
        ctx.register_auxiliary_task(
            key=_router.AUX_TASK,
            display_name="Model router classifier",
            description="Fast model that labels each message simple / normal / complex for per-turn brain routing.",
            defaults={"provider": "auto", "model": "", "timeout": 8, "prefer_fast_model": True},
        )
    except Exception:
        logger.debug("model_router: auxiliary task registration failed", exc_info=True)
    ctx.register_hook("resolve_turn_model", _on_resolve_turn_model)
    ctx.register_command(
        "router",
        handler=_handle_router_command,
        description="Show or change per-turn brain routing (simple → fast, normal → main, complex → orchestrator).",
        args_hint="[status|on|off|auto|heuristic]",
    )
