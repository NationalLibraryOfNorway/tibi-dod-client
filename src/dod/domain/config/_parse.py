"""Strict structural validation of the configuration file (TOML)."""

from __future__ import annotations

import re
import tomllib
from typing import Any

from dod.domain.config._model import Config, ConfigError, Environment
from dod.domain.service import Password

ENVIRONMENT_NAME = re.compile(r"[a-z0-9][a-z0-9_-]*")
_NAME_RULE = "must match [a-z0-9][a-z0-9_-]*"
_TOP_LEVEL = {"default_environment", "environments"}
_FORBIDDEN = {"token", "cookie"}
_ENVIRONMENT_KEYS = {
    "url",
    "wsdl",
    "username",
    "password",
    "insecure",
    "trust_host",
    "protected",
    "quirks",
    "reading_system",
}
_LINE = re.compile(r"line (\d+)")


def parse_config(text: str, path: str) -> Config:
    """Parse and structurally validate the file text.

    Raises `ConfigError` for the first problem: TOML syntax (with the line),
    unknown keys, wrong types, bad names, and an Environment that does not
    have exactly one of `url` and `wsdl`. Applied to every Environment,
    selected or not. `path` is only used in error messages.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(
            _syntax_reason(error), path=path, line=_syntax_line(error)
        ) from None
    return _Parser(path).config(data)


def _syntax_line(error: tomllib.TOMLDecodeError) -> int | None:
    line = getattr(error, "lineno", None)
    if isinstance(line, int):
        return line
    found = _LINE.search(str(error))
    return int(found.group(1)) if found else None


def _syntax_reason(error: tomllib.TOMLDecodeError) -> str:
    # The text never repeats the offending value; drop the position suffix,
    # which is reported separately.
    message = re.sub(
        r"\s*\(at (line \d+, column \d+|end of document)\)$", "", str(error)
    )
    return f"invalid TOML: {message}"


class _Parser:
    def __init__(self, path: str) -> None:
        self._path = path

    def _error(self, key: str | None, reason: str) -> ConfigError:
        return ConfigError(reason, path=self._path, key=key)

    def _unknown(self, key: str, name: str) -> ConfigError:
        if name in _FORBIDDEN:
            return self._error(
                key,
                f"{name} is not allowed here: Session cookies and tokens are "
                "never stored in the configuration file",
            )
        return self._error(key, "unknown key")

    def config(self, data: dict[str, Any]) -> Config:
        for name in data:
            if name not in _TOP_LEVEL:
                raise self._unknown(name, name)
        default = data.get("default_environment")
        if "default_environment" in data:
            if not isinstance(default, str):
                raise self._error("default_environment", "must be a string")
            if not ENVIRONMENT_NAME.fullmatch(default):
                raise self._error("default_environment", _NAME_RULE)
        table = data.get("environments", {})
        if not isinstance(table, dict):
            raise self._error("environments", "must be a table")
        environments: dict[str, Environment] = {}
        for name, body in table.items():
            key = f"environments.{name}"
            if not ENVIRONMENT_NAME.fullmatch(name):
                raise self._error(key, f"the name {_NAME_RULE}")
            if not isinstance(body, dict):
                raise self._error(key, "must be a table")
            environments[name] = self._environment(name, key, body)
        return Config(environments, default)

    def _environment(self, name: str, key: str, body: dict[str, Any]) -> Environment:
        for field in body:
            if field not in _ENVIRONMENT_KEYS:
                raise self._unknown(f"{key}.{field}", field)
        url = self._string(key, body, "url")
        wsdl = self._string(key, body, "wsdl")
        if (url is None) == (wsdl is None):
            raise self._error(key, "exactly one of url and wsdl is required")
        return Environment(
            name=name,
            url=url,
            wsdl=wsdl,
            username=self._string(key, body, "username"),
            password=self._password(key, body),
            insecure=self._flag(key, body, "insecure"),
            trust_host=self._flag(key, body, "trust_host"),
            protected=self._flag(key, body, "protected"),
            quirks=self._quirks(key, body),
            reading_system=self._string(key, body, "reading_system"),
        )

    def _string(self, key: str, body: dict[str, Any], field: str) -> str | None:
        if field not in body:
            return None
        value = body[field]
        if not isinstance(value, str) or not value:
            raise self._error(f"{key}.{field}", "must be a non-empty string")
        return value

    def _flag(self, key: str, body: dict[str, Any], field: str) -> bool:
        value = body.get(field, False)
        if not isinstance(value, bool):
            raise self._error(f"{key}.{field}", "must be true or false")
        return value

    def _password(self, key: str, body: dict[str, Any]) -> Password | None:
        value = self._string(key, body, "password")
        return None if value is None else Password(value)

    def _quirks(self, key: str, body: dict[str, Any]) -> tuple[str, ...]:
        value = body.get("quirks", [])
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item for item in value
        ):
            raise self._error(f"{key}.quirks", "must be a list of non-empty strings")
        return tuple(value)
