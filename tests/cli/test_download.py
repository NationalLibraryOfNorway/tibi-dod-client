"""`dod resources` and `dod download` through the CLI boundary (ADR 0003, 0008).

Subprocess tests run the installed console script against the fake Service on
localhost, with `DOD_STATE_DIR` and `DOD_DATA_DIR` in a temporary directory.
Everything a resources answer names is untrusted, so most tests here are about
what is not written and not sent. Users, books and passwords are synthetic.
"""

import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from dod.domain.v1 import ContentResource
from support import FakeService, run_dod

USER = "synthetic-user"
PASSWORD = "synthetic-secret"
CHAPTER = ContentResource(
    uri="files/chapter1.mp3",
    mime_type="audio/mpeg",
    size=11,
    local_uri="chapter1.mp3",
    last_modified="2024-01-02T03:04:05Z",
)
NCC = ContentResource(
    uri="files/ncc.html", mime_type="text/html", size=5, local_uri="sub/ncc.html"
)


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD)
    fake.offer_resources("book0", [CHAPTER, NCC])
    fake.offer_resources("book1", [CHAPTER], issued=False)
    fake.offer_file("files/chapter1.mp3", b"hello world")
    fake.offer_file("files/ncc.html", b"<html")
    yield fake
    fake.stop()


@pytest.fixture
def other() -> Iterator[FakeService]:
    fake = FakeService()
    fake.offer_file("delegate/a.mp3", b"from delegate")
    yield fake
    fake.stop()


def dod(  # type: ignore[no-untyped-def]
    service: FakeService,
    tmp_path: Path,
    *args: str,
    extra_env: dict[str, str] | None = None,
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
        env={
            "DOD_STATE_DIR": str(tmp_path / "state"),
            "DOD_DATA_DIR": str(tmp_path / "data"),
            **(extra_env or {}),
        },
    )


def operations(service: FakeService) -> list[str | None]:
    return [request.operation for request in service.requests]


def written(root: Path) -> list[str]:
    return sorted(
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    )


# -- resources ---------------------------------------------------------------


def test_resources_shows_the_list_as_the_service_gave_it(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "resources", "book0")

    assert result.returncode == 0, result.stderr
    assert operations(service)[-1] == "getContentResources"
    assert "<contentID>book0</contentID>" in service.requests[-1].body.decode()
    assert result.stdout.splitlines() == [
        "resources: 2",
        "resource 1:",
        "  uri: files/chapter1.mp3",
        "  localURI: chapter1.mp3",
        "  size: 11",
        "  mimeType: audio/mpeg",
        "  lastModifiedDate: 2024-01-02T03:04:05Z",
        "resource 2:",
        "  uri: files/ncc.html",
        "  localURI: sub/ncc.html",
        "  size: 5",
        "  mimeType: text/html",
        "  lastModifiedDate: -",
    ]
    assert service.fetches == []


def test_resources_as_json_is_a_stable_document(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "resources", "book0", "--format", "json")

    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["result"] == "ok"
    assert document["resources"]["resources"][0] == {
        "uri": "files/chapter1.mp3",
        "mime_type": "audio/mpeg",
        "size": 11,
        "local_uri": "chapter1.mp3",
        "last_modified": "2024-01-02T03:04:05Z",
    }


def test_resources_of_content_that_is_not_issued_shows_the_fault_unchanged(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "resources", "book1")

    assert result.returncode == 1
    assert (
        "getContentResources: fault invalidParameter: content is not issued"
        in result.stdout
    )
    assert "issueContent" not in operations(service)


def test_userinfo_in_a_resource_address_is_masked_everywhere_it_is_shown(
    service: FakeService, tmp_path: Path
) -> None:
    service.offer_resources(
        "book2",
        [
            ContentResource(
                uri="https://dg-user:dg-secret@cdn.example.net/a.mp3",
                mime_type="audio/mpeg",
                size=1,
                local_uri="a.mp3",
            )
        ],
    )

    for extra in ([], ["--format", "json"], ["--format", "xml"], ["--debug"]):
        result = dod(service, tmp_path, "resources", "book2", *extra)

        assert result.returncode == 0, result.stderr
        assert "dg-secret" not in result.stdout + result.stderr, extra
        assert "dg-user" not in result.stdout + result.stderr, extra
        assert "@cdn.example.net/a.mp3" in result.stdout + result.stderr, extra


