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
from support import FakeService
from support._fake_player import FakePlayer

USER = "synthetic-user"
PASSWORD = "synthetic-secret"
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
