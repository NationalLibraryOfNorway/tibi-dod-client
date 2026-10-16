"""`dod play` through the CLI boundary, after `logon` and `download` (ADR 0009).

The commands run in-process against the fake Service on localhost, with the
`Player` replaced by a fake: no audio device is ever opened. Files are
synthetic. The password goes in on stdin for the commands that reach the
Service; `play` itself never does.
"""

import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dod.application import PlayerUnavailable
from dod.domain.v1 import ContentResource
from dod.infrastructure import (
    FileConfigStore,
    FileSessionStore,
    HttpFetcher,
    HttpServicePort,
    parse_wsdl,
)
from dod.presentation import create_app
from support import PASSWORD, FakeService
from support._fake_player import FakePlayer

USER = "synthetic-user"
MASTER = (
    b'<smil><head/><body><seq><ref src="b.smil"/><ref src="a.smil"/></seq>'
    b"</body></smil>"
)
SMIL_A = b'<smil><body><seq><par><audio src="a.wav"/></par></seq></body></smil>'
SMIL_B = (
    b'<smil><body><seq><par><seq><audio src="b.wav" clip-begin="npt=0s" '
    b'clip-end="npt=4s"/></seq></par><par><audio src="b.wav" clip-begin="npt=4s" '
    b'clip-end="npt=8s"/></par></seq></body></smil>'
)
DURATIONS = {"a.wav": 60.0, "b.wav": 8.0}


def resource(name: str, body: bytes, mime: str = "application/smil") -> ContentResource:
    return ContentResource(
        uri=f"files/{name}", mime_type=mime, size=len(body), local_uri=name
    )


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD)
    book = {
        "master.smil": MASTER,
        "a.smil": SMIL_A,
        "b.smil": SMIL_B,
        "a.wav": b"synthetic-a",
        "b.wav": b"synthetic-b",
    }
    fake.offer_resources("book0", [resource(name, body) for name, body in book.items()])
    for name, body in book.items():
        fake.offer_file(f"files/{name}", body)
    yield fake
    fake.stop()


class Run:
    """One in-process app per test: Sessions and books under `tmp_path`."""

    def __init__(
        self,
        service: FakeService,
        tmp_path: Path,
        player: Callable[[], FakePlayer] | None = None,
    ) -> None:
        self.service = service
        self.tmp_path = tmp_path
        self.player = FakePlayer(DURATIONS, step=1.0)
        self.open_player = player or (lambda: self.player)
        self.config = tmp_path / "config.toml"
        self.config.write_text(
            f'[environments.test]\nurl = "{service.url}"\ninsecure = true\n'
            f'username = "{USER}"\n',
            encoding="utf-8",
        )
        if sys.platform != "win32":
            self.config.chmod(0o600)

    @property
    def data(self) -> Path:
        return self.tmp_path / "data"

    def __call__(self, *args: str, input: str = PASSWORD + "\n") -> Any:
        app = create_app(
            HttpServicePort,
            FileConfigStore(),
            HttpFetcher(),
            parse_wsdl,
            session_store=FileSessionStore.from_environ(
                {"DOD_STATE_DIR": str(self.tmp_path / "state")}
            ),
            data_dir=self.data,
            open_player=self.open_player,
        )
        return CliRunner(env={"NO_COLOR": "1", "COLUMNS": "100"}).invoke(
            app,
            [*args, "--config", str(self.config), "--env", "test"]
            + (["--password-stdin"] if args[0] != "play" else []),
            input=input,
        )


@pytest.fixture
def run(service: FakeService, tmp_path: Path) -> Run:
    return Run(service, tmp_path)


def downloaded(run: Run) -> None:
    assert run("logon").exit_code == 0
    assert run("download", "book0").exit_code == 0


def test_logon_download_play_plays_the_books_files_in_smil_order_and_exits_0(
    run: Run,
) -> None:
    downloaded(run)
    requests = len(run.service.requests)
    fetches = len(run.service.fetches)

    result = run("play", "book0")

    assert result.exit_code == 0, result.output
    # master.smil lists b.smil first: the order is not the file-name order.
    assert run.player.started == [("b.wav", 0.0), ("a.wav", 0.0)]
    lines = result.stdout.splitlines()
    assert lines[0].startswith("file 1 of 2: b.wav  elapsed 00:00:00 of 00:01:08")
    assert any(line.startswith("file 2 of 2: a.wav") for line in lines)
    assert lines[-1] == "finished: 00:01:08 of 00:01:08"
    assert run.player.closed
    # Local files only: playing never reaches the Service.
    assert len(run.service.requests) == requests
    assert len(run.service.fetches) == fetches


