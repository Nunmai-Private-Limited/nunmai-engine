#!/usr/bin/env node
"use strict";
/*
 * npm bootstrap for Nunmai Engine.
 *
 * Nunmai Engine is a Python application (managed by uv), so this package is a
 * small launcher around the official installer (https://nunmai-engine.nunmai.in):
 *
 *   npm install nunmai      -> (with or without -g) postinstall runs the FULL, non-interactive install
 *                              (engine, Python, git, Node, browser + computer-use
 *                              tools). Nothing on the system is modified — every
 *                              dependency is provisioned into Nunmai's own dirs.
 *                              A `nunmai` command is always left on PATH
 *                              (~/.local/bin), even for local, non -g installs.
 *   nunmai                  -> launches the installed engine (first run opens the
 *                              AI-account wizard). If the engine is missing (e.g.
 *                              npm ran with --ignore-scripts), it installs first.
 *
 *   NUNMAI_HOME                  respected (Windows launchers: %NUNMAI_HOME%\bin)
 *   NUNMAI_INSTALL_LITE=1        lightweight install instead of --full
 *   NUNMAI_INSTALL_ARGS="..."    extra installer flags (appended)
 *   NUNMAI_NPM_NO_POSTINSTALL=1  skip the install at `npm install` time
 *   NUNMAI_BOOTSTRAP_DRY_RUN=1   print what would run instead of installing
 */
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const INSTALL_SH = "https://nunmai-engine.nunmai.in/install.sh";
const INSTALL_PS1 = "https://nunmai-engine.nunmai.in/install.ps1";
const IS_WIN = process.platform === "win32";
const SELF = fs.realpathSync(__filename);
const DRY = process.env.NUNMAI_BOOTSTRAP_DRY_RUN === "1";

// Marker stamped into the Windows fallback shim (a .cmd that re-enters this
// file). findLauncher() must never treat that shim as the engine launcher or
// `nunmai` would recurse into itself forever.
const WIN_SHIM_MARKER = "rem nunmai-npm-shim";

function winBinDir() {
  // Same managed dir install.ps1 uses for the real launchers (Set-PathVariable):
  // %NUNMAI_HOME%\bin, defaulting to %LOCALAPPDATA%\nunmai\bin.
  const home = os.homedir();
  const nunmaiHome = process.env.NUNMAI_HOME || path.join(process.env.LOCALAPPDATA || path.join(home, "AppData", "Local"), "nunmai");
  return path.join(nunmaiHome, "bin");
}

function isWinShim(p) {
  try { return p.toLowerCase().endsWith(".cmd") && fs.readFileSync(p, "utf8").includes(WIN_SHIM_MARKER); } catch (_) { return false; }
}

function candidates() {
  const home = os.homedir();
  if (IS_WIN) {
    const bin = winBinDir();
    return [path.join(bin, "nunmai.exe"), path.join(bin, "nunmai.cmd")];
  }
  const list = [];
  if (process.env.PREFIX && fs.existsSync(path.join(process.env.PREFIX, "bin"))) {
    list.push(path.join(process.env.PREFIX, "bin", "nunmai")); // Termux
  }
  list.push(path.join(home, ".local", "bin", "nunmai"), "/usr/local/bin/nunmai");
  return list;
}

function findLauncher() {
  for (const p of candidates()) {
    try {
      if (fs.realpathSync(p) === SELF) continue; // never recurse into this shim
      if (IS_WIN && isWinShim(p)) continue;      // ...nor into the Windows .cmd shim
      fs.accessSync(p, fs.constants.X_OK);
      return p;
    } catch (_) { /* not there */ }
  }
  return null;
}

