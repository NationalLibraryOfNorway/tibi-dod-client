"""`Playback`: the play controller behind a `Player` seam (ADR 0009).

A fake `Player` stands in for the audio device; its clock moves only when the
test says so. Playlists are synthetic.
"""

from pathlib import Path

import pytest

from dod.application import Playback, PlaybackState, PlayRefused, prepare_playback
from dod.domain.book import Clip, Playlist
from support._fake_player import FakePlayer

BOOK = Path("book")


def make(
    clips: list[Clip], durations: dict[str, float], tmp_path: Path
) -> tuple[Playback, FakePlayer]:
    for name in durations:
        file = tmp_path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"x")
    player = FakePlayer(durations)
    return prepare_playback(tmp_path, Playlist(tuple(clips)), player), player


THREE = [
    Clip("a.wav", 0.0, 10.0),
    Clip("a.wav", 10.0, 20.0),
    Clip("b.wav", 0.0, None),
]
LENGTHS = {"a.wav": 20.0, "b.wav": 50.0}


def test_start_plays_the_first_clip_and_shows_its_place_in_the_book(
    tmp_path: Path,
) -> None:
    playback, player = make(THREE, LENGTHS, tmp_path)

    playback.start()

    assert player.started == [("a.wav", 0.0)]
    status = playback.status()
    assert status.state is PlaybackState.PLAYING
    assert (status.file, status.file_index, status.file_count) == ("a.wav", 1, 2)
    assert (status.elapsed, status.total) == (0.0, 70.0)


def test_a_clip_that_continues_in_the_same_file_does_not_restart_the_player(
    tmp_path: Path,
) -> None:
    playback, player = make(THREE, LENGTHS, tmp_path)
    playback.start()

    player.advance(12.0)
    playback.tick()

    assert player.started == [("a.wav", 0.0)]
    status = playback.status()
    assert status.clip_index == 1
    assert status.elapsed == pytest.approx(12.0)


def test_the_next_file_is_started_when_the_clip_ends(tmp_path: Path) -> None:
    playback, player = make(THREE, LENGTHS, tmp_path)
    playback.start()

    player.advance(20.5)
    playback.tick()

    assert player.started == [("a.wav", 0.0), ("b.wav", 0.0)]
    status = playback.status()
    assert (status.file, status.file_index, status.file_count) == ("b.wav", 2, 2)
    assert status.elapsed == pytest.approx(20.0)


def test_a_gap_between_clips_of_one_file_restarts_at_the_next_clips_begin(
    tmp_path: Path,
) -> None:
    clips = [Clip("a.wav", 0.0, 5.0), Clip("a.wav", 8.0, 12.0)]
    playback, player = make(clips, {"a.wav": 20.0}, tmp_path)
    playback.start()

    player.advance(5.0)
    playback.tick()

    assert player.started == [("a.wav", 0.0), ("a.wav", 8.0)]
    assert playback.status().elapsed == pytest.approx(5.0)


def test_the_last_clip_ending_finishes_playback_and_stops_the_player(
    tmp_path: Path,
) -> None:
    playback, player = make(THREE, LENGTHS, tmp_path)
    playback.start()
    player.advance(20.5)
    playback.tick()

    player.advance(50.0)
    playback.tick()

    assert playback.status().state is PlaybackState.FINISHED
    assert not player.playing


def test_pause_stops_and_resume_restarts_from_where_it_was(tmp_path: Path) -> None:
    playback, player = make(THREE, LENGTHS, tmp_path)
    playback.start()
    player.advance(4.0)

    playback.pause()

    assert not player.playing
    assert playback.status().state is PlaybackState.PAUSED
    assert playback.status().elapsed == pytest.approx(4.0)
    player.advance(100.0)  # time passing while paused changes nothing
    playback.tick()
    assert playback.status().elapsed == pytest.approx(4.0)

    playback.resume()

    assert player.started[-1] == ("a.wav", 4.0)
    assert playback.status().state is PlaybackState.PLAYING


