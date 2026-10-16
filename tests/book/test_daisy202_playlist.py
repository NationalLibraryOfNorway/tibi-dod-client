"""`dod.domain.book`: the Playlist of a DAISY 2.02 book, from bytes (ADR 0009).

Pure functions against synthetic fixtures; no files, no audio, no Service.
"""

from collections.abc import Mapping

import pytest

from dod.domain.book import BookError, BookErrorKind, Clip, daisy202_playlist


def smil(*bodies: str) -> bytes:
    inner = "".join(bodies)
    return (
        '<?xml version="1.0"?><smil><head><meta name="dc:title" content="t"/></head>'
        f"<body><seq>{inner}</seq></body></smil>"
    ).encode()


def par(src: str, begin: str | None = None, end: str | None = None) -> str:
    times = ""
    if begin is not None:
        times += f' clip-begin="{begin}"'
    if end is not None:
        times += f' clip-end="{end}"'
    return f'<par><text src="ncc.html#x"/><seq><audio src="{src}"{times}/></seq></par>'


def master(*refs: str) -> bytes:
    items = "".join(f'<ref src="{ref}"/>' for ref in refs)
    return (f"<smil><head/><body><seq>{items}</seq></body></smil>").encode()


def ncc(*hrefs: str) -> bytes:
    items = "".join(f'<h1><a href="{href}">Chapter</a></h1>' for href in hrefs)
    return (
        '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml">'
        f"<head><title>t</title></head><body>{items}</body></html>"
    ).encode()


def reader(files: Mapping[str, bytes]):  # type: ignore[no-untyped-def]
    return files.get


def test_master_smil_gives_the_order_of_the_content_smil_files() -> None:
    files = {
        "master.smil": master("b.smil", "a.smil"),
        "a.smil": smil(par("a.mp3", "npt=0.000s", "npt=1.500s")),
        "b.smil": smil(par("b.mp3", "npt=2.000s", "npt=3.000s")),
        "ncc.html": ncc("a.smil#1", "b.smil#2"),
    }

    playlist = daisy202_playlist(reader(files))

    assert playlist.clips == (
        Clip("b.mp3", 2.0, 3.0),
        Clip("a.mp3", 0.0, 1.5),
    )


def test_a_book_with_neither_master_smil_nor_ncc_is_refused_not_guessed() -> None:
    files = {"a.mp3": b"", "b.mp3": b""}

    with pytest.raises(BookError) as raised:
        daisy202_playlist(reader(files))

    assert raised.value.kind is BookErrorKind.NO_SMIL


def test_without_master_smil_the_order_ncc_html_first_links_them_in_is_used() -> None:
    files = {
        "ncc.html": ncc("b.smil#1", "a.smil#2", "b.smil#3"),
        "a.smil": smil(par("a.mp3", "npt=0s", "npt=1s")),
        "b.smil": smil(par("b.mp3", "npt=0s", "npt=2s")),
    }

    playlist = daisy202_playlist(reader(files))

    assert [clip.file for clip in playlist.clips] == ["b.mp3", "a.mp3"]


def test_a_smil_that_is_linked_twice_is_played_once() -> None:
    files = {
        "master.smil": master("a.smil", "a.smil"),
        "a.smil": smil(par("a.mp3", "npt=0s", "npt=1s")),
    }

    assert len(daisy202_playlist(reader(files)).clips) == 1


def test_a_smil_the_ncc_links_to_in_a_subdirectory_resolves_its_audio_there() -> None:
    files = {
        "ncc.html": ncc("part/a.smil#1"),
        "part/a.smil": smil(par("a.mp3", "npt=0s", "npt=1s")),
    }

    assert daisy202_playlist(reader(files)).clips == (Clip("part/a.mp3", 0.0, 1.0),)


