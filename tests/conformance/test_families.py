"""The first test families (session, service attributes, catalog) against the
fake Service, with fault injection for every Outcome.

Users, books and passwords are synthetic. The runner talks to the HTTP adapter
and the fake Service on localhost, so the whole wire path is exercised.
"""

from collections.abc import Callable, Iterator

import pytest

from dod.application import (
    CONFORMANCE_TESTS,
    Outcome,
    Record,
    RunReport,
    run_conformance,
)
from dod.domain.service import Password
from dod.domain.v1 import SPEC_REFS, ContentItem, ContentList, ContentMetadata
from dod.infrastructure import HttpServicePort, InMemoryService
from support import FakeService

USER = "synthetic-user"
PASSWORD = Password("synthetic-secret")
ITEMS = tuple(ContentItem(id=f"book{n}", label=f"Book {n}") for n in range(3))
ISSUED = ContentList(id="issued", total_items=3, items=ITEMS)
BOOK = ContentMetadata(
    title="Book 0", identifier="book0", format="Daisy 2.02", size=1234
)

ALL_IDS = [
    "session.logon.valid-credentials",
    "session.logon.wrong-password",
    "session.logoff.invalidates-session",
    "session.call.without-session",
    "attributes.service.get",
    "attributes.reading-system.set",
    "catalog.list.issued",
    "catalog.list.segment",
    "catalog.list.invalid-range",
    "catalog.list.unknown-id",
    "catalog.metadata.get",
    "catalog.metadata.unknown-id",
]

CONTENT_IDS = [
    "content.issue.returns-true",
    "content.resources.list",
    "content.resource.fetch",
    "content.resource.range",
    "content.resources.not-issued",
]
# The optional operations of a Service that declares none: it answers all of them
# but the round trip, which needs --state-changing and a content id.
OPTIONAL_OUTCOMES = {
    "bookmarks.get.known": Outcome.PASS,
    "bookmarks.get.unknown-id": Outcome.PASS,
    "bookmarks.set.round-trip": Outcome.SKIP,
    "key-exchange.unknown-key": Outcome.PASS,
}


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD.reveal())
    fake.offer_catalog([ISSUED], [BOOK])
    yield fake
    fake.stop()


def run(service: FakeService, only: str | None = None) -> RunReport:
    return run_conformance(
        lambda url: HttpServicePort(url),
        service.url,
        USER,
        PASSWORD,
        only=(only,) if only else (),
        insecure=True,
    )


def only_record(report: RunReport) -> Record:
    (record,) = report.records
    return record


def test_the_default_registry_lists_the_first_families_by_stable_id() -> None:
    assert [t.id for t in CONFORMANCE_TESTS.tests if not t.explicit] == [
        *ALL_IDS,
        *CONTENT_IDS,
        *OPTIONAL_OUTCOMES,
    ]
    assert {t.id for t in CONFORMANCE_TESTS.tests if t.state_changing} == {
        *CONTENT_IDS,
        "bookmarks.set.round-trip",
    }


def test_every_test_passes_against_a_conforming_service(service: FakeService) -> None:
    report = run(service)

    assert {r.id: r.outcome for r in report.records} == {
        **dict.fromkeys(ALL_IDS, Outcome.PASS),
        **dict.fromkeys(CONTENT_IDS, Outcome.SKIP),
        **OPTIONAL_OUTCOMES,
    }
    assert report.exit_code == 0
    assert all(r.note is None for r in report.records if r.id in ALL_IDS)


def test_every_test_passes_against_the_in_memory_service() -> None:
    memory = InMemoryService()
    memory.add_user(USER, PASSWORD.reveal())
    memory.offer_catalog([ISSUED], [BOOK])

    report = run_conformance(
        lambda url: memory.open_port(),
        "https://dod.example.org/service",
        USER,
        PASSWORD,
    )

    assert {r.id: r.outcome for r in report.records} == {
        **dict.fromkeys(ALL_IDS, Outcome.PASS),
        **dict.fromkeys(CONTENT_IDS, Outcome.SKIP),
        **OPTIONAL_OUTCOMES,
    }


