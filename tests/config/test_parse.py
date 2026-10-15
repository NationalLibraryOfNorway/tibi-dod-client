"""Structural validation of the configuration file text (public interface only).

All Environments, users and passwords are synthetic.
"""

import pytest

from dod.domain.config import ConfigError, parse_config
from dod.domain.service import Password

PATH = "/synthetic/config.toml"

VALID = """
default_environment = "test"

[environments.test]
url = "https://dod.example.org/service"
username = "synthetic-user"
password = "synthetic-secret"
insecure = false
trust_host = true
protected = true
quirks = ["some-quirk"]

[environments.local]
wsdl = "http://127.0.0.1:8080/service?wsdl"
"""


def rejected(text: str) -> ConfigError:
    with pytest.raises(ConfigError) as caught:
        parse_config(text, PATH)
    return caught.value


def test_a_valid_file_gives_the_named_environments() -> None:
    config = parse_config(VALID, PATH)

    assert config.default_environment == "test"
    assert list(config.environments) == ["test", "local"]
    test = config.environments["test"]
    assert test.url == "https://dod.example.org/service"
    assert test.wsdl is None
    assert test.username == "synthetic-user"
    assert test.password == Password("synthetic-secret")
    assert (test.insecure, test.trust_host, test.protected) == (False, True, True)
    assert test.quirks == ("some-quirk",)
    local = config.environments["local"]
    assert local.wsdl == "http://127.0.0.1:8080/service?wsdl"
    assert local.url is None
    assert local.password is None
    assert (local.insecure, local.trust_host, local.protected) == (False, False, False)
    assert local.quirks == ()


def test_an_empty_file_is_an_empty_configuration() -> None:
    config = parse_config("", PATH)

    assert config.environments == {}
    assert config.default_environment is None


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("colour = 1", "colour"),
        (
            "[environments.a]\nurl = 'https://x.example.org'\nflavour = 1",
            "environments.a.flavour",
        ),
    ],
)
def test_unknown_keys_are_rejected_with_their_key(text: str, key: str) -> None:
    error = rejected(text)

    assert error.key == key
    assert "unknown key" in error.reason
    assert PATH in str(error)
    assert key in str(error)


@pytest.mark.parametrize("name", ["token", "cookie"])
def test_token_and_cookie_get_a_message_of_their_own(name: str) -> None:
    error = rejected(f"[environments.a]\nurl = 'https://x.example.org'\n{name} = 'x'")

    assert error.key == f"environments.a.{name}"
    assert "unknown key" not in error.reason
    assert "never stored" in error.reason


@pytest.mark.parametrize("name", ["Prod", "_a", "a b", "-a", "ø"])
def test_environment_names_must_match_the_pattern(name: str) -> None:
    error = rejected(f"[environments.'{name}']\nurl = 'https://x.example.org'")

    assert "[a-z0-9][a-z0-9_-]*" in error.reason
    assert name in (error.key or "")


@pytest.mark.parametrize(
    "body",
    [
        "url = 1",
        "url = 'https://x.example.org'\nusername = 1",
        "url = 'https://x.example.org'\npassword = 1",
        "url = 'https://x.example.org'\ninsecure = 'yes'",
        "url = 'https://x.example.org'\ntrust_host = 1",
        "url = 'https://x.example.org'\nprotected = 'no'",
        "url = 'https://x.example.org'\nquirks = 'a'",
        "url = 'https://x.example.org'\nquirks = [1]",
    ],
)
def test_values_must_have_the_right_type(body: str) -> None:
    error = rejected(f"[environments.a]\n{body}")

    assert "must be" in error.reason
    assert (error.key or "").startswith("environments.a.")


@pytest.mark.parametrize(
    "body",
    [
        "username = 'u'",
        "url = 'https://x.example.org'\nwsdl = 'https://y.example.org/?wsdl'",
    ],
)
def test_exactly_one_of_url_and_wsdl(body: str) -> None:
    error = rejected(f"[environments.a]\n{body}")

    assert error.key == "environments.a"
    assert "exactly one of url and wsdl" in error.reason


def test_the_default_environment_must_be_a_valid_name() -> None:
    error = rejected('default_environment = "Bad Name"')

    assert error.key == "default_environment"


def test_an_environments_table_of_the_wrong_type_is_rejected() -> None:
    assert rejected("environments = 1").key == "environments"
    assert rejected("[environments]\na = 1").key == "environments.a"


def test_a_syntax_error_gives_the_line_number() -> None:
    error = rejected("default_environment = 'a'\n\n[environments.a\n")

    assert error.line == 3
    assert PATH in str(error)
    assert "line 3" in str(error)


def test_a_password_is_never_part_of_an_error() -> None:
    secret = "synthetic-secret-123"
    texts = [
        f"[environments.a]\nurl = 'https://x.example.org'\npassword = {secret}",
        f"[environments.a]\nurl = 'https://x.example.org'\npassword = ['{secret}']",
        "[environments.a]\nwsdl = 'https://x.example.org'\n"
        f"url = 'https://y.example.org'\npassword = '{secret}'",
        "[environments.a]\nurl = 'https://x.example.org'\n"
        f"password = '{secret}'\nbad = 1",
    ]
    for text in texts:
        error = rejected(text)
        assert secret not in str(error)
        assert secret not in repr(error)
        assert secret not in error.reason
