"""Reading the ports of a Service WSDL without trusting it (ADR 0002).

The document is untrusted input: no DTD, no entities, no network. `import`
elements are never followed; the abstract DODP WSDL they point at is known
here, so its binding is recognised by name instead of being fetched.
"""

from __future__ import annotations

from lxml import etree

from dod.application import WsdlError, WsdlPort

_WSDL = "http://schemas.xmlsoap.org/wsdl/"
_SOAP11 = "http://schemas.xmlsoap.org/wsdl/soap/"
_DODP = "http://www.daisy.org/ns/daisy-online/"
_PORT_TYPE = (_DODP, "daisy-online")
# The binding of the abstract DODP WSDL that a Service's own WSDL imports.
_BUNDLED_BINDING = (_DODP, "DaisyOnlineService")

type _QName = tuple[str | None, str]


def _qname(element: etree._Element, value: str | None) -> _QName | None:
    if not value:
        return None
    prefix, _, local = value.strip().rpartition(":")
    namespace = element.nsmap.get(prefix or None)
    return namespace, local


def parse_wsdl(content: bytes) -> tuple[WsdlPort, ...]:
    """The `port` elements of a WSDL, each marked as DODP and SOAP 1.1 or not."""
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
        remove_comments=True,
        remove_pis=True,
    )
    try:
        root = etree.fromstring(content, parser)
    except etree.XMLSyntaxError:
        raise WsdlError("the document is not well-formed XML") from None
    docinfo = root.getroottree().docinfo
    # lxml-stubs does not declare `doctype`.
    if docinfo.doctype or docinfo.internalDTD:  # type: ignore[union-attr]
        raise WsdlError("the document has a DTD, which is refused")
    if root.tag != f"{{{_WSDL}}}definitions":
        raise WsdlError("the document is not a WSDL 1.1 definitions element")
    target = root.get("targetNamespace")
    local_bindings: dict[_QName, tuple[bool, bool]] = {}
    for binding in root.iter(f"{{{_WSDL}}}binding"):
        port_type = _qname(binding, binding.get("type"))
        soap = binding.find(f"{{{_SOAP11}}}binding") is not None
        local_bindings[(target, binding.get("name") or "")] = (
            port_type == _PORT_TYPE,
            soap,
        )
    local_bindings.setdefault(_BUNDLED_BINDING, (True, True))
    ports: list[WsdlPort] = []
    for port in root.iter(f"{{{_WSDL}}}port"):
        key = _qname(port, port.get("binding"))
        is_dodp, bound_soap = (
            local_bindings.get(key, (False, False)) if key else (False, False)
        )
        address = port.find(f"{{{_SOAP11}}}address")
        ports.append(
            WsdlPort(
                name=port.get("name") or "",
                address=(address.get("location") or "") if address is not None else "",
                is_dodp=is_dodp,
                is_soap11=bound_soap and address is not None,
            )
        )
    return tuple(ports)
