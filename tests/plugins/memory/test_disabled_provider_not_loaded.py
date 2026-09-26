"""A user-installed memory provider parked in ``plugins.disabled`` must not load.

The Plugins hub / `nunmai plugins disable` write the deny-list; ``plugins/memory`` never read it, so
the UI said "disabled" while the provider kept loading at every agent init.
"""

from __future__ import annotations

import pytest

from plugins.memory import find_provider_dir, load_memory_provider

_PROVIDER = """
from agent.memory_provider import MemoryProvider

class P(MemoryProvider):
    name = "fakemem"
    def is_available(self):
        return True
    def initialize(self, *a, **kw):
        pass
    def get_tool_schemas(self):
        return []

def register(ctx):
    ctx.register_memory_provider(P())
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    nunmai_home = tmp_path / "nunmai-home"
    d = nunmai_home / "plugins" / "fakemem"
    d.mkdir(parents=True)
    (d / "plugin.yaml").write_text("name: fakemem-manifest\nkind: exclusive\n", encoding="utf-8")
    (d / "__init__.py").write_text(_PROVIDER, encoding="utf-8")
    monkeypatch.setenv("NUNMAI_HOME", str(nunmai_home))
    return nunmai_home


def test_disabled_user_provider_is_found_but_never_loaded(home):
    (home / "config.yaml").write_text("memory:\n  provider: fakemem\nplugins:\n  disabled: [fakemem-manifest]\n",
                                      encoding="utf-8")
    # Still discoverable (installed, so no catalog re-clone at startup) ...
    assert find_provider_dir("fakemem") == home / "plugins" / "fakemem"
    # ... but the deny-list wins over memory.provider, under the manifest-name spelling the CLI writes.
    assert load_memory_provider("fakemem") is None

    (home / "config.yaml").write_text("memory:\n  provider: fakemem\nplugins:\n  disabled: []\n", encoding="utf-8")
    assert load_memory_provider("fakemem") is not None
