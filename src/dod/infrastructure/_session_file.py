"""Session files on disk, one per (Service URL, user) (ADR 0001, ADR 0005).

A Session file is plain JSON holding the Session cookie and never a password.
It lives in `sessions/` under the state directory (`DOD_STATE_DIR`, else the
platform's user state directory). Where the platform has permission bits the
file is `0600` and the directories `dod` creates are `0700`; on Windows the
user profile's default ACL applies. Writes are atomic (a temporary file in the
same directory, then a rename) and every access happens under a `filelock`.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock
from platformdirs import user_state_dir

from dod.application import SessionKey, SessionSlot
from dod.domain.service import SessionState

_FORMAT = 1
_DIRECTORY_MODE = 0o700
_FILE_MODE = 0o600
_LOCK_TIMEOUT_SECONDS = 60


class _FileSlot:
    def __init__(self, directory: Path, key: SessionKey, stem: str) -> None:
        self._directory = directory
        self._key = key
        self._path = directory / f"{stem}.json"

    def read(self) -> SessionState | None:
        try:
            document = json.loads(self._path.read_text(encoding="utf-8"))
            if (
                document["format"] != _FORMAT
                or document["url"] != self._key.url
                or document["username"] != self._key.username
            ):
                return None
            cookies = tuple(
                (str(name), str(value)) for name, value in document["cookies"]
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return SessionState(cookies=cookies)

    def write(self, state: SessionState) -> None:
        document = {
            "format": _FORMAT,
            "url": self._key.url,
            "username": self._key.username,
            "cookies": [list(pair) for pair in state.cookies],
        }
        descriptor, temporary = tempfile.mkstemp(
            dir=self._directory, prefix=".tmp-", suffix=".json"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
                json.dump(document, file, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            _restrict(temporary, _FILE_MODE)
            os.replace(temporary, self._path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise

    def clear(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._path.unlink()


def _restrict(path: str | Path, mode: int) -> None:
    # Windows has no group or other bits; the profile's ACL protects the file.
    if sys.platform != "win32":
        os.chmod(path, mode)


class FileSessionStore:
    """A `SessionStore` that keeps Session files in the state directory."""

    def __init__(self, state_dir: str | Path | None = None) -> None:
        self._state_dir = Path(
            state_dir if state_dir else user_state_dir("dod", appauthor=False)
        )

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> FileSessionStore:
        """The store for `DOD_STATE_DIR`, or the platform default without it."""
        return cls(environ.get("DOD_STATE_DIR") or None)

    @contextmanager
    def lock(self, key: SessionKey) -> Iterator[SessionSlot]:
        directory = self._ensure_directory()
        stem = hashlib.sha256(f"{key.url}\0{key.username}".encode()).hexdigest()[:24]
        lock = FileLock(
            directory / f"{stem}.lock", timeout=_LOCK_TIMEOUT_SECONDS, mode=_FILE_MODE
        )
        with lock:
            yield _FileSlot(directory, key, stem)

    def _ensure_directory(self) -> Path:
        directory = self._state_dir / "sessions"
        for path in (self._state_dir, directory):
            if not path.exists():
                path.mkdir(mode=_DIRECTORY_MODE, parents=True, exist_ok=True)
                _restrict(path, _DIRECTORY_MODE)
        return directory
