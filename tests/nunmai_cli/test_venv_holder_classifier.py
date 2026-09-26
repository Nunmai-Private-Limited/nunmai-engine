"""Cross-platform unit tests for the venv-holder message classifier (#90778)."""

import pytest

from nunmai_cli.update_cmd import (
    _nunmai_holder_subcommand,
)


class TestHolderSubcommand:
    @pytest.mark.parametrize(
        ("cmdline", "expected"),
        [
            (r"C:\x\venv\Scripts\python.exe -m nunmai_cli.main serve --host 127.0.0.1", "serve"),
            (r"C:\x\venv\Scripts\python.exe -m nunmai_cli.main dashboard", "dashboard"),
            (r"python.exe -m nunmai_cli.main gateway run", "gateway"),
            # profile selector skipped; its VALUE must not become the subcommand
            (r"python -m nunmai_cli.main --profile serve gateway run", "gateway"),
            (r"python -m nunmai_cli.main -p work serve", "serve"),
            # 90778: flags containing subcommand words are not subcommands
            (r"python -m nunmai_cli.main kanban --preserve-cache", "kanban"),
            # 91869 review: EVERY top-level value flag must be skipped —
            # a flag VALUE equal to a subcommand must not become the label
            (r"python -m nunmai_cli.main --reasoning high serve", "serve"),
            (r"python -m nunmai_cli.main -m dashboard serve", "serve"),
            (r"python -m nunmai_cli.main -t browser,files gateway run", "gateway"),
            (r"python -m nunmai_cli.main --model=dashboard serve", "serve"),
            # -c consumes ONE value token; later bare tokens are (harmless,
            # unhinted) subcommand candidates — pin that shape honestly
            (r"python -m nunmai_cli.main -c mysession serve", "serve"),
            (r"C:\bin\nunmai.exe dashboard", "dashboard"),
            (r"/usr/local/bin/nunmai serve", "serve"),
            # no nunmai entry at all
            (r"python -c import time; time.sleep(3)", None),
            # entry but no subcommand
            (r"python -m nunmai_cli.main", None),
        ],
    )
    def test_parses_subcommand(self, cmdline, expected):
        assert _nunmai_holder_subcommand(cmdline) == expected