Inject = Callable[[FakeService], None]


def fault(operation: str, kind: str = "internalServerError", after: int = 0) -> Inject:
    def inject(service: FakeService) -> None:
        service.inject_fault(operation, kind, "synthetic")
        service.defer_injection(operation, after)

    return inject


def deviation(operation: str, after: int = 0) -> Inject:
    def inject(service: FakeService) -> None:
        service.inject_deviation(operation)
        service.defer_injection(operation, after)

    return inject


def http_500(operation: str, after: int = 0) -> Inject:
    def inject(service: FakeService) -> None:
        service.inject_http_500(operation)
        service.defer_injection(operation, after)

    return inject


def no_answer(operation: str, after: int = 0) -> Inject:
    def inject(service: FakeService) -> None:
        service.inject_no_answer(operation)
        service.defer_injection(operation, after)

    return inject


def not_soap(operation: str, after: int = 0) -> Inject:
    def inject(service: FakeService) -> None:
        service.inject_not_soap(operation)
        service.defer_injection(operation, after)

    return inject


# The setup logs on and reads the attributes once, so those two operations are
# injected "after 1" to hit the test and not the setup.
CASES: list[tuple[str, Inject, Outcome]] = [
    ("session.logon.valid-credentials", fault("logOn", after=1), Outcome.FAIL),
    ("session.logon.valid-credentials", http_500("logOn", after=1), Outcome.FAIL),
    ("session.logon.valid-credentials", no_answer("logOn", after=1), Outcome.ERROR),
    ("session.logon.valid-credentials", not_soap("logOn", after=1), Outcome.ERROR),
    ("session.logon.wrong-password", deviation("logOn", after=1), Outcome.FAIL),
    ("session.logon.wrong-password", no_answer("logOn", after=1), Outcome.ERROR),
    ("session.logoff.invalidates-session", fault("logOff", after=0), Outcome.FAIL),
    ("session.logoff.invalidates-session", no_answer("logOff"), Outcome.ERROR),
    (
        "session.call.without-session",
        fault("getServiceAttributes", "invalidOperation", after=1),
        Outcome.FAIL,
    ),
    ("session.call.without-session", http_500("getServiceAttributes", 1), Outcome.FAIL),
    ("attributes.service.get", fault("getServiceAttributes", after=1), Outcome.FAIL),
    ("attributes.service.get", deviation("getServiceAttributes", 1), Outcome.FAIL),
    ("attributes.service.get", no_answer("getServiceAttributes", 1), Outcome.ERROR),
    (
        "attributes.reading-system.set",
        fault("setReadingSystemAttributes", after=1),
        Outcome.FAIL,
    ),
    ("catalog.list.issued", fault("getContentList"), Outcome.FAIL),
    ("catalog.list.issued", deviation("getContentList"), Outcome.FAIL),
    ("catalog.list.issued", no_answer("getContentList"), Outcome.ERROR),
    ("catalog.list.segment", fault("getContentList"), Outcome.FAIL),
    ("catalog.list.invalid-range", fault("getContentList"), Outcome.FAIL),
    ("catalog.list.unknown-id", deviation("getContentList"), Outcome.FAIL),
    ("catalog.list.unknown-id", http_500("getContentList"), Outcome.FAIL),
    ("catalog.list.unknown-id", not_soap("getContentList"), Outcome.ERROR),
    ("catalog.metadata.get", fault("getContentMetadata"), Outcome.FAIL),
    ("catalog.metadata.get", no_answer("getContentMetadata"), Outcome.ERROR),
    ("catalog.metadata.unknown-id", deviation("getContentMetadata"), Outcome.FAIL),
    (
        "catalog.metadata.unknown-id",
        fault("getContentMetadata", "internalServerError"),
        Outcome.FAIL,
    ),
]


