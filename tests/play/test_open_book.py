"""`open_book`: the Playlist of a downloaded DAISY 2.02 book on disk (ADR 0009)."""

from pathlib import Path

import pytest

from dod.application import PlayRefused, open_book
from dod.domain.book import BookError, BookErrorKind, Clip

MASTER = b'<smil><body><seq><ref src="a.smil"/></seq></body></smil>'
SMIL = b'<smil><body><seq><audio src="a.wav" clip-end="npt=1s"/></seq></body></smil>'


def test_the_playlist_is_read_from_the_files_of_the_directory(tmp_path: Path) -> None:
    (tmp_path / "master.smil").write_bytes(MASTER)
    (tmp_path / "a.smil").write_bytes(SMIL)

    assert open_book(tmp_path).clips == (Clip("a.wav", 0.0, 1.0),)


def test_a_book_that_was_never_downloaded_says_so(tmp_path: Path) -> None:
    with pytest.raises(PlayRefused) as raised:
        open_book(tmp_path / "nope")

    assert "dod download" in str(raised.value)


def test_a_book_without_smil_is_a_typed_error(tmp_path: Path) -> None:
    (tmp_path / "a.wav").write_bytes(b"x")

    with pytest.raises(BookError) as raised:
        open_book(tmp_path)

    assert raised.value.kind is BookErrorKind.NO_SMIL


def test_a_smil_that_is_far_too_large_is_not_read(tmp_path: Path) -> None:
    (tmp_path / "master.smil").write_bytes(b"<smil>" + b" " * (17 * 1024 * 1024))

    with pytest.raises(BookError) as raised:
        open_book(tmp_path)

    assert raised.value.kind is BookErrorKind.TOO_LARGE


def test_an_epub_3_book_is_played_in_the_order_of_its_spine(tmp_path: Path) -> None:
    (tmp_path / "META-INF").mkdir()
    (tmp_path / "META-INF" / "container.xml").write_bytes(
        b'<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        b'<rootfiles><rootfile full-path="book.opf"/></rootfiles></container>'
    )
    (tmp_path / "book.opf").write_bytes(
        b'<package xmlns="http://www.idpf.org/2007/opf"><manifest>'
        b'<item id="c" href="c.xhtml" media-overlay="o"/>'
        b'<item id="o" href="o.smil"/></manifest>'
        b'<spine><itemref idref="c"/></spine></package>'
    )
    (tmp_path / "o.smil").write_bytes(
        b'<smil><body><seq><par><audio src="a.wav" clipEnd="2s"/></par></seq>'
        b"</body></smil>"
    )

    assert open_book(tmp_path).clips == (Clip("a.wav", 0.0, 2.0),)


def test_a_text_only_epub_3_book_is_refused_not_played_in_silence(
    tmp_path: Path,
) -> None:
    (tmp_path / "META-INF").mkdir()
    (tmp_path / "META-INF" / "container.xml").write_bytes(
        b'<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        b'<rootfiles><rootfile full-path="book.opf"/></rootfiles></container>'
    )
    (tmp_path / "book.opf").write_bytes(
        b'<package xmlns="http://www.idpf.org/2007/opf"><manifest>'
        b'<item id="c" href="c.xhtml"/></manifest>'
        b'<spine><itemref idref="c"/></spine></package>'
    )

    with pytest.raises(BookError) as raised:
        open_book(tmp_path)

    assert raised.value.kind is BookErrorKind.NO_SMIL
    assert "media overlay" in str(raised.value)