def test_nested_seq_and_par_are_followed_in_document_order() -> None:
    nested = (
        "<seq><par><seq><audio src='a.mp3' clip-begin='npt=0s' clip-end='npt=1s'/>"
        "</seq></par><seq><par><audio src='b.mp3' clip-begin='npt=0s' "
        "clip-end='npt=1s'/></par><par><audio src='c.mp3' clip-begin='npt=0s' "
        "clip-end='npt=1s'/></par></seq></seq>"
    )
    files = {"master.smil": master("a.smil"), "a.smil": smil(nested)}

    assert [c.file for c in daisy202_playlist(reader(files)).clips] == [
        "a.mp3",
        "b.mp3",
        "c.mp3",
    ]


@pytest.mark.parametrize(
    ("begin", "end", "expected"),
    [
        ("npt=1.500s", "npt=2.250s", (1.5, 2.25)),
        ("npt=1.5", "npt=2", (1.5, 2.0)),
        ("1.5s", "2s", (1.5, 2.0)),
        ("npt=0:01:02.5", "npt=0:01:03", (62.5, 63.0)),
        ("npt=01:02.5", "npt=01:03", (62.5, 63.0)),
        ("npt=1500ms", "npt=2min", (1.5, 120.0)),
        ("npt=0.5h", "npt=1h", (1800.0, 3600.0)),
        (None, "npt=2s", (0.0, 2.0)),
        ("npt=1s", None, (1.0, None)),
        (None, None, (0.0, None)),
    ],
)
def test_clip_times_are_read_and_missing_ones_mean_from_start_and_to_the_end(
    begin: str | None, end: str | None, expected: tuple[float, float | None]
) -> None:
    files = {"master.smil": master("a.smil"), "a.smil": smil(par("a.mp3", begin, end))}

    (clip,) = daisy202_playlist(reader(files)).clips

    assert (clip.begin, clip.end) == expected


def test_smil_2_clip_attributes_are_read_too() -> None:
    content = smil("<audio src='a.mp3' clipBegin='npt=1s' clipEnd='npt=2s'/>")
    files = {"master.smil": master("a.smil"), "a.smil": content}

    assert daisy202_playlist(reader(files)).clips == (Clip("a.mp3", 1.0, 2.0),)


@pytest.mark.parametrize("bad", ["npt=abc", "npt=-1s", "npt=nan", "npt=1:2:3:4", ""])
def test_a_clip_time_that_cannot_be_read_is_a_malformed_book(bad: str) -> None:
    files = {"master.smil": master("a.smil"), "a.smil": smil(par("a.mp3", bad, None))}

    with pytest.raises(BookError) as raised:
        daisy202_playlist(reader(files))

    assert raised.value.kind is BookErrorKind.MALFORMED


def test_a_clip_that_ends_before_it_begins_is_a_malformed_book() -> None:
    files = {
        "master.smil": master("a.smil"),
        "a.smil": smil(par("a.mp3", "npt=2s", "npt=1s")),
    }

    with pytest.raises(BookError) as raised:
        daisy202_playlist(reader(files))

    assert raised.value.kind is BookErrorKind.MALFORMED


def test_a_listed_smil_that_is_missing_is_named() -> None:
    files = {"master.smil": master("gone.smil")}

    with pytest.raises(BookError) as raised:
        daisy202_playlist(reader(files))

    assert raised.value.kind is BookErrorKind.MISSING_FILE
    assert "gone.smil" in str(raised.value)


def test_an_ncc_with_no_smil_links_has_no_order_to_give() -> None:
    files = {"ncc.html": ncc("chapter.html#1"), "a.mp3": b""}

    with pytest.raises(BookError) as raised:
        daisy202_playlist(reader(files))

    assert raised.value.kind is BookErrorKind.NO_SMIL


def test_smil_files_without_audio_give_no_playlist() -> None:
    files = {"master.smil": master("a.smil"), "a.smil": smil("<text src='x#y'/>")}

    with pytest.raises(BookError) as raised:
        daisy202_playlist(reader(files))

    assert raised.value.kind is BookErrorKind.NO_SMIL