function ensureFallbackLauncher() {
  // Local installs (`npm install nunmai` without -g) leave the bin shim in
  // ./node_modules/.bin, which is not on PATH. Make sure `nunmai` resolves
  // anyway by linking this shim into ~/.local/bin (or $PREFIX/bin on Termux).
  // The real installer replaces the link with the engine launcher (ln -sf).
  if (IS_WIN) return ensureWinFallbackLauncher();
  const binDir = process.env.PREFIX && fs.existsSync(path.join(process.env.PREFIX, "bin"))
    ? path.join(process.env.PREFIX, "bin")
    : path.join(os.homedir(), ".local", "bin");
  const target = path.join(binDir, "nunmai");
  try {
    fs.mkdirSync(binDir, { recursive: true });
    try { if (fs.realpathSync(target) === SELF) return target; } catch (_) { /* absent or dangling */ }
    try { fs.unlinkSync(target); } catch (_) { /* nothing to remove */ }
    fs.symlinkSync(SELF, target);
    fs.chmodSync(SELF, 0o755);
    ensurePathLine(binDir);
    return target;
  } catch (e) {
    console.error(`nunmai: could not link launcher into ${binDir}: ${e.message}`);
    return null;
  }
}

function ensureWinFallbackLauncher() {
  // Windows twin of the symlink above: drop a nunmai.cmd shim into the managed
  // bin dir and register that dir on the User PATH, so a plain `nunmai` works
  // after a local `npm install nunmai` (where npm >= 11.19 skips postinstall
  // and node_modules\.bin is not on PATH). install.ps1 later overwrites the
  // shim with the real launcher (Install-NunmaiCommandLaunchers) and keeps the
  // same PATH entry, so nothing here has to be undone.
  const binDir = winBinDir();
  const target = path.join(binDir, "nunmai.cmd");
  try {
    fs.mkdirSync(binDir, { recursive: true });
    // Never clobber a real engine launcher.
    if (fs.existsSync(path.join(binDir, "nunmai.exe"))) return null;
    if (fs.existsSync(target) && !isWinShim(target)) return null;
    const body = `@echo off\r\n${WIN_SHIM_MARKER}: ${SELF}\r\n"${process.execPath}" "${SELF}" %*\r\n`;
    fs.writeFileSync(target, body);
    ensureWinUserPath(binDir);
    return target;
  } catch (e) {
    console.error(`nunmai: could not stage launcher into ${binDir}: ${e.message}`);
    return null;
  }
}

function ensureWinUserPath(binDir) {
  // Persist binDir at the front of the User PATH (registry), the same way
  // install.ps1's Set-PathVariable does. Idempotent; best effort.
  const norm = (p) => p.trim().replace(/[\\/]+$/, "").toLowerCase();
  const onPath = (process.env.PATH || "").split(";").some((p) => norm(p) === norm(binDir));
  if (onPath || DRY) return;
  const ps = [
    `$d='${binDir.replace(/'/g, "''")}'`,
    "$cur=[Environment]::GetEnvironmentVariable('Path','User')",
    "$items=@(); if ($cur) { $items=@($cur -split ';') }",
    "if (-not ($items | Where-Object { $_.TrimEnd('\\') -ieq $d })) { [Environment]::SetEnvironmentVariable('Path', ((@($d) + $items) -join ';'), 'User'); exit 0 }",
    "exit 3",
  ].join("; ");
  const r = spawnSync("powershell", ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps], { stdio: "ignore" });
  if (r.status === 0) {
    console.log(`nunmai: added ${binDir} to your user PATH (open a new terminal, then run \`nunmai\`).`);
  } else if (r.status !== 3) {
    console.error(`nunmai: could not update the user PATH automatically. Add this folder to PATH to use \`nunmai\` directly: ${binDir}`);
  }
}

function ensurePathLine(binDir) {
  // Add ~/.local/bin to PATH in the user's shell rc if it is not there already.
  if (binDir !== path.join(os.homedir(), ".local", "bin")) return;
  const onPath = (process.env.PATH || "").split(path.delimiter).includes(binDir);
  if (onPath) return;
  const shell = path.basename(process.env.SHELL || "");
  const rc = shell === "zsh" ? ".zshrc" : shell === "fish" ? null : ".bashrc";
  if (!rc) return;
  const rcPath = path.join(os.homedir(), rc);
  try {
    const cur = fs.existsSync(rcPath) ? fs.readFileSync(rcPath, "utf8") : "";
    if (cur.includes(".local/bin")) return;
    fs.appendFileSync(rcPath, '\n# Nunmai Engine — ensure ~/.local/bin is on PATH\nexport PATH="$HOME/.local/bin:$PATH"\n');
    console.log(`nunmai: added ~/.local/bin to PATH in ~/${rc} (open a new terminal).`);
  } catch (_) { /* best effort */ }
}

