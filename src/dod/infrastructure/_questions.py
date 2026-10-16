"""Menus (`questions`) as XML: reading them leniently.

Shared by the HTTP adapter and the in-memory adapter. Everything is read as the
Service sent it: IDs are not trimmed or checked (some Services use choice IDs
with spaces, against `xs:NMTOKEN`) and anything missing is empty.
"""

from __future__ import annotations

from lxml import etree

from dod.domain.v1 import (
    Choice,
    InputQuestion,
    MultipleChoiceQuestion,
    Question,
    Questions,
)

DODP_NS = "http://www.daisy.org/ns/daisy-online/"
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def _name(name: str) -> str:
    return f"{{{DODP_NS}}}{name}"


def _label(element: etree._Element) -> tuple[str, str | None]:
    label = element.find(_name("label"))
    if label is None:
        return "", None
    return (label.findtext(_name("text")) or ""), label.get(_XML_LANG)


def parse_questions(text: str) -> etree._Element:
    """The root of a `questions` document, parsed without resolving entities or
    touching the network. Raises `ValueError` when it is not one."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    try:
        root = etree.fromstring(text.encode("utf-8"), parser)
    except etree.XMLSyntaxError as error:
        raise ValueError(f"not well-formed XML: {error.msg}") from error
    if root.tag != _name("questions"):
        raise ValueError("the root element is not a questions element")
    return root


def questions_from_element(element: etree._Element) -> Questions:
    """The `questions` element as a model."""
    found: list[Question] = []
    for child in element:
        if child.tag == _name("multipleChoiceQuestion"):
            text, lang = _label(child)
            found.append(
                MultipleChoiceQuestion(
                    id=child.get("id") or "",
                    label=text,
                    choices=tuple(
                        Choice(
                            id=choice.get("id") or "",
                            label=_label(choice)[0],
                            lang=_label(choice)[1],
                        )
                        for choice in child.iterfind(
                            f"{_name('choices')}/{_name('choice')}"
                        )
                    ),
                    allow_multiple_selections=(
                        (child.get("allowMultipleSelections") or "").strip().lower()
                        in {"true", "1"}
                    ),
                    lang=lang,
                )
            )
        elif child.tag == _name("inputQuestion"):
            text, lang = _label(child)
            found.append(
                InputQuestion(
                    id=child.get("id") or "",
                    label=text,
                    input_types=tuple(
                        item.get("type") or ""
                        for item in child.iterfind(
                            f"{_name('inputTypes')}/{_name('input')}"
                        )
                    ),
                    lang=lang,
                )
            )
    reference = element.find(_name("contentListRef"))
    label = element.find(_name("label"))
    return Questions(
        questions=tuple(found),
        content_list_ref=None if reference is None else (reference.text or ""),
        label=None if label is None else _label(element)[0],
    )
