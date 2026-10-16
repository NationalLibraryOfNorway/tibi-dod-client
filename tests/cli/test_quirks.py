"""`dod quirks list`, quirks in Environments and `--with-quirks` (ADR 0010).

Subprocess tests run the installed console script against the fake Service on
localhost and a configuration file in a scratch directory. Users, books and
passwords are synthetic.
"""

import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from dod.domain.v1 import ContentItem, ContentList, ContentMetadata
from support import PASSWORD, FakeService, run_dod

USER = "synthetic-user"
NAME = "http-500-without-fault-as-invalid-operation"
REF_URL = (
    "http://www.daisy.org/projects/daisy-online-delivery/drafts/20100402/"
    "do-spec-20100402.html#ft_invalidOperationFault"
)


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD)
    fake.enforce_initialisation = True
    fake.offer_catalog(
        [ContentList(id="issued", total_items=1, items=(ContentItem("b0", "B"),))],
        [ContentMetadata(title="B", identifier="b0", format="Daisy 2.02", size=1)],
    )
    yield fake
    fake.stop()


def config(tmp_path: Path, service: FakeService, extra: str = "") -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        f"""
[environments.tolerant]
url = "{service.url}"
insecure = true
username = "{USER}"
quirks = ["{NAME}"]

[environments.strict]
url = "{service.url}"
insecure = true
username = "{USER}"
{extra}
""",
        encoding="utf-8",
    )
    if sys.platform != "win32":
        path.chmod(0o600)
    return path


def dod(  # type: ignore[no-untyped-def]
    tmp_path: Path, service: FakeService, *args: str, extra: str = ""
):
    return run_dod(
        "--config",
        str(config(tmp_path, service, extra)),
        *args,
        "--password-stdin",
        stdin=PASSWORD + "\n",
        env={"DOD_STATE_DIR": str(tmp_path / "state")},
    )


# -- dod quirks list -------------------------------------------------------


def test_list_shows_name_description_reference_and_enabling_environments(
    tmp_path: Path, service: FakeService
) -> None:
    result = dod(tmp_path, service, "quirks", "list")

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == NAME
    assert "invalidOperation" in lines[1]
    assert lines[2].strip() == f"Spec: DODP 5.3.4 The invalidOperation Fault: {REF_URL}"
    assert lines[3].strip() == "Enabled in: tolerant"


def test_list_says_when_no_environment_enables_a_quirk(tmp_path: Path) -> None:
    result = run_dod("--config", str(tmp_path / "none.toml"), "quirks", "list")

    assert result.returncode == 2
    empty = tmp_path / "empty.toml"
    empty.write_text("", encoding="utf-8")
    result = run_dod("--config", str(empty), "quirks", "list")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == NAME
    assert "Enabled in: none" in result.stdout


def test_list_with_env_shows_only_the_quirks_that_environment_enables(
    tmp_path: Path, service: FakeService
) -> None:
    on = dod(tmp_path, service, "quirks", "list", "--env", "tolerant")
    off = dod(tmp_path, service, "quirks", "list", "--env", "strict")

    assert on.stdout.splitlines()[0] == NAME
    assert off.returncode == 0, off.stderr
    assert off.stdout == ""


def test_list_with_an_unknown_environment_is_exit_2(
    tmp_path: Path, service: FakeService
) -> None:
    result = dod(tmp_path, service, "quirks", "list", "--env", "gone")

    assert result.returncode == 2
    assert "gone" in result.stderr


def test_list_follows_dod_env_like_other_commands(
    tmp_path: Path, service: FakeService
) -> None:
    path = config(tmp_path, service)
    on = run_dod("--config", str(path), "quirks", "list", env={"DOD_ENV": "tolerant"})
    off = run_dod("--config", str(path), "quirks", "list", env={"DOD_ENV": "strict"})
    flag_wins = run_dod(
        "--config",
        str(path),
        "quirks",
        "list",
        "--env",
        "strict",
        env={"DOD_ENV": "tolerant"},
    )

    assert on.stdout.splitlines()[0] == NAME
    assert off.returncode == 0, off.stderr
    assert off.stdout == ""
    assert flag_wins.stdout == ""


