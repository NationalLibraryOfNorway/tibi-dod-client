"""Marking announcements as read (specification 4.5.2).

The Service only accepts identifiers from the latest `getServiceAnnouncements`
of the same Session, so marking always fetches first. A set the Service
rejects with `invalidParameter` is retried one identifier at a time to find
the culprit; `false` means the announcement was already read. Every call goes
through the session manager (ADR 0005). Use cases do not print and do not
exit: the Replies come back unchanged.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from dod.application._session import SessionManager
from dod.domain.service import Fault, FaultKind, Ok, Reply
from dod.domain.v1 import Announcement, ServicePort


class MarkOutcome(StrEnum):
    MARKED = "marked as read"
    ALREADY_READ = "already read"
    FAILED = "failed"


@dataclass(frozen=True)
class MarkResult:
    """What became of one identifier; `reply` is what the Service answered."""

    id: str
    reply: Reply[bool]

    @property
    def outcome(self) -> MarkOutcome:
        if not isinstance(self.reply, Ok):
            return MarkOutcome.FAILED
        return MarkOutcome.MARKED if self.reply.value else MarkOutcome.ALREADY_READ


@dataclass(frozen=True)
class MarkReport:
    """The fetch that preceded the marking and the result per identifier.

    `results` is empty when the fetch was not an `Ok` (see `fetched`) or when
    there was nothing to mark.
    """

    fetched: Reply[tuple[Announcement, ...]]
    results: tuple[MarkResult, ...] = ()

    @property
    def succeeded(self) -> bool:
        return isinstance(self.fetched, Ok) and all(
            result.outcome is not MarkOutcome.FAILED for result in self.results
        )


def _marking(ids: Sequence[str]) -> Callable[[ServicePort], Reply[bool]]:
    def mark(port: ServicePort) -> Reply[bool]:
        return port.mark_announcements_as_read(ids)

    return mark


def mark_read(manager: SessionManager, ids: Sequence[str] | None) -> MarkReport:
    """Mark `ids` as read, or every announcement of the fetch when `ids` is `None`."""
    fetched = manager.call(lambda port: port.get_service_announcements())
    if not isinstance(fetched, Ok):
        return MarkReport(fetched)
    targets = list(ids) if ids is not None else [a.id for a in fetched.value]
    if not targets:
        return MarkReport(fetched)
    batch = manager.call(_marking(targets))
    if len(targets) == 1 or not (
        isinstance(batch, Fault) and batch.kind is FaultKind.INVALID_PARAMETER
    ):
        return MarkReport(fetched, tuple(MarkResult(i, batch) for i in targets))
    results: list[MarkResult] = []
    for identifier in targets:
        results.append(MarkResult(identifier, manager.call(_marking([identifier]))))
    return MarkReport(fetched, tuple(results))