def test_pause_resume_next_and_previous_move_by_clip(run: Run) -> None:
    downloaded(run)

    result = run("play", "book0", input="p\np\nn\nb\nq\n")

    assert result.exit_code == 0, result.output
    assert run.player.started == [
        ("b.wav", 0.0),  # start
        ("b.wav", 0.0),  # resume after the pause
        ("b.wav", 4.0),  # n: the next Clip
        ("b.wav", 0.0),  # b: the previous Clip
    ]
    assert "paused" in result.stdout
    assert result.stdout.splitlines()[-1].startswith("stopped: ")


def test_a_jump_of_30_seconds_moves_in_playlist_time_forward_and_back(run: Run) -> None:
    downloaded(run)

    result = run("play", "book0", input="f\nr\nq\n")

    assert result.exit_code == 0, result.output
    # 30 s on is 22 s into a.wav (b.wav is 8 s); 30 s back is the start again.
    assert run.player.started == [("b.wav", 0.0), ("a.wav", 22.0), ("b.wav", 0.0)]


def test_an_empty_line_shows_the_status_and_an_unknown_command_says_what_exists(
    run: Run,
) -> None:
    downloaded(run)

    result = run("play", "book0", input="\nxyz\nq\n")

    assert result.exit_code == 0, result.output
    assert result.stdout.count("file 1 of 2: b.wav") == 2  # at the start, on request
    assert "unknown command 'xyz'" in result.stderr


def test_a_book_without_smil_is_refused_with_an_explanation(
    service: FakeService, tmp_path: Path
) -> None:
    service.offer_resources("audio", [resource("a.wav", b"x", "audio/wav")])
    service.offer_file("files/a.wav", b"x")
    run = Run(service, tmp_path)
    assert run("logon").exit_code == 0
    assert run("download", "audio").exit_code == 0

    result = run("play", "audio")

    assert result.exit_code == 2
    assert "no order to play" in result.stderr
    assert "audioOnly" in result.stderr
    assert run.player.started == []


def test_a_missing_audio_file_is_refused_not_fetched(run: Run) -> None:
    downloaded(run)
    (run.data / "test" / "books" / "book0" / "a.wav").unlink()
    fetches = len(run.service.fetches)

    result = run("play", "book0")

    assert result.exit_code == 2
    assert "a.wav" in result.stderr
    assert "dod download" in result.stderr
    assert run.player.started == []
    assert len(run.service.fetches) == fetches


def test_a_book_that_was_not_downloaded_says_so(run: Run) -> None:
    result = run("play", "book0")

    assert result.exit_code == 2
    assert "dod download" in result.stderr


def test_an_audio_format_the_player_cannot_decode_is_an_error_and_an_observation(
    run: Run,
) -> None:
    downloaded(run)
    run.player.durations.pop("a.wav")

    result = run("play", "book0")

    assert result.exit_code == 2
    assert "a.wav cannot be played" in result.stderr
    assert "observation audio-format" in result.stderr
    assert run.player.started == []


def test_without_miniaudio_play_exits_2_and_explains(run: Run) -> None:
    downloaded(run)

    def unavailable() -> FakePlayer:
        raise PlayerUnavailable("audio playback needs miniaudio: dod-client[play]")

    run.open_player = unavailable

    result = run("play", "book0")

    assert result.exit_code == 2
    assert "dod-client[play]" in result.stderr


def test_the_directory_option_plays_a_book_from_anywhere(
    run: Run, tmp_path: Path
) -> None:
    downloaded(run)
    book = run.data / "test" / "books" / "book0"

    result = run("play", "book0", "--directory", str(book), input="q\n")

    assert result.exit_code == 0, result.output


def test_play_has_text_output_only(run: Run) -> None:
    downloaded(run)

    result = run("play", "book0", "--format", "json")

    assert result.exit_code == 2
    assert "text output" in result.stderr
    assert run.player.started == []


