"""The `questions` family against the fake Service.

`getQuestions` is an optional operation (`DYNAMIC_MENUS`), gated on
`supportedOptionalOperations`: a Service that neither declares nor supports it
is SKIP, one that declares it but refuses is FAIL. The test sends only the
reserved `default` answer, which every Service with menus has to understand.
Users and menus are synthetic.
"""

from collections.abc import Iterator

import pytest

from dod.application import CONFORMANCE_TESTS, Outcome, RunReport, run_conformance
from dod.domain.service import Password
from dod.domain.v1 import SPEC_REFS
from dod.infrastructure import HttpServicePort
from support import FakeService
from support.samples import multiple_choice, questions

USER = "synthetic-user"
PASSWORD = Password("synthetic-secret")


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD.reveal())
    fake.declare_operations("DYNAMIC_MENUS")
    fake.offer_menu(
        questions(multiple_choice("root", "Pick", ("a", "A"))), answer_to="default"
    )
    yield fake
    fake.stop()


def run(service: FakeService) -> RunReport:
    return run_conformance(
        lambda url: HttpServicePort(url),
        service.url,
        USER,
        PASSWORD,
        only=("questions",),
        insecure=True,
    )


def test_the_test_is_registered_and_changes_no_state() -> None:
    found = [t for t in CONFORMANCE_TESTS.tests if t.id.startswith("questions.")]

    assert [t.id for t in found] == ["questions.default"]
    assert not found[0].state_changing
    assert not found[0].explicit


def test_a_service_with_a_schema_valid_root_menu_passes(service: FakeService) -> None:
    (record,) = run(service).records

    assert record.outcome is Outcome.PASS
    sent = [r for r in service.requests if r.operation == "getQuestions"]
    assert len(sent) == 1
    assert 'questionID="default"' in sent[0].body.decode()


def test_a_service_that_is_not_declared_and_not_supported_is_skip(
    service: FakeService,
) -> None:
    service.service_attributes_xml = service.service_attributes_xml.replace(
        "<operation>DYNAMIC_MENUS</operation>", ""
    )
    service.inject_fault("getQuestions", "operationNotSupported", "synthetic")

    (record,) = run(service).records

    assert record.outcome is Outcome.SKIP
    assert "DYNAMIC_MENUS" in record.message


def test_a_declared_operation_that_is_refused_fails(service: FakeService) -> None:
    service.inject_fault("getQuestions", "operationNotSupported", "synthetic")

    (record,) = run(service).records

    assert record.outcome is Outcome.FAIL
    assert record.spec_ref == SPEC_REFS["fault.operationNotSupported"]


def test_a_root_menu_that_breaks_the_schema_fails(service: FakeService) -> None:
    service.offer_menu(
        questions(multiple_choice("root", "Pick", ("two words", "A"))),
        answer_to="default",
        schema_valid=False,
    )

    (record,) = run(service).records

    assert record.outcome is Outcome.FAIL
    assert record.spec_ref == SPEC_REFS["type.questions"]


def test_a_service_that_does_not_know_default_fails(service: FakeService) -> None:
    service.inject_fault("getQuestions", "invalidParameter", "synthetic")

    (record,) = run(service).records

    assert record.outcome is Outcome.FAIL
