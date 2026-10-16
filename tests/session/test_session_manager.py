"""`SessionManager` against the in-memory Service, without any network (ADR 0005).

Users and passwords are synthetic. A recording `OpenPort` shows which
operations the manager sent, in order.
"""

from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from dod.application import (
    DownloadRequest,
    InitialisationFailed,
    MemorySessionStore,
    NoCredentialsError,
    SessionKey,
    SessionManager,
    download,
)
from dod.domain.service import (
    Exchange,
    Fault,
    FaultKind,
    Ok,
    Password,
    Reply,
    SessionState,
)
from dod.domain.v1 import (
    Announcement,
    BookmarkSet,
    ByteRange,
    ContentList,
    ContentMetadata,
    ContentResource,
    ContentResources,
    KeyExchangeObject,
    Questions,
    ReadingSystemAttributes,
    ResourceSink,
    ServiceAttributes,
    ServicePort,
    UserResponse,
)
from dod.infrastructure import InMemoryService

URL = "https://dod.example.org/service"
USER = "synthetic-user"
PASSWORD = Password("synthetic-secret")
KEY = SessionKey(URL, USER)


class Recording:
    """A port that records the operations sent through it."""

    def __init__(self, port: ServicePort, log: list[str]) -> None:
        self._port = port
        self._log = log

    @property
    def session(self) -> SessionState | None:
        return self._port.session

    def resume(self, session: SessionState) -> None:
        self._port.resume(session)

    def log_on(self, username: str, password: Password) -> Reply[bool]:
        self._log.append("logOn")
        return self._port.log_on(username, password)

    def log_off(self) -> Reply[bool]:
        self._log.append("logOff")
        return self._port.log_off()

    def get_service_attributes(self) -> Reply[ServiceAttributes]:
        self._log.append("getServiceAttributes")
        return self._port.get_service_attributes()

    def set_reading_system_attributes(
        self, attributes: ReadingSystemAttributes
    ) -> Reply[bool]:
        self._log.append("setReadingSystemAttributes")
        return self._port.set_reading_system_attributes(attributes)

    def get_service_announcements(self) -> Reply[tuple[Announcement, ...]]:
        self._log.append("getServiceAnnouncements")
        return self._port.get_service_announcements()

    def mark_announcements_as_read(self, ids: Sequence[str]) -> Reply[bool]:
        self._log.append("markAnnouncementsAsRead")
        return self._port.mark_announcements_as_read(ids)

    def issue_content(self, content_id: str) -> Reply[bool]:
        self._log.append("issueContent")
        return self._port.issue_content(content_id)

    def return_content(self, content_id: str) -> Reply[bool]:
        self._log.append("returnContent")
        return self._port.return_content(content_id)

    def get_bookmarks(self, content_id: str) -> Reply[BookmarkSet]:
        self._log.append("getBookmarks")
        return self._port.get_bookmarks(content_id)

    def set_bookmarks(self, content_id: str, bookmark_set: str) -> Reply[bool]:
        self._log.append("setBookmarks")
        return self._port.set_bookmarks(content_id, bookmark_set)

    def get_key_exchange_object(
        self, requested_key_name: str
    ) -> Reply[KeyExchangeObject]:
        self._log.append("getKeyExchangeObject")
        return self._port.get_key_exchange_object(requested_key_name)

    def get_questions(self, responses: Sequence[UserResponse]) -> Reply[Questions]:
        self._log.append("getQuestions")
        return self._port.get_questions(responses)

    def get_content_list(
        self, id: str, first_item: int, last_item: int
    ) -> Reply[ContentList]:
        self._log.append("getContentList")
        return self._port.get_content_list(id, first_item, last_item)

    def get_content_metadata(self, content_id: str) -> Reply[ContentMetadata]:
        self._log.append("getContentMetadata")
        return self._port.get_content_metadata(content_id)

    def get_content_resources(self, content_id: str) -> Reply[ContentResources]:
        self._log.append("getContentResources")
        return self._port.get_content_resources(content_id)

    def fetch_resource(
        self, uri: str, sink: ResourceSink, byte_range: ByteRange | None = None
    ) -> Reply[int]:
        self._log.append("fetch_resource")
        return self._port.fetch_resource(uri, sink, byte_range)

    def close(self) -> None:
        self._port.close()


class World:
    def __init__(self) -> None:
        self.service = InMemoryService()
        self.service.add_user(USER, PASSWORD.reveal())
        self.store = MemorySessionStore()
        self.log: list[str] = []

    def open_port(self, url: str) -> ServicePort:
        return Recording(self.service.open_port(), self.log)

    def manager(
        self, credentials: Callable[[], Password | None] = lambda: PASSWORD
    ) -> SessionManager:
        return SessionManager(self.open_port, self.store, URL, USER, credentials)