function run(cmd, args, opts) {
  const env = Object.assign({}, process.env, { NUNMAI_NPM_SHIM: "1", NUNMAI_NPM_SHIM_PATH: SELF });
  const r = spawnSync(cmd, args, Object.assign({ stdio: "inherit", env }, opts || {}));
  if (r.error) {
    console.error(`nunmai: could not start ${cmd}: ${r.error.message}`);
    return 127;
  }
  return r.status == null ? 1 : r.status;
}

function installerFlags(nonInteractive) {
  const flags = [];
  if (process.env.NUNMAI_INSTALL_LITE !== "1") flags.push(IS_WIN ? "-Full" : "--full");
  if (nonInteractive) flags.push(IS_WIN ? "-NonInteractive" : "--non-interactive", IS_WIN ? "-SkipSetup" : "--skip-setup");
  const extra = (process.env.NUNMAI_INSTALL_ARGS || "").trim();
  if (extra) flags.push(extra);
  return flags.join(" ");
}

function install(nonInteractive) {
  const flags = installerFlags(nonInteractive);
  let cmd, args, shown;
  if (IS_WIN) {
    const ps = `& ([scriptblock]::Create((irm ${INSTALL_PS1}))) ${flags}`.trim();
    cmd = "powershell";
    args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps];
    shown = `powershell -NoProfile -ExecutionPolicy Bypass -Command "${ps}"`;
  } else {
    const sh = `curl -fsSL ${INSTALL_SH} | bash -s -- ${flags}`.trim();
    cmd = "bash";
    args = ["-c", sh];
    shown = sh;
  }
  console.log(nonInteractive
    ? "Installing Nunmai Engine and all of its dependencies (this can take a few minutes)…"
    : "Nunmai Engine is not installed on this machine yet — installing it now.");
  console.log(`  ${shown}\n`);
  if (DRY) return 0;
  return run(cmd, args);
}

function manualHint() {
  return IS_WIN ? `  irm ${INSTALL_PS1} | iex` : `  curl -fsSL ${INSTALL_SH} | bash`;
}

function postinstall() {
  // Runs from `npm install -g nunmai`. Must never fail the npm install: on any
  // problem we exit 0 and the first `nunmai` run retries interactively.
  if (process.env.NUNMAI_NPM_NO_POSTINSTALL === "1" || process.env.CI) {
    if (!findLauncher()) ensureFallbackLauncher();
    console.log("nunmai: engine install deferred to first run.");
    return 0;
  }
  if (findLauncher()) {
    console.log("nunmai: engine already installed — run `nunmai` to start.");
    return 0;
  }
  const code = install(true);
  if (code !== 0) {
    ensureFallbackLauncher();
    console.error(`\nnunmai: installer exited with code ${code}. Run \`nunmai\` to retry, or install manually:\n${manualHint()}`);
    return 0;
  }
  if (!DRY && !findLauncher()) ensureFallbackLauncher();
  console.log("\n✓ Nunmai Engine installed. Open a new terminal and run:  nunmai");
  return 0;
}

// The npm global prefix that owns this shim, or null for a project-local
// `npm install nunmai` (a node_modules next to a package.json — the project's
// dependency, not ours to remove).
function npmGlobalPrefix() {
  const parts = SELF.split(path.sep);
  for (let i = 0; i < parts.length - 1; i++) {
    if (parts[i] !== "node_modules" || parts[i + 1] !== "nunmai") continue;
    const nmParent = parts.slice(0, i).join(path.sep) || path.sep;
    if (fs.existsSync(path.join(nmParent, "package.json"))) return null;
    if (IS_WIN) return fs.existsSync(path.join(nmParent, "nunmai.cmd")) ? nmParent : null;
    return path.basename(nmParent) === "lib" ? path.dirname(nmParent) : null;
  }
  return null;
}

