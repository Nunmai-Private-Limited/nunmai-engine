"""EBADENGINE from ``npm ci`` must not be retried as ``npm install``.

With the checkout's ``engine-strict=true``, a node/npm outside
``package.json`` ``engines`` fails both commands with the identical error
wall.  ``_run_npm_install_deterministic`` used to run both before handing the
failure to the managed-runtime repair, so users saw the wall twice
(``nunmai update`` on a host with a non-LTS Node, 2026-08-29).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import nunmai_cli.main as main_mod

_EBADENGINE = (
    "npm error code EBADENGINE\n"
    "npm error engine Unsupported engine\n"
    'npm error notsup Required: {"node":"^22.22.0 || ^24.11.0 || >=26.0.0","npm":"<11.10.0 || >=11.17.0"}\n'
    'npm error notsup Actual:   {"node":"v25.8.1","npm":"11.11.0"}\n'
)


def _wire(monkeypatch, tmp_path: Path, stderr: str):
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(cmd, *, cwd, env, capture_output):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=stderr)

    monkeypatch.setattr(main_mod, "_run_npm_watching_for_engine_failure", fake_run)
    monkeypatch.setattr(
        "nunmai_cli.npm_engine.maybe_repair_npm_engine", lambda *a, **k: None
    )
    return calls


def test_engine_failure_skips_the_npm_install_fallback(monkeypatch, tmp_path):
    calls = _wire(monkeypatch, tmp_path, _EBADENGINE)

    result = main_mod._run_npm_install_deterministic("npm", tmp_path)

    assert result.returncode == 1
    assert [c[1] for c in calls] == ["ci"], calls


def test_other_ci_failures_still_fall_back_to_npm_install(monkeypatch, tmp_path):
    calls = _wire(monkeypatch, tmp_path, "npm error code EUSAGE\nlockfile out of sync\n")

    main_mod._run_npm_install_deterministic("npm", tmp_path)

    assert [c[1] for c in calls] == ["ci", "install"], calls
