"""`dod bookmarks` and `dod key-exchange` through the CLI boundary (ADR 0003, 0005).

Subprocess tests run the installed console script against the fake Service on
localhost, with `DOD_STATE_DIR` in a temporary directory. The password is the
first line of stdin. Users, books, passwords and keys are synthetic.
"""

import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from dod.domain.v1 import ContentMetadata
from support import PASSWORD, FakeService, run_dod
from support.samples import KEY_EXCHANGE, bookmark_set

USER = "synthetic-user"
KEY = "c3ludGhldGlj"
BOOK = ContentMetadata(title="Book", identifier="book0", format="Daisy 2.02", size=1)
LASTMARK = (
    "<lastmark><ncxRef>hix00023</ncxRef><URI>s023.smil#main</URI>"
    "<timeOffset>97.826</timeOffset></lastmark>"
)


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD)
    fake.offer_catalog([], [BOOK])
    fake.offer_key_exchange("synthetic-key", KEY_EXCHANGE)
    yield fake
    fake.stop()


def dod(  # type: ignore[no-untyped-def]
    service: FakeService, tmp_path: Path, *args: str
):
    """Run `dod` against the fake Service, in an Environment named `test`."""
    config = tmp_path / "config.toml"
    config.write_text(
        f'[environments.test]\nurl = "{service.url}"\ninsecure = true\n'
        f'username = "{USER}"\n',
        encoding="utf-8",
    )
    if sys.platform != "win32":
        config.chmod(0o600)
    return run_dod(
        *args,
        "--env",
        "test",
        "--config",
        str(config),
        "--password-stdin",
        stdin=PASSWORD + "\n",
        env={"DOD_STATE_DIR": str(tmp_path / "state")},
    )


def operations(service: FakeService) -> list[str | None]:
    return [request.operation for request in service.requests]


