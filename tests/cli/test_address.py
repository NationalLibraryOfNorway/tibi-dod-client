"""Finding the endpoint: `--wsdl`, host security, `discover` and the banner.

Subprocess tests run the installed console script against the fake Service on
localhost, which also serves a WSDL (ADR 0002, ADR 0003). Hosts, users and
passwords are synthetic.
"""

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from support import FakeService, run_dod, service_wsdl

USER = "synthetic-user"
PASSWORD = "synthetic-secret"


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD)
    yield fake
    fake.stop()


@pytest.fixture
def other() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD)
    yield fake
    fake.stop()


def logon(*args: str):  # type: ignore[no-untyped-def]
    return run_dod(
        "logon",
        "--no-session",
        "--username",
        USER,
        "--password-stdin",
        *args,
        stdin=PASSWORD + "\n",
    )


def operations(service: FakeService) -> list[str | None]:
    return [request.operation for request in service.requests]


# -- --wsdl ----------------------------------------------------------------


def test_logon_with_wsdl_talks_to_the_soap_address_of_the_wsdl(
    service: FakeService,
) -> None:
    service.wsdl_address = service.url + "/soap"

    result = logon("--wsdl", service.wsdl_url, "--insecure")

    assert result.returncode == 0, result.stderr
    assert {request.path for request in service.requests} == {"/dodp/soap"}
    assert operations(service)[0] == "logOn"


def test_the_wsdl_is_fetched_without_credentials_or_cookies(
    service: FakeService,
) -> None:
    result = logon("--wsdl", service.wsdl_url, "--insecure")

    assert result.returncode == 0, result.stderr
    assert [fetch.path for fetch in service.fetches] == ["/dodp?wsdl"]
    names = {name.lower() for name in service.fetches[0].headers}
    assert names.isdisjoint({"authorization", "cookie"})


def test_url_and_wsdl_together_are_a_usage_error(service: FakeService) -> None:
    result = logon("--url", service.url, "--wsdl", service.wsdl_url, "--insecure")

    assert result.returncode == 2
    assert "--url" in result.stderr and "--wsdl" in result.stderr
    assert service.requests == [] and service.fetches == []


def test_an_environment_with_a_wsdl_is_used(
    service: FakeService, tmp_path: Path
) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        f'[environments.test]\nwsdl = "{service.wsdl_url}"\ninsecure = true\n',
        encoding="utf-8",
    )
    if sys.platform != "win32":
        config.chmod(0o600)

    result = logon("--config", str(config), "--env", "test")

    assert result.returncode == 0, result.stderr
    assert operations(service)[0] == "logOn"


def test_http_for_the_wsdl_needs_insecure_and_nothing_is_fetched(
    service: FakeService,
) -> None:
    result = logon("--wsdl", service.wsdl_url)

    assert result.returncode == 2
    assert "--insecure" in result.stderr
    assert service.fetches == []


def test_a_wsdl_naming_another_port_is_refused_without_trust_host(
    service: FakeService, other: FakeService
) -> None:
    service.wsdl_address = other.url

    result = logon("--wsdl", service.wsdl_url, "--insecure")

    assert result.returncode == 2
    assert "--trust-host" in result.stderr
    assert service.requests == [] and other.requests == []


def test_trust_host_lets_the_wsdl_name_another_host(
    service: FakeService, other: FakeService
) -> None:
    service.wsdl_address = other.url

    result = logon("--wsdl", service.wsdl_url, "--insecure", "--trust-host")

    assert result.returncode == 0, result.stderr
    assert operations(other)[0] == "logOn"
    assert service.requests == []


def test_a_wsdl_naming_another_scheme_is_refused_without_trust_host(
    service: FakeService,
) -> None:
    service.wsdl_address = service.url.replace("http://", "https://")

    result = logon("--wsdl", service.wsdl_url, "--insecure")

    assert result.returncode == 2
    assert "--trust-host" in result.stderr
    assert service.requests == []


def test_a_redirect_to_another_host_is_refused_even_with_trust_host(
    service: FakeService, other: FakeService
) -> None:
    service.wsdl_redirect = other.wsdl_url.replace("127.0.0.1", "localhost")

    result = logon("--wsdl", service.wsdl_url, "--insecure", "--trust-host")

    assert result.returncode == 2
    assert "redirect" in result.stderr
    assert other.fetches == [] and service.requests == []


