"""WhatsApp send_exec_approval renders a poll with plain approval words.

The poll question must carry the human reason only (never the raw command),
and the option labels must be words the gateway's blocking-approval text
intercept already resolves ("approve"/"always"/"deny", case-insensitive).
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock

import pytest


def _load_adapter_module():
    path = Path(__file__).resolve().parents[2] / "plugins" / "platforms" / "whatsapp" / "adapter.py"
    if "nunmai_plugins" not in sys.modules:
        ns = types.ModuleType("nunmai_plugins")
        ns.__path__ = []
        sys.modules["nunmai_plugins"] = ns
    pkg = types.ModuleType("nunmai_plugins.whatsapp_platform")
    pkg.__path__ = [str(path.parent)]
    sys.modules.setdefault("nunmai_plugins.whatsapp_platform", pkg)
    spec = importlib.util.spec_from_file_location("nunmai_plugins.whatsapp_platform.adapter", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def adapter():
    mod = _load_adapter_module()
    a = object.__new__(mod.WhatsAppAdapter)
    a.send_poll = AsyncMock(return_value=mod.SendResult(success=True, message_id="p1"))
    return a


def _call(adapter, **kw):
    return asyncio.get_event_loop().run_until_complete(
        adapter.send_exec_approval(
            chat_id="9665551234",
            command="rm -rf /srv/app && systemctl restart app",
            session_key="agent:main:whatsapp:dm:9665551234",
            **kw,
        )
    )


def test_poll_has_reason_not_command(adapter):
    result = _call(adapter, description="restart the app service to apply the fix")
    assert result.success
    args = adapter.send_poll.await_args
    question = args.args[1]
    options = args.args[2]
    assert "restart the app service" in question
    assert "rm -rf" not in question
    assert [o.lower() for o in options] == ["approve", "always", "deny"]


def test_smart_denied_offers_once_only(adapter):
    _call(adapter, description="delete old backups", smart_denied=True)
    options = adapter.send_poll.await_args.args[2]
    assert [o.lower() for o in options] == ["approve", "deny"]


def test_no_permanent_no_session_drops_always(adapter):
    _call(adapter, description="x", allow_permanent=False, allow_session=False)
    options = adapter.send_poll.await_args.args[2]
    assert [o.lower() for o in options] == ["approve", "deny"]


def test_long_reason_truncated(adapter):
    _call(adapter, description="word " * 100)
    question = adapter.send_poll.await_args.args[1]
    assert len(question) < 260
