"""Quirk names in the configuration file, and which Environments enable which."""

import pytest

from dod.application import (
    ConfigError,
    ConfigFile,
    check_config,
    list_quirks,
    load_config,
    resolve_connection,
)
from dod.domain.v1 import QUIRKS

NAME = "http-500-without-fault-as-invalid-operation"
FILE = f"""
[environments.a]
url = "https://a.example.org/service"
quirks = ["{NAME}"]

[environments.b]
url = "https://b.example.org/service"
"""


PATH = "/synthetic/config.toml"


class _Store:
    def __init__(self, text: str) -> None:
        self._text = text

    def default_path(self) -> str:
        return PATH

    def read(self, path: str) -> ConfigFile | None:
        return ConfigFile(path, self._text.encode(), False)


def loaded(text: str = FILE):  # type: ignore[no-untyped-def]
    return load_config(_Store(text), None)


def bad(name: str) -> str:
    return f"[environments.a]\nurl = 'https://a.example.org'\nquirks = ['{name}']"


def test_a_known_quirk_name_is_accepted_and_sourced() -> None:
    connection = resolve_connection(
        loaded(), env="a", url=None, username=None, insecure=False, environ={}
    )

    assert connection.quirks.value == (NAME,)
    assert connection.quirks.source == "environments.a.quirks"


def test_an_unknown_quirk_name_is_refused_for_the_selected_environment() -> None:
    with pytest.raises(ConfigError) as caught:
        resolve_connection(
            loaded(bad("made-up")),
            env="a",
            url=None,
            username=None,
            insecure=False,
            environ={},
        )

    assert caught.value.key == "environments.a.quirks"
    assert "made-up" in str(caught.value)
    assert NAME in str(caught.value)


def test_check_refuses_an_unknown_quirk_in_an_environment_nobody_selected() -> None:
    with pytest.raises(ConfigError) as caught:
        check_config(loaded(bad("made-up")))

    assert caught.value.key == "environments.a.quirks"


def test_the_listing_has_every_known_quirk_and_the_environments_that_enable_it() -> (
    None
):
    listing = list_quirks(loaded())

    assert [use.quirk for use in listing] == list(QUIRKS.values())
    (use,) = [u for u in listing if u.quirk.name == NAME]
    assert use.environments == ("a",)


def test_the_listing_for_one_environment_has_only_its_quirks() -> None:
    assert [u.quirk.name for u in list_quirks(loaded(), env="a")] == [NAME]
    assert list_quirks(loaded(), env="b") == ()


def test_the_listing_for_an_unknown_environment_is_an_error() -> None:
    with pytest.raises(ConfigError, match="gone"):
        list_quirks(loaded(), env="gone")


def test_the_listing_refuses_an_unknown_quirk_name() -> None:
    with pytest.raises(ConfigError):
        list_quirks(loaded(bad("made-up")))
