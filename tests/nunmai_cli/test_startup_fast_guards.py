"""Guards for nunmai_cli._startup_fast — the pre-import version fast path.

Two invariants, each of which has been broken before:

1. IMPORT WEIGHT: _startup_fast must stay stdlib-only. The whole point of
   the module is to run before main.py's heavy import wall; one careless
   ``from nunmai_cli.config import ...`` silently makes `nunmai --version`
   slow again for everyone (the regression would be invisible — everything
   still works, just 40x slower).

2. OUTPUT PARITY / LIVENESS: the fast path must actually produce version
   output and exit 0 in a real subprocess, on and off Termux. This is the
   test that would have caught eb4040242, which changed the canonical
   version output to reference the PROJECT_ROOT module constant inside the
   fast function — a name that doesn't exist yet at the fast exit point —
   NameError-ing the Termux fast path in production for weeks.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Modules that must NEVER be imported by the fast path. Each one either
# pulls yaml/argparse/logging config or is itself a god-module.
_FORBIDDEN_MODULES = (
    "nunmai_cli.config",
    "nunmai_cli.main",
    "yaml",
    "argparse",
    "cli",
    "run_agent",
    "model_tools",
    "httpx",
    "openai",
)


@pytest.mark.linux_only
def test_cli_starts_from_a_deleted_cwd(tmp_path):
    """A child spawned into a directory that was removed since (a cron delivery from a reaped
    kanban workspace) must still reach argv parsing: a relative ``sys.path`` entry made
    ``ensure_project_root_on_path`` die in ``realpath`` → ``getcwd`` (#102941)."""
    home = tmp_path / ".nunmai"
    home.mkdir()
    gone = tmp_path / "scratch"
    gone.mkdir()
    # The child needs the checkout on sys.path by absolute name; the cwd is exactly what is gone.
    env = {**os.environ, "NUNMAI_HOME": str(home), "TERMUX_VERSION": "",
           "PYTHONPATH": os.pathsep.join(p for p in (str(REPO_ROOT), os.environ.get("PYTHONPATH")) if p)}
    env.pop("NUNMAI_DEV", None)
    fd = os.open(gone, os.O_RDONLY)
    try:
        gone.rmdir()
        # ``cwd=`` of a removed path is refused by Popen, so start in the dead dir via a
        # preexec fchdir onto its still-open handle — the shape a reaped workspace leaves behind.
        result = subprocess.run(
            [sys.executable, "-m", "nunmai_cli.main", "--version"],
            capture_output=True, text=True, timeout=60, env=env,
            cwd=REPO_ROOT, preexec_fn=lambda: os.fchdir(fd))
    finally:
        os.close(fd)
    assert result.returncode == 0, result.stderr
    assert "Nunmai Engine v" in result.stdout
    assert "FileNotFoundError" not in result.stderr


def test_startup_fast_import_weight():
    """Importing _startup_fast must not drag in any heavy module."""
    probe = (
        "import sys, json\n"
        "import nunmai_cli._startup_fast\n"
        "print(json.dumps(sorted(sys.modules.keys())))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    loaded = set(json.loads(result.stdout))
    offenders = [m for m in _FORBIDDEN_MODULES if m in loaded]
    assert not offenders, (
        f"nunmai_cli._startup_fast imported heavy modules: {offenders} — "
        "the fast path must stay stdlib-only (see module docstring)."
    )


def _run_version(env_overrides: dict) -> subprocess.CompletedProcess:
    env = {**os.environ, **env_overrides}
    env.pop("NUNMAI_DEV", None)
    return subprocess.run(
        [sys.executable, "-m", "nunmai_cli.main", "--version"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO_ROOT,
        env=env,
    )




def test_fast_version_parity_on_termux(tmp_path):
    """The historical Termux path — the one eb4040242 broke."""
    home = tmp_path / ".nunmai"
    home.mkdir()
    result = _run_version(
        {"NUNMAI_HOME": str(home), "TERMUX_VERSION": "0.118"}
    )
    assert result.returncode == 0, result.stderr
    assert "Nunmai Engine v" in result.stdout
    assert "Traceback" not in result.stderr


def test_fast_version_reports_install_method_stamp(tmp_path):
    home = tmp_path / ".nunmai"
    home.mkdir()
    (home / ".install_method").write_text("git\n", encoding="utf-8")
    result = _run_version({"NUNMAI_HOME": str(home), "TERMUX_VERSION": ""})
    assert result.returncode == 0, result.stderr
    assert "Install method: git" in result.stdout


def test_literal_tilde_nunmai_home_expands_before_any_reader(tmp_path):
    """A literal ``~`` in NUNMAI_HOME (fish, or any quoted value) is expanded at process entry.

    Before the fix ``Path("~/.x")`` was relative, so the real CLI resolved it against cwd and
    scaffolded a full home under ``<cwd>/~/.x``. The negative assertion on cwd is the
    reporter's own acceptance criterion.
    """
    fake_home = tmp_path / "home"
    cwd = tmp_path / "project"
    fake_home.mkdir()
    cwd.mkdir()
    env = {**os.environ, "HOME": str(fake_home), "USERPROFILE": str(fake_home), "NUNMAI_HOME": "~/.x"}
    env.pop("NUNMAI_DEV", None)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-m", "nunmai_cli.main", "config", "path"],
        capture_output=True, text=True, timeout=120, cwd=cwd, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(fake_home / ".x" / "config.yaml")
    assert not (cwd / "~").exists(), sorted(p.name for p in cwd.iterdir())

    # Raw-reader observable: the ~30 ``os.environ["NUNMAI_HOME"]`` readers in nunmai_cli/ never
    # call the resolver, so the entry-point hunk in main.py (not nunmai_constants) must have
    # rewritten the env var by the time the module import finishes.
    probe = subprocess.run(
        [sys.executable, "-c", "import nunmai_cli.main, os; print(os.environ['NUNMAI_HOME'])"],
        capture_output=True, text=True, timeout=120, cwd=cwd, env=env,
    )
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == str(fake_home / ".x")


def test_normalize_nunmai_home_env_rewrites_tilde_and_leaves_absolute_alone(tmp_path, monkeypatch):
    from nunmai_cli import _startup_fast

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("NUNMAI_HOME", "~/.x")
    _startup_fast.normalize_nunmai_home_env()
    assert os.environ["NUNMAI_HOME"] == str(tmp_path / ".x")

    monkeypatch.setenv("NUNMAI_HOME", str(tmp_path / "abs"))
    _startup_fast.normalize_nunmai_home_env()
    assert os.environ["NUNMAI_HOME"] == str(tmp_path / "abs")

    monkeypatch.delenv("NUNMAI_HOME")
    _startup_fast.normalize_nunmai_home_env()
    assert "NUNMAI_HOME" not in os.environ
