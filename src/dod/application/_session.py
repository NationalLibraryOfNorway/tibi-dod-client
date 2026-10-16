"""The session manager: the only place for initialisation and relogin (ADR 0005).

Everything ordinary commands need from a Session lives here: reusing the stored
Session, the Initialisation sequence, the single relogin after an Expired
session and reading and writing the Session file through a `SessionStore`.
Conformance runs never use it. Ephemeral mode is the same manager without
persistence. Use cases do not print and do not exit.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import Protocol

from dod.application._logon import (
    LogonReport,
    OpenPort,
    Step,
    default_reading_system,
    initialise,
)
from dod.domain.service import (
    Deviation,
    Fault,
    FaultKind,
    Password,
    Reply,
    SessionState,
    TransportError,
)
from dod.domain.v1 import ReadingSystemAttributes, ServiceAttributes, ServicePort


@dataclass(frozen=True)
class SessionKey:
    """What identifies a Session file: the resolved Service URL and the user."""

    url: str
    username: str


class SessionSlot(Protocol):
    """The Session file of one key, usable only while its lock is held."""

    def read(self) -> SessionState | None: ...

    def write(self, state: SessionState) -> None: ...

    def clear(self) -> None: ...


class SessionStore(Protocol):
    """Where Session files live. The lock is part of the interface (ADR 0005).

    Reading, changing and writing happen inside `lock`, across processes. The
    lock is never held while a call to the Service is in flight, except for the
    Initialisation sequence of a login, which is what lets exactly one process
    log in.
    """

    def lock(self, key: SessionKey) -> AbstractContextManager[SessionSlot]: ...


type CredentialProvider = Callable[[], Password | None]
"""Gives the password when a login is needed, or `None` when there is none."""


class SessionError(Exception):
    """A Session could not be had; the message says what to do."""


class NoCredentialsError(SessionError):
    """A login is needed but no credentials are available."""


class InitialisationFailed(SessionError):
    """The Initialisation sequence did not succeed; the report says where."""

    def __init__(self, report: LogonReport) -> None:
        super().__init__("the Initialisation sequence did not succeed")
        self.report = report


@dataclass(frozen=True)
class LogoffResult:
    """What `logoff` did: whether a Session was stored and what went wrong."""

    had_session: bool
    warning: str | None = None


class _MemorySlot:
    def __init__(self, sessions: dict[SessionKey, SessionState], key: SessionKey):
        self._sessions = sessions
        self._key = key

    def read(self) -> SessionState | None:
        return self._sessions.get(self._key)

    def write(self, state: SessionState) -> None:
        self._sessions[self._key] = state

    def clear(self) -> None:
        self._sessions.pop(self._key, None)


class MemorySessionStore:
    """A `SessionStore` that keeps Sessions in this process only."""

    def __init__(self) -> None:
        self._sessions: dict[SessionKey, SessionState] = {}
        self._lock = threading.RLock()

    @contextmanager
    def lock(self, key: SessionKey) -> Iterator[SessionSlot]:
        with self._lock:
            yield _MemorySlot(self._sessions, key)


def _expired(reply: Reply[object]) -> bool:
    """An Expired session is `noActiveSession` in `detail`, nothing else."""
    return isinstance(reply, Fault) and reply.kind is FaultKind.NO_ACTIVE_SESSION


class SessionManager:
    """Gives operations a usable Session for one Service URL and user."""

    def __init__(
        self,
        open_port: OpenPort,
        store: SessionStore,
        url: str,
        username: str,
        credentials: CredentialProvider | None,
        *,
        reading_system: ReadingSystemAttributes | None = None,
        ephemeral: bool = False,
    ) -> None:
        self._open_port = open_port
        self._store = store
        self._url = url
        self._username = username
        self._credentials = credentials
        self._reading_system = reading_system or default_reading_system()
        self._ephemeral = ephemeral
        self._key = SessionKey(url, username)

    @classmethod
    def ephemeral(
        cls,
        open_port: OpenPort,
        url: str,
        username: str,
        credentials: CredentialProvider | None,
        *,
        reading_system: ReadingSystemAttributes | None = None,
    ) -> SessionManager:
        """Ephemeral mode: a Session of its own, never stored, ended after the call."""
        return cls(
            open_port,
            MemorySessionStore(),
            url,
            username,
            credentials,
            reading_system=reading_system,
            ephemeral=True,
        )

    # -- ordinary operations ---------------------------------------------

    def call[T](self, op: Callable[[ServicePort], Reply[T]]) -> Reply[T]:
        """Run `op` on a port that has a Session.

        An Expired session is replaced exactly once and `op` is repeated; with
        no credentials that is a `NoCredentialsError`. A failing Initialisation
        sequence is an `InitialisationFailed`.
        """
        if self._ephemeral:
            return self._call_ephemeral(op)
        stale = self._stored()
        if stale is not None:
            reply = self._run(op, stale)
            if not _expired(reply):
                return reply
        return self._run(op, self._renew(stale))

    def _call_ephemeral[T](self, op: Callable[[ServicePort], Reply[T]]) -> Reply[T]:
        password = self._credentials() if self._credentials else None
        if password is None:
            raise NoCredentialsError(
                "Ephemeral mode has to log on every time and there are no "
                "credentials; give the password on stdin or in the Environment"
            )
        port = self._open_port(self._url)
        try:
            steps = initialise(port, self._username, password, self._reading_system)
            if not all(step.succeeded for step in steps):
                raise InitialisationFailed(LogonReport(tuple(steps)))
            try:
                return op(port)
            finally:
                with contextlib.suppress(TransportError):
                    port.log_off()
        finally:
            port.close()

    # -- the Session commands --------------------------------------------

    def logon(self, password: Password) -> LogonReport:
        """End a stored Session, run the Initialisation sequence, store the result.

        The Session file is written only when the whole sequence succeeded.
        """
        with self._store.lock(self._key) as slot:
            previous = slot.read()
            slot.clear()
            if previous is not None:
                self._end_quietly(previous)
            steps, state = self._initialise(password)
            if state is not None:
                slot.write(state)
        return LogonReport(tuple(steps))

    def logoff(self) -> LogoffResult:
        """Call `logOff` and delete the Session file whatever the Service says."""
        state = self._stored()
        warning: str | None = None
        if state is not None:
            port = self._open_port(self._url)
            try:
                port.resume(state)
                reply = port.log_off()
                if isinstance(reply, Fault):
                    warning = f"logOff answered with the fault {reply.kind}"
                elif isinstance(reply, Deviation):
                    warning = (
                        "logOff answered contrary to the specification: "
                        f"{reply.description}"
                    )
            except TransportError as error:
                warning = f"logOff got no usable answer: {error}"
            finally:
                port.close()
        self.clear()
        return LogoffResult(had_session=state is not None, warning=warning)

    def clear(self) -> None:
        """Delete the Session file without contacting the Service."""
        with self._store.lock(self._key) as slot:
            slot.clear()

    def stored(self) -> bool:
        return self._stored() is not None

    def probe(self) -> bool | None:
        """Check the stored Session with one reading call; never logs in again.

        `None` when nothing is stored, `False` when the Service says the Session
        has expired, otherwise `True`.
        """
        state = self._stored()
        if state is None:
            return None
        reply = self._run(_read_attributes, state)
        return not _expired(reply)

    # -- internals --------------------------------------------------------

    def _stored(self) -> SessionState | None:
        with self._store.lock(self._key) as slot:
            return slot.read()

    def _run[T](
        self, op: Callable[[ServicePort], Reply[T]], state: SessionState
    ) -> Reply[T]:
        port = self._open_port(self._url)
        try:
            port.resume(state)
            return op(port)
        finally:
            port.close()

    def _renew(self, stale: SessionState | None) -> SessionState:
        """Log in again unless another process already replaced `stale`."""
        if (current := self._replaced(stale)) is not None:
            return current
        password = self._credentials() if self._credentials else None
        if password is None:
            raise NoCredentialsError(
                "there is no usable Session and no credentials to log on with; "
                "run: dod logon"
            )
        with self._store.lock(self._key) as slot:
            current = slot.read()
            if current is not None and current != stale:
                return current
            steps, state = self._initialise(password)
            if state is None:
                slot.clear()
                raise InitialisationFailed(LogonReport(tuple(steps)))
            slot.write(state)
            return state

    def _replaced(self, stale: SessionState | None) -> SessionState | None:
        current = self._stored()
        return current if current is not None and current != stale else None

    def _initialise(self, password: Password) -> tuple[list[Step], SessionState | None]:
        port = self._open_port(self._url)
        try:
            steps = initialise(port, self._username, password, self._reading_system)
            state = port.session if all(step.succeeded for step in steps) else None
        finally:
            port.close()
        return steps, state

    def _end_quietly(self, state: SessionState) -> None:
        port = self._open_port(self._url)
        try:
            port.resume(state)
            with contextlib.suppress(TransportError):
                port.log_off()
        finally:
            port.close()


def _read_attributes(port: ServicePort) -> Reply[ServiceAttributes]:
    return port.get_service_attributes()
