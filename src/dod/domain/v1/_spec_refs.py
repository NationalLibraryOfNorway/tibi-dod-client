"""The closed registry of Spec references (ADR 0008).

Every FAIL and every `Deviation` points at one of these. Section numbers,
titles and anchors follow the HTML version of the specification; a test checks
them against the local copy without network access. The short rules are our
own wording.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from dod.domain.service import SpecReference

_OPERATIONS = (
    ("logOn", "5.1.1"),
    ("logOff", "5.1.2"),
    ("setReadingSystemAttributes", "5.1.3"),
    ("issueContent", "5.1.4"),
    ("getContentMetadata", "5.1.5"),
    ("getContentResources", "5.1.6"),
    ("getServiceAttributes", "5.1.7"),
    ("getContentList", "5.1.8"),
    ("getServiceAnnouncements", "5.2.1"),
    ("markAnnouncementsAsRead", "5.2.2"),
    ("returnContent", "5.2.3"),
    ("setBookmarks", "5.2.4"),
    ("getBookmarks", "5.2.5"),
    ("getQuestions", "5.2.6"),
    ("getKeyExchangeObject", "5.2.7"),
)
_FAULTS = (
    ("internalServerError", "5.3.1", "An error on the Service halted the operation."),
    (
        "noActiveSession",
        "5.3.2",
        "Every operation but the Session Initialization Sequence needs an active "
        "Session.",
    ),
    (
        "operationNotSupported",
        "5.3.3",
        "Issued when an optional operation is called that the Service does not "
        "support.",
    ),
    ("invalidOperation", "5.3.4", "The operation is not valid in the current context."),
    (
        "invalidParameter",
        "5.3.5",
        "Issued for a parameter the Service does not recognise, allow or support.",
    ),
)
_TYPES = (
    ("announcements", "6.1"),
    ("bookmarkSet", "6.2"),
    ("contentList", "6.3"),
    ("contentMetadata", "6.4"),
    ("questions", "6.7"),
    ("readingSystemAttributes", "6.9"),
    ("resources", "6.10"),
    ("serviceAttributes", "6.11"),
)

_RULES = {
    "logOn": "Answers whether the logon was successful.",
    "logOff": "A false result or a Fault means the logoff was not successful.",
    "getContentList": (
        "The id of the returned list must match the id asked for; an invalid "
        "range gives an empty list with totalItems set."
    ),
}


def _build() -> dict[str, SpecReference]:
    refs: dict[str, SpecReference] = {}
    for name, section in _OPERATIONS:
        refs[f"operation.{name}"] = SpecReference(
            section=section,
            title=f"The {name} Operation",
            anchor=f"op_{name}",
            rule=_RULES.get(name),
        )
    refs["faults"] = SpecReference("5.3", "Faults", "apiReferenceFaults")
    for name, section, rule in _FAULTS:
        refs[f"fault.{name}"] = SpecReference(
            section=section,
            title=f"The {name} Fault",
            anchor=f"ft_{name}Fault",
            rule=rule,
        )
    for name, section in _TYPES:
        refs[f"type.{name}"] = SpecReference(
            section=section, title=f"The {name} Type", anchor=f"tp_{name}"
        )
    refs["session.initialization"] = SpecReference(
        "4.2.1",
        "Session Initialization",
        "fundamentals_session_initializationSequence",
        "After a successful logOn the Reading System calls getServiceAttributes "
        "and setReadingSystemAttributes.",
    )
    refs["optional-operations"] = SpecReference(
        "5.2", "Optional Operations", "apiReferenceOptional"
    )
    return refs


SPEC_REFS: Mapping[str, SpecReference] = MappingProxyType(_build())
"""Every Spec reference `dod` can attach, by key."""


def operation_ref(operation: str) -> SpecReference:
    """The section that defines the operation; `KeyError` for an unknown one."""
    return SPEC_REFS[f"operation.{operation}"]


def fault_ref(kind: str) -> SpecReference:
    """The section that defines the DODP fault `kind` (`noActiveSession`, ...)."""
    return SPEC_REFS[f"fault.{kind}"]
