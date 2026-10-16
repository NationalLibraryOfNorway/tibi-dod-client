"""Stored Sessions through the CLI boundary (ADR 0001, ADR 0003, ADR 0005).

Subprocess tests run the installed console script against the fake Service on
localhost, with `DOD_STATE_DIR` pointing into a temporary directory. Users,
passwords and cookies are synthetic.
"""

import json
import stat
import subprocess
import sys
import textwrap
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from support import PASSWORD, FakeService, run_dod

USER = "synthetic-user"
INIT = ["logOn", "getServiceAttributes", "setReadingSystemAttributes"]


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD)
    yield fake
    fake.stop()


def dod(  # type: ignore[no-untyped-def]
    service: FakeService,
    state: Path,
    *args: str,
    password: str = PASSWORD,
    env: dict[str, str] | None = None,
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
        env={"DOD_STATE_DIR": str(state)} | (env or {}),
    )


def operations(service: FakeService) -> list[str | None]:
    return [request.operation for request in service.requests]


def session_files(state: Path) -> list[Path]:
    return sorted(state.rglob("*.json"))


def test_logon_stores_the_session_and_does_not_log_off(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "logon")

    assert result.returncode == 0, result.stderr
    assert operations(service) == INIT
    assert result.stdout.splitlines() == [
        "logOn: ok",
        "getServiceAttributes: ok",
        "setReadingSystemAttributes: ok",
    ]
    assert len(service.sessions) == 1
    assert len(session_files(tmp_path)) == 1


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_the_session_file_is_private(service: FakeService, tmp_path: Path) -> None:
    dod(service, tmp_path, "logon")

    (file,) = session_files(tmp_path)
    assert stat.S_IMODE(file.stat().st_mode) == 0o600
    assert stat.S_IMODE(file.parent.stat().st_mode) == 0o700


def test_the_session_file_never_holds_the_password(
    service: FakeService, tmp_path: Path
) -> None:
    dod(service, tmp_path, "logon")

    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert PASSWORD not in path.read_text(encoding="utf-8")


def test_a_second_logon_ends_the_old_session_first(
    service: FakeService, tmp_path: Path
) -> None:
    dod(service, tmp_path, "logon")
    service.requests.clear()

    result = dod(service, tmp_path, "logon")

    assert result.returncode == 0, result.stderr
    assert operations(service) == ["logOff", *INIT]
    assert len(service.sessions) == 1


def test_a_wrong_password_exits_1_and_stores_nothing(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "logon", password="wrong")

    assert result.returncode == 1
    assert "logOn: failed" in result.stdout
    assert session_files(tmp_path) == []


def test_a_failing_set_reading_system_attributes_logs_off_and_stores_nothing(
    service: FakeService, tmp_path: Path
) -> None:
    service.inject_fault("setReadingSystemAttributes", "invalidParameter", "bad")

    result = dod(service, tmp_path, "logon")

    assert result.returncode == 1
    assert operations(service) == [*INIT, "logOff"]
    assert service.sessions == set()
    assert session_files(tmp_path) == []


def test_no_session_flag_keeps_ephemeral_mode_and_stores_nothing(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "logon", "--no-session")

    assert result.returncode == 0, result.stderr
    assert operations(service) == [*INIT, "logOff"]
    assert session_files(tmp_path) == []


def test_dod_no_session_selects_ephemeral_mode(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "logon", env={"DOD_NO_SESSION": "1"})

    assert result.returncode == 0, result.stderr
    assert operations(service)[-1] == "logOff"
    assert session_files(tmp_path) == []


def test_logoff_ends_the_session_and_deletes_the_file(
    service: FakeService, tmp_path: Path
) -> None:
    dod(service, tmp_path, "logon")
    service.requests.clear()

    result = dod(service, tmp_path, "logoff")

    assert result.returncode == 0, result.stderr
    assert operations(service) == ["logOff"]
    assert service.sessions == set()
    assert session_files(tmp_path) == []


def test_logoff_deletes_the_file_and_warns_when_the_service_fails(
    service: FakeService, tmp_path: Path
) -> None:
    dod(service, tmp_path, "logon")
    service.inject_fault("logOff", "internalServerError", "boom")

    result = dod(service, tmp_path, "logoff")

    assert result.returncode == 0
    assert "warning" in result.stderr
    assert "internalServerError" in result.stderr
    assert session_files(tmp_path) == []


def test_logoff_deletes_the_file_and_warns_when_the_service_does_not_answer(
    service: FakeService, tmp_path: Path
) -> None:
    dod(service, tmp_path, "logon")
    service.inject_no_answer("logOff")

    result = dod(service, tmp_path, "logoff")

    assert result.returncode == 0
    assert "warning" in result.stderr
    assert session_files(tmp_path) == []


