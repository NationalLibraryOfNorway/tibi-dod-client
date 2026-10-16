"""The closed registry of Spec references against the local specification copy.

No network: the anchors, section numbers and titles are looked up in
`docs/spec/dodp-v1` (ADR 0008).
"""

import html
import re
from pathlib import Path

import pytest

from dod.domain.v1 import SPEC_REFS, operation_ref

SPEC = Path(__file__).resolve().parents[2] / "docs/spec/dodp-v1/do-spec-20100402.html"
OPERATIONS = (
    "logOn",
    "logOff",
    "setReadingSystemAttributes",
    "issueContent",
    "getContentMetadata",
    "getContentResources",
    "getServiceAttributes",
    "getContentList",
    "getServiceAnnouncements",
    "markAnnouncementsAsRead",
    "returnContent",
    "setBookmarks",
    "getBookmarks",
    "getQuestions",
    "getKeyExchangeObject",
)


def headings() -> dict[str, str]:
    """Anchor to heading text, as the local copy gives it."""
    text = SPEC.read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for match in re.finditer(
        r'<h[2-6][^>]*><a id="([^"]+)"/>(.*?)</h[2-6]>', text, re.DOTALL
    ):
        plain = re.sub(r"<[^>]+>", "", match.group(2))
        found[match.group(1)] = " ".join(html.unescape(plain).split())
    return found


def test_every_reference_points_at_a_heading_of_the_local_copy() -> None:
    found = headings()

    for key, ref in SPEC_REFS.items():
        assert ref.anchor in found, f"{key}: no heading with id {ref.anchor}"
        assert found[ref.anchor] == f"{ref.section}. {ref.title}", key


def test_the_link_of_a_reference_names_the_published_version_and_the_anchor() -> None:
    published = "http://www.daisy.org/projects/daisy-online-delivery/drafts/20100402/"
    text = SPEC.read_text(encoding="utf-8")

    for ref in SPEC_REFS.values():
        assert ref.url == f"{published}do-spec-20100402.html#{ref.anchor}"
    assert f"{published}do-spec-20100402.html" in text


@pytest.mark.parametrize("operation", OPERATIONS)
def test_every_operation_has_a_reference(operation: str) -> None:
    ref = operation_ref(operation)

    assert ref.title == f"The {operation} Operation"


def test_the_registry_is_closed() -> None:
    with pytest.raises(KeyError):
        operation_ref("noSuchOperation")


def test_a_reference_may_carry_a_short_rule() -> None:
    assert SPEC_REFS["fault.noActiveSession"].rule
