#!/usr/bin/env bash
# Nunmai Engine: move Node 1 from 0.20.6 to 0.21.2 — and back, in seconds, if anything looks wrong.
#
#   sudo bash /root/engine-cutover.sh --status     # what is where right now
#   sudo bash /root/engine-cutover.sh --stage      # build the new venv. NO client impact.
#   sudo bash /root/engine-cutover.sh --flip       # the swap. A few seconds of downtime.
#   sudo bash /root/engine-cutover.sh --rollback   # back to 0.20.6, same few seconds.
#
# WHY IT IS SHAPED LIKE THIS. The gateway unit hardcodes
# /usr/local/lib/nunmai-engine/venv/bin/python, so the version swap is done by turning that path into a
# SYMLINK to a versioned directory. Flipping is then one `ln -sfn`, and rolling back is the same command
# pointing the other way. The 0.20.6 tree is renamed, never deleted.
#
# WHAT IS AFFECTED. /usr/local/lib/nunmai-engine is the engine the PLATFORM runs: root's user services
# nunmai-gateway-default (the multiplexer that serves every organisation at /p/<slug>/) and
# nunmai-gateway-lumi. Every client org answers through these. ikhan's own install under
# ~ikhan/.nunmai is separate and is not touched.
set -euo pipefail

OLD=/usr/local/lib/nunmai-engine-0.20.6
NEW=/usr/local/lib/nunmai-engine-0.21.2
LINK=/usr/local/lib/nunmai-engine
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/0}

[ "$(id -u)" -eq 0 ] || { echo "run me with sudo" >&2; exit 1; }

running_units() {
  systemctl --user list-units --type=service --state=running --no-legend 'nunmai-gateway-*' 2>/dev/null | awk '{print $1}'
}
show_units() {
  systemctl --user list-units --type=service --all --no-legend 'nunmai-gateway-*' 2>/dev/null | sed 's/^/  /'
}
health() {
  curl -s -m 25 http://127.0.0.1:8700/health \
    | python3 -c 'import sys,json; e=(json.load(sys.stdin) or {}).get("engine") or {}; print("  engine:", e.get("platform"), e.get("version"), "| status", e.get("status"))' \
    2>/dev/null || echo "  control API did not answer"
}

case "${1:-}" in

--status)
  if [ -L "$LINK" ]; then
    echo "link:  $LINK -> $(readlink -f "$LINK")"
  else
    echo "link:  $LINK is still a plain directory (no flip has happened yet)"
  fi
  for d in "$LINK" "$OLD" "$NEW"; do
    [ -d "$d" ] || continue
    v=$(grep -m1 '^version' "$d/pyproject.toml" 2>/dev/null | cut -d'"' -f2)
    echo "tree:  $d  version ${v:-?}  venv:$([ -x "$d/venv/bin/python" ] && echo yes || echo NO)"
  done
  echo "gateways:"; show_units
  echo "live:"; health
  ;;

--stage)
  # Everything here happens while 0.20.6 keeps serving. Nothing is swapped, nothing restarts.
  [ -d "$NEW" ] || { echo "$NEW is missing — rsync the tree up first (step 1)" >&2; exit 1; }

  # The unit puts <engine>/node_modules/.bin on PATH, so the new tree needs one. Copying the existing
  # one is faster and less risky than a fresh npm install, and it is the same engine major.
  if [ ! -d "$NEW/node_modules" ] && [ -d "$LINK/node_modules" ]; then
    echo "copying node_modules from the running install..."
    cp -a "$LINK/node_modules" "$NEW/node_modules"
  fi

  echo "building the venv for 0.21.2 (the running engine is untouched)..."
  # Build it from the RUNNING venv's own interpreter. That pins the new venv to the same base Python
  # without guessing a binary name — python3.11 is not on root's PATH over ssh.
  [ -x "$NEW/venv/bin/python" ] || "$LINK/venv/bin/python" -m venv "$NEW/venv"
  "$NEW/venv/bin/python" -m pip install --upgrade pip setuptools wheel

  # The EXTRAS matter as much as the base install. 0.20.6's venv carries 58 packages that a bare
  # `pip install -e .` does not pull, and they are not decorative: mcp is every client connector,
  # google is Workspace and Meet, tts-premium is the agent voice, voice is local transcription.
  # Flipping without these would leave the gateway importing half a platform.
  EXTRAS=mcp,anthropic,tts-premium,voice,google,bedrock,edge-tts,acp,wecom,youtube,web
  echo "installing with extras: $EXTRAS"
  "$NEW/venv/bin/python" -m pip install -e "$NEW[$EXTRAS]"

  echo
  echo "checking the new engine can start and names itself correctly..."
  NUNMAI_HOME=/root/.nunmai "$NEW/venv/bin/python" -m nunmai_cli.main --version
  echo
  echo "STAGED. 0.20.6 is still serving every organisation — nothing has changed for any client."
  echo "Next:  sudo bash $0 --flip"
  ;;

