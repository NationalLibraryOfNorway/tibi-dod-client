"""The `dod` command line: command groups arranged in help panels."""

import dataclasses
import json
import os
import re
import shlex
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from dod.application import (
    CONFORMANCE_TESTS,
    AudioError,
    Baseline,
    BaselineError,
    BookError,
    ConfigError,
    ConfigStore,
    Connection,
    CredentialProvider,
    Discovery,
    DocumentValidator,
    DownloadReport,
    DownloadRequest,
    Endpoint,
    EndpointError,
    Fetcher,
    FileOutcome,
    InitialisationFailed,
    LocalCopy,
    LogonReport,
    MarkOutcome,
    MarkReport,
    MemorySessionStore,
    NoCredentialsError,
    OpenPlayer,
    OpenPort,
    OpenQuirkPort,
    OpenRawChannel,
    PlayerUnavailable,
    PlayRefused,
    ReadingSystemError,
    ReadingSystemParser,
    ReturnReport,
    ReturnRequest,
    SessionManager,
    SessionStore,
    Step,
    WsdlParser,
    book_directory,
    check_config,
    check_endpoint,
    compare,
    default_reading_system,
    discover,
    download,
    list_quirks,
    load_config,
    logon_ephemeral,
    mark_read,
    open_book,
    origin,
    prepare_playback,
    resolve_connection,
    resolve_endpoint,
    return_content,
    run_conformance,
    select,
    write_baseline,
)
from dod.domain.service import (
    Deviation,
    Fault,
    Observation,
    Ok,
    Password,
    Reply,
    TransportError,
)
from dod.domain.v1 import (
    Announcement,
    BookmarkSet,
    ContentList,
    ContentMetadata,
    ContentResources,
    InputQuestion,
    KeyExchangeObject,
    MultipleChoiceQuestion,
    Questions,
    ReadingSystemAttributes,
    ServicePort,
    UserResponse,
)
from dod.presentation._conformance import (
    ReportExchanges,
    json_report,
    list_json,
    text_report,
)
from dod.presentation._diagnostics import Diagnostics
from dod.presentation._globals import (
    GlobalOptions,
    GlobalOptionsFirst,
    OutputFormat,
    Terminal,
)
from dod.presentation._masking import MaskPolicy, mask, mask_keys, mask_url
from dod.presentation._play import piped_commands, run_playback, terminal_commands
from dod.presentation._quirks import quirk_lines, quirks_json

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


