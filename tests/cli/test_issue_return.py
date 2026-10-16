"""`dod issue` and `dod return` through the CLI boundary (ADR 0003, 0005, 0008).

Subprocess tests run the installed console script against the fake Service on
localhost, with `DOD_STATE_DIR` and `DOD_DATA_DIR` in a temporary directory.
The password is the first line of stdin and an answer to the deletion prompt is
the second. Users, books and passwords are synthetic.
"""

import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from dod.domain.v1 import ContentMetadata, ContentResource
from support import FakeService, run_dod

USER = "synthetic-user"
PASSWORD = "synthetic-secret"
CHAPTER = ContentResource(
    uri="files/chapter1.mp3", mime_type="audio/mpeg", size=11, local_uri="chapter1.mp3"
)


def metadata(identifier: str, *, requires_return: bool) -> ContentMetadata:
    return ContentMetadata(
        title="Synthetic title",
        identifier=identifier,
        format="Daisy 2.02",
        size=1,
        requires_return=requires_return,
    )


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD)
    fake.offer_resources("borrowed", [CHAPTER])
    fake.offer_resources("free", [CHAPTER])
    fake.offer_resources("shelf", [CHAPTER], issued=False)
    fake.offer_catalog(
        [],
        [
            metadata("borrowed", requires_return=True),
            metadata("free", requires_return=False),
            metadata("shelf", requires_return=True),
        ],
    )
    yield fake
    fake.stop()


def dod(  # type: ignore[no-untyped-def]
    service: FakeService,
    tmp_path: Path,
    *args: str,
    answer: str = "",
    with_environment: bool = True,
):
    """Run `dod` against the fake Service, in an Environment named `test`."""
    env = {
        "DOD_STATE_DIR": str(tmp_path / "state"),
        "DOD_DATA_DIR": str(tmp_path / "data"),
    }
    if not with_environment:
        return run_dod(
            *args,
            "--url",
            service.url,
            "--username",
            USER,
            "--password-stdin",
            "--insecure",
            stdin=PASSWORD + "\n" + answer,
            env=env,
        )
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
        stdin=PASSWORD + "\n" + answer,
        env=env,
    )


def operations(service: FakeService) -> list[str | None]:
    return [request.operation for request in service.requests]


def local_copy(tmp_path: Path, content_id: str) -> Path:
    """Create a downloaded book as `dod download` leaves it."""
    book = tmp_path / "data" / "test" / "books" / content_id
    book.mkdir(parents=True)
    (book / "chapter1.mp3").write_bytes(b"hello world")
    return book


# -- issue -------------------------------------------------------------------


def test_issue_calls_issue_content_and_shows_the_reply_unchanged(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "issue", "shelf")

    assert result.returncode == 0, result.stderr
    assert operations(service)[-1] == "issueContent"
    assert "<contentID>shelf</contentID>" in service.requests[-1].body.decode()
    assert result.stdout.splitlines() == ["issueContent: ok"]
    assert service.books["shelf"][1] is True


def test_issue_of_unknown_content_shows_the_fault_as_it_came(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "issue", "nothing")

    assert result.returncode == 1
    assert "issueContent: fault invalidParameter: unknown content" in result.stdout


def test_issue_can_show_json_and_the_raw_xml(
    service: FakeService, tmp_path: Path
) -> None:
    as_json = dod(service, tmp_path, "issue", "shelf", "--format", "json")
    as_xml = dod(service, tmp_path, "issue", "shelf", "--format", "xml")

    assert json.loads(as_json.stdout) == {"result": "ok"}
    assert "<issueContentResult>true</issueContentResult>" in as_xml.stdout


# -- return ------------------------------------------------------------------


def test_return_deletes_the_local_copy_and_then_returns_the_content(
    service: FakeService, tmp_path: Path
) -> None:
    book = local_copy(tmp_path, "borrowed")
    neighbour = local_copy(tmp_path, "other")

    result = dod(service, tmp_path, "return", "borrowed", "--yes")

    assert result.returncode == 0, result.stderr
    assert not book.exists()
    assert (neighbour / "chapter1.mp3").read_bytes() == b"hello world"
    assert operations(service)[-1] == "returnContent"
    assert "<contentID>borrowed</contentID>" in service.requests[-1].body.decode()
    assert result.stdout.splitlines() == [
        f"local copy: deleted {book}",
        "returnContent: ok",
    ]
    assert service.books["borrowed"][1] is False


def test_return_asks_before_deleting_and_does_nothing_when_declined(
    service: FakeService, tmp_path: Path
) -> None:
    book = local_copy(tmp_path, "borrowed")

    result = dod(service, tmp_path, "return", "borrowed", answer="n\n")

    assert result.returncode != 0
    assert (book / "chapter1.mp3").exists()
    assert "returnContent" not in operations(service)
    assert service.books["borrowed"][1] is True


