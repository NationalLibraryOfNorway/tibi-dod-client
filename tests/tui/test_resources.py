"""The TUI's resource screen and download progress through Textual's Pilot.

Driven headless against the in-memory Service (ADR 0003, ADR 0004). Downloads
reuse the `download` use case; the screen only shows what it reports. Books,
files and users are synthetic and every file goes under a pytest tmp path.
"""

import asyncio
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from textual.pilot import Pilot
from textual.widgets import DataTable, Static

from dod.application import MemorySessionStore, SessionManager
from dod.domain.service import Password
from dod.domain.v1 import (
    ContentItem,
    ContentList,
    ContentResource,
    ResourceSink,
    ServicePort,
)
from dod.infrastructure import InMemoryService
from dod.presentation import DownloadSettings, create_tui

URL = "https://dod.example.org/service"
USER = "synthetic-user"
PASSWORD = "synthetic-secret"
SHELF = ContentList(
    id="issued",
    total_items=1,
    items=(ContentItem(id="book0", label="Book 0"),),
)
BODIES = {"files/a.txt": b"hello", "files/b.txt": b"0123456789"}


def entry(service: InMemoryService, name: str, local_uri: str, size: int) -> Any:
    return ContentResource(
        uri=service.file_url(f"files/{name}"),
        mime_type="text/plain",
        size=size,
        local_uri=local_uri,
    )


class World:
    def __init__(
        self,
        tmp_path: Path,
        *,
        resources: list[ContentResource] | None = None,
        issued: bool = True,
        wrap: Callable[[ServicePort], ServicePort] = lambda port: port,
        settings: bool = True,
        trust_host: bool = True,
    ) -> None:
        self.service = InMemoryService()
        self.service.add_user(USER, PASSWORD)
        self.service.offer_catalog([SHELF], [])
        for path, body in BODIES.items():
            self.service.offer_file(path, body)
        self.service.offer_resources(
            "book0",
            resources
            if resources is not None
            else [
                entry(self.service, "a.txt", "a.txt", 5),
                entry(self.service, "b.txt", "sub/b.txt", 10),
            ],
            issued=issued,
        )
        self.books = tmp_path / "books"
        self.manager = SessionManager(
            lambda url: wrap(self.service.open_port()),
            MemorySessionStore(),
            URL,
            USER,
            lambda: Password(PASSWORD),
        )
        self.settings = (
            DownloadSettings(
                service_url=URL,
                directory_for=lambda content_id: self.books / content_id,
                trust_host=trust_host,
            )
            if settings
            else None
        )

    def drive(self, scenario: Callable[[Pilot[None]], Awaitable[None]]) -> None:
        async def run() -> None:
            app = create_tui(self.manager, self.settings)
            async with app.run_test(size=(100, 30)) as pilot:
                await settle(pilot)
                await pilot.press("f")
                await settle(pilot)
                await scenario(pilot)

        asyncio.run(run())


async def settle(pilot: Pilot[None]) -> None:
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


def text(pilot: Pilot[None], selector: str) -> str:
    return str(pilot.app.screen.query_one(selector, Static).render())


def rows(pilot: Pilot[None]) -> list[tuple[str, ...]]:
    table = pilot.app.screen.query_one(DataTable)
    return [
        tuple(str(cell) for cell in table.get_row_at(n)) for n in range(table.row_count)
    ]


class _Chunked:
    """A port that hands a resource to the sink in two halves and waits between."""

    def __init__(
        self, port: ServicePort, half: threading.Event, go: threading.Event
    ) -> None:
        self._port = port
        self._half = half
        self._go = go

    def __getattr__(self, name: str) -> Any:
        return getattr(self._port, name)

    def fetch_resource(self, uri: str, sink: ResourceSink, *rest: Any) -> Any:
        def halves(chunk: bytes) -> None:
            middle = len(chunk) // 2
            sink(chunk[:middle])
            self._half.set()
            assert self._go.wait(timeout=10)
            sink(chunk[middle:])

        return self._port.fetch_resource(uri, halves, *rest)


def test_f_on_a_book_lists_its_files_without_fetching_any(tmp_path: Path) -> None:
    world = World(tmp_path)

    async def scenario(pilot: Pilot[None]) -> None:
        assert rows(pilot) == [("a.txt", "5", "-"), ("sub/b.txt", "10", "-")]
        assert text(pilot, "#heading") == "files of book0"
        assert not world.books.exists()

    world.drive(scenario)


def test_d_downloads_every_file_and_marks_each_as_downloaded(tmp_path: Path) -> None:
    world = World(tmp_path)

    async def scenario(pilot: Pilot[None]) -> None:
        await pilot.press("d")
        await settle(pilot)

        assert rows(pilot) == [
            ("a.txt", "5", "downloaded"),
            ("sub/b.txt", "10", "downloaded"),
        ]
        assert text(pilot, "#status") == "2 files in " + str(world.books / "book0")
        assert (world.books / "book0" / "a.txt").read_bytes() == b"hello"
        assert (world.books / "book0" / "sub" / "b.txt").read_bytes() == BODIES[
            "files/b.txt"
        ]

    world.drive(scenario)


