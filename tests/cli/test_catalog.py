"""`dod list` and `dod metadata` through the CLI boundary.

Subprocess tests run the installed console script against the fake Service on
localhost, with `DOD_STATE_DIR` in a temporary directory. Users, books and
passwords are synthetic.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from dod.domain.v1 import ContentItem, ContentList, ContentMetadata
from support import PASSWORD, FakeService, run_dod
from support._fake_service import NS, SOAP

USER = "synthetic-user"
ITEMS = tuple(
    ContentItem(id=f"book{n}", label=f"Book {n}", lang="en") for n in range(3)
)
ISSUED = ContentList(id="issued", total_items=1, items=ITEMS[:1])
NEW = ContentList(id="new", total_items=3, items=ITEMS, label="New")
BOOK = ContentMetadata(
    title="Book 0",
    identifier="book0",
    format="Daisy 2.02",
    size=1234,
    requires_return=False,
    creators=("Synthetic Author",),
    meta=(("synthetic:key", "value"),),
)


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD)
    fake.offer_catalog([ISSUED, NEW], [BOOK])
    yield fake
    fake.stop()


def dod(  # type: ignore[no-untyped-def]
    service: FakeService, state: Path, *args: str
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
        env={"DOD_STATE_DIR": str(state)},
    )


def last_request(service: FakeService) -> str:
    return service.requests[-1].body.decode()


def test_list_without_an_id_shows_the_shelf(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "list")

    assert result.returncode == 0, result.stderr
    assert "<id>issued</id>" in last_request(service)
    assert "<firstItem>0</firstItem><lastItem>-1</lastItem>" in last_request(service)
    assert result.stdout.splitlines() == [
        "list issued: items 0-0 of 1",
        "book0: Book 0",
    ]


def test_list_with_an_id_and_a_range_gets_that_segment(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(
        service, tmp_path, "list", "--id", "new", "--first", "1", "--last", "2"
    )

    assert result.returncode == 0, result.stderr
    assert "<id>new</id>" in last_request(service)
    assert "<firstItem>1</firstItem><lastItem>2</lastItem>" in last_request(service)
    assert result.stdout.splitlines() == [
        "list new: items 1-2 of 3",
        "book1: Book 1",
        "book2: Book 2",
    ]


def test_list_with_an_empty_segment_says_how_many_there_are(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "list", "--id", "new", "--first", "9")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["list new: no items (3 in total)"]


def test_a_list_id_with_spaces_can_be_quoted_and_is_sent_as_given(
    service: FakeService, tmp_path: Path
) -> None:
    service.offer_catalog(
        [ContentList(id="my list", total_items=1, items=ITEMS[:1])], [BOOK]
    )

    result = dod(service, tmp_path, "list", "--id", "my list")

    assert result.returncode == 0, result.stderr
    assert "<id>my list</id>" in last_request(service)
    assert "book0: Book 0" in result.stdout


def test_an_identifier_that_breaks_nmtoken_is_a_schema_violation_not_an_error(
    service: FakeService, tmp_path: Path
) -> None:
    service.offer_catalog(
        [ContentList(id="my list", total_items=1, items=ITEMS[:1])], [BOOK]
    )

    result = dod(service, tmp_path, "list", "--id", "my list")

    assert result.returncode == 0, result.stderr
    assert "schema violation in getContentList" in result.stderr
    assert "schema violation" not in result.stdout


def test_list_as_json_is_a_stable_document(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "list", "--id", "new", "--format", "json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "result": "ok",
        "list": {
            "id": "new",
            "label": "New",
            "total_items": 3,
            "first_item": 0,
            "last_item": 2,
            "items": [
                {
                    "id": f"book{n}",
                    "label": f"Book {n}",
                    "lang": "en",
                    "last_modified": None,
                }
                for n in range(3)
            ],
        },
    }


def test_list_as_the_raw_response(service: FakeService, tmp_path: Path) -> None:
    result = dod(service, tmp_path, "list", "--format", "xml")

    assert result.stdout.lstrip().startswith("<soap:Envelope")
    assert "<contentList" in result.stdout
    assert "logOn" not in result.stdout


def test_elements_dod_does_not_know_do_not_break_list_or_metadata(
    service: FakeService, tmp_path: Path
) -> None:
    dod(service, tmp_path, "logon")
    service.respond_with(
        200,
        (
            f'<soap:Envelope xmlns:soap="{SOAP}"><soap:Body>'
            f'<getContentListResponse xmlns="{NS}">'
            '<contentList id="issued" totalItems="1" extra="x">'
            '<surprise a="b"/><contentItem id="b1"><label xml:lang="en">'
            "<text>Odd</text></label><unknown/></contentItem></contentList>"
            "</getContentListResponse></soap:Body></soap:Envelope>"
        ).encode(),
    )

    result = dod(service, tmp_path, "list")

    assert result.returncode == 0, result.stderr
    assert "b1: Odd" in result.stdout.splitlines()
    assert "schema violation" in result.stderr


def test_a_fault_from_the_service_is_shown_as_it_came(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "list", "--id", "nope")

    assert result.returncode == 1
    assert "getContentList: fault invalidParameter: unknown list" in result.stdout


def test_text_from_the_service_cannot_forge_lines_or_drive_the_terminal(
    service: FakeService, tmp_path: Path
) -> None:
    hostile = ContentItem(id="x", label="a\nlogOn: ok\x9b31m\x85b")
    service.offer_catalog(
        [ContentList(id="issued", total_items=1, items=(hostile,))], []
    )

    result = dod(service, tmp_path, "list")

    assert "\x9b" not in result.stdout
    assert "\x85" not in result.stdout
    assert "logOn: ok" not in result.stdout.splitlines()


def test_an_expired_session_is_replaced_once_by_the_session_manager(
    service: FakeService, tmp_path: Path
) -> None:
    dod(service, tmp_path, "logon")
    service.sessions.clear()

    result = dod(service, tmp_path, "list")

    assert result.returncode == 0, result.stderr
    operations = [r.operation for r in service.requests]
    assert operations[-5:] == [
        "getContentList",
        "logOn",
        "getServiceAttributes",
        "setReadingSystemAttributes",
        "getContentList",
    ]


def test_metadata_shows_a_book_that_is_not_issued(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "metadata", "book0")

    assert result.returncode == 0, result.stderr
    assert "<contentID>book0</contentID>" in last_request(service)
    lines = result.stdout.splitlines()
    assert "title: Book 0" in lines
    assert "identifier: book0" in lines
    assert "size: 1234" in lines
    assert "requires_return: false" in lines
    assert "creators: Synthetic Author" in lines
    assert "meta: synthetic:key=value" in lines


def test_metadata_as_json(service: FakeService, tmp_path: Path) -> None:
    result = dod(service, tmp_path, "metadata", "book0", "--format", "json")

    document = json.loads(result.stdout)
    assert document["result"] == "ok"
    assert document["metadata"]["title"] == "Book 0"
    assert document["metadata"]["creators"] == ["Synthetic Author"]
    assert document["metadata"]["meta"] == [
        {"name": "synthetic:key", "content": "value"}
    ]


def test_metadata_as_the_raw_response(service: FakeService, tmp_path: Path) -> None:
    result = dod(service, tmp_path, "metadata", "book0", "--format", "xml")

    assert "<contentMetadata" in result.stdout
    assert "logOn" not in result.stdout


def test_metadata_for_an_unknown_book_is_the_services_fault(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "metadata", "nope")

    assert result.returncode == 1
    assert "getContentMetadata: fault invalidParameter: unknown content" in (
        result.stdout
    )


def test_metadata_with_spaces_in_the_identifier_can_be_quoted(
    service: FakeService, tmp_path: Path
) -> None:
    spaced = ContentMetadata(
        title="T", identifier="a b", format="Daisy 2.02", size=1, requires_return=False
    )
    service.offer_catalog([], [spaced])

    result = dod(service, tmp_path, "metadata", "a b")

    assert result.returncode == 0, result.stderr
    assert "identifier: a b" in result.stdout.splitlines()
