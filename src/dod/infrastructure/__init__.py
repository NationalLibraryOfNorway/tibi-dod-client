"""Infrastructure layer: adapters such as the HTTP adapter towards a Service.

May import the application and domain packages.
"""

from dod.infrastructure._http import HttpServicePort
from dod.infrastructure._memory import InMemoryPort, InMemoryService
from dod.infrastructure._schema import (
    SchemaFinding,
    SchemaUnavailableError,
    validate_document,
)

__all__ = [
    "HttpServicePort",
    "InMemoryPort",
    "InMemoryService",
    "SchemaFinding",
    "SchemaUnavailableError",
    "validate_document",
]
