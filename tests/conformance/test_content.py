"""The `content` family: issue, resources, fetch and Range, against the fake Service.

The family is State-changing and needs an explicit `--content-id`; every test
returns what it issued. Users, books and passwords are synthetic.
"""

from collections.abc import Iterator

import pytest

from dod.application import CONFORMANCE_TESTS, Outcome, RunReport, run_conformance
from dod.domain.service import Password
from dod.domain.v1 import (
    SPEC_REFS,
    ContentItem,
    ContentList,
    ContentMetadata,
    ContentResource,
)
from dod.infrastructure import HttpServicePort
from support import FakeService

USER = "synthetic-user"
PASSWORD = Password("synthetic-secret")
BODY = bytes(range(200))
BOOK = ContentMetadata(title="Book 0", identifier="book0", format="Daisy 2.02", size=1)
OTHER = ContentMetadata(title="Book 1", identifier="book1", format="Daisy 2.02", size=1)

CONTENT_IDS = [
    "content.issue.returns-true",
    "content.resources.list",
    "content.resource.fetch",
    "content.resource.range",
    "content.resources.not-issued",
]


def lists(*issued: str) -> list[ContentList]:
    items = tuple(ContentItem(id=i, label=i) for i in issued)
    return [ContentList(id="issued", total_items=len(items), items=items)]


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD.reveal())
    fake.offer_catalog(lists(), [BOOK, OTHER])
    fake.offer_file("book0/ncc.html", BODY)
    fake.offer_resources(
        "book0",
        [
            ContentResource(
                uri=fake.file_url("book0/ncc.html"),
                mime_type="text/html",
                size=len(BODY),
                local_uri="ncc.html",
            )
        ],
        issued=False,
    )
    fake.offer_resources("book1", [], issued=False)
    yield fake
    fake.stop()


def run(
    service: FakeService,
    *only: str,
    content_id: str | None = "book0",
    unissued_content_id: str | None = "book1",
    state_changing: bool = True,
) -> RunReport:
    return run_conformance(
        lambda url: HttpServicePort(url),
        service.url,
        USER,
        PASSWORD,
        only=only or ("content",),
        state_changing=state_changing,
        insecure=True,
        content_id=content_id,
        unissued_content_id=unissued_content_id,
    )


def outcomes(report: RunReport) -> dict[str, Outcome]:
    return {r.id: r.outcome for r in report.records}


def operations(service: FakeService) -> list[str]:
    return [r.operation or "" for r in service.requests]


def test_the_family_is_registered_as_state_changing_tests() -> None:
    content = [t for t in CONFORMANCE_TESTS.tests if t.id.startswith("content.")]

    assert [t.id for t in content] == CONTENT_IDS
    assert all(t.state_changing and not t.explicit for t in content)


def test_every_test_passes_against_a_conforming_service(service: FakeService) -> None:
    report = run(service)

    assert outcomes(report) == dict.fromkeys(CONTENT_IDS, Outcome.PASS)
    assert report.exit_code == 0


def test_the_tests_return_what_they_issued_and_leave_nothing_issued(
    service: FakeService,
) -> None:
    run(service)

    ops = operations(service)
    assert ops.count("issueContent") == ops.count("returnContent") == 4
    assert service.books["book0"][1] is False


def test_without_a_content_id_the_tests_are_skipped_and_nothing_is_issued(
    service: FakeService,
) -> None:
    report = run(service, content_id=None, unissued_content_id=None)

    assert set(outcomes(report).values()) == {Outcome.SKIP}
    assert "issueContent" not in operations(service)


def test_the_unissued_test_is_skipped_without_its_own_id(service: FakeService) -> None:
    report = run(service, unissued_content_id=None)

    assert outcomes(report)["content.resources.not-issued"] is Outcome.SKIP
    assert outcomes(report)["content.issue.returns-true"] is Outcome.PASS


def test_without_state_changing_the_family_is_skipped(service: FakeService) -> None:
    report = run(service, state_changing=False)

    assert set(outcomes(report).values()) == {Outcome.SKIP}
    assert "issueContent" not in operations(service)


def test_content_that_was_issued_before_the_run_is_not_returned(
    service: FakeService,
) -> None:
    service.books["book0"] = (service.books["book0"][0], True)
    service.offer_catalog(lists("book0"), [BOOK, OTHER])

    report = run(service)

    assert outcomes(report) == dict.fromkeys(CONTENT_IDS, Outcome.PASS)
    assert "returnContent" not in operations(service)
    assert service.books["book0"][1] is True


def test_content_that_cannot_be_issued_is_an_error(service: FakeService) -> None:
    report = run(service, content_id="no-such-book")

    result = outcomes(report)
    assert result["content.issue.returns-true"] is Outcome.ERROR
    assert result["content.resources.list"] is Outcome.ERROR
    assert report.exit_code == 2


