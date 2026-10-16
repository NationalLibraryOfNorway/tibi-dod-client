"""Loading the file and resolving the effective connection (application interface).

The file system is replaced by an in-memory store; users and passwords are
synthetic.
"""

import pytest

from dod.application import (
    ConfigError,
    ConfigFile,
    check_config,
    load_config,
    resolve_connection,
)
from dod.domain.service import Password

DEFAULT_PATH = "/synthetic/default/config.toml"

FILE = """
default_environment = "test"

[environments.test]
url = "https://test.example.org/service"
username = "file-user"
password = "file-secret"
protected = true

[environments.other]
url = "https://other.example.org/service"
insecure = true

[environments.wsdl]
wsdl = "https://wsdl.example.org/service?wsdl"
"""


class MemoryStore:
    def __init__(
        self,
        files: dict[str, bytes] | None = None,
        *,
        others_can_read: bool | None = False,
    ) -> None:
        self.files = files or {}
        self.others_can_read = others_can_read

    def default_path(self) -> str:
        return DEFAULT_PATH

    def read(self, path: str) -> ConfigFile | None:
        if path not in self.files:
            return None
        return ConfigFile(path, self.files[path], self.others_can_read)


def store_with(
    text: str = FILE, *, others_can_read: bool | None = False
) -> MemoryStore:
    return MemoryStore({DEFAULT_PATH: text.encode()}, others_can_read=others_can_read)


def resolve(  # type: ignore[no-untyped-def]
    store: MemoryStore | None = None,
    *,
    config: str | None = None,
    env: str | None = None,
    url: str | None = None,
    username: str | None = None,
    insecure: bool = False,
    environ: dict[str, str] | None = None,
):
    loaded = load_config(store or store_with(), config)
    return resolve_connection(
        loaded,
        env=env,
        url=url,
        username=username,
        insecure=insecure,
        environ=environ or {},
    )


# -- loading ---------------------------------------------------------------


def test_a_missing_default_file_is_an_empty_configuration() -> None:
    loaded = load_config(MemoryStore(), None)

    assert loaded.path == DEFAULT_PATH
    assert loaded.found is False
    assert loaded.config.environments == {}


def test_a_missing_explicit_file_is_an_error() -> None:
    with pytest.raises(ConfigError) as caught:
        load_config(store_with(), "/synthetic/other.toml")

    assert "/synthetic/other.toml" in str(caught.value)
    assert "not found" in caught.value.reason


def test_an_explicit_file_replaces_the_default_one() -> None:
    store = MemoryStore({"/x.toml": b"default_environment = 'a'"})

    loaded = load_config(store, "/x.toml")

    assert loaded.path == "/x.toml"
    assert loaded.config.default_environment == "a"


def test_a_file_that_is_not_utf8_is_an_error_with_its_path() -> None:
    store = MemoryStore({DEFAULT_PATH: b"\xff\xfe"})

    with pytest.raises(ConfigError) as caught:
        load_config(store, None)

    assert DEFAULT_PATH in str(caught.value)


def test_structural_errors_name_the_file() -> None:
    with pytest.raises(ConfigError) as caught:
        load_config(
            store_with("[environments.a]\nurl = 'https://x.example.org'\nx = 1"), None
        )

    assert str(caught.value).startswith(f"{DEFAULT_PATH}: environments.a.x:")


def test_a_password_in_a_file_others_can_read_is_refused_with_chmod() -> None:
    with pytest.raises(ConfigError) as caught:
        load_config(store_with(others_can_read=True), None)

    assert "chmod 600" in caught.value.reason
    assert DEFAULT_PATH in str(caught.value)
    assert "file-secret" not in str(caught.value)


def test_a_file_without_a_password_may_be_readable_by_others() -> None:
    text = "[environments.a]\nurl = 'https://x.example.org'"

    assert load_config(store_with(text, others_can_read=True), None).found


# -- selecting the environment ---------------------------------------------


def test_the_default_environment_is_used_when_nothing_else_is_given() -> None:
    connection = resolve()

    assert connection.environment is not None
    assert (connection.environment.value, connection.environment.source) == (
        "test",
        "default_environment",
    )
    assert connection.url is not None
    assert connection.url.value == "https://test.example.org/service"


def test_the_environment_flag_beats_the_variable_beats_the_default() -> None:
    environ = {"DOD_ENV": "other"}

    flag = resolve(env="wsdl", environ=environ)
    variable = resolve(environ=environ)

    assert flag.environment is not None
    assert (flag.environment.value, flag.environment.source) == ("wsdl", "--env")
    assert variable.environment is not None
    assert (variable.environment.value, variable.environment.source) == (
        "other",
        "DOD_ENV",
    )


def test_env_together_with_url_is_an_error() -> None:
    with pytest.raises(ConfigError) as caught:
        resolve(env="test", url="https://x.example.org")

    assert "--env" in caught.value.reason
    assert "--url" in caught.value.reason


