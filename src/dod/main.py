"""Composition root: wires the layers together and runs the `dod` command."""

import os

from dod.domain.v1 import ServicePort
from dod.infrastructure import (
    FileConfigStore,
    FileSessionStore,
    HttpFetcher,
    HttpServicePort,
    parse_wsdl,
)
from dod.presentation import create_app


def _open_http_port(url: str) -> ServicePort:
    return HttpServicePort(url)


def main() -> None:
    """Entry point of the `dod` console script."""
    create_app(
        _open_http_port,
        FileConfigStore(),
        HttpFetcher(),
        parse_wsdl,
        session_store=FileSessionStore.from_environ(os.environ),
    )()
