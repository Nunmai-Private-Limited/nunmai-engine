"""`nunmai uninstall` is one question, like the installer is none.

- default: a single [y/N] prompt; y removes the engine AND all data/caches/npm package.
- --keep-data: a single [Y/n] prompt; Enter/y removes the engine but keeps ~/.nunmai.
- --full (legacy): same as the default.
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
    base = {"full": False, "keep_data": False, "yes": False, "dry_run": False}
    base.update(kw)
    return types.SimpleNamespace(**base)


def _answers(monkeypatch, *answers):
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))


def test_default_is_single_prompt_and_removes_everything(monkeypatch, wired, capsys):
    _answers(monkeypatch, "y")
    u.run_uninstall(_args())
    assert len(wired.calls) == 1
    assert wired.calls[0]["full_uninstall"] is True
    assert wired.calls[0]["remove_profiles"] is False
    out = capsys.readouterr().out
    assert "deleted" in out
    assert "Select option" not in out


def test_default_enter_cancels_destructive_removal(monkeypatch, wired, capsys):
    _answers(monkeypatch, "")  # Enter = No for the destructive default
    u.run_uninstall(_args())
    assert wired.calls == []
    out = capsys.readouterr().out
    assert "nothing was changed" in out
    assert "--keep-data" in out


def test_keep_data_is_yn_default_yes(monkeypatch, wired, capsys):
    _answers(monkeypatch, "")  # Enter = yes
    u.run_uninstall(_args(keep_data=True))
    assert wired.calls[0]["full_uninstall"] is False
    assert "kept" in capsys.readouterr().out


def test_keep_data_n_cancels(monkeypatch, wired):
    _answers(monkeypatch, "n")
    u.run_uninstall(_args(keep_data=True))
    assert wired.calls == []


def test_legacy_full_flag_means_the_default(monkeypatch, wired):
    _answers(monkeypatch, "yes")
    u.run_uninstall(_args(full=True))
    assert wired.calls[0]["full_uninstall"] is True


def test_asks_about_profiles_only_when_present(monkeypatch, wired):
    prof = types.SimpleNamespace(name="work", path=wired.home / "profiles" / "work", gateway_running=False)
    monkeypatch.setattr(u, "_discover_named_profiles", lambda: [prof])
    monkeypatch.setattr(u, "_is_default_nunmai_home", lambda p: True)
    _answers(monkeypatch, "y", "y")
    u.run_uninstall(_args())
    assert wired.calls[0]["remove_profiles"] is True
    assert wired.calls[0]["named_profiles"] == [prof]


def test_ctrl_c_cancels(monkeypatch, wired):
    def boom(prompt=""):
        raise KeyboardInterrupt
    monkeypatch.setattr("builtins.input", boom)
    u.run_uninstall(_args())
    assert wired.calls == []


def test_yes_flag_skips_prompts_and_removes_everything(monkeypatch, wired):
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("must not prompt"))
    u.run_uninstall(_args(yes=True))
    assert wired.calls[0]["full_uninstall"] is True


def test_yes_keep_data(monkeypatch, wired):
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("must not prompt"))
    u.run_uninstall(_args(yes=True, keep_data=True))
    assert wired.calls[0]["full_uninstall"] is False


def _quiet_perform(monkeypatch):
    for name in ("uninstall_gateway_service",):
        monkeypatch.setattr(u, name, lambda: False)
    for name in ("remove_path_from_shell_configs", "remove_wrapper_script"):
        monkeypatch.setattr(u, name, lambda: [])
    monkeypatch.setattr(u, "remove_node_symlinks", lambda h: [])
    monkeypatch.setattr(u, "remove_npm_global_links", lambda r, h: [])
    monkeypatch.setattr(u, "find_npm_shim_path", lambda: None)
    monkeypatch.setattr(u, "_is_windows", lambda: False)
    monkeypatch.setattr(u, "playwright_browsers_dir", lambda: None)
    monkeypatch.setattr(u, "uv_cache_dir", lambda h: None)
    import nunmai_cli.gui_uninstall as g
    monkeypatch.setattr(g, "uninstall_gui", lambda h: False)


def test_report_lists_only_what_changed_keep_data(monkeypatch, tmp_path, capsys):
    root = tmp_path / "nunmai-engine"; root.mkdir(); (root / "x").write_text("x")
    home = tmp_path / ".nunmai"; home.mkdir()
    _quiet_perform(monkeypatch)
    u._perform_uninstall(project_root=root, nunmai_home=home, full_uninstall=False, remove_profiles=False, named_profiles=[])
    out = capsys.readouterr().out
    assert not root.exists() and home.exists()
    assert f"Removed engine {root}" in out
    assert "Kept your config and data" in out
    assert "No " not in out and "Checking" not in out


def test_full_removes_home_and_caches(monkeypatch, tmp_path, capsys):
    root = tmp_path / "nunmai-engine"; root.mkdir()
    home = tmp_path / ".nunmai"; home.mkdir()
    pw = tmp_path / "ms-playwright"; pw.mkdir(); (pw / "chromium").mkdir()
    uvc = tmp_path / "uv"; uvc.mkdir()
    _quiet_perform(monkeypatch)
    monkeypatch.setattr(u, "playwright_browsers_dir", lambda: pw)
    monkeypatch.setattr(u, "uv_cache_dir", lambda h: uvc)
    u._perform_uninstall(project_root=root, nunmai_home=home, full_uninstall=True, remove_profiles=False, named_profiles=[])
    out = capsys.readouterr().out
    assert not root.exists() and not home.exists() and not pw.exists() and not uvc.exists()
    assert f"Removed cache {pw}" in out
    assert "Kept your config" not in out


def test_npm_package_removed_when_installed_via_npm(monkeypatch, tmp_path, capsys):
    root = tmp_path / "nunmai-engine"; root.mkdir()
    home = tmp_path / ".nunmai"; home.mkdir()
    shim = tmp_path / "lib" / "node_modules" / "nunmai" / "bin" / "nunmai.js"
    _quiet_perform(monkeypatch)
    monkeypatch.setattr(u, "find_npm_shim_path", lambda: shim)
    seen = []
    monkeypatch.setattr(u, "remove_npm_package", lambda s, h: seen.append((s, h)) or True)
    monkeypatch.setattr(u, "restore_npm_shim_launcher", lambda s: pytest.fail("must not restore when npm removal succeeded"))
    u._perform_uninstall(project_root=root, nunmai_home=home, full_uninstall=True, remove_profiles=False, named_profiles=[])
    out = capsys.readouterr().out
    assert seen == [(shim, home)]
    assert "Removed the npm package" in out
    assert "Could not remove the npm package" not in out


def test_npm_removal_failure_restores_launcher_and_hints(monkeypatch, tmp_path, capsys):
    root = tmp_path / "nunmai-engine"; root.mkdir()
    home = tmp_path / ".nunmai"; home.mkdir()
    shim = tmp_path / "lib" / "node_modules" / "nunmai" / "bin" / "nunmai.js"
    _quiet_perform(monkeypatch)
    monkeypatch.setattr(u, "find_npm_shim_path", lambda: shim)
    monkeypatch.setattr(u, "remove_npm_package", lambda s, h: False)
    restored = []
    monkeypatch.setattr(u, "restore_npm_shim_launcher", lambda s: restored.append(s) or (tmp_path / "link"))
    u._perform_uninstall(project_root=root, nunmai_home=home, full_uninstall=True, remove_profiles=False, named_profiles=[])
    out = capsys.readouterr().out
    assert restored == [shim]
    assert "npm uninstall -g nunmai" in out


# --- helpers -----------------------------------------------------------------

def test_npm_global_prefix_posix(monkeypatch, tmp_path):
    monkeypatch.setattr(u, "_is_windows", lambda: False)
    shim = tmp_path / "usr" / "local" / "lib" / "node_modules" / "nunmai" / "bin" / "nunmai.js"
    shim.parent.mkdir(parents=True); shim.write_text("x")
    assert u._npm_global_prefix(shim) == tmp_path / "usr" / "local"


def test_npm_global_prefix_project_local_is_none(monkeypatch, tmp_path):
    monkeypatch.setattr(u, "_is_windows", lambda: False)
    proj = tmp_path / "lib"  # even a project dir literally named "lib"
    shim = proj / "node_modules" / "nunmai" / "bin" / "nunmai.js"
    shim.parent.mkdir(parents=True); shim.write_text("x")
    (proj / "package.json").write_text("{}")
    assert u._npm_global_prefix(shim) is None
    shim2 = tmp_path / "app" / "node_modules" / "nunmai" / "bin" / "nunmai.js"
    shim2.parent.mkdir(parents=True); shim2.write_text("x")
    assert u._npm_global_prefix(shim2) is None


def test_npm_global_prefix_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(u, "_is_windows", lambda: True)
    npm_dir = tmp_path / "AppData" / "Roaming" / "npm"
    shim = npm_dir / "node_modules" / "nunmai" / "bin" / "nunmai.js"
    shim.parent.mkdir(parents=True); shim.write_text("x")
    assert u._npm_global_prefix(shim) is None  # no bin shim → not a global install
    (npm_dir / "nunmai.cmd").write_text("x")
    assert u._npm_global_prefix(shim) == npm_dir


def test_remove_npm_package_runs_npm_with_prefix(monkeypatch, tmp_path):
    monkeypatch.setattr(u, "_is_windows", lambda: False)
    prefix = tmp_path / "usr" / "local"
    shim = prefix / "lib" / "node_modules" / "nunmai" / "bin" / "nunmai.js"
    shim.parent.mkdir(parents=True); shim.write_text("x")
    npm = prefix / "bin" / "npm"; npm.parent.mkdir(); npm.write_text("#!/bin/sh\n")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        shim.unlink()
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(u.subprocess, "run", fake_run)
    assert u.remove_npm_package(shim, tmp_path / ".nunmai") is True
    assert calls[0][:1] == [str(npm)]
    assert calls[0][1:] == ["uninstall", "-g", "--prefix", str(prefix), "nunmai"]


def test_remove_npm_package_local_is_none(monkeypatch, tmp_path):
    monkeypatch.setattr(u, "_is_windows", lambda: False)
    shim = tmp_path / "app" / "node_modules" / "nunmai" / "bin" / "nunmai.js"
    shim.parent.mkdir(parents=True); shim.write_text("x")
    monkeypatch.setattr(u.subprocess, "run", lambda *a, **k: pytest.fail("must not run npm"))
    assert u.remove_npm_package(shim, tmp_path / ".nunmai") is None


def test_playwright_dir_respects_user_override(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/somewhere")
    assert u.playwright_browsers_dir() is None
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH")
    assert u.playwright_browsers_dir().name == "ms-playwright"


def test_uv_cache_only_when_uv_is_ours(monkeypatch, tmp_path):
    home = tmp_path / ".nunmai"
    (home / "bin").mkdir(parents=True)
    monkeypatch.delenv("UV_CACHE_DIR", raising=False)
    monkeypatch.setattr(u.shutil, "which", lambda n: str(tmp_path / "usr" / "bin" / "uv"))
    assert u.uv_cache_dir(home) is None  # user's own uv → keep its cache
    monkeypatch.setattr(u.shutil, "which", lambda n: str(home / "bin" / "uv"))
    assert u.uv_cache_dir(home) is not None
    monkeypatch.setattr(u.shutil, "which", lambda n: None)
    assert u.uv_cache_dir(home) is not None
    monkeypatch.setenv("UV_CACHE_DIR", "/x")
    assert u.uv_cache_dir(home) is None


def test_npm_global_links_into_engine_are_removed(monkeypatch, tmp_path):
    monkeypatch.setattr(u, "_is_windows", lambda: False)
    root = tmp_path / "usr" / "local" / "lib" / "nunmai-engine"; (root / "ui-tui").mkdir(parents=True)
    nm = tmp_path / "usr" / "local" / "lib" / "node_modules"; nm.mkdir()
    (nm / "nunmai-engine").symlink_to(root)
    (nm / "nunmai-tui").symlink_to(root / "ui-tui")
    (nm / "nunmai").mkdir()  # the npm launcher package — not ours to touch here
    other = tmp_path / "elsewhere"; other.mkdir()
    (nm / "somepkg").symlink_to(other)
    (nm / "real").mkdir()
    monkeypatch.setattr(u, "_npm_global_node_modules", lambda h: [nm])
    removed = u.remove_npm_global_links(root, tmp_path / ".nunmai")
    assert sorted(p.name for p in removed) == ["nunmai-engine", "nunmai-tui"]
    assert (nm / "somepkg").is_symlink() and (nm / "real").is_dir() and (nm / "nunmai").is_dir()


def test_path_sweep_removes_marker_and_following_export(monkeypatch, tmp_path):
    rc = tmp_path / ".bashrc"
    rc.write_text('alias ll="ls -l"\n\n# Nunmai Engine — ensure ~/.local/bin is on PATH\nexport PATH="$HOME/.local/bin:$PATH"\n\nexport EDITOR=vim\n')
    monkeypatch.setattr(u, "find_shell_configs", lambda: [rc])
    assert u.remove_path_from_shell_configs() == [rc]
    out = rc.read_text()
    assert "Nunmai" not in out and ".local/bin" not in out
    assert 'alias ll="ls -l"' in out and "export EDITOR=vim" in out


def test_fish_config_is_swept(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    fish = tmp_path / ".config" / "fish" / "config.fish"; fish.parent.mkdir(parents=True)
    fish.write_text("set -g fish_greeting\n# Nunmai Engine — ensure ~/.local/bin is on PATH\nfish_add_path $HOME/.local/bin\n")
    assert fish in u.find_shell_configs()
    u.remove_path_from_shell_configs()
    assert "fish_add_path" not in fish.read_text() and "fish_greeting" in fish.read_text()