def test_url_beats_the_variable_and_the_default_environment() -> None:
    connection = resolve(url="https://x.example.org", environ={"DOD_ENV": "other"})

    assert connection.environment is None
    assert connection.url is not None
    assert (connection.url.value, connection.url.source) == (
        "https://x.example.org",
        "--url",
    )
    assert connection.password is None


def test_an_unknown_environment_names_the_known_ones() -> None:
    with pytest.raises(ConfigError) as caught:
        resolve(env="nope")

    assert "nope" in caught.value.reason
    assert "other" in caught.value.reason
    assert "test" in caught.value.reason


def test_a_default_environment_that_does_not_exist_is_an_error_when_used() -> None:
    store = store_with("default_environment = 'gone'")

    with pytest.raises(ConfigError) as caught:
        resolve(store)
    assert "gone" in caught.value.reason
    assert resolve(store, url="https://x.example.org").url is not None


def test_nothing_selected_means_no_address() -> None:
    connection = resolve(MemoryStore())

    assert connection.environment is None
    assert connection.url is None
    assert connection.wsdl is None


# -- values and their sources ----------------------------------------------


def test_username_comes_from_the_flag_then_the_variable_then_the_file() -> None:
    environ = {"DOD_USERNAME": "env-user"}

    flag = resolve(username="flag-user", environ=environ).username
    variable = resolve(environ=environ).username
    file = resolve().username

    assert flag is not None and (flag.value, flag.source) == ("flag-user", "--username")
    assert variable is not None and (variable.value, variable.source) == (
        "env-user",
        "DOD_USERNAME",
    )
    assert file is not None and (file.value, file.source) == (
        "file-user",
        "environments.test.username",
    )


def test_the_password_comes_from_the_selected_environment_only() -> None:
    connection = resolve()

    assert connection.password is not None
    assert connection.password.value == Password("file-secret")
    assert connection.password.source == "environments.test.password"
    assert resolve(env="other").password is None


def test_there_is_no_environment_variable_for_the_password() -> None:
    assert resolve(env="other", environ={"DOD_PASSWORD": "x"}).password is None


def test_insecure_is_the_flag_or_the_environment() -> None:
    assert resolve().insecure.value is False
    assert resolve().insecure.source == "default"
    assert resolve(env="other").insecure.value is True
    assert resolve(env="other").insecure.source == "environments.other.insecure"
    assert resolve(insecure=True).insecure.source == "--insecure"


def test_protected_and_the_other_switches_come_from_the_file() -> None:
    connection = resolve()

    assert connection.protected.value is True
    assert connection.trust_host.value is False
    assert connection.quirks.value == ()


def test_a_wsdl_environment_has_a_wsdl_and_no_url() -> None:
    connection = resolve(env="wsdl")

    assert connection.url is None
    assert connection.wsdl is not None
    assert connection.wsdl.value == "https://wsdl.example.org/service?wsdl"


def test_empty_variables_count_as_unset() -> None:
    connection = resolve(environ={"DOD_ENV": "", "DOD_USERNAME": ""})

    assert connection.environment is not None
    assert connection.environment.source == "default_environment"


def test_the_selected_environment_must_have_a_usable_address() -> None:
    store = store_with("[environments.a]\nurl = 'ftp://x.example.org'")

    with pytest.raises(ConfigError) as caught:
        resolve(store, env="a")

    assert caught.value.key == "environments.a.url"
    assert DEFAULT_PATH in str(caught.value)


def test_the_password_is_not_shown_by_repr() -> None:
    assert "file-secret" not in repr(resolve())


# -- check -----------------------------------------------------------------


def test_check_validates_every_environment_without_selecting_one() -> None:
    loaded = load_config(store_with(), None)

    report = check_config(loaded)

    assert report.environments == ("test", "other", "wsdl")
    assert report.warnings == ()


def test_check_finds_a_bad_address_in_an_unused_environment() -> None:
    text = (
        "[environments.a]\nurl = 'https://x.example.org'\n"
        "[environments.b]\nurl = 'not a url'\n"
    )

    with pytest.raises(ConfigError) as caught:
        check_config(load_config(store_with(text), None))

    assert caught.value.key == "environments.b.url"


def test_check_finds_a_default_environment_that_does_not_exist() -> None:
    with pytest.raises(ConfigError) as caught:
        check_config(load_config(store_with("default_environment = 'gone'"), None))

    assert caught.value.key == "default_environment"


def test_check_warns_that_permissions_are_not_checked_where_they_cannot_be() -> None:
    report = check_config(load_config(store_with(others_can_read=None), None))

    assert any("permissions" in warning for warning in report.warnings)


def test_check_does_not_warn_about_permissions_without_a_file() -> None:
    assert (
        check_config(load_config(MemoryStore(others_can_read=None), None)).warnings
        == ()
    )


def test_check_warns_about_plain_http_without_insecure() -> None:
    text = "[environments.a]\nurl = 'http://x.example.org'"

    report = check_config(load_config(store_with(text), None))

    assert any("insecure" in warning for warning in report.warnings)
