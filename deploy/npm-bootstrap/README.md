# nunmai

Install [Nunmai Engine](https://nunmai.in) with npm — everything included.

```bash
npm install -g nunmai
nunmai
```

`npm install` runs the official installer (https://nunmai-engine.nunmai.in) in
**full, non-interactive** mode: the engine, Python, git, Node.js, browser and
computer-use tools are all provisioned automatically into Nunmai's own
directories — your system toolchain is never modified. Then `nunmai` starts the
engine; the first run opens the AI-account wizard (Claude, ChatGPT, Kimi,
Gemini, OpenRouter).

- macOS, Linux, Windows 10/11 (PowerShell), Android (Termux).
- **Local install** (`npm install nunmai`, no `-g`): run it once with `npx nunmai`.
  npm ≥ 11.19 blocks dependency install scripts by default, so the engine is
  installed on that first run. The launcher then puts a plain `nunmai` command
  on your PATH itself — `~/.local/bin` on macOS/Linux, `%LOCALAPPDATA%\nunmai\bin`
  (registered on the user PATH) on Windows — so after opening a new terminal
  `nunmai` just works. To skip even that first `npx`, allow the script:
  `npm install nunmai --allow-scripts=nunmai`.
- If npm skipped the install script (`--ignore-scripts`, `CI` set, or the
  allow-scripts policy above), the install simply happens on the first run.
- Lightweight install (no browser/computer-use): `NUNMAI_INSTALL_LITE=1 npm i -g nunmai`.
- Extra installer flags: `NUNMAI_INSTALL_ARGS="--branch dev" npm i -g nunmai`.
- Updates: `nunmai update`.
- Remove: `nunmai uninstall` — one confirmation, then everything goes: the engine,
  `~/.nunmai` (config, keys, sessions, managed Node/uv), the gateway service,
  browser/uv caches **and this npm package**. `nunmai uninstall --keep-data`
  keeps `~/.nunmai` for a later reinstall; `--yes` skips the prompt;
  `--dry-run` only shows the plan. Running `nunmai uninstall` when the engine
  is not installed says so, offers to clear any leftovers from an earlier or
  failed install, and removes the launcher itself — so the next `nunmai` is a
  plain "command not found".

This package only contains the launcher; the engine's source lives at
https://github.com/Nunmai-Private-Limited/nunmai-engine.
