"""``/brain`` must not block the chat when dispatched off the main thread.

Slash commands run on the ``process_loop`` daemon thread while prompt_toolkit
owns stdin.  The brain wizard reads the terminal with plain ``input()``; run
directly on that thread it blocked forever and every later message queued
behind it — the chat looked frozen (field report 2026-08-29).  The handler now
schedules the wizard onto the app loop inside ``run_in_terminal`` and waits
for it.  These tests pin the routing without a real terminal.
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from cli import NunmaiCLI


@pytest.fixture
def app_loop():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, name="pt-app-loop", daemon=True)
    thread.start()
    yield loop, thread
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)


def _make_cli(loop, wizard):
    obj = NunmaiCLI.__new__(NunmaiCLI)  # bypass __init__ (no full app needed)
    obj._app = SimpleNamespace(loop=loop)
    obj._status_bar_visible = True
    obj._invalidate = lambda *a, **k: None
    obj._run_brain_wizard = wizard
    obj._handle_model_switch = lambda *a, **k: None
    return obj


def _run_off_main_thread(fn, timeout=10.0):
    result = {}

    def _worker():
        try:
            fn()
            result["ok"] = True
        except BaseException as exc:  # pragma: no cover - surfaced by assert
            result["exc"] = exc

    t = threading.Thread(target=_worker, name="process_loop")
    t.start()
    t.join(timeout=timeout)
    assert not t.is_alive(), "/brain handler hung off the main thread"
    if "exc" in result:
        raise result["exc"]
    return result


def test_wizard_runs_on_app_loop_and_handler_waits(app_loop, monkeypatch):
    loop, thread = app_loop
    seen = []

    def wizard():
        seen.append(threading.current_thread().name)

    cli_obj = _make_cli(loop, wizard)
    monkeypatch.setattr("prompt_toolkit.application.run_in_terminal", lambda fn: fn())
    monkeypatch.setattr("nunmai_cli.config.load_config", lambda: {})

    _run_off_main_thread(cli_obj._handle_brain_command)

    assert seen == [thread.name], "wizard must execute on the prompt_toolkit loop thread"
    assert cli_obj._status_bar_visible is True  # restored after the wizard


def test_wizard_error_is_reported_and_model_switch_skipped(app_loop, monkeypatch, capsys):
    loop, _ = app_loop

    def wizard():
        raise SystemExit("No AI account connected.")

    switched = []
    cli_obj = _make_cli(loop, wizard)
    cli_obj._handle_model_switch = lambda *a, **k: switched.append(a)
    monkeypatch.setattr("prompt_toolkit.application.run_in_terminal", lambda fn: fn())

    _run_off_main_thread(cli_obj._handle_brain_command)

    assert "No AI account connected." in capsys.readouterr().out
    assert switched == []


def test_without_running_app_wizard_runs_inline(monkeypatch):
    seen = []
    cli_obj = _make_cli(None, lambda: seen.append(threading.current_thread().name))
    cli_obj._app = None
    monkeypatch.setattr("nunmai_cli.config.load_config", lambda: {})

    _run_off_main_thread(cli_obj._handle_brain_command)

    assert seen == ["process_loop"]