def read_attributes(port: ServicePort) -> Reply[ServiceAttributes]:
    return port.get_service_attributes()


@pytest.fixture
def world() -> World:
    return World()


def stored(world: World) -> SessionState | None:
    with world.store.lock(KEY) as slot:
        return slot.read()


def test_logon_runs_the_sequence_and_stores_the_session_afterwards(
    world: World,
) -> None:
    report = world.manager().logon(PASSWORD)

    assert report.succeeded
    assert world.log == [
        "logOn",
        "getServiceAttributes",
        "setReadingSystemAttributes",
    ]
    assert stored(world) is not None


def test_logon_logs_off_an_existing_session_first_and_replaces_it(
    world: World,
) -> None:
    world.manager().logon(PASSWORD)
    first = stored(world)
    world.log.clear()

    world.manager().logon(PASSWORD)

    assert world.log[0] == "logOff"
    assert world.log[1:] == [
        "logOn",
        "getServiceAttributes",
        "setReadingSystemAttributes",
    ]
    assert stored(world) not in (None, first)


def test_logon_ignores_a_failing_logoff_of_the_old_session(world: World) -> None:
    world.manager().logon(PASSWORD)
    world.service.inject_fault("logOff", "internalServerError", "boom")

    report = world.manager().logon(PASSWORD)

    assert report.succeeded
    assert stored(world) is not None


def test_a_failing_set_reading_system_attributes_logs_off_and_stores_nothing(
    world: World,
) -> None:
    world.service.inject_fault("setReadingSystemAttributes", "invalidParameter", "x")

    report = world.manager().logon(PASSWORD)

    assert not report.succeeded
    assert world.log[-1] == "logOff"
    assert stored(world) is None


def test_a_failed_logon_clears_the_session_it_replaced(world: World) -> None:
    world.manager().logon(PASSWORD)

    report = world.manager().logon(Password("wrong"))

    assert not report.succeeded
    assert stored(world) is None


def test_a_call_reuses_the_stored_session_without_initialising(
    world: World,
) -> None:
    world.manager().logon(PASSWORD)
    world.log.clear()

    reply = world.manager().call(read_attributes)

    assert isinstance(reply, Ok)
    assert world.log == ["getServiceAttributes"]


def test_a_call_without_a_stored_session_initialises_and_stores_one(
    world: World,
) -> None:
    reply = world.manager().call(read_attributes)

    assert isinstance(reply, Ok)
    assert world.log == [
        "logOn",
        "getServiceAttributes",
        "setReadingSystemAttributes",
        "getServiceAttributes",
    ]
    assert stored(world) is not None


def test_an_expired_session_is_replaced_once_and_the_operation_repeated(
    world: World,
) -> None:
    world.manager().logon(PASSWORD)
    old = stored(world)
    world.service.expire_sessions()
    world.log.clear()

    reply = world.manager().call(read_attributes)

    assert isinstance(reply, Ok)
    assert world.log == [
        "getServiceAttributes",
        "logOn",
        "getServiceAttributes",
        "setReadingSystemAttributes",
        "getServiceAttributes",
    ]
    assert stored(world) not in (None, old)


def test_relogin_happens_only_once_when_the_operation_expires_again(
    world: World,
) -> None:
    world.manager().logon(PASSWORD)
    world.log.clear()
    calls = 0
    exchange = Exchange("POST", URL, (), "", 500, (), "")

    def always_expired(port: ServicePort) -> Reply[ServiceAttributes]:
        nonlocal calls
        calls += 1
        return Fault(kind=FaultKind.NO_ACTIVE_SESSION, exchange=exchange)

    reply = world.manager().call(always_expired)

    assert isinstance(reply, Fault)
    assert calls == 2
    assert world.log.count("logOn") == 1


@pytest.mark.parametrize(
    "kind", ["invalidParameter", "internalServerError", "operationNotSupported"]
)
def test_other_faults_do_not_cause_a_relogin(world: World, kind: str) -> None:
    world.manager().logon(PASSWORD)
    world.service.inject_fault("getServiceAttributes", kind, "nope")
    world.log.clear()

    reply = world.manager().call(read_attributes)

    assert isinstance(reply, Fault)
    assert world.log == ["getServiceAttributes"]


def test_an_expired_session_without_credentials_asks_for_dod_logon(
    world: World,
) -> None:
    world.manager().logon(PASSWORD)
    world.service.expire_sessions()

    with pytest.raises(NoCredentialsError, match="dod logon"):
        world.manager(credentials=lambda: None).call(read_attributes)


def test_no_session_and_no_credentials_asks_for_dod_logon(world: World) -> None:
    with pytest.raises(NoCredentialsError, match="dod logon"):
        world.manager(credentials=lambda: None).call(read_attributes)
    assert world.log == []


