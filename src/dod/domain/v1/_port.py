"""The port towards a DODP v1 Service (ADR 0004)."""

from __future__ import annotations

from typing import Protocol

from dod.domain.service import Password, Reply, SessionState
from dod.domain.v1._models import ReadingSystemAttributes, ServiceAttributes


class ServicePort(Protocol):
    """Synchronous, bound to one Service URL and at most one Session.

    Every method returns what the Service answered as a `Reply` and raises
    `TransportError` only when there was no usable answer. The port never logs
    in again and never retries (ADR 0005).
    """

    @property
    def session(self) -> SessionState | None:
        """The current Session, or `None` before a `log_on` has started one."""
        ...

    def resume(self, session: SessionState) -> None:
        """Continue a Session started by another port, from its `session` state.

        Sends nothing; whether the Service still knows the Session shows on the
        next call, as a `noActiveSession` fault when it does not.
        """
        ...

    def log_on(self, username: str, password: Password) -> Reply[bool]: ...

    def log_off(self) -> Reply[bool]: ...

    def get_service_attributes(self) -> Reply[ServiceAttributes]: ...

    def set_reading_system_attributes(
        self, attributes: ReadingSystemAttributes
    ) -> Reply[bool]: ...

    def close(self) -> None:
        """Release the connection; the port is not used afterwards."""
        ...
