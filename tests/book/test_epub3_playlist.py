"""`dod.domain.book`: the Playlist of an EPUB 3 book with media overlays (ADR 0009).

Pure functions against synthetic fixtures; no files, no audio, no Service.
"""

from collections.abc import Mapping

import pytest

from dod.domain.book import BookError, BookErrorKind, Clip, epub3_playlist

CONTAINER = (
    b'<?xml version="1.0"?><container version="1.0" '
    b'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
    b'<rootfile full-path="OEBPS/book.opf" '
    b'media-type="application/oebps-package+xml"/></rootfiles></container>'
)


def opf(items: str, spine: str) -> bytes:
    return (
        '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
        'version="3.0"><metadata/>'
        f"<manifest>{items}</manifest><spine>{spine}</spine></package>"
    ).encode()


def item(id: str, href: str, overlay: str | None = None) -> str:
    extra = f' media-overlay="{overlay}"' if overlay else ""
    return f'<item id="{id}" href="{href}" media-type="x/y"{extra}/>'


def refs(*ids: str) -> str:
    return "".join(f'<itemref idref="{i}"/>' for i in ids)


def overlay(*bodies: str) -> bytes:
    return (
        '<smil xmlns="http://www.w3.org/ns/SMIL" version="3.0"><body><seq>'
        f"{''.join(bodies)}</seq></body></smil>"
    ).encode()


def par(src: str, begin: str | None = None, end: str | None = None) -> str:
    times = ""
    if begin is not None:
        times += f' clipBegin="{begin}"'
    if end is not None:
        times += f' clipEnd="{end}"'
    return f'<par><text src="c.xhtml#x"/><audio src="{src}"{times}/></par>'


def book(package: bytes) -> dict[str, bytes]:
    return {"META-INF/container.xml": CONTAINER, "OEBPS/book.opf": package}


def reader(files: Mapping[str, bytes]):  # type: ignore[no-untyped-def]
    return files.get


def test_the_spine_and_media_overlays_give_the_order_of_the_clips() -> None:
    files = book(
        opf(
            item("c1", "c1.xhtml", "o1")
            + item("c2", "c2.xhtml", "o2")
            + item("o1", "o1.smil")
            + item("o2", "o2.smil"),
            refs("c2", "c1"),
        )
    )
    files["OEBPS/o1.smil"] = overlay(par("a.mp3", "0:00:00.5", "0:00:01.5"))
    files["OEBPS/o2.smil"] = overlay(par("b.mp3", "2s", "3s"))

    playlist = epub3_playlist(reader(files))

    assert playlist.clips == (
        Clip("OEBPS/b.mp3", 2.0, 3.0),
        Clip("OEBPS/a.mp3", 0.5, 1.5),
    )


def test_audio_paths_may_climb_out_of_the_overlay_directory_but_not_the_book() -> None:
    files = book(
        opf(item("c", "text/c.xhtml", "o") + item("o", "smil/o.smil"), refs("c")),
    )
    files["OEBPS/smil/o.smil"] = overlay(par("../audio/a%20b.mp3", "0s", "1s"))

    assert epub3_playlist(reader(files)).clips == (
        Clip("OEBPS/audio/a b.mp3", 0.0, 1.0),
    )

    files["OEBPS/smil/o.smil"] = overlay(par("../../../x.mp3"))
    with pytest.raises(BookError) as raised:
        epub3_playlist(reader(files))
    assert raised.value.kind is BookErrorKind.UNSAFE_PATH


def test_missing_clip_times_and_nested_seq_keep_document_order() -> None:
    files = book(opf(item("c", "c.xhtml", "o") + item("o", "o.smil"), refs("c")))
    files["OEBPS/o.smil"] = overlay(
        par("a.mp3"),
        f"<seq><par><seq>{par('b.mp3', '1s')[5:-6]}</seq></par></seq>",
        par("c.mp3", end="2s"),
    )

    assert epub3_playlist(reader(files)).clips == (
        Clip("OEBPS/a.mp3"),
        Clip("OEBPS/b.mp3", 1.0, None),
        Clip("OEBPS/c.mp3", 0.0, 2.0),
    )


def test_an_overlay_linked_twice_is_played_once() -> None:
    files = book(
        opf(
            item("c1", "c1.xhtml", "o")
            + item("c2", "c2.xhtml", "o")
            + item("o", "o.smil"),
            refs("c1", "c2", "c1"),
        )
    )
    files["OEBPS/o.smil"] = overlay(par("a.mp3", "0s", "1s"))

    assert epub3_playlist(reader(files)).clips == (Clip("OEBPS/a.mp3", 0.0, 1.0),)


def test_spine_items_without_overlay_are_skipped_but_a_book_with_none_is_refused() -> (
    None
):
    files = book(
        opf(
            item("t", "t.xhtml") + item("c", "c.xhtml", "o") + item("o", "o.smil"),
            refs("t", "c"),
        )
    )
    files["OEBPS/o.smil"] = overlay(par("a.mp3"))
    assert epub3_playlist(reader(files)).clips == (Clip("OEBPS/a.mp3"),)

    text_only = book(opf(item("t", "t.xhtml"), refs("t")))
    with pytest.raises(BookError) as raised:
        epub3_playlist(reader(text_only))
    assert raised.value.kind is BookErrorKind.NO_SMIL
    assert "media overlay" in str(raised.value)


def test_an_overlay_with_no_audio_is_an_error_not_silence() -> None:
    files = book(opf(item("c", "c.xhtml", "o") + item("o", "o.smil"), refs("c")))
    files["OEBPS/o.smil"] = overlay("<par><text src='c.xhtml#x'/></par>")

    with pytest.raises(BookError) as raised:
        epub3_playlist(reader(files))

    assert raised.value.kind is BookErrorKind.NO_SMIL
    assert "no audio" in str(raised.value)


@pytest.mark.parametrize(
    ("files", "kind"),
    [
        ({}, BookErrorKind.NO_SMIL),
        ({"META-INF/container.xml": b"<container/>"}, BookErrorKind.MALFORMED),
        ({"META-INF/container.xml": CONTAINER}, BookErrorKind.MISSING_FILE),
        (
            book(opf(item("c", "c.xhtml", "nope"), refs("c"))),
            BookErrorKind.MALFORMED,
        ),
        (
            book(opf(item("c", "c.xhtml", "o") + item("o", "o.smil"), refs("c"))),
            BookErrorKind.MISSING_FILE,
        ),
        (
            book(opf(item("c", "c.xhtml", "o") + item("o", "/etc/x.smil"), refs("c"))),
            BookErrorKind.UNSAFE_PATH,
        ),
        (book(b"<package"), BookErrorKind.MALFORMED),
    ],
)
def test_a_broken_book_is_a_typed_error(
    files: dict[str, bytes], kind: BookErrorKind
) -> None:
    with pytest.raises(BookError) as raised:
        epub3_playlist(reader(files))

    assert raised.value.kind is kind


def test_entities_are_not_expanded() -> None:
    files = book(b'<!DOCTYPE p [<!ENTITY x "y">]><package/>')

    with pytest.raises(BookError) as raised:
        epub3_playlist(reader(files))

    assert raised.value.kind is BookErrorKind.MALFORMED