def test_relogin_that_the_service_refuses_reports_the_failed_sequence(
    world: World,
) -> None:
    world.manager().logon(PASSWORD)
    world.service.expire_sessions()

    with pytest.raises(InitialisationFailed) as failed:
        world.manager(credentials=lambda: Password("wrong")).call(read_attributes)

    assert failed.value.report.steps[0].operation == "logOn"
    assert stored(world) is None


def test_ephemeral_mode_initialises_calls_and_logs_off_storing_nothing(
    world: World,
) -> None:
    manager = SessionManager.ephemeral(world.open_port, URL, USER, lambda: PASSWORD)

    reply = manager.call(read_attributes)

    assert isinstance(reply, Ok)
    assert world.log == [
        "logOn",
        "getServiceAttributes",
        "setReadingSystemAttributes",
        "getServiceAttributes",
        "logOff",
    ]
    assert stored(world) is None


def test_ephemeral_mode_ignores_a_stored_session(world: World) -> None:
    world.manager().logon(PASSWORD)
    world.log.clear()
    manager = SessionManager.ephemeral(world.open_port, URL, USER, lambda: PASSWORD)

    manager.call(read_attributes)

    assert world.log[0] == "logOn"
    assert stored(world) is not None


def test_logoff_ends_the_session_and_deletes_the_file(world: World) -> None:
    world.manager().logon(PASSWORD)
    world.log.clear()

    result = world.manager().logoff()

    assert world.log == ["logOff"]
    assert result.warning is None
    assert stored(world) is None


def test_logoff_deletes_the_file_even_when_the_service_fails(world: World) -> None:
    world.manager().logon(PASSWORD)
    world.service.inject_fault("logOff", "internalServerError", "boom")

    result = world.manager().logoff()

    assert result.warning is not None
    assert "internalServerError" in result.warning
    assert stored(world) is None


def test_logoff_without_a_session_sends_nothing(world: World) -> None:
    result = world.manager().logoff()

    assert world.log == []
    assert result.had_session is False


def test_clear_deletes_the_file_without_any_call(world: World) -> None:
    world.manager().logon(PASSWORD)
    world.log.clear()

    world.manager().clear()

    assert world.log == []
    assert stored(world) is None


def test_probe_checks_the_stored_session_with_one_reading_call(world: World) -> None:
    world.manager().logon(PASSWORD)
    world.log.clear()

    assert world.manager().probe() is True
    assert world.log == ["getServiceAttributes"]


def test_probe_reports_an_expired_session_without_logging_on_again(
    world: World,
) -> None:
    world.manager().logon(PASSWORD)
    world.service.expire_sessions()
    world.log.clear()

    assert world.manager().probe() is False
    assert world.log == ["getServiceAttributes"]


def test_probe_without_a_stored_session_sends_nothing(world: World) -> None:
    assert world.manager().probe() is None
    assert world.log == []


def test_sessions_are_kept_apart_per_service_url_and_user(world: World) -> None:
    world.manager().logon(PASSWORD)

    other = SessionManager(world.open_port, world.store, URL, "someone-else", None)
    with world.store.lock(SessionKey(URL, "someone-else")) as slot:
        assert slot.read() is None
    assert other.probe() is None


def test_download_replaces_an_expired_session_once_before_fetching_anything(
    world: World, tmp_path: Path
) -> None:
    world.service.offer_resources(
        "book0",
        [
            ContentResource(
                uri=world.service.file_url("files/a.txt"),
                mime_type="text/plain",
                size=5,
                local_uri="a.txt",
            )
        ],
    )
    world.service.offer_file("files/a.txt", b"hello")
    world.manager().logon(PASSWORD)
    world.service.expire_sessions()
    world.log.clear()

    report = download(
        world.manager(),
        DownloadRequest(
            content_id="book0",
            directory=tmp_path / "book",
            service_url=URL,
            trust_host=True,
        ),
    )

    assert report.succeeded, report
    assert world.log[:2] == ["getContentResources", "logOn"]
    assert world.log.count("logOn") == 1
    assert world.log.count("fetch_resource") == 1
    assert (tmp_path / "book" / "a.txt").read_bytes() == b"hello"


def test_a_failed_resource_fetch_never_triggers_a_relogin(
    world: World, tmp_path: Path
) -> None:
    world.service.offer_resources(
        "book0",
        [
            ContentResource(
                uri=world.service.file_url("files/missing.txt"),
                mime_type="text/plain",
                size=5,
                local_uri="a.txt",
            )
        ],
    )
    world.manager().logon(PASSWORD)
    world.log.clear()

    report = download(
        world.manager(),
        DownloadRequest(
            content_id="book0",
            directory=tmp_path / "book",
            service_url=URL,
            trust_host=True,
        ),
    )

    assert not report.succeeded
    assert world.log == ["getContentResources", "fetch_resource"]
