"""Live Windows probe: pre-suffix gateway launchers are reported by ``status`` and removed by
``uninstall`` (#116157).

Runs only on real Windows (the on-demand ``wine2e/**`` windows-latest lane). It registers a REAL
Scheduled Task named ``Nunmai_Gateway`` (harmless action) plus a pre-suffix Startup entry under a
temp APPDATA, then drives the production ``status()`` / ``uninstall()`` against ``schtasks.exe``.
"""

import shutil
import subprocess

import pytest

import nunmai_cli.gateway_windows as gateway_windows


@pytest.mark.windows_only
def test_status_warns_and_uninstall_removes_pre_suffix_launchers(tmp_path, monkeypatch, capsys):
    home = tmp_path / "nunmai"
    (home / "gateway-service").mkdir(parents=True)
    monkeypatch.setenv("NUNMAI_HOME", str(home))
    appdata = tmp_path / "AppData" / "Roaming"
    startup = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    startup.mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(gateway_windows, "_gateway_pids", lambda *a, **k: [])
    monkeypatch.setattr(gateway_windows, "_print_start_attestation_warning", lambda: None)

    current = gateway_windows.get_task_name()
    assert current != "Nunmai_Gateway", "a temp home must carry a profile suffix"
    legacy_pair = home / "gateway-service" / "Nunmai_Gateway.vbs"
    legacy_pair.write_text("' pre-suffix launcher\r\n", encoding="utf-8")
    # Both objects must point INTO this home: a bare-named task/entry targeting another home is a
    # sibling install (the default profile's live gateway) and is deliberately left alone.
    legacy_vbs = startup / "Nunmai_Gateway.vbs"
    legacy_vbs.write_text(gateway_windows._build_startup_launcher(legacy_pair.with_suffix(".cmd")), encoding="utf-8")

    schtasks = shutil.which("schtasks") or "schtasks"
    create = subprocess.run(
        [schtasks, "/Create", "/F", "/TN", "Nunmai_Gateway", "/SC", "ONLOGON", "/TR", f"wscript.exe //B {legacy_pair}"],
        capture_output=True, text=True, timeout=60,
    )
    assert create.returncode == 0, create.stderr
    try:
        gateway_windows.status()
        out = capsys.readouterr().out
        assert "legacy pre-suffix Scheduled Task still installed: Nunmai_Gateway" in out
        assert f"legacy pre-suffix Windows login item still installed: {legacy_vbs}" in out
        assert f"legacy pre-suffix task launcher still installed: {legacy_pair}" in out
        assert "nunmai gateway uninstall" in out

        gateway_windows.uninstall()
        out = capsys.readouterr().out
        assert "Removed legacy pre-suffix Scheduled Task 'Nunmai_Gateway'" in out
        assert not legacy_vbs.exists()
        assert not legacy_pair.exists()
        query = subprocess.run([schtasks, "/Query", "/TN", "Nunmai_Gateway"], capture_output=True, text=True, timeout=60)
        assert query.returncode != 0, "the pre-suffix task must be gone after uninstall"

        gateway_windows.status()
        assert "legacy pre-suffix" not in capsys.readouterr().out
    finally:
        subprocess.run([schtasks, "/Delete", "/F", "/TN", "Nunmai_Gateway"], capture_output=True, text=True, timeout=60)
