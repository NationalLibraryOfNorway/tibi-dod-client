"""Announcements through the CLI boundary: `dod logon`, `list` and `mark-read`.

Subprocess tests run the installed console script against the fake Service on
localhost, with `DOD_STATE_DIR` in a temporary directory. Users and passwords
are synthetic.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from dod.domain.v1 import Announcement
from support import FakeService, run_dod

USER = "synthetic-user"
PASSWORD = "synthetic-secret"
INIT = ["logOn", "getServiceAttributes", "setReadingSystemAttributes"]
ONE = Announcement(id="a1", text="Maintenance tonight", lang="en")
TWO = Announcement(id="a2", text="Vedlikehold", lang="nb", type="WARNING", priority=1)


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD)
    yield fake
    fake.stop()


@pytest.fixture
def offering(service: FakeService) -> FakeService:
    service.offer_announcements(ONE, TWO)
    return service


def dod(  # type: ignore[no-untyped-def]
    service: FakeService, state: Path, *args: str, env: dict[str, str] | None = None
):
    return run_dod(
        *args,
        "--url",
        service.url,
        "--username",
        USER,
        "--password-stdin",
        "--insecure",
        stdin=PASSWORD + "\n",
        env={"DOD_STATE_DIR": str(state)} | (env or {}),
    )


def operations(service: FakeService) -> list[str | None]:
    return [request.operation for request in service.requests]


def test_logon_shows_the_announcements_without_marking_them_read(
    offering: FakeService, tmp_path: Path
) -> None:
    result = dod(offering, tmp_path, "logon")

    assert result.returncode == 0, result.stderr
    assert operations(offering) == [*INIT, "getServiceAnnouncements"]
    assert offering.read_announcements == set()
    assert "announcement a1 [INFORMATION, priority 3]: Maintenance tonight" in (
        result.stdout.splitlines()
    )
    assert "announcement a2 [WARNING, priority 1]: Vedlikehold" in (
        result.stdout.splitlines()
    )
    assert len(offering.sessions) == 1


def test_logon_without_announcement_support_does_not_ask(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "logon")

    assert result.returncode == 0, result.stderr
    assert operations(service) == INIT
    assert "announcement" not in result.stdout


def test_ephemeral_logon_shows_them_before_it_logs_off(
    offering: FakeService, tmp_path: Path
) -> None:
    result = dod(offering, tmp_path, "logon", "--no-session")

    assert result.returncode == 0, result.stderr
    assert operations(offering) == [*INIT, "getServiceAnnouncements", "logOff"]
    assert "announcement a1" in result.stdout


def test_logon_as_json_lists_the_announcements(
    offering: FakeService, tmp_path: Path
) -> None:
    result = dod(offering, tmp_path, "logon", "--format", "json")

    shown = json.loads(result.stdout)["announcements"]
    assert [a["id"] for a in shown] == ["a1", "a2"]


def test_a_fault_on_the_announcements_is_shown_and_keeps_the_session(
    offering: FakeService, tmp_path: Path
) -> None:
    offering.inject_fault("getServiceAnnouncements", "internalServerError", "boom")

    result = dod(offering, tmp_path, "logon")

    assert result.returncode == 0, result.stderr
    assert "getServiceAnnouncements: fault internalServerError: boom" in result.stdout
    assert len(offering.sessions) == 1
    assert len(list(tmp_path.rglob("*.json"))) == 1


def test_text_from_the_service_cannot_forge_lines_or_drive_the_terminal(
    service: FakeService, tmp_path: Path
) -> None:
    service.offer_announcements(
        Announcement(id="x", text="hello\nlogOn: ok\x9b31m\x85done")
    )

    result = dod(service, tmp_path, "logon")

    assert "\x9b" not in result.stdout
    assert "\x85" not in result.stdout
    assert result.stdout.splitlines().count("logOn: ok") == 1


def test_list_shows_the_unread_announcements(
    offering: FakeService, tmp_path: Path
) -> None:
    dod(offering, tmp_path, "logon")
    offering.requests.clear()

    result = dod(offering, tmp_path, "announcements", "list")

    assert result.returncode == 0, result.stderr
    assert operations(offering) == ["getServiceAnnouncements"]
    assert result.stdout.splitlines() == [
        "announcement a1 [INFORMATION, priority 3]: Maintenance tonight",
        "announcement a2 [WARNING, priority 1]: Vedlikehold",
    ]


def test_list_as_the_raw_response(offering: FakeService, tmp_path: Path) -> None:
    result = dod(offering, tmp_path, "announcements", "list", "--format", "xml")

    assert "<announcements" in result.stdout
    assert "logOn" not in result.stdout


def test_list_with_nothing_unread_says_so(service: FakeService, tmp_path: Path) -> None:
    service.offer_announcements(ONE)
    service.read_announcements = {"a1"}

    result = dod(service, tmp_path, "announcements", "list")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["no unread announcements"]


@pytest.mark.parametrize(
    "args", [["announcements", "list"], ["announcements", "mark-read", "a1"]]
)
def test_a_service_without_the_operations_answers_with_its_fault_as_it_is(
    service: FakeService, tmp_path: Path, args: list[str]
) -> None:
    result = dod(service, tmp_path, *args)

    assert result.returncode == 1
    assert "getServiceAnnouncements: fault operationNotSupported" in result.stdout


def test_mark_read_marks_the_named_announcements(
    offering: FakeService, tmp_path: Path
) -> None:
    result = dod(offering, tmp_path, "announcements", "mark-read", "a1")

    assert result.returncode == 0, result.stderr
    assert operations(offering)[-2:] == [
        "getServiceAnnouncements",
        "markAnnouncementsAsRead",
    ]
    assert result.stdout.splitlines() == ["a1: marked as read"]
    assert offering.read_announcements == {"a1"}


def test_mark_read_all_uses_the_identifiers_of_the_latest_fetch(
    offering: FakeService, tmp_path: Path
) -> None:
    result = dod(offering, tmp_path, "announcements", "mark-read", "--all")

    assert result.returncode == 0, result.stderr
    assert offering.read_announcements == {"a1", "a2"}
    assert result.stdout.splitlines() == ["a1: marked as read", "a2: marked as read"]
    marks = [r for r in offering.requests if r.operation == "markAnnouncementsAsRead"]
    assert len(marks) == 1


def test_false_from_the_service_means_already_read(
    offering: FakeService, tmp_path: Path
) -> None:
    dod(offering, tmp_path, "announcements", "mark-read", "a1")

    result = dod(offering, tmp_path, "announcements", "mark-read", "a1")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["a1: already read"]


def test_an_invalid_parameter_makes_it_try_one_by_one(
    offering: FakeService, tmp_path: Path
) -> None:
    result = dod(offering, tmp_path, "announcements", "mark-read", "a1", "nope", "a2")

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        "a1: marked as read",
        "nope: fault invalidParameter: unknown announcement",
        "a2: marked as read",
    ]
    marks = [r for r in offering.requests if r.operation == "markAnnouncementsAsRead"]
    assert len(marks) == 4  # the whole set, then one call per identifier
    assert offering.read_announcements == {"a1", "a2"}


def test_all_also_falls_back_to_one_by_one(
    offering: FakeService, tmp_path: Path
) -> None:
    offering.inject_fault("markAnnouncementsAsRead", "invalidParameter", "synthetic")

    result = dod(offering, tmp_path, "announcements", "mark-read", "--all")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["a1: marked as read", "a2: marked as read"]


def test_all_with_nothing_unread_marks_nothing(
    service: FakeService, tmp_path: Path
) -> None:
    service.offer_announcements(ONE)
    service.read_announcements = {"a1"}

    result = dod(service, tmp_path, "announcements", "mark-read", "--all")

    assert result.returncode == 0, result.stderr
    assert "markAnnouncementsAsRead" not in operations(service)


def test_mark_read_needs_identifiers_or_all_but_not_both(
    offering: FakeService, tmp_path: Path
) -> None:
    neither = dod(offering, tmp_path, "announcements", "mark-read")
    both = dod(offering, tmp_path, "announcements", "mark-read", "a1", "--all")

    assert neither.returncode == 2
    assert both.returncode == 2
    assert operations(offering) == []


def test_a_deviation_is_shown_as_it_is(offering: FakeService, tmp_path: Path) -> None:
    dod(offering, tmp_path, "logon")
    offering.inject_deviation("getServiceAnnouncements")

    result = dod(offering, tmp_path, "announcements", "list")

    assert result.returncode == 1
    assert "getServiceAnnouncements: deviation" in result.stdout
    assert "5.2.1" in result.stderr
