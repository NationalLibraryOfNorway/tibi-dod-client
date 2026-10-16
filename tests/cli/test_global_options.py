"""The documented global flags are accepted before or after the subcommand."""

import pytest

from support import PASSWORD, FakeService, run_dod

USER = "synthetic-user"


@pytest.fixture
def service():  # type: ignore[no-untyped-def]
    fake = FakeService()
    fake.add_user(USER, PASSWORD)
    yield fake
    fake.stop()


def _connection_flags(service: FakeService) -> list[str]:
    return [
        "--url",
        service.url,
        "--username",
        USER,
        "--password-stdin",
        "--insecure",
        "--no-session",
        "--quiet",
    ]


def test_global_flags_before_the_subcommand_work(service: FakeService) -> None:
    result = run_dod(*_connection_flags(service), "logon", stdin=PASSWORD + "\n")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == "logOn: ok"
    assert "[-]" not in result.stderr


def test_global_flags_after_the_subcommand_work(service: FakeService) -> None:
    result = run_dod("logon", *_connection_flags(service), stdin=PASSWORD + "\n")

    assert result.returncode == 0, result.stderr
    assert "[-]" not in result.stderr


def test_global_flags_may_be_split_around_the_subcommand(
    service: FakeService,
) -> None:
    result = run_dod(
        "--url",
        service.url,
        "logon",
        "--username",
        USER,
        "--insecure",
        "--no-session",
        "--password-stdin",
        "--quiet",
        stdin=PASSWORD + "\n",
    )

    assert result.returncode == 0, result.stderr


def test_the_equals_form_works_after_a_nested_subcommand(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "missing.toml"

    result = run_dod("config", "path", f"--config={path}")

    assert result.stdout.strip() == str(path)


def test_global_flags_are_listed_in_the_top_level_help() -> None:
    result = run_dod("--help")

    for flag in (
        "--env",
        "--url",
        "--wsdl",
        "--username",
        "--config",
        "--format",
        "--debug",
        "--save-exchanges",
        "--quiet",
        "--no-session",
        "--insecure",
        "--trust-host",
        "--unmask",
        "--unmask-password",
        "--password-stdin",
    ):
        assert flag in result.stdout, flag


def test_an_unknown_format_is_a_usage_error() -> None:
    result = run_dod("--format", "yaml", "config", "path")

    assert result.returncode == 2


def test_a_command_without_structured_output_refuses_other_formats() -> None:
    result = run_dod("config", "path", "--format", "json")

    assert result.returncode == 2
    assert "--format" in result.stderr
