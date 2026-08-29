"""xAI (Grok) provider profile."""

from nunmai_cli import __version__ as _NUNMAI_VERSION
from providers import register_provider
from providers.base import ProviderProfile

xai = ProviderProfile(
    name="xai",
    aliases=("grok", "x-ai", "x.ai"),
    api_mode="codex_responses",
    env_vars=("XAI_API_KEY",),
    base_url="https://api.x.ai/v1",
    auth_type="api_key",
    default_headers={"User-Agent": f"Nunmai-Agent/{_NUNMAI_VERSION}"},
)

register_provider(xai)
