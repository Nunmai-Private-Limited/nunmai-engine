"""`nunmai uninstall` is one question, like the installer is none.

- default: a single [Y/n] prompt; Enter/y removes the engine and KEEPS data.
- --full: a single typed "yes" (destructive); profiles asked only when present.
- n / Ctrl+C: nothing changes.
- The removal report lists only what actually changed.
"""
import types
from pathlib import Path

import pytest

from nunmai_cli import uninstall as u


@pytest.fixture
def wired(monkeypatch, tmp_path):
    root = tmp_path / "nunmai-engine"; root.mkdir()
    home = tmp_path / ".nunmai"; home.mkdir()
    calls = []
    monkeypatch.setattr(u, "get_project_root", lambda: root)
    monkeypatch.setattr(u, "get_nunmai_home", lambda: home)
    monkeypatch.setattr(u, "_discover_named_profiles", lambda: [])
    monkeypatch.setattr(u, "_perform_uninstall", lambda **kw: calls.append(kw))
    return types.SimpleNamespace(root=root, home=home, calls=calls)


def _args(**kw):
    base = {"full": False, "yes": False, "dry_run": False}
    base.update(kw)
    return types.SimpleNamespace(**base)


def _answers(monkeypatch, *answers):
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))


def test_default_is_single_yn_prompt_and_keeps_data(monkeypatch, wired, capsys):
    _answers(monkeypatch, "")  # Enter = yes
    u.run_uninstall(_args())
    assert len(wired.calls) == 1
    assert wired.calls[0]["full_uninstall"] is False
    assert wired.calls[0]["remove_profiles"] is False
    out = capsys.readouterr().out
    assert "kept" in out
    assert "Select option" not in out


def test_default_n_cancels_without_changes(monkeypatch, wired, capsys):
    _answers(monkeypatch, "n")
    u.run_uninstall(_args())
    assert wired.calls == []
    assert "nothing was changed" in capsys.readouterr().out


def test_full_requires_typed_yes(monkeypatch, wired):
    _answers(monkeypatch, "y")  # not the literal "yes"
    u.run_uninstall(_args(full=True))
    assert wired.calls == []
    _answers(monkeypatch, "yes")
    u.run_uninstall(_args(full=True))
    assert wired.calls[0]["full_uninstall"] is True


def test_full_asks_about_profiles_only_when_present(monkeypatch, wired):
    prof = types.SimpleNamespace(name="work", path=wired.home / "profiles" / "work", gateway_running=False)
    monkeypatch.setattr(u, "_discover_named_profiles", lambda: [prof])
    monkeypatch.setattr(u, "_is_default_nunmai_home", lambda p: True)
    _answers(monkeypatch, "yes", "y")
    u.run_uninstall(_args(full=True))
    assert wired.calls[0]["remove_profiles"] is True
    assert wired.calls[0]["named_profiles"] == [prof]


def test_ctrl_c_cancels(monkeypatch, wired):
    def boom(prompt=""):
        raise KeyboardInterrupt
    monkeypatch.setattr("builtins.input", boom)
    u.run_uninstall(_args())
    assert wired.calls == []


def test_yes_flag_skips_prompts(monkeypatch, wired):
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("must not prompt"))
    u.run_uninstall(_args(yes=True, full=True))
    assert wired.calls[0]["full_uninstall"] is True


def test_report_lists_only_what_changed(monkeypatch, tmp_path, capsys):
    root = tmp_path / "nunmai-engine"; root.mkdir(); (root / "x").write_text("x")
    home = tmp_path / ".nunmai"; home.mkdir()
    for name in ("uninstall_gateway_service",):
        monkeypatch.setattr(u, name, lambda: False)
    for name in ("remove_path_from_shell_configs", "remove_wrapper_script"):
        monkeypatch.setattr(u, name, lambda: [])
    monkeypatch.setattr(u, "remove_node_symlinks", lambda h: [])
    monkeypatch.setattr(u, "find_npm_shim_path", lambda: None)
    monkeypatch.setattr(u, "_is_windows", lambda: False)
    import nunmai_cli.gui_uninstall as g
    monkeypatch.setattr(g, "uninstall_gui", lambda h: False)
    u._perform_uninstall(project_root=root, nunmai_home=home, full_uninstall=False, remove_profiles=False, named_profiles=[])
    out = capsys.readouterr().out
    assert not root.exists() and home.exists()
    assert f"Removed engine {root}" in out
    assert "Kept your config and data" in out
    assert "No " not in out and "Checking" not in out