_QUESTIONS_HELP = (
    "Navigate the Service's dynamic menus (getQuestions). Without a "
    "subcommand this sends the reserved answer `default` and shows the "
    "root question. Every call is one step: the Service answers with "
    "questions, each shown with the `answer <questionID> <value>` "
    "arguments of its choices so that they can be copied into the next "
    "command, or with an endpoint, a contentListRef to follow with "
    "`dod list --id <ref>` or a label. Nothing in dod depends on one "
    "backend's question IDs, and dod keeps no position in the menus. "
    "The commands can always be called; whether the Service has menus "
    "is in `dod attributes service` (DYNAMIC_MENUS). Questions that "
    "need an input type dod does not declare (AUDIO) are shown but "
    "cannot be answered."
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
    session_store: SessionStore | None = None,
    parse_reading_system: ReadingSystemParser | None = None,
    open_raw: OpenRawChannel | None = None,
    open_quirky: OpenQuirkPort | None = None,
    data_dir: Path | None = None,
    validate_bookmarks: DocumentValidator | None = None,
    open_player: OpenPlayer | None = None,
) -> typer.Typer:
    """Build the `dod` command line application.

    `open_port` is how commands reach a Service, `config_store` where the
    configuration file lives, and `fetcher` and `parse_wsdl` how a WSDL is
    fetched and read; the composition root supplies them, because presentation
    never imports the infrastructure layer. `terminal` answers whether stderr
    and stdin are terminals (the real ones by default), and `session_store` is
    where Session files live (in memory, so lost at exit, by default).
    `parse_reading_system` reads a Reading System declaration file, and
    `open_raw` opens the raw channel the negative tests send through, and
    `open_quirky` opens a port that may use the named Quirks (ADR 0010), and
    `data_dir` is where downloaded books go (`--output` needs no data directory),
    and `validate_bookmarks` checks a bookmark set file against the local schema,
    and `open_player` opens the audio player `dod play` uses (it may raise
    `PlayerUnavailable`).
    """
    terminal = terminal or _SystemTerminal()
    store = session_store or MemorySessionStore()
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
        groups[name] = typer.Typer(no_args_is_help=name != "questions")
        app.add_typer(
            groups[name],
            name=name,
            help=_QUESTIONS_HELP if name == "questions" else help_text,
            short_help=help_text,
            rich_help_panel=panel,
        )
    _add_config_commands(groups["config"], config_store)
    _add_quirks_commands(groups["quirks"], config_store)

    def ports(connection: Connection, *, quirks: bool = True) -> OpenPort:
        """Ports for the Environment, with its Quirks unless `quirks` is false."""
        names = frozenset(connection.quirks.value) if quirks else frozenset()
        if not names:
            return open_port
        if open_quirky is None:
            _fail("Quirks are not available here")
        opener = open_quirky
        return lambda url: opener(url, names)

    def diagnostics(ctx: typer.Context) -> Diagnostics:
        return _start_diagnostics(ctx, _globals(ctx), terminal)

    def network_target(ctx: typer.Context, g: GlobalOptions) -> _Target:
        diag = diagnostics(ctx)
        connection = _connection(config_store, g)
        try:
            endpoint = resolve_endpoint(connection, fetcher, parse_wsdl)
        except EndpointError as error:
            _fail(str(error))
        if endpoint is None:
            _fail(_NO_ADDRESS)
        _banner(connection, endpoint.url, g.quiet)
        diag.observe(_host_boundary(endpoint))
        try:
            check_endpoint(endpoint.url, insecure=connection.insecure.value)
        except EndpointError as error:
            _fail(str(error))
        return _Target(diag, connection, endpoint.url, _username(connection))

    def manager_for(
        target: _Target,
        reading_system: ReadingSystemAttributes | None = None,
        credentials: CredentialProvider | None = None,
    ) -> SessionManager:
        return SessionManager(
            target.diag.wrap(ports(target.connection)),
            store,
            target.url,
            target.username,
            credentials,
            reading_system=reading_system,
        )

    def declaration(
        connection: Connection, file: str | None = None
    ) -> ReadingSystemAttributes | None:
        """The declared Reading System: `--file`, then the Environment's key."""
        path = file or (
            connection.reading_system.value if connection.reading_system else None
        )
        if path is None:
            return None
        if parse_reading_system is None:
            _fail("reading a Reading System declaration is not available here")
        try:
            content = Path(path).read_bytes()
        except OSError as error:
            _fail(f"{path}: cannot be read: {error.strerror or error}")
        try:
            return parse_reading_system(content)
        except ReadingSystemError as error:
            _fail(f"{path}: {error}")

    def service_manager(
        g: GlobalOptions,
        target: _Target,
        reading_system: ReadingSystemAttributes | None,
    ) -> SessionManager:
        """The manager an ordinary command calls the Service through (ADR 0005)."""
        credentials = _credentials(g, target.connection, prompt=g.no_session)
        wrapped = target.diag.wrap(ports(target.connection))
        if g.no_session:
            return SessionManager.ephemeral(
                wrapped,
                target.url,
                target.username,
                credentials,
                reading_system=reading_system,
            )
        return manager_for(target, reading_system, credentials)

    def serve[T](
        g: GlobalOptions,
        target: _Target,
        manager: SessionManager,
        operation: Callable[[ServicePort], Reply[T]],
    ) -> Reply[T]:
        """Run one Service call through the manager; a failure to get a Session
        or no answer at all ends the command."""
        return guarded(g, target, lambda: manager.call(operation))

    def guarded[R](g: GlobalOptions, target: _Target, run: Callable[[], R]) -> R:
        try:
            return run()
        except TransportError as error:
            _fail(_no_answer(error, target.url))
        except NoCredentialsError as error:
            _fail(str(error))
        except InitialisationFailed as error:
            _render(error.report, g.format, target.diag)
            raise typer.Exit(EXIT_SERVICE_FAILED) from None

    @app.command(
        rich_help_panel=SESSION_AND_SETUP,
        epilog=_EPILOG,
        help=(
            "Log on: end a stored Session, run the initialisation sequence and "
            "store the new Session for later commands. With --no-session it runs "
            "the sequence and logs off again, storing nothing."
        ),
    )
    def logon(ctx: typer.Context) -> None:
        g = _globals(ctx)
        target = network_target(ctx, g)
        reading_system = declaration(target.connection)
        password = _password(g.password_stdin, target.connection)
        try:
            if g.no_session:
                report = logon_ephemeral(
                    target.diag.wrap(ports(target.connection)),
                    target.url,
                    target.username,
                    password,
                    insecure=target.connection.insecure.value,
                    reading_system=reading_system,
                )
            else:
                report = manager_for(target, reading_system).logon(password)
        except EndpointError as error:
            _fail(str(error))
        except TransportError as error:
            _fail(_no_answer(error, target.url))
        _render(report, g.format, target.diag)
        raise typer.Exit(EXIT_OK if report.succeeded else EXIT_SERVICE_FAILED)

    @app.command(
        rich_help_panel=SESSION_AND_SETUP,
        epilog=_EPILOG,
        help=(
            "Call logOff for the stored Session and delete the Session file "
            "whatever the Service answers (a failure is only a warning)."
        ),
    )
    def logoff(ctx: typer.Context) -> None:
        g = _globals(ctx)
        _text_only(g, "logoff")
        if g.no_session:
            _fail("--no-session has no stored Session to end")
        target = network_target(ctx, g)
        result = manager_for(target).logoff()
        if result.warning:
            typer.echo(f"warning: {result.warning}", err=True)
        typer.echo("logged off" if result.had_session else "no stored Session")

    @app.command(
        "status",
        rich_help_panel=SESSION_AND_SETUP,
        epilog=_EPILOG,
        help=(
            "Show the Environment, the user and whether the Session is stored "
            "or ephemeral. Local: nothing is sent to the Service."
        ),
    )
    def status_command(ctx: typer.Context) -> None:
        g = _globals(ctx)
        _no_xml(g, "status")
        connection, url = _local_target(config_store, g)
        _banner(connection, url, g.quiet)
        manager = _local_manager(open_port, store, connection, url)
        if g.no_session:
            state = "ephemeral"
        else:
            state = "stored" if manager and manager.stored() else "none"
        _show(
            g,
            {
                "environment": connection.environment.value
                if connection.environment
                else "-",
                "url": mask_url(url),
                "username": connection.username.value if connection.username else "-",
                "session": state,
            },
        )

    @groups["session"].command(
        "status",
        epilog=_EPILOG,
        help=(
            "Show whether a Session is stored for the Service and user. Local by "
            "default; --check asks the Service with one reading call (exit 1 when "
            "the Session has expired)."
        ),
    )
    def session_status(
        ctx: typer.Context,
        check: Annotated[
            bool,
            typer.Option(
                "--check",
                help="Ask the Service with getServiceAttributes whether the "
                "stored Session is still active.",
            ),
        ] = False,
    ) -> None:
        g = _globals(ctx)
        _no_xml(g, "session status")
        diag = diagnostics(ctx)
        connection, url = _local_target(config_store, g)
        _banner(connection, url, g.quiet)
        if check:
            try:
                check_endpoint(url, insecure=connection.insecure.value)
            except EndpointError as error:
                _fail(str(error))
        manager = _local_manager(diag.wrap(ports(connection)), store, connection, url)
        stored = manager is not None and manager.stored()
        values = {"session": "stored" if stored else "none"}
        expired = False
        if check and manager is not None and stored:
            try:
                active = manager.probe()
            except TransportError as error:
                _fail(_no_answer(error, url))
            expired = active is False
            values["service"] = "expired" if expired else "active"
        _show(g, values)
        raise typer.Exit(EXIT_SERVICE_FAILED if expired else EXIT_OK)

    @groups["session"].command(
        "clear",
        epilog=_EPILOG,
        help="Delete the stored Session file without contacting the Service.",
    )
    def session_clear(ctx: typer.Context) -> None:
        g = _globals(ctx)
        _text_only(g, "session clear")
        connection, url = _local_target(config_store, g)
        _banner(connection, url, g.quiet)
        manager = _local_manager(open_port, store, connection, url)
        if manager is None:
            _fail(_NO_USERNAME)
        manager.clear()
        typer.echo("stored Session deleted")

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

    @groups["attributes"].command(
        "service",
        epilog=_EPILOG,
        help=(
            "Show what the Service supports (getServiceAttributes), as the "
            "Service answered."
        ),
    )
    def attributes_service(ctx: typer.Context) -> None:
        g = _globals(ctx)
        target = network_target(ctx, g)
        manager = service_manager(g, target, declaration(target.connection))
        reply = serve(g, target, manager, lambda port: port.get_service_attributes())
        _present(
            g,
            target.diag,
            "getServiceAttributes",
            reply,
            lambda value: _field_lines(value),
            lambda value: dataclasses.asdict(value),
        )

    @groups["attributes"].command(
        "reading-system",
        epilog=_EPILOG,
        help=(
            "Declare the Reading System (setReadingSystemAttributes) and show "
            "the answer. Declares DAISY 2.02 and EPUB 3, audio/mpeg and "
            "audio/wav and text and numeric input unless --file or the "
            "Environment's reading_system gives another XML document."
        ),
    )
    def attributes_reading_system(
        ctx: typer.Context,
        file: Annotated[
            str | None,
            typer.Option(
                "--file",
                help="A readingSystemAttributes XML document to send instead of "
                "the default declaration.",
            ),
        ] = None,
    ) -> None:
        g = _globals(ctx)
        target = network_target(ctx, g)
        sent = declaration(target.connection, file) or default_reading_system()
        manager = service_manager(g, target, sent)
        reply = serve(
            g, target, manager, lambda port: port.set_reading_system_attributes(sent)
        )
        _present(
            g,
            target.diag,
            "setReadingSystemAttributes",
            reply,
            lambda value: _field_lines(sent),
            lambda value: {"declared": dataclasses.asdict(sent)},
        )

    @groups["announcements"].command(
        "list",
        epilog=_EPILOG,
        help=(
            "Show the announcements the Service has for you that you have not "
            "read yet (getServiceAnnouncements). Nothing is marked as read."
        ),
    )
    def announcements_list(ctx: typer.Context) -> None:
        g = _globals(ctx)
        target = network_target(ctx, g)
        manager = service_manager(g, target, declaration(target.connection))
        reply = serve(g, target, manager, lambda port: port.get_service_announcements())
        _present(
            g,
            target.diag,
            "getServiceAnnouncements",
            reply,
            _announcement_lines,
            lambda value: {"announcements": [_announcement_json(a) for a in value]},
            header=False,
        )

    @groups["announcements"].command(
        "mark-read",
        epilog=_EPILOG,
        help=(
            "Mark announcements as read (markAnnouncementsAsRead). Give "
            "identifiers, or --all for every announcement of the latest fetch. "
            "The announcements are fetched first, as the specification requires. "
            "If the Service rejects the set with invalidParameter, they are "
            "tried one at a time. false from the Service means already read."
        ),
    )
    def announcements_mark_read(
        ctx: typer.Context,
        ids: Annotated[
            list[str] | None,
            typer.Argument(help="Identifiers of the announcements to mark."),
        ] = None,
        all_: Annotated[
            bool,
            typer.Option("--all", help="Mark every announcement of the latest fetch."),
        ] = False,
    ) -> None:
        g = _globals(ctx)
        _no_xml(g, "announcements mark-read")
        if bool(ids) == all_:
            _fail("give announcement identifiers, or --all, but not both")
        target = network_target(ctx, g)
        manager = service_manager(g, target, declaration(target.connection))
        try:
            report = mark_read(manager, None if all_ else ids)
        except TransportError as error:
            _fail(_no_answer(error, target.url))
        except NoCredentialsError as error:
            _fail(str(error))
        except InitialisationFailed as error:
            _render(error.report, g.format, target.diag)
            raise typer.Exit(EXIT_SERVICE_FAILED) from None
        if not isinstance(report.fetched, Ok):
            _present(
                g,
                target.diag,
                "getServiceAnnouncements",
                report.fetched,
                lambda value: [],
                lambda value: {},
            )
        _render_marks(g, target.diag, report)

    @app.command(
        "list",
        rich_help_panel=BROWSE_AND_ISSUE,
        epilog=_EPILOG,
        help=(
            "Show a content list (getContentList). Without --id that is the "
            "shelf, `issued`. Other lists are `new`, `expired`, the dynamic "
            "lists of a menu and a contentListRef from a menu; quote an id that "
            "has spaces. --first and --last pick a segment, counted from 0; "
            "--last -1 means to the end."
        ),
    )
    def list_content(
        ctx: typer.Context,
        id: Annotated[
            str,
            typer.Option("--id", help="The list to show (default: issued)."),
        ] = "issued",
        first: Annotated[
            int, typer.Option("--first", help="Index of the first item.")
        ] = 0,
        last: Annotated[
            int,
            typer.Option("--last", help="Index of the last item; -1 is the end."),
        ] = -1,
    ) -> None:
        g = _globals(ctx)
        target = network_target(ctx, g)
        manager = service_manager(g, target, declaration(target.connection))
        reply = serve(
            g, target, manager, lambda port: port.get_content_list(id, first, last)
        )
        _present(
            g,
            target.diag,
            "getContentList",
            reply,
            _content_list_lines,
            lambda value: {"list": dataclasses.asdict(value)},
            header=False,
        )

    @app.command(
        rich_help_panel=BROWSE_AND_ISSUE,
        epilog=_EPILOG,
        help=(
            "Show the metadata of any book, issued or not (getContentMetadata). "
            "Quote an id that has spaces."
        ),
    )
    def metadata(
        ctx: typer.Context,
        id: Annotated[str, typer.Argument(help="The identifier of the book.")],
    ) -> None:
        g = _globals(ctx)
        target = network_target(ctx, g)
        manager = service_manager(g, target, declaration(target.connection))
        reply = serve(g, target, manager, lambda port: port.get_content_metadata(id))
        _present(
            g,
            target.diag,
            "getContentMetadata",
            reply,
            _metadata_lines,
            lambda value: {"metadata": _metadata_json(value)},
            header=False,
        )

    def ask(ctx: typer.Context, response: UserResponse) -> None:
        """One step in the menus: send one answer and show the Service's reply."""
        g = _globals(ctx)
        target = network_target(ctx, g)
        attributes = declaration(target.connection) or default_reading_system()
        manager = service_manager(g, target, attributes)
        reply = serve(g, target, manager, lambda port: port.get_questions([response]))
        supported = frozenset(attributes.config.supported_input_types)
        _present(
            g,
            target.diag,
            "getQuestions",
            reply,
            lambda value: _questions_lines(value, supported),
            lambda value: {"questions": _questions_json(value, supported)},
            header=False,
        )

    @groups["questions"].callback(invoke_without_command=True, epilog=_EPILOG)
    def questions_root(ctx: typer.Context) -> None:
        if ctx.invoked_subcommand is None:
            ask(ctx, UserResponse("default"))

    @groups["questions"].command(
        "answer",
        epilog=_EPILOG,
        help=(
            "Answer one question (getQuestions with one answer): QUESTION_ID and "
            "VALUE are sent as given, so copy them from the previous output. "
            "Quote a value that has spaces. One answer per call; multiple "
            "selections are not supported."
        ),
    )
    def questions_answer(
        ctx: typer.Context,
        question_id: Annotated[
            str, typer.Argument(metavar="QUESTION_ID", help="The question to answer.")
        ],
        value: Annotated[
            str, typer.Argument(metavar="VALUE", help="The choice id or the text.")
        ],
    ) -> None:
        ask(ctx, UserResponse(question_id, value))

    @groups["questions"].command(
        "search",
        epilog=_EPILOG,
        help=(
            "Send the reserved answer `search`, with TEXT as the value when "
            "given (getQuestions). The Service shows its search question or "
            "the result."
        ),
    )
    def questions_search(
        ctx: typer.Context,
        text: Annotated[
            str | None,
            typer.Argument(metavar="[TEXT]", help="What to search for."),
        ] = None,
    ) -> None:
        ask(ctx, UserResponse("search", text))

    @groups["questions"].command(
        "back",
        epilog=_EPILOG,
        help=(
            "Send the reserved answer `back` (getQuestions) and show the "
            "Service's reply unchanged. Some Services do not support it and "
            "answer with a fault or an error, which is shown as it came."
        ),
    )
    def questions_back(ctx: typer.Context) -> None:
        ask(ctx, UserResponse("back"))

    @groups["bookmarks"].command(
        "get",
        epilog=_EPILOG,
        help=(
            "Show the bookmark set of a book (getBookmarks) as the Service "
            "sent it: the bookmarkSet element, with the title, uid, lastmark, "
            "bookmarks and highlights. The command can always be called; "
            "whether the Service supports it is in `dod attributes service` "
            "(GET_BOOKMARKS). Quote an id that has spaces."
        ),
    )
    def bookmarks_get(
        ctx: typer.Context,
        id: Annotated[str, typer.Argument(help="The identifier of the book.")],
    ) -> None:
        g = _globals(ctx)
        target = network_target(ctx, g)
        manager = service_manager(g, target, declaration(target.connection))
        reply = serve(g, target, manager, lambda port: port.get_bookmarks(id))
        _present(
            g,
            target.diag,
            "getBookmarks",
            reply,
            _bookmark_set_lines,
            lambda value: {"bookmark_set": dataclasses.asdict(value)},
            header=False,
        )

    @groups["bookmarks"].command(
        "set",
        epilog=_EPILOG,
        help=(
            "Store a bookmark set (setBookmarks) read from --file, a bookmarkSet "
            "XML document. The file is checked against the local bookmark "
            "schema first and refused, with nothing sent, if it does not "
            "conform; otherwise it is sent as it is. WARNING: setBookmarks "
            "replaces the whole set (title, lastmark, bookmarks and "
            "highlights), so read the current set first with `dod bookmarks "
            "get`, change that and send it back. The uid should be the "
            "identifier of the book, or some Services refuse the set. The "
            "command can always be called; whether the Service supports it is "
            "in `dod attributes service` (SET_BOOKMARKS)."
        ),
    )
    def bookmarks_set(
        ctx: typer.Context,
        id: Annotated[str, typer.Argument(help="The identifier of the book.")],
        file: Annotated[
            str,
            typer.Option("--file", help="A bookmarkSet XML document (at most 1 MiB)."),
        ],
    ) -> None:
        g = _globals(ctx)
        if validate_bookmarks is None:
            _fail("checking a bookmark set file is not available here")
        document = _read_bookmark_file(file, validate_bookmarks)
        target = network_target(ctx, g)
        manager = service_manager(g, target, declaration(target.connection))
        reply = serve(g, target, manager, lambda port: port.set_bookmarks(id, document))
        _present(g, target.diag, "setBookmarks", reply, lambda v: [], lambda v: {})

    @app.command(
        "key-exchange",
        rich_help_panel=DOWNLOAD_AND_PLAY,
        epilog=_EPILOG,
        help=(
            "Call getKeyExchangeObject for the key NAME, which asks the Service "
            "for a PDTB2 Key Exchange Object. It is rarely used: only Services "
            "that deliver PDTB2-protected content (PDTB2_KEY_PROVISION) answer "
            "it. dod does not interpret the key and does not support DRM; the "
            "answer is shown as it came, except that key material is masked "
            "(ADR 0007). Without support the Service answers with a fault, "
            "which is shown as it came."
        ),
    )
    def key_exchange(
        ctx: typer.Context,
        name: Annotated[
            str, typer.Argument(help="The name of the key to ask for (NAME).")
        ],
    ) -> None:
        g = _globals(ctx)
        target = network_target(ctx, g)
        manager = service_manager(g, target, declaration(target.connection))
        reply = serve(
            g, target, manager, lambda port: port.get_key_exchange_object(name)
        )
        _present(
            g,
            target.diag,
            "getKeyExchangeObject",
            reply,
            _key_exchange_lines,
            lambda value: {"key_exchange": {"xml": mask_keys(value.xml)}},
            header=False,
        )

    @app.command(
        rich_help_panel=DOWNLOAD_AND_PLAY,
        epilog=_EPILOG,
        help=(
            "Borrow a book: issueContent, shown as the Service answered. Only "
            "issued books can be listed with `dod resources` and fetched with "
            "`dod download`, which never issue anything themselves. Quote an id "
            "that has spaces."
        ),
    )
    def issue(
        ctx: typer.Context,
        id: Annotated[str, typer.Argument(help="The identifier of the book.")],
    ) -> None:
        g = _globals(ctx)
        target = network_target(ctx, g)
        manager = service_manager(g, target, declaration(target.connection))
        reply = serve(g, target, manager, lambda port: port.issue_content(id))
        _present(g, target.diag, "issueContent", reply, lambda value: [], lambda v: {})

    @app.command(
        "return",
        rich_help_panel=DOWNLOAD_AND_PLAY,
        epilog=_EPILOG,
        help=(
            "Give a book back: delete the local copy, then returnContent. The "
            "specification requires the copy to be deleted first; only "
            "<data>/<environment>/books/<id>/ is ever deleted (DOD_DATA_DIR sets "
            "<data>), after a confirmation unless --yes. A book whose metadata "
            "says requiresReturn is false is refused unless --force. "
            "--keep-local returns without deleting, which breaks the "
            "specification, and is the only way to return without an "
            "Environment. A result of false is a deviation; returning twice "
            "should answer true both times."
        ),
    )
    def return_command(
        ctx: typer.Context,
        id: Annotated[str, typer.Argument(help="The identifier of the book.")],
        yes: Annotated[
            bool,
            typer.Option("--yes", help="Delete the local copy without asking."),
        ] = False,
        force: Annotated[
            bool,
            typer.Option(
                "--force",
                help="Call returnContent although requiresReturn is false.",
            ),
        ] = False,
        keep_local: Annotated[
            bool,
            typer.Option(
                "--keep-local",
                help="Return without deleting the local copy (breaks the "
                "specification).",
            ),
        ] = False,
    ) -> None:
        g = _globals(ctx)
        _no_xml(g, "return")
        if not id:
            _fail("the book identifier is empty")
        if yes and keep_local:
            _fail("--yes and --keep-local contradict each other")
        connection = _connection(config_store, g)
        directory: Path | None = None
        if not keep_local:
            if connection.environment is None:
                _fail(
                    "there is no Environment to locate the local copy: select "
                    "one with --env, or pass --keep-local"
                )
            if data_dir is None:
                _fail("there is no data directory: pass --keep-local")
            directory = book_directory(data_dir, connection.environment.value, id)

        def confirm(path: Path) -> bool:
            if yes:
                return True
            try:
                return typer.confirm(f"Delete the local copy {path}?", err=True)
            except typer.Abort:
                return False

        target = network_target(ctx, g)
        manager = service_manager(g, target, declaration(target.connection))
        if keep_local:
            typer.echo(
                "warning: --keep-local leaves the local copy in place, which the "
                "specification forbids when content is returned",
                err=True,
            )
        request = ReturnRequest(
            content_id=id, directory=directory, keep_local=keep_local, force=force
        )
        report = guarded(g, target, lambda: return_content(manager, request, confirm))
        _render_return(g, target.diag, report, directory)

    @app.command(
        rich_help_panel=DOWNLOAD_AND_PLAY,
        epilog=_EPILOG,
        help=(
            "List the files of an issued book (getContentResources) as the "
            "Service gave them; nothing is downloaded. Quote an id that has "
            "spaces."
        ),
    )
    def resources(
        ctx: typer.Context,
        id: Annotated[str, typer.Argument(help="The identifier of the book.")],
    ) -> None:
        g = _globals(ctx)
        target = network_target(ctx, g)
        manager = service_manager(g, target, declaration(target.connection))
        reply = serve(g, target, manager, lambda port: port.get_content_resources(id))
        _present(
            g,
            target.diag,
            "getContentResources",
            reply,
            _resources_lines,
            lambda value: {"resources": _resources_json(value)},
            header=False,
        )

    @app.command(
        "download",
        rich_help_panel=DOWNLOAD_AND_PLAY,
        epilog=_EPILOG,
        help=(
            "Download the files of an issued book: getContentResources, then one "
            "HTTP GET per file, one after the other. It never issues the book "
            "itself (run `dod issue` first); a book that is not issued gives the "
            "Service's invalidParameter fault as it came. The files go to "
            "<data>/<environment>/books/<id>/ (DOD_DATA_DIR sets <data>), or to "
            "--output; --output is required without an Environment. Every "
            "localURI is checked before anything is fetched, and one that is "
            "absolute, has `..` or backslashes or a drive letter, or leaves the "
            "directory, aborts with nothing written. A file is written as "
            ".part and renamed only when its size is the announced one. Existing "
            "files are not overwritten without --force. Addresses on another "
            "host than the Service need --trust-host; the Session cookie and the "
            "password are never sent there."
        ),
    )
    def download_command(
        ctx: typer.Context,
        id: Annotated[str, typer.Argument(help="The identifier of the book.")],
        file: Annotated[
            list[str] | None,
            typer.Option(
                "--file",
                help="Fetch only this localURI (as `dod resources` shows it). "
                "May be repeated.",
            ),
        ] = None,
        output: Annotated[
            Path | None,
            typer.Option(
                "--output",
                help="The directory to put the files in, instead of the default.",
            ),
        ] = None,
        force: Annotated[
            bool, typer.Option("--force", help="Overwrite files that already exist.")
        ] = False,
    ) -> None:
        g = _globals(ctx)
        _no_xml(g, "download")
        if not id:
            _fail("the book identifier is empty")
        connection = _connection(config_store, g)
        directory = output
        if directory is None:
            if connection.environment is None:
                _fail(
                    "there is no Environment to name the target directory: "
                    "pass --output"
                )
            if data_dir is None:
                _fail("there is no data directory: pass --output")
            directory = book_directory(data_dir, connection.environment.value, id)
        target = network_target(ctx, g)
        manager = service_manager(g, target, declaration(target.connection))
        request = DownloadRequest(
            content_id=id,
            directory=directory,
            service_url=target.url,
            files=tuple(file or ()),
            force=force,
            trust_host=target.connection.trust_host.value,
            insecure=target.connection.insecure.value,
        )
        report = guarded(g, target, lambda: download(manager, request))
        _render_download(g, target.diag, report, directory)

    @app.command(
        "play",
        rich_help_panel=DOWNLOAD_AND_PLAY,
        epilog=_EPILOG,
        help=(
            "Play a downloaded DAISY 2.02 or EPUB 3 book from the files on disk; "
            "nothing is fetched or streamed. The order comes from master.smil, "
            "else from the SMIL files ncc.html first links to (DAISY 2.02), or "
            "from the spine and the media overlays of its items (EPUB 3), and "
            "never from file names. It "
            "needs the optional `miniaudio` (`pip install 'dod-client[play]'`; "
            "WAV, FLAC, MP3 and Ogg Vorbis, not AAC) and exits 2 without it. A "
            "book without SMIL (audioOnly) or an EPUB without media overlays "
            "(text only) is refused with an explanation. The book is read from "
            "<data>/<environment>/books/<id>/ (DOD_DATA_DIR sets <data>), or from "
            "--directory. While playing, type a command and Enter: p "
            "pause/resume, n next clip, b previous clip, f forward 30 s, r back "
            "30 s, q stop; the display shows the file's place in the book "
            "(`file 3 of 7`) and the elapsed Playlist time."
        ),
    )
    def play_command(
        ctx: typer.Context,
        id: Annotated[str, typer.Argument(help="The identifier of the book.")],
        directory: Annotated[
            Path | None,
            typer.Option(
                "--directory",
                help="The directory the book is in, instead of the default.",
            ),
        ] = None,
    ) -> None:
        g = _globals(ctx)
        if g.format is not OutputFormat.TEXT:
            _fail("dod play has text output only; --format is text")
        if not id:
            _fail("the book identifier is empty")
        diag = diagnostics(ctx)
        connection = _connection(config_store, g)
        book = directory
        if book is None:
            if connection.environment is None:
                _fail(
                    "there is no Environment to locate the book: select one with "
                    "--env, or pass --directory"
                )
            if data_dir is None:
                _fail("there is no data directory: pass --directory")
            book = book_directory(data_dir, connection.environment.value, id)
        if open_player is None:
            _fail("audio playback is not available here")
        try:
            player = open_player()
        except PlayerUnavailable as error:
            _fail(str(error))
        try:
            playback = prepare_playback(book, open_book(book), player)
            playback.start()
            run_playback(
                playback,
                terminal_commands() if terminal.stdin_is_tty() else piped_commands(),
                _plain,
            )
        except PlayRefused as error:
            diag.observe(error.observations)
            _fail(_plain(str(error)))
        except BookError as error:
            _fail(_plain(str(error)))
        except AudioError as error:
            _fail(_plain(f"playback failed: {error}"))
        except KeyboardInterrupt:
            pass
        finally:
            player.stop()
            player.close()

    @groups["test"].command(
        "list",
        epilog=_EPILOG,
        help=(
            "List the ids of the Conformance tests, one per line, including "
            "the explicit ones (negative.*) that a run only includes when "
            "--only names them. Nothing is sent to a Service. --only and "
            "--skip narrow the list."
        ),
    )
    def test_list(
        ctx: typer.Context,
        only: _ONLY = None,
        skip: _SKIP = None,
    ) -> None:
        g = _globals(ctx)
        _no_xml(g, "test list")
        tests = _selected(only, skip, include_explicit=True)
        if g.format is OutputFormat.JSON:
            typer.echo(json.dumps(list_json(tests), indent=2))
        else:
            for chosen in tests:
                typer.echo(chosen.id)

    @groups["test"].command(
        "run",
        epilog=_EPILOG,
        help=(
            "Run Conformance tests against a Service and report one Outcome "
            "(PASS, FAIL, SKIP or ERROR) per test. The run logs on with a "
            "Session of its own and never uses a stored one. Exit code 0 "
            "without FAIL or ERROR, 1 with FAIL only, 2 with any ERROR. "
            "--format json gives a versioned report with masked Exchanges. "
            "The negative tests (deliberately invalid requests, each in a "
            "Session of its own) run only when chosen: --only negative. "
            "--baseline compares the run with a file of known FAILs (new FAIL "
            "exits 1, ERROR still exits 2) and --write-baseline writes one; "
            "Outcomes in the report do not change. The content tests "
            "(issue, resources, fetch, Range) are State-changing and run only "
            "with --state-changing and an explicit --content-id; they return "
            "what they issued and read at most 64 KiB of a resource. The optional "
            "operations (bookmarks, key exchange) are tested only as far as "
            "`supportedOptionalOperations` says the Service has them; the "
            "bookmark round trip is State-changing too, and writes back the "
            "set it read."
        ),
    )
    def test_run(
        ctx: typer.Context,
        only: _ONLY = None,
        skip: _SKIP = None,
        state_changing: Annotated[
            bool,
            typer.Option(
                "--state-changing",
                help="Also run the State-changing tests, which alter data on the "
                "Service. A protected Environment needs --confirm-env as well.",
            ),
        ] = False,
        confirm_env: Annotated[
            str | None,
            typer.Option(
                "--confirm-env",
                help="The name of a protected Environment, to confirm that "
                "State-changing tests may run against it.",
            ),
        ] = None,
        content_id: Annotated[
            str | None,
            typer.Option(
                "--content-id",
                help="The content item the content tests may issue and return, and "
                "the bookmark round trip may read and write back (never chosen "
                "automatically). Without it they are SKIP.",
            ),
        ] = None,
        unissued_content_id: Annotated[
            str | None,
            typer.Option(
                "--unissued-content-id",
                help="Content that is not issued, for the test that "
                "getContentResources on it is invalidParameter. Without it that "
                "test is SKIP.",
            ),
        ] = None,
        report_exchanges: Annotated[
            ReportExchanges,
            typer.Option(
                "--report-exchanges",
                help="Which Exchanges the JSON report includes, masked: all, "
                "failures (FAIL and ERROR tests) or none.",
            ),
        ] = ReportExchanges.FAILURES,
        baseline_path: Annotated[
            Path | None,
            typer.Option(
                "--baseline",
                help="A Baseline file of known FAILs (kept in the Service's own "
                "repository). A FAIL not in it is new and exits 1; an entry that "
                "now passes is reported as resolved. ERROR still exits 2.",
            ),
        ] = None,
        fail_on_resolved: Annotated[
            bool,
            typer.Option(
                "--fail-on-resolved",
                help="With --baseline: exit 1 when a baseline entry now passes, "
                "so the file is kept up to date.",
            ),
        ] = False,
        write_baseline_path: Annotated[
            Path | None,
            typer.Option(
                "--write-baseline",
                help="Write a Baseline from this run's FAILs: test ids and a "
                "short reason, no addresses or credentials.",
            ),
        ] = None,
        with_quirks: Annotated[
            bool,
            typer.Option(
                "--with-quirks",
                help="Let the Environment's Quirks apply during the run. Without "
                "it they are ignored, so a tolerated deviation stays a FAIL; the "
                "report says which Quirks were on (ADR 0010).",
            ),
        ] = False,
    ) -> None:
        g = _globals(ctx)
        _no_xml(g, "test run")
        _selected(only, skip)
        baseline = _read_baseline(baseline_path)
        if fail_on_resolved and baseline is None:
            _fail("--fail-on-resolved needs --baseline")
        target = network_target(ctx, g)
        name = target.connection.environment
        if (
            state_changing
            and target.connection.protected.value
            and (name is None or confirm_env != name.value)
        ):
            _fail(
                f"the Environment {name.value if name else '-'} is protected; "
                "State-changing tests need "
                f"--confirm-env {name.value if name else '<name>'}"
            )
        password = _password(g.password_stdin, target.connection)
        try:
            report = run_conformance(
                target.diag.wrap(ports(target.connection, quirks=with_quirks)),
                target.url,
                target.username,
                password,
                open_raw=None if open_raw is None else target.diag.wrap_raw(open_raw),
                only=only or (),
                skip=skip or (),
                state_changing=state_changing,
                insecure=target.connection.insecure.value,
                reading_system=declaration(target.connection),
                trust_host=target.connection.trust_host.value,
                content_id=content_id,
                unissued_content_id=unissued_content_id,
            )
        except EndpointError as error:
            _fail(str(error))
        quirks_on = target.connection.quirks.value if with_quirks else ()
        comparison = None if baseline is None else compare(report, baseline)
        code = (
            report.exit_code
            if comparison is None
            else comparison.exit_code(report, fail_on_resolved=fail_on_resolved)
        )
        if baseline is not None:
            stale = baseline.unknown_ids({t.id for t in CONFORMANCE_TESTS.tests})
            for identifier in stale:
                typer.echo(
                    f"warning: the baseline names {identifier}, which is not a "
                    "known test id",
                    err=True,
                )
        if g.format is OutputFormat.JSON:
            document = json_report(
                report,
                url=target.url,
                environment=name.value if name else None,
                exchanges=report_exchanges,
                baseline=comparison,
                exit_code=code,
                quirks=quirks_on,
            )
            typer.echo(json.dumps(document, indent=2))
        else:
            for line in text_report(
                report,
                hyperlinks=sys.stdout.isatty(),
                baseline=comparison,
                quirks=quirks_on,
            ):
                typer.echo(line)
        if write_baseline_path is not None and report.setup_error is None:
            try:
                write_baseline_path.write_text(
                    write_baseline(report, baseline), encoding="utf-8"
                )
            except OSError as error:
                _fail(f"{write_baseline_path}: cannot be written: {error.strerror}")
        raise typer.Exit(code)

    return app


