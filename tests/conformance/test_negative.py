"""The negative tests: deliberately invalid requests sent over a `RawChannel`.

They run against the fake Service on localhost through the HTTP adapter, which
is the only adapter with a raw channel. Users, books and passwords are
synthetic.
"""

from collections.abc import Iterator

import pytest

from dod.application import CONFORMANCE_TESTS, Outcome, RunReport, run_conformance
from dod.domain.service import Password
from dod.domain.v1 import SPEC_REFS, ContentItem, ContentList, ContentMetadata
from dod.infrastructure import HttpServicePort
from support import FakeService

USER = "synthetic-user"
PASSWORD = Password("synthetic-secret")
BOOK = ContentMetadata(title="Book 0", identifier="book0", format="Daisy 2.02", size=1)
ISSUED = ContentList(
    id="issued", total_items=1, items=(ContentItem(id="book0", label="Book 0"),)
)

NEGATIVE_IDS = [
    "negative.session.no-session",
    "negative.init.operation-before-init",
    "negative.operation.unknown",
    "negative.parameter.content-list-non-numeric-range",
    "negative.parameter.content-list-empty-id",
    "negative.parameter.content-metadata-empty-id",
]
UNKNOWN_OPERATION = "dodConformanceUnknownOperation"


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD.reveal())
    fake.enforce_initialisation = True
    fake.offer_catalog([ISSUED], [BOOK])
    yield fake
    fake.stop()


def run(service: FakeService, *only: str, with_raw: bool = True) -> RunReport:
    return run_conformance(
        lambda url: HttpServicePort(url),
        service.url,
        USER,
        PASSWORD,
        only=only,
        insecure=True,
        open_raw=(lambda url: HttpServicePort(url)) if with_raw else None,
    )


def outcomes(report: RunReport) -> dict[str, Outcome]:
    return {r.id: r.outcome for r in report.records}


def test_the_negative_family_is_registered_as_explicit_tests() -> None:
    negative = [t for t in CONFORMANCE_TESTS.tests if t.id.startswith("negative.")]

    assert [t.id for t in negative] == NEGATIVE_IDS
    assert all(t.explicit and not t.state_changing for t in negative)


def test_an_ordinary_run_never_includes_a_negative_test(service: FakeService) -> None:
    report = run_conformance(
        lambda url: HttpServicePort(url),
        service.url,
        USER,
        PASSWORD,
        insecure=True,
        open_raw=lambda url: HttpServicePort(url),
    )

    assert not any(r.id.startswith("negative.") for r in report.records)
    assert not any(r.operation == UNKNOWN_OPERATION for r in service.requests)


def test_every_negative_test_passes_against_a_conforming_service(
    service: FakeService,
) -> None:
    report = run(service, "negative")

    assert outcomes(report) == dict.fromkeys(NEGATIVE_IDS, Outcome.PASS)
    assert report.exit_code == 0


def test_the_negative_tests_use_sessions_of_their_own_and_log_them_off(
    service: FakeService,
) -> None:
    report = run(service, "negative")

    assert report.exit_code == 0
    assert service.sessions == set()
    logons = [r for r in service.requests if r.operation == "logOn"]
    assert len(logons) > 1  # the setup's, and one per test that needs a Session


def test_the_requests_are_the_deliberately_invalid_ones(service: FakeService) -> None:
    run(service, "negative")

    sent = {r.operation for r in service.requests}
    assert UNKNOWN_OPERATION in sent
    bodies = [
        r.body.decode() for r in service.requests if r.operation == "getContentList"
    ]
    assert any("<firstItem>abc</firstItem>" in body for body in bodies)