def test_return_goes_ahead_when_the_deletion_is_confirmed(
    service: FakeService, tmp_path: Path
) -> None:
    book = local_copy(tmp_path, "borrowed")

    result = dod(service, tmp_path, "return", "borrowed", answer="y\n")

    assert result.returncode == 0, result.stderr
    assert not book.exists()
    assert operations(service)[-1] == "returnContent"


def test_return_without_a_local_copy_does_not_ask(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "return", "borrowed")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["local copy: none", "returnContent: ok"]


def test_keep_local_returns_without_deleting_and_warns_about_the_specification(
    service: FakeService, tmp_path: Path
) -> None:
    book = local_copy(tmp_path, "borrowed")

    result = dod(service, tmp_path, "return", "borrowed", "--keep-local")

    assert result.returncode == 0, result.stderr
    assert (book / "chapter1.mp3").exists()
    assert "specification" in result.stderr
    assert "local copy: kept" in result.stdout
    assert operations(service)[-1] == "returnContent"


def test_content_that_needs_no_return_is_refused_before_anything_is_deleted(
    service: FakeService, tmp_path: Path
) -> None:
    book = local_copy(tmp_path, "free")

    result = dod(service, tmp_path, "return", "free", "--yes")

    assert result.returncode == 2
    assert "requiresReturn" in result.stderr
    assert "--force" in result.stderr
    assert (book / "chapter1.mp3").exists()
    assert "returnContent" not in operations(service)


def test_force_returns_content_that_needs_no_return(
    service: FakeService, tmp_path: Path
) -> None:
    book = local_copy(tmp_path, "free")

    result = dod(service, tmp_path, "return", "free", "--yes", "--force")

    assert result.returncode == 0, result.stderr
    assert not book.exists()
    assert operations(service)[-1] == "returnContent"


def test_returning_twice_answers_true_both_times(
    service: FakeService, tmp_path: Path
) -> None:
    first = dod(service, tmp_path, "return", "borrowed")
    second = dod(service, tmp_path, "return", "borrowed")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert second.stdout.splitlines()[-1] == "returnContent: ok"


def test_returning_content_that_was_never_borrowed_answers_true(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "return", "shelf")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == "returnContent: ok"


def test_a_false_answer_is_a_deviation(service: FakeService, tmp_path: Path) -> None:
    service.inject_false("returnContent")

    result = dod(service, tmp_path, "return", "borrowed")

    assert result.returncode == 1
    assert "returnContent: deviation:" in result.stdout
    assert "false" in result.stdout


def test_a_fault_from_return_is_shown_as_it_came(
    service: FakeService, tmp_path: Path
) -> None:
    service.inject_fault("returnContent", "internalServerError", "synthetic failure")

    result = dod(service, tmp_path, "return", "borrowed", "--format", "json")

    assert result.returncode == 1
    assert json.loads(result.stdout)["result"] == (
        "fault internalServerError: synthetic failure"
    )


def test_return_of_unknown_content_stops_at_the_metadata_fault(
    service: FakeService, tmp_path: Path
) -> None:
    book = local_copy(tmp_path, "nothing")

    result = dod(service, tmp_path, "return", "nothing", "--yes")

    assert result.returncode == 1
    assert "getContentMetadata: fault invalidParameter" in result.stdout
    assert (book / "chapter1.mp3").exists()
    assert "returnContent" not in operations(service)


def test_return_reports_json(service: FakeService, tmp_path: Path) -> None:
    book = local_copy(tmp_path, "borrowed")

    result = dod(service, tmp_path, "return", "borrowed", "--yes", "--format", "json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "result": "ok",
        "local_copy": "deleted",
        "directory": str(book),
    }


def test_without_an_environment_return_needs_keep_local(
    service: FakeService, tmp_path: Path
) -> None:
    refused = dod(service, tmp_path, "return", "borrowed", with_environment=False)

    assert refused.returncode == 2
    assert "--keep-local" in refused.stderr
    assert service.requests == []

    kept = dod(
        service, tmp_path, "return", "borrowed", "--keep-local", with_environment=False
    )

    assert kept.returncode == 0, kept.stderr
    assert operations(service)[-1] == "returnContent"


def test_a_content_id_that_is_a_path_deletes_only_its_own_safe_directory(
    service: FakeService, tmp_path: Path
) -> None:
    service.offer_resources("../../x", [CHAPTER])
    service.offer_catalog([], [metadata("../../x", requires_return=True)])
    outside = tmp_path / "x"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    book = local_copy(tmp_path, "%2E.%2F..%2Fx")

    result = dod(service, tmp_path, "return", "../../x", "--yes")

    assert result.returncode == 0, result.stderr
    assert not book.exists()
    assert (outside / "keep.txt").exists()
    assert (tmp_path / "data" / "test" / "books").is_dir()


def test_return_has_no_xml_output(service: FakeService, tmp_path: Path) -> None:
    result = dod(service, tmp_path, "return", "borrowed", "--format", "xml")

    assert result.returncode == 2
    assert service.requests == []
