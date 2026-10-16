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
NEGATIVE_IDS = [
    "negative.session.no-session",
    "negative.init.operation-before-init",
    "negative.operation.unknown",
    "negative.parameter.content-list-non-numeric-range",
    "negative.parameter.content-list-empty-id",
    "negative.parameter.content-metadata-empty-id",
]


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD)
    fake.enforce_initialisation = True
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
    assert result.stdout.splitlines() == ALL_IDS + NEGATIVE_IDS


def test_list_as_json_gives_ids_and_whether_they_change_state() -> None:
    result = run_dod("test", "list", "--format", "json", "--only", "catalog.metadata")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "schema_version": 3,
        "tests": [
            {"id": "catalog.metadata.get", "state_changing": False, "explicit": False},
            {
                "id": "catalog.metadata.unknown-id",
                "state_changing": False,
                "explicit": False,
            },
        ],
    }


def test_list_as_json_marks_the_negative_tests_as_explicit() -> None:
    result = run_dod("test", "list", "--format", "json", "--only", "negative")

    assert result.returncode == 0, result.stderr
    tests = json.loads(result.stdout)["tests"]
    assert [t["id"] for t in tests] == NEGATIVE_IDS
    assert all(t["explicit"] for t in tests)


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
    assert report["schema_version"] == 3
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


def test_a_run_without_only_leaves_the_negative_tests_out(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "test", "run")

    assert result.returncode == 0, result.stderr
    assert "negative" not in result.stdout
    assert "dodConformanceUnknownOperation" not in [
        r.operation for r in service.requests
    ]


def test_only_negative_runs_the_family_and_exits_0_against_a_conforming_service(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "test", "run", "--only", "negative")

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[: len(NEGATIVE_IDS)] == [f"PASS {name}" for name in NEGATIVE_IDS]
    assert "6 tests: 6 PASS, 0 FAIL, 0 SKIP, 0 ERROR" in lines
    assert "dodConformanceUnknownOperation" in [r.operation for r in service.requests]
    assert service.sessions == set()


def test_the_negative_tests_never_touch_a_stored_session(
    service: FakeService, tmp_path: Path
) -> None:
    dod(service, tmp_path, "test", "run", "--only", "negative")

    assert list(tmp_path.iterdir()) == []


def test_a_cleanup_that_goes_wrong_is_an_error_line_of_its_own_and_exit_2(
    service: FakeService, tmp_path: Path
) -> None:
    service.inject_fault("logOff", "internalServerError", "synthetic")

    result = dod(
        service,
        tmp_path,
        "test",
        "run",
        "--only",
        "negative.parameter.content-list-empty-id",
    )

    assert result.returncode == 2, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "PASS negative.parameter.content-list-empty-id"
    assert lines[1].startswith(
        "ERROR negative.parameter.content-list-empty-id.cleanup: "
    )
    assert not any(line.startswith("FAIL") for line in lines)


