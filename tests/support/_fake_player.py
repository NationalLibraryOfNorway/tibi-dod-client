"""A fake `Player`: no audio device, a clock the test advances by hand."""

from __future__ import annotations

from pathlib import Path

from dod.application import AudioError


class FakePlayer:
    """Plays nothing. `advance` moves its clock; `step` also moves it on every
    `finished()` poll, which the play loop makes once per tick."""

    def __init__(
        self,
        durations: dict[str, float] | None = None,
        *,
        step: float = 0.0,
    ) -> None:
        self.durations = dict(durations or {})
        self.step = step
        self.started: list[tuple[str, float]] = []
        self.stops = 0
        self.closed = False
        self._file: str | None = None
        self._position = 0.0
        self._playing = False

    def duration(self, path: Path) -> float:
        if path.name not in self.durations:
            raise AudioError(f"{path.name}: the format is not supported")
        return self.durations[path.name]

    def start(self, path: Path, offset: float) -> None:
        self.started.append((path.name, offset))
        self._file, self._position, self._playing = path.name, offset, True

    def stop(self) -> None:
        self.stops += 1
        self._playing = False

    def close(self) -> None:
        self.closed = True

    def position(self) -> float:
        return self._position

    def finished(self) -> bool:
        if self._playing:
            self._position += self.step
        assert self._file is not None
        return self._playing and self._position >= self.durations[self._file]

    def advance(self, seconds: float) -> None:
        if self._playing:
            self._position += seconds

    @property
    def playing(self) -> bool:
        return self._playing