function removeFallbackLauncher() {
  // Undo ensureFallbackLauncher(): the ~/.local/bin (or $PREFIX/bin) symlink
  // and the Windows .cmd shim that point back at this file.
  let removed = false;
  if (IS_WIN) {
    const shim = path.join(winBinDir(), "nunmai.cmd");
    if (isWinShim(shim)) { try { fs.unlinkSync(shim); removed = true; } catch (_) { /* best effort */ } }
    return removed;
  }
  for (const p of candidates()) {
    try {
      if (fs.lstatSync(p).isSymbolicLink() && fs.realpathSync(p) === SELF) { fs.unlinkSync(p); removed = true; }
    } catch (_) { /* absent or not ours */ }
  }
  return removed;
}

// `npm uninstall -g nunmai` for the global install this shim belongs to.
// Returns true (removed), false (failed), or null (project-local install).
function removeSelfFromNpm() {
  const prefix = npmGlobalPrefix();
  if (prefix === null) return null;
  const nodeDir = path.dirname(process.execPath);
  const npms = IS_WIN
    ? [path.join(nodeDir, "npm.cmd"), "npm.cmd", "npm"]
    : [path.join(nodeDir, "npm"), path.join(prefix, "bin", "npm"), "npm"];
  for (const npm of npms) {
    const r = spawnSync(npm, ["uninstall", "-g", "--prefix", prefix, "nunmai"], { stdio: "ignore", shell: IS_WIN && npm.toLowerCase().endsWith(".cmd") });
    if (!r.error && r.status === 0 && !fs.existsSync(SELF)) return true;
  }
  return false;
}

// Commands that must never trigger an engine install when the engine is
// absent: a user asking to remove, or merely inspect, Nunmai should not be
// handed a multi-minute full install first.
function handleWithoutEngine(argv) {
  const cmd = (argv[0] || "").toLowerCase();
  if (cmd === "uninstall") {
    console.log("Nunmai Engine is not installed on this machine — nothing to remove.");
    removeFallbackLauncher();
    const npm = removeSelfFromNpm();
    if (npm === true) {
      console.log("Removed the `nunmai` npm launcher as well (npm uninstall -g nunmai). Nunmai is now fully gone.");
    } else if (npm === false) {
      console.log("Could not remove the npm launcher automatically. Run:  npm uninstall -g nunmai");
    } else {
      console.log("This launcher is a project dependency — remove it there with:  npm uninstall nunmai");
    }
    return 0;
  }
  if (cmd === "--version" || cmd === "-v" || cmd === "version") {
    console.log(`nunmai launcher ${require("../package.json").version} (engine not installed — run \`nunmai\` to install)`);
    return 0;
  }
  if (cmd === "--help" || cmd === "-h" || cmd === "help") {
    console.log([
      "Nunmai Engine is not installed on this machine yet.",
      "",
      "  nunmai            install the engine, then start it",
      "  nunmai --version  show the launcher version",
      "  nunmai uninstall  remove the engine and this launcher (nothing installed right now)",
      "",
      `Manual install: ${manualHint().trim()}`,
    ].join("\n"));
    return 0;
  }
  return null;
}

function main() {
  const argv = process.argv.slice(2);
  if (argv[0] === "--bootstrap-postinstall") process.exit(postinstall());

  let launcher = findLauncher();
  if (!launcher) {
    const handled = handleWithoutEngine(argv);
    if (handled !== null) process.exit(handled);
    const code = install(false);
    if (code !== 0) {
      console.error(`\nnunmai: installer exited with code ${code}. You can retry it manually:\n${manualHint()}`);
      process.exit(code);
    }
    if (DRY) process.exit(0);
    launcher = findLauncher();
    if (!launcher) {
      console.error("nunmai: install finished but the launcher was not found. Open a new terminal and run `nunmai`.");
      process.exit(1);
    }
    if (argv.length === 0) console.log("\nInstalled. Starting Nunmai Engine…\n");
  }
  process.exit(run(launcher, argv, IS_WIN && launcher.endsWith(".cmd") ? { shell: true } : {}));
}

main();
