# Nunmai Engine 0.21.2 — upgraded, tested, NOT deployed

This tree is the next Nunmai Engine: upstream v2026.9.11 (0.21.2), rebranded, with our own work ported
onto it. **Nothing here is live.** Node 1 still runs 0.20.6.

Preserved out of a session scratchpad on 2026-09-13 — the previous session lost its equivalent work
exactly that way, so do not move this back into /tmp.

## What it is

    git log --oneline          # 17 commits: the rebranded 0.21.2 base + our ports

Verified: 267 unit tests green; the ported tree fails on exactly the same tests as the untouched base
(zero regressions); and a live smoke test in which the gateway boots, a real chat turn completes, and the
model router routes end to end.

## Rebuilding the test venv (seconds — only 5 declared dependencies)

    uv venv --python 3.11 .venv-test
    uv pip install --python .venv-test/bin/python -e . pytest pytest-asyncio pytest-timeout pyyaml aiohttp
    .venv-test/bin/python -m pytest tests/plugins/test_model_router_plugin.py -q

Do NOT run `setup-nunmai.sh` for this — it symlinks `nunmai` into a user bin dir and can run the setup
wizard against the host.

## Re-running the smoke test

`smoke-kit/stub_model.py` is a stub OpenAI-compatible server; it **must** speak SSE, because the engine
always streams from providers. `smoke-kit/config.example.yaml` is the isolated config it was driven with.

    python smoke-kit/stub_model.py 8931 &
    export NUNMAI_HOME=/some/scratch/home          # never the real ~/.nunmai
    NUNMAI_HOME=$NUNMAI_HOME API_SERVER_KEY=$(openssl rand -hex 32) \
      .venv-test/bin/python -m nunmai_cli.main gateway run

`API_SERVER_KEY` must be a strong ENV secret — config.yaml is not enough, the gateway refuses to start
even on a loopback bind.

Testing the router: a tier pointing at the SAME provider already serving the turn is correctly ignored
(our f8c6136, "never swap one model of the tier's provider for another"). Point it at a genuinely
different provider or the router will look broken when it is working.

## Before this replaces anything on Node 1

- Confirm whether 0.20.6 is actually exposed to the multi-profile isolation bugs 0.21.2 fixes. Nunmai
  runs every client org as a profile under one multiplexer gateway, which is the shape those bugs bite.
- Check whether the approvals blocker (per-profile MCP tokens vs the root store the multiplexer reads) is
  fixed upstream before hand-patching it.
- Still unported, deliberately: the uninstall cluster and the install scripts. Both sides rewrote the
  same files, so they need re-implementation rather than a merge. Nothing platform-side depends on them.

Full detail is in MemPalace, wing `Nunmai`, room `engine`.
