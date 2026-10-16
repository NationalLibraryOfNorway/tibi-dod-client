"""The `Player` adapter around `miniaudio` (ADR 0009).

`miniaudio` is optional (`dod-client[play]`) and is imported only here, when a
player is opened. It decodes WAV, FLAC, MP3 and Ogg Vorbis, not AAC, and has no
pause, seek or position on a running device: the position is our own count of
the frames handed to the device, which runs a little ahead of what is heard,
and a seek is a new stream started at a frame offset.
"""

from __future__ import annotations

import threading
from collections.abc import Generator
from pathlib import Path
from typing import Any

from dod.application import AudioError, PlayerUnavailable

_RATE = 44100
_CHANNELS = 2
_MISSING = (
    "audio playback needs the optional `miniaudio` package, which is not "
    "available here: install it with `pip install 'dod-client[play]'`. It has "
    "no wheels for every platform (for example Linux arm64, Windows arm64 and "
    "Python 3.15), where `dod play` cannot run"
)


def open_miniaudio_player() -> MiniaudioPlayer:
    """A Player on the default audio device, or `PlayerUnavailable`."""
    try:
        import miniaudio  # noqa: F401
    except ImportError:
        raise PlayerUnavailable(_MISSING) from None
    return MiniaudioPlayer()


class MiniaudioPlayer:
    """Plays one file at a time as 16-bit stereo at 44.1 kHz."""

    def __init__(self, backends: list[Any] | None = None) -> None:
        import miniaudio

        self._miniaudio = miniaudio
        self._backends = backends
        self._device: Any = None
        self._lock = threading.Lock()
        self._offset = 0.0
        self._frames = 0
        self._finished = False

    def duration(self, path: Path) -> float:
        try:
            return float(self._miniaudio.get_file_info(str(path)).duration)
        except (self._miniaudio.MiniaudioError, OSError, ValueError) as error:
            raise AudioError(_reason(error)) from None

    def start(self, path: Path, offset: float) -> None:
        self.stop()
        try:
            stream = self._miniaudio.stream_file(
                str(path),
                output_format=self._miniaudio.SampleFormat.SIGNED16,
                nchannels=_CHANNELS,
                sample_rate=_RATE,
                seek_frame=int(offset * _RATE),
            )
            with self._lock:
                self._offset, self._frames, self._finished = offset, 0, False
            if self._device is None:
                self._device = self._miniaudio.PlaybackDevice(
                    output_format=self._miniaudio.SampleFormat.SIGNED16,
                    nchannels=_CHANNELS,
                    sample_rate=_RATE,
                    backends=self._backends,
                    app_name="dod",
                )
            counting = self._counting(stream)
            next(counting)  # miniaudio wants a generator that is already started
            self._device.start(counting)
        except (self._miniaudio.MiniaudioError, OSError) as error:
            raise AudioError(_reason(error)) from None

    def stop(self) -> None:
        if self._device is not None:
            self._device.stop()

    def close(self) -> None:
        if self._device is not None:
            self._device.close()
            self._device = None

    def position(self) -> float:
        with self._lock:
            return self._offset + self._frames / _RATE

    def finished(self) -> bool:
        with self._lock:
            return self._finished

    def _counting(self, source: Generator[Any, int, None]) -> Generator[Any, int, None]:
        """Hand the device what `source` decodes, counting the frames."""
        next(source)
        frames = yield b""
        while True:
            try:
                data = source.send(frames)
            except StopIteration:
                with self._lock:
                    self._finished = True
                return
            with self._lock:
                self._frames += len(data) // _CHANNELS
            frames = yield data


def _reason(error: Exception) -> str:
    text = str(error).strip()
    return text or type(error).__name__
