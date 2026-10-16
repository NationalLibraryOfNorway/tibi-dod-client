"""Synthetic documents shared by the tests."""

BOOKMARK_NS = "http://www.daisy.org/z3986/2005/bookmark/"

KEY_EXCHANGE = (
    '<KeyExchange xmlns="http://www.daisy.org/DRM/2005/KeyExchange" '
    'xmlns:ds="http://www.w3.org/2000/09/xmldsig#">'
    '<Issuer uid="DAISY.synthetic">Synthetic issuer</Issuer>'
    "<Keys><ds:KeyInfo><ds:KeyName>synthetic-key</ds:KeyName></ds:KeyInfo>"
    '<UAK issuerID="synthetic" collectionID="synthetic">c3ludGhldGlj</UAK>'
    "</Keys></KeyExchange>"
)


def bookmark_set(
    uid: str,
    *,
    title: str = "Synthetic title",
    lastmark: str = "",
    bookmarks: int = 0,
    hilites: int = 0,
) -> str:
    """A schema-valid `bookmarkSet` document."""
    marks = "".join(
        f'<bookmark label="mark {n}"><ncxRef>n{n}</ncxRef><URI>s{n}.smil#par1</URI>'
        "<timeOffset>1.5</timeOffset></bookmark>"
        for n in range(bookmarks)
    )
    lights = "".join(
        "<hilite><hiliteStart><ncxRef>a</ncxRef><URI>s.smil#p</URI>"
        "<charOffset>1</charOffset></hiliteStart><hiliteEnd><ncxRef>a</ncxRef>"
        "<URI>s.smil#p</URI><charOffset>9</charOffset></hiliteEnd></hilite>"
        for _ in range(hilites)
    )
    return (
        f'<bookmarkSet xmlns="{BOOKMARK_NS}"><title><text>{title}</text></title>'
        f"<uid>{uid}</uid>{lastmark}{marks}{lights}</bookmarkSet>"
    )


def questions(body: str) -> str:
    """A `questions` document around `body`."""
    return (
        f'<questions xmlns="http://www.daisy.org/ns/daisy-online/">{body}</questions>'
    )


def label(text: str) -> str:
    return f'<label xml:lang="en"><text>{text}</text></label>'


def multiple_choice(question_id: str, text: str, *choices: tuple[str, str]) -> str:
    """A `multipleChoiceQuestion`; `choices` are (id, label) pairs."""
    listed = "".join(
        f'<choice id="{choice_id}">{label(choice_text)}</choice>'
        for choice_id, choice_text in choices
    )
    return (
        f'<multipleChoiceQuestion id="{question_id}">{label(text)}'
        f"<choices>{listed}</choices></multipleChoiceQuestion>"
    )


def input_question(question_id: str, text: str, *types: str) -> str:
    """An `inputQuestion` accepting the given input types."""
    listed = "".join(f'<input type="{kind}"/>' for kind in types)
    return (
        f'<inputQuestion id="{question_id}"><inputTypes>{listed}</inputTypes>'
        f"{label(text)}</inputQuestion>"
    )
