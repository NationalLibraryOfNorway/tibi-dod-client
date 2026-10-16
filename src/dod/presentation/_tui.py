"""The terminal user interface: a thin layer over the application's use cases.

Every Service call goes through `SessionManager.call` (ADR 0005) in a thread
worker (ADR 0004), so the interface stays responsive while the Service answers;
the interface itself holds no Service logic. Downloads are the `download` use
case, in a worker, and the screen only shows the progress it reports; nothing
is fetched without the user pressing `d`, and content is never issued (ADR
0008). Everything the Service names
(ids, labels, metadata) is untrusted text: control characters are replaced and
no markup in it is interpreted (ADR 0008). The TUI is always masked (ADR 0007):
it has nothing that shows credentials.

Textual (MIT) is the optional `dod-client[tui]`; this module is only imported
when the interface is started.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from typing import Any, ClassVar

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult, ScreenStackError
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.coordinate import Coordinate
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Static

from dod.application import (
    CANCELLED,
    DownloadReport,
    DownloadRequest,
    FileOutcome,
    FileProgress,
    InitialisationFailed,
    OpenPlayer,
    Playback,
    SessionError,
    SessionManager,
    Step,
    download,
)
from dod.domain.service import Ok, TransportError
from dod.domain.v1 import ContentList, ContentMetadata, ContentResources, ServicePort
from dod.presentation._diagnostics import ActivityLog
from dod.presentation._launch import DownloadSettings
from dod.presentation._player_control import PlayerControl
from dod.presentation._text import (
    download_summary,
    log_lines,
    metadata_lines,
    plain,
    step_line,
)

_Bindings = list[Binding | tuple[str, str] | tuple[str, str, str]]
PAGE_SIZE = 25
SHELF = "issued"


class Gateway:
    """Calls the Service through the Session manager, one call at a time, and
    turns everything that can go wrong into a line of text."""

    def __init__(self, manager: SessionManager) -> None:
        self._manager = manager
        self._lock = threading.Lock()

    def call[T](
        self, operation: str, run: Callable[[ServicePort], Any]
    ) -> tuple[T | None, str | None]:
        """`(value, None)` when the Service answered Ok, else `(None, problem)`."""
        reply, problem = self.run(operation, lambda manager: manager.call(run))
        if reply is None:
            return None, problem
        if isinstance(reply, Ok):
            return reply.value, None
        return None, plain(step_line(Step(operation, reply)))

    def run[T](
        self, operation: str, use_case: Callable[[SessionManager], T]
    ) -> tuple[T | None, str | None]:
        """`(result, None)` of a use case that calls the manager itself, or
        `(None, problem)` when there was no answer or no Session."""
        with self._lock:
            try:
                return use_case(self._manager), None
            except TransportError as error:
                return None, f"{operation}: no answer: {plain(str(error))}"
            except InitialisationFailed as error:
                failed = next((s for s in error.report.steps if not s.succeeded), None)
                what = step_line(failed) if failed else "the initialisation failed"
                return None, f"could not log on: {plain(what)}"
            except SessionError as error:
                return None, plain(str(error))


class PlayerBar(Static):
    """The player bar: what plays and how far, on every screen."""

    def __init__(self) -> None:
        super().__init__("", id="player", markup=False)

    def on_mount(self) -> None:
        app = self.app
        if isinstance(app, DodTui):
            self.update(app.player_line())


class CatalogScreen(Screen[None]):
    """The shelf and the other content lists (`dod list`)."""

    BINDINGS: ClassVar[_Bindings] = [
        Binding("l", "choose_list", "List"),
        Binding("n", "next_page", "Next page"),
        Binding("p", "previous_page", "Previous page"),
        Binding("r", "reload", "Reload"),
        Binding("f", "files", "Files"),
    ]

    def __init__(self, gateway: Gateway, downloads: DownloadSettings | None) -> None:
        super().__init__()
        self._gateway = gateway
        self._downloads = downloads
        self._list_id = SHELF
        self._first = 0
        self._total = 0
        self._ids: list[str] = []
        self._request = 0

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(value=SHELF, placeholder="list id", id="list-id")
        yield Static("", id="summary", markup=False)
        yield DataTable(id="items", cursor_type="row")
        yield Static("", id="status", markup=False)
        yield PlayerBar()
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns("Id", "Label")
        self.query_one(DataTable).focus()
        self._load()

    def _load(self) -> None:
        self._request += 1
        self.query_one("#status", Static).update("Loading...")
        self._fetch(
            self._request, self._list_id, self._first, self._first + PAGE_SIZE - 1
        )

    @work(thread=True, group="service")
    def _fetch(self, request: int, list_id: str, first: int, last: int) -> None:
        value, problem = self._gateway.call(
            "getContentList", lambda port: port.get_content_list(list_id, first, last)
        )
        self.app.call_from_thread(self._show, request, value, problem)

    def _show(
        self, request: int, shown: ContentList | None, problem: str | None
    ) -> None:
        if request != self._request:
            return
        table = self.query_one(DataTable)
        table.clear()
        self._ids = []
        if shown is None:
            self.query_one("#summary", Static).update("")
            self.query_one("#status", Static).update(problem or "")
            return
        for item in shown.items:
            table.add_row(Text(plain(item.id)), Text(plain(item.label)))
            self._ids.append(item.id)
        self._total = shown.total_items
        last = self._first + len(shown.items) - 1
        self.query_one("#summary", Static).update(
            f"list {plain(shown.id)}: items {self._first}-{last} of {shown.total_items}"
            if shown.items
            else f"list {plain(shown.id)}: no items ({shown.total_items} in total)"
        )
        self.query_one("#status", Static).update("")

    @on(Input.Submitted, "#list-id")
    def _list_chosen(self, event: Input.Submitted) -> None:
        self._list_id = event.value.strip() or SHELF
        self._first = 0
        self._load()
        self.query_one(DataTable).focus()

    @on(DataTable.RowSelected)
    def _book_chosen(self, event: DataTable.RowSelected) -> None:
        if 0 <= event.cursor_row < len(self._ids):
            self.app.push_screen(
                MetadataScreen(self._gateway, self._ids[event.cursor_row])
            )

    def book_id(self) -> str | None:
        row = self.query_one(DataTable).cursor_row
        return self._ids[row] if 0 <= row < len(self._ids) else None

    def action_files(self) -> None:
        row = self.query_one(DataTable).cursor_row
        if 0 <= row < len(self._ids):
            self.app.push_screen(
                ResourcesScreen(self._gateway, self._ids[row], self._downloads)
            )

    def action_choose_list(self) -> None:
        self.query_one(Input).focus()

    def action_next_page(self) -> None:
        if self._first + PAGE_SIZE < self._total:
            self._first += PAGE_SIZE
            self._load()

    def action_previous_page(self) -> None:
        if self._first > 0:
            self._first = max(0, self._first - PAGE_SIZE)
            self._load()

    def action_reload(self) -> None:
        self._load()


class MetadataScreen(Screen[None]):
    """The metadata of one book (`dod metadata`)."""

    BINDINGS: ClassVar[_Bindings] = [Binding("escape", "back", "Back")]

    def __init__(self, gateway: Gateway, content_id: str) -> None:
        super().__init__()
        self._gateway = gateway
        self._content_id = content_id

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"metadata {plain(self._content_id)}", id="heading", markup=False)
        yield Static("Loading...", id="details", markup=False)
        yield PlayerBar()
        yield Footer()

    def on_mount(self) -> None:
        self._fetch(self._content_id)

    @work(thread=True, group="service")
    def _fetch(self, content_id: str) -> None:
        value, problem = self._gateway.call(
            "getContentMetadata", lambda port: port.get_content_metadata(content_id)
        )
        self.app.call_from_thread(self._show, value, problem)

    def _show(self, shown: ContentMetadata | None, problem: str | None) -> None:
        text = "\n".join(metadata_lines(shown)) if shown is not None else problem
        self.query_one("#details", Static).update(text or "")

    def book_id(self) -> str | None:
        return self._content_id

    def action_back(self) -> None:
        self.app.pop_screen()


class ResourcesScreen(Screen[None]):
    """The files of an issued book and their download (`dod resources`, `dod
    download`). The files are listed, never issued; `d` downloads them all."""

    BINDINGS: ClassVar[_Bindings] = [
        Binding("d", "download", "Download"),
        Binding("c", "cancel", "Cancel"),
        Binding("escape", "back", "Back"),
    ]
    PENDING = "-"

    def __init__(
        self, gateway: Gateway, content_id: str, downloads: DownloadSettings | None
    ) -> None:
        super().__init__()
        self._gateway = gateway
        self._content_id = content_id
        self._downloads = downloads
        self._names: list[str] = []
        self._cancel = threading.Event()
        self._busy = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"files of {plain(self._content_id)}", id="heading", markup=False)
        yield DataTable(id="files", cursor_type="row")
        yield Static("", id="status", markup=False)
        yield PlayerBar()
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns("File", "Size", "State")
        self.query_one("#status", Static).update("Loading...")
        self._list(self._content_id)

    @work(thread=True, group="service")
    def _list(self, content_id: str) -> None:
        value, problem = self._gateway.call(
            "getContentResources",
            lambda port: port.get_content_resources(content_id),
        )
        self._deliver(self._listed, value, problem)

    def _deliver(self, callback: Callable[..., None], *args: Any) -> None:
        """Hand a result to the screen from a worker; the screen may be gone."""
        with contextlib.suppress(RuntimeError):
            self.app.call_from_thread(callback, *args)

    def _listed(self, shown: ContentResources | None, problem: str | None) -> None:
        if not self.is_attached:
            return
        table = self.query_one(DataTable)
        table.clear()
        self._names = []
        for item in shown.resources if shown is not None else ():
            size = "-" if item.size is None else str(item.size)
            table.add_row(Text(plain(item.local_uri)), size, self.PENDING)
            self._names.append(item.local_uri)
        self.query_one("#status", Static).update(problem or "")

    def _state(self, local_uri: str, state: str) -> None:
        if local_uri in self._names:
            self.query_one(DataTable).update_cell_at(
                Coordinate(self._names.index(local_uri), 2), state
            )

    def action_download(self) -> None:
        status = self.query_one("#status", Static)
        directory = (
            self._downloads.directory_for(self._content_id)
            if self._downloads is not None
            else None
        )
        if self._downloads is None or directory is None:
            status.update(
                "no directory to download to: choose an Environment and a data "
                "directory (DOD_DATA_DIR) for `dod tui`"
            )
            return
        if self._busy:
            return
        self._busy = True
        self._cancel.clear()
        for name in self._names:
            self._state(name, self.PENDING)
        status.update("downloading...")
        request = DownloadRequest(
            content_id=self._content_id,
            directory=directory,
            service_url=self._downloads.service_url,
            trust_host=self._downloads.trust_host,
            insecure=self._downloads.insecure,
            progress=self._progress_from_worker,
            cancelled=self._cancel.is_set,
        )
        self._fetch(request, str(directory))

    @work(thread=True, group="download")
    def _fetch(self, request: DownloadRequest, directory: str) -> None:
        report, problem = self._gateway.run(
            "download", lambda manager: download(manager, request)
        )
        self._deliver(self._finished, report, problem, directory)

    def _progress_from_worker(self, progress: FileProgress) -> None:
        self._deliver(self._progress, progress)

    def _progress(self, progress: FileProgress) -> None:
        if not self.is_attached:
            return
        self._state(progress.local_uri, f"{progress.received} of {progress.size} bytes")
        self.query_one("#status", Static).update(
            f"downloading {plain(progress.local_uri)}"
        )

    def _finished(
        self, report: DownloadReport | None, problem: str | None, directory: str
    ) -> None:
        self._busy = False
        if not self.is_attached:
            return
        status = self.query_one("#status", Static)
        if report is None:
            status.update(problem or "")
            return
        for item in report.files:
            if item.outcome is FileOutcome.DOWNLOADED:
                self._state(item.local_uri, "downloaded")
            else:
                self._state(
                    item.local_uri,
                    "cancelled" if item.problem == CANCELLED else "failed",
                )
        stopped = self._cancel.is_set() and not any(
            item.problem == CANCELLED for item in report.files
        )
        status.update("cancelled" if stopped else download_summary(report, directory))

    def book_id(self) -> str | None:
        return self._content_id

    def action_cancel(self) -> None:
        if self._busy:
            self._cancel.set()

    def action_back(self) -> None:
        self._cancel.set()
        self.app.pop_screen()


class LogScreen(Screen[None]):
    """The log panel: the Exchanges and Observations of this run, masked."""

    BINDINGS: ClassVar[_Bindings] = [Binding("escape", "back", "Back")]

    def __init__(self, log: ActivityLog) -> None:
        super().__init__()
        self._log = log
        self._shown = -1

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Static("", id="log", markup=False)
        yield PlayerBar()
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()
        self.set_interval(0.5, self._refresh)

    def _refresh(self) -> None:
        entries = self._log.entries()
        if len(entries) == self._shown:
            return
        self._shown = len(entries)
        self.query_one("#log", Static).update(
            "\n".join(log_lines(entries)) or "nothing exchanged yet"
        )

    def action_back(self) -> None:
        self.app.pop_screen()


class DodTui(App[None]):
    """`dod tui`: browse the shelf, see a book's metadata, download its files,
    play a downloaded book and read the masked log."""

    TITLE = "dod"
    BINDINGS: ClassVar[_Bindings] = [
        Binding("q", "quit", "Quit"),
        Binding("P", "play", "Play"),
        Binding("space", "pause", "Pause/resume"),
        Binding("x", "stop", "Stop"),
        Binding("right_square_bracket", "next_clip", "Next"),
        Binding("left_square_bracket", "previous_clip", "Previous"),
        Binding("full_stop", "skip_forward", "+30 s"),
        Binding("comma", "skip_back", "-30 s"),
        Binding("L", "log", "Log"),
    ]
    TICK = 0.25

    def __init__(
        self,
        manager: SessionManager,
        downloads: DownloadSettings | None = None,
        open_player: OpenPlayer | None = None,
        log: ActivityLog | None = None,
    ) -> None:
        super().__init__()
        self._gateway = Gateway(manager)
        self._downloads = downloads
        self._activity = log if log is not None else ActivityLog()
        self._player = PlayerControl(
            open_player,
            downloads.directory_for if downloads is not None else None,
            self._activity,
        )

    def on_mount(self) -> None:
        self.push_screen(CatalogScreen(self._gateway, self._downloads))
        self.set_interval(self.TICK, self._tick)

    def on_unmount(self) -> None:
        self._player.close()

    def player_line(self) -> str:
        return self._player.line()

    def _show_player(self) -> None:
        line = self._player.line()
        try:
            bars = self.screen.query(PlayerBar)
        except ScreenStackError:
            return  # the timer fired while the app was shutting down
        for bar in bars:
            bar.update(line)

    def _tick(self) -> None:
        self._player.tick()
        self._show_player()

    def action_play(self) -> None:
        book = getattr(self.screen, "book_id", lambda: None)()
        if book is not None:
            self._player.note("preparing " + plain(book) + "...")
            self._show_player()
            self._prepare(book)

    @work(thread=True, group="play", exclusive=True)
    def _prepare(self, content_id: str) -> None:
        prepared = self._player.prepare(content_id)
        with contextlib.suppress(RuntimeError):
            self.call_from_thread(self._prepared, prepared)

    def _prepared(self, prepared: Playback | str) -> None:
        if isinstance(prepared, str):
            self._player.note(prepared)
        else:
            self._player.adopt(prepared)
        self._show_player()

    def _control(self, act: Callable[[], None]) -> None:
        act()
        self._show_player()

    def action_pause(self) -> None:
        self._control(self._player.toggle)

    def action_stop(self) -> None:
        self._control(self._player.stop)

    def action_next_clip(self) -> None:
        self._control(self._player.next)

    def action_previous_clip(self) -> None:
        self._control(self._player.previous)

    def action_skip_forward(self) -> None:
        self._control(self._player.forward)

    def action_skip_back(self) -> None:
        self._control(self._player.back)

    def action_log(self) -> None:
        if not isinstance(self.screen, LogScreen):
            self.push_screen(LogScreen(self._activity))
