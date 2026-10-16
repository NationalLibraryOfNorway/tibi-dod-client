"""Rendering of `dod quirks list`: text and JSON."""

from __future__ import annotations

from typing import Any

from dod.application import QuirkUse
from dod.presentation._conformance import ref_json
from dod.presentation._text import plain


def quirk_lines(uses: tuple[QuirkUse, ...]) -> list[str]:
    """Per Quirk: its name, description, Spec reference and Environments."""
    lines: list[str] = []
    for use in uses:
        ref = use.quirk.spec_reference
        enabled = ", ".join(use.environments) or "none"
        lines += [
            use.quirk.name,
            f"  {use.quirk.description}",
            f"  Spec: DODP {ref.section} {ref.title}: {ref.url}",
            f"  Enabled in: {plain(enabled)}",
        ]
    return lines


def quirks_json(uses: tuple[QuirkUse, ...]) -> dict[str, Any]:
    return {
        "quirks": [
            {
                "name": use.quirk.name,
                "description": use.quirk.description,
                "spec_reference": ref_json(use.quirk.spec_reference),
                "environments": list(use.environments),
            }
            for use in uses
        ]
    }
