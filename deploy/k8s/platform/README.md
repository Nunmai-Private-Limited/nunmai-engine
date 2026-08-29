# Platform TLS — wildcard *.platform.nunmai.in

Every customer gets <name>.platform.nunmai.in. One wildcard certificate from
Let's Encrypt (DNS-01 via Cloudflare) is installed as Traefik's default TLS
certificate, so per-customer Ingresses need no cert of their own.

DNS (Cloudflare, "DNS only" / grey cloud — Cloudflare's free edge cert does not
cover a second-level wildcard, and Traefik terminates TLS itself):
  A     platform.nunmai.in    -> 116.203.208.31
  A     *.platform.nunmai.in  -> 116.203.208.31
  AAAA  platform.nunmai.in    -> <server IPv6>   (optional)
  AAAA  *.platform.nunmai.in  -> <server IPv6>   (optional)

Cloudflare API token (My Profile -> API Tokens -> "Edit zone DNS" template,
scoped to zone nunmai.in):
  kubectl -n cert-manager create secret generic cloudflare-api-token --from-literal=api-token=<token>
  kubectl apply -f deploy/k8s/platform/
  kubectl -n kube-system get certificate platform-wildcard   # READY=True after ~1-2 min
