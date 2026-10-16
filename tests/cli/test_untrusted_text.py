"""Text and addresses a Service names never reach the output raw (ADR 0007, 0008).

Subprocess tests run the installed console script against the fake Service on
localhost. The fake answers with control characters in fault reasons and with a
WSDL that names an endpoint carrying credentials; every output path, terminal
and JSON, must show neither. Users, books and passwords are synthetic.
"""

import json
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from dod.domain.v1 import Announcement, ContentMetadata, ContentResource
from support import PASSWORD, FakeService, run_dod

USER = "synthetic-user"
HOSTILE = "bad\x9b31mred\rforged"
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
CHAPTER = ContentResource(
    uri="files/c.mp3", mime_type="audio/mpeg", size=1, local_uri="c.mp3"
)


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD)
    fake.offer_resources("book0", [CHAPTER])
    fake.offer_announcements(Announcement(id="a1", text="t", lang="en"))
    fake.offer_catalog(
        [],
        [
            ContentMetadata(
                title="T",
                identifier="book0",
                format="Daisy 2.02",
                size=1,
                requires_return=True,
            )
        ],
    )
    yield fake
    fake.stop()


@pytest.fixture
def other() -> Iterator[FakeService]:
    fake = FakeService()
    yield fake
    fake.stop()


def dod(
    service: FakeService, tmp_path: Path, *args: str
) -> subprocess.CompletedProcess[str]:
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
        },
    )


def assert_plain(result: subprocess.CompletedProcess[str]) -> None:
    assert not CONTROL.search(result.stdout), repr(result.stdout)
    assert not CONTROL.search(result.stderr), repr(result.stderr)


def assert_plain_json(result: subprocess.CompletedProcess[str]) -> None:
    """The parsed values, not the escaped text, are free of control characters."""
    assert_plain(result)

    def walk(value: object) -> None:
        if isinstance(value, str):
            assert not CONTROL.search(value), repr(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(json.loads(result.stdout))


COMMANDS = [
    ("getContentResources", ["download", "book0", "--output"]),
    ("returnContent", ["return", "book0", "--keep-local"]),
    ("markAnnouncementsAsRead", ["announcements", "mark-read", "a1"]),
    ("getServiceAttributes", ["attributes", "service"]),
]


@pytest.mark.parametrize(("operation", "args"), COMMANDS)
@pytest.mark.parametrize("fmt", ["text", "json"])
def test_a_fault_reason_is_shown_without_control_characters(
    service: FakeService,
    tmp_path: Path,
    operation: str,
    args: list[str],
    fmt: str,
) -> None:
    service.inject_fault(operation, "internalServerError", HOSTILE)
    if args[-1] == "--output":
        args = [*args, str(tmp_path / "out")]

    result = dod(service, tmp_path, *args, "--format", fmt)

    assert result.returncode in (1, 2)
    assert "bad" in result.stdout + result.stderr
    (assert_plain_json if fmt == "json" else assert_plain)(result)


def test_discover_masks_credentials_in_the_endpoint_the_wsdl_names(
    service: FakeService, other: FakeService, tmp_path: Path
) -> None:
    host = other.url.removeprefix("http://")
    service.wsdl_address = f"http://alice:hunter2@{host}?token=sekret"

    result = run_dod("discover", service.url, "--insecure")

    assert result.returncode == 0, result.stderr
    for secret in ("hunter2", "sekret"):
        assert secret not in result.stdout
        assert secret not in result.stderr
    assert "***[" in result.stdout


def test_discover_shows_no_control_characters_of_the_endpoint(
    service: FakeService, tmp_path: Path
) -> None:
    service.wsdl_address = f"{service.url}/x\x9b31m"

    result = run_dod("discover", service.url, "--insecure")

    assert result.returncode == 0, result.stderr
    assert "/x" in result.stdout
    assert_plain(result)
