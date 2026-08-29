# Nunmai CLI Reference

Live sources when anything looks stale: `nunmai --help`, `nunmai <command> --help`,
https://nunmai.in/docs/reference/cli-commands

### Global Flags

```
nunmai [flags] [command]        (no subcommand = interactive chat)

  --version, -V             Show version
  -z, --oneshot PROMPT      One-shot: print ONLY the final response (for scripts/pipes)
  -m MODEL  --provider P    Model/provider override for this invocation
  -t, --toolsets LIST       Comma-separated toolsets for this invocation
  --resume, -r SESSION      Resume session by ID or title
  --continue, -c [NAME]     Resume by name, or most recent session
  --worktree, -w            Isolated git worktree mode (parallel agents)
  --skills, -s SKILL        Preload skills (comma-separate or repeat)
  --profile, -p NAME        Use a named profile
  --yolo                    Skip dangerous command approval
  --tui / --cli             Force the Ink TUI / classic REPL
  --ignore-rules            Skip AGENTS.md/SOUL.md/memory/skill injection
  --safe-mode               Disable ALL customizations (troubleshooting)
  --pass-session-id         Include session ID in system prompt
```

### Chat

```
nunmai chat [flags]
  -q, --query TEXT          Single query, non-interactive
  --image PATH              Attach a local image to a single query
  -Q, --quiet               Suppress banner, spinner, tool previews
  --checkpoints             Enable filesystem checkpoints (/rollback)
  --max-turns N             Cap tool-calling iterations
  --source TAG              Session source tag (default: cli)
```
(plus the global flags above)

### Configuration

```
nunmai setup [section]      Wizard (model|tts|terminal|gateway|tools|agent)
nunmai model                Interactive model/provider picker
nunmai fallback [add|remove|list]  Fallback provider chain
nunmai config [show|edit|get|set|unset|path|env-path|check|migrate]
nunmai login / logout       OAuth sign-in / clear stored auth
nunmai doctor [--fix]       Check dependencies and config
nunmai status [--all]       Component status
```

### Tools & Skills

```
nunmai tools [list|enable NAME|disable NAME]   Per-platform toolsets (curses UI with no args)

nunmai skills list|browse|search QUERY|inspect ID
nunmai skills install ID    Hub identifier OR a direct https://…/SKILL.md URL
nunmai skills config        Enable/disable skills per platform
nunmai skills check|update|uninstall|publish PATH
nunmai skills tap add REPO  Add a GitHub repo as a skill source
nunmai bundles              Skill bundles (one /<name> alias loads several skills)
```

### MCP Servers

```
nunmai mcp add NAME (--url or --command) | remove | list | test NAME
nunmai mcp catalog | install NAME     Curated catalog install
nunmai mcp configure NAME             Toggle tool selection
nunmai mcp serve                      Run Nunmai as an MCP server
```
Details (transport, tool discovery, catalog): `references/native-mcp.md`.

### Gateway (Messaging Platforms)

```
nunmai gateway run|install|start|stop|restart|status|setup
```

20+ platforms: Telegram, Discord, Slack, WhatsApp (Baileys + Business Cloud API), iMessage (Photon — `nunmai photon setup`), Signal, Email, SMS, Matrix, Mattermost, Teams, LINE, SimpleX, ntfy, Google Chat, Home Assistant, DingTalk, Feishu, WeCom, Weixin, API Server, Webhooks. Open WebUI connects via the API Server adapter. Most adapters ship under `plugins/platforms/`.
Docs: https://nunmai.in/docs/user-guide/messaging/

### Sessions

```
nunmai sessions list|browse|rename ID TITLE|delete ID|export OUT|prune|stats
```

### Cron / Webhooks

```
nunmai cron list|create SCHED|edit ID|pause|resume|run ID|remove|status
    Schedules: '30m', 'every 2h', '0 9 * * *', ISO timestamp
nunmai webhook subscribe NAME|list|remove NAME|test NAME
```
Webhook payloads/routes: `references/webhooks.md`.

### Profiles

```
nunmai profile list|create NAME (--clone|--clone-all|--clone-from)|use|show|delete
nunmai profile rename A B | alias NAME | export NAME | import FILE
```

### Credentials & Pools

```
nunmai auth                 Interactive credential manager
nunmai auth add [PROVIDER]  Add OAuth or API-key credential (nous, openai-codex, qwen-oauth, …)
nunmai auth list|remove P IDX|reset PROVIDER|status
```
Multiple credentials per provider form a pool that rotates automatically and skips exhausted keys.

### Other

```
nunmai desktop / gui        Native desktop app
nunmai dashboard            Web admin panel + embedded chat (--stop / --status)
nunmai proxy                OpenAI-compatible local proxy backed by an OAuth provider
nunmai portal               Quick setup / sign in via Nous Portal
nunmai kanban <verb>        Multi-agent work-queue board
nunmai project              Named multi-folder workspaces
nunmai skin list|use|set    Switch/tweak skins (see references/themes.md)
nunmai pets <verb>          Pet mascots (see references/petdex.md)
nunmai memory setup|status|off|reset   Memory provider
nunmai secrets bitwarden|onepassword   External secret stores
nunmai moa                  Mixture-of-Agents slots
nunmai hooks / security / backup / import / checkpoints / console
nunmai logs [-f] [errors]   View agent/error logs
nunmai send                 One-off message through a gateway platform
nunmai pairing / plugins / insights / journey / computer-use
nunmai acp                  ACP server (IDE integration)
nunmai completion bash|zsh|fish
nunmai update / uninstall / claw migrate
```

Plugin- and provider-supplied subcommands (e.g. `nunmai photon setup`) only appear once their plugin is installed/active.

### Where to Find Things

| Looking for... | Location |
|---|---|
| Config options | `nunmai config edit` · [Configuration docs](https://nunmai.in/docs/user-guide/configuration) |
| Tools / toolsets | `nunmai tools list` · [Tools reference](https://nunmai.in/docs/reference/tools-reference) |
| Skills catalog | `nunmai skills browse` · [Skills catalog](https://nunmai.in/docs/reference/skills-catalog) |
| Provider setup | `nunmai model` · [Providers guide](https://nunmai.in/docs/integrations/providers) |
| Env variables | `nunmai config env-path` · [Env vars reference](https://nunmai.in/docs/reference/environment-variables) |
| Gateway logs | `~/.nunmai/logs/gateway.log` (or `nunmai logs`) |
| Sessions | `nunmai sessions browse` (reads state.db) |
