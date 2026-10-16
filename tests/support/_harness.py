"""What the contract tests need from a fake Service, whichever adapter is used."""

from typing import Protocol

from dod.domain.v1 import ServicePort


class Harness(Protocol):
    """A fresh fake Service plus a way to open a `ServicePort` towards it."""

    def add_user(self, username: str, password: str) -> None: ...

    def inject_fault(self, operation: str, kind: str, reason: str) -> None:
        """Make the next call of `operation` answer with the DODP fault `kind`."""
        ...

    def inject_deviation(self, operation: str) -> None:
        """Make the next call of `operation` answer contrary to the specification."""
        ...

    def open_port(self) -> ServicePort: ...
