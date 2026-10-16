"""The closed registry of Quirks (ADR 0010).

A Quirk is a named, generic workaround for a Service deviation that would
otherwise make an answer unreadable. It is named after the behaviour it
tolerates, never after a backend, is off unless an Environment lists it, and
always produces an `interoperability` Observation when it is used. The
behaviour itself lives in the HTTP adapter; this module only knows the names,
so configuration can be validated and `dod quirks list` can show them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from dod.domain.service import SpecReference
from dod.domain.v1._spec_refs import SPEC_REFS

BARE_500_AS_INVALID_OPERATION = "http-500-without-fault-as-invalid-operation"
"""An HTTP 500 with no DODP fault element, before initialisation."""

OBSERVATION_ID = "interoperability"
"""The id of the Observation every use of a Quirk produces."""


@dataclass(frozen=True)
class Quirk:
    """A known deviation that can be tolerated, and what the specification says."""

    name: str
    description: str
    spec_reference: SpecReference


def _build() -> dict[str, Quirk]:
    quirks = [
        Quirk(
            BARE_500_AS_INVALID_OPERATION,
            "Read an HTTP 500 whose SOAP fault has no DODP fault element as an "
            "invalidOperation fault, for operations that need the Session "
            "initialisation sequence (not logOn, logOff, getServiceAttributes "
            "or setReadingSystemAttributes). The specification requires the "
            "invalidOperation fault when an operation is called before the "
            "initialisation is complete.",
            SPEC_REFS["fault.invalidOperation"],
        ),
    ]
    return {quirk.name: quirk for quirk in quirks}


QUIRKS: Mapping[str, Quirk] = MappingProxyType(_build())
"""Every Quirk `dod` knows, by name."""
