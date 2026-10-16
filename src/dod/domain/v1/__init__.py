"""DODP v1 models and the port towards a Service.

May import `dod.domain.service` and nothing else from `dod`.
"""

from dod.domain.v1._models import (
    Announcement,
    ContentItem,
    ContentList,
    ContentMetadata,
    ReadingSystemAttributes,
    ReadingSystemConfig,
    ServiceAttributes,
)
from dod.domain.v1._port import RawChannel, ServicePort
from dod.domain.v1._quirks import (
    BARE_500_AS_INVALID_OPERATION,
    OBSERVATION_ID,
    QUIRKS,
    Quirk,
)
from dod.domain.v1._spec_refs import SPEC_REFS, fault_ref, operation_ref

__all__ = [
    "BARE_500_AS_INVALID_OPERATION",
    "OBSERVATION_ID",
    "QUIRKS",
    "SPEC_REFS",
    "Announcement",
    "ContentItem",
    "ContentList",
    "ContentMetadata",
    "Quirk",
    "RawChannel",
    "ReadingSystemAttributes",
    "ReadingSystemConfig",
    "ServiceAttributes",
    "ServicePort",
    "fault_ref",
    "operation_ref",
]