def test_logoff_without_a_stored_session_sends_nothing(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "logoff")

    assert result.returncode == 0
    assert service.requests == []


def test_session_clear_deletes_the_file_without_any_network(
    service: FakeService, tmp_path: Path
) -> None:
    dod(service, tmp_path, "logon")
    service.requests.clear()

    result = dod(service, tmp_path, "session", "clear")

    assert result.returncode == 0, result.stderr
    assert service.requests == []
    assert len(service.sessions) == 1
    assert session_files(tmp_path) == []


def test_session_status_is_local_by_default(
    service: FakeService, tmp_path: Path
) -> None:
    before = dod(service, tmp_path, "session", "status")
    dod(service, tmp_path, "logon")
    service.requests.clear()
    after = dod(service, tmp_path, "session", "status")

    assert before.returncode == 0
    assert "none" in before.stdout
    assert after.returncode == 0
    assert "stored" in after.stdout
    assert service.requests == []


def test_session_status_check_asks_the_service_with_one_reading_call(
    service: FakeService, tmp_path: Path
) -> None:
    dod(service, tmp_path, "logon")
    service.requests.clear()

    result = dod(service, tmp_path, "session", "status", "--check")

    assert result.returncode == 0, result.stderr
    assert "active" in result.stdout
    assert operations(service) == ["getServiceAttributes"]


def test_session_status_check_reports_an_expired_session_and_exits_1(
    service: FakeService, tmp_path: Path
) -> None:
    dod(service, tmp_path, "logon")
    service.sessions.clear()
    service.requests.clear()

    result = dod(service, tmp_path, "session", "status", "--check")

    assert result.returncode == 1
    assert "expired" in result.stdout
    assert operations(service) == ["getServiceAttributes"]


def test_session_status_has_json_output(service: FakeService, tmp_path: Path) -> None:
    dod(service, tmp_path, "logon")

    result = dod(service, tmp_path, "session", "status", "--format", "json")

    assert json.loads(result.stdout)["session"] == "stored"


def test_status_shows_environment_user_and_the_stored_session(
    service: FakeService, tmp_path: Path
) -> None:
    dod(service, tmp_path, "logon")
    service.requests.clear()

    result = dod(service, tmp_path, "status", "--quiet")

    assert result.returncode == 0, result.stderr
    assert f"username: {USER}" in result.stdout
    assert "session: stored" in result.stdout
    assert "environment: -" in result.stdout
    assert service.requests == []


def test_status_shows_an_ephemeral_session_with_no_session(
    service: FakeService, tmp_path: Path
) -> None:
    dod(service, tmp_path, "logon")

    result = dod(service, tmp_path, "status", "--no-session")

    assert "session: ephemeral" in result.stdout


def test_status_without_a_stored_session_says_so(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "status")

    assert "session: none" in result.stdout


def test_the_session_commands_refuse_xml_output(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "session", "status", "--format", "xml")

    assert result.returncode == 2
    assert "xml" in result.stderr


def test_session_commands_without_a_service_address_say_what_to_pass(
    tmp_path: Path,
) -> None:
    result = run_dod("status", env={"DOD_STATE_DIR": str(tmp_path)})

    assert result.returncode == 2
    assert "--url" in result.stderr


_WORKER = textwrap.dedent(
    """
    import sys, time
    from dod.application import SessionManager
    from dod.domain.service import Ok, Password
    from dod.infrastructure import FileSessionStore, HttpServicePort

    url, state, start = sys.argv[1], sys.argv[2], float(sys.argv[3])
    manager = SessionManager(
        HttpServicePort, FileSessionStore(state), url, "synthetic-user",
        lambda: Password("synthetic-secret"),
    )
    time.sleep(max(0.0, start - time.time()))
    reply = manager.call(lambda port: port.get_service_attributes())
    sys.exit(0 if isinstance(reply, Ok) else 1)
    """
)


def test_concurrent_processes_share_one_session_and_only_one_logs_in_again(
    service: FakeService, tmp_path: Path
) -> None:
    dod(service, tmp_path, "logon")
    service.sessions.clear()
    service.requests.clear()
    start = time.time() + 2.0

    workers = [
        subprocess.Popen(
            [sys.executable, "-c", _WORKER, service.url, str(tmp_path), str(start)],
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(4)
    ]
    outcomes = [
        (worker.wait(60), worker.stderr.read() if worker.stderr else "")
        for worker in workers
    ]

    assert [code for code, _ in outcomes] == [0, 0, 0, 0], outcomes
    assert operations(service).count("logOn") == 1
    assert len(service.sessions) == 1
    assert len(session_files(tmp_path)) == 1
