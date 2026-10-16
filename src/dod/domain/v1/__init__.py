"""DODP v1 models and the port towards a Service.

May import `dod.domain.service` and nothing else from `dod`.
"""

from dod.domain.v1._models import (
    Announcement,
    BookmarkSet,
    Choice,
    ContentItem,
    ContentList,
    ContentMetadata,
    ContentResource,
    ContentResources,
    InputQuestion,
    KeyExchangeObject,
    Lastmark,
    MultipleChoiceQuestion,
    Question,
    Questions,
    ReadingSystemAttributes,
    ReadingSystemConfig,
    ServiceAttributes,
    UserResponse,
)
from dod.domain.v1._port import (
    ByteRange,
    RawChannel,
    ResourceSink,
    ServicePort,
    SinkRefused,
)
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
    "BookmarkSet",
    "ByteRange",
    "Choice",
    "ContentItem",
    "ContentList",
    "ContentMetadata",
    "ContentResource",
    "ContentResources",
    "InputQuestion",
    "KeyExchangeObject",
    "Lastmark",
    "MultipleChoiceQuestion",
    "Question",
    "Questions",
    "Quirk",
    "RawChannel",
    "ReadingSystemAttributes",
    "ReadingSystemConfig",
    "ResourceSink",
    "ServiceAttributes",
    "ServicePort",
    "SinkRefused",
    "UserResponse",
    "fault_ref",
    "operation_ref",
]
