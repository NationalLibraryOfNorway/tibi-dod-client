"""The TUI's player bar through Textual's Pilot, with a fake Player (ADR 0003).

The bar drives the same `Playback` as `dod play` over the `Player` seam; no
audio device is ever opened. Books are synthetic files under a pytest tmp path,
played from disk only (ADR 0009).
"""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from textual.pilot import Pilot
from textual.widgets import Static

from dod.application import (
    MemorySessionStore,
    OpenPlayer,
    PlayerUnavailable,
    SessionManager,
)
from dod.domain.service import Exchange, Observation, Password
from dod.domain.v1 import ContentItem, ContentList
from dod.infrastructure import InMemoryService
from dod.presentation import ActivityLog, DownloadSettings, create_tui
from support._fake_player import FakePlayer

URL = "https://dod.example.org/service"
USER = "synthetic-user"
PASSWORD = "synthetic-secret"
MASTER = (
    b'<smil><head/><body><seq><ref src="b.smil"/><ref src="a.smil"/></seq>'
    b"</body></smil>"
)
SMIL_A = b'<smil><body><seq><par><audio src="a.wav"/></par></seq></body></smil>'
SMIL_B = (
    b'<smil><body><seq><par><seq><audio src="b.wav" clip-begin="npt=0s" '
    b'clip-end="npt=4s"/></seq></par><par><audio src="b.wav" clip-begin="npt=4s" '
    b'clip-end="npt=8s"/></par></seq></body></smil>'
)
COOKIE = "synthetic-cookie-value"
DURATIONS = {"a.wav": 60.0, "b.wav": 8.0}
BOOK = {
    "master.smil": MASTER,
    "a.smil": SMIL_A,
    "b.smil": SMIL_B,
    "a.wav": b"synthetic-a",
    "b.wav": b"synthetic-b",
}
SHELF = ContentList(
    id="issued", total_items=1, items=(ContentItem(id="book0", label="Book 0"),)
)


class Rig:
    def __init__(
        self,
        tmp_path: Path,
        *,
        on_disk: bool = True,
        open_player: OpenPlayer | None = None,
    ) -> None:
        self.service = InMemoryService()
        self.service.add_user(USER, PASSWORD)
        self.service.offer_catalog([SHELF], [])
        self.books = tmp_path / "books"
        if on_disk:
            (self.books / "book0").mkdir(parents=True)
            for name, body in BOOK.items():
                (self.books / "book0" / name).write_bytes(body)
        self.player = FakePlayer(DURATIONS)
        self.open_player: OpenPlayer = open_player or (lambda: self.player)
        self.log = ActivityLog()
        self.manager = SessionManager(
            self.log.wrap(lambda url: self.service.open_port()),
            MemorySessionStore(),
            URL,
            USER,
            lambda: Password(PASSWORD),
        )
        self.settings = DownloadSettings(
            service_url=URL, directory_for=lambda content_id: self.books / content_id
        )

    def drive(self, scenario: Callable[[Pilot[None]], Awaitable[None]]) -> None:
        async def run() -> None:
            app = create_tui(
                self.manager,
                self.settings,
                open_player=self.open_player,
                log=self.log,
            )
            async with app.run_test(size=(100, 30)) as pilot:
                await settle(pilot)
                await scenario(pilot)

        asyncio.run(run())


async def settle(pilot: Pilot[None]) -> None:
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


def bar(pilot: Pilot[None]) -> str:
    return str(pilot.app.screen.query_one("#player", Static).render())