def test_the_raw_exchanges_are_in_the_json_report_with_the_password_masked(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(
        service,
        tmp_path,
        "test",
        "run",
        "--only",
        "negative.operation.unknown",
        "--format",
        "json",
        "--report-exchanges",
        "all",
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    bodies = [e["request_body"] for e in report["exchanges"].values()]
    assert any("dodConformanceUnknownOperation" in body for body in bodies)
    assert PASSWORD not in result.stdout


FAILING = "catalog.list.issued"


def baseline_file(tmp_path: Path, *ids: str) -> Path:
    path = tmp_path / "baseline.toml"
    path.write_text(
        "".join(f'[[known]]\nid = "{i}"\nreason = "synthetic reason"\n\n' for i in ids),
        encoding="utf-8",
    )
    return path


def test_write_baseline_lists_the_failing_ids_with_a_reason_and_nothing_else(
    service: FakeService, tmp_path: Path
) -> None:
    service.inject_http_500("getContentList")
    target = tmp_path / "out" / "baseline.toml"
    target.parent.mkdir()

    result = dod(service, tmp_path, "test", "run", "--write-baseline", str(target))

    assert result.returncode == 1, result.stderr
    written = target.read_text(encoding="utf-8")
    assert f'id = "{FAILING}"' in written
    assert 'reason = "DODP 5.3 Faults"' in written
    assert "PASS" not in written
    assert service.url not in written
    assert "127.0.0.1" not in written and "localhost" not in written
    assert PASSWORD not in written and USER not in written


def test_a_written_baseline_makes_the_same_run_exit_0(
    service: FakeService, tmp_path: Path
) -> None:
    service.inject_http_500("getContentList")
    target = tmp_path / "baseline.toml"
    dod(service, tmp_path, "test", "run", "--write-baseline", str(target))
    service.inject_http_500("getContentList")

    result = dod(service, tmp_path, "test", "run", "--baseline", str(target))

    assert result.returncode == 0, result.stderr
    assert f"FAIL {FAILING}: " in result.stdout
    assert "Baseline: 0 new, 0 resolved, 1 known" in result.stdout


def test_a_fail_that_is_not_in_the_baseline_is_new_and_exits_1(
    service: FakeService, tmp_path: Path
) -> None:
    service.inject_http_500("getContentList")
    baseline = baseline_file(tmp_path, "catalog.metadata.unknown-id")

    result = dod(service, tmp_path, "test", "run", "--baseline", str(baseline))

    assert result.returncode == 1, result.stderr
    assert f"NEW {FAILING}" in result.stdout


def test_a_baseline_entry_that_passes_is_resolved_and_only_fails_the_run_on_request(
    service: FakeService, tmp_path: Path
) -> None:
    baseline = baseline_file(tmp_path, FAILING)

    plain = dod(service, tmp_path, "test", "run", "--baseline", str(baseline))
    strict = dod(
        service,
        tmp_path,
        "test",
        "run",
        "--baseline",
        str(baseline),
        "--fail-on-resolved",
    )

    assert plain.returncode == 0, plain.stderr
    assert f"RESOLVED {FAILING}" in plain.stdout
    assert strict.returncode == 1, strict.stderr


def test_an_entry_for_a_test_that_did_not_run_is_neither_new_nor_resolved(
    service: FakeService, tmp_path: Path
) -> None:
    baseline = baseline_file(tmp_path, FAILING)

    result = dod(
        service,
        tmp_path,
        "test",
        "run",
        "--only",
        "attributes",
        "--baseline",
        str(baseline),
        "--fail-on-resolved",
    )

    assert result.returncode == 0, result.stderr
    assert "Baseline: 0 new, 0 resolved, 0 known" in result.stdout


def test_an_error_gives_exit_2_whatever_the_baseline_says(
    service: FakeService, tmp_path: Path
) -> None:
    service.inject_no_answer("getContentMetadata")
    baseline = baseline_file(tmp_path, "catalog.metadata.get")

    result = dod(
        service,
        tmp_path,
        "test",
        "run",
        "--only",
        "catalog",
        "--baseline",
        str(baseline),
    )

    assert result.returncode == 2, result.stderr


def test_the_json_report_has_a_baseline_section_and_keeps_the_outcomes(
    service: FakeService, tmp_path: Path
) -> None:
    service.inject_http_500("getContentList")
    service.inject_deviation("getContentMetadata")
    baseline = baseline_file(tmp_path, FAILING, "session.logon.wrong-password")

    result = dod(
        service,
        tmp_path,
        "test",
        "run",
        "--format",
        "json",
        "--only",
        "catalog",
        "--only",
        "session.logon",
        "--baseline",
        str(baseline),
    )

    report = json.loads(result.stdout)
    assert report["schema_version"] == 3
    assert report["exit_code"] == result.returncode
    outcomes = {r["id"]: r["outcome"] for r in report["results"]}
    assert outcomes[FAILING] == "FAIL"
    assert report["baseline"] == {
        "new": ["catalog.metadata.get"],
        "resolved": ["session.logon.wrong-password"],
        "known": [FAILING],
    }


def test_the_json_report_has_no_baseline_without_one(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(
        service, tmp_path, "test", "run", "--format", "json", "--only", "attributes"
    )

    assert json.loads(result.stdout)["baseline"] is None


def test_a_missing_or_malformed_baseline_is_a_usage_error_before_anything_is_sent(
    service: FakeService, tmp_path: Path
) -> None:
    broken = tmp_path / "broken.toml"
    broken.write_text("[[known]]\nid = 7\n", encoding="utf-8")

    missing = dod(service, tmp_path, "test", "run", "--baseline", str(tmp_path / "no"))
    malformed = dod(service, tmp_path, "test", "run", "--baseline", str(broken))

    assert missing.returncode == 2 and "cannot be read" in missing.stderr
    assert malformed.returncode == 2 and "baseline" in malformed.stderr
    assert service.requests == []


def test_a_baseline_cannot_be_used_in_a_run_with_a_setup_error_silently(
    service: FakeService, tmp_path: Path
) -> None:
    target = tmp_path / "baseline.toml"

    result = dod(
        service,
        tmp_path,
        "test",
        "run",
        "--write-baseline",
        str(target),
        password="not-the-password",
    )

    assert result.returncode == 2
    assert not target.exists()


def test_help_lists_the_baseline_options() -> None:
    result = run_dod("test", "run", "--help")

    for option in ("--baseline", "--write-baseline", "--fail-on-resolved"):
        assert option in result.stdout


def test_rewriting_a_baseline_keeps_the_reasons_of_entries_that_still_fail(
    service: FakeService, tmp_path: Path
) -> None:
    service.inject_http_500("getContentList")
    baseline = baseline_file(tmp_path, FAILING, "session.logon.wrong-password")
    rewritten = tmp_path / "next.toml"

    dod(
        service,
        tmp_path,
        "test",
        "run",
        "--baseline",
        str(baseline),
        "--write-baseline",
        str(rewritten),
    )

    text = rewritten.read_text(encoding="utf-8")
    assert f'id = "{FAILING}"\nreason = "synthetic reason"' in text
    assert "wrong-password" not in text