def test_a_wsdl_without_exactly_one_dodp_port_lists_the_ports(
    service: FakeService,
) -> None:
    service.serve_wsdl(service_wsdl(service.url, binding="do:Unknown"))

    result = logon("--wsdl", service.wsdl_url, "--insecure")

    assert result.returncode == 2
    assert "SyntheticPort" in result.stderr
    assert "not DODP" in result.stderr
    assert service.requests == []


def test_a_wsdl_with_a_dtd_is_refused(service: FakeService) -> None:
    service.serve_wsdl(b'<!DOCTYPE a [<!ENTITY x "y">]><a>&x;</a>')

    result = logon("--wsdl", service.wsdl_url, "--insecure")

    assert result.returncode == 2
    assert "DTD" in result.stderr
    assert service.requests == []


# -- banner and hint ---------------------------------------------------------


def test_every_command_says_where_the_call_goes(service: FakeService) -> None:
    result = logon("--url", service.url, "--insecure")

    assert f"[-] {service.url}" in result.stderr.splitlines()
    assert service.url not in result.stdout


def test_the_banner_names_the_environment_and_the_resolved_endpoint(
    service: FakeService, tmp_path: Path
) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        f'[environments.test]\nwsdl = "{service.wsdl_url}"\ninsecure = true\n',
        encoding="utf-8",
    )
    if sys.platform != "win32":
        config.chmod(0o600)

    result = logon("--config", str(config), "--env", "test")

    assert f"[test] {service.url}" in result.stderr.splitlines()


def test_quiet_turns_the_banner_off(service: FakeService) -> None:
    result = logon("--url", service.url, "--insecure", "--quiet")

    assert result.returncode == 0
    assert service.url not in result.stderr


def test_an_address_that_is_not_a_dodp_service_suggests_discover(
    service: FakeService,
) -> None:
    service.inject_not_soap("logOn")

    result = logon("--url", service.url, "--insecure")

    assert result.returncode == 2
    assert "dod discover" in result.stderr


# -- discover ----------------------------------------------------------------


def discover(*args: str):  # type: ignore[no-untyped-def]
    return run_dod("discover", *args)


def test_discover_tries_wsdl_on_the_address_and_reports_the_endpoint(
    service: FakeService,
) -> None:
    result = discover(service.url, "--insecure")

    assert result.returncode == 0, result.stderr
    assert service.url in result.stdout
    assert f"{service.url}?wsdl" in result.stderr
    assert service.requests == []
    for fetch in service.fetches:
        assert {n.lower() for n in fetch.headers}.isdisjoint(
            {"authorization", "cookie"}
        )


def test_discover_tries_known_paths_and_says_what_it_tried(
    service: FakeService,
) -> None:
    base = service.url.removesuffix("/dodp")

    result = discover(base, "--insecure")

    assert result.returncode == 0, result.stderr
    tried = [fetch.path for fetch in service.fetches]
    assert tried[0] == "/?wsdl" and tried[-1] == "/dodp?wsdl"
    assert "HTTP 404" in result.stderr
    assert service.url in result.stdout


def test_discover_notes_that_a_wsdl_names_another_host(
    service: FakeService, other: FakeService
) -> None:
    service.wsdl_address = other.url

    result = discover(service.url, "--insecure")

    assert result.returncode == 0, result.stderr
    assert other.url in result.stdout
    assert "--trust-host" in result.stderr


def test_a_failed_discovery_lists_every_attempt_and_suggests_next_steps(
    service: FakeService,
) -> None:
    service.wsdl_path = "/elsewhere?wsdl"
    base = service.url.removesuffix("/dodp")

    result = discover(base, "--insecure")

    assert result.returncode == 2
    assert result.stdout == ""
    assert f"{base}/?wsdl" in result.stderr
    assert f"{base}/dodp?wsdl" in result.stderr
    assert "HTTP 404" in result.stderr
    assert "--url" in result.stderr and "--wsdl" in result.stderr
    # The answer is described, never reproduced.
    assert "not found" not in result.stderr


def test_discover_over_http_needs_insecure_and_sends_nothing(
    service: FakeService,
) -> None:
    result = discover(service.url)

    assert result.returncode == 2
    assert "--insecure" in result.stderr
    assert service.fetches == []
