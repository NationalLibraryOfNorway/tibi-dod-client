"""Composition root: wires the layers together and runs the `dod` command."""

import os

from dod.domain.v1 import RawChannel, ServicePort
from dod.infrastructure import (
    FileConfigStore,
    FileSessionStore,
    HttpFetcher,
    HttpServicePort,
    data_directory,
    parse_reading_system,
    parse_wsdl,
    validate_bookmark_set,
)
from dod.presentation import create_app


def _open_http_port(url: str) -> ServicePort:
    return HttpServicePort(url)


def _open_http_quirky(url: str, quirks: frozenset[str]) -> ServicePort:
    return HttpServicePort(url, quirks=quirks)


def _open_http_raw(url: str) -> RawChannel:
    return HttpServicePort(url)


def main() -> None:
    """Entry point of the `dod` console script."""
    create_app(
        _open_http_port,
        FileConfigStore(),
        HttpFetcher(),
        parse_wsdl,
        session_store=FileSessionStore.from_environ(os.environ),
        parse_reading_system=parse_reading_system,
        open_raw=_open_http_raw,
        open_quirky=_open_http_quirky,
        data_dir=data_directory(os.environ),
        validate_bookmarks=validate_bookmark_set,
    )()
