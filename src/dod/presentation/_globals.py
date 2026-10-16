"""The global flags, accepted before or after the subcommand.

Click's parser stops at the first subcommand, so options declared on the root
command are only accepted before it. `GlobalOptionsFirst` moves the documented
global flags found anywhere on the line to the front before parsing, so that
`dod --url U logon` and `dod logon --url U` mean the same, and a command added
later inherits every global flag without declaring any of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from typer.core import TyperGroup

VALUE_OPTIONS = frozenset(
    {
        "--env",
        "--url",
        "--wsdl",
        "--username",
        "--config",
        "--format",
        "--save-exchanges",
    }
)
FLAG_OPTIONS = frozenset(
    {
        "--debug",
        "--quiet",
        "--no-session",
        "--insecure",
        "--trust-host",
        "--unmask",
        "--unmask-password",
        "--password-stdin",
    }
)


class OutputFormat(StrEnum):
    TEXT = "text"
    JSON = "json"
    XML = "xml"


@dataclass(frozen=True)
class GlobalOptions:
    """What the global flags said; one per run, available to every command."""

    env: str | None = None
    url: str | None = None
    wsdl: str | None = None
    username: str | None = None
    config: str | None = None
    format: OutputFormat = OutputFormat.TEXT
    debug: bool = False
    save_exchanges: str | None = None
    quiet: bool = False
    no_session: bool = False
    insecure: bool = False
    trust_host: bool = False
    unmask: bool = False
    unmask_password: bool = False
    password_stdin: bool = False


class Terminal(Protocol):
    """What the unmask rules ask about the terminal (ADR 0007)."""

    def stderr_is_tty(self) -> bool: ...

    def stdin_is_tty(self) -> bool: ...


def hoist_global_options(args: list[str]) -> list[str]:
    """Move global flags (and their values) in front of everything else."""
    hoisted: list[str] = []
    rest: list[str] = []
    position = 0
    while position < len(args):
        arg = args[position]
        if arg == "--":
            rest.extend(args[position:])
            break
        name = arg.partition("=")[0]
        if arg in FLAG_OPTIONS or (name in VALUE_OPTIONS and "=" in arg):
            hoisted.append(arg)
        elif arg in VALUE_OPTIONS and position + 1 < len(args):
            hoisted.extend(args[position : position + 2])
            position += 1
        else:
            rest.append(arg)
        position += 1
    return hoisted + rest


class GlobalOptionsFirst(TyperGroup):
    """A command group that accepts the global flags anywhere on the line."""

    def parse_args(self, ctx, args):  # type: ignore[no-untyped-def]
        return super().parse_args(ctx, hoist_global_options(list(args)))