_ONLY = Annotated[
    list[str] | None,
    typer.Option(
        "--only",
        help="Only tests whose id starts with this prefix (whole dotted "
        "segments, e.g. session.logon). Can be repeated. Explicit tests, such "
        "as negative, run only when named here.",
    ),
]
_SKIP = Annotated[
    list[str] | None,
    typer.Option(
        "--skip",
        help="Leave out tests whose id starts with this prefix. Can be repeated.",
    ),
]


def _read_baseline(path: Path | None) -> Baseline | None:
    if path is None:
        return None
    try:
        return Baseline.parse(path.read_text(encoding="utf-8"))
    except OSError as error:
        _fail(f"{path}: cannot be read: {error.strerror or error}")
    except (UnicodeDecodeError, BaselineError) as error:
        _fail(f"{path}: not a valid baseline: {error}")


def _selected(
    only: list[str] | None, skip: list[str] | None, *, include_explicit: bool = False
) -> tuple[Any, ...]:
    try:
        return select(
            CONFORMANCE_TESTS, only or (), skip or (), include_explicit=include_explicit
        )
    except ValueError as error:
        _fail(str(error))


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


def _banner(connection: Connection, url: str, quiet: bool) -> None:
    if quiet:
        return
    name = connection.environment.value if connection.environment else "-"
    typer.echo(f"[{name}] {mask_url(url)}", err=True)


