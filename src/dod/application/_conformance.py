"""The conformance runner: registry, test context and the run itself.

A Conformance test is a function `(ctx) -> Result` registered under a stable,
hierarchical id. The runner owns everything around it: the setup (a Session of
its own, never the session manager's, ADR 0005), `--only` and `--skip`
selection, the opt-in for State-changing tests and turning what happens into an
Outcome. A fault is classified on its DODP element, never on HTTP status or
`faultstring`; that already happened in the port, so the runner only sees
`Ok`, `Fault` and `Deviation` values and `TransportError`.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import NoReturn

from dod.application._address import check_endpoint
from dod.application._logon import OpenPort, default_reading_system, initialise
from dod.domain.service import (
    Deviation,
    Exchange,
    Fault,
    FaultKind,
    Observation,
    Ok,
    Password,
    Reply,
    SpecReference,
    TransportError,
)
from dod.domain.v1 import (
    ReadingSystemAttributes,
    ServiceAttributes,
    ServicePort,
    fault_ref,
)

_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*(\.[a-z0-9]+(-[a-z0-9]+)*)*$")


class Outcome(StrEnum):
    """The result of a Conformance test (see GLOSSARY.md)."""

    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    ERROR = "ERROR"


@dataclass(frozen=True)
class Result:
    """What a test function returns: PASS or FAIL (SKIP and ERROR are the runner's)."""

    outcome: Outcome
    message: str = ""
    spec_ref: SpecReference | None = None
    note: str | None = None

    @classmethod
    def passed(cls, note: str | None = None) -> Result:
        """The Service answered as the specification requires."""
        return cls(Outcome.PASS, note=note)

    @classmethod
    def failed(cls, message: str, spec_ref: SpecReference) -> Result:
        """The Service answered contrary to the specification `spec_ref` names."""
        return cls(Outcome.FAIL, message, spec_ref)


type TestFunction = Callable[[Context], Result]


@dataclass(frozen=True)
class ConformanceTest:
    """A registered test: its stable id and whether it changes data on the Service."""

    id: str
    function: TestFunction
    state_changing: bool = False


class Registry:
    """The tests that can be run, in registration order."""

    def __init__(self) -> None:
        self._tests: dict[str, ConformanceTest] = {}

    @property
    def tests(self) -> tuple[ConformanceTest, ...]:
        return tuple(self._tests.values())

    def test(
        self, id: str, *, state_changing: bool = False
    ) -> Callable[[TestFunction], TestFunction]:
        """Register a test function under `id` (decorator).

        Ids are lower-case words joined by `-`, in dotted segments, such as
        `session.logon.wrong-password`, and are never reused.
        """
        if not _ID.match(id):
            raise ValueError(f"{id!r} is not a dotted, lower-case, hyphenated test id")
        if id in self._tests:
            raise ValueError(f"the test id {id} is already registered")

        def register(function: TestFunction) -> TestFunction:
            self._tests[id] = ConformanceTest(id, function, state_changing)
            return function

        return register


CONFORMANCE_TESTS = Registry()
"""The tests `dod test run` knows; the families register themselves here."""

conformance_test = CONFORMANCE_TESTS.test


class _Finished(Exception):
    """Ends a test early with a result chosen by a helper of the context."""

    def __init__(self, result: Result) -> None:
        super().__init__(result.message)
        self.result = result


class Context:
    """What a test sees: the ports it may use and the helpers that classify."""

    def __init__(
        self,
        port: ServicePort,
        open_port: Callable[[], ServicePort],
        username: str,
        password: Password,
        attributes: ServiceAttributes,
        reading_system: ReadingSystemAttributes,
        record: Callable[[Exchange | None, Sequence[Observation]], str | None],
    ) -> None:
        self.port = port
        """The setup's Session: logged on and initialised, for ordinary calls."""
        self.username = username
        self.password = password
        self.attributes = attributes
        """What the Service declared in the setup's `getServiceAttributes`."""
        self.reading_system = reading_system
        self._open_port = open_port
        self._record = record
        self._opened: list[ServicePort] = []
        self._notes: list[str] = []
        self.exchange_ids: list[str] = []

    def open_port(self) -> ServicePort:
        """A new port with no Session, for tests that log on themselves.

        The runner closes it when the test ends.
        """
        port = self._open_port()
        self._opened.append(port)
        return port

    def call[T](
        self,
        operation: Callable[[ServicePort], Reply[T]],
        *,
        on: ServicePort | None = None,
    ) -> Reply[T]:
        """Make one call, on the setup's port unless `on` is given, and keep its
        Exchange for the report. `TransportError` is not caught: it ends the test
        as ERROR."""
        reply = operation(on or self.port)
        self._remember(self._record(reply.exchange, reply.observations))
        return reply

    def _remember(self, exchange_id: str | None) -> None:
        if exchange_id is not None:
            self.exchange_ids.append(exchange_id)

    def skip(self, reason: str) -> NoReturn:
        """End the test as SKIP: it does not apply to this Service or run."""
        raise _Finished(Result(Outcome.SKIP, reason))

    def fail(self, message: str, spec_ref: SpecReference) -> NoReturn:
        """End the test as FAIL, citing the part of the specification."""
        raise _Finished(Result.failed(message, spec_ref))

    def note(self, text: str) -> None:
        """Add a remark that goes with a PASS."""
        self._notes.append(text)

    def expect_ok[T](self, reply: Reply[T], spec_ref: SpecReference) -> T:
        """The value of an `Ok` reply without schema violations.

        Anything else ends the test as FAIL: a fault names its DODP element, a
        Deviation brings its own Spec reference and a schema violation is cited
        with `spec_ref`.
        """
        if isinstance(reply, Deviation):
            self.fail(
                f"answered contrary to the specification: {reply.description}",
                reply.spec_reference,
            )
        if isinstance(reply, Fault):
            reason = f" ({reply.reason})" if reply.reason else ""
            self.fail(f"answered with the fault {reply.kind}{reason}", spec_ref)
        if reply.schema_violations:
            shown = "; ".join(
                f"line {v.line}: {v.message}" for v in reply.schema_violations[:3]
            )
            self.fail(f"the answer breaks the schema: {shown}", spec_ref)
        return reply.value

    def expect_fault[T](
        self, reply: Reply[T], kind: FaultKind, spec_ref: SpecReference | None = None
    ) -> Fault:
        """The `Fault` of the DODP kind `kind`; anything else ends the test as FAIL."""
        ref = spec_ref or fault_ref(kind)
        if isinstance(reply, Deviation):
            self.fail(
                f"expected the fault {kind}, but the answer is contrary to the "
                f"specification: {reply.description}",
                reply.spec_reference,
            )
        if isinstance(reply, Ok):
            self.fail(f"expected the fault {kind}, but the call succeeded", ref)
        if reply.kind is not kind:
            self.fail(f"expected the fault {kind}, got {reply.kind}", ref)
        return reply

    def optional[T](
        self,
        token: str,
        operation: Callable[[ServicePort], Reply[T]],
        spec_ref: SpecReference,
    ) -> Reply[T]:
        """Call an optional operation; `token` is its declared name.

        The token is the one `supportedOptionalOperations` uses.

        Not declared and answered `operationNotSupported` is SKIP. Declared and
        answered `operationNotSupported` is FAIL. Not declared but working is
        accepted with a note on the PASS. Any other answer is returned.
        """
        declared = token in self.attributes.supported_optional_operations
        reply = self.call(operation)
        unsupported = (
            isinstance(reply, Fault) and reply.kind is FaultKind.OPERATION_NOT_SUPPORTED
        )
        if unsupported and not declared:
            self.skip(f"{token} is not declared and the Service does not support it")
        if unsupported:
            self.fail(
                f"{token} is declared in supportedOptionalOperations, but the "
                "operation answered operationNotSupported",
                fault_ref(FaultKind.OPERATION_NOT_SUPPORTED),
            )
        if not declared and isinstance(reply, Ok):
            self.note(
                f"{token} works but is not declared in supportedOptionalOperations"
            )
        return reply

    def _close_ports(self) -> None:
        for port in self._opened:
            with contextlib.suppress(Exception):
                port.close()


@dataclass(frozen=True)
class Record:
    """One test's Outcome in a run."""

    id: str
    outcome: Outcome
    message: str = ""
    spec_ref: SpecReference | None = None
    note: str | None = None
    exchange_ids: tuple[str, ...] = ()
    state_changing: bool = False


@dataclass(frozen=True)
class RunReport:
    """Everything one `dod test run` found."""

    records: tuple[Record, ...]
    exchanges: dict[str, Exchange]
    """Unmasked; presentation masks them. Ids are `e1`, `e2`, ... in call order."""
    observations: tuple[Observation, ...]
    setup_exchange_ids: tuple[str, ...] = ()
    setup_error: str | None = None
    """Set when the setup failed; no test ran then (ERROR, exit code 2)."""

    @property
    def exit_code(self) -> int:
        """0 without FAIL or ERROR, 1 with FAIL only, 2 with any ERROR."""
        if self.setup_error is not None or any(
            r.outcome is Outcome.ERROR for r in self.records
        ):
            return 2
        return 1 if any(r.outcome is Outcome.FAIL for r in self.records) else 0


def _matches(test_id: str, prefix: str) -> bool:
    return test_id == prefix or test_id.startswith(prefix + ".")


def select(
    registry: Registry, only: Sequence[str] = (), skip: Sequence[str] = ()
) -> tuple[ConformanceTest, ...]:
    """The tests chosen by `--only` and `--skip`: prefixes on whole id segments.

    Raises `ValueError` for a prefix that matches no test.
    """
    for prefix in (*only, *skip):
        if not any(_matches(t.id, prefix) for t in registry.tests):
            raise ValueError(f"no test id starts with {prefix}")
    return tuple(
        test
        for test in registry.tests
        if (not only or any(_matches(test.id, p) for p in only))
        and not any(_matches(test.id, p) for p in skip)
    )


class _Run:
    """The Exchanges and Observations of one run, numbered as they come."""

    def __init__(self) -> None:
        self.exchanges: dict[str, Exchange] = {}
        self.observations: dict[Observation, None] = {}

    def record(
        self, exchange: Exchange | None, observations: Sequence[Observation]
    ) -> str | None:
        self.observations.update(dict.fromkeys(observations))
        if exchange is None:
            return None
        identifier = f"e{len(self.exchanges) + 1}"
        self.exchanges[identifier] = exchange
        return identifier


def run_conformance(
    open_port: OpenPort,
    url: str,
    username: str,
    password: Password,
    *,
    tests: Registry | None = None,
    only: Sequence[str] = (),
    skip: Sequence[str] = (),
    state_changing: bool = False,
    insecure: bool = False,
    reading_system: ReadingSystemAttributes | None = None,
) -> RunReport:
    """Run the selected Conformance tests against the Service at `url`.

    The run opens its own ports and logs on with `username` and `password`; it
    never uses the session manager or a stored Session (ADR 0005), so a fault
    is seen as data and not hidden by a relogin. A setup that fails ends the run
    at once. `state_changing` is the explicit opt-in for State-changing tests.

    Raises `EndpointError` before anything is sent when the address is refused
    and `ValueError` for an `only` or `skip` prefix that matches nothing.
    """
    check_endpoint(url, insecure=insecure)
    selected = select(tests or CONFORMANCE_TESTS, only, skip)
    run = _Run()
    declared = reading_system or default_reading_system()
    port = open_port(url)
    try:
        attributes = _setup(port, run, username, password, declared)
        if isinstance(attributes, str):
            return RunReport(
                (),
                run.exchanges,
                tuple(run.observations),
                tuple(run.exchanges),
                attributes,
            )
        setup_ids = tuple(run.exchanges)
        records = tuple(
            _run_one(
                test,
                Context(
                    port,
                    lambda: open_port(url),
                    username,
                    password,
                    attributes,
                    declared,
                    run.record,
                ),
                state_changing,
            )
            for test in selected
        )
        with contextlib.suppress(TransportError):
            reply = port.log_off()
            run.record(reply.exchange, reply.observations)
        return RunReport(records, run.exchanges, tuple(run.observations), setup_ids)
    finally:
        port.close()


def _setup(
    port: ServicePort,
    run: _Run,
    username: str,
    password: Password,
    reading_system: ReadingSystemAttributes,
) -> ServiceAttributes | str:
    """Log on and initialise; the Service's attributes, or why the setup failed."""
    try:
        steps = initialise(port, username, password, reading_system)
    except TransportError as error:
        run.record(error.exchange, ())
        return f"the setup got no usable answer: {error}"
    for step in steps:
        run.record(step.reply.exchange, step.reply.observations)
    for step in steps:
        if not step.succeeded:
            return f"the setup failed at {step.operation}: {_describe(step.reply)}"
    attributes = steps[1].reply
    assert isinstance(attributes, Ok)
    return attributes.value  # type: ignore[no-any-return]


def _describe(reply: Reply[object]) -> str:
    if isinstance(reply, Ok):
        return "the Service answered false"
    if isinstance(reply, Fault):
        return f"the fault {reply.kind}" + (
            f" ({reply.reason})" if reply.reason else ""
        )
    return f"an answer contrary to the specification: {reply.description}"


def _run_one(test: ConformanceTest, ctx: Context, state_changing: bool) -> Record:
    def record(result: Result) -> Record:
        outcome = result.outcome
        message = result.message
        if outcome is Outcome.FAIL and result.spec_ref is None:
            outcome = Outcome.ERROR
            message = (
                "defect in dod: the test failed without a Spec reference "
                f"({result.message})"
            )
        return Record(
            test.id,
            outcome,
            message,
            result.spec_ref,
            result.note if outcome is Outcome.PASS else None,
            tuple(ctx.exchange_ids),
            test.state_changing,
        )

    if test.state_changing and not state_changing:
        return Record(
            test.id,
            Outcome.SKIP,
            "a state-changing test; enable it with --state-changing",
            state_changing=True,
        )
    try:
        result = test.function(ctx)
        if not isinstance(result, Result):
            raise TypeError(f"the test returned {type(result).__name__}, not a Result")
        if result.outcome is Outcome.PASS and ctx._notes:
            result = Result.passed("; ".join(ctx._notes))
        return record(result)
    except _Finished as finished:
        return record(finished.result)
    except TransportError as error:
        ctx._remember(ctx._record(error.exchange, ()))
        return Record(
            test.id,
            Outcome.ERROR,
            str(error),
            None,
            None,
            tuple(ctx.exchange_ids),
            test.state_changing,
        )
    except Exception as error:
        return Record(
            test.id,
            Outcome.ERROR,
            f"defect in dod: {type(error).__name__}: {error}",
            None,
            None,
            tuple(ctx.exchange_ids),
            test.state_changing,
        )
    finally:
        ctx._close_ports()
