"""Regression: install.ps1 must never build a PATH over Windows' 32,767 limit.

``Sync-EnvPath`` ran before every stage and did a bare
``$env:Path = User + ";" + Machine``.  On machines with a bloated PATH
(corporate laptops, repeated installer runs) that assignment throws
"Environment variable name or value is too long" and the install died right
after Stage-Uv with no actionable message.

The fix routes every PATH string through ``Join-PathEntries`` (dedupe, drop
blanks, cap the in-process PATH) and ``Push-ProcessPath`` for session
prepends; the persisted User PATH is deduped but never truncated and fails
with a clear message instead.  Source-text contract, same style as the other
install.ps1 tests (the script only runs on Windows).
"""
import re
from pathlib import Path

_INSTALL_PS1 = Path(__file__).resolve().parents[1] / "scripts" / "install.ps1"


def _src() -> str:
    return _INSTALL_PS1.read_text(encoding="utf-8")


def test_join_path_entries_helper_exists_with_cap():
    src = _src()
    assert "function Join-PathEntries" in src
    assert "$script:MaxEnvValueLength = 32000" in src
    assert re.search(r"\[int\]\$MaxLength", src)


def test_sync_envpath_goes_through_join_path_entries():
    src = _src()
    body = re.search(r"function Sync-EnvPath \{(.*?)\n\}", src, re.S).group(1)
    assert "Join-PathEntries" in body
    assert "-MaxLength $script:MaxEnvValueLength" in body
    assert '+ ";" +' not in body


def test_no_raw_session_path_prepends_remain():
    # Every `$env:Path = "<dir>;$env:Path"` must be a Push-ProcessPath call.
    assert not re.search(r'\$env:Path\s*=\s*"[^"\n]*;\$env:Path"', _src())
    assert _src().count("Push-ProcessPath -Dir") >= 5


def test_persisted_user_path_is_deduped_and_never_truncated():
    src = _src()
    body = re.search(r"function Set-PathVariable \{(.*?)\n\}", src, re.S).group(1)
    assert "$newUserPath = Join-PathEntries" in body
    # No -MaxLength on the persisted write: the user's own entries are never dropped.
    assert not re.search(r"newUserPath = Join-PathEntries[^\n]*-MaxLength", body)
    assert "Windows allows at most 32,767" in body
