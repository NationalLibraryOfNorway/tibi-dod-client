"""What a resources answer may name: local paths, addresses and book directories.

All of it is untrusted (ADR 0008). These tests use the application's public
interface only and no file system.
"""

from pathlib import Path

import pytest

from dod.application import (
    ResourceRefused,
    book_directory,
    resolve_resource_uri,
    safe_segment,
    validate_resources,
)
from dod.domain.v1 import ContentResource


def resource(
    local_uri: str, *, size: int | None = 1, uri: str = "x"
) -> ContentResource:
    return ContentResource(
        uri=uri, mime_type="audio/mpeg", size=size, local_uri=local_uri
    )


@pytest.mark.parametrize(
    "local_uri",
    [
        "a.mp3",
        "sub/dir/a.mp3",
        "with space.mp3",
        "ø æ å.mp3",
        "a%20b.mp3",
        "..a",
        "a..b",
    ],
)
def test_ordinary_relative_paths_are_accepted(local_uri: str) -> None:
    assert validate_resources([resource(local_uri)]) == ()


@pytest.mark.parametrize(
    "local_uri",
    [
        "",
        "../a.mp3",
        "sub/../../a.mp3",
        "sub/..",
        "./a.mp3",
        "sub/./a.mp3",
        "/etc/passwd",
        "//host/share/a.mp3",
        "sub//a.mp3",
        "sub/",
        "..\\a.mp3",
        "sub\\a.mp3",
        "C:/a.mp3",
        "c:a.mp3",
        "a.mp3:stream",
        "%2e%2e/a.mp3",
        "%2E%2E%2Fa.mp3",
        "%5Ca.mp3",
        "%2Fetc/passwd",
        "a%00.mp3",
        "a\nb.mp3",
        "a?b.mp3",
        "a*.mp3",
        "trailing-dot.",
        "trailing-space ",
        "dir./a.mp3",
        "CON",
        "nul.txt",
        "sub/COM1.mp3",
        "bad%ffbytes.mp3",
        "x" * 300,
    ],
)
def test_a_path_that_could_leave_the_target_or_not_be_portable_is_a_violation(
    local_uri: str,
) -> None:
    problems = validate_resources([resource("fine.mp3"), resource(local_uri)])

    assert len(problems) == 1, problems
    assert "fine.mp3" not in problems[0]


def test_two_entries_for_one_file_are_a_violation_also_across_case_and_encoding() -> (
    None
):
    problems = validate_resources([resource("a.mp3"), resource("A.MP3")])

    assert problems != ()


def test_a_file_that_is_also_a_directory_is_a_violation() -> None:
    assert validate_resources([resource("a"), resource("a/b.mp3")]) != ()


def test_a_final_name_that_is_another_entrys_partial_file_is_a_violation() -> None:
    assert validate_resources([resource("a.mp3"), resource("a.mp3.part")]) != ()


@pytest.mark.parametrize("size", [None, -1])
def test_a_size_that_is_missing_or_negative_is_a_violation(size: int | None) -> None:
    assert validate_resources([resource("a.mp3", size=size)]) != ()


def test_every_violation_is_reported_not_only_the_first() -> None:
    problems = validate_resources(
        [resource("../a"), resource("b/../c"), resource("ok")]
    )

    assert len(problems) == 2


@pytest.mark.parametrize(
    ("content_id", "segment"),
    [
        ("book0", "book0"),
        ("ABC_def-1", "ABC_def-1"),
        ("a.b", "a.b"),
        ("..", "%2E%2E"),
        (".", "%2E"),
        (".hidden", "%2Ehidden"),
        ("name.", "name%2E"),
        ("a/b", "a%2Fb"),
        ("a\\b", "a%5Cb"),
        ("../../x", "%2E.%2F..%2Fx"),
        ("C:", "C%3A"),
        ("100%", "100%25"),
        ("with space", "with%20space"),
        ("bok\u00e5", "bok%C3%A5"),
        ("CON", "%43ON"),
        ("lpt1.txt", "%6Cpt1.txt"),
        ("", "%"),
    ],
)
def test_a_content_id_becomes_one_safe_path_segment(
    content_id: str, segment: str
) -> None:
    assert safe_segment(content_id) == segment


def test_a_very_long_content_id_is_shortened_but_stays_distinct() -> None:
    first = safe_segment("x" * 300 + "1")
    second = safe_segment("x" * 300 + "2")

    assert len(first) < 100
    assert first != second
    assert first == safe_segment("x" * 300 + "1")


def test_the_book_directory_is_under_data_environment_and_books() -> None:
    assert book_directory(Path("data"), "prod", "book0") == Path(
        "data", "prod", "books", "book0"
    )
    assert book_directory(Path("data"), "../x", "..") == Path(
        "data", "%2E.%2Fx", "books", "%2E%2E"
    )


SERVICE = "https://dod.example.org/service"


def test_a_relative_address_is_resolved_against_the_service_url() -> None:
    resolved = resolve_resource_uri(
        "files/a.mp3", SERVICE, trust_host=False, insecure=False
    )

    assert resolved.url == "https://dod.example.org/files/a.mp3"
    assert [o.id for o in resolved.observations] == ["interoperability"]


def test_an_absolute_address_on_the_service_host_needs_no_trust() -> None:
    resolved = resolve_resource_uri(
        "https://dod.example.org/files/a.mp3", SERVICE, trust_host=False, insecure=False
    )

    assert resolved.url == "https://dod.example.org/files/a.mp3"
    assert resolved.observations == ()


def test_another_host_is_refused_without_trust_host() -> None:
    with pytest.raises(ResourceRefused, match="--trust-host"):
        resolve_resource_uri(
            "https://cdn.example.net/a.mp3", SERVICE, trust_host=False, insecure=False
        )


def test_another_host_is_accepted_with_trust_host_and_an_observation() -> None:
    resolved = resolve_resource_uri(
        "https://user:secret@cdn.example.net/a.mp3",
        SERVICE,
        trust_host=True,
        insecure=False,
    )

    assert resolved.url == "https://user:secret@cdn.example.net/a.mp3"
    [observation] = resolved.observations
    assert observation.id == "host-boundary"
    assert "secret" not in observation.message
    assert "cdn.example.net" in observation.message


def test_another_port_or_scheme_on_the_same_host_is_another_origin() -> None:
    for uri in ("https://dod.example.org:8443/a", "http://dod.example.org/a"):
        with pytest.raises(ResourceRefused):
            resolve_resource_uri(uri, SERVICE, trust_host=False, insecure=True)


def test_a_network_path_reference_is_another_host_not_a_relative_path() -> None:
    with pytest.raises(ResourceRefused, match="--trust-host"):
        resolve_resource_uri(
            "//cdn.example.net/a.mp3", SERVICE, trust_host=False, insecure=False
        )


def test_http_is_refused_without_insecure() -> None:
    with pytest.raises(ResourceRefused, match="--insecure"):
        resolve_resource_uri(
            "http://cdn.example.net/a.mp3", SERVICE, trust_host=True, insecure=False
        )


@pytest.mark.parametrize("uri", ["", "ftp://dod.example.org/a", "file:///etc/passwd"])
def test_an_empty_address_or_another_scheme_is_refused(uri: str) -> None:
    with pytest.raises(ResourceRefused):
        resolve_resource_uri(uri, SERVICE, trust_host=True, insecure=True)
