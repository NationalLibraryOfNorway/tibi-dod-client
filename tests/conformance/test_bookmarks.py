"""The `bookmarks` and `key-exchange` families against the fake Service.

The optional operations are gated on `supportedOptionalOperations`: a test of an
operation the Service neither declares nor supports is SKIP, and one it declares
but refuses is FAIL. Users, books, passwords and keys are synthetic.
"""

from collections.abc import Iterator

import pytest

from dod.application import CONFORMANCE_TESTS, Outcome, RunReport, run_conformance
from dod.domain.v1 import SPEC_REFS, ContentItem, ContentList, ContentMetadata
from dod.infrastructure import HttpServicePort
from support import SECRET as PASSWORD
from support import FakeService
from support.samples import KEY_EXCHANGE, bookmark_set

USER = "synthetic-user"
BOOK = ContentMetadata(title="Book 0", identifier="book0", format="Daisy 2.02", size=1)
LASTMARK = (
    "<lastmark><ncxRef>hix00023</ncxRef><URI>s023.smil#main</URI>"
    "<timeOffset>97.826</timeOffset></lastmark>"
)
BOOKMARK_IDS = [
    "bookmarks.get.known",
    "bookmarks.get.unknown-id",
    "bookmarks.set.round-trip",
]
KEY_IDS = ["key-exchange.unknown-key"]


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD.reveal())
    fake.offer_catalog(
        [ContentList("issued", 1, (ContentItem("book0", "Book 0"),))], [BOOK]
    )
    fake.offer_bookmarks("book0", bookmark_set("book0", lastmark=LASTMARK, bookmarks=2))
    fake.declare_operations("GET_BOOKMARKS", "SET_BOOKMARKS", "PDTB2_KEY_PROVISION")
    yield fake
    fake.stop()


def run(
    service: FakeService,
    *only: str,
    content_id: str | None = "book0",
    state_changing: bool = True,
) -> RunReport:
    return run_conformance(
        lambda url: HttpServicePort(url),
        service.url,
        USER,
        PASSWORD,
        only=only or ("bookmarks", "key-exchange"),
        state_changing=state_changing,
        insecure=True,
        content_id=content_id,
    )


def outcomes(report: RunReport) -> dict[str, Outcome]:
    return {r.id: r.outcome for r in report.records}


def operations(service: FakeService) -> list[str]:
    return [r.operation or "" for r in service.requests]


def test_the_families_are_registered_and_only_the_round_trip_changes_state() -> None:
    found = {
        t.id: t
        for t in CONFORMANCE_TESTS.tests
        if t.id.startswith(("bookmarks.", "key-exchange."))
    }

    assert list(found) == [*BOOKMARK_IDS, *KEY_IDS]
    assert {i for i, t in found.items() if t.state_changing} == {
        "bookmarks.set.round-trip"
    }
    assert not any(t.explicit for t in found.values())


def test_every_test_passes_against_a_conforming_service(service: FakeService) -> None:
    report = run(service)

    assert outcomes(report) == dict.fromkeys([*BOOKMARK_IDS, *KEY_IDS], Outcome.PASS)
    assert report.exit_code == 0


def test_the_round_trip_writes_back_exactly_what_it_read(service: FakeService) -> None:
    before = service.bookmarks["book0"]

    run(service, "bookmarks.set")

    sent = [r for r in service.requests if r.operation == "setBookmarks"]
    assert len(sent) == 1
    assert LASTMARK in sent[0].body.decode()
    assert sent[0].body.decode().count("<bookmark ") == 2
    assert service.bookmarks["book0"].count("<bookmark ") == before.count("<bookmark ")
    assert LASTMARK in service.bookmarks["book0"]


def test_without_state_changing_the_round_trip_is_skipped_and_nothing_is_written(
    service: FakeService,
) -> None:
    report = run(service, state_changing=False)

    assert outcomes(report)["bookmarks.set.round-trip"] is Outcome.SKIP
    assert outcomes(report)["bookmarks.get.known"] is Outcome.PASS
    assert "setBookmarks" not in operations(service)


