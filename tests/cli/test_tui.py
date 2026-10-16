"""`dod tui` through the CLI boundary (ADR 0007, ADR 0003).

Refusals run the installed console script. The wiring runs in-process against
the in-memory Service with the Textual app captured instead of run, and is then
driven headless with Pilot. Users, passwords and books are synthetic.
"""

import asyncio
import subprocess
import sys
from typing import Any

import pytest
from textual.app import App
from textual.widgets import DataTable
from typer.testing import CliRunner

from dod.application import ConfigFile
from dod.domain.v1 import ContentItem, ContentList
from dod.infrastructure import HttpFetcher, InMemoryService, parse_wsdl
from dod.presentation import create_app
from support import run_dod

URL = "https://dod.example.org/service"
USER = "synthetic-user"
PASSWORD = "synthetic-secret"


class NoConfig:
    def default_path(self) -> str:
        return "unused.toml"

    def read(self, path: str) -> ConfigFile | None:
        return None


@pytest.mark.parametrize("flag", ["--unmask", "--unmask-password"])
def test_the_tui_refuses_to_unmask(flag: str) -> None:
    result = run_dod("tui", flag, "--url", URL, "--username", USER)

    assert result.returncode == 2
    assert "always masked" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    "flags",
    [["--password-stdin"], ["--debug"], ["--no-session"], ["--format", "json"]],
)
def test_the_tui_refuses_options_that_need_the_terminal_or_the_screen(
    flags: list[str],
) -> None:
    result = run_dod("tui", *flags, "--url", URL, "--username", USER)

    assert result.returncode == 2
    assert result.stderr.startswith("error: ")


def test_without_textual_the_tui_exits_2_and_names_the_extra() -> None:
    # Textual is hidden from the interpreter, as on an install without the extra.
    script = (
        "import sys; sys.modules['textual'] = None; from dod.main import main; main()"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, "tui", "--url", URL, "--username", USER],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "dod-client[tui]" in result.stderr
    assert "Traceback" not in result.stderr


def test_tui_help_says_what_it_is_and_that_it_needs_no_player() -> None:
    result = run_dod("tui", "--help")

    text = " ".join(result.stdout.split())
    assert result.returncode == 0, result.stderr
    assert "dod-client[tui]" in text
    assert "always masked" in text
    assert "mpv" not in text


def test_the_tui_command_hands_the_stored_session_to_an_app_that_browses() -> None:
    memory = InMemoryService()
    memory.add_user(USER, PASSWORD)
    memory.offer_catalog(
        [
            ContentList(
                id="issued",
                total_items=1,
                items=(ContentItem(id="book0", label="Book 0"),),
            )
        ],
        [],
    )
    started: list[App[None]] = []
    app = create_app(
        lambda url: memory.open_port(),
        NoConfig(),
        HttpFetcher(),
        parse_wsdl,
        run_tui=started.append,
    )
    runner = CliRunner(env={"NO_COLOR": "1"})
    common = ["--url", URL, "--username", USER]
    logon = runner.invoke(app, ["logon", *common, "--password-stdin"], input=PASSWORD)
    assert logon.exit_code == 0, logon.output

    result = runner.invoke(app, ["tui", *common])

    assert result.exit_code == 0, result.output
    assert len(started) == 1

    async def browse() -> list[Any]:
        async with started[0].run_test() as pilot:
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()
            table = pilot.app.screen.query_one(DataTable)
            return [table.get_row_at(n) for n in range(table.row_count)]

    shown = asyncio.run(browse())
    assert [[str(cell) for cell in row] for row in shown] == [["book0", "Book 0"]]