def test_control_characters_in_a_resource_cannot_drive_the_terminal(
    service: FakeService, tmp_path: Path
) -> None:
    service.offer_resources(
        "book2",
        [
            ContentResource(
                uri="files/a\u009b31m.mp3",
                mime_type="audio/mpeg\u0085forged: line",
                size=1,
                local_uri="a.mp3",
            )
        ],
    )

    result = dod(service, tmp_path, "resources", "book2")

    assert "\u009b" not in result.stdout
    assert "\u0085" not in result.stdout
    assert not any(line.startswith("forged") for line in result.stdout.splitlines())


# -- download ----------------------------------------------------------------


def test_download_writes_every_file_under_the_output_directory(
    service: FakeService, tmp_path: Path
) -> None:
    target = tmp_path / "book"

    result = dod(service, tmp_path, "download", "book0", "--output", str(target))

    assert result.returncode == 0, result.stderr
    assert (target / "chapter1.mp3").read_bytes() == b"hello world"
    assert (target / "sub" / "ncc.html").read_bytes() == b"<html"
    assert written(target) == ["chapter1.mp3", "sub/ncc.html"]
    assert "downloaded chapter1.mp3 (11 bytes)" in result.stdout
    assert "downloaded sub/ncc.html (5 bytes)" in result.stdout
    assert operations(service).count("getContentResources") == 1
    assert [f.path for f in service.fetches] == [
        "/files/chapter1.mp3",
        "/files/ncc.html",
    ]


def test_download_never_issues_and_reports_invalid_parameter_as_it_came(
    service: FakeService, tmp_path: Path
) -> None:
    target = tmp_path / "book"

    result = dod(service, tmp_path, "download", "book1", "--output", str(target))

    assert result.returncode == 1
    assert (
        "getContentResources: fault invalidParameter: content is not issued"
        in result.stdout
    )
    assert "issueContent" not in operations(service)
    assert not target.exists()
    assert service.fetches == []


def test_the_default_target_is_data_environment_books_and_the_content_id(
    service: FakeService, tmp_path: Path
) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        f'[environments.test]\nurl = "{service.url}"\ninsecure = true\n'
        f'username = "{USER}"\n',
        encoding="utf-8",
    )
    if sys.platform != "win32":
        config.chmod(0o600)

    result = run_dod(
        "download",
        "book0",
        "--env",
        "test",
        "--config",
        str(config),
        "--password-stdin",
        stdin=PASSWORD + "\n",
        env={
            "DOD_STATE_DIR": str(tmp_path / "state"),
            "DOD_DATA_DIR": str(tmp_path / "data"),
        },
    )

    assert result.returncode == 0, result.stderr
    book = tmp_path / "data" / "test" / "books" / "book0"
    assert (book / "chapter1.mp3").read_bytes() == b"hello world"


def test_a_content_id_that_is_a_path_becomes_one_safe_directory_name(
    service: FakeService, tmp_path: Path
) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        f'[environments.test]\nurl = "{service.url}"\ninsecure = true\n'
        f'username = "{USER}"\n',
        encoding="utf-8",
    )
    if sys.platform != "win32":
        config.chmod(0o600)
    service.offer_resources("../../x", [CHAPTER])

    result = run_dod(
        "download",
        "../../x",
        "--env",
        "test",
        "--config",
        str(config),
        "--password-stdin",
        stdin=PASSWORD + "\n",
        env={
            "DOD_STATE_DIR": str(tmp_path / "state"),
            "DOD_DATA_DIR": str(tmp_path / "data"),
        },
    )

    assert result.returncode == 0, result.stderr
    assert written(tmp_path / "data") == ["test/books/%2E.%2F..%2Fx/chapter1.mp3"]


def test_without_an_environment_output_is_required(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "download", "book0")

    assert result.returncode == 2
    assert "--output" in result.stderr
    assert operations(service) == []
    assert not (tmp_path / "data").exists()


