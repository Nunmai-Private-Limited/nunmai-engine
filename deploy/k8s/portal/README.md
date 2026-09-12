# Nunmai Portal — the shared AI brain

One LiteLLM router per cluster, namespace `nunmai-portal`. It holds every
provider key (Claude, OpenAI, Gemini, Kimi/Moonshot, OpenRouter, …); customer
engines never see them. Each customer gets a *virtual key* with its own model
allow-list and monthly budget; the engine's config points at
`http://litellm.nunmai-portal.svc.cluster.local:4000/v1` with that key.

Model aliases (edit `litellm-config.yaml`):
- `nunmai-smart`  — best quality; several providers behind one name, load-balanced with fallbacks
- `nunmai-fast`   — cheap/fast
- `nunmai-code`   — coding

Install:
  kubectl create namespace nunmai-portal
  kubectl -n nunmai-portal create secret generic portal-provider-keys \
      --from-literal=ANTHROPIC_API_KEY=... --from-literal=OPENAI_API_KEY=... \
      --from-literal=GEMINI_API_KEY=... --from-literal=OPENROUTER_API_KEY=...
  kubectl -n nunmai-portal create secret generic portal-master \
      --from-literal=LITELLM_MASTER_KEY=sk-nunmai-$(openssl rand -hex 24) \
      --from-literal=POSTGRES_PASSWORD=$(openssl rand -hex 16)
  kubectl apply -k deploy/k8s/portal

Create a customer key (from your Mac, via the tunnel):
  deploy/k8s/portal/new-customer-key.sh acme 20    # $20/month budget