_NO_ADDRESS = (
    "no Service address: pass --url, --wsdl or --env, or set "
    "default_environment in the configuration file"
)
_NO_USERNAME = (
    "no username: pass --username, set DOD_USERNAME or give the Environment a username"
)


@dataclass(frozen=True)
class _Target:
    """What a command that talks to the Service needs: where, as whom."""

    diag: Diagnostics
    connection: Connection
    url: str
    username: str


def _username(connection: Connection) -> str:
    if connection.username is None:
        _fail(_NO_USERNAME)
    return connection.username.value


def _local_target(store: ConfigStore, g: GlobalOptions) -> tuple[Connection, str]:
    """The Service URL of a command that sends nothing, so no WSDL is fetched."""
    connection = _connection(store, g)
    if connection.url is None:
        if connection.wsdl is not None:
            _fail(
                "this command does not fetch the WSDL; pass the endpoint with "
                "--url or give the Environment a url"
            )
        _fail(_NO_ADDRESS)
    return connection, connection.url.value


def _local_manager(
    open_port: OpenPort, store: SessionStore, connection: Connection, url: str
) -> SessionManager | None:
    if connection.username is None:
        return None
    return SessionManager(open_port, store, url, connection.username.value, None)


def _no_xml(g: GlobalOptions, command: str) -> None:
    if g.format is OutputFormat.XML:
        _fail(f"dod {command} has no xml output; --format is text or json")


