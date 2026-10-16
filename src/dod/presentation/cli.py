"""The `dod` command line: command groups arranged in help panels."""

import sys
from typing import Annotated, Any

import typer

from dod.application import (
    EndpointError,
    LogonReport,
    OpenPort,
    Step,
    logon_ephemeral,
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


def create_app(open_port: OpenPort) -> typer.Typer:
    """Build the `dod` command line application.

    `open_port` is how commands reach a Service; the composition root supplies
    it, because presentation never imports the infrastructure layer.
    """
    app = typer.Typer(
        name="dod",
        help="Test client for DODP v1 Services.",
        no_args_is_help=True,
        add_completion=False,
        rich_markup_mode="rich",
    )
    for name, help_text, panel in _GROUPS:
        group = typer.Typer(no_args_is_help=True)
        app.add_typer(group, name=name, help=help_text, rich_help_panel=panel)

    @app.command(
        rich_help_panel=SESSION_AND_SETUP,
        help=(
            "Run the initialisation sequence against a Service and log off again "
            "(ephemeral mode: nothing is stored)."
        ),
    )
    def logon(
        url: Annotated[
            str,
            typer.Option(
                "--url",
                help="The Service endpoint, e.g. https://dod.example.org/service.",
            ),
        ],
        username: Annotated[
            str, typer.Option("--username", help="The user to log on as.")
        ],
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
                help="Read the password from stdin instead of prompting.",
            ),
        ] = False,
        insecure: Annotated[
            bool,
            typer.Option(
                "--insecure",
                help="Allow an unencrypted http address, also on loopback.",
            ),
        ] = False,
    ) -> None:
        if not no_session:
            _fail("stored Sessions are not available yet; pass --no-session")
        password = _read_password(password_stdin)
        try:
            report = logon_ephemeral(
                open_port, url, username, password, insecure=insecure
            )
        except EndpointError as error:
            _fail(str(error))
        except TransportError as error:
            _fail(str(error))
        _render(report)
        raise typer.Exit(EXIT_OK if report.succeeded else EXIT_SERVICE_FAILED)

    return app


def _fail(message: str) -> Any:
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(EXIT_UNUSABLE)


def _read_password(from_stdin: bool) -> Password:
    if from_stdin:
        line = sys.stdin.readline().rstrip("\r\n")
        if not line:
            _fail("--password-stdin was given but stdin has no password")
        return Password(line)
    return Password(typer.prompt("Password", hide_input=True))


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
