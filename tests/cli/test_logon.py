"""`dod logon --no-session` through the CLI boundary (ADR 0003).

Subprocess tests run the installed console script against the fake Service on
localhost; prompt tests run the same app in-process against the in-memory
adapter. Users and passwords are synthetic.
"""

from collections.abc import Iterator

import pytest
from typer.testing import CliRunner

from dod.application import ConfigFile
from dod.infrastructure import HttpFetcher, InMemoryService, parse_wsdl
from dod.presentation import create_app
from support import FakeService, run_dod

USER = "synthetic-user"
PASSWORD = "synthetic-secret"


class NoConfig:
    def default_path(self) -> str:
        return "unused.toml"

    def read(self, path: str) -> ConfigFile | None:
        return None


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD)
    yield fake
    fake.stop()


def logon(service: FakeService, *extra: str, password: str = PASSWORD):  # type: ignore[no-untyped-def]
    return run_dod(
        "logon",
        "--no-session",
        "--url",
        service.url,
        "--username",
        USER,
        "--password-stdin",
        "--insecure",
        *extra,
        stdin=password + "\n",
    )


def operations(service: FakeService) -> list[str | None]:
    return [request.operation for request in service.requests]


def test_logon_runs_the_initialisation_sequence_and_logs_off(
    service: FakeService,
) -> None:
    result = logon(service)

    assert result.returncode == 0, result.stderr
    assert operations(service) == [
        "logOn",
        "getServiceAttributes",
        "setReadingSystemAttributes",
        "logOff",
    ]
    assert service.sessions == set()
    assert result.stdout.splitlines() == [
        "logOn: ok",
        "getServiceAttributes: ok",
        "setReadingSystemAttributes: ok",
        "logOff: ok",
    ]


def test_http_gives_a_transport_security_observation_on_stderr_only(
    service: FakeService,
) -> None:
    result = logon(service)

    assert "transport-security" in result.stderr
    assert "transport-security" not in result.stdout


def test_the_password_never_appears_in_the_output(service: FakeService) -> None:
    result = logon(service)

    assert PASSWORD not in result.stdout
    assert PASSWORD not in result.stderr


def test_http_without_insecure_is_refused_before_anything_is_sent(
    service: FakeService,
) -> None:
    result = run_dod(
        "logon",
        "--no-session",
        "--url",
        service.url,
        "--username",
        USER,
        "--password-stdin",
        stdin=PASSWORD + "\n",
    )

    assert result.returncode == 2
    assert "--insecure" in result.stderr
    assert service.requests == []


def test_a_wrong_password_exits_1_and_does_not_continue(service: FakeService) -> None:
    result = logon(service, password="wrong")

    assert result.returncode == 1
    assert "logOn: failed" in result.stdout
    assert operations(service) == ["logOn"]


def test_a_fault_exits_1_but_the_session_is_still_logged_off(
    service: FakeService,
) -> None:
    service.inject_fault("setReadingSystemAttributes", "invalidParameter", "bad")

    result = logon(service)

    assert result.returncode == 1
    assert "setReadingSystemAttributes: fault invalidParameter: bad" in result.stdout
    assert operations(service)[-1] == "logOff"
    assert service.sessions == set()


def test_an_answer_contrary_to_the_specification_exits_1(
    service: FakeService,
) -> None:
    service.inject_deviation("logOn")

    result = logon(service)

    assert result.returncode == 1
    assert "logOn: deviation" in result.stdout
    assert "5.1.1" in result.stderr


def test_no_answer_from_the_service_exits_2() -> None:
    result = run_dod(
        "logon",
        "--no-session",
        "--url",
        "http://127.0.0.1:9/dodp",
        "--username",
        USER,
        "--password-stdin",
        "--insecure",
        stdin=PASSWORD + "\n",
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr != ""


def test_session_mode_is_not_available_yet_and_exits_2(service: FakeService) -> None:
    result = run_dod(
        "logon",
        "--url",
        service.url,
        "--username",
        USER,
        "--insecure",
        "--password-stdin",
        stdin=PASSWORD + "\n",
    )

    assert result.returncode == 2
    assert "--no-session" in result.stderr
    assert service.requests == []


def test_an_empty_password_on_stdin_is_a_usage_error(service: FakeService) -> None:
    result = logon(service, password="")

    assert result.returncode == 2
    assert service.requests == []


def test_the_password_prompt_does_not_echo_the_password() -> None:
    memory = InMemoryService()
    memory.add_user(USER, PASSWORD)
    app = create_app(
        lambda url: memory.open_port(), NoConfig(), HttpFetcher(), parse_wsdl
    )

    result = CliRunner().invoke(
        app,
        [
            "logon",
            "--no-session",
            "--url",
            "https://dod.example.org/service",
            "--username",
            USER,
        ],
        input=PASSWORD + "\n",
    )

    assert result.exit_code == 0, result.output
    assert "Password" in result.output
    assert PASSWORD not in result.output


def test_logon_help_points_to_the_global_options() -> None:
    result = run_dod("logon", "--help")

    assert result.returncode == 0
    assert "dod --help" in result.stdout
    assert "--no-session" in run_dod("--help").stdout


def test_logon_is_listed_under_session_and_setup() -> None:
    result = run_dod("--help")

    assert "logon" in result.stdout