def _show(g: GlobalOptions, values: dict[str, str]) -> None:
    if g.format is OutputFormat.JSON:
        typer.echo(json.dumps(values, indent=2))
    else:
        for name, value in values.items():
            typer.echo(f"{name}: {value}")


def _no_answer(error: TransportError, url: str) -> str:
    return (
        f"{error}\nIf {mask_url(url)} is not the SOAP endpoint, try: "
        f"dod discover {mask_url(url)}"
    )


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


def _announcement_lines(announcements: tuple[Announcement, ...]) -> list[str]:
    if not announcements:
        return ["no unread announcements"]
    return [
        f"announcement {_plain(a.id)} [{_plain(a.type)}, priority {a.priority}]: "
        f"{_plain(a.text)}"
        for a in announcements
    ]


def _announcement_json(announcement: Announcement) -> dict[str, Any]:
    return dataclasses.asdict(announcement)


def _content_list_lines(shown: ContentList) -> list[str]:
    name = _plain(shown.id)
    if not shown.items:
        return [f"list {name}: no items ({shown.total_items} in total)"]
    first = shown.first_item if shown.first_item is not None else 0
    last = (
        shown.last_item if shown.last_item is not None else first + len(shown.items) - 1
    )
    return [
        f"list {name}: items {first}-{last} of {shown.total_items}",
        *(f"{_plain(item.id)}: {_plain(item.label)}" for item in shown.items),
    ]


