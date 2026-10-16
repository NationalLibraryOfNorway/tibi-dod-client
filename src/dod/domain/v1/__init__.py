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
from dod.domain.v1._spec_refs import SPEC_REFS, fault_ref, operation_ref

__all__ = [
    "SPEC_REFS",
    "Announcement",
    "ContentItem",
    "ContentList",
    "ContentMetadata",
    "RawChannel",
    "ReadingSystemAttributes",
    "ReadingSystemConfig",
    "ServiceAttributes",
    "ServicePort",
    "fault_ref",
    "operation_ref",
]
