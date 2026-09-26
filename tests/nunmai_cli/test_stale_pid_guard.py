# -*- coding: utf-8 -*-
"""Regression tests for the fail-closed PID-ownership guard.

Refs #90471 / #89614.  The three patched Windows ``taskkill`` boundaries:

- ``nunmai_cli/_subprocess_compat.pid_is_nunmai`` / ``kill_process_tree``
- ``nunmai_cli/dashboard_procs._kill_stale_dashboard_processes`` (win32)
- ``nunmai_cli/update_cmd._stop_process_trees``

Acceptance from #90471:
1. missing / unreadable / non-matching identity fails closed -> no taskkill
2. a recycled or foreign PID control process remains untouched
3. probe failure or timeout is never converted into permission to kill
"""
import sys
from pathlib import Path
from unittest import mock

import pytest

from nunmai_cli import _subprocess_compat
from nunmai_cli import dashboard_procs
from nunmai_cli import update_cmd


def _probe_stdout(value: str) -> mock.Mock:
    return mock.Mock(stdout=value)


class TestPidIsNunmai:
    """The shared identity probe must fail closed on every ambiguity."""

    def test_non_windows_is_unconditional_pass(self):
        # Non-Windows callers have no taskkill path at all.
        with mock.patch.object(_subprocess_compat, "IS_WINDOWS", False):
            assert _subprocess_compat.pid_is_nunmai(1234) is True

    def test_non_windows_still_rejects_recycled_identity(self):
        # An explicit fingerprint mismatch is a recycled PID on any platform.
        with mock.patch.object(_subprocess_compat, "IS_WINDOWS", False), mock.patch.object(
            _subprocess_compat, "_process_start_time", return_value=456
        ):
            assert _subprocess_compat.pid_is_nunmai(
                1234, expected_start_time=123
            ) is False

    def test_nunmai_match_requires_token_boundary(self):
        # "nunmai" buried inside an unrelated path segment must not match.
        assert _subprocess_compat._text_names_nunmai(
            r"c:\users\snunmaia\app.exe"
        ) is False
        assert _subprocess_compat._text_names_nunmai(
            r"C:\Users\x\.nunmai-runtime\python.exe -m nunmai_cli.main"
        ) is True
        assert _subprocess_compat._text_names_nunmai(
            "/opt/nunmai-engine/venv/bin/python"
        ) is True

    @pytest.mark.windows_only
    def test_invalid_pid_inputs_do_not_crash(self):
        with mock.patch.object(_subprocess_compat, "IS_WINDOWS", True):
            assert _subprocess_compat.pid_is_nunmai(-1) is False
            assert _subprocess_compat.pid_is_nunmai(0) is False
            assert _subprocess_compat.pid_is_nunmai("not-a-pid") is False
            assert _subprocess_compat.pid_is_nunmai(True) is False

    @pytest.mark.windows_only
    def test_probe_matches_nunmai_like_process(self):
        with mock.patch.object(_subprocess_compat, "IS_WINDOWS", True), mock.patch.object(
            _subprocess_compat, "_process_start_time", return_value=123
        ), mock.patch.object(
            _subprocess_compat, "_process_command_is_nunmai", return_value=True
        ):
            assert _subprocess_compat.pid_is_nunmai(1234) is True

    @pytest.mark.windows_only
    def test_probe_rejects_recycled_process_identity(self):
        with mock.patch.object(_subprocess_compat, "IS_WINDOWS", True), mock.patch.object(
            _subprocess_compat, "_process_start_time", return_value=456
        ), mock.patch.object(
            _subprocess_compat, "_process_command_is_nunmai", return_value=True
        ):
            assert _subprocess_compat.pid_is_nunmai(
                1234, expected_start_time=123
            ) is False

    @pytest.mark.windows_only
    def test_probe_rejects_foreign_process(self):
        with mock.patch.object(_subprocess_compat, "IS_WINDOWS", True), mock.patch.object(
            _subprocess_compat, "_process_start_time", return_value=123
        ), mock.patch.object(
            _subprocess_compat, "_process_command_is_nunmai", return_value=False
        ):
            assert _subprocess_compat.pid_is_nunmai(1234) is False

    @pytest.mark.windows_only
    def test_probe_blank_stdout_fails_closed(self):
        with mock.patch.object(_subprocess_compat, "IS_WINDOWS", True), mock.patch.object(
            _subprocess_compat, "_process_start_time", return_value=None
        ):
            assert _subprocess_compat.pid_is_nunmai(1234) is False


    @pytest.mark.windows_only
    def test_probe_oserror_fails_closed(self):
        with mock.patch.object(_subprocess_compat, "IS_WINDOWS", True), mock.patch.object(
            _subprocess_compat, "_process_start_time", side_effect=OSError("broken pipe")
        ):
            assert _subprocess_compat.pid_is_nunmai(1234) is False

    @pytest.mark.windows_only
    def test_missing_pid_real_probe_fails_closed(self):
        # A PID that cannot exist must never be judged Nunmai-owned.
        assert _subprocess_compat.pid_is_nunmai(2**24) is False


