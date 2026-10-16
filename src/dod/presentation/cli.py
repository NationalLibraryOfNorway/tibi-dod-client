"""The `dod` command line: command groups arranged in help panels."""

import json
import os
import sys
from typing import Annotated, Any, NoReturn

import typer

from dod.application import (
    ConfigError,
    ConfigStore,
    Connection,
    Discovery,
    Endpoint,
    EndpointError,
    Fetcher,
    LogonReport,
    OpenPort,
    Step,
    WsdlParser,
    check_config,
    discover,
    load_config,
    logon_ephemeral,
    origin,
    resolve_connection,
    resolve_endpoint,
)
from dod.domain.service import (
    Deviation,
    Fault,
    Observation,
    Ok,
    Password,
    TransportError,
)
from dod.presentation._diagnostics import Diagnostics
from dod.presentation._globals import (
    GlobalOptions,
    GlobalOptionsFirst,
    OutputFormat,
    Terminal,
)
from dod.presentation._masking import MaskPolicy, mask_url

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


_EPILOG = (
    "Global options such as --url, --config and --format are listed in "
    "`dod --help` and work here too."
)
_GLOBAL = "Global options (accepted before or after the command)"


def _option(*names: str, help: str, envvar: str | None = None) -> Any:
    return typer.Option(*names, help=help, envvar=envvar, rich_help_panel=_GLOBAL)


class _SystemTerminal:
    def stderr_is_tty(self) -> bool:
        return sys.stderr.isatty()

    def stdin_is_tty(self) -> bool:
        return sys.stdin.isatty()


