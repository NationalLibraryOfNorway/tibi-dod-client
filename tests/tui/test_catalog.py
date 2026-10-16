"""The TUI's shelf/catalog screen through Textual's Pilot (ADR 0003, ADR 0004).

The TUI is driven headless against the in-memory Service; no terminal and no
network are involved. Users, passwords and books are synthetic.
"""

import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from textual.pilot import Pilot
from textual.widgets import DataTable, Input, Static

from dod.application import MemorySessionStore, SessionManager
from dod.domain.service import Password, TransportError
from dod.domain.v1 import ContentItem, ContentList, ContentMetadata, ServicePort
from dod.infrastructure import InMemoryService
from dod.presentation import create_tui

URL = "https://dod.example.org/service"
USER = "synthetic-user"
PASSWORD = "synthetic-secret"
ITEMS = tuple(
    ContentItem(id=f"book{n}", label=f"Book {n}", lang="en") for n in range(3)
)
BOOK = ContentMetadata(
    title="Book 0",
    identifier="book0",
    format="Daisy 2.02",
    size=1234,
    creators=("Synthetic Author",),
    meta=(("synthetic:key", "value"),),
)
ISSUED = ContentList(id="issued", total_items=1, items=ITEMS[:1])
NEW = ContentList(id="new", total_items=3, items=ITEMS, label="New")


def world(
    lists: list[ContentList] | None = None,
    metadata: list[ContentMetadata] | None = None,
    wrap: Callable[[ServicePort], ServicePort] = lambda port: port,
    credentials: Callable[[], Password | None] = lambda: Password(PASSWORD),
) -> tuple[InMemoryService, SessionManager]:
    service = InMemoryService()
    service.add_user(USER, PASSWORD)
    service.offer_catalog(lists if lists is not None else [ISSUED, NEW], metadata or [])
    manager = SessionManager(
        lambda url: wrap(service.open_port()),
        MemorySessionStore(),
        URL,
        USER,
        credentials,
    )
    return service, manager


def drive(manager: SessionManager, scenario: Callable[[Pilot[None]], Awaitable[None]]):  # type: ignore[no-untyped-def]
    async def run() -> None:
        app = create_tui(manager)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()
            await scenario(pilot)

    asyncio.run(run())


def text(pilot: Pilot[None], selector: str) -> str:
    return str(pilot.app.screen.query_one(selector, Static).render())


def rows(pilot: Pilot[None]) -> list[tuple[str, str]]:
    table = pilot.app.screen.query_one(DataTable)
    return [
        (str(table.get_row_at(n)[0]), str(table.get_row_at(n)[1]))
        for n in range(table.row_count)
    ]


def test_the_shelf_is_shown_when_the_tui_starts() -> None:
    _, manager = world()

    async def scenario(pilot: Pilot[None]) -> None:
        assert rows(pilot) == [("book0", "Book 0")]

    drive(manager, scenario)


def test_another_list_is_chosen_by_its_id() -> None:
    _, manager = world()

    async def scenario(pilot: Pilot[None]) -> None:
        await pilot.press("l")
        pilot.app.screen.query_one(Input).value = "new"
        await pilot.press("enter")
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()

        assert [row[0] for row in rows(pilot)] == ["book0", "book1", "book2"]
        assert text(pilot, "#summary") == "list new: items 0-2 of 3"

    drive(manager, scenario)


def test_a_long_list_is_paged_with_n_and_p() -> None:
    items = tuple(ContentItem(id=f"b{n}", label=f"B {n}") for n in range(30))
    _, manager = world([ContentList(id="issued", total_items=30, items=items)])

    async def scenario(pilot: Pilot[None]) -> None:
        assert len(rows(pilot)) == 25
        assert text(pilot, "#summary") == "list issued: items 0-24 of 30"
        await pilot.press("n")
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
        assert [row[0] for row in rows(pilot)] == [f"b{n}" for n in range(25, 30)]
        assert text(pilot, "#summary") == "list issued: items 25-29 of 30"
        await pilot.press("n")
        await pilot.app.workers.wait_for_complete()
        await pilot.press("p")
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
        assert len(rows(pilot)) == 25

    drive(manager, scenario)


