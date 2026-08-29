"""``nunmai brain`` — connect the AI subscriptions / keys you already have.

One guided step: tick the AI accounts you own (Claude, ChatGPT, Kimi, Gemini,
OpenRouter), sign in or paste a key for each, and Nunmai Engine wires them as
primary + fallback chain automatically. Re-run any time to change.

Non-interactive: ``nunmai brain --providers anthropic,openai-codex``
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional

# (provider id used in config.yaml, label, how to connect)
#   oauth   -> `nunmai auth add <provider>` (browser sign-in)
#   env:VAR -> paste an API key, stored in ~/.nunmai/.env
#   claude  -> API key OR Claude Pro/Max token (`claude setup-token`)
BRAINS: List[Dict[str, str]] = [
    {"id": "anthropic", "label": "Claude", "sub": "Claude Pro / Max subscription, or an Anthropic API key", "how": "claude"},
    {"id": "openai-codex", "label": "ChatGPT", "sub": "ChatGPT Plus / Pro subscription (browser sign-in)", "how": "oauth"},
    {"id": "kimi-coding", "label": "Kimi", "sub": "Kimi subscription (browser sign-in)", "how": "oauth"},
    {"id": "gemini", "label": "Google Gemini", "sub": "Google AI Studio API key", "how": "env:GEMINI_API_KEY"},
    {"id": "openrouter", "label": "OpenRouter", "sub": "one API key, 300+ models", "how": "env:OPENROUTER_API_KEY"},
]
_BY_ID = {b["id"]: b for b in BRAINS}


def _nunmai_argv() -> List[str]:
    exe = shutil.which("nunmai")
    return [exe] if exe else [sys.executable, "-m", "nunmai_cli.main"]


def _ask(prompt: str) -> str:
    # Plain input(): works inside the chat's first-run path and standalone;
    # prompt_toolkit's line_input can drop the first keystroke during its
    # terminal probe when called from the CLI startup path.
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


def _secret(prompt: str) -> str:
    try:
        from nunmai_cli.auth_commands import masked_secret_prompt  # type: ignore
        return masked_secret_prompt(prompt).strip()
    except Exception:
        import getpass
        return getpass.getpass(prompt).strip()


def _save_env(key: str, value: str) -> None:
    from nunmai_cli.config import save_env_value
    save_env_value(key, value)
    os.environ[key] = value


def _connect(brain: Dict[str, str]) -> bool:
    """Run the connection step for one brain. Returns True on success."""
    pid, how, label = brain["id"], brain["how"], brain["label"]
    print()
    print(f"  ◆ {label}")
    if how == "oauth":
        print(f"    Opening browser sign-in for {label}…")
        rc = subprocess.call(_nunmai_argv() + ["auth", "add", pid])
        return rc == 0
    if how == "claude":
        print("    1) Anthropic API key   2) Claude Pro/Max subscription")
        choice = _ask("    Choose [1/2]: ") or "1"
        if choice.startswith("2"):
            print("    In another terminal run:  claude setup-token   (needs Claude Code installed)")
            tok = _secret("    Paste the token here: ")
            if not tok:
                return False
            _save_env("CLAUDE_CODE_OAUTH_TOKEN", tok)
            return True
        key = _secret("    Paste your Anthropic API key (sk-ant-…): ")
        if not key:
            return False
        _save_env("ANTHROPIC_API_KEY", key)
        return True
    if how.startswith("env:"):
        var = how.split(":", 1)[1]
        key = _secret(f"    Paste your {label} API key: ")
        if not key:
            return False
        _save_env(var, key)
        return True
    return False


def _default_model(provider: str) -> str:
    try:
        from nunmai_cli.models import get_default_model_for_provider
        return get_default_model_for_provider(provider) or ""
    except Exception:
        return ""


def _wire(selected: List[str]) -> None:
    """Primary = first selected; the rest become the fallback chain."""
    from nunmai_cli.config import load_config, save_config
    from nunmai_cli.fallback_cmd import _write_chain

    cfg = load_config()
    primary = selected[0]
    model_cfg = cfg.get("model") if isinstance(cfg.get("model"), dict) else {}
    model_cfg = dict(model_cfg or {})
    model_cfg["provider"] = primary
    model_cfg["default"] = _default_model(primary) or model_cfg.get("default") or ""
    model_cfg.pop("base_url", None)
    cfg["model"] = model_cfg

    chain = [{"provider": p, "model": _default_model(p)} for p in selected[1:]]
    _write_chain(cfg, chain)
    save_config(cfg)

    print()
    print("  Your AI brain:")
    print(f"    primary   → {_BY_ID[primary]['label']}  ({model_cfg['default'] or 'default model'})")
    for e in chain:
        print(f"    fallback  → {_BY_ID[e['provider']]['label']}  ({e['model'] or 'default model'})")
    print()
    print("  Done. Run  nunmai  to chat.  Change later: nunmai brain · nunmai model · nunmai fallback")


def cmd_brain(args: Any) -> None:
    wanted: Optional[str] = getattr(args, "providers", None)
    if wanted:
        selected = [p.strip() for p in wanted.split(",") if p.strip()]
        bad = [p for p in selected if p not in _BY_ID]
        if bad:
            raise SystemExit(f"Unknown provider(s): {', '.join(bad)}. Choose from: {', '.join(_BY_ID)}")
    else:
        if not sys.stdin.isatty():
            raise SystemExit("nunmai brain needs a terminal (or pass --providers a,b,c).")
        print()
        print("  ◆ Nunmai Engine — connect your AI brain")
        print("  Which AI accounts do you have? You can pick several; the first is primary,")
        print("  the others take over automatically when it is busy or out of quota.")
        print()
        for i, b in enumerate(BRAINS, 1):
            print(f"    {i}) {b['label']:<15} {b['sub']}")
        print()
        raw = _ask("  Enter numbers in order of preference (e.g. 1,2,3): ")
        idx: List[int] = []
        for tok in raw.replace(" ", ",").split(","):
            if tok.isdigit() and 1 <= int(tok) <= len(BRAINS) and int(tok) not in idx:
                idx.append(int(tok))
        selected = [BRAINS[i - 1]["id"] for i in idx]
    if not selected:
        print("  Nothing selected. Run  nunmai brain  again when ready.")
        return

    connected: List[str] = []
    for pid in selected:
        if getattr(args, "skip_connect", False) or _connect(_BY_ID[pid]):
            connected.append(pid)
        else:
            print(f"    ✗ {_BY_ID[pid]['label']} not connected (skipped)")
    if not connected:
        raise SystemExit("No AI account connected.")
    _wire(connected)