def create_app(
    open_port: OpenPort,
    config_store: ConfigStore,
    fetcher: Fetcher,
    parse_wsdl: WsdlParser,
    terminal: Terminal | None = None,
) -> typer.Typer:
    """Build the `dod` command line application.

    `open_port` is how commands reach a Service, `config_store` where the
    configuration file lives, and `fetcher` and `parse_wsdl` how a WSDL is
    fetched and read; the composition root supplies them, because presentation
    never imports the infrastructure layer. `terminal` answers whether stderr
    and stdin are terminals (the real ones by default).
    """
    terminal = terminal or _SystemTerminal()
    app = typer.Typer(
        name="dod",
        help="Test client for DODP v1 Services.",
        no_args_is_help=True,
        add_completion=False,
        rich_markup_mode="rich",
        cls=GlobalOptionsFirst,
    )

    @app.callback()
    def global_options(
        ctx: typer.Context,
        env: Annotated[
            str | None,
            _option("--env", help="The named Environment to use (also DOD_ENV)."),
        ] = None,
        url: Annotated[
            str | None,
            _option(
                "--url",
                help="The SOAP endpoint itself, e.g. https://dod.example.org/service.",
            ),
        ] = None,
        wsdl: Annotated[
            str | None,
            _option(
                "--wsdl",
                help="The Service's WSDL; its soap:address is the endpoint. Fetched "
                "without credentials.",
            ),
        ] = None,
        username: Annotated[
            str | None,
            _option(
                "--username",
                help="The user to log on as (also DOD_USERNAME, else the "
                "Environment's).",
            ),
        ] = None,
        config: Annotated[
            str | None,
            _option(
                "--config",
                envvar="DOD_CONFIG",
                help="The configuration file (default: in the platform's config "
                "directory).",
            ),
        ] = None,
        format: Annotated[
            OutputFormat,
            _option(
                "--format",
                help="text (default), json, or xml: the raw, masked response. "
                "Commands without that output refuse json and xml.",
            ),
        ] = OutputFormat.TEXT,
        debug: Annotated[
            bool,
            _option(
                "--debug",
                help="Write every Exchange as a readable block on stderr, masked.",
            ),
        ] = False,
        save_exchanges: Annotated[
            str | None,
            _option(
                "--save-exchanges",
                help="Write request, response and a small JSON per Exchange to "
                "this directory, masked.",
            ),
        ] = None,
        quiet: Annotated[
            bool,
            _option("--quiet", help="Do not print the environment and endpoint line."),
        ] = False,
        no_session: Annotated[
            bool,
            _option(
                "--no-session",
                envvar="DOD_NO_SESSION",
                help="Use a Session of its own that is never stored.",
            ),
        ] = False,
        insecure: Annotated[
            bool,
            _option(
                "--insecure",
                help="Allow an unencrypted http address, also on loopback.",
            ),
        ] = False,
        trust_host: Annotated[
            bool,
            _option(
                "--trust-host",
                help="Accept a WSDL whose soap:address has another host, port or "
                "scheme.",
            ),
        ] = False,
        unmask: Annotated[
            bool,
            _option(
                "--unmask",
                help="Show cookies and headers unmasked in --debug. Only on a "
                "terminal, never with --save-exchanges (ADR 0007).",
            ),
        ] = False,
        unmask_password: Annotated[
            bool,
            _option(
                "--unmask-password",
                help="Also show the password in --debug, after an interactive "
                "confirmation. Same restrictions as --unmask.",
            ),
        ] = False,
        password_stdin: Annotated[
            bool,
            _option(
                "--password-stdin",
                help="Read the password from stdin instead of the file or a prompt.",
            ),
        ] = False,
    ) -> None:
        ctx.obj = GlobalOptions(
            env=env,
            url=url,
            wsdl=wsdl,
            username=username,
            config=config,
            format=format,
            debug=debug,
            save_exchanges=save_exchanges,
            quiet=quiet,
            no_session=no_session,
            insecure=insecure,
            trust_host=trust_host,
            unmask=unmask,
            unmask_password=unmask_password,
            password_stdin=password_stdin,
        )

    groups: dict[str, typer.Typer] = {}
    for name, help_text, panel in _GROUPS:
        groups[name] = typer.Typer(no_args_is_help=True)
        app.add_typer(groups[name], name=name, help=help_text, rich_help_panel=panel)
    _add_config_commands(groups["config"], config_store)

    def diagnostics(ctx: typer.Context) -> Diagnostics:
        return _start_diagnostics(ctx, _globals(ctx), terminal)

    @app.command(
        rich_help_panel=SESSION_AND_SETUP,
        epilog=_EPILOG,
        help=(
            "Run the initialisation sequence against a Service and log off again "
            "(ephemeral mode: nothing is stored; --no-session is required)."
        ),
    )
    def logon(ctx: typer.Context) -> None:
        g = _globals(ctx)
        if not g.no_session:
            _fail("stored Sessions are not available yet; pass --no-session")
        diag = diagnostics(ctx)
        connection = _connection(config_store, g)
        try:
            endpoint = resolve_endpoint(connection, fetcher, parse_wsdl)
        except EndpointError as error:
            _fail(str(error))
        if endpoint is None:
            _fail(
                "no Service address: pass --url, --wsdl or --env, or set "
                "default_environment in the configuration file"
            )
        _banner(connection, endpoint, g.quiet)
        diag.observe(_host_boundary(endpoint))
        if connection.username is None:
            _fail(
                "no username: pass --username, set DOD_USERNAME or give the "
                "Environment a username"
            )
        password = _password(g.password_stdin, connection)
        try:
            report = logon_ephemeral(
                diag.wrap(open_port),
                endpoint.url,
                connection.username.value,
                password,
                insecure=connection.insecure.value,
            )
        except EndpointError as error:
            _fail(str(error))
        except TransportError as error:
            _fail(
                f"{error}\nIf {mask_url(endpoint.url)} is not the SOAP "
                f"endpoint, try: dod discover {mask_url(endpoint.url)}"
            )
        _render(report, g.format, diag)
        raise typer.Exit(EXIT_OK if report.succeeded else EXIT_SERVICE_FAILED)

    @app.command(
        "discover",
        rich_help_panel=SESSION_AND_SETUP,
        epilog=_EPILOG,
        help=(
            "Look for the SOAP endpoint of a Service: try ?wsdl and known paths. "
            "Sends no credentials and stores nothing."
        ),
    )
    def discover_command(
        ctx: typer.Context,
        address: Annotated[
            str,
            typer.Argument(help="Address of the Service, e.g. https://dod.example.org"),
        ],
    ) -> None:
        g = _globals(ctx)
        _text_only(g, "discover")
        if not g.quiet:
            typer.echo(f"[-] {mask_url(address)}", err=True)
        try:
            discovery = discover(address, fetcher, parse_wsdl, insecure=g.insecure)
        except EndpointError as error:
            _fail(str(error))
        _render_discovery(discovery, address)

    return app


def _globals(ctx: typer.Context) -> GlobalOptions:
    obj = ctx.find_root().obj
    assert isinstance(obj, GlobalOptions)
    return obj


def _text_only(g: GlobalOptions, command: str) -> None:
    if g.format is not OutputFormat.TEXT:
        _fail(f"dod {command} has no {g.format.value} output; --format is text only")


def _start_diagnostics(
    ctx: typer.Context, g: GlobalOptions, terminal: Terminal
) -> Diagnostics:
    """Apply the unmask rules (ADR 0007), then build the run's diagnostics."""
    unmasking = g.unmask or g.unmask_password
    if unmasking:
        flags = "--unmask-password" if g.unmask_password else "--unmask"
        if g.save_exchanges is not None:
            _fail(
                f"{flags} cannot be combined with --save-exchanges (files are masked)"
            )
        if not terminal.stderr_is_tty():
            _fail(f"{flags} needs a terminal on stderr")
        if not g.debug:
            _fail(f"{flags} only affects --debug output; add --debug")
        if g.unmask_password:
            if g.password_stdin or not terminal.stdin_is_tty():
                _fail("--unmask-password needs an interactive terminal on stdin")
            typer.echo(
                "warning: the password will be shown in clear text on this terminal.",
                err=True,
            )
            if not typer.confirm("Show the password?", err=True):
                _fail("--unmask-password was not confirmed")
        typer.echo(
            "warning: unmasked secrets follow on stderr (highlighted when the "
            "terminal has colour). Do not paste them into tickets, chats or AI tools.",
            err=True,
        )
        ctx.call_on_close(
            lambda: typer.echo(
                "warning: unmasked secrets were shown above; clear the terminal if "
                "the screen is shared or recorded.",
                err=True,
            )
        )
    return Diagnostics(
        debug=g.debug,
        save_to=g.save_exchanges,
        policy=MaskPolicy(unmask=g.unmask, unmask_password=g.unmask_password),
        colour=unmasking and "NO_COLOR" not in os.environ,
    )


