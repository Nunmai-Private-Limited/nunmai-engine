"""`nunmai uninstall` must hand the `nunmai` command back to the npm shim.

When the engine was installed through the `nunmai` npm package, install.sh
stamps `# nunmai-npm-shim: <path>` into the launcher. After uninstall the
launcher is replaced by a symlink to that shim, so `nunmai` (and a repeat
`npm install nunmai`, whose postinstall npm skips) reinstall instead of
failing with command-not-found.
"""
from pathlib import Path

import pytest

from nunmai_cli import uninstall as u


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    (tmp_path / ".local" / "bin").mkdir(parents=True)
    return tmp_path


def _write_launcher(home: Path, shim: "Path | None") -> Path:
    launcher = home / ".local" / "bin" / "nunmai"
    body = '#!/usr/bin/env bash\nexec "/x/nunmai-engine/venv/bin/python" "/x/nunmai-engine/nunmai" "$@"\n'
    if shim is not None:
        body += f"{u.NPM_SHIM_MARKER}{shim}\n"
    launcher.write_text(body)
    launcher.chmod(0o755)
    return launcher


def test_find_npm_shim_path_reads_marker(home):
    shim = home / "node_modules" / "nunmai" / "bin" / "nunmai.js"
    shim.parent.mkdir(parents=True)
    shim.write_text("// shim\n")
    _write_launcher(home, shim)
    assert u.find_npm_shim_path() == shim


def test_find_npm_shim_path_ignores_missing_shim(home):
    _write_launcher(home, home / "gone" / "nunmai.js")
    assert u.find_npm_shim_path() is None


def test_find_npm_shim_path_none_without_marker(home):
    _write_launcher(home, None)
    assert u.find_npm_shim_path() is None


def test_restore_relinks_launcher_and_keeps_path(home):
    shim = home / "node_modules" / "nunmai" / "bin" / "nunmai.js"
    shim.parent.mkdir(parents=True)
    shim.write_text("// shim\n")
    _write_launcher(home, shim)
    (home / ".zshrc").write_text("export FOO=1\n")

    found = u.find_npm_shim_path()
    assert u.remove_wrapper_script() == [home / ".local" / "bin" / "nunmai"]
    link = u.restore_npm_shim_launcher(found)

    assert link == home / ".local" / "bin" / "nunmai"
    assert link.is_symlink() and link.resolve() == shim.resolve()
    assert 'export PATH="$HOME/.local/bin:$PATH"' in (home / ".zshrc").read_text()
    # idempotent
    assert u.restore_npm_shim_launcher(found) == link
    assert (home / ".zshrc").read_text().count(".local/bin") == 1