def _metadata_lines(book: ContentMetadata) -> list[str]:
    lines = _field_lines(dataclasses.replace(book, meta=()))
    pairs = ", ".join(f"{_plain(n)}={_plain(c)}" for n, c in book.meta)
    return [*lines, f"meta: {pairs or '-'}"]


def _metadata_json(book: ContentMetadata) -> dict[str, Any]:
    document = dataclasses.asdict(book)
    document["meta"] = [{"name": n, "content": c} for n, c in book.meta]
    return document


def _resources_lines(shown: ContentResources) -> list[str]:
    lines = [f"resources: {len(shown.resources)}"]
    if shown.return_by is not None:
        lines.append(f"returnBy: {_plain(shown.return_by)}")
    for number, item in enumerate(shown.resources, start=1):
        lines += [
            f"resource {number}:",
            f"  uri: {_plain(mask_url(item.uri))}",
            f"  localURI: {_plain(item.local_uri)}",
            f"  size: {'-' if item.size is None else item.size}",
            f"  mimeType: {_plain(item.mime_type)}",
            f"  lastModifiedDate: {_plain(item.last_modified or '-')}",
        ]
    return lines


def _resources_json(shown: ContentResources) -> dict[str, Any]:
    document = dataclasses.asdict(shown)
    for item in document["resources"]:
        item["uri"] = mask_url(item["uri"])
    return document


