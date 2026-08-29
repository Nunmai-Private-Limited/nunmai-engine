"""``preflight_node_toolchain``: swap an incompatible system node/npm for the
managed runtime BEFORE running npm (same rules as the installer's check_node),
so a lightweight install never shows the EBADENGINE wall on first use."""

from __future__ import annotations

import pytest

from nunmai_cli import npm_engine as ne

pytestmark = pytest.mark.real_node_preflight


@pytest.mark.parametrize(
    "version,ok",
    [
        ("v22.22.0", True), ("v22.21.9", False), ("v24.11.0", True), ("v24.10.5", False),
        ("v26.0.0", True), ("v27.1.0", True), ("v25.8.1", False), ("v20.19.0", False),
        ("v26.0.0-nightly", False), ("", False), (None, False), ("garbage", False),
    ],
)
def test_node_satisfies_build(version, ok):
    assert ne.node_satisfies_build(version) is ok


@pytest.mark.parametrize(
    "version,ok",
    [("11.9.9", True), ("11.10.0", False), ("11.11.0", False), ("11.16.9", False),
     ("11.17.0", True), ("12.0.2", True), ("10.9.0", True), (None, False)],
)
def test_npm_supports_npmrc(version, ok):
    assert ne.npm_supports_npmrc(version) is ok


def _npm_file(tmp_path):
    f = tmp_path / "npm"
    f.write_text("#!/bin/sh\n", encoding="utf-8")
    return str(f)


def _wire(monkeypatch, *, node, npm, managed_prefix=None, provisioned="/managed/npm"):
    monkeypatch.setattr(ne, "_probe_node_version", lambda _npm: node)
    monkeypatch.setattr(ne, "_probe_version", lambda _npm: npm)
    monkeypatch.setattr(ne, "managed_npm_prefix", lambda _npm: managed_prefix)
    calls = []

    def fake_provision(npm_range, *, quiet=False):
        calls.append(npm_range)
        return provisioned

    monkeypatch.setattr(ne, "_provision_managed_npm", fake_provision)
    monkeypatch.setattr(ne, "_repo_npm_range", lambda: "<11.10.0 || >=11.17.0")
    return calls


def test_compatible_system_toolchain_is_kept(monkeypatch, tmp_path):
    calls = _wire(monkeypatch, node="v22.23.2", npm="12.0.2")
    npm = _npm_file(tmp_path)
    assert ne.preflight_node_toolchain(npm, quiet=True) == npm
    assert calls == []


def test_non_lts_node_is_swapped_for_managed_runtime(monkeypatch, capsys, tmp_path):
    calls = _wire(monkeypatch, node="v25.8.1", npm="11.11.0")
    assert ne.preflight_node_toolchain(_npm_file(tmp_path)) == "/managed/npm"
    assert calls == ["<11.10.0 || >=11.17.0"]
    assert "outside the supported range" in capsys.readouterr().out


def test_bad_npm_band_alone_is_swapped(monkeypatch, capsys, tmp_path):
    _wire(monkeypatch, node="v24.11.0", npm="11.12.0")
    assert ne.preflight_node_toolchain(_npm_file(tmp_path)) == "/managed/npm"
    assert "cannot read this checkout's .npmrc" in capsys.readouterr().out


def test_unprobeable_versions_keep_npm_for_reactive_repair(monkeypatch, tmp_path):
    calls = _wire(monkeypatch, node=None, npm="11.11.0")
    npm = _npm_file(tmp_path)
    assert ne.preflight_node_toolchain(npm, quiet=True) == npm
    assert calls == []


def test_managed_npm_is_trusted_as_is(monkeypatch, tmp_path):
    calls = _wire(monkeypatch, node="v25.8.1", npm="11.11.0", managed_prefix=str(tmp_path))
    npm = _npm_file(tmp_path)
    assert ne.preflight_node_toolchain(npm, quiet=True) == npm
    assert calls == []


def test_stub_or_bare_command_is_not_probed(monkeypatch):
    calls = _wire(monkeypatch, node="v25.8.1", npm="11.11.0")
    assert ne.preflight_node_toolchain("npm", quiet=True) == "npm"
    assert ne.preflight_node_toolchain("/fake/does/not/exist/npm", quiet=True).endswith("npm")
    assert calls == []


def test_failed_provisioning_falls_back_to_original_npm(monkeypatch, tmp_path):
    _wire(monkeypatch, node="v25.8.1", npm="11.11.0", provisioned=None)
    npm = _npm_file(tmp_path)
    assert ne.preflight_node_toolchain(npm, quiet=True) == npm


def test_install_uses_preflighted_npm(monkeypatch, tmp_path):
    import subprocess
    import nunmai_cli.main as main_mod

    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    seen = []

    def fake_run(cmd, *, cwd, env, capture_output):
        seen.append((cmd[0], env.get("PATH", "")))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(main_mod, "_run_npm_watching_for_engine_failure", fake_run)
    monkeypatch.setattr(
        "nunmai_cli.npm_engine.preflight_node_toolchain", lambda npm, quiet=False: "/managed/bin/npm"
    )
    main_mod._run_npm_install_deterministic("/opt/homebrew/bin/npm", tmp_path)
    assert seen and seen[0][0] == "/managed/bin/npm"
