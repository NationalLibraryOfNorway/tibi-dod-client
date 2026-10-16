"""The `dod play` loop: commands from the keyboard, a status line on stdout.

Commands are lines, not single keys, so that it works the same on every
platform and in a pipe. On a terminal they are read by a thread while the loop
ticks; from a pipe each line is applied in turn, and when the input ends the
book plays on to its end. Everything shown about a file is untrusted text.
"""

from __future__ import annotations

import queue
import sys
import threading
import time
from collections.abc import Callable, Iterator

import typer

from dod.application import Playback, PlaybackState, PlaybackStatus

JUMP_SECONDS = 30.0
_TICK_SECONDS = 0.02
_STATUS_EVERY = 10.0
COMMANDS_HELP = (
    "commands (then Enter): p pause/resume, n next clip, b previous clip, "
    "f forward 30 s, r back 30 s, Enter status, q stop"
)


def clock(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 3600:02d}:{whole % 3600 // 60:02d}:{whole % 60:02d}"


def status_line(status: PlaybackStatus, plain: Callable[[str], str]) -> str:
    line = (
        f"file {status.file_index} of {status.file_count}: {plain(status.file)}  "
        f"elapsed {clock(status.elapsed)} of {clock(status.total)}"
    )
    return line + " (paused)" if status.state is PlaybackState.PAUSED else line


def terminal_commands() -> Iterator[str | None]:
    """Lines typed on a terminal; None when none arrived within a tick."""
    lines: queue.Queue[str] = queue.Queue()

    def read() -> None:
        while True:
            line = sys.stdin.readline()
            lines.put(line.strip() if line else "q")
            if not line:
                return

    threading.Thread(target=read, daemon=True).start()
    while True:
        try:
            yield lines.get(timeout=_TICK_SECONDS)
        except queue.Empty:
            yield None


def piped_commands() -> Iterator[str | None]:
    """Each line of stdin in turn, then None for as long as the book plays."""
    for line in sys.stdin:
        yield line.strip()
    while True:
        time.sleep(_TICK_SECONDS)
        yield None


def run_playback(
    playback: Playback,
    commands: Iterator[str | None],
    plain: Callable[[str], str],
) -> None:
    """Drive `playback` until it finishes or `q`; a line per change on stdout."""
    status = playback.status()
    typer.echo(status_line(status, plain))
    typer.echo(COMMANDS_HELP, err=True)
    shown = (status.file_index, int(status.elapsed // _STATUS_EVERY))
    for command in commands:
        if command is None:
            playback.tick()
        elif command in {"q", "quit", "s", "stop"}:
            playback.stop()
            status = playback.status()
            typer.echo(f"stopped: {clock(status.elapsed)} of {clock(status.total)}")
            return
        elif command == "":
            typer.echo(status_line(playback.status(), plain))
        elif command in {"p", "pause", "resume"}:
            if playback.status().state is PlaybackState.PAUSED:
                playback.resume()
            else:
                playback.pause()
            typer.echo(status_line(playback.status(), plain))
        elif command in {"n", "next"}:
            playback.next()
            typer.echo(status_line(playback.status(), plain))
        elif command in {"b", "back", "previous", "prev"}:
            playback.previous()
            typer.echo(status_line(playback.status(), plain))
        elif command in {"f", "forward"}:
            playback.jump(JUMP_SECONDS)
            typer.echo(status_line(playback.status(), plain))
        elif command in {"r", "rewind"}:
            playback.jump(-JUMP_SECONDS)
            typer.echo(status_line(playback.status(), plain))
        else:
            typer.echo(
                f"unknown command {plain(command)[:40]!r}; {COMMANDS_HELP}", err=True
            )
        status = playback.status()
        if status.state is PlaybackState.FINISHED:
            typer.echo(f"finished: {clock(status.elapsed)} of {clock(status.total)}")
            return
        current = (status.file_index, int(status.elapsed // _STATUS_EVERY))
        if command is None and current != shown:
            typer.echo(status_line(status, plain))
        shown = current
