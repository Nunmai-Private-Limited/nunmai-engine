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
- **Local install** (`npm install nunmai`, no `-g`): run it with `npx nunmai`.
  npm ≥ 11.19 blocks dependency install scripts by default, so the engine is
  installed on the first `npx nunmai` run. To get a plain `nunmai` command from
  a local install, allow the script: `npm install nunmai --allow-scripts=nunmai`.
- If npm skipped the install script (`--ignore-scripts`, `CI` set, or the
  allow-scripts policy above), the install simply happens on the first run.
- After `nunmai uninstall`, the `nunmai` command falls back to this launcher —
  running `nunmai` again reinstalls the engine.
- Lightweight install (no browser/computer-use): `NUNMAI_INSTALL_LITE=1 npm i -g nunmai`.
- Extra installer flags: `NUNMAI_INSTALL_ARGS="--branch dev" npm i -g nunmai`.
- Updates: `nunmai update`. Remove: `nunmai uninstall`, then `npm uninstall -g nunmai`.

This package only contains the launcher; the engine's source lives at
https://github.com/Nunmai-Private-Limited/nunmai-engine.
