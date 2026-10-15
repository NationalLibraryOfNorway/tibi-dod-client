"""`--debug`, `--save-exchanges`, `--format` and `--unmask` at the CLI boundary.

Subprocess tests run the installed console script against the fake Service;
terminal tests run the same app in-process with a fake `Terminal`. Users,
passwords and cookies are synthetic.
"""

import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dod.application import ConfigFile
from dod.infrastructure import HttpFetcher, HttpServicePort, parse_wsdl
from dod.presentation import create_app
from support import FakeService, run_dod

USER = "synthetic-user"
PASSWORD = "synthetic-secret"
ANSI = re.compile(r"\x1b\[[0-9;]*m")


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD)
    yield fake
    fake.stop()


def logon(service: FakeService, *extra: str):  # type: ignore[no-untyped-def]
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
        stdin=PASSWORD + "\n",
    )


def session_tokens(service: FakeService) -> set[str]:
    tokens: set[str] = set()
    for request in service.requests:
        cookie = request.headers.get("Cookie", "")
        tokens |= {part.partition("=")[2] for part in cookie.split("; ") if part}
    assert tokens, "the Service saw no cookie"
    return tokens


# -- --debug ---------------------------------------------------------------


def test_debug_writes_each_exchange_as_a_readable_block_on_stderr(
    service: FakeService,
) -> None:
    result = logon(service, "--debug")

    assert result.returncode == 0, result.stderr
    assert result.stderr.count("== exchange ") == 4
    assert f"POST {service.url}" in result.stderr
    assert "-- 200 in " in result.stderr
    assert "ms" in result.stderr
    # Pretty-printed SOAP: elements on their own, indented lines.
    assert re.search(r"^  <soap:Body>", result.stderr, re.MULTILINE)
    assert "<username>synthetic-user</username>" in result.stderr


def test_debug_never_shows_the_password_or_the_session_cookie(
    service: FakeService,
) -> None:
    result = logon(service, "--debug")

    assert PASSWORD not in result.stderr
    assert "<password>***[" in result.stderr
    assert "cookie: session=***[" in result.stderr.lower()
    for token in session_tokens(service):
        assert token not in result.stderr
        assert token not in result.stdout


def test_the_same_session_has_the_same_fingerprint_in_every_exchange(
    service: FakeService,
) -> None:
    result = logon(service, "--debug")

    prints = set(
        re.findall(r"[Cc]ookie: session=(\*\*\*\[[0-9a-f]{6}\])", result.stderr)
    )
    assert len(prints) == 1


def test_debug_does_not_change_stdout_or_the_exit_code(service: FakeService) -> None:
    plain = logon(service)
    debugged = logon(service, "--debug")

    assert debugged.stdout == plain.stdout
    assert debugged.returncode == plain.returncode


def test_debug_shows_an_exchange_the_service_never_answered_properly(
    service: FakeService,
) -> None:
    service.inject_redirect("logOn", "https://other.example.org/")

    result = logon(service, "--debug")

    assert result.returncode == 2
    assert "-- 307 in " in result.stderr


# -- --format --------------------------------------------------------------


def test_format_json_on_stdout_is_valid_json_despite_debug_and_observations(
    service: FakeService,
) -> None:
    result = logon(service, "--format", "json", "--debug")

    document = json.loads(result.stdout)
    assert document["succeeded"] is True
    assert next(step["operation"] for step in document["steps"]) == "logOn"
    assert "transport-security" in result.stderr
    assert "== exchange" in result.stderr


def test_format_xml_writes_the_raw_masked_responses_to_stdout(
    service: FakeService,
) -> None:
    result = logon(service, "--format", "xml")

    assert result.returncode == 0, result.stderr
    assert result.stdout.count("<logOnResponse") == 1
    assert "<logOnResult>true</logOnResult>" in result.stdout
    assert "logOn: ok" not in result.stdout
    for token in session_tokens(service):
        assert token not in result.stdout


# -- --save-exchanges ------------------------------------------------------


