"""`dod config` and `dod logon --env` through the CLI boundary (ADR 0003).

Subprocess tests run the installed console script against configuration files
in a scratch directory and the fake Service on localhost. Users, passwords and
hosts are synthetic. The Windows file-permission model differs, so the tests of
the permission refusal run on POSIX only.
"""

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from support import FakeService, run_dod

USER = "synthetic-user"
PASSWORD = "synthetic-secret"
FILE_PASSWORD = "synthetic-file-secret"

posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX file permissions"
)


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD)
    fake.add_user("file-user", FILE_PASSWORD)
    yield fake
    fake.stop()


def write(tmp_path: Path, text: str, *, mode: int = 0o600) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    if sys.platform != "win32":
        path.chmod(mode)
    return path


def local_file(tmp_path: Path, service: FakeService) -> Path:
    return write(
        tmp_path,
        f"""
default_environment = "local"

[environments.local]
url = "{service.url}"
insecure = true
username = "file-user"
password = "{FILE_PASSWORD}"

[environments.bare]
url = "{service.url}"
insecure = true
""",
    )


# -- config path -----------------------------------------------------------


def test_config_path_prints_the_explicit_file(tmp_path: Path) -> None:
    path = tmp_path / "x.toml"

    result = run_dod("config", "path", "--config", str(path))

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(path)


def test_config_path_follows_dod_config(tmp_path: Path) -> None:
    path = tmp_path / "x.toml"

    result = run_dod("config", "path", env={"DOD_CONFIG": str(path)})

    assert result.stdout.strip() == str(path)


def test_config_path_defaults_to_a_file_in_the_platform_config_directory() -> None:
    result = run_dod("config", "path")

    assert result.returncode == 0
    path = Path(result.stdout.strip())
    assert path.name == "config.toml"
    assert path.parent.name == "dod"


# -- config check ----------------------------------------------------------


def test_a_missing_default_file_is_not_an_error(tmp_path: Path) -> None:
    home = {
        "HOME": str(tmp_path),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg"),
        "USERPROFILE": str(tmp_path),
        "APPDATA": str(tmp_path / "appdata"),
        "LOCALAPPDATA": str(tmp_path / "appdata"),
    }

    result = run_dod("config", "check", env=home)

    assert result.returncode == 0, result.stderr


def test_a_missing_explicit_file_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "absent.toml"

    result = run_dod("config", "check", "--config", str(path))

    assert result.returncode == 2
    assert str(path) in result.stderr
    assert "not found" in result.stderr


def test_check_lists_every_environment(tmp_path: Path, service: FakeService) -> None:
    path = local_file(tmp_path, service)

    result = run_dod("config", "check", "--config", str(path))

    assert result.returncode == 0, result.stderr
    assert "environments.local: ok" in result.stdout
    assert "environments.bare: ok" in result.stdout
    assert service.requests == []


def test_check_reports_file_key_and_reason(tmp_path: Path) -> None:
    path = write(tmp_path, "[environments.a]\nurl = 'https://x.example.org'\nx = 1\n")

    result = run_dod("config", "check", "--config", str(path))

    assert result.returncode == 2
    assert str(path) in result.stderr
    assert "environments.a.x" in result.stderr
    assert "unknown key" in result.stderr


def test_a_syntax_error_reports_the_line(tmp_path: Path) -> None:
    path = write(tmp_path, "\n\n[environments.a\n")

    result = run_dod("config", "check", "--config", str(path))

    assert result.returncode == 2
    assert str(path) in result.stderr
    assert "line 3" in result.stderr


def test_a_password_is_never_in_an_error(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        f"[environments.a]\nurl = 'https://x.example.org'\npassword = {PASSWORD}\n",
    )

    result = run_dod("config", "check", "--config", str(path))

    assert result.returncode == 2
    assert PASSWORD not in result.stderr + result.stdout


@posix_only
def test_a_password_in_a_file_others_can_read_is_refused(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        f"[environments.a]\nurl = 'https://x.example.org'\npassword = '{PASSWORD}'\n",
        mode=0o644,
    )

    for command in (("config", "check"), ("config", "show", "--env", "a")):
        result = run_dod(*command, "--config", str(path))

        assert result.returncode == 2
        assert f"chmod 600 {path}" in result.stderr
        assert PASSWORD not in result.stderr + result.stdout


