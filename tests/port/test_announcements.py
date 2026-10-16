"""Contract tests for the announcement operations, run against every adapter."""

import pytest

from dod.domain.service import Deviation, Fault, FaultKind, Ok
from dod.domain.v1 import Announcement, ServicePort
from support import SECRET as PASSWORD
from support import Harness

USER = "synthetic-user"
ANNOUNCEMENTS = (
    Announcement(id="a1", text="Maintenance tonight", lang="en"),
    Announcement(id="a2", text="Vedlikehold", lang="nb", type="WARNING", priority=1),
)


@pytest.fixture
def port(adapter: Harness) -> ServicePort:
    adapter.add_user(USER, PASSWORD.reveal())
    adapter.offer_announcements(*ANNOUNCEMENTS)
    port = adapter.open_port()
    port.log_on(USER, PASSWORD)
    return port


def test_the_announcements_are_read_into_the_model(port: ServicePort) -> None:
    reply = port.get_service_announcements()

    assert isinstance(reply, Ok)
    assert reply.value == ANNOUNCEMENTS
    assert reply.schema_violations == ()


def test_a_service_that_offers_them_says_so_in_its_attributes(
    port: ServicePort,
) -> None:
    reply = port.get_service_attributes()

    assert isinstance(reply, Ok)
    assert reply.value.supports_announcements


def test_marking_one_announcement_removes_it_from_the_unread_ones(
    port: ServicePort,
) -> None:
    port.get_service_announcements()

    marked = port.mark_announcements_as_read(["a1"])
    remaining = port.get_service_announcements()

    assert isinstance(marked, Ok)
    assert marked.value is True
    assert isinstance(remaining, Ok)
    assert [a.id for a in remaining.value] == ["a2"]


def test_several_announcements_can_be_marked_in_one_call(port: ServicePort) -> None:
    port.get_service_announcements()

    marked = port.mark_announcements_as_read(["a1", "a2"])

    assert isinstance(marked, Ok)
    assert marked.value is True


def test_marking_an_announcement_that_is_already_read_answers_false(
    port: ServicePort,
) -> None:
    port.get_service_announcements()
    port.mark_announcements_as_read(["a1"])

    again = port.mark_announcements_as_read(["a1"])

    assert isinstance(again, Ok)
    assert again.value is False


def test_marking_an_unknown_identifier_is_an_invalid_parameter_fault(
    port: ServicePort,
) -> None:
    port.get_service_announcements()

    reply = port.mark_announcements_as_read(["nope"])

    assert isinstance(reply, Fault)
    assert reply.kind is FaultKind.INVALID_PARAMETER


def test_a_service_without_announcements_says_operation_not_supported(
    adapter: Harness,
) -> None:
    adapter.add_user(USER, PASSWORD.reveal())
    port = adapter.open_port()
    port.log_on(USER, PASSWORD)

    fetched = port.get_service_announcements()
    marked = port.mark_announcements_as_read(["a1"])

    for reply in (fetched, marked):
        assert isinstance(reply, Fault)
        assert reply.kind is FaultKind.OPERATION_NOT_SUPPORTED


def test_the_operations_need_a_session(adapter: Harness) -> None:
    adapter.offer_announcements(*ANNOUNCEMENTS)
    port = adapter.open_port()

    for reply in (
        port.get_service_announcements(),
        port.mark_announcements_as_read(["a1"]),
    ):
        assert isinstance(reply, Fault)
        assert reply.kind is FaultKind.NO_ACTIVE_SESSION


@pytest.mark.parametrize(
    ("operation", "section"),
    [("getServiceAnnouncements", "5.2.1"), ("markAnnouncementsAsRead", "5.2.2")],
)
def test_an_answer_contrary_to_the_specification_is_a_deviation_with_a_reference(
    adapter: Harness, port: ServicePort, operation: str, section: str
) -> None:
    adapter.inject_deviation(operation)

    reply = (
        port.get_service_announcements()
        if operation == "getServiceAnnouncements"
        else port.mark_announcements_as_read(["a1"])
    )

    assert isinstance(reply, Deviation)
    assert reply.spec_reference.section == section