def _host_boundary(endpoint: Endpoint) -> tuple[Observation, ...]:
    if endpoint.wsdl is None or origin(endpoint.wsdl) == origin(endpoint.url):
        return ()
    return (
        Observation(
            id="host-boundary",
            message=(
                f"the WSDL at {mask_url(endpoint.wsdl)} names the endpoint "
                f"{mask_url(endpoint.url)}, which has another host, port or scheme; "
                "accepted because of --trust-host"
            ),
        ),
    )


def _banner(connection: Connection, endpoint: Endpoint, quiet: bool) -> None:
    if quiet:
        return
    name = connection.environment.value if connection.environment else "-"
    typer.echo(f"[{name}] {mask_url(endpoint.url)}", err=True)


def _render_discovery(discovery: Discovery, address: str) -> None:
    for attempt in discovery.attempts:
        typer.echo(f"tried {attempt.url}: {attempt.outcome}", err=True)
    found = discovery.found
    if found is None or found.port is None:
        _fail(
            f"no DODP endpoint found at {mask_url(address)}.\n"
            "Next steps: pass the SOAP endpoint with --url, give the address of "
            "the WSDL with --wsdl, or ask the Service's owner for the endpoint."
        )
    endpoint = found.port.address
    typer.echo(f"endpoint: {endpoint}")
    typer.echo(f"wsdl: {found.url}")
    if origin(found.url) != origin(endpoint):
        typer.echo(
            "note: the WSDL names another host, port or scheme than it came from; "
            f"using it needs --trust-host (or: --url {endpoint})",
            err=True,
        )
    else:
        typer.echo(f"use it with: --wsdl {found.url}  or  --url {endpoint}", err=True)


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


def _connection(store: ConfigStore, g: GlobalOptions) -> Connection:
    try:
        return resolve_connection(
            load_config(store, g.config),
            env=g.env,
            url=g.url,
            wsdl=g.wsdl,
            username=g.username,
            insecure=g.insecure,
            trust_host=g.trust_host,
            environ=os.environ,
        )
    except ConfigError as error:
        _fail(str(error))


def _add_config_commands(group: typer.Typer, store: ConfigStore) -> None:
    @group.command(
        "path", epilog=_EPILOG, help="Print the path of the configuration file."
    )
    def config_path(ctx: typer.Context) -> None:
        g = _globals(ctx)
        _text_only(g, "config path")
        typer.echo(g.config or store.default_path())

    @group.command(
        "check",
        epilog=_EPILOG,
        help="Validate every Environment in the configuration file, offline.",
    )
    def config_check(ctx: typer.Context) -> None:
        g = _globals(ctx)
        _text_only(g, "config check")
        try:
            loaded = load_config(store, g.config)
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
        epilog=_EPILOG,
        help="Show the effective configuration and where each value comes from.",
    )
    def config_show(ctx: typer.Context) -> None:
        g = _globals(ctx)
        _text_only(g, "config show")
        try:
            loaded = load_config(store, g.config)
            connection = resolve_connection(
                loaded,
                env=g.env,
                url=g.url,
                wsdl=g.wsdl,
                username=g.username,
                insecure=g.insecure,
                trust_host=g.trust_host,
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
            add(name, mask_url(address.value), address.source)
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


def _render(report: LogonReport, output: OutputFormat, diag: Diagnostics) -> None:
    """Results go to stdout; Observations and findings go to stderr."""
    if output is OutputFormat.JSON:
        typer.echo(json.dumps(_logon_json(report), indent=2))
    elif output is OutputFormat.XML:
        for exchange in diag.masked_exchanges:
            typer.echo(exchange.response_body)
    else:
        for step in report.steps:
            typer.echo(_line(step))
    diag.observe(report.observations)
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


def _logon_json(report: LogonReport) -> dict[str, Any]:
    return {
        "succeeded": report.succeeded,
        "steps": [
            {"operation": step.operation, "result": _line(step).split(": ", 1)[1]}
            for step in report.steps
        ],
    }


def _line(step: Step) -> str:
    reply = step.reply
    if isinstance(reply, Ok):
        return f"{step.operation}: {'failed' if reply.value is False else 'ok'}"
    if isinstance(reply, Fault):
        reason = f": {reply.reason}" if reply.reason else ""
        return f"{step.operation}: fault {reply.kind}{reason}"
    return f"{step.operation}: deviation: {reply.description}"
