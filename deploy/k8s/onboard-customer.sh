#!/usr/bin/env bash
# Usage: deploy/k8s/onboard-customer.sh <customer> [extra helm args...]
# Creates/updates namespace cust-<customer> from deploy/k8s/customers/<customer>.yaml
set -euo pipefail
c="${1:?customer name}"; shift || true
here="$(cd "$(dirname "$0")" && pwd)"
vals="$here/customers/$c.yaml"
[ -f "$vals" ] || { echo "missing $vals"; exit 1; }
helm upgrade --install "$c" "$here/nunmai-chart" -n "cust-$c" --create-namespace -f "$vals" --wait --timeout 10m "$@"
kubectl -n "cust-$c" get pods
