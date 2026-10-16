"""Infrastructure layer: adapters such as the HTTP adapter towards a Service.

May import the application and domain packages.
"""

from dod.infrastructure._audio import MiniaudioPlayer, open_miniaudio_player
from dod.infrastructure._bookmarks import validate_bookmark_set
from dod.infrastructure._config_file import FileConfigStore
from dod.infrastructure._data_dir import data_directory
from dod.infrastructure._fetch import HttpFetcher
from dod.infrastructure._http import HttpServicePort
from dod.infrastructure._memory import InMemoryPort, InMemoryService
from dod.infrastructure._reading_system import parse_reading_system
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
    "MiniaudioPlayer",
    "SchemaFinding",
    "SchemaUnavailableError",
    "data_directory",
    "open_miniaudio_player",
    "parse_reading_system",
    "parse_wsdl",
    "validate_bookmark_set",
    "validate_document",
]