def test_list_follows_default_environment(tmp_path: Path, service: FakeService) -> None:
    path = config(tmp_path, service)
    path.write_text(
        'default_environment = "strict"\n' + path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    result = run_dod("--config", str(path), "quirks", "list")

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_list_with_an_unknown_dod_env_is_exit_2(
    tmp_path: Path, service: FakeService
) -> None:
    result = run_dod(
        "--config",
        str(config(tmp_path, service)),
        "quirks",
        "list",
        env={"DOD_ENV": "gone"},
    )

    assert result.returncode == 2
    assert "gone" in result.stderr


def test_list_as_json(tmp_path: Path, service: FakeService) -> None:
    result = dod(tmp_path, service, "quirks", "list", "--format", "json")

    assert result.returncode == 0, result.stderr
    (quirk,) = json.loads(result.stdout)["quirks"]
    assert quirk["name"] == NAME
    assert quirk["description"]
    assert quirk["spec_reference"]["section"] == "5.3.4"
    assert quirk["spec_reference"]["url"] == REF_URL
    assert quirk["environments"] == ["tolerant"]


def test_list_refuses_xml(tmp_path: Path, service: FakeService) -> None:
    result = dod(tmp_path, service, "quirks", "list", "--format", "xml")

    assert result.returncode == 2


def test_an_unknown_quirk_name_in_the_file_is_refused_by_every_command(
    tmp_path: Path, service: FakeService
) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text(
        f'[environments.x]\nurl = "{service.url}"\nquirks = ["made-up"]\n',
        encoding="utf-8",
    )

    for args in (("quirks", "list"), ("config", "check"), ("list", "--env", "x")):
        result = run_dod("--config", str(bad), *args)
        assert result.returncode == 2, args
        assert "environments.x.quirks" in result.stderr
        assert "made-up" in result.stderr


# -- using a quirk ---------------------------------------------------------


def test_a_data_command_uses_the_environments_quirks_and_says_so(
    tmp_path: Path, service: FakeService
) -> None:
    service.inject_http_500("getContentList")

    result = dod(tmp_path, service, "list", "--env", "tolerant")

    assert result.returncode == 1
    assert "invalidOperation" in result.stdout
    assert f"observation interoperability: Quirk {NAME}" in result.stderr


def test_without_the_quirk_the_same_answer_is_a_deviation(
    tmp_path: Path, service: FakeService
) -> None:
    service.inject_http_500("getContentList")

    result = dod(tmp_path, service, "list", "--env", "strict")

    assert result.returncode == 1
    assert "interoperability" not in result.stderr
    assert "invalidOperation" not in result.stdout


# -- conformance runs ------------------------------------------------------

TEST_ID = "catalog.list.unknown-id"


def test_a_conformance_run_ignores_quirks_unless_with_quirks_is_given(
    tmp_path: Path, service: FakeService
) -> None:
    service.inject_http_500("getContentList")

    result = dod(
        tmp_path, service, "test", "run", "--only", TEST_ID, "--env", "tolerant"
    )

    assert result.returncode == 1
    assert "interoperability" not in result.stdout
    assert "Quirks on" not in result.stdout
    assert "a SOAP fault without a recognisable DODP fault element" in result.stdout


def test_with_quirks_the_run_applies_them_and_the_report_says_so(
    tmp_path: Path, service: FakeService
) -> None:
    service.inject_http_500("getContentList")

    result = dod(
        tmp_path,
        service,
        "test",
        "run",
        "--only",
        TEST_ID,
        "--env",
        "tolerant",
        "--with-quirks",
    )

    assert f"Quirks on: {NAME}" in result.stdout.splitlines()
    assert f"interoperability: Quirk {NAME}" in result.stdout


def test_the_json_report_lists_the_quirks_that_were_on(
    tmp_path: Path, service: FakeService
) -> None:
    on = dod(
        tmp_path,
        service,
        "test",
        "run",
        "--only",
        "session.logon",
        "--env",
        "tolerant",
        "--with-quirks",
        "--format",
        "json",
    )
    off = dod(
        tmp_path,
        service,
        "test",
        "run",
        "--only",
        "session.logon",
        "--env",
        "tolerant",
        "--format",
        "json",
    )

    assert json.loads(on.stdout)["schema_version"] == 4
    assert json.loads(on.stdout)["quirks"] == [NAME]
    assert json.loads(off.stdout)["quirks"] == []
