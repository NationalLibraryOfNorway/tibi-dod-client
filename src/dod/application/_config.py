"""Loading the configuration file and resolving the effective connection.

Precedence, strongest first: command-line flag, environment variable,
configuration file, default. Passwords have no environment variable (ADR 0006).
Use cases do not print and do not exit; they raise `ConfigError`.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from dod.domain.config import Config, ConfigError, Environment, parse_config
from dod.domain.service import Password
from dod.domain.v1 import QUIRKS, Quirk

_EMPTY = Config()


@dataclass(frozen=True)
class ConfigFile:
    """A configuration file as read from storage."""

    path: str
    content: bytes
    others_can_read: bool | None
    """Whether group or others may read it; `None` where that cannot be told."""


class ConfigStore(Protocol):
    """Where the configuration file lives; implemented by infrastructure."""

    def default_path(self) -> str: ...

    def read(self, path: str) -> ConfigFile | None:
        """Return the file, or `None` when it does not exist."""
        ...


@dataclass(frozen=True)
class LoadedConfig:
    """The result of loading: where it looked, whether a file was there."""

    path: str
    found: bool
    config: Config
    permissions_checked: bool = True


def load_config(store: ConfigStore, explicit_path: str | None) -> LoadedConfig:
    """Read and structurally validate the file, every Environment included.

    A missing default file is an empty configuration; a missing explicit file
    is an error. A file with a `password` that group or others can read is
    refused (ADR 0006).
    """
    path = explicit_path or store.default_path()
    try:
        file = store.read(path)
    except OSError as error:
        raise ConfigError(
            f"cannot be read: {error.strerror or error}", path=path
        ) from None
    if file is None:
        if explicit_path:
            raise ConfigError("file not found", path=path)
        return LoadedConfig(path, False, _EMPTY)
    try:
        text = file.content.decode("utf-8")
    except UnicodeDecodeError:
        raise ConfigError("is not valid UTF-8 text", path=path) from None
    config = parse_config(text, path)
    if file.others_can_read and any(
        environment.password for environment in config.environments.values()
    ):
        raise ConfigError(
            "contains a password but can be read by group or others; "
            f"run: chmod 600 {path}",
            path=path,
        )
    return LoadedConfig(path, True, config, file.others_can_read is not None)


@dataclass(frozen=True)
class Sourced[T]:
    """A value and where it came from (a flag, a variable, a key, `default`)."""

    value: T
    source: str


@dataclass(frozen=True)
class Connection:
    """The effective settings for one command, with the source of each."""

    environment: Sourced[str] | None
    url: Sourced[str] | None
    wsdl: Sourced[str] | None
    username: Sourced[str] | None
    password: Sourced[Password] | None
    insecure: Sourced[bool]
    trust_host: Sourced[bool]
    protected: Sourced[bool]
    quirks: Sourced[tuple[str, ...]]
    reading_system: Sourced[str] | None = None


def resolve_connection(
    loaded: LoadedConfig,
    *,
    env: str | None,
    url: str | None,
    username: str | None,
    insecure: bool,
    environ: Mapping[str, str],
    wsdl: str | None = None,
    trust_host: bool = False,
) -> Connection:
    """Combine flags, variables and the selected Environment.

    `env` is the `--env` flag, `url` the `--url` flag and `wsdl` the `--wsdl`
    flag. The Environment is `--env`, then `DOD_ENV`, then
    `default_environment`; an explicit `--url` or `--wsdl` selects none (and
    `--env` together with either, or both of them, is an error). The selected
    Environment is validated semantically.
    """
    if url and wsdl:
        raise ConfigError("--url cannot be combined with --wsdl")
    if env and (url or wsdl):
        raise ConfigError(
            f"--env cannot be combined with {'--url' if url else '--wsdl'}"
        )
    selected = None if url or wsdl else _select(loaded, env, environ)
    if selected is not None:
        name = selected[0]
        _check_semantics(loaded.path, loaded.config.environments[name])
    environment = loaded.config.environments[selected[0]] if selected else None
    prefix = f"environments.{environment.name}." if environment else ""

    def configured[T](value: T | None, key: str) -> Sourced[T] | None:
        return None if value is None else Sourced(value, prefix + key)

    return Connection(
        environment=Sourced(*selected) if selected else None,
        url=Sourced(url, "--url") if url else _from(environment, "url", prefix),
        wsdl=Sourced(wsdl, "--wsdl") if wsdl else _from(environment, "wsdl", prefix),
        username=_username(
            username,
            environ,
            configured(environment.username if environment else None, "username"),
        ),
        password=configured(environment.password if environment else None, "password"),
        insecure=_flag(insecure, environment, "insecure", prefix),
        trust_host=_flag(trust_host, environment, "trust_host", prefix),
        protected=_flag(False, environment, "protected", prefix),
        quirks=(
            Sourced(environment.quirks, prefix + "quirks")
            if environment and environment.quirks
            else Sourced((), "default")
        ),
        reading_system=_declaration(loaded.path, environment, prefix),
    )


def _declaration(
    config_path: str, environment: Environment | None, prefix: str
) -> Sourced[str] | None:
    """The `reading_system` file; a relative path is relative to the config file."""
    if environment is None or environment.reading_system is None:
        return None
    path = environment.reading_system
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(config_path), path)
    return Sourced(path, prefix + "reading_system")


def _select(
    loaded: LoadedConfig, env: str | None, environ: Mapping[str, str]
) -> tuple[str, str] | None:
    chosen: tuple[str, str] | None = None
    if env:
        chosen = (env, "--env")
    elif environ.get("DOD_ENV"):
        chosen = (environ["DOD_ENV"], "DOD_ENV")
    elif loaded.config.default_environment:
        chosen = (loaded.config.default_environment, "default_environment")
    if chosen is None:
        return None
    if chosen[0] not in loaded.config.environments:
        known = ", ".join(loaded.config.environments) or "none"
        where = "in the configuration" if loaded.found else "(no configuration file)"
        raise ConfigError(
            f"unknown Environment {chosen[0]!r} from {chosen[1]} {where}; "
            f"defined: {known}",
            path=loaded.path if loaded.found else None,
        )
    return chosen


def _from(
    environment: Environment | None, field: str, prefix: str
) -> Sourced[str] | None:
    value: str | None = getattr(environment, field, None)
    return None if value is None else Sourced(value, prefix + field)


def _username(
    flag: str | None, environ: Mapping[str, str], configured: Sourced[str] | None
) -> Sourced[str] | None:
    if flag:
        return Sourced(flag, "--username")
    if environ.get("DOD_USERNAME"):
        return Sourced(environ["DOD_USERNAME"], "DOD_USERNAME")
    return configured


def _flag(
    flag: bool, environment: Environment | None, field: str, prefix: str
) -> Sourced[bool]:
    if flag:
        return Sourced(True, f"--{field.replace('_', '-')}")
    if environment is not None and getattr(environment, field):
        return Sourced(True, prefix + field)
    return Sourced(False, "default")


def _check_semantics(path: str, environment: Environment) -> None:
    _check_quirks(path, environment)
    for field in ("url", "wsdl"):
        value: str | None = getattr(environment, field)
        if value is None:
            continue
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ConfigError(
                "must be an http or https address with a host",
                path=path,
                key=f"environments.{environment.name}.{field}",
            )


@dataclass(frozen=True)
class ConfigCheck:
    """What `config check` found: the Environments checked and any warnings."""

    environments: tuple[str, ...]
    warnings: tuple[str, ...]


def check_config(loaded: LoadedConfig) -> ConfigCheck:
    """Validate every Environment semantically, without any network access.

    Raises `ConfigError` for the first problem. Warnings do not fail the check.
    """
    config = loaded.config
    default = config.default_environment
    if default is not None and default not in config.environments:
        raise ConfigError(
            f"names an Environment that is not defined ({default!r})",
            path=loaded.path,
            key="default_environment",
        )
    warnings: list[str] = []
    if loaded.found and not loaded.permissions_checked:
        warnings.append(
            "file permissions are not checked on this platform; make sure only "
            "you can read the file if it holds a password"
        )
    for environment in config.environments.values():
        _check_semantics(loaded.path, environment)
        address = environment.url or environment.wsdl or ""
        if address.startswith("http://") and not environment.insecure:
            warnings.append(
                f"environments.{environment.name} uses http; "
                "commands need insecure = true (or --insecure) to use it"
            )
    return ConfigCheck(tuple(config.environments), tuple(warnings))


def _check_quirks(path: str, environment: Environment) -> None:
    unknown = [name for name in environment.quirks if name not in QUIRKS]
    if unknown:
        raise ConfigError(
            f"unknown Quirk {', '.join(repr(name) for name in unknown)}; "
            f"known: {', '.join(QUIRKS)}",
            path=path,
            key=f"environments.{environment.name}.quirks",
        )


@dataclass(frozen=True)
class QuirkUse:
    """A known Quirk and the Environments that switch it on."""

    quirk: Quirk
    environments: tuple[str, ...]


def list_quirks(
    loaded: LoadedConfig,
    env: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[QuirkUse, ...]:
    """Every known Quirk with the Environments that enable it.

    The Environment is selected as for every other command: `env` (`--env`),
    then `DOD_ENV` in `environ`, then `default_environment`. With one selected
    only the Quirks it enables are listed; with none, all of them. Raises
    `ConfigError` for an unknown Environment or a Quirk name nobody knows.
    """
    environments = loaded.config.environments
    selected = _select(loaded, env, environ or {})
    env = selected[0] if selected else None
    for environment in environments.values():
        _check_quirks(loaded.path, environment)
    chosen = environments.values() if env is None else [environments[env]]
    uses = tuple(
        QuirkUse(
            quirk,
            tuple(e.name for e in chosen if quirk.name in e.quirks),
        )
        for quirk in QUIRKS.values()
    )
    return uses if env is None else tuple(use for use in uses if use.environments)


EXAMPLE_CONFIG = """\
# dod configuration. Save it at the path `dod config path` prints, then run
# `dod config check`. Replace the example values with your own.
default_environment = "test"

[environments.test]
url = "https://dod.example.org/services/daisyonline"   # or: wsdl = "https://.../?wsdl"
username = "alice"
# No password here: dod asks for it. A password in this file is plaintext
# (docs/adr/0006); if you add one, `chmod 600` the file.
# insecure = false
# trust_host = false
# protected = false
# quirks = []                              # names from `dod quirks list`
# reading_system = "reading-system.xml"    # replaces the default declaration

# A Service on your own machine:
# [environments.local]
# url = "http://127.0.0.1:8080/service"
# insecure = true
"""
"""A commented starting point for the configuration file (`dod config example`)."""