@posix_only
def test_a_file_without_a_password_may_be_readable_by_others(tmp_path: Path) -> None:
    path = write(
        tmp_path, "[environments.a]\nurl = 'https://x.example.org'\n", mode=0o644
    )

    assert run_dod("config", "check", "--config", str(path)).returncode == 0


@posix_only
def test_check_does_not_warn_about_permissions_on_posix(tmp_path: Path) -> None:
    path = write(tmp_path, "[environments.a]\nurl = 'https://x.example.org'\n")

    assert run_dod("config", "check", "--config", str(path)).stderr == ""


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_check_warns_on_windows_that_permissions_are_not_checked(
    tmp_path: Path,
) -> None:
    path = write(tmp_path, "[environments.a]\nurl = 'https://x.example.org'\n")

    result = run_dod("config", "check", "--config", str(path))

    assert result.returncode == 0
    assert "permissions are not checked" in result.stderr


# -- config show -----------------------------------------------------------


def test_show_gives_the_effective_values_with_their_sources(
    tmp_path: Path, service: FakeService
) -> None:
    path = local_file(tmp_path, service)

    result = run_dod("config", "show", "--config", str(path), "--username", "flag-user")

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert f"url = {service.url} (environments.local.url)" in lines
    assert "environment = local (default_environment)" in lines
    assert "username = flag-user (--username)" in lines
    assert "password = *** (environments.local.password)" in lines
    assert "insecure = true (environments.local.insecure)" in lines
    assert "protected = false (default)" in lines
    assert FILE_PASSWORD not in result.stdout + result.stderr


def test_show_without_an_environment_says_so(tmp_path: Path) -> None:
    path = write(tmp_path, "")

    result = run_dod("config", "show", "--config", str(path))

    assert result.returncode == 0, result.stderr
    assert "environment = none" in result.stdout.splitlines()


def test_show_hides_credentials_embedded_in_an_address(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "[environments.a]\nurl = 'https://u:embedded-secret@x.example.org/s'\n",
    )

    result = run_dod("config", "show", "--config", str(path), "--env", "a")

    assert "embedded-secret" not in result.stdout
    assert "x.example.org" in result.stdout


def test_show_takes_the_environment_from_dod_env(
    tmp_path: Path, service: FakeService
) -> None:
    path = local_file(tmp_path, service)

    result = run_dod("config", "show", "--config", str(path), env={"DOD_ENV": "bare"})

    assert "environment = bare (DOD_ENV)" in result.stdout.splitlines()


def test_show_with_env_and_url_is_an_error(tmp_path: Path) -> None:
    path = write(tmp_path, "[environments.a]\nurl = 'https://x.example.org'\n")

    result = run_dod(
        "config",
        "show",
        "--config",
        str(path),
        "--env",
        "a",
        "--url",
        "https://y.example.org",
    )

    assert result.returncode == 2
    assert "--env" in result.stderr


# -- logon --env -----------------------------------------------------------


def test_logon_with_env_uses_the_address_and_credentials_of_the_file(
    tmp_path: Path, service: FakeService
) -> None:
    path = local_file(tmp_path, service)

    result = run_dod("logon", "--no-session", "--config", str(path), "--env", "local")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == "logOn: ok"
    assert service.sessions == set()


def test_logon_uses_the_default_environment_and_dod_config(
    tmp_path: Path, service: FakeService
) -> None:
    path = local_file(tmp_path, service)

    result = run_dod("logon", "--no-session", env={"DOD_CONFIG": str(path)})

    assert result.returncode == 0, result.stderr


def test_logon_takes_the_environment_from_dod_env(
    tmp_path: Path, service: FakeService
) -> None:
    path = local_file(tmp_path, service)

    result = run_dod(
        "logon",
        "--no-session",
        "--username",
        USER,
        "--password-stdin",
        "--config",
        str(path),
        env={"DOD_ENV": "bare"},
        stdin=PASSWORD + "\n",
    )

    assert result.returncode == 0, result.stderr


