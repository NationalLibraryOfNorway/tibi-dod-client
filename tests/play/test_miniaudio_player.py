"""The `miniaudio` adapter of the `Player` seam, on the NULL backend.

No audio device is ever opened: miniaudio's `Backend.NULL` consumes samples in
real time and plays nothing. Skipped where miniaudio has no wheels.
"""

import math
import struct
import sys
import time
import wave
from pathlib import Path

import pytest

from dod.application import AudioError, PlayerUnavailable
from dod.infrastructure import MiniaudioPlayer, open_miniaudio_player

miniaudio = pytest.importorskip("miniaudio")


def write_wav(path: Path, seconds: float, rate: int = 22050) -> Path:
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(
            b"".join(
                struct.pack("<h", int(8000 * math.sin(i / 20))) for i in range(frames)
            )
        )
    return path


@pytest.fixture
def player():  # type: ignore[no-untyped-def]
    adapter = MiniaudioPlayer(backends=[miniaudio.Backend.NULL])
    yield adapter
    adapter.close()


def wait_until_finished(player: MiniaudioPlayer, seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    while not player.finished():
        assert time.monotonic() < deadline, "the player never finished"
        time.sleep(0.01)


def test_duration_is_the_length_of_the_file_in_seconds(
    player: MiniaudioPlayer, tmp_path: Path
) -> None:
    wav = write_wav(tmp_path / "a.wav", 0.5)

    assert player.duration(wav) == pytest.approx(0.5, abs=0.01)


def test_a_file_in_a_format_miniaudio_cannot_decode_is_an_audio_error(
    player: MiniaudioPlayer, tmp_path: Path
) -> None:
    aac = tmp_path / "a.m4a"
    aac.write_bytes(b"\x00\x00\x00\x18ftypM4A " + b"\x00" * 200)

    with pytest.raises(AudioError):
        player.duration(aac)


def test_a_missing_file_is_an_audio_error(
    player: MiniaudioPlayer, tmp_path: Path
) -> None:
    with pytest.raises(AudioError):
        player.duration(tmp_path / "nope.wav")


def test_playing_runs_to_the_end_and_counts_the_frames_handed_to_the_device(
    player: MiniaudioPlayer, tmp_path: Path
) -> None:
    wav = write_wav(tmp_path / "a.wav", 0.3)

    player.start(wav, 0.0)
    wait_until_finished(player)

    assert player.position() == pytest.approx(0.3, abs=0.05)


def test_a_start_offset_seeks_by_frame(player: MiniaudioPlayer, tmp_path: Path) -> None:
    wav = write_wav(tmp_path / "a.wav", 0.4)

    player.start(wav, 0.25)

    wait_until_finished(player)
    # Only the last 0.15 s were handed to the device: without the seek this
    # would be 0.4 + 0.25.
    assert player.position() == pytest.approx(0.4, abs=0.05)


def test_stop_ends_the_playing_where_it_is(
    player: MiniaudioPlayer, tmp_path: Path
) -> None:
    wav = write_wav(tmp_path / "a.wav", 5.0)
    player.start(wav, 0.0)
    time.sleep(0.2)

    player.stop()
    stopped_at = player.position()
    time.sleep(0.2)

    assert player.position() == stopped_at
    assert stopped_at < 4.0
    assert not player.finished()


def test_it_can_be_started_again_after_a_stop(
    player: MiniaudioPlayer, tmp_path: Path
) -> None:
    wav = write_wav(tmp_path / "a.wav", 0.3)
    player.start(wav, 0.0)
    player.stop()

    player.start(wav, 0.1)
    wait_until_finished(player)

    assert player.position() == pytest.approx(0.3, abs=0.05)


def test_without_miniaudio_the_player_is_unavailable_with_an_explanation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "miniaudio", None)

    with pytest.raises(PlayerUnavailable) as raised:
        open_miniaudio_player()

    assert "dod-client[play]" in str(raised.value)