def test_without_a_content_id_the_round_trip_is_skipped(service: FakeService) -> None:
    report = run(service, content_id=None)

    assert outcomes(report)["bookmarks.set.round-trip"] is Outcome.SKIP
    assert "setBookmarks" not in operations(service)


def test_without_a_content_id_the_get_test_uses_the_first_book_of_the_shelf(
    service: FakeService,
) -> None:
    report = run(service, "bookmarks.get.known", content_id=None)

    assert outcomes(report) == {"bookmarks.get.known": Outcome.PASS}
    asked = next(r for r in service.requests if r.operation == "getBookmarks")
    assert "<contentID>book0</contentID>" in asked.body.decode()


@pytest.mark.parametrize(
    ("test_id", "operation", "token"),
    [
        ("bookmarks.get.known", "getBookmarks", "GET_BOOKMARKS"),
        ("bookmarks.get.unknown-id", "getBookmarks", "GET_BOOKMARKS"),
        ("bookmarks.set.round-trip", "getBookmarks", "GET_BOOKMARKS"),
        ("key-exchange.unknown-key", "getKeyExchangeObject", "PDTB2_KEY_PROVISION"),
    ],
)
def test_an_operation_that_is_not_declared_and_not_supported_is_skip(
    service: FakeService, test_id: str, operation: str, token: str
) -> None:
    service.service_attributes_xml = service.service_attributes_xml.replace(
        f"<operation>{token}</operation>", ""
    )
    service.inject_fault(operation, "operationNotSupported", "synthetic")

    (record,) = run(service, test_id).records

    assert record.outcome is Outcome.SKIP
    assert token in record.message


@pytest.mark.parametrize(
    ("test_id", "operation"),
    [
        ("bookmarks.get.known", "getBookmarks"),
        ("key-exchange.unknown-key", "getKeyExchangeObject"),
    ],
)
def test_a_declared_operation_that_is_refused_fails(
    service: FakeService, test_id: str, operation: str
) -> None:
    service.inject_fault(operation, "operationNotSupported", "synthetic")

    (record,) = run(service, test_id).records

    assert record.outcome is Outcome.FAIL
    assert record.spec_ref == SPEC_REFS["fault.operationNotSupported"]


def test_a_set_that_is_declared_but_refused_fails(service: FakeService) -> None:
    service.inject_fault("setBookmarks", "operationNotSupported", "synthetic")

    (record,) = run(service, "bookmarks.set").records

    assert record.outcome is Outcome.FAIL
    assert "SET_BOOKMARKS" in record.message


def test_a_set_that_answers_false_fails(service: FakeService) -> None:
    service.inject_false("setBookmarks")

    (record,) = run(service, "bookmarks.set").records

    assert record.outcome is Outcome.FAIL
    assert record.spec_ref == SPEC_REFS["operation.setBookmarks"]


def test_a_set_that_loses_the_lastmark_fails(service: FakeService) -> None:
    service.store_bookmarks_as = lambda stored: stored.replace(LASTMARK, "")

    (record,) = run(service, "bookmarks.set").records

    assert record.outcome is Outcome.FAIL
    assert "differs" in record.message


def test_a_bookmark_set_that_breaks_the_schema_fails_the_get_test(
    service: FakeService,
) -> None:
    service.offer_bookmarks(
        "book0",
        bookmark_set("book0").replace("<uid>book0</uid>", ""),
        schema_valid=False,
    )

    (record,) = run(service, "bookmarks.get.known").records

    assert record.outcome is Outcome.FAIL
    assert record.spec_ref == SPEC_REFS["type.bookmarkSet"]


def test_a_service_that_answers_for_an_unknown_key_fails(service: FakeService) -> None:
    service.offer_key_exchange("dod-conformance-unknown-key", KEY_EXCHANGE)

    (record,) = run(service, "key-exchange").records

    assert record.outcome is Outcome.FAIL
    assert "invalidParameter" in record.message
