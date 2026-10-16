"""Contract tests for `ServicePort`, run against every adapter (ADR 0003).

The `adapter` fixture in `tests/conftest.py` yields a `Harness`: a way to open
a port towards a fresh fake Service and to steer that Service. All users and
passwords are synthetic.
"""

import pytest

from dod.domain.service import Deviation, Fault, FaultKind, Ok, Password
from dod.domain.v1 import (
    ReadingSystemAttributes,
    ReadingSystemConfig,
    ServicePort,
)
from support import Harness

USER = "synthetic-user"
PASSWORD = Password("synthetic-secret")
READING_SYSTEM = ReadingSystemAttributes(
    manufacturer="Synthetic Maker",
    model="dod",
    version="0.0.0",
    config=ReadingSystemConfig(
        supports_multiple_selections=False,
        preferred_ui_language="nb",
        supported_content_formats=("Daisy 2.02",),
        supported_content_protection_formats=(),
        supported_mime_types=("audio/mpeg",),
        supported_input_types=("TEXT_NUMERIC",),
        requires_audio_labels=False,
    ),
)


@pytest.fixture
def port(adapter: Harness) -> ServicePort:
    adapter.add_user(USER, PASSWORD.reveal())
    return adapter.open_port()


def test_log_on_with_valid_credentials_is_ok_and_starts_a_session(
    port: ServicePort,
) -> None:
    reply = port.log_on(USER, PASSWORD)

    assert isinstance(reply, Ok)
    assert reply.value is True
    assert port.session is not None


def test_log_on_with_a_wrong_password_is_ok_false_and_no_usable_session(
    port: ServicePort,
) -> None:
    reply = port.log_on(USER, Password("wrong"))

    assert isinstance(reply, Ok)
    assert reply.value is False
    follow_up = port.get_service_attributes()
    assert isinstance(follow_up, Fault)
    assert follow_up.kind is FaultKind.NO_ACTIVE_SESSION


def test_service_attributes_after_log_on_are_read_into_the_model(
    port: ServicePort,
) -> None:
    port.log_on(USER, PASSWORD)

    reply = port.get_service_attributes()

    assert isinstance(reply, Ok)
    assert reply.value.service_id == "synthetic-service"
    assert reply.value.supported_content_selection_methods == ("BROWSE",)
    assert reply.value.supports_search is False
    assert reply.schema_violations == ()


def test_reading_system_attributes_are_accepted_in_a_session(
    port: ServicePort,
) -> None:
    port.log_on(USER, PASSWORD)

    reply = port.set_reading_system_attributes(READING_SYSTEM)

    assert isinstance(reply, Ok)
    assert reply.value is True


def test_an_operation_without_a_session_is_a_no_active_session_fault(
    port: ServicePort,
) -> None:
    reply = port.set_reading_system_attributes(READING_SYSTEM)

    assert isinstance(reply, Fault)
    assert reply.kind is FaultKind.NO_ACTIVE_SESSION


def test_log_off_ends_the_session(port: ServicePort) -> None:
    port.log_on(USER, PASSWORD)

    reply = port.log_off()

    assert isinstance(reply, Ok)
    assert reply.value is True
    follow_up = port.get_service_attributes()
    assert isinstance(follow_up, Fault)
    assert follow_up.kind is FaultKind.NO_ACTIVE_SESSION


def test_a_fault_is_returned_as_a_value_with_kind_and_reason(
    adapter: Harness, port: ServicePort
) -> None:
    port.log_on(USER, PASSWORD)
    adapter.inject_fault(
        "setReadingSystemAttributes", "invalidParameter", "synthetic reason"
    )

    reply = port.set_reading_system_attributes(READING_SYSTEM)

    assert isinstance(reply, Fault)
    assert reply.kind is FaultKind.INVALID_PARAMETER
    assert reply.reason == "synthetic reason"


def test_an_answer_contrary_to_the_specification_is_a_deviation_with_a_reference(
    adapter: Harness, port: ServicePort
) -> None:
    adapter.inject_deviation("logOn")

    reply = port.log_on(USER, PASSWORD)

    assert isinstance(reply, Deviation)
    assert reply.spec_reference.section == "5.1.1"


@pytest.mark.parametrize("operation", ["logOn", "logOff"])
def test_every_reply_carries_an_exchange(port: ServicePort, operation: str) -> None:
    reply = port.log_on(USER, PASSWORD) if operation == "logOn" else port.log_off()

    assert reply.exchange.status == 200