def test_an_issue_that_answers_false_is_an_error(service: FakeService) -> None:
    service.inject_false("issueContent")

    report = run(service, "content.issue")

    assert outcomes(report) == {"content.issue.returns-true": Outcome.ERROR}


def test_an_issue_that_is_contrary_to_the_specification_fails(
    service: FakeService,
) -> None:
    service.inject_deviation("issueContent")

    (record,) = run(service, "content.issue").records

    assert record.outcome is Outcome.FAIL
    assert record.spec_ref is not None


def test_a_failing_return_is_an_error_on_the_cleanup_record(
    service: FakeService,
) -> None:
    service.inject_fault("returnContent", "internalServerError", "synthetic")

    report = run(service, "content.issue")

    assert outcomes(report) == {
        "content.issue.returns-true": Outcome.PASS,
        "content.issue.returns-true.cleanup": Outcome.ERROR,
    }


def test_a_localuri_that_leaves_the_directory_fails_the_resource_list(
    service: FakeService,
) -> None:
    service.offer_resources(
        "book0",
        [ContentResource(service.file_url("x"), "text/html", 1, "../evil.html")],
        issued=False,
    )

    (record,) = run(service, "content.resources.list").records

    assert record.outcome is Outcome.FAIL
    assert record.spec_ref == SPEC_REFS["type.resources"]
    assert "localURI" in record.message


def test_a_resource_list_that_breaks_the_schema_fails(service: FakeService) -> None:
    service.offer_resources(
        "book0",
        [ContentResource(service.file_url("x"), "text/html", -1, "a.html")],
        issued=False,
    )

    (record,) = run(service, "content.resources.list").records

    assert record.outcome is Outcome.FAIL


def test_a_content_length_that_differs_from_the_declared_size_fails(
    service: FakeService,
) -> None:
    service.offer_resources(
        "book0",
        [
            ContentResource(
                service.file_url("book0/ncc.html"), "text/html", 7, "ncc.html"
            )
        ],
        issued=False,
    )

    (record,) = run(service, "content.resource.fetch").records

    assert record.outcome is Outcome.FAIL
    assert record.spec_ref == SPEC_REFS["type.resources"]


def test_a_resource_that_cannot_be_fetched_fails(service: FakeService) -> None:
    service.answer_file("book0/ncc.html", 404, b"gone")

    (record,) = run(service, "content.resource.fetch").records

    assert record.outcome is Outcome.FAIL


def test_a_large_resource_is_cut_off_at_64_kib(service: FakeService) -> None:
    big = bytes(70 * 1024)
    service.offer_file("book0/big.bin", big)
    service.offer_resources(
        "book0",
        [
            ContentResource(
                service.file_url("book0/big.bin"),
                "application/octet-stream",
                len(big),
                "big.bin",
            )
        ],
        issued=False,
    )

    report = run(service, "content.resource")

    assert set(outcomes(report).values()) == {Outcome.PASS}
    delivered = [r for r in service.fetches if r.path.endswith("big.bin")]
    assert delivered


def test_range_is_answered_with_206_and_a_content_range(service: FakeService) -> None:
    report = run(service, "content.resource.range")

    (record,) = report.records
    assert record.outcome is Outcome.PASS
    assert "interoperability" not in [o.id for o in report.observations]
    (fetch,) = [r for r in service.fetches if r.headers.get("Range")]
    assert fetch.headers["Range"].startswith("bytes=0-")


def test_missing_range_support_is_an_observation_not_a_fail(
    service: FakeService,
) -> None:
    service.ignore_range = True

    report = run(service, "content.resource.range")

    (record,) = report.records
    assert record.outcome is Outcome.PASS
    assert record.note is not None
    assert "interoperability" in [o.id for o in report.observations]


def test_a_content_range_that_does_not_match_fails(service: FakeService) -> None:
    service.answer_file(
        "book0/ncc.html", 206, BODY[:10], {"Content-Range": "bytes 5-14/200"}
    )

    (record,) = run(service, "content.resource.range").records

    assert record.outcome is Outcome.FAIL
    assert record.spec_ref == SPEC_REFS["type.resources"]


def test_a_resource_on_another_host_is_skipped_without_trust_host(
    service: FakeService,
) -> None:
    service.offer_resources(
        "book0",
        [ContentResource("http://127.0.0.2:9/x", "text/html", 1, "x.html")],
        issued=False,
    )

    report = run(service, "content.resource")

    assert set(outcomes(report).values()) == {Outcome.SKIP}


def test_unissued_content_must_answer_invalid_parameter(service: FakeService) -> None:
    service.inject_deviation("getContentResources")

    (record,) = run(service, "content.resources.not-issued").records

    assert record.outcome is Outcome.FAIL


def test_unissued_content_that_is_in_fact_issued_is_skipped(
    service: FakeService,
) -> None:
    service.books["book1"] = ((), True)
    service.offer_catalog(lists("book1"), [BOOK, OTHER])

    (record,) = run(service, "content.resources.not-issued").records

    assert record.outcome is Outcome.SKIP
