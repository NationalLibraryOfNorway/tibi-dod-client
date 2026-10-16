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
from textual.widgets import DataTable, Static
from typer.testing import CliRunner

from dod.application import ConfigFile, book_directory
from dod.domain.v1 import ContentItem, ContentList
from dod.infrastructure import HttpFetcher, InMemoryService, parse_wsdl
from dod.presentation import create_app
from support import PASSWORD, run_dod
from support._fake_player import FakePlayer

URL = "https://dod.example.org/service"
USER = "synthetic-user"


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


def test_tui_help_says_what_it_is_and_that_playing_needs_the_player_extra() -> None:
    result = run_dod("tui", "--help")

    text = " ".join(result.stdout.split())
    assert result.returncode == 0, result.stderr
    assert "dod-client[tui]" in text
    assert "always masked" in text
    assert "dod-client[play]" in text
    assert "never streamed" in text
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


def test_the_tui_command_downloads_nowhere_without_an_environment(
    tmp_path: Any,
) -> None:
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
        data_dir=tmp_path / "data",
        run_tui=started.append,
    )
    runner = CliRunner(env={"NO_COLOR": "1"})
    common = ["--url", URL, "--username", USER]
    runner.invoke(app, ["logon", *common, "--password-stdin"], input=PASSWORD)
    assert runner.invoke(app, ["tui", *common]).exit_code == 0

    async def press() -> str:
        async with started[0].run_test() as pilot:
            await pilot.app.workers.wait_for_complete()
            await pilot.press("f", "d")
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()
            return str(pilot.app.screen.query_one("#status").render())

    assert "no directory to download to" in asyncio.run(press())
    assert not (tmp_path / "data").exists()


class OneEnvironment:
    """A configuration file with the Environment `test`."""

    def default_path(self) -> str:
        return "config.toml"

    def read(self, path: str) -> ConfigFile | None:
        text = f'[environments.test]\nurl = "{URL}"\nusername = "{USER}"\n'
        return ConfigFile(path, text.encode(), False)


def test_the_tui_command_plays_a_downloaded_book_and_logs_what_it_exchanged(
    tmp_path: Any, capfd: Any
) -> None:
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
    book = book_directory(tmp_path / "data", "test", "book0")
    book.mkdir(parents=True)
    (book / "master.smil").write_bytes(
        b'<smil><body><seq><ref src="a.smil"/></seq></body></smil>'
    )
    (book / "a.smil").write_bytes(
        b'<smil><body><seq><par><audio src="a.wav"/></par></seq></body></smil>'
    )
    (book / "a.wav").write_bytes(b"synthetic")
    player = FakePlayer({"a.wav": 10.0})
    started: list[App[None]] = []
    app = create_app(
        lambda url: memory.open_port(),
        OneEnvironment(),
        HttpFetcher(),
        parse_wsdl,
        data_dir=tmp_path / "data",
        open_player=lambda: player,
        run_tui=started.append,
    )
    runner = CliRunner(env={"NO_COLOR": "1"})
    common = ["--env", "test"]
    runner.invoke(app, ["logon", *common, "--password-stdin"], input=PASSWORD)
    assert runner.invoke(app, ["tui", *common]).exit_code == 0

    async def play_and_read() -> list[str]:
        async with started[0].run_test(size=(100, 30)) as pilot:
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("P")
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()
            shown = [str(pilot.app.screen.query_one("#player", Static).render())]
            await pilot.press("L")
            await pilot.pause()
            shown.append(str(pilot.app.screen.query_one("#log", Static).render()))
            return shown

    capfd.readouterr()
    bar, log = asyncio.run(play_and_read())

    assert "playing" in bar and "file 1 of 1: a.wav" in bar
    assert player.started == [("a.wav", 0.0)]
    assert player.closed
    assert "exchange: POST" in log
    assert PASSWORD not in log
    assert capfd.readouterr().err == ""
