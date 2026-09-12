"""Regression tests for #88235 — state.db corruption must surface a warning
to the user's messaging platform, not stay silently in the logs.

When SessionDB init fails at gateway startup (corruption, NFS/SMB locks,
disk errors), the gateway sets _session_db = None and logs a warning — but
the user never sees it.  Messages may flow but nothing is persisted, and the
user only discovers the breakage when /resume or session_search comes back
empty.

The fix adds:
1. _session_db_init_error attribute on GatewayRunner, set when init fails
2. _send_session_db_warning_notifications() — broadcasts a recovery-guidance
   message to all home channels after the gateway connects
3. Improved "corrupt" cause wording in _format_turn_completion_explanation
   with the full recovery path (nunmai doctor, sqlite3 .recover, backups)
"""

from pytest import fixture


def test_format_turn_completion_corrupt_includes_recovery_options():
    """The 'corrupt' persistence cause must list all recovery options."""
    from run_agent import AIAgent

    explanation = AIAgent._format_turn_completion_explanation(
        "session_persistence_failed", "corrupt"
    )
    assert "nunmai doctor" in explanation
    assert ".recover" in explanation
    assert "backups" in explanation
    assert "Freeing disk space will not help" in explanation


def test_gateway_corruption_banner_backups_dir_follows_nunmai_home(monkeypatch, tmp_path):
    """The gateway broadcast's step 3 must name the live backups dir, not ~/.nunmai (#104250).

    Pre-update backups live at ``<nunmai_root>/backups`` (``nunmai_cli/backup.py``); a
    custom-NUNMAI_HOME gateway must not be told to restore from a directory that never
    held its backups.
    """
    import asyncio

    import gateway.run as gateway_run

    custom_home = tmp_path / "custom-nunmai-home"
    monkeypatch.setenv("NUNMAI_HOME", str(custom_home / "profiles" / "research"))

    runner = object.__new__(gateway_run.GatewayRunner)
    runner._session_db_init_error = "database disk image is malformed"
    sent = []
    monkeypatch.setattr(
        runner, "_home_channel_transports", lambda: [("telegram", {}, "home-chat", object())]
    )

    async def _capture_send(_platform, _home, _transport, message, _log_fmt):
        sent.append(message)

    monkeypatch.setattr(runner, "_send_home_channel_message", _capture_send)
    asyncio.run(runner._send_session_db_warning_notifications())

    assert sent, "warning must be broadcast to home channels"
    assert f"{custom_home / 'backups'}" in sent[0]
    assert "~/.nunmai/backups" not in sent[0]


def test_format_turn_completion_corrupt_names_the_sessions_own_store(monkeypatch, tmp_path):
    """Recovery commands target the store that failed, not the process default (#105887).

    A Desktop ``serve`` backend launched on the root home hosts named-profile sessions
    whose SessionDB is ``profiles/<name>/state.db``; guidance built from the process
    default would tell the operator to inspect/repair the root database.
    """
    from run_agent import AIAgent

    root = tmp_path / "root"
    monkeypatch.setenv("NUNMAI_HOME", str(root))
    failing = root / "profiles" / "research" / "state.db"

    explanation = AIAgent._format_turn_completion_explanation(
        "session_persistence_failed", "corrupt", db_path=failing
    )
    assert f"--source {failing} --inspect-only" in explanation
    assert f"--source {root / 'state.db'}" not in explanation


def test_format_turn_completion_corrupt_never_names_the_live_db():
    """The 'corrupt' cause must not direct a raw sqlite3 shell at the live DB.

    #100368 forensics: the system sqlite3 CLI on Debian/Ubuntu (3.45.1/
    3.46.1, below the 3.51.x WAL-reset fix) unlinks the live WAL/SHM pair
    when pointed at a live state.db, splitting the store into two
    generations whose acknowledged writes vanish. The guidance that ships
    in the corruption banner must be the snapshot-copying
    `nunmai sessions recover` lane.
    """
    from run_agent import AIAgent

    explanation = AIAgent._format_turn_completion_explanation(
        "session_persistence_failed", "corrupt"
    )
    assert "sessions recover" in explanation
    assert 'sqlite3 ~/.nunmai/state.db ".recover"' not in explanation
    # The replacement guidance names the safe command.
    assert "nunmai sessions recover --source" in explanation


def test_format_turn_completion_disk_still_advises_space():
    """The 'disk' cause still gives disk-space advice (unchanged)."""
    from run_agent import AIAgent

    explanation = AIAgent._format_turn_completion_explanation(
        "session_persistence_failed", "disk"
    )
    assert "free some space" in explanation


def test_format_turn_completion_locked_still_advises_retry():
    """The 'locked' cause still advises retrying (unchanged)."""
    from run_agent import AIAgent

    explanation = AIAgent._format_turn_completion_explanation(
        "session_persistence_failed", "locked"
    )
    assert "busy" in explanation
    assert "send it again" in explanation


def test_corrupt_guidance_pins_the_failing_profile(tmp_path, monkeypatch):
    """#105887: every `nunmai ...` command in the recovery guidance (turn explainer, gateway
    home-channel notice, exhausted-repair diagnostic) carries the active profile selector and
    names that profile's state.db. A bare `nunmai` follows the sticky ``active_profile`` file,
    so with another profile active the operator would repair the wrong database."""
    import asyncio

    import gateway.run as gateway_run
    from nunmai_state import _default_db_path
    from nunmai_state_repair import _persistent_repair_exhausted_error
    from run_agent import AIAgent

    root = tmp_path / "nunmai"
    home = root / "profiles" / "research"
    home.mkdir(parents=True)
    (root / "config.yaml").write_text("")
    (root / "active_profile").write_text("other\n")
    monkeypatch.setenv("NUNMAI_HOME", str(home))

    explanation = AIAgent._format_turn_completion_explanation("session_persistence_failed", "corrupt")
    commands = [line.strip() for line in explanation.splitlines() if "nunmai " in line]
    assert commands and all("nunmai -p research " in line for line in commands), commands
    # The conftest pins nunmai_state.DEFAULT_DB_PATH, so the store named is whatever the
    # process resolves — the contract is "the same path the runtime would open".
    assert f"--source {_default_db_path()} " in explanation

    runner = object.__new__(gateway_run.GatewayRunner)
    runner._session_db_init_error = "database disk image is malformed"
    sent = []
    monkeypatch.setattr(runner, "_home_channel_transports", lambda: [("telegram", {}, "home-chat", object())])

    async def _capture_send(_platform, _home, _transport, message, _log_fmt):
        sent.append(message)

    monkeypatch.setattr(runner, "_send_home_channel_message", _capture_send)
    asyncio.run(runner._send_session_db_warning_notifications())
    notice_commands = [line.strip() for line in sent[0].splitlines() if "nunmai " in line]
    assert notice_commands and all("nunmai -p research " in line for line in notice_commands), notice_commands
    assert f"--source {_default_db_path()} " in sent[0]

    exhausted = _persistent_repair_exhausted_error(home / "state.db")
    assert "`nunmai -p research sessions recover --source" in exhausted
