"""Behavior-contract compatibility tests for native Nunmai plugins."""

from pathlib import Path
import shutil

import yaml

from nunmai_cli.plugins import PluginManager


LEGACY_PLUGIN = Path(__file__).parent / "fixtures" / "plugin_compat_legacy"


def test_legacy_plugin_loads_and_ignores_additive_hook_and_manifest_fields(
    tmp_path, monkeypatch
):
    """A frozen plugin keeps working as manifests and hook payloads grow."""
    nunmai_home = tmp_path / "nunmai-home"
    plugins_dir = nunmai_home / "plugins"
    plugins_dir.mkdir(parents=True)
    shutil.copytree(LEGACY_PLUGIN, plugins_dir / "legacy-contract-fixture")
    (nunmai_home / "config.yaml").write_text(
        yaml.safe_dump(
            {"plugins": {"enabled": ["legacy-contract-fixture"]}}
        ),
        encoding="utf-8",
    )
    empty_bundled = tmp_path / "bundled-plugins"
    empty_bundled.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "os-home"))
    monkeypatch.setenv("NUNMAI_HOME", str(nunmai_home))
    monkeypatch.setenv("NUNMAI_BUNDLED_PLUGINS", str(empty_bundled))

    manager = PluginManager()
    manager.discover_and_load()

    loaded = manager._plugins["legacy-contract-fixture"]
    assert loaded.enabled is True
    assert loaded.error is None
    assert loaded.module is not None
    assert loaded.manifest.version == "0.1.0"
    assert "on_session_start" in loaded.hooks_registered

    results = manager.invoke_hook(
        "on_session_start",
        session_id="legacy-session",
        resumed=True,
        future_additive_field={"nested": "value"},
    )

    assert results == [{"legacy_session_id": "legacy-session"}]
    assert loaded.module.received_sessions == ["legacy-session"]
