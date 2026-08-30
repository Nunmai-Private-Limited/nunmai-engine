"""
Nunmai Engine Uninstaller.

Provides options for:
- Full uninstall: Remove everything including configs and data
- Keep data: Remove code but keep ~/.nunmai/ (configs, sessions, logs)
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from nunmai_constants import get_nunmai_home

from nunmai_cli.colors import Colors, color

def log_info(msg: str):
    print(f"{color('→', Colors.CYAN)} {msg}")

def log_success(msg: str):
    print(f"{color('✓', Colors.GREEN)} {msg}")

def log_warn(msg: str):
    print(f"{color('⚠', Colors.YELLOW)} {msg}")

def get_project_root() -> Path:
    """Get the project installation directory."""
    return Path(__file__).parent.parent.resolve()


def find_shell_configs() -> list:
    """Find shell configuration files that might have PATH entries."""
    home = Path.home()
    configs = []
    
    candidates = [
        home / ".bashrc",
        home / ".bash_profile",
        home / ".profile",
        home / ".zshrc",
        home / ".zprofile",
    ]
    
    for config in candidates:
        if config.exists():
            configs.append(config)
    
    return configs


def remove_path_from_shell_configs():
    """Remove Nunmai PATH entries from shell configuration files."""
    configs = find_shell_configs()
    removed_from = []
    
    for config_path in configs:
        try:
            content = config_path.read_text(encoding="utf-8")
            original_content = content
            
            # Remove lines containing nunmai-engine or nunmai PATH entries
            new_lines = []
            skip_next = False
            
            for line in content.split('\n'):
                # Skip the "# Nunmai Engine" comment and following line
                if '# Nunmai Engine' in line or '# nunmai-engine' in line:
                    skip_next = True
                    continue
                if skip_next and ('nunmai' in line.lower() and 'PATH' in line):
                    skip_next = False
                    continue
                skip_next = False
                
                # Remove any PATH line containing nunmai
                if 'nunmai' in line.lower() and ('PATH=' in line or 'path=' in line.lower()):
                    continue
                    
                new_lines.append(line)
            
            new_content = '\n'.join(new_lines)
            
            # Clean up multiple blank lines
            while '\n\n\n' in new_content:
                new_content = new_content.replace('\n\n\n', '\n\n')
            
            if new_content != original_content:
                from utils import atomic_write_text

                # This is the user's own shell rc, not a Nunmai-owned file, and
                # nothing in this function backs it up. A bare write_text()
                # truncates it before the new content lands, so a crash or
                # SIGINT mid-write leaves the user with an empty or truncated
                # ~/.zshrc -- and the enclosing `except Exception` downgrades
                # that to a warning, so the next login just starts a bare
                # shell. atomic_replace also resolves a symlinked rc file, so a
                # dotfiles-repo setup keeps the symlink instead of having it
                # replaced by a regular file. preserve_mode keeps the rc's
                # permission bits (normally 0644) and owner (sudo-run
                # uninstalls) instead of mkstemp's 0600/root.
                atomic_write_text(config_path, new_content, preserve_mode=True)
                removed_from.append(config_path)
                
        except Exception as e:
            log_warn(f"Could not update {config_path}: {e}")
    
    return removed_from


NPM_SHIM_MARKER = "# nunmai-npm-shim: "


def find_npm_shim_path() -> "Path | None":
    """Return the npm bootstrap shim recorded in the ``nunmai`` launcher.

    scripts/install.sh stamps ``# nunmai-npm-shim: <path>`` into the launcher
    when the install was driven by the ``nunmai`` npm package. The shim is
    owned by npm (node_modules/nunmai/bin/nunmai.js), survives our uninstall,
    and reinstalls the engine on its next run — so it must become the
    ``nunmai`` command again once our launcher is gone.
    """
    for launcher in (Path.home() / ".local" / "bin" / "nunmai", Path("/usr/local/bin/nunmai")):
        try:
            if not launcher.is_file():
                continue
            for line in launcher.read_text(encoding="utf-8").splitlines():
                if line.startswith(NPM_SHIM_MARKER):
                    shim = Path(line[len(NPM_SHIM_MARKER):].strip())
                    if shim.is_file():
                        return shim
        except Exception:
            continue
    return None


def restore_npm_shim_launcher(shim: Path) -> "Path | None":
    """Point ``~/.local/bin/nunmai`` back at the npm shim and keep the dir on PATH.

    Runs after :func:`remove_wrapper_script` (launcher gone) and after
    :func:`remove_path_from_shell_configs` (our PATH line gone), so it re-adds
    a marker-free ``~/.local/bin`` PATH line the config sweep won't strip.
    """
    bin_dir = Path.home() / ".local" / "bin"
    link = bin_dir / "nunmai"
    try:
        bin_dir.mkdir(parents=True, exist_ok=True)
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(shim)
    except Exception as e:
        log_warn(f"Could not restore npm launcher at {link}: {e}")
        return None

    on_path = str(bin_dir) in os.environ.get("PATH", "").split(os.pathsep)
    if not on_path:
        for config_path in find_shell_configs():
            try:
                content = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
                if ".local/bin" in content:
                    continue
                with open(config_path, "a", encoding="utf-8") as fh:
                    fh.write('\nexport PATH="$HOME/.local/bin:$PATH"\n')
                break
            except Exception:
                continue
    return link


def _npm_global_prefix(shim: Path) -> "Path | None":
    """Return the npm global prefix that owns ``shim`` (``.../node_modules/nunmai/bin/nunmai.js``).

    ``None`` when the shim belongs to a project-local ``npm install nunmai``
    (a ``node_modules`` next to a ``package.json``) — a project dependency is
    the project's business, not ours to ``npm uninstall``.
    """
    try:
        parts = shim.resolve().parts
    except Exception:
        parts = shim.parts
    for i in range(len(parts) - 1):
        if parts[i] != "node_modules" or parts[i + 1] != "nunmai":
            continue
        nm_parent = Path(*parts[:i]) if i else Path(shim.anchor)
        if (nm_parent / "package.json").exists():
            return None  # project-local install
        if _is_windows():
            # %APPDATA%\npm\node_modules\nunmai — prefix is the dir holding node_modules
            return nm_parent if (nm_parent / "nunmai.cmd").exists() else None
        # POSIX global layout is always <prefix>/lib/node_modules/<pkg>
        return nm_parent.parent if nm_parent.name == "lib" else None
    return None


def _npm_executables(prefix: Path, nunmai_home: Path) -> "list[str]":
    """npm binaries to try, most specific first."""
    names = ("npm.cmd", "npm") if _is_windows() else ("npm",)
    cands: list[Path] = []
    for n in names:
        cands.append(prefix / n if _is_windows() else prefix / "bin" / n)
        cands.append(nunmai_home / "node" / n if _is_windows() else nunmai_home / "node" / "bin" / n)
    out = [str(c) for c in cands if c.exists()]
    for n in names:
        found = shutil.which(n)
        if found and found not in out:
            out.append(found)
    return out


def remove_npm_package(shim: Path, nunmai_home: Path) -> "bool | None":
    """``npm uninstall -g nunmai`` for the global install that owns ``shim``.

    Returns True when removed, False when the removal failed, and None when
    the shim is a project-local dependency we deliberately leave alone.
    Runs before ``$NUNMAI_HOME`` is deleted so a Nunmai-managed npm is still
    usable.
    """
    prefix = _npm_global_prefix(shim)
    if prefix is None:
        return None
    for npm in _npm_executables(prefix, nunmai_home):
        try:
            r = subprocess.run(
                [npm, "uninstall", "-g", "--prefix", str(prefix), "nunmai"],
                capture_output=True, text=True, timeout=180,
                shell=_is_windows() and npm.lower().endswith(".cmd"),
            )
        except Exception:
            continue
        if r.returncode == 0 and not shim.exists():
            return True
    return False


def _cache_base() -> Path:
    if _is_windows():
        return Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches"
    return Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache"))


def playwright_browsers_dir() -> "Path | None":
    """Where ``playwright install chromium`` (installer ``--full``) put the browsers.

    ``None`` when the user pointed Playwright somewhere themselves via
    ``PLAYWRIGHT_BROWSERS_PATH`` — that location is theirs to manage.
    """
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return None
    return _cache_base() / "ms-playwright"


def uv_cache_dir(nunmai_home: Path) -> "Path | None":
    """The uv download cache — only when the only ``uv`` around is the one the
    installer put under ``$NUNMAI_HOME/bin`` (or none is on PATH at all)."""
    if os.environ.get("UV_CACHE_DIR"):
        return None
    found = shutil.which("uv")
    if found:
        try:
            if nunmai_home.resolve() not in Path(found).resolve().parents:
                return None  # the user's own uv — its cache stays
        except Exception:
            return None
    if _is_windows():
        return _cache_base() / "uv" / "cache"
    return _cache_base() / "uv"


def remove_wrapper_script():
    """Remove the nunmai wrapper script if it exists."""
    wrapper_paths = [
        Path.home() / ".local" / "bin" / "nunmai",
        Path.home() / ".local" / "bin" / "nunmai-acp",
        Path.home() / ".local" / "bin" / "nunmai-engine",
        Path("/usr/local/bin/nunmai"),
        Path("/usr/local/bin/nunmai-acp"),
        Path("/usr/local/bin/nunmai-engine"),
    ]
    
    removed = []
    for wrapper in wrapper_paths:
        if wrapper.exists() or wrapper.is_symlink():
            try:
                if wrapper.is_symlink() and not wrapper.exists():
                    wrapper.unlink()  # dangling link (e.g. to an already-removed npm shim)
                    removed.append(wrapper)
                    continue
                # Check if it's our wrapper (contains nunmai_cli reference) or
                # the npm bootstrap shim's fallback symlink.
                content = wrapper.read_text(encoding="utf-8")
                if 'nunmai_cli' in content or 'nunmai-engine' in content or 'nunmai-npm-shim' in content:
                    wrapper.unlink()
                    removed.append(wrapper)
            except Exception as e:
                log_warn(f"Could not remove {wrapper}: {e}")
    
    return removed


def _node_symlink_candidate_dirs() -> "list[Path]":
    """Directories where the installer may have placed node/npm/npx symlinks."""
    dirs: list[Path] = [Path.home() / ".local" / "bin"]
    # Root FHS installs put links in /usr/local/bin.
    if sys.platform == "linux":
        dirs.append(Path("/usr/local/bin"))
    # Termux installs put links in $PREFIX/bin.
    prefix = os.environ.get("PREFIX", "")
    if prefix and "com.termux" in prefix:
        dirs.append(Path(prefix) / "bin")
    return dirs


def remove_node_symlinks(nunmai_home: Path) -> list:
    """Remove the node/npm/npx symlinks the installer placed on PATH.

    The POSIX installer (``scripts/install.sh`` / ``scripts/lib/node-bootstrap.sh``)
    symlinks node/npm/npx into the same directory as the ``nunmai`` command:

    - ``/usr/local/bin/`` on root FHS installs (Linux, uid 0)
    - ``$PREFIX/bin/`` on Termux
    - ``~/.local/bin/`` otherwise (the common non-root case)

    We check all candidate directories so that uninstall works regardless of
    how the install was done (e.g. a root FHS install that placed links in
    ``/usr/local/bin``, or an older install that used ``~/.local/bin`` before
    the FHS fix).  Only symlinks that resolve into this Nunmai home's ``node``
    directory are removed — links the user has repointed elsewhere (nvm, fnm,
    etc.) are left untouched.
    """
    node_dir = (nunmai_home / "node").resolve()
    removed = []

    for name in ("node", "npm", "npx"):
        for bin_dir in _node_symlink_candidate_dirs():
            link = bin_dir / name
            try:
                # Only act on symlinks — never delete a real binary the user put here.
                if not link.is_symlink():
                    continue

                # Resolve the link target and confirm it points into our node dir.
                # os.readlink + manual join handles broken (dangling) links too;
                # Path.resolve() on a dangling link still returns the target path.
                target = Path(os.readlink(link))
                if not target.is_absolute():
                    target = (link.parent / target)
                target = target.resolve()

                if target == node_dir or node_dir in target.parents:
                    link.unlink()
                    removed.append(link)
            except Exception as e:
                log_warn(f"Could not remove {link}: {e}")

    return removed


def uninstall_gateway_service():
    """Stop and uninstall the gateway service (systemd, launchd, Windows
    Scheduled Task / Startup folder) and kill any standalone gateway processes.

    Delegates to the gateway module which handles:
    - Linux: user + system systemd services (with proper DBUS env setup)
    - macOS: launchd plists
    - Windows: Scheduled Task + Startup-folder fallback, via ``gateway_windows``
    - All platforms: standalone ``nunmai gateway run`` processes
    - Termux/Android: skips systemd (no systemd on Android), still kills standalone processes
    """
    import platform
    stopped_something = False

    # 1. Kill any standalone gateway processes (all platforms, including Termux)
    try:
        from nunmai_cli.gateway import kill_gateway_processes, find_gateway_pids
        pids = find_gateway_pids()
        if pids:
            killed = kill_gateway_processes()
            if killed:
                log_success(f"Killed {killed} running gateway process(es)")
                stopped_something = True
    except Exception as e:
        log_warn(f"Could not check for gateway processes: {e}")

    system = platform.system()

    # Termux/Android has no systemd and no launchd — nothing left to do.
    prefix = os.getenv("PREFIX", "")
    is_termux = bool(os.getenv("TERMUX_VERSION") or "com.termux/files/usr" in prefix)
    if is_termux:
        return stopped_something

    # 2. Linux: uninstall systemd services (both user and system scopes)
    if system == "Linux":
        try:
            from nunmai_cli.gateway import (
                get_systemd_unit_path,
                get_service_name,
                _systemctl_cmd,
            )
            svc_name = get_service_name()

            for is_system in (False, True):
                unit_path = get_systemd_unit_path(system=is_system)
                if not unit_path.exists():
                    continue

                scope = "system" if is_system else "user"
                try:
                    if is_system and os.geteuid() != 0:  # windows-footgun: ok — Linux systemd uninstall path, guarded by `if system == "Linux"` above
                        log_warn(f"System gateway service exists at {unit_path} "
                                 f"but needs sudo to remove")
                        continue

                    cmd = _systemctl_cmd(is_system)
                    subprocess.run(cmd + ["stop", svc_name],
                                   capture_output=True, check=False)
                    subprocess.run(cmd + ["disable", svc_name],
                                   capture_output=True, check=False)
                    unit_path.unlink()
                    subprocess.run(cmd + ["daemon-reload"],
                                   capture_output=True, check=False)
                    log_success(f"Removed {scope} gateway service ({unit_path})")
                    stopped_something = True
                except Exception as e:
                    log_warn(f"Could not remove {scope} gateway service: {e}")
        except Exception as e:
            log_warn(f"Could not check systemd gateway services: {e}")

    # 3. macOS: uninstall launchd plist
    elif system == "Darwin":
        try:
            from nunmai_cli.gateway import get_launchd_plist_path
            plist_path = get_launchd_plist_path()
            if plist_path.exists():
                subprocess.run(["launchctl", "unload", str(plist_path)],
                               capture_output=True, check=False)
                plist_path.unlink()
                log_success(f"Removed macOS gateway service ({plist_path})")
                stopped_something = True
        except Exception as e:
            log_warn(f"Could not remove launchd gateway service: {e}")

    # 4. Windows: uninstall Scheduled Task + Startup-folder entry.  The
    #    gateway_windows module already knows how to locate and remove both
    #    code paths (schtasks /Delete + .cmd unlink) and how to stop any
    #    running detached pythonw gateway process.  We call into it so the
    #    uninstall logic stays in exactly one place.
    elif system == "Windows":
        try:
            from nunmai_cli import gateway_windows
            if gateway_windows.is_installed() or gateway_windows.is_task_registered() \
                    or gateway_windows.is_startup_entry_installed():
                try:
                    gateway_windows.stop()
                except Exception as e:
                    log_warn(f"Could not stop Windows gateway cleanly: {e}")
                try:
                    gateway_windows.uninstall()
                    log_success("Removed Windows gateway (Scheduled Task + Startup entry)")
                    stopped_something = True
                except Exception as e:
                    log_warn(f"Could not fully uninstall Windows gateway: {e}")
        except Exception as e:
            log_warn(f"Could not check Windows gateway service: {e}")

    return stopped_something


# ============================================================================
# Windows-specific uninstall helpers
# ============================================================================
#
# The installer (``scripts/install.ps1``) does four Windows-only things that
# ``remove_path_from_shell_configs`` / ``remove_wrapper_script`` don't cover:
#
#   1. Sets User-scope env vars ``NUNMAI_HOME`` and ``NUNMAI_GIT_BASH_PATH``
#      via ``[Environment]::SetEnvironmentVariable(..., "User")``.  These
#      don't live in ~/.bashrc — they're in the Windows registry at
#      HKCU\Environment.
#   2. Prepends to User-scope ``PATH`` (same registry location) entries
#      like ``%LOCALAPPDATA%\nunmai\git\cmd``, ``%LOCALAPPDATA%\nunmai\git\bin``,
#      ``%LOCALAPPDATA%\nunmai\git\usr\bin``, ``%LOCALAPPDATA%\nunmai\node``.
#      Again not in any rc file — only accessible via the registry or the
#      .NET [Environment] API.
#   3. Downloads PortableGit to ``%LOCALAPPDATA%\nunmai\git\`` and Node to
#      ``%LOCALAPPDATA%\nunmai\node\`` as user-scoped, isolated copies.
#      These are ~200MB combined and serve no purpose after uninstall.
#   4. On the ``nunmai dashboard`` + gateway paths, drops files into
#      ``%LOCALAPPDATA%\nunmai\gateway-service\`` and sometimes
#      ``%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`` — the
#      latter is handled by ``gateway_windows.uninstall()`` already.
#
# Running a PowerShell one-liner per operation is overkill and fragile on
# locked-down machines (Constrained Language Mode, restricted ExecutionPolicy).
# Direct registry writes via ``winreg`` work without spawning any subprocess
# and apply immediately for new shells (SendMessage WM_SETTINGCHANGE would
# be nicer but requires ctypes and buys us nothing — the user will log out
# or open a new terminal anyway).


def _nunmai_path_markers(nunmai_home: Path, *, include_managed_bin: bool = False) -> list[str]:
    """Path-entry substrings that identify Nunmai-owned User-PATH entries.

    ``include_managed_bin`` adds the managed binary dir (``<root>\\bin``,
    holding the nunmai launchers and the managed uv) — only wanted when
    that dir is about to be deleted (full uninstall from the default root),
    so a keep-data uninstall leaves the still-working managed uv resolvable.
    """
    root = str(nunmai_home).rstrip("\\/")
    # Match on prefix so sub-entries (git\cmd, git\bin, git\usr\bin, node, etc.)
    # all get swept.  Also match the bare nunmai-engine install dir.
    markers = [root + "\\nunmai-engine", root + "\\git", root + "\\node", root + "\\venv"]
    if include_managed_bin:
        markers.append(root + "\\bin")
    # Also match if NUNMAI_HOME was customised to somewhere else — find-and-nuke
    # any entry whose path component contains "nunmai".  We don't want to catch
    # unrelated entries like "cnunmai-foo" or "ephermeral", so we look for
    # backslash-nunmai as a word-ish boundary.
    return markers


def remove_path_from_windows_registry(nunmai_home: Path, *, include_managed_bin: bool = False) -> list[str]:
    """Strip Nunmai-owned entries from User-scope PATH in the registry.

    Returns the list of removed path entries.  Operates on HKCU\\Environment,
    same key the installer wrote to via ``[Environment]::SetEnvironmentVariable``.

    ``include_managed_bin`` adds ``<nunmai_home>\\bin`` (the managed binary
    dir holding the nunmai launchers and the managed uv) to the sweep. Only
    pass it when that dir is actually being deleted — full uninstall from
    the default root — so a keep-data uninstall leaves the still-working
    managed uv resolvable.
    """
    try:
        import winreg
    except ImportError:
        return []  # not on Windows, nothing to do

    removed: list[str] = []
    key_path = "Environment"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                            winreg.KEY_READ | winreg.KEY_WRITE) as key:
            try:
                path_value, path_type = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                return []
            # Preserve REG_EXPAND_SZ vs REG_SZ so unexpanded %VARS% survive.
            entries = [e for e in path_value.split(";") if e]
            markers = _nunmai_path_markers(nunmai_home, include_managed_bin=include_managed_bin)
            kept: list[str] = []
            for entry in entries:
                entry_norm = entry.rstrip("\\/")
                matched = any(entry_norm.lower().startswith(m.lower()) for m in markers)
                if matched:
                    removed.append(entry)
                else:
                    kept.append(entry)
            if removed:
                new_value = ";".join(kept)
                winreg.SetValueEx(key, "Path", 0, path_type, new_value)
    except OSError as e:
        log_warn(f"Could not edit User PATH in registry: {e}")
    return removed


def remove_nunmai_env_vars_windows() -> list[str]:
    """Delete NUNMAI_HOME and NUNMAI_GIT_BASH_PATH from User-scope env vars."""
    try:
        import winreg
    except ImportError:
        return []

    removed: list[str] = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_READ | winreg.KEY_WRITE) as key:
            for name in ("NUNMAI_HOME", "NUNMAI_GIT_BASH_PATH"):
                try:
                    winreg.QueryValueEx(key, name)
                except FileNotFoundError:
                    continue
                try:
                    winreg.DeleteValue(key, name)
                    removed.append(name)
                except OSError as e:
                    log_warn(f"Could not delete {name} from User env: {e}")
    except OSError as e:
        log_warn(f"Could not open User Environment key: {e}")
    return removed


def remove_portable_tooling_windows(nunmai_home: Path) -> list[Path]:
    """Delete PortableGit and Node installs the Windows installer created under
    ``%LOCALAPPDATA%\\nunmai\\``.  Only called on full uninstall; they're
    isolated from any system Git / Node so they cannot break other tools."""
    removed: list[Path] = []
    for sub in ("git", "node", "gateway-service"):
        target = nunmai_home / sub
        if target.exists():
            try:
                shutil.rmtree(target, ignore_errors=False)
                removed.append(target)
            except Exception as e:
                log_warn(f"Could not remove {target}: {e}")
    return removed


def remove_windows_bin_launchers(*, windows: bool | None = None) -> list[Path]:
    """Delete the ``nunmai`` launchers install.ps1 staged in the managed
    binary dir (the default Nunmai root's ``bin``, next to the managed uv).

    Every uninstall mode deletes the code checkout, so the launchers —
    which invoke ``<checkout>\\venv\\Scripts`` — would otherwise dangle:
    ``nunmai`` in a new terminal resolves to a launcher whose target is
    gone and errors, which reads worse than command-not-found. The managed
    uv (uv*.exe) in the same dir is left for keep-data reinstalls.

    A launcher that IS this process's own trampoline is mandatory-locked
    against deletion but not rename (same fact
    ``_install_repair._quarantine_running_nunmai_exe`` relies on), so
    deletion falls back to renaming it aside with a non-executable suffix.

    *windows* is an injectable platform verdict for tests (same pattern as
    ``_install_repair.ensure_windows_bin_launchers``).
    """
    if windows is None:
        windows = _is_windows()
    if not windows:
        return []
    try:
        # Lockstep launcher-name list — the same names install.ps1 and the
        # startup heal stage into this dir.
        from nunmai_cli._install_repair import _WINDOWS_BIN_LAUNCHERS
        from nunmai_constants import get_default_nunmai_root

        bin_dir = get_default_nunmai_root() / "bin"
    except Exception as e:
        log_warn(f"Could not locate the managed binary dir: {e}")
        return []

    removed: list[Path] = []
    for name in _WINDOWS_BIN_LAUNCHERS:
        for suffix in (".exe", ".cmd"):
            launcher = bin_dir / f"{name}{suffix}"
            if not launcher.exists():
                continue
            try:
                launcher.unlink()
                removed.append(launcher)
            except OSError:
                aside = launcher.with_name(f"{launcher.name}.uninstalled.{os.getpid()}")
                try:
                    os.rename(launcher, aside)
                    removed.append(launcher)
                except OSError as e:
                    log_warn(f"Could not remove {launcher}: {e}")
    return removed


def _is_windows() -> bool:
    import sys
    return sys.platform == "win32"


def _is_default_nunmai_home(nunmai_home: Path) -> bool:
    """Return True when ``nunmai_home`` points at the default (non-profile) root."""
    try:
        from nunmai_constants import get_default_nunmai_root
        return nunmai_home.resolve() == get_default_nunmai_root().resolve()
    except Exception:
        return False


def _discover_named_profiles():
    """Return a list of ``ProfileInfo`` for every non-default profile, or ``[]``
    if profile support is unavailable or nothing is installed beyond the
    default root."""
    try:
        from nunmai_cli.profiles import list_profiles
    except Exception:
        return []
    try:
        return [p for p in list_profiles() if not getattr(p, "is_default", False)]
    except Exception as e:
        log_warn(f"Could not enumerate profiles: {e}")
        return []


def _uninstall_profile(profile) -> None:
    """Fully uninstall a single named profile: stop its gateway service,
    remove its alias wrapper, and wipe its NUNMAI_HOME directory.

    We shell out to ``nunmai -p <name> gateway stop|uninstall`` because
    service names, unit paths, and plist paths are all derived from the
    current NUNMAI_HOME and can't be easily switched in-process.
    """
    import sys as _sys
    name = profile.name
    profile_home = profile.path

    log_info(f"Uninstalling profile '{name}'...")

    # 1. Stop and remove this profile's gateway service.
    #    Use `python -m nunmai_cli.main` so we don't depend on a `nunmai`
    #    wrapper that may be half-removed mid-uninstall.
    nunmai_invocation = [_sys.executable, "-m", "nunmai_cli.main", "--profile", name]
    for subcmd in ("stop", "uninstall"):
        try:
            subprocess.run(
                nunmai_invocation + ["gateway", subcmd],
                capture_output=True,
                text=True, encoding='utf-8', errors='replace',
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired:
            log_warn(f"  Gateway {subcmd} timed out for '{name}'")
        except Exception as e:
            log_warn(f"  Could not run gateway {subcmd} for '{name}': {e}")

    # 2. Remove the wrapper alias script at ~/.local/bin/<name> (if any).
    alias_path = getattr(profile, "alias_path", None)
    if alias_path and alias_path.exists():
        try:
            alias_path.unlink()
            log_success(f"  Removed alias {alias_path}")
        except Exception as e:
            log_warn(f"  Could not remove alias {alias_path}: {e}")

    # 3. Wipe the profile's NUNMAI_HOME directory.
    try:
        if profile_home.exists():
            shutil.rmtree(profile_home)
            log_success(f"  Removed {profile_home}")
    except Exception as e:
        log_warn(f"  Could not remove {profile_home}: {e}")


def run_gui_uninstall(args):
    """GUI-only uninstall: remove the Chat GUI, leave the agent + data intact.

    Mirrors ``nunmai uninstall --gui``. Removes the desktop app's built
    artifacts, the packaged app bundle (best-effort), and the Electron
    userData dir — nothing under ``$NUNMAI_HOME`` config/sessions/.env, and
    never the Python agent or its venv.
    """
    from nunmai_cli.gui_uninstall import (
        agent_is_installed,
        gui_install_summary,
        uninstall_gui,
    )

    nunmai_home = get_nunmai_home()
    summary = gui_install_summary(nunmai_home)
    skip_confirm = bool(getattr(args, "yes", False))

    print()
    print(color("┌─────────────────────────────────────────────────────────┐", Colors.MAGENTA, Colors.BOLD))
    print(color("│         ◆ Nunmai Chat GUI Uninstaller                  │", Colors.MAGENTA, Colors.BOLD))
    print(color("└─────────────────────────────────────────────────────────┘", Colors.MAGENTA, Colors.BOLD))
    print()

    if not summary["gui_installed"]:
        print("No Nunmai Chat GUI installation was found.")
        print(f"  Checked: {nunmai_home}, and the standard app locations for this OS.")
        return

    print(color("This removes the Chat GUI only. The Nunmai agent stays installed.", Colors.CYAN))
    print()
    print(color("Will remove:", Colors.YELLOW, Colors.BOLD))
    for p in summary["source_built_artifacts"]:
        print(f"  • {p}")
    for p in summary["packaged_app_paths"]:
        print(f"  • {p}")
    if summary["userdata_exists"]:
        print(f"  • {summary['userdata_dir']}  (desktop app data)")
    print()
    if agent_is_installed(nunmai_home):
        print(color("Kept intact:", Colors.GREEN, Colors.BOLD))
        print(f"  • The Nunmai agent at {nunmai_home / 'nunmai-engine'}")
        print(f"  • Your config, sessions, and secrets under {nunmai_home}")
        print()

    if not skip_confirm:
        try:
            confirm = input(f"Type '{color('yes', Colors.YELLOW)}' to remove the Chat GUI: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            print("Cancelled.")
            return
        if confirm != "yes":
            print()
            print("Uninstall cancelled.")
            return

    print()
    print(color("Uninstalling Chat GUI...", Colors.CYAN, Colors.BOLD))
    print()
    uninstall_gui(nunmai_home)

    print()
    print(color("┌─────────────────────────────────────────────────────────┐", Colors.GREEN, Colors.BOLD))
    print(color("│            ✓ Chat GUI Uninstalled!                      │", Colors.GREEN, Colors.BOLD))
    print(color("└─────────────────────────────────────────────────────────┘", Colors.GREEN, Colors.BOLD))
    print()
    print("The Nunmai agent is still installed. Run 'nunmai' to use the CLI,")
    print("or 'nunmai uninstall' to remove the agent too.")
    print()


def _wants_full(args) -> bool:
    """A clean, complete removal is the default. ``--keep-data`` keeps
    ``$NUNMAI_HOME``; the legacy ``--full`` flag is accepted and means the default."""
    return not bool(getattr(args, "keep_data", False))


def run_uninstall(args):
    """
    Run the uninstall process.

    Default: remove everything — engine, ~/.nunmai (config, data, logs,
    managed Node/uv), services, launchers, caches and the npm package.
    ``--keep-data``: same, but ~/.nunmai is kept for a future reinstall.
    """
    project_root = get_project_root()
    nunmai_home = get_nunmai_home()
    full_uninstall = _wants_full(args)

    if bool(getattr(args, "dry_run", False)):
        _print_uninstall_dry_run(
            project_root=project_root,
            nunmai_home=nunmai_home,
            full_uninstall=full_uninstall,
        )
        return

    # Detect named profiles when uninstalling from the default root —
    # offer to clean them up too instead of leaving zombie NUNMAI_HOMEs
    # and systemd units behind.
    is_default_profile = _is_default_nunmai_home(nunmai_home)
    named_profiles = _discover_named_profiles() if is_default_profile else []

    # Non-interactive fast path (``--yes``): no prompts. Named profiles are
    # NOT auto-removed here — that's a surprising default for an unattended
    # run, so it stays opt-in to the interactive flow. This is the path the
    # desktop app's detached cleanup script uses.
    if bool(getattr(args, "yes", False)):
        _perform_uninstall(
            project_root=project_root,
            nunmai_home=nunmai_home,
            full_uninstall=full_uninstall,
            remove_profiles=False,
            named_profiles=named_profiles,
        )
        return

    # Interactive flow — one question, like the installer asks none.
    #   nunmai uninstall              → removes everything            [y/N]
    #   nunmai uninstall --keep-data  → removes everything but ~/.nunmai [Y/n]
    print()
    print(color("◆ Nunmai Engine Uninstaller", Colors.MAGENTA, Colors.BOLD))
    print()
    print(f"  Engine:  {project_root}")
    if full_uninstall:
        print(f"  Data:    {nunmai_home}  " + color("(deleted: config, API keys, sessions, cron, logs)", Colors.RED))
    else:
        print(f"  Data:    {nunmai_home}  " + color("(kept — reinstall picks your settings back up)", Colors.GREEN))
    print("  Also:    gateway service, the `nunmai` command, managed Node/uv, browser cache, npm package")
    if named_profiles:
        print("  Profiles: " + ", ".join(p.name for p in named_profiles) + ("  (asked below)" if full_uninstall else "  (kept)"))
    print()

    remove_profiles = False
    try:
        if full_uninstall:
            resp = input(color("Remove Nunmai Engine and all of its data? [y/N]: ", Colors.BOLD)).strip().lower()
            if resp not in {"y", "yes"}:
                print("Cancelled — nothing was changed.")
                print(color("  (to keep your config and data:  nunmai uninstall --keep-data)", Colors.DIM))
                return
            if named_profiles:
                resp = input(color(
                    f"Also remove the {len(named_profiles)} named profile(s) listed above? [y/N]: ",
                    Colors.BOLD,
                )).strip().lower()
                remove_profiles = resp in {"y", "yes"}
        else:
            resp = input(color("Remove Nunmai Engine (keeping your data)? [Y/n]: ", Colors.BOLD)).strip().lower()
            if resp not in {"", "y", "yes"}:
                print("Cancelled — nothing was changed.")
                return
    except (KeyboardInterrupt, EOFError):
        print()
        print("Cancelled — nothing was changed.")
        return

    _perform_uninstall(
        project_root=project_root,
        nunmai_home=nunmai_home,
        full_uninstall=full_uninstall,
        remove_profiles=remove_profiles,
        named_profiles=named_profiles,
    )


def _print_uninstall_dry_run(*, project_root: Path, nunmai_home: Path, full_uninstall: bool) -> None:
    """Print the uninstall plan without stopping services or deleting files."""
    print()
    print(color("Dry run: no files, services, or environment entries will be changed.", Colors.CYAN, Colors.BOLD))
    print()
    print(color("Would inspect/remove:", Colors.YELLOW, Colors.BOLD))
    print("  • Gateway services and standalone gateway processes")
    print("  • Nunmai PATH entries from shell configs / Windows User PATH")
    print("  • Nunmai wrapper scripts and Nunmai-managed node/npm/npx symlinks")
    print("  • Desktop Chat GUI artifacts")
    print("  • The `nunmai` npm package (when installed with npm)")
    print(f"  • Code checkout: {project_root}")
    if full_uninstall:
        print(f"  • Nunmai config/data: {nunmai_home}")
        print("  • Playwright browser cache and the uv cache (when uv is Nunmai-managed)")
        if _is_default_nunmai_home(nunmai_home):
            profiles = _discover_named_profiles()
            if profiles:
                print("  • Named profiles (interactive uninstall asks before removing):")
                for prof in profiles:
                    print(f"    - {prof.name}: {prof.path}")
    else:
        print(f"  • Keep Nunmai config/data: {nunmai_home}")
    print()


def _perform_uninstall(
    *,
    project_root: Path,
    nunmai_home: Path,
    full_uninstall: bool,
    remove_profiles: bool,
    named_profiles: list,
) -> None:
    """Execute the uninstall steps. Shared by the interactive and ``--yes``
    paths so the destructive sequence lives in exactly one place.

    Steps: stop gateway → strip PATH (rc files + Windows registry) → remove the
    ``nunmai`` wrapper + node symlinks → remove the desktop Chat GUI artifacts →
    delete the code checkout → (Windows) remove PortableGit/Node → optionally
    wipe ``$NUNMAI_HOME`` data and named profiles on full uninstall.
    """
    print()
    print(color("Uninstalling…", Colors.CYAN, Colors.BOLD))
    print()

    # Output policy: print a line only for something that actually changed.
    # Steps that find nothing stay silent — an uninstall should read like the
    # installer's success path, not a diagnostic transcript.
    done: list[str] = []

    def _did(msg: str) -> None:
        done.append(msg)
        log_success(msg)

    # 1. Stop and uninstall gateway service + kill standalone processes
    if uninstall_gateway_service():
        _did("Stopped the gateway")

    # 2. PATH entries: shell rc files (POSIX) and the Windows User registry.
    for config in remove_path_from_shell_configs():
        _did(f"Removed PATH entry from {config}")

    if _is_windows():
        # The managed binary dir (nunmai\bin: launchers + managed uv) leaves
        # the PATH only when the full wipe below deletes it; keep-data mode
        # keeps the dir and the still-working uv resolvable.
        sweep_managed_bin = full_uninstall and _is_default_nunmai_home(nunmai_home)
        for entry in remove_path_from_windows_registry(
            Path(os.path.expandvars(str(nunmai_home))),
            include_managed_bin=sweep_managed_bin,
        ):
            _did(f"Removed from User PATH: {entry}")
        for name in remove_nunmai_env_vars_windows():
            _did(f"Removed User env var: {name}")

    # 3. The `nunmai` command. If the install came through `npm install
    #    nunmai`, remove that package too (before $NUNMAI_HOME goes, so a
    #    Nunmai-managed npm is still there to do it). Only when the npm
    #    removal fails do we point `nunmai` back at the shim so the user
    #    still has a working command to reinstall or retry with.
    npm_shim = find_npm_shim_path()
    for wrapper in remove_wrapper_script():
        _did(f"Removed command {wrapper}")
    npm_restored = None
    npm_failed = False
    if npm_shim is not None:
        try:
            outcome = remove_npm_package(npm_shim, nunmai_home)
        except Exception as e:
            log_warn(f"Could not remove the npm package: {e}")
            outcome = False
        if outcome is True:
            _did("Removed the npm package (npm uninstall -g nunmai)")
        elif outcome is False:
            npm_failed = True
            npm_restored = restore_npm_shim_launcher(npm_shim)

    if _is_windows():
        for launcher in remove_windows_bin_launchers():
            _did(f"Removed command {launcher}")

    for link in remove_node_symlinks(nunmai_home):
        _did(f"Removed {link}")

    # 3c. Desktop Chat GUI artifacts (packaged app + Electron userData live
    #     outside NUNMAI_HOME, so they need explicit cleanup in both modes).
    try:
        from nunmai_cli.gui_uninstall import uninstall_gui
        if uninstall_gui(nunmai_home):
            _did("Removed the desktop app")
    except Exception as e:
        log_warn(f"Could not remove desktop GUI artifacts: {e}")

    # 4. The code checkout
    try:
        if project_root.exists():
            shutil.rmtree(project_root)
            _did(f"Removed engine {project_root}")
    except Exception as e:
        log_warn(f"Could not fully remove {project_root}: {e} — remove it manually")

    # 4b. Windows-only installer tooling (PortableGit, bundled Node, service
    #     dir): install artifacts, not user data — safe in keep-data mode too.
    if _is_windows():
        for path in remove_portable_tooling_windows(nunmai_home):
            _did(f"Removed {path}")

    # 5. Config/data (full uninstall only) and named profiles
    if full_uninstall:
        if remove_profiles and named_profiles:
            for prof in named_profiles:
                _uninstall_profile(prof)
                _did(f"Removed profile {prof.name}")
        # Caches the installer filled: decide about uv BEFORE $NUNMAI_HOME
        # (and the managed uv inside it) disappears.
        cache_dirs = [d for d in (playwright_browsers_dir(), uv_cache_dir(nunmai_home)) if d is not None]
        try:
            if nunmai_home.exists():
                shutil.rmtree(nunmai_home)
                _did(f"Removed data {nunmai_home}")
        except Exception as e:
            log_warn(f"Could not fully remove {nunmai_home}: {e} — remove it manually")
        for cache in cache_dirs:
            try:
                if cache.is_dir():
                    shutil.rmtree(cache)
                    _did(f"Removed cache {cache}")
            except Exception as e:
                log_warn(f"Could not remove {cache}: {e}")

    # Done
    print()
    if done:
        print(color("✓ Nunmai Engine removed.", Colors.GREEN, Colors.BOLD))
    else:
        print(color("✓ Nothing left to remove.", Colors.GREEN, Colors.BOLD))
    if not full_uninstall:
        print(f"  Kept your config and data: {nunmai_home}")
    if npm_failed:
        print(color("  Could not remove the npm package automatically. Run:  npm uninstall -g nunmai", Colors.YELLOW))
        if npm_restored is not None:
            print("  Until then `nunmai` is the npm launcher and would reinstall the engine.")
    elif npm_shim is not None and _npm_global_prefix(npm_shim) is None:
        print("  Installed as a project dependency — remove it there with:  npm uninstall nunmai")
    print()
    if _is_windows():
        print(color("Open a new terminal to pick up the updated PATH.", Colors.DIM))
    else:
        print(color("Open a new terminal (or `source ~/.zshrc` / `~/.bashrc`) to refresh PATH.", Colors.DIM))
    print()


class _UninstallArgs:
    """Lightweight args namespace for the module entrypoint below."""

    def __init__(self, *, mode: str):
        self.gui = mode == "gui"
        self.gui_summary = False
        self.full = mode == "full"
        self.keep_data = mode == "lite"
        self.yes = True  # the module entrypoint is always non-interactive


def main(argv=None) -> int:
    """Module entrypoint: ``python -m nunmai_cli.uninstall --mode <gui|lite|full>``.

    Exists so the desktop app can run the uninstall under a Python interpreter
    OUTSIDE the venv being deleted. On Windows, ``lite``/``full`` rmtree the
    venv that contains the running ``python.exe`` — and a running .exe is
    mandatory-locked, so doing that from the venv's own interpreter half-fails.
    The desktop launches this with the system Python + ``PYTHONPATH=<agentRoot>``
    so ``import nunmai_cli`` resolves from source while the venv is torn down.

    This module imports only stdlib + ``nunmai_constants`` + ``nunmai_cli.colors``
    (and lazily ``nunmai_cli.gui_uninstall``), so it runs fine under a bare
    system Python with no site-packages from the venv.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="python -m nunmai_cli.uninstall")
    parser.add_argument(
        "--mode",
        choices=["gui", "lite", "full"],
        required=True,
        help="gui = Chat GUI only; lite = GUI + agent, keep data; full = everything",
    )
    ns = parser.parse_args(argv)
    args = _UninstallArgs(mode=ns.mode)

    if args.gui:
        run_gui_uninstall(args)
    else:
        run_uninstall(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
