"""Version-neutral shared kernel: Reply, Exchange, Observation, session state.

Innermost layer. It must not import any other `dod` package.
"""

from dod.domain.service._core import (
    Deviation,
    Exchange,
    Fault,
    FaultKind,
    Observation,
    Ok,
    Password,
    Reply,
    SchemaViolation,
    SessionState,
    SpecReference,
    TransportError,
)

__all__ = [
    "Deviation",
    "Exchange",
    "Fault",
    "FaultKind",
    "Observation",
    "Ok",
    "Password",
    "Reply",
    "SchemaViolation",
    "SessionState",
    "SpecReference",
    "TransportError",
]
