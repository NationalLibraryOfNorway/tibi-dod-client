"""Infrastructure layer: adapters such as the HTTP adapter towards a Service.

May import the application and domain packages.
"""

from dod.infrastructure._config_file import FileConfigStore
from dod.infrastructure._fetch import HttpFetcher
from dod.infrastructure._http import HttpServicePort
from dod.infrastructure._memory import InMemoryPort, InMemoryService
from dod.infrastructure._schema import (
    SchemaFinding,
    SchemaUnavailableError,
    validate_document,
)
from dod.infrastructure._session_file import FileSessionStore
from dod.infrastructure._wsdl import parse_wsdl

__all__ = [
    "FileConfigStore",
    "FileSessionStore",
    "HttpFetcher",
    "HttpServicePort",
    "InMemoryPort",
    "InMemoryService",
    "SchemaFinding",
    "SchemaUnavailableError",
    "parse_wsdl",
    "validate_document",
]