def test_save_exchanges_writes_a_masked_file_set_per_exchange(
    service: FakeService, tmp_path: Path
) -> None:
    target = tmp_path / "nested" / "exchanges"

    result = logon(service, "--save-exchanges", str(target))

    assert result.returncode == 0, result.stderr
    names = sorted(path.name for path in target.iterdir())
    assert names == [
        f"{number:03d}-{operation}.{suffix}"
        for number, operation in enumerate(
            ["logOn", "getServiceAttributes", "setReadingSystemAttributes", "logOff"],
            start=1,
        )
        for suffix in ("json", "request.xml", "response.xml")
    ]
    request = (target / "001-logOn.request.xml").read_text(encoding="utf-8")
    assert "<username>synthetic-user</username>" in request
    assert "<password>***[" in request
    summary = json.loads((target / "001-logOn.json").read_text(encoding="utf-8"))
    assert summary["status"] == 200
    assert summary["method"] == "POST"
    assert summary["duration_seconds"] >= 0
    assert any(name.lower() == "set-cookie" for name, _ in summary["response_headers"])


def test_no_secret_is_in_stderr_files_or_stdout(
    service: FakeService, tmp_path: Path
) -> None:
    result = logon(service, "--debug", "--save-exchanges", str(tmp_path))

    contents = result.stdout + result.stderr
    for path in tmp_path.iterdir():
        contents += path.read_text(encoding="utf-8")
    assert PASSWORD not in contents
    for token in session_tokens(service):
        assert token not in contents


def test_an_unusable_save_directory_exits_2_before_anything_is_sent(
    service: FakeService, tmp_path: Path
) -> None:
    occupied = tmp_path / "file"
    occupied.write_text("x", encoding="utf-8")

    result = logon(service, "--save-exchanges", str(occupied))

    assert result.returncode == 2
    assert service.requests == []


# -- unmasking (ADR 0007) --------------------------------------------------


@pytest.mark.parametrize("flag", ["--unmask", "--unmask-password"])
def test_unmask_is_refused_when_stderr_is_not_a_terminal(
    service: FakeService, flag: str
) -> None:
    result = logon(service, "--debug", flag)

    assert result.returncode == 2
    assert "terminal" in result.stderr
    assert service.requests == []
    assert PASSWORD not in result.stderr


def test_unmask_cannot_be_enabled_by_the_environment(service: FakeService) -> None:
    result = run_dod(
        "logon",
        "--no-session",
        "--url",
        service.url,
        "--username",
        USER,
        "--password-stdin",
        "--insecure",
        "--debug",
        stdin=PASSWORD + "\n",
        env={"DOD_UNMASK": "1", "DOD_UNMASK_PASSWORD": "1"},
    )

    assert result.returncode == 0, result.stderr
    assert PASSWORD not in result.stderr
    assert "<password>***[" in result.stderr


def test_unmask_is_refused_together_with_save_exchanges(
    service: FakeService, tmp_path: Path
) -> None:
    result = logon(service, "--debug", "--unmask", "--save-exchanges", str(tmp_path))

    assert result.returncode == 2
    assert "--save-exchanges" in result.stderr
    assert service.requests == []
    assert list(tmp_path.iterdir()) == []


class NoConfig:
    def default_path(self) -> str:
        return "unused.toml"

    def read(self, path: str) -> ConfigFile | None:
        return None


class FakeTerminal:
    def __init__(self, *, stderr: bool = True, stdin: bool = True) -> None:
        self._stderr = stderr
        self._stdin = stdin

    def stderr_is_tty(self) -> bool:
        return self._stderr

    def stdin_is_tty(self) -> bool:
        return self._stdin


def invoke(  # type: ignore[no-untyped-def]
    service: FakeService,
    *extra: str,
    terminal: FakeTerminal | None = None,
    input: str = "",
    env: dict[str, str | None] | None = None,
):
    app = create_app(
        HttpServicePort,
        NoConfig(),
        HttpFetcher(),
        parse_wsdl,
        terminal or FakeTerminal(),
    )
    return CliRunner(env={"NO_COLOR": None, **(env or {})}).invoke(
        app,
        [
            "logon",
            "--no-session",
            "--url",
            service.url,
            "--username",
            USER,
            "--insecure",
            "--debug",
            *extra,
        ],
        input=input,
    )