def test_file_name_order_is_never_a_fallback() -> None:
    files = {"b.mp3": b"", "a.mp3": b"", "ncc.html": ncc()}

    with pytest.raises(BookError):
        daisy202_playlist(reader(files))


@pytest.mark.parametrize(
    "src",
    [
        "../evil.mp3",
        "/etc/passwd",
        "C:/evil.mp3",
        "a\\b.mp3",
        "%2e%2e/evil.mp3",
        "sub//a.mp3",
        "",
    ],
)
def test_an_audio_path_that_is_not_a_safe_relative_path_is_refused(src: str) -> None:
    files = {"master.smil": master("a.smil"), "a.smil": smil(par(src, None, None))}

    with pytest.raises(BookError) as raised:
        daisy202_playlist(reader(files))

    assert raised.value.kind is BookErrorKind.UNSAFE_PATH


def test_a_smil_path_that_leaves_the_book_is_refused_before_it_is_read() -> None:
    asked: list[str] = []

    def read(path: str) -> bytes | None:
        asked.append(path)
        return master("../outside.smil") if path == "master.smil" else None

    with pytest.raises(BookError) as raised:
        daisy202_playlist(read)

    assert raised.value.kind is BookErrorKind.UNSAFE_PATH
    assert asked == ["master.smil"]


def test_a_fragment_on_a_smil_link_is_not_part_of_the_path() -> None:
    files = {
        "ncc.html": ncc("a.smil#id"),
        "a.smil": smil(par("a.mp3", "npt=0s", "npt=1s")),
    }

    assert daisy202_playlist(reader(files)).clips == (Clip("a.mp3", 0.0, 1.0),)


def test_audio_paths_are_percent_decoded_like_a_local_uri() -> None:
    files = {
        "master.smil": master("a.smil"),
        "a.smil": smil(par("my%20file.mp3", "npt=0s", "npt=1s")),
    }

    assert daisy202_playlist(reader(files)).clips[0].file == "my file.mp3"


def test_malformed_xml_is_a_typed_error_not_a_crash() -> None:
    files = {"master.smil": b"<smil><seq></smil>"}

    with pytest.raises(BookError) as raised:
        daisy202_playlist(reader(files))

    assert raised.value.kind is BookErrorKind.MALFORMED
    assert "master.smil" in str(raised.value)


def test_a_document_that_declares_entities_is_refused_not_expanded() -> None:
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE smil [<!ENTITY a "AAAA">'
        b'<!ENTITY b "&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;">]>'
        b'<smil><body><seq><audio src="&c;.mp3"/></seq></body></smil>'
    )
    files = {"master.smil": master("a.smil"), "a.smil": bomb}

    with pytest.raises(BookError) as raised:
        daisy202_playlist(reader(files))

    assert raised.value.kind is BookErrorKind.MALFORMED


def test_an_external_dtd_is_neither_fetched_nor_needed() -> None:
    # Port 9 (discard) on loopback: a fetch would fail loudly or hang.
    external = (
        b'<?xml version="1.0"?><!DOCTYPE smil SYSTEM "http://127.0.0.1:9/x.dtd">'
        b'<smil><body><seq><audio src="a.mp3"/></seq></body></smil>'
    )
    files = {"master.smil": master("a.smil"), "a.smil": external}

    assert daisy202_playlist(reader(files)).clips == (Clip("a.mp3", 0.0, None),)


def test_files_lists_the_distinct_audio_files_in_playing_order() -> None:
    files = {
        "master.smil": master("a.smil"),
        "a.smil": smil(
            par("x.mp3", "npt=0s", "npt=1s"),
            par("y.mp3", "npt=0s", "npt=1s"),
            par("x.mp3", "npt=1s", "npt=2s"),
        ),
    }

    assert daisy202_playlist(reader(files)).files == ("x.mp3", "y.mp3")
