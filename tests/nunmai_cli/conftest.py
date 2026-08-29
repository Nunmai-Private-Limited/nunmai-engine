"""Fixtures shared across nunmai_cli kanban tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def all_assignees_spawnable(monkeypatch):
    """Pretend every assignee maps to a real Nunmai profile.

    Most dispatcher tests use synthetic assignees ("alice", "bob") that
    don't correspond to actual profile directories on disk. Without this
    patch, the dispatcher's profile-exists guard (PR #20105) routes
    those tasks into ``skipped_nonspawnable`` instead of spawning, which
    would break tests that assert spawn behavior.
    """
    from nunmai_cli import profiles
    monkeypatch.setattr(profiles, "profile_exists", lambda name: True)


@pytest.fixture(autouse=True)
def _suppress_concurrent_nunmai_gate(request, monkeypatch):
    """Default ``_detect_concurrent_nunmai_instances`` to ``[]`` for every test.

    The Windows update path now refuses to proceed when another
    ``nunmai.exe`` is detected (issue #26670). On a developer's Windows
    machine running the test suite via ``nunmai`` itself, this would
    flag the running agent as a concurrent instance and abort every
    ``cmd_update`` test. Tests that want to exercise the gate explicitly
    re-patch ``_detect_concurrent_nunmai_instances`` with their own
    return value — autouse here gives a clean default without touching
    the rest of the suite.

    Tests that need to call the REAL function (e.g. unit tests for the
    helper itself) opt out with ``@pytest.mark.real_concurrent_gate``.
    """
    if request.node.get_closest_marker("real_concurrent_gate"):
        return
    try:
        from nunmai_cli import main as _cli_main
    except Exception:
        return
    # raising=False: under pytest's per-test spawn isolation, a concurrent
    # xdist worker importing a module that transitively touches nunmai_cli.main
    # can briefly expose a partially-initialized module object here — one where
    # _detect_concurrent_nunmai_instances isn't defined yet. A bare setattr
    # would raise AttributeError and error the (unrelated) test. The attribute
    # always exists once main.py finishes importing, so a no-op when it's
    # transiently absent is the correct, race-free default.
    monkeypatch.setattr(
        _cli_main,
        "_detect_concurrent_nunmai_instances",
        lambda *_a, **_k: [],
        raising=False,
    )


@pytest.fixture(autouse=True)
def _disable_node_toolchain_preflight(request, monkeypatch):
    """Keep ``preflight_node_toolchain`` from probing the host's node/npm.

    Before every npm install the CLI probes the resolved toolchain's versions
    (``node --version`` / ``npm --version``) and swaps an unsupported system
    Node for the Nunmai-managed runtime. Under test that means two extra
    ``subprocess`` calls that scripted ``subprocess.run`` fakes never planned
    for — and on a developer machine with a non-LTS Node, a real managed-Node
    provisioning. Identity here; tests for the preflight itself opt out with
    ``@pytest.mark.real_node_preflight``.
    """
    if request.node.get_closest_marker("real_node_preflight"):
        return
    try:
        from nunmai_cli import npm_engine as _npm_engine
    except Exception:
        return
    monkeypatch.setattr(
        _npm_engine,
        "preflight_node_toolchain",
        lambda npm, *, quiet=False: npm,
        raising=False,
    )


@pytest.fixture(autouse=True)
def _isolate_launchd_home(request, monkeypatch, tmp_path):
    """Keep launchd plist paths off the developer's real ``~/Library``.

    ``nunmai_cli.gateway.get_launchd_plist_path`` resolves the account home
    via ``pwd.getpwuid`` on purpose (profile mode rewrites ``HOME``), which
    also means the test-isolated ``NUNMAI_HOME`` does not redirect it. On a
    macOS developer machine with a real ``ai.nunmai.gateway`` LaunchAgent the
    end-to-end ``cmd_update`` tests then found that plist, rewrote it, and
    restarted / verified the real (production) gateway through ``launchctl``
    (2026-08-29: three restarts of a live WhatsApp gateway during a test run).
    Point the launchd home at a per-test temp dir so no plist exists and the
    restart phase is a no-op. Tests that must see the real home opt out with
    ``@pytest.mark.real_launchd_home``.
    """
    if request.node.get_closest_marker("real_launchd_home"):
        return
    try:
        from nunmai_cli import gateway as _gateway
    except Exception:
        return
    fake_home = tmp_path / "launchd-home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        _gateway, "_launchd_user_home", lambda: fake_home, raising=False
    )


@pytest.fixture(autouse=True)
def _disable_stale_module_purge(request, monkeypatch):
    """Keep ``_purge_stale_nunmai_modules`` from evicting patched modules.

    The updater purges every cached ``nunmai_cli.*`` / ``gateway`` / ``tools``
    / ``agent`` module after a pull so later lazy imports see the new code.
    Under pytest that eviction re-imports FRESH module objects mid-test, and
    every monkeypatch the test (or this conftest) applied to the old objects
    silently stops applying: end-to-end ``cmd_update`` tests then ran the
    real launchd restart against a live gateway and a real ``uv`` install
    into the checkout's venv (2026-08-29). Purge-specific tests opt out with
    ``@pytest.mark.real_module_purge``.
    """
    if request.node.get_closest_marker("real_module_purge"):
        return
    for modname in ("nunmai_cli.update_cmd", "nunmai_cli.main"):
        try:
            mod = __import__(modname, fromlist=["_purge_stale_nunmai_modules"])
        except Exception:
            continue
        monkeypatch.setattr(mod, "_purge_stale_nunmai_modules", lambda: None, raising=False)