@pytest.mark.parametrize(
    ("test_id", "inject", "expected"),
    CASES,
    ids=[f"{c[0]}-{n}" for n, c in enumerate(CASES)],
)
def test_each_test_reaches_its_outcome_under_fault_injection(
    service: FakeService, test_id: str, inject: Inject, expected: Outcome
) -> None:
    inject(service)

    record = only_record(run(service, test_id))

    assert record.outcome is expected, record.message
    if expected is Outcome.FAIL:
        assert record.spec_ref is not None
        assert record.message
    if expected is Outcome.ERROR:
        assert record.message


def test_a_fault_is_judged_by_its_dodp_element_not_the_http_status(
    service: FakeService,
) -> None:
    # The fake Service answers every DODP fault with HTTP 500, and the unknown
    # list is still a PASS: invalidParameter in `detail` is what counts.
    record = only_record(run(service, "catalog.list.unknown-id"))

    assert record.outcome is Outcome.PASS


def test_http_500_without_a_dodp_element_fails_with_the_faults_reference(
    service: FakeService,
) -> None:
    http_500("getContentList")(service)

    record = only_record(run(service, "catalog.list.unknown-id"))

    assert record.outcome is Outcome.FAIL
    assert record.spec_ref == SPEC_REFS["faults"]


def test_the_wrong_fault_kind_fails_with_that_faults_reference(
    service: FakeService,
) -> None:
    fault("getContentList", "invalidOperation")(service)

    record = only_record(run(service, "catalog.list.unknown-id"))

    assert record.outcome is Outcome.FAIL
    assert "invalidParameter" in record.message
    assert record.spec_ref == SPEC_REFS["fault.invalidParameter"]


def test_an_answer_that_breaks_the_schema_fails(service: FakeService) -> None:
    # An id with whitespace is not an xs:NMTOKEN.
    service.lists["issued"] = ContentList(id="has space", total_items=0)

    record = only_record(run(service, "catalog.list.issued"))

    assert record.outcome is Outcome.FAIL
    assert "schema" in record.message
    assert record.spec_ref == SPEC_REFS["operation.getContentList"]


def test_a_list_that_answers_with_another_id_fails(service: FakeService) -> None:
    service.offer_catalog([ISSUED], [BOOK])
    service.lists["issued"] = ContentList(id="other", total_items=3, items=ITEMS)

    record = only_record(run(service, "catalog.list.issued"))

    assert record.outcome is Outcome.FAIL
    assert "other" in record.message


def test_without_books_the_catalog_tests_that_need_one_are_skipped(
    service: FakeService,
) -> None:
    service.offer_catalog([], [])

    report = run(service, "catalog")

    assert {r.id: r.outcome for r in report.records} == {
        "catalog.list.issued": Outcome.PASS,
        "catalog.list.segment": Outcome.SKIP,
        "catalog.list.invalid-range": Outcome.PASS,
        "catalog.list.unknown-id": Outcome.PASS,
        "catalog.metadata.get": Outcome.SKIP,
        "catalog.metadata.unknown-id": Outcome.PASS,
    }


def test_the_wrong_password_test_never_uses_the_runs_password(
    service: FakeService,
) -> None:
    run(service, "session.logon.wrong-password")

    sent = [
        r.body.decode()
        for r in service.requests
        if r.operation == "logOn" and PASSWORD.reveal() not in r.body.decode()
    ]
    assert len(sent) == 1


def test_a_setup_that_cannot_log_on_ends_the_run_with_an_error(
    service: FakeService,
) -> None:
    report = run_conformance(
        lambda url: HttpServicePort(url),
        service.url,
        USER,
        Password("not-the-password"),
        insecure=True,
    )

    assert report.records == ()
    assert report.setup_error is not None
    assert report.exit_code == 2
    assert [r.operation for r in service.requests] == ["logOn"]


def test_the_exchanges_of_a_test_are_kept_for_the_report(service: FakeService) -> None:
    report = run(service, "attributes.service.get")

    record = only_record(report)
    (identifier,) = record.exchange_ids
    exchange = report.exchanges[identifier]
    assert "getServiceAttributes" in exchange.request_body
    assert "synthetic-provider" in exchange.response_body