--verify)
  # Compare what the two venvs actually have installed. The flip is only safe when nothing the
  # running engine carries is absent from the new one.
  norm() { "$1/venv/bin/python" -m pip freeze 2>/dev/null \
             | grep -v '^-e ' | grep -v '^#' | sed 's/[=@].*//' \
             | tr '[:upper:]' '[:lower:]' | tr '_' '-' | sort -u; }
  norm "$LINK" > /tmp/eng-old.txt
  norm "$NEW"  > /tmp/eng-new.txt
  echo "packages: running=$(wc -l < /tmp/eng-old.txt)  staged=$(wc -l < /tmp/eng-new.txt)"
  # Known-benign absences. importlib-metadata (and its dep zipp) are the stdlib backport: 0.20.6 pulled
  # them in through an older opentelemetry pin, and nothing in the engine imports them — every call site
  # uses stdlib importlib.metadata, which Python 3.11 ships. Verified by grep across the tree.
  BENIGN='^(importlib-metadata|zipp)$'
  MISSING=$(comm -23 /tmp/eng-old.txt /tmp/eng-new.txt | grep -Ev "$BENIGN" || true)
  DROPPED=$(comm -23 /tmp/eng-old.txt /tmp/eng-new.txt | grep -E "$BENIGN" || true)
  [ -n "$DROPPED" ] && { echo "dropped, known-benign (stdlib backport, unused):"; echo "$DROPPED" | sed 's/^/  /'; }
  if [ -n "$MISSING" ]; then
    echo "STILL MISSING in 0.21.2 — do NOT flip yet:"; echo "$MISSING" | sed 's/^/  /'
    exit 1
  fi
  echo "OK — the staged engine has everything the running one has."
  ;;

--flip)
  # Refuse to flip on a guess: the package comparison must pass first.
  bash "$0" --verify || { echo "aborting the flip" >&2; exit 1; }
  [ -x "$NEW/venv/bin/python" ] || { echo "not staged yet — run --stage first" >&2; exit 1; }

  # First flip only: turn the real directory into a versioned one plus a symlink. Running processes hold
  # their files by inode, so the rename does not disturb them.
  if [ ! -L "$LINK" ]; then
    echo "converting $LINK into a symlink (first flip only)..."
    mv "$LINK" "$OLD"
    ln -sfn "$OLD" "$LINK"
  fi

  mapfile -t RUN < <(running_units)
  echo "stopping: ${RUN[*]:-none}"
  for u in ${RUN[@]+"${RUN[@]}"}; do systemctl --user stop "$u" || true; done

  ln -sfn "$NEW" "$LINK"
  echo "link now: $LINK -> $(readlink -f "$LINK")"

  for u in ${RUN[@]+"${RUN[@]}"}; do systemctl --user start "$u" || true; done
  sleep 10
  echo "gateways:"; show_units
  echo
  echo "--- what the platform sees (this is the real test) ---"
  health
  echo
  echo "Now send one message in the portal. If anything is wrong:"
  echo "  sudo bash $0 --rollback"
  ;;

--rollback)
  [ -d "$OLD" ] || { echo "no 0.20.6 tree at $OLD — nothing to roll back to" >&2; exit 1; }
  mapfile -t RUN < <(running_units)
  for u in ${RUN[@]+"${RUN[@]}"}; do systemctl --user stop "$u" || true; done
  ln -sfn "$OLD" "$LINK"
  for u in ${RUN[@]+"${RUN[@]}"}; do systemctl --user start "$u" || true; done
  sleep 10
  echo "rolled back to $(readlink -f "$LINK")"
  health
  ;;

*)
  echo "usage: sudo bash $0 --status | --stage | --verify | --flip | --rollback" >&2
  exit 2 ;;
esac
