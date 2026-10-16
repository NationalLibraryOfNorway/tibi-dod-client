"""DODP v1 models and the port towards a Service.

May import `dod.domain.service` and nothing else from `dod`.
"""

from dod.domain.v1._models import (
    Announcement,
    ReadingSystemAttributes,
    ReadingSystemConfig,
    ServiceAttributes,
)
from dod.domain.v1._port import ServicePort

__all__ = [
    "Announcement",
    "ReadingSystemAttributes",
    "ReadingSystemConfig",
    "ServiceAttributes",
    "ServicePort",
]
