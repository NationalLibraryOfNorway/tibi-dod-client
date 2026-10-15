"""The `dod` command line: command groups arranged in help panels."""

import os
import sys
from typing import Annotated, NoReturn
from urllib.parse import urlsplit

import typer

from dod.application import (
    ConfigError,
    ConfigStore,
    Connection,
    EndpointError,
    LogonReport,
    OpenPort,
    Step,
    check_config,
    load_config,
    logon_ephemeral,
    resolve_connection,
)
from dod.domain.service import (
    Deviation,
    Fault,
    Ok,
    Password,
    TransportError,
)

# Exit codes: 0 ok, 1 the Service answered with a Fault or contrary to the
# specification, 2 no usable answer or the command could not be run.
EXIT_OK = 0
EXIT_SERVICE_FAILED = 1
EXIT_UNUSABLE = 2

SESSION_AND_SETUP = "Session and setup"
BROWSE_AND_ISSUE = "Browse and issue"
DOWNLOAD_AND_PLAY = "Download and play"
TESTING_AND_TOOLS = "Testing and tools"

# Command groups with subcommands, by help panel. The commands themselves are
# added by later tickets; until then the groups are empty.
_GROUPS: tuple[tuple[str, str, str], ...] = (
    ("session", "Inspect and clear the stored Session.", SESSION_AND_SETUP),
    ("config", "Show and check the configuration file.", SESSION_AND_SETUP),
    ("quirks", "List the known Quirks.", SESSION_AND_SETUP),
    ("attributes", "Service and Reading System attributes.", BROWSE_AND_ISSUE),
    ("announcements", "Read and mark Service announcements.", BROWSE_AND_ISSUE),
    ("questions", "Navigate the Service's menus.", BROWSE_AND_ISSUE),
    ("bookmarks", "Get and set bookmarks.", DOWNLOAD_AND_PLAY),
    ("test", "Run Conformance tests against a Service.", TESTING_AND_TOOLS),
)


_ConfigOption = Annotated[
    str | None,
    typer.Option(
        "--config",
        envvar="DOD_CONFIG",
        help="The configuration file (default: in the platform's config directory).",
    ),
]
_EnvOption = Annotated[
    str | None,
    typer.Option(
        "--env",
        help="The named Environment to use (also DOD_ENV); not with --url.",
    ),
]
_UsernameOption = Annotated[
    str | None,
    typer.Option(
        "--username",
        help="The user to log on as (also DOD_USERNAME, else the Environment's).",
    ),
]
_InsecureOption = Annotated[
    bool,
    typer.Option(
        "--insecure",
        help="Allow an unencrypted http address, also on loopback.",
    ),
]


def create_app(open_port: OpenPort, config_store: ConfigStore) -> typer.Typer:
    """Build the `dod` command line application.

    `open_port` is how commands reach a Service and `config_store` where the
    configuration file lives; the composition root supplies both, because
    presentation never imports the infrastructure layer.
    """
    app = typer.Typer(
        name="dod",
        help="Test client for DODP v1 Services.",
        no_args_is_help=True,
        add_completion=False,
        rich_markup_mode="rich",
    )
    groups: dict[str, typer.Typer] = {}
    for name, help_text, panel in _GROUPS:
        groups[name] = typer.Typer(no_args_is_help=True)
        app.add_typer(groups[name], name=name, help=help_text, rich_help_panel=panel)
    _add_config_commands(groups["config"], config_store)

    @app.command(
        rich_help_panel=SESSION_AND_SETUP,
        help=(
            "Run the initialisation sequence against a Service and log off again "
            "(ephemeral mode: nothing is stored)."
        ),
    )
    def logon(
        url: Annotated[
            str | None,
            typer.Option(
                "--url",
                help="The Service endpoint, e.g. https://dod.example.org/service.",
            ),
        ] = None,
        username: _UsernameOption = None,
        env: _EnvOption = None,
        config: _ConfigOption = None,
        no_session: Annotated[
            bool,
            typer.Option(
                "--no-session",
                envvar="DOD_NO_SESSION",
                help="Use a Session of its own that is never stored (required).",
            ),
        ] = False,
        password_stdin: Annotated[
            bool,
            typer.Option(
                "--password-stdin",
                help="Read the password from stdin instead of the file or a prompt.",
            ),
        ] = False,
        insecure: _InsecureOption = False,
    ) -> None:
        if not no_session:
            _fail("stored Sessions are not available yet; pass --no-session")
        connection = _connection(config_store, config, env, url, username, insecure)
        if connection.url is None:
            if connection.wsdl is not None:
                _fail("an Environment with a wsdl is not supported by logon yet")
            _fail(
                "no Service address: pass --url or --env, or set "
                "default_environment in the configuration file"
            )
        if connection.username is None:
            _fail(
                "no username: pass --username, set DOD_USERNAME or give the "
                "Environment a username"
            )
        password = _password(password_stdin, connection)
        try:
            report = logon_ephemeral(
                open_port,
                connection.url.value,
                connection.username.value,
                password,
                insecure=connection.insecure.value,
            )
        except EndpointError as error:
            _fail(str(error))
        except TransportError as error:
            _fail(str(error))
        _render(report)
        raise typer.Exit(EXIT_OK if report.succeeded else EXIT_SERVICE_FAILED)

    return app


