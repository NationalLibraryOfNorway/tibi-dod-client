"""Plain text from models and Replies, shared by the CLI and the TUI.

Text from a Service is untrusted: control characters never reach the terminal
(ADR 0008).
"""

import dataclasses
import re
from typing import Any

from dod.application import CANCELLED, DownloadReport, FileOutcome, Step
from dod.domain.service import Fault, Ok
from dod.domain.v1 import ContentMetadata

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def plain(text: str) -> str:
    """`text` with every control character replaced by a space."""
    return _CONTROL.sub(" ", text)


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


def step_line(step: Step) -> str:
    """One line on how an operation went, as the Service answered."""
    reply = step.reply
    if isinstance(reply, Ok):
        return f"{step.operation}: {'failed' if reply.value is False else 'ok'}"
    if isinstance(reply, Fault):
        reason = f": {reply.reason}" if reply.reason else ""
        return f"{step.operation}: fault {reply.kind}{reason}"
    return f"{step.operation}: deviation: {reply.description}"


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
