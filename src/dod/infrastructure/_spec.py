"""Spec references the adapters attach to Deviations."""

from dod.domain.service import SpecReference

# The published HTML version has no stable per-section anchors we can rely on
# yet; the link names the DODP page and the section number does the pointing.
_SPEC_URL = "https://daisy.org/?p=492"


def operation_reference(operation: str) -> SpecReference:
    """The section that defines `operation` among the required operations."""
    sections = {
        "logOn": "5.1.1",
        "logOff": "5.1.2",
        "setReadingSystemAttributes": "5.1.3",
        "getContentMetadata": "5.1.5",
        "getServiceAttributes": "5.1.7",
        "getContentList": "5.1.8",
        "getServiceAnnouncements": "5.2.1",
        "markAnnouncementsAsRead": "5.2.2",
    }
    return SpecReference(
        section=sections[operation],
        title=f"The {operation} Operation",
        url=_SPEC_URL,
    )


FAULTS_REFERENCE = SpecReference(section="5.3", title="Faults", url=_SPEC_URL)
