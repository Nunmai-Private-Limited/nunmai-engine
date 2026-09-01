"""Regression tests: dependency install scripts are blocked by default.

An npm install script is arbitrary code executed at install time. package.json
has long carried an ``allowScripts`` map naming which packages may run one —
but that is a LavaMoat convention and nothing in the install path honoured it,
so the block was dead config and every script ran.

The visible symptom was ``unicode-animations``, whose postinstall prints a
3-second animated advert. It opens /dev/tty directly, so install.sh's output
capture cannot suppress it and it scribbles over the installer's own output.

install.sh now installs with --ignore-scripts and re-runs only the allowed
entries via ``npm rebuild``. The allowed list is derived from package.json at
run time rather than hardcoded, so the two cannot drift apart.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"
SITE_INSTALL_SH = REPO_ROOT / "deploy" / "installer-site" / "public" / "install.sh"
PACKAGE_JSON = REPO_ROOT / "package.json"
PACKAGE_LOCK = REPO_ROOT / "package-lock.json"


def _base(spec: str) -> str:
    """'esbuild@0.28.1' -> 'esbuild'; '@scope/x@1.0.0' -> '@scope/x'."""
    return "@" + spec[1:].split("@")[0] if spec.startswith("@") else spec.split("@")[0]


class TestInstallShBlocksScripts:
    def test_npm_install_uses_ignore_scripts(self) -> None:
        text = INSTALL_SH.read_text()
        assert "npm install --silent --ignore-scripts" in text

    def test_allowed_scripts_are_rebuilt(self) -> None:
        text = INSTALL_SH.read_text()
        assert "run_allowed_install_scripts() {" in text
        assert "npm rebuild --silent" in text
        # Called from the node-deps stage, and its failure aborts the install.
        assert "if ! run_allowed_install_scripts; then" in text

    def test_rebuild_failure_is_fatal(self) -> None:
        """A native module that fails to build leaves the TUI broken, so it
        must fail the install rather than print a success line (#85297)."""
        text = INSTALL_SH.read_text()
        idx = text.index("run_allowed_install_scripts() {")
        body = text[idx:idx + 2000]
        assert 'log_error "npm rebuild failed for:' in body
        assert "return 1" in body

    def test_undeclared_install_scripts_are_reported(self) -> None:
        """A new dependency with an install script stays blocked (safe), but
        must be named — silently skipping a native build would surface much
        later as a mysterious runtime failure."""
        text = INSTALL_SH.read_text()
        assert "warn_undeclared_install_scripts() {" in text
        assert "missing from package.json allowScripts" in text

    def test_served_installer_matches_canonical(self) -> None:
        """public/install.sh is a generated copy; a stale one means users curl
        an installer without this fix."""
        assert SITE_INSTALL_SH.read_text() == INSTALL_SH.read_text()


class TestAllowScriptsManifest:
    def test_every_scripted_dependency_is_declared(self) -> None:
        """allowScripts must cover every package the lockfile marks as having
        an install script. An undeclared native module would be silently left
        unbuilt."""
        lock = json.loads(PACKAGE_LOCK.read_text())
        allow = json.loads(PACKAGE_JSON.read_text()).get("allowScripts", {})
        declared = {_base(k) for k in allow}
        scripted = {
            path.split("node_modules/")[-1]
            for path, meta in (lock.get("packages") or {}).items()
            if path and meta.get("hasInstallScript")
        }
        assert scripted - declared == set(), (
            f"undeclared packages with install scripts: {sorted(scripted - declared)}"
        )

    def test_the_advert_postinstall_stays_blocked(self) -> None:
        allow = json.loads(PACKAGE_JSON.read_text()).get("allowScripts", {})
        assert allow.get("unicode-animations") is False

    def test_native_builds_stay_allowed(self) -> None:
        """These carry real build steps; blocking one breaks the TUI or the
        desktop app."""
        allow = json.loads(PACKAGE_JSON.read_text()).get("allowScripts", {})
        enabled = {_base(k) for k, v in allow.items() if v}
        for pkg in ("node-pty", "esbuild"):
            assert pkg in enabled