def _fail(message: str) -> NoReturn:
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(EXIT_UNUSABLE)


def _password(from_stdin: bool, connection: Connection) -> Password:
    """`--password-stdin`, then the Environment's password, then a prompt."""
    if from_stdin:
        line = sys.stdin.readline().rstrip("\r\n")
        if not line:
            _fail("--password-stdin was given but stdin has no password")
        return Password(line)
    if connection.password is not None:
        return connection.password.value
    return Password(typer.prompt("Password", hide_input=True))


def _connection(
    store: ConfigStore,
    config: str | None,
    env: str | None,
    url: str | None,
    username: str | None,
    insecure: bool,
) -> Connection:
    try:
        return resolve_connection(
            load_config(store, config),
            env=env,
            url=url,
            username=username,
            insecure=insecure,
            environ=os.environ,
        )
    except ConfigError as error:
        _fail(str(error))


def _add_config_commands(group: typer.Typer, store: ConfigStore) -> None:
    @group.command("path", help="Print the path of the configuration file.")
    def config_path(config: _ConfigOption = None) -> None:
        typer.echo(config or store.default_path())

    @group.command(
        "check",
        help="Validate every Environment in the configuration file, offline.",
    )
    def config_check(config: _ConfigOption = None) -> None:
        try:
            loaded = load_config(store, config)
            report = check_config(loaded)
        except ConfigError as error:
            _fail(str(error))
        if not loaded.found:
            typer.echo(f"no configuration file at {loaded.path}")
        for name in report.environments:
            typer.echo(f"environments.{name}: ok")
        for warning in report.warnings:
            typer.echo(f"warning: {warning}", err=True)

    @group.command(
        "show",
        help="Show the effective configuration and where each value comes from.",
    )
    def config_show(
        config: _ConfigOption = None,
        env: _EnvOption = None,
        url: Annotated[
            str | None, typer.Option("--url", help="The Service endpoint.")
        ] = None,
        username: _UsernameOption = None,
        insecure: _InsecureOption = False,
    ) -> None:
        try:
            loaded = load_config(store, config)
            connection = resolve_connection(
                loaded,
                env=env,
                url=url,
                username=username,
                insecure=insecure,
                environ=os.environ,
            )
        except ConfigError as error:
            _fail(str(error))
        state = "found" if loaded.found else "not found"
        typer.echo(f"config file = {loaded.path} ({state})")
        for line in _show_lines(connection):
            typer.echo(line)


def _show_lines(connection: Connection) -> list[str]:
    lines: list[str] = []

    def add(name: str, value: str, source: str) -> None:
        lines.append(f"{name} = {value} ({source})")

    if connection.environment:
        add("environment", connection.environment.value, connection.environment.source)
    else:
        lines.append("environment = none")
    for name, address in (("url", connection.url), ("wsdl", connection.wsdl)):
        if address:
            add(name, _without_userinfo(address.value), address.source)
    if connection.username:
        add("username", connection.username.value, connection.username.source)
    if connection.password:
        add("password", "***", connection.password.source)
    for name, flag in (
        ("insecure", connection.insecure),
        ("trust_host", connection.trust_host),
        ("protected", connection.protected),
    ):
        add(name, str(flag.value).lower(), flag.source)
    quirks = ", ".join(f'"{quirk}"' for quirk in connection.quirks.value)
    add("quirks", f"[{quirks}]", connection.quirks.source)
    return lines


def _without_userinfo(address: str) -> str:
    """Hide credentials embedded in an address."""
    parts = urlsplit(address)
    if "@" not in parts.netloc:
        return address
    host = parts.netloc.rsplit("@", 1)[1]
    return parts._replace(netloc=f"***@{host}").geturl()


def _render(report: LogonReport) -> None:
    """Results go to stdout; Observations and findings go to stderr."""
    for step in report.steps:
        typer.echo(_line(step))
    for observation in report.observations:
        typer.echo(f"observation {observation.id}: {observation.message}", err=True)
    for step in report.steps:
        reply = step.reply
        for violation in reply.schema_violations:
            typer.echo(
                f"schema violation in {step.operation} (line {violation.line}): "
                f"{violation.message}",
                err=True,
            )
        if isinstance(reply, Deviation):
            ref = reply.spec_reference
            typer.echo(
                f"{step.operation} contradicts DODP v1 section {ref.section}, "
                f"{ref.title} ({ref.url})",
                err=True,
            )


def _line(step: Step) -> str:
    reply = step.reply
    if isinstance(reply, Ok):
        return f"{step.operation}: {'failed' if reply.value is False else 'ok'}"
    if isinstance(reply, Fault):
        reason = f": {reply.reason}" if reply.reason else ""
        return f"{step.operation}: fault {reply.kind}{reason}"
    return f"{step.operation}: deviation: {reply.description}"