@pytest.mark.parametrize(
    ("test_id", "operation", "expected_ref"),
    [
        ("negative.session.no-session", "getContentList", "fault.noActiveSession"),
        (
            "negative.init.operation-before-init",
            "getContentList",
            "session.initialization",
        ),
        ("negative.operation.unknown", UNKNOWN_OPERATION, "fault.invalidOperation"),
        (
            "negative.parameter.content-list-non-numeric-range",
            "getContentList",
            "fault.invalidParameter",
        ),
        (
            "negative.parameter.content-list-empty-id",
            "getContentList",
            "fault.invalidParameter",
        ),
        (
            "negative.parameter.content-metadata-empty-id",
            "getContentMetadata",
            "fault.invalidParameter",
        ),
    ],
)
def test_a_wrong_fault_is_a_fail_that_cites_the_expected_fault(
    service: FakeService, test_id: str, operation: str, expected_ref: str
) -> None:
    service.inject_fault(operation, "internalServerError", "synthetic")

    report = run(service, test_id)

    (record,) = report.records
    assert record.outcome is Outcome.FAIL
    assert "internalServerError" in record.message
    assert record.spec_ref == SPEC_REFS[expected_ref]
    assert report.exit_code == 1


def test_a_service_that_accepts_the_invalid_request_fails_the_test(
    service: FakeService,
) -> None:
    # A Service that treats the empty content id as a book of its own.
    service.offer_catalog(
        [ISSUED], [BOOK, ContentMetadata(identifier="", title="x", size=1)]
    )

    report = run(service, "negative.parameter.content-metadata-empty-id")

    (record,) = report.records
    assert record.outcome is Outcome.FAIL
    assert "succeeded" in record.message
    assert record.spec_ref == SPEC_REFS["fault.invalidParameter"]
    # The answer for an empty identifier breaks the schemas on purpose.
    service.invalid_responses.clear()


def test_a_fault_without_a_dodp_element_is_a_fail_on_the_faults_section(
    service: FakeService,
) -> None:
    service.inject_http_500("getContentMetadata")

    report = run(service, "negative.parameter.content-metadata-empty-id")

    (record,) = report.records
    assert record.outcome is Outcome.FAIL
    assert record.spec_ref == SPEC_REFS["faults"]


def test_an_unknown_operation_may_also_be_answered_operation_not_supported(
    service: FakeService,
) -> None:
    service.inject_fault(UNKNOWN_OPERATION, "operationNotSupported", "synthetic")

    report = run(service, "negative.operation.unknown")

    assert outcomes(report) == {"negative.operation.unknown": Outcome.PASS}


def test_no_answer_is_an_error_not_a_fail(service: FakeService) -> None:
    service.inject_no_answer("getContentList")

    report = run(service, "negative.session.no-session")

    (record,) = report.records
    assert record.outcome is Outcome.ERROR
    assert report.exit_code == 2


def test_a_logoff_that_fails_is_an_error_on_the_cleanup_step_not_a_fail(
    service: FakeService,
) -> None:
    service.inject_fault("logOff", "internalServerError", "synthetic")

    report = run(service, "negative.parameter.content-list-empty-id")

    first, cleanup = report.records
    assert (first.id, first.outcome) == (
        "negative.parameter.content-list-empty-id",
        Outcome.PASS,
    )
    assert (cleanup.id, cleanup.outcome) == (
        "negative.parameter.content-list-empty-id.cleanup",
        Outcome.ERROR,
    )
    assert cleanup.exchange_ids
    assert report.exit_code == 2


def test_the_failures_of_a_test_keep_their_exchanges(service: FakeService) -> None:
    service.inject_fault("getContentList", "internalServerError", "synthetic")

    report = run(service, "negative.init.operation-before-init")

    (record,) = report.records
    assert record.exchange_ids
    assert all(i in report.exchanges for i in record.exchange_ids)


def test_without_a_raw_channel_a_negative_test_is_an_error(
    service: FakeService,
) -> None:
    report = run(service, "negative.session.no-session", with_raw=False)

    (record,) = report.records
    assert record.outcome is Outcome.ERROR
    assert "raw channel" in record.message


def test_the_setups_session_is_not_the_one_the_negative_tests_use(
    service: FakeService,
) -> None:
    report = run(service, "negative.session.no-session")

    assert report.exit_code == 0
    # No cookie was sent on the call that must see no Session.
    request = next(r for r in service.requests if r.operation == "getContentList")
    assert "Cookie" not in request.headers
