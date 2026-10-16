"""`dod test list` and `dod test run` through the CLI boundary.

Subprocess tests run the installed console script against the fake Service on
localhost, with `DOD_STATE_DIR` in a temporary directory. Users, books and
passwords are synthetic.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from dod.domain.v1 import ContentItem, ContentList, ContentMetadata
from support import FakeService, run_dod

USER = "synthetic-user"
PASSWORD = "synthetic-secret"
ITEMS = tuple(ContentItem(id=f"book{n}", label=f"Book {n}") for n in range(3))
BOOK = ContentMetadata(
    title="Book 0", identifier="book0", format="Daisy 2.02", size=1234
)
FAULTS_LINK = (
    "http://www.daisy.org/projects/daisy-online-delivery/drafts/20100402/"
    "do-spec-20100402.html#apiReferenceFaults"
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


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD)
    fake.offer_catalog([ContentList(id="issued", total_items=3, items=ITEMS)], [BOOK])
    yield fake
    fake.stop()


def dod(  # type: ignore[no-untyped-def]
    service: FakeService, state: Path, *args: str, password: str = PASSWORD
):
    return run_dod(
        *args,
        "--url",
        service.url,
        "--username",
        USER,
        "--password-stdin",
        "--insecure",
        stdin=password + "\n",
        env={"DOD_STATE_DIR": str(state)},
    )


def test_list_shows_every_test_id_one_per_line() -> None:
    result = run_dod("test", "list")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ALL_IDS


def test_list_as_json_gives_ids_and_whether_they_change_state() -> None:
    result = run_dod("test", "list", "--format", "json", "--only", "catalog.metadata")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "schema_version": 1,
        "tests": [
            {"id": "catalog.metadata.get", "state_changing": False},
            {"id": "catalog.metadata.unknown-id", "state_changing": False},
        ],
    }


def test_run_prints_one_line_per_test_and_exits_0_when_all_pass(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "test", "run")

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[: len(ALL_IDS)] == [f"PASS {name}" for name in ALL_IDS]
    assert "12 tests: 12 PASS, 0 FAIL, 0 SKIP, 0 ERROR" in lines


def test_run_never_reads_or_writes_a_stored_session(
    service: FakeService, tmp_path: Path
) -> None:
    dod(service, tmp_path, "test", "run")

    assert list(tmp_path.iterdir()) == []


def test_a_fail_names_the_specification_with_a_link_and_exits_1(
    service: FakeService, tmp_path: Path
) -> None:
    service.inject_http_500("getContentList")

    result = dod(service, tmp_path, "test", "run", "--only", "catalog.list.unknown-id")

    assert result.returncode == 1, result.stderr
    (line,) = [x for x in result.stdout.splitlines() if x.startswith("FAIL")]
    assert line.startswith("FAIL catalog.list.unknown-id: ")
    assert "5.3 Faults" in line
    assert FAULTS_LINK in line


def test_an_error_exits_2_even_when_something_failed_too(
    service: FakeService, tmp_path: Path
) -> None:
    service.inject_no_answer("getContentMetadata")
    service.inject_deviation("getContentList")

    result = dod(service, tmp_path, "test", "run", "--only", "catalog")

    assert result.returncode == 2, result.stderr
    assert "ERROR catalog.metadata.get: " in result.stdout
    assert "FAIL catalog.list.issued: " in result.stdout


def test_a_skip_gives_the_reason_and_does_not_change_the_exit_code(
    service: FakeService, tmp_path: Path
) -> None:
    service.offer_catalog([], [])

    result = dod(service, tmp_path, "test", "run", "--only", "catalog.metadata.get")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0].startswith("SKIP catalog.metadata.get: ")


def test_only_and_skip_pick_tests_by_id_prefix(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(
        service,
        tmp_path,
        "test",
        "run",
        "--only",
        "session",
        "--only",
        "attributes",
        "--skip",
        "session.logon",
    )

    assert result.returncode == 0, result.stderr
    names = [x.split()[1] for x in result.stdout.splitlines() if x[:4] == "PASS"]
    assert names == [
        "session.logoff.invalidates-session",
        "session.call.without-session",
        "attributes.service.get",
        "attributes.reading-system.set",
    ]


def test_a_prefix_that_matches_nothing_is_a_usage_error(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "test", "run", "--only", "nope")

    assert result.returncode == 2
    assert "no test id starts with nope" in result.stderr
    assert service.requests == []


def test_a_failed_logon_in_the_setup_is_an_error_that_ends_the_run(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "test", "run", password="not-the-password")

    assert result.returncode == 2
    assert result.stdout.splitlines()[0].startswith("ERROR setup: ")
    assert "logOn" in result.stdout
    assert [r.operation for r in service.requests] == ["logOn"]


def test_the_json_report_has_a_schema_version_and_exchange_ids(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(
        service, tmp_path, "test", "run", "--format", "json", "--only", "attributes"
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["schema_version"] == 1
    assert report["exit_code"] == 0
    assert report["summary"] == {"PASS": 2, "FAIL": 0, "SKIP": 0, "ERROR": 0}
    assert report["setup"] is None
    assert [r["id"] for r in report["results"]] == [
        "attributes.service.get",
        "attributes.reading-system.set",
    ]
    first = report["results"][0]
    assert first["outcome"] == "PASS"
    assert first["spec_ref"] is None
    assert len(first["exchanges"]) == 1


def test_failures_carry_their_spec_reference_and_masked_exchanges(
    service: FakeService, tmp_path: Path
) -> None:
    service.inject_http_500("getContentList")

    result = dod(
        service,
        tmp_path,
        "test",
        "run",
        "--format",
        "json",
        "--only",
        "catalog.list.unknown-id",
        "--only",
        "attributes.service.get",
    )

    report = json.loads(result.stdout)
    by_id = {r["id"]: r for r in report["results"]}
    failed = by_id["catalog.list.unknown-id"]
    assert failed["outcome"] == "FAIL"
    assert by_id["attributes.service.get"]["outcome"] == "PASS"
    assert failed["spec_ref"] == {
        "section": "5.3",
        "title": "Faults",
        "anchor": "apiReferenceFaults",
        "rule": None,
        "url": FAULTS_LINK,
    }
    # The default is failures only; the passing test's Exchange is left out.
    assert set(report["exchanges"]) == set(failed["exchanges"])
    (identifier,) = failed["exchanges"]
    exchange = report["exchanges"][identifier]
    assert exchange["status"] == 500
    assert "getContentList" in exchange["request_body"]


def exchange_count(service: FakeService, state: Path, mode: str) -> int:
    service.inject_http_500("getContentList")
    result = dod(
        service,
        state,
        "test",
        "run",
        "--format",
        "json",
        "--report-exchanges",
        mode,
        "--only",
        "catalog.list.unknown-id",
        "--only",
        "catalog.metadata.unknown-id",
    )
    report = json.loads(result.stdout)
    assert all(r["exchanges"] for r in report["results"])
    return len(report["exchanges"])


def test_report_exchanges_chooses_which_exchanges_are_included(
    service: FakeService, tmp_path: Path
) -> None:
    everything = exchange_count(service, tmp_path, "all")
    failures = exchange_count(service, tmp_path, "failures")
    nothing = exchange_count(service, tmp_path, "none")

    # The setup's three calls, the two tests' calls and the final logOff.
    assert everything == 6
    # Only the one failing test's call.
    assert failures == 1
    assert nothing == 0


def test_exchanges_in_the_report_are_masked(
    service: FakeService, tmp_path: Path
) -> None:
    service.inject_deviation("logOn")
    service.defer_injection("logOn", 1)

    result = dod(
        service,
        tmp_path,
        "test",
        "run",
        "--format",
        "json",
        "--report-exchanges",
        "all",
        "--only",
        "session.logon.valid-credentials",
    )

    assert json.loads(result.stdout)["results"][0]["outcome"] == "FAIL"
    assert PASSWORD not in result.stdout
    assert "***[" in result.stdout
    assert "session=" not in result.stdout.replace("session=***", "")


def test_observations_have_a_section_of_their_own_and_do_not_affect_the_exit_code(
    service: FakeService, tmp_path: Path
) -> None:
    text = dod(service, tmp_path, "test", "run", "--only", "attributes.service.get")
    document = dod(
        service,
        tmp_path,
        "test",
        "run",
        "--format",
        "json",
        "--only",
        "attributes.service.get",
    )

    assert text.returncode == 0
    lines = text.stdout.splitlines()
    assert "Observations" in lines
    assert any(x.startswith("  transport-security: ") for x in lines)
    report = json.loads(document.stdout)
    assert [o["id"] for o in report["observations"]] == ["transport-security"]


def test_control_characters_from_the_service_never_reach_the_terminal(
    service: FakeService, tmp_path: Path
) -> None:
    service.inject_fault("getContentList", "internalServerError", "bad\x9b31mred")

    result = dod(service, tmp_path, "test", "run", "--only", "catalog.list.issued")

    assert "\x9b" not in result.stdout


def test_xml_output_is_refused(service: FakeService, tmp_path: Path) -> None:
    result = dod(service, tmp_path, "test", "run", "--format", "xml")

    assert result.returncode == 2
    assert "no xml output" in result.stderr


def write_config(path: Path, service: FakeService, *, protected: bool) -> Path:
    file = path / "config.toml"
    file.write_text(
        "[environments.test]\n"
        f'url = "{service.url}"\n'
        f'username = "{USER}"\n'
        "insecure = true\n"
        f"protected = {str(protected).lower()}\n",
        encoding="utf-8",
    )
    return file


def run_in_env(path: Path, config: Path, *args: str):  # type: ignore[no-untyped-def]
    return run_dod(
        "--config",
        str(config),
        "--env",
        "test",
        "--password-stdin",
        *args,
        stdin=PASSWORD + "\n",
        env={"DOD_STATE_DIR": str(path)},
    )


def test_state_changing_tests_in_a_protected_environment_need_confirm_env(
    service: FakeService, tmp_path: Path
) -> None:
    config = write_config(tmp_path, service, protected=True)

    refused = run_in_env(
        tmp_path, config, "test", "run", "--state-changing", "--only", "session"
    )
    wrong = run_in_env(
        tmp_path,
        config,
        "test",
        "run",
        "--state-changing",
        "--confirm-env",
        "prod",
        "--only",
        "session",
    )
    sent_when_refused = len(service.requests)
    confirmed = run_in_env(
        tmp_path,
        config,
        "test",
        "run",
        "--state-changing",
        "--confirm-env",
        "test",
        "--only",
        "session",
    )

    assert (refused.returncode, wrong.returncode) == (2, 2)
    assert "--confirm-env test" in refused.stderr
    assert sent_when_refused == 0
    assert confirmed.returncode == 0, confirmed.stderr


def test_a_protected_environment_runs_ordinary_tests_without_confirmation(
    service: FakeService, tmp_path: Path
) -> None:
    config = write_config(tmp_path, service, protected=True)

    result = run_in_env(tmp_path, config, "test", "run", "--only", "session")

    assert result.returncode == 0, result.stderr


def test_help_lists_the_run_options() -> None:
    result = run_dod("test", "run", "--help")

    assert result.returncode == 0
    for option in (
        "--only",
        "--skip",
        "--state-changing",
        "--confirm-env",
        "--report-exchanges",
    ):
        assert option in result.stdout