def test_next_and_previous_move_by_clip(tmp_path: Path) -> None:
    playback, player = make(THREE, LENGTHS, tmp_path)
    playback.start()

    playback.next()
    assert player.started[-1] == ("a.wav", 10.0)
    assert playback.status().clip_index == 1

    playback.next()
    assert player.started[-1] == ("b.wav", 0.0)

    playback.next()  # already on the last clip
    assert playback.status().clip_index == 2

    playback.previous()
    assert player.started[-1] == ("a.wav", 10.0)
    playback.previous()
    playback.previous()  # already on the first: starts it over
    assert player.started[-1] == ("a.wav", 0.0)
    assert playback.status().clip_index == 0


def test_next_while_paused_moves_but_stays_paused(tmp_path: Path) -> None:
    playback, player = make(THREE, LENGTHS, tmp_path)
    playback.start()
    playback.pause()

    playback.next()

    assert playback.status().state is PlaybackState.PAUSED
    assert playback.status().clip_index == 1
    playback.resume()
    assert player.started[-1] == ("a.wav", 10.0)


def test_jump_forward_30_seconds_crosses_clips_by_playlist_time(
    tmp_path: Path,
) -> None:
    playback, player = make(THREE, LENGTHS, tmp_path)
    playback.start()
    player.advance(5.0)

    playback.jump(30.0)

    # 5 + 30 = 35 s of Playlist time: 15 s into b.wav.
    assert player.started[-1] == ("b.wav", 15.0)
    assert playback.status().elapsed == pytest.approx(35.0)


def test_jump_back_is_clamped_to_the_start_and_forward_to_the_end(
    tmp_path: Path,
) -> None:
    playback, player = make(THREE, LENGTHS, tmp_path)
    playback.start()
    player.advance(5.0)

    playback.jump(-30.0)
    assert player.started[-1] == ("a.wav", 0.0)
    assert playback.status().elapsed == 0.0

    playback.jump(30.0)
    playback.jump(30.0)
    playback.jump(30.0)
    assert playback.status().state is PlaybackState.FINISHED
    assert not player.playing


def test_stop_stops_the_player(tmp_path: Path) -> None:
    playback, player = make(THREE, LENGTHS, tmp_path)
    playback.start()

    playback.stop()

    assert playback.status().state is PlaybackState.STOPPED
    assert not player.playing


def test_a_clip_that_ends_after_its_file_is_cut_at_the_files_end(
    tmp_path: Path,
) -> None:
    playback, _ = make([Clip("a.wav", 0.0, 99.0)], {"a.wav": 4.0}, tmp_path)

    assert playback.status().total == 4.0


def test_a_missing_audio_file_refuses_before_anything_plays(tmp_path: Path) -> None:
    (tmp_path / "a.wav").write_bytes(b"x")
    player = FakePlayer({"a.wav": 1.0, "b.wav": 1.0})
    playlist = Playlist((Clip("a.wav"), Clip("sub/b.wav")))

    with pytest.raises(PlayRefused) as raised:
        prepare_playback(tmp_path, playlist, player)

    assert "sub/b.wav" in str(raised.value)
    assert "dod download" in str(raised.value)
    assert player.started == []


def test_a_format_the_player_cannot_decode_is_an_error_with_an_observation(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.m4a").write_bytes(b"x")
    player = FakePlayer({})
    playlist = Playlist((Clip("a.m4a"),))

    with pytest.raises(PlayRefused) as raised:
        prepare_playback(tmp_path, playlist, player)

    assert "a.m4a" in str(raised.value)
    assert [o.id for o in raised.value.observations] == ["audio-format"]
    assert "a.m4a" in raised.value.observations[0].message


@pytest.mark.skipif(
    __import__("sys").platform == "win32", reason="symbolic links need privileges"
)
def test_an_audio_file_that_is_a_link_out_of_the_book_is_refused(
    tmp_path: Path,
) -> None:
    book = tmp_path / "book"
    book.mkdir()
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"x")
    (book / "a.wav").symlink_to(outside)

    with pytest.raises(PlayRefused) as raised:
        prepare_playback(book, Playlist((Clip("a.wav"),)), FakePlayer({"a.wav": 1.0}))

    assert "leaves the book directory" in str(raised.value)