_MAX_BOOKMARK_FILE = 1024 * 1024


def _read_bookmark_file(path: str, validate: DocumentValidator) -> str:
    """The text of a bookmark set file that conforms; otherwise the command
    ends with exit code 2 and nothing is sent."""
    try:
        with open(path, "rb") as handle:
            data = handle.read(_MAX_BOOKMARK_FILE + 1)
    except OSError as error:
        _fail(f"{path}: cannot be read: {error.strerror or error}")
    if len(data) > _MAX_BOOKMARK_FILE:
        _fail(f"{path}: is larger than 1 MiB")
    findings = validate(data)
    if findings:
        shown = "\n".join(
            f"{path}: line {f.line}: {_plain(f.message)}" for f in findings[:10]
        )
        _fail(f"the file does not conform to the bookmark schema:\n{shown}")
    return data.decode("utf-8")


def _xml_lines(xml: str) -> list[str]:
    return [_plain(line) for line in xml.splitlines()]


def _bookmark_set_lines(shown: BookmarkSet) -> list[str]:
    return _xml_lines(shown.xml)


def _key_exchange_lines(shown: KeyExchangeObject) -> list[str]:
    return _xml_lines(mask_keys(shown.xml))


def _questions_lines(shown: Questions, supported: frozenset[str]) -> list[str]:
    """Questions and choices as the arguments of the next command (ADR 0008:
    everything from the Service is made plain, and quoted where it has spaces)."""
    lines: list[str] = []
    for question in shown.questions:
        qid = shlex.quote(_plain(question.id))
        if isinstance(question, MultipleChoiceQuestion):
            lines.append(f"question {_plain(question.id)}: {_plain(question.label)}")
            for choice in question.choices:
                lines.append(
                    f"  answer {qid} {shlex.quote(_plain(choice.id))}"
                    f"    # {_plain(choice.label)}"
                )
        else:
            types = ", ".join(_plain(t) for t in question.input_types)
            head = f"input question {_plain(question.id)}: {_plain(question.label)}"
            if _answerable(question, supported):
                lines.append(f"{head} [{types}]")
                lines.append(f"  answer {qid} <text>")
            else:
                lines.append(
                    f"{head} [{types}] (cannot be answered: dod does not "
                    "declare any of these input types)"
                )
    if shown.content_list_ref is not None:
        ref = _plain(shown.content_list_ref)
        lines.append(f"contentListRef: {ref}    # dod list --id {shlex.quote(ref)}")
    if shown.label is not None:
        lines.append(f"label: {_plain(shown.label)}")
    return lines


def _answerable(question: InputQuestion, supported: frozenset[str]) -> bool:
    return any(kind in supported for kind in question.input_types)


