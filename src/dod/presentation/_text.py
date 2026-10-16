"""Plain text from models and Replies, shared by the CLI and the TUI.

Text from a Service is untrusted: control characters never reach the terminal
(ADR 0008).
"""

import dataclasses
import re
from typing import Any

from dod.application import CANCELLED, DownloadReport, FileOutcome, Step
from dod.domain.service import Exchange, Fault, Observation, Ok
from dod.domain.v1 import ContentMetadata

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def plain(text: str) -> str:
    """`text` with every control character replaced by a space."""
    return _CONTROL.sub(" ", text)


def plain_lines(text: str) -> str:
    """Like `plain`, but keeps the line breaks of multi-line text."""
    return "\n".join(plain(line) for line in text.split("\n"))


def field_lines(value: Any, prefix: str = "") -> list[str]:
    """`name: value` for every field of a model, nested ones with a prefix."""
    lines: list[str] = []
    for field in dataclasses.fields(value):
        item = getattr(value, field.name)
        if dataclasses.is_dataclass(item):
            lines += field_lines(item, f"{prefix}{field.name}.")
            continue
        if isinstance(item, bool):
            shown = str(item).lower()
        elif isinstance(item, tuple):
            shown = ", ".join(plain(str(part)) for part in item) or "-"
        else:
            shown = "-" if item is None else plain(str(item))
        lines.append(f"{prefix}{field.name}: {shown}")
    return lines


def metadata_lines(book: ContentMetadata) -> list[str]:
    lines = field_lines(dataclasses.replace(book, meta=()))
    pairs = ", ".join(f"{plain(n)}={plain(c)}" for n, c in book.meta)
    return [*lines, f"meta: {pairs or '-'}"]


def step_result(step: Step) -> str:
    """How an operation went, as the Service answered, without control characters."""
    reply = step.reply
    if isinstance(reply, Ok):
        return "failed" if reply.value is False else "ok"
    if isinstance(reply, Fault):
        reason = f": {reply.reason}" if reply.reason else ""
        return plain(f"fault {reply.kind}{reason}")
    return plain(f"deviation: {reply.description}")


def step_line(step: Step) -> str:
    """One line on how an operation went, as the Service answered."""
    return f"{plain(step.operation)}: {step_result(step)}"


def download_summary(report: DownloadReport, directory: str) -> str:
    """One line on how a download went, for the status line."""
    if report.refusal is not None:
        return plain(report.refusal)
    if report.deviation is not None:
        return plain(step_line(Step("getContentResources", report.deviation)))
    if not isinstance(report.resources, Ok):
        return plain(step_line(Step("getContentResources", report.resources)))
    for item in report.files:
        if item.outcome is FileOutcome.DOWNLOADED:
            continue
        name = plain(item.local_uri)
        if item.problem == CANCELLED:
            return f"cancelled; nothing was kept of {name}"
        problem = item.problem
        reason = (
            plain(problem)
            if isinstance(problem, str)
            else plain(step_line(Step("fetch_resource", problem)))
            if problem is not None
            else "unknown"
        )
        return f"failed {name}: {reason}"
    count = len(report.files)
    return f"{count} file{'s' if count != 1 else ''} in {plain(directory)}"


BODY_LIMIT = 2000


def _body_lines(body: str) -> list[str]:
    shown = body[:BODY_LIMIT]
    lines = [plain(line) for line in shown.splitlines()] or [""]
    if len(body) > BODY_LIMIT:
        lines.append(f"[{len(body) - BODY_LIMIT} more characters not shown]")
    return lines


def log_lines(entries: tuple[Exchange | Observation, ...]) -> list[str]:
    """The log panel's text: what was sent and received, and what was noticed.

    The Exchanges are the masked copies the log holds; every character of them
    comes from the network, so control characters are replaced (ADR 0008).
    """
    lines: list[str] = []
    for entry in entries:
        if isinstance(entry, Observation):
            lines.append(f"observation {plain(entry.id)}: {plain(entry.message)}")
            continue
        lines.append(
            f"exchange: {plain(entry.method)} {plain(entry.url)} -> {entry.status} "
            f"in {round(entry.duration_seconds * 1000)} ms"
        )
        lines += [f"  > {plain(n)}: {plain(v)}" for n, v in entry.request_headers]
        lines += [f"  > {line}" for line in _body_lines(entry.request_body)]
        lines += [f"  < {plain(n)}: {plain(v)}" for n, v in entry.response_headers]
        lines += [f"  < {line}" for line in _body_lines(entry.response_body)]
    return lines
