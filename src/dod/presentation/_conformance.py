"""Rendering of a conformance run: the text report and the JSON report.

The results go to stdout. Every Exchange in a report passes through `mask`
(ADR 0007), and text that came from the Service is stripped of control
characters before it reaches a terminal (ADR 0008).
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from dod.application import (
    BaselineComparison,
    ConformanceTest,
    Outcome,
    Record,
    RunReport,
)
from dod.domain.service import Exchange, SpecReference
from dod.presentation._masking import mask, mask_url

SCHEMA_VERSION = 4
"""Raised whenever the shape of the JSON report changes (ADR 0010)."""

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class ReportExchanges(StrEnum):
    """Which Exchanges a report includes."""

    ALL = "all"
    FAILURES = "failures"
    NONE = "none"


def plain(text: str) -> str:
    """The text without control characters."""
    return _CONTROL.sub(" ", text)


def _link(ref: SpecReference, hyperlinks: bool) -> str:
    label = f"DODP {ref.section} {ref.title}"
    if hyperlinks:
        return f"\x1b]8;;{ref.url}\x1b\\{label}\x1b]8;;\x1b\\"
    return f"{label}: {ref.url}"


def _line(record: Record, hyperlinks: bool) -> str:
    detail = plain(record.message)
    if record.outcome is Outcome.PASS:
        return f"PASS {record.id}" + (
            f" (note: {plain(record.note)})" if record.note else ""
        )
    if record.spec_ref is not None and record.outcome is Outcome.FAIL:
        detail += f" [{_link(record.spec_ref, hyperlinks)}]"
    return f"{record.outcome.value} {record.id}: {detail}"


def text_report(
    report: RunReport,
    *,
    hyperlinks: bool = False,
    baseline: BaselineComparison | None = None,
    quirks: tuple[str, ...] = (),
) -> list[str]:
    """One line per test, a summary, the Quirks that were on, the Baseline lines
    and the Observations."""
    lines: list[str] = []
    if report.setup_error is not None:
        lines.append(f"ERROR setup: {plain(report.setup_error)}")
    lines += [_line(record, hyperlinks) for record in report.records]
    counts = _summary(report)
    total = sum(counts.values())
    lines.append(
        f"{total} tests: " + ", ".join(f"{counts[o.value]} {o.value}" for o in Outcome)
    )
    if quirks:
        lines.append(f"Quirks on: {', '.join(quirks)}")
    if baseline is not None:
        lines.append(
            f"Baseline: {len(baseline.new)} new, {len(baseline.resolved)} "
            f"resolved, {len(baseline.known)} known"
        )
        lines += [f"NEW {plain(i)}" for i in baseline.new]
        lines += [f"RESOLVED {plain(i)}" for i in baseline.resolved]
    if report.observations:
        lines += ["", "Observations"]
        lines += [f"  {plain(o.id)}: {plain(o.message)}" for o in report.observations]
    return lines


def _summary(report: RunReport) -> dict[str, int]:
    counts = {outcome.value: 0 for outcome in Outcome}
    for record in report.records:
        counts[record.outcome.value] += 1
    return counts


def ref_json(ref: SpecReference | None) -> dict[str, Any] | None:
    if ref is None:
        return None
    return {
        "section": ref.section,
        "title": ref.title,
        "anchor": ref.anchor,
        "rule": ref.rule,
        "url": ref.url,
    }


def _exchange_json(exchange: Exchange) -> dict[str, Any]:
    masked = mask(exchange)
    return {
        "method": masked.method,
        "url": masked.url,
        "status": masked.status,
        "duration_seconds": round(masked.duration_seconds, 3),
        "request_headers": [list(pair) for pair in masked.request_headers],
        "request_body": masked.request_body,
        "response_headers": [list(pair) for pair in masked.response_headers],
        "response_body": masked.response_body,
    }


def json_report(
    report: RunReport,
    *,
    url: str,
    environment: str | None,
    exchanges: ReportExchanges,
    baseline: BaselineComparison | None = None,
    exit_code: int | None = None,
    quirks: tuple[str, ...] = (),
) -> dict[str, Any]:
    """The JSON report: results, Observations and the chosen masked Exchanges.

    `exit_code` is the one the run ends with, which a Baseline can change;
    Outcomes never change. `quirks` are the Quirks that were switched on.
    """
    included: list[str] = []
    if exchanges is ReportExchanges.ALL:
        included = list(report.exchanges)
    elif exchanges is ReportExchanges.FAILURES:
        if report.setup_error is not None:
            included += report.setup_exchange_ids
        for record in report.records:
            if record.outcome in {Outcome.FAIL, Outcome.ERROR}:
                included += record.exchange_ids
    setup = (
        None
        if report.setup_error is None
        else {
            "outcome": Outcome.ERROR.value,
            "message": report.setup_error,
            "exchanges": list(report.setup_exchange_ids),
        }
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "service": mask_url(url),
        "environment": environment,
        "quirks": list(quirks),
        "exit_code": report.exit_code if exit_code is None else exit_code,
        "summary": _summary(report),
        "setup": setup,
        "baseline": (
            None
            if baseline is None
            else {
                "new": list(baseline.new),
                "resolved": list(baseline.resolved),
                "known": list(baseline.known),
            }
        ),
        "results": [
            {
                "id": record.id,
                "outcome": record.outcome.value,
                "message": record.message,
                "note": record.note,
                "spec_ref": ref_json(record.spec_ref),
                "state_changing": record.state_changing,
                "exchanges": list(record.exchange_ids),
            }
            for record in report.records
        ],
        "observations": [
            {"id": o.id, "message": o.message} for o in report.observations
        ],
        "exchanges": {
            identifier: _exchange_json(report.exchanges[identifier])
            for identifier in dict.fromkeys(included)
        },
    }


def list_json(tests: tuple[ConformanceTest, ...]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "tests": [
            {"id": t.id, "state_changing": t.state_changing, "explicit": t.explicit}
            for t in tests
        ],
    }