def test_play_starts_the_selected_book_from_the_first_file(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    shown: list[str] = []

    async def scenario(pilot: Pilot[None]) -> None:
        await pilot.press("P")
        await settle(pilot)
        shown.append(bar(pilot))

    rig.drive(scenario)

    assert rig.player.started == [("b.wav", 0.0)]
    assert "playing" in shown[0]
    assert "file 1 of 2: b.wav" in shown[0]
    assert "00:00:00 of 00:01:08" in shown[0]


def played(rig: Rig, *keys: str, advance: float = 0.0) -> str:
    """The bar after `P`, `advance` seconds of playing and then `keys`."""
    shown: list[str] = []

    async def scenario(pilot: Pilot[None]) -> None:
        await pilot.press("P")
        await settle(pilot)
        rig.player.advance(advance)
        await pilot.press(*keys)
        await pilot.pause()
        shown.append(bar(pilot))

    rig.drive(scenario)
    return shown[0]


def test_pause_stops_the_player_and_resume_continues_from_the_same_place(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)

    paused = played(rig, "space", advance=2.0)

    assert "paused" in paused
    assert not rig.player.playing

    resumed = played(Rig(tmp_path / "again"), "space", "space", advance=2.0)

    assert "paused" not in resumed
    assert "playing" in resumed


def test_resume_restarts_the_file_at_the_paused_offset(tmp_path: Path) -> None:
    rig = Rig(tmp_path)

    played(rig, "space", "space", advance=2.0)

    assert rig.player.started == [("b.wav", 0.0), ("b.wav", 2.0)]


def test_stop_ends_the_playing(tmp_path: Path) -> None:
    rig = Rig(tmp_path)

    shown = played(rig, "x", advance=1.0)

    assert not rig.player.playing
    assert "stopped" in shown


def test_next_and_previous_move_between_clips(tmp_path: Path) -> None:
    rig = Rig(tmp_path)

    played(rig, "right_square_bracket", "left_square_bracket", advance=1.0)

    assert rig.player.started == [("b.wav", 0.0), ("b.wav", 4.0), ("b.wav", 0.0)]


def test_forward_and_back_jump_thirty_seconds_across_files(tmp_path: Path) -> None:
    rig = Rig(tmp_path)

    shown = played(rig, "full_stop", advance=0.0)

    assert rig.player.started[-1] == ("a.wav", 22.0)
    assert "file 2 of 2: a.wav" in shown
    assert "00:00:30 of 00:01:08" in shown

    played(rig, "full_stop", "comma", advance=0.0)

    assert rig.player.started[-1] == ("b.wav", 0.0)


def test_the_bar_follows_the_player_while_it_plays(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    shown: list[str] = []

    async def scenario(pilot: Pilot[None]) -> None:
        await pilot.press("P")
        await settle(pilot)
        rig.player.advance(5.0)
        await pilot.pause(0.6)
        shown.append(bar(pilot))

    rig.drive(scenario)

    assert "00:00:05 of 00:01:08" in shown[0]


def test_a_book_that_is_not_on_disk_is_not_played_or_streamed(tmp_path: Path) -> None:
    rig = Rig(tmp_path, on_disk=False)

    shown = played(rig)

    assert "no local copy" in shown
    assert "download it first" in shown
    assert rig.player.started == []


def test_a_book_with_audio_missing_is_not_played_or_streamed(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    (rig.books / "book0" / "a.wav").unlink()

    shown = played(rig)

    assert "1 audio file(s) of the book are not on disk" in shown
    assert rig.player.started == []


def test_without_an_audio_player_the_tui_still_browses_and_says_why(
    tmp_path: Path,
) -> None:
    def unavailable() -> FakePlayer:
        raise PlayerUnavailable("audio playback needs miniaudio")

    rig = Rig(tmp_path, open_player=unavailable)

    shown = played(rig)

    assert "audio playback needs miniaudio" in shown


def test_a_file_the_player_cannot_decode_is_refused_with_an_observation(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    rig.player.durations.pop("a.wav")
    logged: list[str] = []

    async def scenario(pilot: Pilot[None]) -> None:
        await pilot.press("P")
        await settle(pilot)
        logged.append(bar(pilot))
        await pilot.press("L")
        await settle(pilot)
        logged.append(str(pilot.app.screen.query_one("#log", Static).render()))

    rig.drive(scenario)

    assert "a.wav cannot be played" in logged[0]
    assert rig.player.started == []
    assert "observation audio-format" in logged[1]


def test_the_log_panel_shows_exchanges_and_observations_masked_and_plain(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    rig.log.record(
        Exchange(
            method="POST",
            url="https://dod.example.org/service",
            request_headers=(("Cookie", f"session={COOKIE}"),),
            request_body=f"<logOn><password>{PASSWORD}</password></logOn>",
            status=200,
            response_headers=(("Set-Cookie", f"session={COOKIE}; Path=/"),),
            response_body="<ok/>\x1b[31m",
        )
    )
    rig.log.observe((Observation("odd", "a \x1b[2Jmessage [bold]kept[/bold]"),))
    shown: list[str] = []

    async def scenario(pilot: Pilot[None]) -> None:
        await pilot.press("L")
        await pilot.pause()
        shown.append(str(pilot.app.screen.query_one("#log", Static).render()))
        await pilot.press("escape")
        await pilot.pause()
        shown.append(type(pilot.app.screen).__name__)

    rig.drive(scenario)

    log = shown[0]
    assert "exchange: POST https://dod.example.org/service -> 200" in log
    assert "  > Cookie: session=***[" in log
    assert "<password>***[" in log
    assert COOKIE not in log
    assert PASSWORD not in log
    assert "observation odd: a  [2Jmessage [bold]kept[/bold]" in log
    assert "\x1b" not in log
    assert shown[1] == "CatalogScreen"


def test_the_log_panel_shows_the_calls_the_screens_make(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    shown: list[str] = []

    async def scenario(pilot: Pilot[None]) -> None:
        await pilot.press("L")
        await pilot.pause()
        shown.append(str(pilot.app.screen.query_one("#log", Static).render()))

    rig.drive(scenario)

    assert shown[0].count("exchange: POST") >= 2