def test_file_fetches_only_the_chosen_files_and_may_be_repeated(
    service: FakeService, tmp_path: Path
) -> None:
    target = tmp_path / "book"

    result = dod(
        service,
        tmp_path,
        "download",
        "book0",
        "--output",
        str(target),
        "--file",
        "sub/ncc.html",
    )

    assert result.returncode == 0, result.stderr
    assert written(target) == ["sub/ncc.html"]
    both = dod(
        service,
        tmp_path,
        "download",
        "book0",
        "--output",
        str(tmp_path / "both"),
        "--file",
        "chapter1.mp3",
        "--file",
        "sub/ncc.html",
    )
    assert both.returncode == 0, both.stderr
    assert written(tmp_path / "both") == ["chapter1.mp3", "sub/ncc.html"]


def test_a_file_that_is_not_in_the_list_fetches_nothing(
    service: FakeService, tmp_path: Path
) -> None:
    target = tmp_path / "book"

    result = dod(
        service,
        tmp_path,
        "download",
        "book0",
        "--output",
        str(target),
        "--file",
        "chapter1.mp3",
        "--file",
        "nope.mp3",
    )

    assert result.returncode == 2
    assert "nope.mp3" in result.stderr
    assert service.fetches == []
    assert not target.exists()


@pytest.mark.parametrize(
    "bad",
    ["../evil.mp3", "/abs/evil.mp3", "sub\\evil.mp3", "C:/evil.mp3", "%2e%2e/evil.mp3"],
)
def test_one_bad_local_uri_aborts_with_nothing_written_not_even_the_good_files(
    service: FakeService, tmp_path: Path, bad: str
) -> None:
    service.offer_resources(
        "book2",
        [
            CHAPTER,
            ContentResource(
                uri="files/ncc.html", mime_type="text/html", size=5, local_uri=bad
            ),
        ],
    )
    target = tmp_path / "out" / "book"

    result = dod(
        service,
        tmp_path,
        "download",
        "book2",
        "--output",
        str(target),
        "--file",
        "chapter1.mp3",
    )

    assert result.returncode == 1
    assert "deviation" in result.stdout
    assert "contradicts DODP v1 section 6.10" in result.stderr
    assert service.fetches == []
    assert written(tmp_path / "out") == []
    assert not (tmp_path / "evil.mp3").exists()
    assert not (tmp_path / "out" / "evil.mp3").exists()


def test_a_file_that_is_shorter_than_announced_is_discarded(
    service: FakeService, tmp_path: Path
) -> None:
    service.offer_resources(
        "book2",
        [
            ContentResource(
                uri="files/ncc.html", mime_type="text/html", size=50, local_uri="a.html"
            )
        ],
    )
    target = tmp_path / "book"

    result = dod(service, tmp_path, "download", "book2", "--output", str(target))

    assert result.returncode == 1
    assert "5 bytes received, the Service announced 50" in result.stdout
    assert written(target) == []


def test_a_file_that_is_longer_than_announced_is_discarded(
    service: FakeService, tmp_path: Path
) -> None:
    service.offer_resources(
        "book2",
        [
            ContentResource(
                uri="files/chapter1.mp3",
                mime_type="audio/mpeg",
                size=3,
                local_uri="a.mp3",
            )
        ],
    )
    target = tmp_path / "book"

    result = dod(service, tmp_path, "download", "book2", "--output", str(target))

    assert result.returncode == 1
    assert "more than the 3 bytes announced" in result.stdout
    assert written(target) == []


def test_a_non_2xx_resource_answer_is_a_deviation_and_never_a_relogin(
    service: FakeService, tmp_path: Path
) -> None:
    service.answer_file("files/chapter1.mp3", 401, b"<html>login</html>")
    target = tmp_path / "book"

    result = dod(service, tmp_path, "download", "book0", "--output", str(target))

    assert result.returncode == 1
    assert "the resource answered HTTP 401" in result.stdout
    assert "contradicts DODP v1 section 6.10" in result.stderr
    assert operations(service).count("logOn") == 1
    assert written(target) == []
    # Files are fetched one at a time and the first failure ends the run.
    assert [f.path for f in service.fetches] == ["/files/chapter1.mp3"]


