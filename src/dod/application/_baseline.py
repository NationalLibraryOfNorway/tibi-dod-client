"""A Baseline: the Conformance test ids a Service is known to FAIL (ADR 0010).

The file belongs to the Service's own repository. It is TOML, one `[[known]]`
table per test with an `id` and a short `reason`; it holds no addresses and no
credentials. Comparing a run with it changes only the exit code: Outcomes stay
as the run found them.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass

from dod.application._conformance import Outcome, RunReport


class BaselineError(ValueError):
    """The Baseline file is not a valid Baseline."""


@dataclass(frozen=True)
class Baseline:
    """Known failing test ids, each with a short reason."""

    reasons: Mapping[str, str]

    @classmethod
    def parse(cls, text: str) -> Baseline:
        """Read a Baseline; raises `BaselineError` naming what is wrong."""
        try:
            document = tomllib.loads(text)
        except tomllib.TOMLDecodeError as error:
            raise BaselineError(f"not valid TOML: {error}") from error
        unknown = set(document) - {"known"}
        if unknown:
            raise BaselineError(f"unknown key {sorted(unknown)[0]!r}")
        entries = document.get("known", [])
        if not isinstance(entries, list):
            raise BaselineError("'known' must be an array of tables ([[known]])")
        reasons: dict[str, str] = {}
        for number, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict):
                raise BaselineError(f"known entry {number} is not a table")
            identifier = entry.get("id")
            reason = entry.get("reason", "")
            if not isinstance(identifier, str) or not identifier:
                raise BaselineError(f"known entry {number} needs a string 'id'")
            if not isinstance(reason, str):
                raise BaselineError(f"known entry {number}: 'reason' must be a string")
            if identifier in reasons:
                raise BaselineError(f"{identifier} is listed twice")
            reasons[identifier] = reason
        return cls(reasons)

    def unknown_ids(self, known_tests: set[str]) -> tuple[str, ...]:
        """Entries that name no registered test, probably a typo or a retired id."""
        return tuple(i for i in self.reasons if i not in known_tests)


@dataclass(frozen=True)
class BaselineComparison:
    """A run set against a Baseline; each list is sorted by test id."""

    new: tuple[str, ...]
    """FAIL and not in the Baseline."""
    resolved: tuple[str, ...]
    """In the Baseline, and the test ran and now passes."""
    known: tuple[str, ...]
    """FAIL and in the Baseline."""

    def exit_code(self, report: RunReport, *, fail_on_resolved: bool = False) -> int:
        """2 with any ERROR, else 1 for a new FAIL (or a resolved entry when
        `fail_on_resolved`), else 0."""
        if report.exit_code == 2:
            return 2
        return 1 if self.new or (fail_on_resolved and self.resolved) else 0


def compare(report: RunReport, baseline: Baseline) -> BaselineComparison:
    """Sort the run's FAILs into new and known, and find the resolved entries.

    A baseline entry whose test was skipped, not selected or ended in ERROR is
    neither known nor resolved: the run says nothing about it.
    """
    failed = {r.id for r in report.records if r.outcome is Outcome.FAIL}
    passed = {r.id for r in report.records if r.outcome is Outcome.PASS}
    return BaselineComparison(
        new=tuple(sorted(failed - set(baseline.reasons))),
        resolved=tuple(sorted(passed & set(baseline.reasons))),
        known=tuple(sorted(failed & set(baseline.reasons))),
    )


def write_baseline(report: RunReport, previous: Baseline | None = None) -> str:
    """A Baseline file for the run's FAILs, as TOML.

    The reason is the Spec reference the FAIL cites (never text from the
    Service), or the reason `previous` already gave for that test.
    """
    lines = [
        "# Known deviations of a Service, written by `dod test run --write-baseline`.",
        "# Keep this file in the Service's own repository. Edit the reasons freely.",
    ]
    for record in sorted(
        (r for r in report.records if r.outcome is Outcome.FAIL), key=lambda r: r.id
    ):
        reason = (previous.reasons.get(record.id) if previous else None) or (
            f"DODP {record.spec_ref.section} {record.spec_ref.title}"
            if record.spec_ref
            else "known deviation"
        )
        lines += [
            "",
            "[[known]]",
            f"id = {_quote(record.id)}",
            f"reason = {_quote(reason)}",
        ]
    return "\n".join(lines) + "\n"


def _quote(text: str) -> str:
    """A TOML basic string."""
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    escaped = "".join(
        f"\\u{ord(c):04x}" if ord(c) < 0x20 or ord(c) == 0x7F else c for c in text
    )
    return f'"{escaped}"'