def test_without_an_environment_a_directory_is_required(
    service: FakeService, tmp_path: Path
) -> None:
    app = create_app(
        HttpServicePort,
        FileConfigStore(),
        HttpFetcher(),
        parse_wsdl,
        data_dir=tmp_path / "data",
        open_player=lambda: FakePlayer(),
    )

    result = CliRunner().invoke(app, ["play", "book0"])

    assert result.exit_code == 2
    assert "--directory" in result.stderr


def test_a_text_only_epub_is_refused_with_an_explanation(
    service: FakeService, tmp_path: Path
) -> None:
    container = (
        b'<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        b'<rootfiles><rootfile full-path="book.opf"/></rootfiles></container>'
    )
    package = (
        b'<package xmlns="http://www.idpf.org/2007/opf"><manifest>'
        b'<item id="c" href="c.xhtml"/></manifest>'
        b'<spine><itemref idref="c"/></spine></package>'
    )
    book = {
        "META-INF/container.xml": container,
        "book.opf": package,
        "c.xhtml": b"<html/>",
    }
    service.offer_resources("text", [resource(n, b) for n, b in book.items()])
    for name, body in book.items():
        service.offer_file(f"files/{name}", body)
    run = Run(service, tmp_path)
    assert run("logon").exit_code == 0
    assert run("download", "text").exit_code == 0

    result = run("play", "text")

    assert result.exit_code == 2
    assert "media overlay" in result.stderr
    assert run.player.started == []


def test_an_epub_3_book_with_media_overlays_plays_in_spine_order(
    service: FakeService, tmp_path: Path
) -> None:
    book = {
        "META-INF/container.xml": (
            b'<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            b'<rootfiles><rootfile full-path="OEBPS/book.opf"/></rootfiles>'
            b"</container>"
        ),
        "OEBPS/book.opf": (
            b'<package xmlns="http://www.idpf.org/2007/opf"><manifest>'
            b'<item id="c" href="c.xhtml" media-overlay="o"/>'
            b'<item id="o" href="o.smil"/></manifest>'
            b'<spine><itemref idref="c"/></spine></package>'
        ),
        "OEBPS/o.smil": (
            b'<smil><body><seq><par><audio src="../a.wav"/></par></seq></body></smil>'
        ),
        "a.wav": b"synthetic-a",
    }
    service.offer_resources("epub", [resource(n, b) for n, b in book.items()])
    for name, body in book.items():
        service.offer_file(f"files/{name}", body)
    run = Run(service, tmp_path)
    assert run("logon").exit_code == 0
    assert run("download", "epub").exit_code == 0

    result = run("play", "epub")

    assert result.exit_code == 0, result.stderr
    assert [name for name, _ in run.player.started] == ["a.wav"]


# --fetch-missing (ADR 0009, ADR 0008)


def book_dir(run: Run) -> Path:
    return run.data / "test" / "books" / "book0"


def operations(service: FakeService) -> list[str | None]:
    return [request.operation for request in service.requests]


def audio_fetches(service: FakeService) -> list[str]:
    return [r.path for r in service.fetches if r.path.endswith(".wav")]


def test_fetch_missing_fetches_the_missing_audio_into_the_book_and_plays(
    run: Run,
) -> None:
    downloaded(run)
    (book_dir(run) / "a.wav").unlink()
    fetched = len(audio_fetches(run.service))

    result = run("play", "book0", "--fetch-missing")

    assert result.exit_code == 0, result.output
    assert (book_dir(run) / "a.wav").read_bytes() == b"synthetic-a"
    assert len(audio_fetches(run.service)) == fetched + 1
    assert run.player.started == [("b.wav", 0.0), ("a.wav", 0.0)]
    assert "a.wav" in result.stderr
    assert result.stdout.splitlines()[-1] == "finished: 00:01:08 of 00:01:08"
    assert "issueContent" not in operations(run.service)


def test_without_the_flag_nothing_is_fetched_for_a_missing_file(run: Run) -> None:
    downloaded(run)
    (book_dir(run) / "a.wav").unlink()
    before = len(run.service.requests), len(run.service.fetches)

    result = run("play", "book0")

    assert result.exit_code == 2
    assert "--fetch-missing" in result.stderr
    assert (len(run.service.requests), len(run.service.fetches)) == before
    assert not (book_dir(run) / "a.wav").exists()


