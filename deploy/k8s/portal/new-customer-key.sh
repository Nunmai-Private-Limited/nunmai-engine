#!/usr/bin/env bash
# Usage: new-customer-key.sh <customer> [monthly_budget_usd] [models...]
# Creates a LiteLLM virtual key for a customer (through the SSH tunnel / port-forward).
set -euo pipefail
c="${1:?customer}"; budget="${2:-10}"; shift 2 || shift $# ; models="${*:-nunmai-smart nunmai-fast nunmai-code}"
MASTER="$(kubectl -n nunmai-portal get secret portal-master -o jsonpath='{.data.LITELLM_MASTER_KEY}' | base64 -d)"
kubectl -n nunmai-portal port-forward svc/litellm 14000:4000 >/dev/null 2>&1 & pf=$!; trap 'kill $pf' EXIT; sleep 2
models_json=$(printf '%s\n' $models | python3 -c 'import sys,json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))')
curl -s -X POST http://127.0.0.1:14000/key/generate -H "Authorization: Bearer $MASTER" -H "Content-Type: application/json" \
  -d "{\"key_alias\":\"cust-$c\",\"team_id\":\"cust-$c\",\"models\":$models_json,\"max_budget\":$budget,\"budget_duration\":\"30d\",\"metadata\":{\"customer\":\"$c\"}}" \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print("PORTAL_KEY for", "'"$c"'", "=", d.get("key") or d)'