def write(tmp_path: Path, text: str, name: str = "set.xml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def last_body(service: FakeService, operation: str) -> str:
    sent = [r for r in service.requests if r.operation == operation]
    return sent[-1].body.decode()


# -- bookmarks get ---------------------------------------------------------------


def test_get_shows_the_bookmark_set_as_received_without_the_operation_being_declared(
    service: FakeService, tmp_path: Path
) -> None:
    stored = bookmark_set("book0", lastmark=LASTMARK, bookmarks=1)
    service.offer_bookmarks("book0", stored)

    result = dod(service, tmp_path, "bookmarks", "get", "book0")

    assert result.returncode == 0, result.stderr
    assert "<contentID>book0</contentID>" in last_body(service, "getBookmarks")
    assert result.stdout.strip() == stored
    assert "<timeOffset>97.826</timeOffset>" in result.stdout


def test_get_of_a_book_without_bookmarks_shows_the_empty_set(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "bookmarks", "get", "book0")

    assert result.returncode == 0, result.stderr
    assert "<uid>book0</uid>" in result.stdout


def test_get_as_json_summarises_the_set_and_keeps_the_xml(
    service: FakeService, tmp_path: Path
) -> None:
    service.offer_bookmarks("book0", bookmark_set("book0", lastmark=LASTMARK))

    result = dod(service, tmp_path, "bookmarks", "get", "book0", "--format", "json")

    document = json.loads(result.stdout)
    assert document["result"] == "ok"
    assert document["bookmark_set"]["lastmark"] == {
        "ncx_ref": "hix00023",
        "uri": "s023.smil#main",
        "time_offset": "97.826",
        "char_offset": None,
    }
    assert "<uid>book0</uid>" in document["bookmark_set"]["xml"]


def test_get_as_xml_is_the_raw_response(service: FakeService, tmp_path: Path) -> None:
    result = dod(service, tmp_path, "bookmarks", "get", "book0", "--format", "xml")

    assert "<getBookmarksResponse" in result.stdout


def test_get_of_unknown_content_shows_the_fault_as_it_came(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "bookmarks", "get", "nothing")

    assert result.returncode == 1
    assert "getBookmarks: fault invalidParameter: unknown content" in result.stdout


def test_get_never_lets_control_characters_of_the_service_reach_the_terminal(
    service: FakeService, tmp_path: Path
) -> None:
    service.offer_bookmarks("book0", bookmark_set("book0", title="a&#x9b;31mb"))

    result = dod(service, tmp_path, "bookmarks", "get", "book0")

    assert not re.search(r"[\x80-\x9f]", result.stdout)
    assert "a 31mb" in result.stdout


# -- bookmarks set ---------------------------------------------------------------


def test_set_sends_the_set_as_it_is_and_the_service_replaces_the_old_one(
    service: FakeService, tmp_path: Path
) -> None:
    service.offer_bookmarks("book0", bookmark_set("book0", bookmarks=2))
    sent = bookmark_set("book0", lastmark=LASTMARK)
    file = write(tmp_path, sent)

    result = dod(service, tmp_path, "bookmarks", "set", "book0", "--file", str(file))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["setBookmarks: ok"]
    body = last_body(service, "setBookmarks")
    assert "<contentID>book0</contentID>" in body
    assert LASTMARK in body
    shown = dod(service, tmp_path, "bookmarks", "get", "book0")
    assert "<bookmark " not in shown.stdout
    assert LASTMARK in shown.stdout


def test_set_refuses_a_file_that_breaks_the_bookmark_schema_and_sends_nothing(
    service: FakeService, tmp_path: Path
) -> None:
    broken = bookmark_set("book0").replace("<uid>book0</uid>", "")
    file = write(tmp_path, broken)

    result = dod(service, tmp_path, "bookmarks", "set", "book0", "--file", str(file))

    assert result.returncode == 2
    assert "set.xml" in result.stderr
    assert "uid" in result.stderr or "Missing child element" in result.stderr
    assert operations(service) == []


@pytest.mark.parametrize(
    "text",
    ["<bookmarkSet", "<foo/>", '<!DOCTYPE x [<!ENTITY e "v">]><bookmarkSet/>'],
)
def test_set_refuses_what_is_not_a_bookmark_set(
    service: FakeService, tmp_path: Path, text: str
) -> None:
    file = write(tmp_path, text)

    result = dod(service, tmp_path, "bookmarks", "set", "book0", "--file", str(file))

    assert result.returncode == 2
    assert operations(service) == []


def test_set_with_a_missing_file_is_a_usage_error_and_sends_nothing(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(
        service, tmp_path, "bookmarks", "set", "book0", "--file", str(tmp_path / "no")
    )

    assert result.returncode == 2
    assert "cannot be read" in result.stderr
    assert operations(service) == []


def test_set_shows_the_services_fault_as_it_came(
    service: FakeService, tmp_path: Path
) -> None:
    file = write(tmp_path, bookmark_set("other"))

    result = dod(service, tmp_path, "bookmarks", "set", "book0", "--file", str(file))

    assert result.returncode == 1
    assert "setBookmarks: fault invalidParameter" in result.stdout


def test_set_help_warns_that_the_whole_set_is_replaced_and_says_to_read_first() -> None:
    result = run_dod("bookmarks", "set", "--help")

    text = " ".join(result.stdout.split())
    assert result.returncode == 0, result.stderr
    assert "replaces the whole set" in text
    assert "dod bookmarks get" in text
    assert "--file" in text


def test_the_bookmark_commands_are_listed() -> None:
    result = run_dod("bookmarks", "--help")

    for command in ("get", "set"):
        assert re.search(rf"^\W*{command}\s", result.stdout, re.M), result.stdout


# -- key-exchange ----------------------------------------------------------------


def test_key_exchange_shows_the_answer_with_the_key_material_masked(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "key-exchange", "synthetic-key")

    assert result.returncode == 0, result.stderr
    assert "<requestedKeyName>synthetic-key</requestedKeyName>" in last_body(
        service, "getKeyExchangeObject"
    )
    assert KEY not in result.stdout
    assert re.search(
        r'collectionID="synthetic">\*\*\*\[[0-9a-f]{6}\]</UAK>', result.stdout
    )
    assert '<Issuer uid="DAISY.synthetic">Synthetic issuer</Issuer>' in result.stdout


@pytest.mark.parametrize("output", ["json", "xml"])
def test_key_exchange_masks_the_key_in_every_format(
    service: FakeService, tmp_path: Path, output: str
) -> None:
    result = dod(service, tmp_path, "key-exchange", "synthetic-key", "--format", output)

    assert result.returncode == 0, result.stderr
    assert KEY not in result.stdout
    assert "Synthetic issuer" in result.stdout


def test_key_exchange_never_writes_the_key_to_diagnostics_or_saved_files(
    service: FakeService, tmp_path: Path
) -> None:
    saved = tmp_path / "exchanges"

    shown = dod(service, tmp_path, "key-exchange", "synthetic-key", "--debug")
    kept = dod(
        service,
        tmp_path,
        "key-exchange",
        "synthetic-key",
        "--save-exchanges",
        str(saved),
    )

    assert shown.returncode == kept.returncode == 0
    assert KEY not in shown.stderr
    files = [f for f in saved.rglob("*") if f.is_file()]
    assert files
    assert not any(KEY in f.read_text(encoding="utf-8") for f in files)


def test_key_exchange_of_an_unknown_key_shows_the_fault_as_it_came(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "key-exchange", "no-such-key")

    assert result.returncode == 1
    assert "getKeyExchangeObject: fault invalidParameter: unknown key" in result.stdout


def test_key_exchange_help_says_what_it_asks_for_and_that_dod_has_no_drm() -> None:
    result = run_dod("key-exchange", "--help")

    text = " ".join(result.stdout.split())
    assert result.returncode == 0, result.stderr
    assert "PDTB2 Key Exchange Object" in text
    assert "rarely used" in text
    assert "does not interpret" in text
    assert "DRM" in text