def test_unmask_shows_cookies_in_colour_and_warns_before_and_after(
    service: FakeService,
) -> None:
    result = invoke(service, "--unmask", input=PASSWORD + "\n")

    assert result.exit_code == 0, result.output
    tokens = session_tokens(service)
    assert any(f"\x1b[1;31m{token}\x1b[0m" in result.stderr for token in tokens)
    # The password stays masked with --unmask alone.
    assert "<password>***[" in result.stderr
    assert result.stderr.index("warning:") < result.stderr.index("== exchange 1")
    assert result.stderr.rindex("warning:") > result.stderr.rindex("== exchange 4")
    assert result.stdout.count("warning") == 0


def test_unmask_password_needs_confirmation_and_shows_only_the_password(
    service: FakeService,
) -> None:
    result = invoke(service, "--unmask-password", input="y\n" + PASSWORD + "\n")

    assert result.exit_code == 0, result.output
    # Colour instead of text markers: without the escapes it is valid XML.
    plain = ANSI.sub("", result.stderr)
    assert f"<password>{PASSWORD}</password>" in plain
    assert f"\x1b[1;31m{PASSWORD}\x1b[0m" in result.stderr
    assert "cookie: session=***[" in result.stderr.lower()


def test_unmask_password_without_confirmation_sends_nothing(
    service: FakeService,
) -> None:
    result = invoke(service, "--unmask-password", input="n\n")

    assert result.exit_code == 2
    assert service.requests == []
    assert PASSWORD not in result.stderr


def test_unmask_password_is_refused_when_stdin_is_not_a_terminal(
    service: FakeService,
) -> None:
    result = invoke(
        service, "--unmask-password", terminal=FakeTerminal(stdin=False), input="y\n"
    )

    assert result.exit_code == 2
    assert service.requests == []


def test_unmask_password_cannot_read_the_password_from_stdin(
    service: FakeService,
) -> None:
    result = invoke(service, "--unmask-password", "--password-stdin", input="y\n")

    assert result.exit_code == 2
    assert service.requests == []


def test_unmask_without_debug_is_a_usage_error(service: FakeService) -> None:
    app = create_app(
        HttpServicePort, NoConfig(), HttpFetcher(), parse_wsdl, FakeTerminal()
    )

    result = CliRunner().invoke(
        app, ["logon", "--no-session", "--url", service.url, "--unmask"]
    )

    assert result.exit_code == 2
    assert service.requests == []


def test_with_no_color_only_the_warning_remains(service: FakeService) -> None:
    result = invoke(service, "--unmask", input=PASSWORD + "\n", env={"NO_COLOR": "1"})

    assert result.exit_code == 0, result.output
    assert "\x1b" not in result.stderr
    assert "warning:" in result.stderr
    assert any(token in result.stderr for token in session_tokens(service))


# -- Observations ----------------------------------------------------------


def test_an_observation_is_written_once_per_run_on_stderr_only(
    service: FakeService,
) -> None:
    result = logon(service)

    assert result.returncode == 0, result.stderr
    assert result.stderr.count("observation transport-security:") == 1
    assert "observation" not in result.stdout


def test_a_session_cookie_without_httponly_gives_cookie_hardening(
    service: FakeService,
) -> None:
    service.cookie_attributes = "Path=/"

    result = logon(service)

    assert result.returncode == 0, result.stderr
    assert result.stderr.count("observation cookie-hardening:") == 1
    assert "HttpOnly" in result.stderr
    for token in session_tokens(service):
        assert token not in result.stderr


def test_a_hardened_cookie_gives_no_cookie_hardening(service: FakeService) -> None:
    result = logon(service)

    assert "cookie-hardening" not in result.stderr


def test_a_trusted_wsdl_naming_another_host_gives_host_boundary() -> None:
    first, second = FakeService(), FakeService()
    try:
        first.add_user(USER, PASSWORD)
        second.add_user(USER, PASSWORD)
        first.wsdl_address = second.url

        result = run_dod(
            "logon",
            "--no-session",
            "--wsdl",
            first.wsdl_url,
            "--username",
            USER,
            "--password-stdin",
            "--insecure",
            "--trust-host",
            stdin=PASSWORD + "\n",
        )
    finally:
        first.stop()
        second.stop()

    assert result.returncode == 0, result.stderr
    assert result.stderr.count("observation host-boundary:") == 1


def test_observations_do_not_change_the_exit_code(service: FakeService) -> None:
    service.cookie_attributes = "Path=/"

    assert logon(service).returncode == 0