def test_the_password_from_stdin_beats_the_one_in_the_file(
    tmp_path: Path, service: FakeService
) -> None:
    path = local_file(tmp_path, service)

    right = run_dod(
        "logon",
        "--no-session",
        "--config",
        str(path),
        "--username",
        USER,
        "--password-stdin",
        stdin=PASSWORD + "\n",
    )
    wrong = run_dod(
        "logon",
        "--no-session",
        "--config",
        str(path),
        "--password-stdin",
        stdin="not-the-password\n",
    )

    assert right.returncode == 0, right.stderr
    assert wrong.returncode == 1


def test_the_username_flag_beats_dod_username_beats_the_file(
    tmp_path: Path, service: FakeService
) -> None:
    path = local_file(tmp_path, service)
    base = ("logon", "--no-session", "--config", str(path), "--password-stdin")

    from_variable = run_dod(*base, env={"DOD_USERNAME": USER}, stdin=PASSWORD + "\n")
    from_flag = run_dod(
        *base, "--username", USER, env={"DOD_USERNAME": "other"}, stdin=PASSWORD + "\n"
    )
    from_file = run_dod(*base, stdin=FILE_PASSWORD + "\n")

    assert from_variable.returncode == 0, from_variable.stderr
    assert from_flag.returncode == 0, from_flag.stderr
    assert from_file.returncode == 0, from_file.stderr


def test_there_is_no_password_variable(tmp_path: Path, service: FakeService) -> None:
    path = local_file(tmp_path, service)

    result = run_dod(
        "logon",
        "--no-session",
        "--config",
        str(path),
        "--env",
        "bare",
        "--username",
        USER,
        "--password-stdin",
        env={"DOD_PASSWORD": PASSWORD},
        stdin="",
    )

    assert result.returncode == 2
    assert service.requests == []


def test_logon_with_env_and_url_is_a_usage_error(
    tmp_path: Path, service: FakeService
) -> None:
    path = local_file(tmp_path, service)

    result = run_dod(
        "logon",
        "--no-session",
        "--config",
        str(path),
        "--env",
        "local",
        "--url",
        service.url,
    )

    assert result.returncode == 2
    assert "--env" in result.stderr
    assert service.requests == []


def test_logon_with_an_unknown_environment_is_exit_2(
    tmp_path: Path, service: FakeService
) -> None:
    path = local_file(tmp_path, service)

    result = run_dod("logon", "--no-session", "--config", str(path), "--env", "nope")

    assert result.returncode == 2
    assert "nope" in result.stderr
    assert service.requests == []


def test_logon_without_an_address_says_what_to_pass(tmp_path: Path) -> None:
    path = write(tmp_path, "")

    result = run_dod("logon", "--no-session", "--config", str(path), "--username", "u")

    assert result.returncode == 2
    assert "--url" in result.stderr
    assert "--env" in result.stderr


def test_logon_with_a_broken_config_is_exit_2_before_anything_is_sent(
    tmp_path: Path, service: FakeService
) -> None:
    path = write(tmp_path, "bogus = 1\n")

    result = run_dod(
        "logon",
        "--no-session",
        "--config",
        str(path),
        "--url",
        service.url,
        "--username",
        USER,
        "--insecure",
        "--password-stdin",
        stdin=PASSWORD + "\n",
    )

    assert result.returncode == 2
    assert "bogus" in result.stderr
    assert service.requests == []


# -- help ------------------------------------------------------------------


@pytest.mark.parametrize("command", [("config", "show"), ("logon",)])
def test_help_describes_the_configuration_options(command: tuple[str, ...]) -> None:
    top_level = run_dod("--help")
    result = run_dod(*command, "--help")

    for option in ("--config", "--env"):
        assert option in top_level.stdout
    assert "dod --help" in result.stdout


@pytest.mark.parametrize("name", ["path", "check", "show"])
def test_the_config_commands_are_listed(name: str) -> None:
    assert name in run_dod("config", "--help").stdout
