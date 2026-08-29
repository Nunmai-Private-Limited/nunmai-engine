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

- macOS, Linux, Windows 10/11 (PowerShell), Android (Termux). `npx nunmai` works too.
- If npm ran with `--ignore-scripts` (or `CI` is set), the install happens on the
  first `nunmai` run instead.
- Lightweight install (no browser/computer-use): `NUNMAI_INSTALL_LITE=1 npm i -g nunmai`.
- Extra installer flags: `NUNMAI_INSTALL_ARGS="--branch dev" npm i -g nunmai`.
- Updates: `nunmai update`. Remove: `nunmai uninstall`, then `npm uninstall -g nunmai`.

This package only contains the launcher; the engine's source lives at
https://github.com/Nunmai-Private-Limited/nunmai-engine.