class TestKillProcessTree:
    """kill_process_tree operates on our own retained Popen handle.

    A retained handle pins the PID (the child cannot be reaped while the
    handle is open), so PID recycling is impossible there and the identity
    guard deliberately does NOT apply — it could only false-refuse a
    legitimate cleanup. These tests pin that contract for the legacy
    Windows fallback path.
    """

    def _proc(self, pid=4321):
        return mock.Mock(pid=pid)

    @pytest.mark.windows_only
    def test_retained_handle_is_taskkilled_without_probe(self):
        with mock.patch.object(_subprocess_compat, "IS_WINDOWS", True), mock.patch.object(
            _subprocess_compat, "pid_is_nunmai"
        ) as guard, mock.patch.object(_subprocess_compat.subprocess, "run") as run:
            _subprocess_compat._legacy_kill_process_tree(self._proc())
            guard.assert_not_called()
            run.assert_called_once()
            argv = run.call_args.args[0]
            assert argv[0] == "taskkill"
            assert "/PID" in argv
            assert str(4321) in argv


class TestStopProcessTrees:
    """update_cmd._stop_process_trees guard behaviour."""

    def test_foreign_pids_only_probed(self):
        with mock.patch(
            "gateway.status.get_process_start_time", return_value=123
        ), mock.patch(
            "nunmai_cli._subprocess_compat.pid_is_nunmai", return_value=False
        ), mock.patch.object(update_cmd.subprocess, "run") as run:
            update_cmd._stop_process_trees([1111, 2222])
        run.assert_not_called()

    def test_nunmai_pid_probed_then_taskkilled(self):
        with mock.patch(
            "gateway.status.get_process_start_time", return_value=123
        ), mock.patch(
            "nunmai_cli._subprocess_compat.pid_is_nunmai", return_value=True
        ), mock.patch.object(
            update_cmd.subprocess, "run", return_value=mock.Mock(returncode=0)
        ) as run:
            update_cmd._stop_process_trees([1111])
        assert len(run.call_args_list) == 1
        assert run.call_args.args[0][0] == "taskkill"



class TestKillStaleDashboardProcesses:
    """dashboard_procs win32 kill branch guard behaviour."""

    def _patch_find(self, pids=(12345,)):
        from nunmai_cli import main_dashboard

        return mock.patch.object(main_dashboard, "_find_stale_dashboard_pids", return_value=list(pids))

    @pytest.mark.windows_only
    def test_foreign_pid_reported_not_killed(self):
        with self._patch_find(), mock.patch.object(
            dashboard_procs.sys, "platform", "win32"
        ), mock.patch(
            "gateway.status.get_process_start_time", return_value=123
        ), mock.patch(
            "nunmai_cli._subprocess_compat.pid_is_nunmai", return_value=False
        ), mock.patch.object(dashboard_procs.subprocess, "run") as run:
            result = dashboard_procs._kill_stale_dashboard_processes()
        assert result["killed"] == []
        assert result["failed"] == [
            (12345, "not nunmai-owned or process identity changed")
        ]
        run.assert_not_called()

    @pytest.mark.windows_only
    def test_nunmai_pid_killed(self):
        with self._patch_find(), mock.patch.object(
            dashboard_procs.sys, "platform", "win32"
        ), mock.patch(
            "gateway.status.get_process_start_time", return_value=123
        ), mock.patch(
            "nunmai_cli._subprocess_compat.pid_is_nunmai", return_value=True
        ), mock.patch.object(
            dashboard_procs.subprocess, "run", return_value=mock.Mock(
                returncode=0, stderr="", stdout=""
            )
        ) as run:
            result = dashboard_procs._kill_stale_dashboard_processes()
        taskkill_calls = [c for c in run.call_args_list if c.args[0][0] == "taskkill"]
        assert len(taskkill_calls) == 1
        assert result["killed"] == [12345]
        assert result["failed"] == []

    def test_stop_only_targets_the_invoking_nunmai_home(self, monkeypatch):
        """An argv match from another profile is never a ``--stop`` target."""
        own_home = "/tmp/nunmai-own"
        foreign_home = "/tmp/nunmai-foreign"
        monkeypatch.setenv("NUNMAI_HOME", own_home)

        with mock.patch.object(
            dashboard_procs, "_scan_dashboard_processes",
            return_value=[(12345, "nunmai serve"), (12346, "nunmai serve"), (12347, "nunmai serve")],
        ), mock.patch.object(dashboard_procs, "_caller_ancestor_pids", return_value=set()), mock.patch.object(
            dashboard_procs, "_nunmai_home_for_pid",
            side_effect=lambda pid: {
                12345: own_home,
                12346: foreign_home,
                12347: None,
            }[pid],
        ), mock.patch.object(
            dashboard_procs, "_kill_pids_posix"
        ) as kill:
            result = dashboard_procs._kill_stale_dashboard_processes(scope_home=own_home)

        kill.assert_called_once()
        assert kill.call_args.args[0] == [12345]
        assert result["matched"] == [12345]