def test_an_existing_file_is_never_overwritten_without_force(
    service: FakeService, tmp_path: Path
) -> None:
    target = tmp_path / "book"
    target.mkdir()
    (target / "chapter1.mp3").write_bytes(b"mine")

    refused = dod(service, tmp_path, "download", "book0", "--output", str(target))

    assert refused.returncode == 2
    assert "already exists" in refused.stderr
    assert (target / "chapter1.mp3").read_bytes() == b"mine"
    assert service.fetches == []

    forced = dod(
        service, tmp_path, "download", "book0", "--output", str(target), "--force"
    )

    assert forced.returncode == 0, forced.stderr
    assert (target / "chapter1.mp3").read_bytes() == b"hello world"


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need privileges")
def test_a_symbolic_link_in_the_target_cannot_lead_the_download_elsewhere(
    service: FakeService, tmp_path: Path
) -> None:
    target = tmp_path / "book"
    outside = tmp_path / "outside"
    outside.mkdir()
    target.mkdir()
    (target / "sub").symlink_to(outside, target_is_directory=True)

    result = dod(service, tmp_path, "download", "book0", "--output", str(target))

    assert result.returncode == 1
    assert written(outside) == []


def test_another_host_is_refused_without_trust_host_and_nothing_is_fetched(
    service: FakeService, other: FakeService, tmp_path: Path
) -> None:
    service.offer_resources(
        "book2",
        [
            ContentResource(
                uri=other.file_url("delegate/a.mp3"),
                mime_type="audio/mpeg",
                size=13,
                local_uri="a.mp3",
            )
        ],
    )
    target = tmp_path / "book"

    result = dod(service, tmp_path, "download", "book2", "--output", str(target))

    assert result.returncode == 2
    assert "--trust-host" in result.stderr
    assert other.fetches == []
    assert not target.exists()


def test_a_trusted_other_host_gets_no_cookie_and_only_its_own_userinfo(
    service: FakeService, other: FakeService, tmp_path: Path
) -> None:
    url = other.file_url("delegate/a.mp3").replace(
        "http://", "http://dg-user:dg-secret@"
    )
    service.offer_resources(
        "book2",
        [ContentResource(uri=url, mime_type="audio/mpeg", size=13, local_uri="a.mp3")],
    )
    target = tmp_path / "book"

    result = dod(
        service,
        tmp_path,
        "download",
        "book2",
        "--output",
        str(target),
        "--trust-host",
    )

    assert result.returncode == 0, result.stderr
    assert (target / "a.mp3").read_bytes() == b"from delegate"
    sent = other.fetches[-1].headers
    assert "Cookie" not in sent
    assert sent["Authorization"].startswith("Basic ")
    assert PASSWORD not in str(sent)
    assert "observation host-boundary" in result.stderr
    assert "dg-secret" not in result.stdout + result.stderr


def test_a_relative_address_is_resolved_against_the_service_with_an_observation(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(
        service, tmp_path, "download", "book0", "--output", str(tmp_path / "book")
    )

    assert "observation interoperability" in result.stderr
    assert service.fetches[0].headers["Cookie"].startswith("session=")


def test_download_as_json_lists_every_file(
    service: FakeService, tmp_path: Path
) -> None:
    target = tmp_path / "book"

    result = dod(
        service,
        tmp_path,
        "download",
        "book0",
        "--output",
        str(target),
        "--format",
        "json",
    )

    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["result"] == "ok"
    assert [(f["local_uri"], f["outcome"], f["bytes"]) for f in document["files"]] == [
        ("chapter1.mp3", "downloaded", 11),
        ("sub/ncc.html", "downloaded", 5),
    ]


def test_download_has_no_xml_output(service: FakeService, tmp_path: Path) -> None:
    result = dod(
        service,
        tmp_path,
        "download",
        "book0",
        "--output",
        str(tmp_path / "book"),
        "--format",
        "xml",
    )

    assert result.returncode == 2
    assert "xml" in result.stderr
    assert service.fetches == []


def test_the_debug_output_shows_the_resource_exchange_with_its_body_cut(
    service: FakeService, tmp_path: Path
) -> None:
    service.offer_file("files/chapter1.mp3", b"x" * 11)
    big = b"abcdefghij" * 1024
    service.offer_file("files/ncc.html", big)
    service.offer_resources(
        "book2",
        [
            ContentResource(
                uri="files/ncc.html",
                mime_type="text/html",
                size=len(big),
                local_uri="big.html",
            )
        ],
    )

    result = dod(
        service,
        tmp_path,
        "download",
        "book2",
        "--output",
        str(tmp_path / "book"),
        "--debug",
    )

    assert result.returncode == 0, result.stderr
    assert "GET http://127.0.0.1" in result.stderr
    assert "[the body is cut here" in result.stderr
    assert big.decode() not in result.stderr