def test_fetch_missing_with_every_file_on_disk_does_not_reach_the_service(
    run: Run,
) -> None:
    downloaded(run)
    before = len(run.service.requests), len(run.service.fetches)

    result = run("play", "book0", "--fetch-missing")

    assert result.exit_code == 0, result.output
    assert (len(run.service.requests), len(run.service.fetches)) == before


def test_fetch_missing_fetches_only_the_audio_that_is_missing_one_by_one(
    run: Run,
) -> None:
    downloaded(run)
    (book_dir(run) / "a.wav").unlink()
    (book_dir(run) / "b.wav").unlink()
    before = len(audio_fetches(run.service))

    result = run("play", "book0", "--fetch-missing")

    assert result.exit_code == 0, result.output
    # In playing order (master.smil lists b first), and not the structure files.
    assert audio_fetches(run.service)[before:] == ["/files/b.wav", "/files/a.wav"]


def test_fetch_missing_never_issues_content_and_shows_the_fault_as_it_came(
    run: Run,
) -> None:
    downloaded(run)
    (book_dir(run) / "a.wav").unlink()
    run.service.offer_resources("book0", [], issued=False)

    result = run("play", "book0", "--fetch-missing")

    assert result.exit_code == 1
    assert "invalidParameter: content is not issued" in result.stdout
    assert "issueContent" not in operations(run.service)
    assert run.player.started == []


def test_fetch_missing_refuses_a_file_the_service_does_not_list(run: Run) -> None:
    downloaded(run)
    (book_dir(run) / "a.wav").unlink()
    run.service.offer_resources(
        "book0",
        [resource("master.smil", MASTER), resource("b.smil", SMIL_B)],
    )
    fetched = len(audio_fetches(run.service))

    result = run("play", "book0", "--fetch-missing")

    assert result.exit_code == 2
    assert "a.wav" in result.stderr
    assert len(audio_fetches(run.service)) == fetched
    assert run.player.started == []


def test_fetch_missing_applies_the_untrusted_name_checks_of_download(run: Run) -> None:
    downloaded(run)
    (book_dir(run) / "a.wav").unlink()
    run.service.offer_resources(
        "book0",
        [
            resource("a.wav", b"synthetic-a"),
            ContentResource(
                uri="files/b.wav",
                mime_type="audio/wav",
                size=1,
                local_uri="../escape.wav",
            ),
        ],
    )
    fetched = len(audio_fetches(run.service))

    result = run("play", "book0", "--fetch-missing")

    assert result.exit_code == 1
    assert "not safe to download" in result.stdout
    assert len(audio_fetches(run.service)) == fetched
    assert not (book_dir(run) / "a.wav").exists()
    assert not (run.data / "test" / "books" / "escape.wav").exists()
    assert run.player.started == []


def test_fetch_missing_keeps_to_the_service_host_unless_trusted(
    run: Run, tmp_path: Path
) -> None:
    downloaded(run)
    (book_dir(run) / "a.wav").unlink()
    delegate = FakeService()
    try:
        delegate.offer_file("delegate/a.wav", b"synthetic-a")
        run.service.offer_resources(
            "book0",
            [
                resource("master.smil", MASTER),
                resource("b.smil", SMIL_B),
                resource("a.smil", SMIL_A),
                ContentResource(
                    uri=delegate.file_url("delegate/a.wav"),
                    mime_type="audio/wav",
                    size=11,
                    local_uri="a.wav",
                ),
            ],
        )

        refused = run("play", "book0", "--fetch-missing")

        assert refused.exit_code == 2
        assert "--trust-host" in refused.stderr
        assert delegate.fetches == []
        assert run.player.started == []

        trusted = run("play", "book0", "--fetch-missing", "--trust-host")

        assert trusted.exit_code == 0, trusted.output
        assert "Cookie" not in delegate.fetches[-1].headers
        assert "observation host-boundary" in trusted.stderr
        assert (book_dir(run) / "a.wav").read_bytes() == b"synthetic-a"
    finally:
        delegate.stop()


def test_a_failed_fetch_leaves_no_file_and_plays_nothing(run: Run) -> None:
    downloaded(run)
    (book_dir(run) / "a.wav").unlink()
    run.service.answer_file("files/a.wav", 404)

    result = run("play", "book0", "--fetch-missing")

    assert result.exit_code == 1
    assert "failed a.wav" in result.stdout
    assert sorted(p.name for p in book_dir(run).glob("a.wav*")) == []
    assert run.player.started == []