class TestNunmaiHomeForPid:
    """Tri-state owner resolution: a readable environment always names a home."""

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX default home is $HOME/.nunmai")
    def test_readable_env_without_var_resolves_to_that_process_default_home(self, monkeypatch, tmp_path):
        """The common install shape exports no NUNMAI_HOME: the backend lives in its user's
        platform default home, and a default-home ``--stop`` must still find it (#113978)."""
        home = str(tmp_path / "alice")
        monkeypatch.setattr(dashboard_procs, "_pid_environ", lambda pid: {"HOME": home})
        from nunmai_cli import main_dashboard
        monkeypatch.setattr(main_dashboard, "_dashboard_cmdline_for_pid",
                            lambda pid: ["nunmai", "--profile", "work", "serve"] if pid == 2 else ["nunmai", "serve"])

        assert dashboard_procs._nunmai_home_for_pid(1) == f"{home}/.nunmai"
        # ``-p``/``--profile`` is applied to os.environ after exec, invisible in /proc environ.
        assert dashboard_procs._nunmai_home_for_pid(2) == f"{home}/.nunmai/profiles/work"
        assert dashboard_procs._pids_owned_by_nunmai_home([1, 2], f"{home}/.nunmai") == [1]

    # REGRESSION (#116906): a systemd/launchd unit with a scrubbed environment exports no HOME.
    # The target resolves its own default home from the password database, so attributing it to
    # the INSPECTING process's home named another user's directory — and `nunmai update` /
    # `--stop` then acted on the wrong profile root.
    def _posix_scrubbed_unit(self, monkeypatch, tmp_path, passwd_home):
        """A unit whose environment carries neither HOME nor NUNMAI_HOME, on the POSIX branch."""
        monkeypatch.setattr(dashboard_procs.sys, "platform", "linux")
        monkeypatch.setattr(dashboard_procs, "_pid_environ", lambda pid: {})
        monkeypatch.setattr(dashboard_procs, "_pid_passwd_home", lambda pid: passwd_home)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "inspecting-user"))
        from nunmai_cli import main_dashboard
        monkeypatch.setattr(main_dashboard, "_dashboard_cmdline_for_pid", lambda pid: ["nunmai", "serve"])

    def test_scrubbed_unit_env_resolves_to_the_owners_passwd_home(self, monkeypatch, tmp_path):
        service_home = tmp_path / "nunmai-service"
        self._posix_scrubbed_unit(monkeypatch, tmp_path, str(service_home))

        assert Path(dashboard_procs._nunmai_home_for_pid(1)) == service_home / ".nunmai"

    def test_unreadable_passwd_entry_keeps_the_existing_fallback(self, monkeypatch, tmp_path):
        """No owner, no entry: the previous behaviour stands rather than resolving to nothing."""
        self._posix_scrubbed_unit(monkeypatch, tmp_path, None)

        assert Path(dashboard_procs._nunmai_home_for_pid(1)) == tmp_path / "inspecting-user" / ".nunmai"

    def test_root_shaped_nunmai_home_follows_the_flag_and_the_sticky_active_profile(self, monkeypatch, tmp_path):
        """Mirror ``_apply_profile_override``: an exported root ``NUNMAI_HOME`` is the root, not the
        home — ``-p work`` and ``nunmai profile use work`` both land in ``<root>/profiles/work``."""
        root = tmp_path / ".nunmai"
        root.mkdir()
        monkeypatch.setattr(dashboard_procs, "_pid_environ",
                            lambda pid: {"HOME": str(tmp_path), "NUNMAI_HOME": str(root)})
        from nunmai_cli import main_dashboard
        monkeypatch.setattr(main_dashboard, "_dashboard_cmdline_for_pid",
                            lambda pid: ["nunmai", "-p", "work", "serve"] if pid == 2 else ["nunmai", "serve"])

        assert dashboard_procs._nunmai_home_for_pid(2) == str(root / "profiles" / "work")
        assert dashboard_procs._nunmai_home_for_pid(1) == str(root)  # no flag, no active_profile
        (root / "active_profile").write_text("work", encoding="utf-8")
        assert dashboard_procs._nunmai_home_for_pid(1) == str(root / "profiles" / "work")
        # A profile-shaped NUNMAI_HOME without a flag is the home itself (root = its grandparent).
        monkeypatch.setattr(dashboard_procs, "_pid_environ",
                            lambda pid: {"NUNMAI_HOME": str(root / "profiles" / "ops")})
        assert dashboard_procs._nunmai_home_for_pid(1) == str(root / "profiles" / "ops")

    def test_unreadable_env_is_none_and_spared(self, monkeypatch):
        monkeypatch.setattr(dashboard_procs, "_pid_environ", lambda pid: None)
        assert dashboard_procs._nunmai_home_for_pid(7) is None
        assert dashboard_procs._pids_owned_by_nunmai_home([7], "/home/alice/.nunmai") == []