def _questions_json(shown: Questions, supported: frozenset[str]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for question in shown.questions:
        if isinstance(question, MultipleChoiceQuestion):
            items.append(
                {
                    "type": "multiple-choice",
                    "id": question.id,
                    "label": question.label,
                    "lang": question.lang,
                    "allow_multiple_selections": question.allow_multiple_selections,
                    "choices": [dataclasses.asdict(c) for c in question.choices],
                    "answerable": True,
                }
            )
        else:
            items.append(
                {
                    "type": "input",
                    "id": question.id,
                    "label": question.label,
                    "lang": question.lang,
                    "input_types": list(question.input_types),
                    "answerable": _answerable(question, supported),
                }
            )
    return {
        "questions": items,
        "content_list_ref": shown.content_list_ref,
        "label": shown.label,
    }


def _problem_text(problem: Reply[int] | str) -> str:
    if isinstance(problem, str):
        return problem
    if isinstance(problem, Deviation):
        return problem.description
    return _line(Step("fetch", problem)).split(": ", 1)[1]


def _render_download(
    g: GlobalOptions, diag: Diagnostics, report: DownloadReport, directory: Path
) -> None:
    """Results go to stdout; refusals, Observations and findings go to stderr."""
    step = Step("getContentResources", report.resources)
    diag.observe(report.observations)
    if report.refusal is not None:
        _fail(_plain(report.refusal))
    if report.deviation is not None:
        step = Step("getContentResources", report.deviation)
    if report.succeeded:
        result = "ok"
    elif report.files:
        result = "failed"
    else:
        result = _line(step).split(": ", 1)[1]
    if g.format is OutputFormat.JSON:
        document: dict[str, Any] = {
            "result": result,
            "directory": str(directory),
            "files": [
                {
                    "local_uri": item.local_uri,
                    "path": str(item.path),
                    "outcome": item.outcome.value,
                    "bytes": item.size,
                    "problem": None
                    if item.problem is None
                    else _problem_text(item.problem),
                }
                for item in report.files
            ],
        }
        typer.echo(json.dumps(document, indent=2))
    else:
        if not isinstance(report.resources, Ok) or report.deviation is not None:
            typer.echo(_line(step))
        for item in report.files:
            name = _plain(item.local_uri)
            if item.outcome is FileOutcome.DOWNLOADED:
                typer.echo(f"downloaded {name} ({item.size} bytes)")
            else:
                reason = _plain(_problem_text(item.problem or "unknown"))
                typer.echo(f"failed {name}: {reason}")
        if report.succeeded:
            count = len(report.files)
            typer.echo(f"{count} file{'s' if count != 1 else ''} in {directory}")
    _diagnose(diag, step)
    for item in report.files:
        if isinstance(item.problem, Deviation):
            _diagnose(diag, Step("fetch_resource", item.problem))
    raise typer.Exit(EXIT_OK if report.succeeded else EXIT_SERVICE_FAILED)


def _render_return(
    g: GlobalOptions, diag: Diagnostics, report: ReturnReport, directory: Path | None
) -> None:
    """The Service's answers go to stdout; refusals and findings to stderr."""
    if report.refusal is not None:
        _fail(_plain(report.refusal))
    if report.returned is not None:
        step = Step("returnContent", report.returned)
    else:
        assert report.metadata is not None
        step = Step("getContentMetadata", report.metadata)
    result = _line(step).split(": ", 1)[1]
    local = report.local_copy
    if g.format is OutputFormat.JSON:
        document: dict[str, Any] = {"result": result}
        if local is not None:
            document["local_copy"] = local.value
            document["directory"] = None if directory is None else str(directory)
        typer.echo(json.dumps(document, indent=2))
    else:
        if local is LocalCopy.DELETED:
            typer.echo(f"local copy: deleted {directory}")
        elif local is not None:
            typer.echo(f"local copy: {local.value}")
        typer.echo(_line(step))
    _diagnose(diag, step)
    raise typer.Exit(EXIT_OK if step.succeeded else EXIT_SERVICE_FAILED)


def _render_marks(g: GlobalOptions, diag: Diagnostics, report: MarkReport) -> None:
    """One line per identifier; the Service's faults are shown as they came."""
    shown: list[tuple[str, str]] = []
    for result in report.results:
        if result.outcome is MarkOutcome.FAILED:
            failed = Step("markAnnouncementsAsRead", result.reply)
            text = _line(failed).split(": ", 1)[1]
        else:
            text = result.outcome.value
        shown.append((_plain(result.id), text))
        _diagnose(diag, Step("markAnnouncementsAsRead", result.reply))
    if g.format is OutputFormat.JSON:
        document = [{"id": name, "result": text} for name, text in shown]
        typer.echo(json.dumps({"results": document}, indent=2))
    else:
        for name, text in shown:
            typer.echo(f"{name}: {text}")
        if not shown:
            typer.echo("no unread announcements")
    raise typer.Exit(EXIT_OK if report.succeeded else EXIT_SERVICE_FAILED)


def _credentials(
    g: GlobalOptions, connection: Connection, *, prompt: bool
) -> CredentialProvider:
    """Where a login gets its password: stdin, the Environment, else a prompt.

    The prompt is only for ephemeral mode; a stored Session that has expired
    and has no credentials asks for `dod logon` instead. The password is read
    once per run.
    """
    given: list[Password | None] = []

    def provide() -> Password | None:
        if not given:
            if g.password_stdin or connection.password is not None or prompt:
                given.append(_password(g.password_stdin, connection))
            else:
                given.append(None)
        return given[0]

    return provide


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _plain(text: str) -> str:
    """Text from a Service is untrusted: control characters never reach the
    terminal (ADR 0008)."""
    return _CONTROL.sub(" ", text)


def _field_lines(value: Any, prefix: str = "") -> list[str]:
    """`name: value` for every field of a model, nested ones with a prefix."""
    lines: list[str] = []
    for field in dataclasses.fields(value):
        item = getattr(value, field.name)
        if dataclasses.is_dataclass(item):
            lines += _field_lines(item, f"{prefix}{field.name}.")
            continue
        if isinstance(item, bool):
            shown = str(item).lower()
        elif isinstance(item, tuple):
            shown = ", ".join(_plain(str(part)) for part in item) or "-"
        else:
            shown = "-" if item is None else _plain(str(item))
        lines.append(f"{prefix}{field.name}: {shown}")
    return lines


def _present[T](
    g: GlobalOptions,
    diag: Diagnostics,
    operation: str,
    reply: Reply[T],
    lines: Callable[[T], list[str]],
    document: Callable[[T], dict[str, Any]],
    *,
    header: bool = True,
) -> None:
    """Show one Reply as received and end the command (exit 1 unless it is Ok).

    Results go to stdout; Observations and findings go to stderr.
    """
    step = Step(operation, reply)
    if g.format is OutputFormat.XML:
        typer.echo(mask(reply.exchange).response_body)
    elif g.format is OutputFormat.JSON:
        result = {"result": _line(step).split(": ", 1)[1]}
        body = document(reply.value) if isinstance(reply, Ok) else {}
        typer.echo(json.dumps(result | body, indent=2))
    else:
        if header or not isinstance(reply, Ok):
            typer.echo(_line(step))
        if isinstance(reply, Ok) and reply.value is not False:
            for line in lines(reply.value):
                typer.echo(line)
    _diagnose(diag, step)
    raise typer.Exit(EXIT_OK if step.succeeded else EXIT_SERVICE_FAILED)


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


def _add_quirks_commands(group: typer.Typer, store: ConfigStore) -> None:
    @group.command(
        "list",
        epilog=_EPILOG,
        help=(
            "List every known Quirk: its name, what it tolerates, the Spec "
            "reference and the Environments that enable it. --env shows only "
            "the Quirks that Environment enables. Quirks are off by default "
            "(ADR 0010). Local: nothing is sent to a Service."
        ),
    )
    def quirks_list(ctx: typer.Context) -> None:
        g = _globals(ctx)
        _no_xml(g, "quirks list")
        try:
            uses = list_quirks(load_config(store, g.config), g.env)
        except ConfigError as error:
            _fail(str(error))
        if g.format is OutputFormat.JSON:
            typer.echo(json.dumps(quirks_json(uses), indent=2))
        else:
            for line in quirk_lines(uses):
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
    if connection.reading_system:
        reading = connection.reading_system
        add("reading_system", reading.value, reading.source)
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
            if (
                isinstance(step.reply, Ok)
                and step.operation == "getServiceAnnouncements"
            ):
                for line in _announcement_lines(step.reply.value):
                    typer.echo(line)
    diag.observe(report.observations)
    for step in report.steps:
        _diagnose(diag, step, observe=False)


def _diagnose(diag: Diagnostics, step: Step, *, observe: bool = True) -> None:
    """Schema violations and Spec deviations of one answer, on stderr."""
    reply = step.reply
    if observe:
        diag.observe(reply.observations)
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
    document: dict[str, Any] = {
        "succeeded": report.succeeded,
        "steps": [
            {"operation": step.operation, "result": _line(step).split(": ", 1)[1]}
            for step in report.steps
        ],
    }
    for step in report.steps:
        if isinstance(step.reply, Ok) and step.operation == "getServiceAnnouncements":
            document["announcements"] = [
                _announcement_json(a) for a in step.reply.value
            ]
    return document


def _line(step: Step) -> str:
    reply = step.reply
    if isinstance(reply, Ok):
        return f"{step.operation}: {'failed' if reply.value is False else 'ok'}"
    if isinstance(reply, Fault):
        reason = f": {reply.reason}" if reply.reason else ""
        return f"{step.operation}: fault {reply.kind}{reason}"
    return f"{step.operation}: deviation: {reply.description}"