def test_progress_is_shown_while_a_file_is_being_fetched(tmp_path: Path) -> None:
    half, go = threading.Event(), threading.Event()
    world = World(tmp_path, wrap=lambda port: _Chunked(port, half, go))

    async def scenario(pilot: Pilot[None]) -> None:
        try:
            await pilot.press("d")
            while not half.is_set():
                await pilot.pause(0.01)
            await pilot.pause()
            assert rows(pilot)[0] == ("a.txt", "5", "2 of 5 bytes")
            assert rows(pilot)[1][2] == "-"
            assert "downloading" in text(pilot, "#status")
        finally:
            go.set()
        await settle(pilot)
        assert [row[2] for row in rows(pilot)] == ["downloaded", "downloaded"]

    world.drive(scenario)


def test_c_cancels_the_download_and_leaves_no_partial_file(tmp_path: Path) -> None:
    half, go = threading.Event(), threading.Event()
    world = World(tmp_path, wrap=lambda port: _Chunked(port, half, go))

    async def scenario(pilot: Pilot[None]) -> None:
        await pilot.press("d")
        while not half.is_set():
            await pilot.pause(0.01)
        await pilot.press("c")
        go.set()
        await settle(pilot)

        assert [row[2] for row in rows(pilot)] == ["cancelled", "-"]
        assert text(pilot, "#status") == "cancelled; nothing was kept of a.txt"
        directory = world.books / "book0"
        assert not directory.exists() or list(directory.rglob("*")) == []

    world.drive(scenario)


def test_a_failed_download_names_the_file_and_the_reason(tmp_path: Path) -> None:
    world = World(tmp_path)
    resources = [
        entry(world.service, "a.txt", "a.txt", 5),
        entry(world.service, "gone.txt", "gone.txt", 3),
        entry(world.service, "b.txt", "sub/b.txt", 10),
    ]
    world.service.offer_resources("book0", resources)

    async def scenario(pilot: Pilot[None]) -> None:
        await pilot.press("d")
        await settle(pilot)

        assert [row[2] for row in rows(pilot)] == ["downloaded", "failed", "-"]
        assert text(pilot, "#status").startswith(
            "failed gone.txt: fetch_resource: deviation: "
        )
        directory = world.books / "book0"
        assert sorted(p.name for p in directory.rglob("*") if p.is_file()) == ["a.txt"]

    world.drive(scenario)


def test_a_wrong_size_fails_the_file_and_keeps_nothing(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.service.offer_resources(
        "book0", [entry(world.service, "a.txt", "a.txt", 7)], issued=True
    )

    async def scenario(pilot: Pilot[None]) -> None:
        await pilot.press("d")
        await settle(pilot)

        assert [row[2] for row in rows(pilot)] == ["failed"]
        assert "5 bytes received, the Service announced 7" in text(pilot, "#status")
        assert not list((world.books / "book0").rglob("*.*"))

    world.drive(scenario)


def test_content_that_is_not_issued_shows_the_fault_and_is_never_issued(
    tmp_path: Path,
) -> None:
    world = World(tmp_path, issued=False)

    async def scenario(pilot: Pilot[None]) -> None:
        assert rows(pilot) == []
        assert text(pilot, "#status") == (
            "getContentResources: fault invalidParameter: content is not issued"
        )
        await pilot.press("d")
        await settle(pilot)
        assert not world.books.exists()
        assert "getContentResources: fault invalidParameter" in text(pilot, "#status")

    world.drive(scenario)


def test_an_unsafe_local_uri_stops_the_download_before_anything_is_written(
    tmp_path: Path,
) -> None:
    world = World(tmp_path)
    world.service.offer_resources(
        "book0",
        [
            entry(world.service, "a.txt", "a.txt", 5),
            entry(world.service, "b.txt", "../escape.txt", 10),
        ],
    )

    async def scenario(pilot: Pilot[None]) -> None:
        await pilot.press("d")
        await settle(pilot)

        assert "not safe to download" in text(pilot, "#status")
        assert not world.books.exists()
        assert not (tmp_path / "escape.txt").exists()

    world.drive(scenario)


def test_another_host_is_refused_without_trust_host(tmp_path: Path) -> None:
    world = World(tmp_path, trust_host=False)

    async def scenario(pilot: Pilot[None]) -> None:
        await pilot.press("d")
        await settle(pilot)

        assert "is not on the Service's own host" in text(pilot, "#status")
        assert not world.books.exists()

    world.drive(scenario)


def test_without_a_target_directory_d_explains_and_fetches_nothing(
    tmp_path: Path,
) -> None:
    world = World(tmp_path, settings=False)

    async def scenario(pilot: Pilot[None]) -> None:
        await pilot.press("d")
        await settle(pilot)

        assert "no directory to download to" in text(pilot, "#status")
        assert not world.books.exists()

    world.drive(scenario)


def test_names_from_the_service_are_shown_literally(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.service.offer_resources(
        "book0",
        [entry(world.service, "a.txt", "[red]a\x1b[2J.txt", 5)],
    )

    async def scenario(pilot: Pilot[None]) -> None:
        await pilot.press("d")
        await settle(pilot)

        assert rows(pilot)[0][0] == "[red]a [2J.txt"
        assert "not safe to download" in text(pilot, "#status")

    world.drive(scenario)


def test_escape_goes_back_to_the_shelf(tmp_path: Path) -> None:
    world = World(tmp_path)

    async def scenario(pilot: Pilot[None]) -> None:
        await pilot.press("escape")
        await pilot.pause()
        assert pilot.app.screen.query_one(DataTable).row_count == 1
        assert text(pilot, "#summary") == "list issued: items 0-0 of 1"

    world.drive(scenario)