def test_enter_on_a_book_shows_its_metadata_and_escape_goes_back() -> None:
    _, manager = world(metadata=[BOOK])

    async def scenario(pilot: Pilot[None]) -> None:
        await pilot.press("enter")
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()

        shown = text(pilot, "#details")
        assert "title: Book 0" in shown
        assert "format: Daisy 2.02" in shown
        assert "creators: Synthetic Author" in shown
        assert "meta: synthetic:key=value" in shown

        await pilot.press("escape")
        await pilot.pause()
        assert rows(pilot) == [("book0", "Book 0")]

    drive(manager, scenario)


def test_a_fault_is_shown_as_the_service_answered_it() -> None:
    _, manager = world()

    async def scenario(pilot: Pilot[None]) -> None:
        await pilot.press("enter")
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()

        assert text(pilot, "#details") == (
            "getContentMetadata: fault invalidParameter: unknown content"
        )

    drive(manager, scenario)


def test_a_list_fault_clears_the_table_and_says_why() -> None:
    _, manager = world()

    async def scenario(pilot: Pilot[None]) -> None:
        await pilot.press("l")
        pilot.app.screen.query_one(Input).value = "nonexistent"
        await pilot.press("enter")
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()

        assert rows(pilot) == []
        assert text(pilot, "#status") == (
            "getContentList: fault invalidParameter: unknown list"
        )

    drive(manager, scenario)


def test_an_answer_against_the_specification_is_shown_as_a_deviation() -> None:
    service, manager = world()
    service.inject_deviation("getContentList")

    async def scenario(pilot: Pilot[None]) -> None:
        assert text(pilot, "#status").startswith("getContentList: deviation: ")

    drive(manager, scenario)


def test_an_expired_session_is_replaced_by_the_manager() -> None:
    service, manager = world()

    async def scenario(pilot: Pilot[None]) -> None:
        service.expire_sessions()
        await pilot.press("r")
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()

        assert rows(pilot) == [("book0", "Book 0")]

    drive(manager, scenario)


def test_without_credentials_an_expired_session_asks_for_a_logon() -> None:
    _, manager = world(credentials=lambda: None)

    async def scenario(pilot: Pilot[None]) -> None:
        assert rows(pilot) == []
        assert "dod logon" in text(pilot, "#status")

    drive(manager, scenario)


def test_a_failed_logon_names_the_step_that_failed() -> None:
    _, manager = world(credentials=lambda: Password("wrong-password"))

    async def scenario(pilot: Pilot[None]) -> None:
        assert text(pilot, "#status").startswith("could not log on: logOn: ")

    drive(manager, scenario)


class _NoAnswer:
    def __init__(self, port: ServicePort) -> None:
        self._port = port

    def __getattr__(self, name: str) -> Any:
        return getattr(self._port, name)

    def get_content_list(self, *args: Any) -> Any:
        raise TransportError("connection refused")


def test_no_answer_from_the_service_is_shown_and_does_not_end_the_tui() -> None:
    _, manager = world(wrap=lambda port: _NoAnswer(port))

    async def scenario(pilot: Pilot[None]) -> None:
        assert text(pilot, "#status") == "getContentList: no answer: connection refused"

    drive(manager, scenario)


def test_text_from_the_service_is_shown_literally() -> None:
    nasty = ContentItem(id="[bold]x[/bold]\x1b[2J", label="[red]Title\x07[/red]")
    _, manager = world([ContentList(id="issued", total_items=1, items=(nasty,))])

    async def scenario(pilot: Pilot[None]) -> None:
        assert rows(pilot) == [("[bold]x[/bold] [2J", "[red]Title [/red]")]

    drive(manager, scenario)


class _Slow:
    """A port whose getContentList waits until the test lets it answer."""

    def __init__(self, port: ServicePort, gate: threading.Event) -> None:
        self._port = port
        self._gate = gate

    def __getattr__(self, name: str) -> Any:
        return getattr(self._port, name)

    def get_content_list(self, *args: Any) -> Any:
        assert self._gate.wait(timeout=10)
        return self._port.get_content_list(*args)


def test_the_interface_stays_responsive_while_the_service_is_slow() -> None:
    gate = threading.Event()
    _, manager = world(wrap=lambda port: _Slow(port, gate))

    async def run() -> None:
        app = create_tui(manager)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            assert text(pilot, "#status") == "Loading..."
            await pilot.press("l")
            assert pilot.app.screen.focused is pilot.app.screen.query_one(Input)
            gate.set()
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()
            assert rows(pilot) == [("book0", "Book 0")]

    try:
        asyncio.run(run())
    finally:
        gate.set()
