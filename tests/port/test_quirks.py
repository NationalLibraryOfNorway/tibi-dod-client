"""Quirks seen through the HTTP adapter (ADR 0010).

A Quirk is off unless it is named when the port is opened, and using it always
adds an `interoperability` Observation.
"""

from collections.abc import Iterator

import pytest

from dod.domain.service import Deviation, Fault, FaultKind, Ok, Password
from dod.domain.v1 import QUIRKS
from dod.infrastructure import HttpServicePort
from support import FakeService

USER = "synthetic-user"
PASSWORD = Password("synthetic-secret")
BARE_500 = "http-500-without-fault-as-invalid-operation"


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD.reveal())
    yield fake
    fake.stop()


def test_every_quirk_has_a_behaviour_name_a_description_and_a_reference() -> None:
    assert BARE_500 in QUIRKS
    for name, quirk in QUIRKS.items():
        assert quirk.name == name
        assert name.islower() and name.replace("-", "").isalnum()
        assert quirk.description
        assert quirk.spec_reference.url.startswith("http")


def test_a_bare_http_500_is_a_deviation_while_the_quirk_is_off(
    service: FakeService,
) -> None:
    port = HttpServicePort(service.url)
    port.log_on(USER, PASSWORD)
    service.inject_http_500("getContentList")

    reply = port.get_content_list("issued", 0, 9)

    assert isinstance(reply, Deviation)
    assert "interoperability" not in [o.id for o in reply.observations]
    port.close()


def test_with_the_quirk_a_bare_http_500_before_initialisation_is_invalid_operation(
    service: FakeService,
) -> None:
    port = HttpServicePort(service.url, quirks=frozenset({BARE_500}))
    port.log_on(USER, PASSWORD)
    service.inject_http_500("getContentList")

    reply = port.get_content_list("issued", 0, 9)

    assert isinstance(reply, Fault)
    assert reply.kind is FaultKind.INVALID_OPERATION
    assert reply.exchange.status == 500
    (observation,) = [o for o in reply.observations if o.id == "interoperability"]
    assert BARE_500 in observation.message
    port.close()


def test_the_quirk_leaves_a_real_dodp_fault_alone(service: FakeService) -> None:
    port = HttpServicePort(service.url, quirks=frozenset({BARE_500}))
    port.log_on(USER, PASSWORD)
    service.inject_fault("getContentList", FaultKind.INVALID_PARAMETER, "synthetic")

    reply = port.get_content_list("issued", 0, 9)

    assert isinstance(reply, Fault)
    assert reply.kind is FaultKind.INVALID_PARAMETER
    assert "interoperability" not in [o.id for o in reply.observations]
    port.close()


def test_the_quirk_does_not_apply_to_the_initialisation_sequence_itself(
    service: FakeService,
) -> None:
    port = HttpServicePort(service.url, quirks=frozenset({BARE_500}))
    service.inject_http_500("logOn")

    reply = port.log_on(USER, PASSWORD)

    assert isinstance(reply, Deviation)
    port.close()


def test_a_port_refuses_a_quirk_it_does_not_know() -> None:
    with pytest.raises(ValueError, match="made-up"):
        HttpServicePort("http://127.0.0.1:1", quirks=frozenset({"made-up"}))


def test_a_port_without_quirks_still_reads_normal_answers(service: FakeService) -> None:
    port = HttpServicePort(service.url, quirks=frozenset({BARE_500}))

    assert isinstance(port.log_on(USER, PASSWORD), Ok)
    port.close()


def test_the_adapter_accepts_every_registered_quirk() -> None:
    port = HttpServicePort("http://127.0.0.1:1", quirks=frozenset(QUIRKS))

    port.close()
