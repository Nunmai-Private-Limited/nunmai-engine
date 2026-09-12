from pathlib import Path


def test_windows_native_install_path_docs_match_installer() -> None:
    doc = Path("website/docs/user-guide/windows-native.md").read_text()
    install = Path("scripts/install.ps1").read_text()

    # The launchers live in the managed binary dir OUTSIDE the git checkout
    # (NUNMAI_HOME\bin, next to the managed uv) — NOT the whole venv\Scripts
    # (which would shadow the user's python, #83797) and NOT a dir inside
    # the checkout (which `nunmai update`'s autostash swept off disk).
    assert "%LOCALAPPDATA%\\nunmai\\bin" in doc
    assert (
        "Get-Command nunmai        # should print "
        "C:\\Users\\<you>\\AppData\\Local\\nunmai\\bin\\nunmai.exe"
    ) in doc
    # Installer exposes $NunmaiHome\bin, and must copy the launchers into it.
    assert '$nunmaiBin = "$NunmaiHome\\bin"' in install
    assert "nunmai.exe" in install and "nunmai-acp.exe" in install
    # Guard against regressions to either legacy layout.
    assert '$nunmaiBin = "$InstallDir\\venv\\Scripts"' not in install
    assert '$nunmaiBin = "$InstallDir\\bin"' not in install
