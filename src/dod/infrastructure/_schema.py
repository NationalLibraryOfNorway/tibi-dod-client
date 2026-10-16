"""Offline validation of DODP v1 documents against the local schema copies."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from lxml import etree

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SPEC_DIR = _REPO_ROOT / "docs" / "spec" / "dodp-v1"
_CATALOG = _REPO_ROOT / "schemas" / "catalog.xml"
_CATALOG_NS = "urn:oasis:names:tc:entity:xmlns:xml:catalog"

_WSDL = _SPEC_DIR / "do-wsdl-10.wsdl"
_XSD = "http://www.w3.org/2001/XMLSchema"


@dataclass(frozen=True)
class SchemaFinding:
    """One way in which a document does not conform to the DODP v1 schemas."""

    line: int
    message: str


class SchemaUnavailableError(Exception):
    """The local schema copies cannot be found, for example in an installed wheel."""


class _CatalogResolver(etree.Resolver):
    """Serves remote schema locations from the catalog and refuses the rest."""

    def __init__(self) -> None:
        super().__init__()
        catalog = etree.parse(str(_CATALOG))
        self._local = {
            entry.get("systemId"): (_CATALOG.parent / entry.get("uri", "")).resolve()
            for entry in catalog.iter(f"{{{_CATALOG_NS}}}system")
        }

    def resolve(  # type: ignore[override]
        self, system_url: str, public_id: str, context: Any
    ) -> Any:
        if system_url.startswith(("http://", "https://")):
            local = self._local.get(system_url)
            if local is None:
                raise OSError(f"no catalog entry for {system_url}")
            return self.resolve_filename(str(local), context)  # type: ignore[attr-defined]
        return None


@cache
def _schema() -> etree.XMLSchema:
    if not _CATALOG.is_file() or not _SPEC_DIR.is_dir():
        raise SchemaUnavailableError(
            "the DODP v1 schemas are only available in a source checkout or sdist"
        )
    parser = etree.XMLParser(no_network=True, load_dtd=False)
    parser.resolvers.add(_CatalogResolver())
    # The schema embedded in the WSDL holds the operation messages and the
    # faults and includes the types schema; lxml cannot read a WSDL itself, so
    # the schema element is lifted out and keeps the WSDL's base URL.
    wsdl = etree.parse(str(_WSDL), parser)
    embedded = wsdl.find(f".//{{{_XSD}}}schema")
    if embedded is None:
        raise SchemaUnavailableError("the DODP v1 WSDL has no embedded schema")
    document = etree.fromstring(
        etree.tostring(embedded), parser, base_url=_WSDL.as_uri()
    )
    return etree.XMLSchema(document)


def validate_document(document: str | bytes) -> tuple[SchemaFinding, ...]:
    """Validate one DODP v1 document and return what is wrong with it.

    The findings are values; an empty tuple means the document is valid. A
    document that is not well-formed XML is reported as a single finding.
    """
    data = document.encode() if isinstance(document, str) else document
    schema = _schema()
    try:
        tree = etree.fromstring(data, etree.XMLParser(no_network=True))
    except etree.XMLSyntaxError as error:
        return (SchemaFinding(line=error.lineno or 0, message=str(error.msg)),)
    schema.validate(tree)
    return tuple(
        SchemaFinding(line=entry.line, message=entry.message)
        for entry in schema.error_log  # type: ignore[attr-defined]
    )
