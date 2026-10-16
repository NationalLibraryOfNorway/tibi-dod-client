"""The file-backed `SessionStore` (ADR 0001, ADR 0005), through its public interface.

State directories are temporary; users, passwords and cookies are synthetic.
"""

import json
import os
import stat
import sys
import threading
from pathlib import Path

import pytest

from dod.application import SessionKey, SessionManager
from dod.domain.service import Password, SessionState
from dod.infrastructure import FileSessionStore, InMemoryService

URL = "https://dod.example.org/service"
KEY = SessionKey(URL, "synthetic-user")
STATE = SessionState(cookies=(("session", "synthetic-cookie"),))
posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX permission bits; Windows uses the ACL"
)


def read(store: FileSessionStore, key: SessionKey = KEY) -> SessionState | None:
    with store.lock(key) as slot:
        return slot.read()


def files_in(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def test_a_written_session_is_read_back_by_another_store_instance(
    tmp_path: Path,
) -> None:
    with FileSessionStore(tmp_path).lock(KEY) as slot:
        slot.write(STATE)

    assert read(FileSessionStore(tmp_path)) == STATE


def test_nothing_stored_reads_as_none(tmp_path: Path) -> None:
    assert read(FileSessionStore(tmp_path)) is None


def test_clear_deletes_the_session(tmp_path: Path) -> None:
    store = FileSessionStore(tmp_path)
    with store.lock(KEY) as slot:
        slot.write(STATE)
    with store.lock(KEY) as slot:
        slot.clear()
        slot.clear()

    assert read(store) is None


def test_each_service_url_and_user_has_a_session_of_its_own(tmp_path: Path) -> None:
    store = FileSessionStore(tmp_path)
    other_user = SessionKey(URL, "someone-else")
    other_url = SessionKey("https://other.example.org/service", "synthetic-user")
    with store.lock(KEY) as slot:
        slot.write(STATE)

    assert read(store, other_user) is None
    assert read(store, other_url) is None


def test_a_file_that_is_not_a_session_file_reads_as_none(tmp_path: Path) -> None:
    store = FileSessionStore(tmp_path)
    with store.lock(KEY) as slot:
        slot.write(STATE)
    (session_file,) = [p for p in files_in(tmp_path) if p.suffix == ".json"]
    session_file.write_text("{not json", encoding="utf-8")

    assert read(store) is None


def test_the_file_is_plain_json_with_the_cookies_and_no_password(
    tmp_path: Path,
) -> None:
    memory = InMemoryService()
    memory.add_user(KEY.username, "synthetic-secret")
    store = FileSessionStore(tmp_path)
    manager = SessionManager(
        lambda url: memory.open_port(), store, URL, KEY.username, None
    )

    manager.logon(Password("synthetic-secret"))

    (session_file,) = [p for p in files_in(tmp_path) if p.suffix == ".json"]
    text = session_file.read_text(encoding="utf-8")
    assert "synthetic-secret" not in text
    document = json.loads(text)
    assert document["url"] == URL
    assert document["username"] == KEY.username
    assert document["cookies"][0][0] == "session"
    assert KEY.username not in session_file.name


def test_writing_leaves_no_temporary_files_behind(tmp_path: Path) -> None:
    store = FileSessionStore(tmp_path)
    for value in ("a", "b", "c"):
        with store.lock(KEY) as slot:
            slot.write(SessionState(cookies=(("session", value),)))

    names = [path.name for path in files_in(tmp_path)]
    assert len([n for n in names if n.endswith(".json")]) == 1
    assert not [n for n in names if "tmp" in n]


@posix_only
def test_the_file_is_0600_and_the_directories_are_0700(tmp_path: Path) -> None:
    root = tmp_path / "state"
    store = FileSessionStore(root)
    with store.lock(KEY) as slot:
        slot.write(STATE)

    (session_file,) = [p for p in files_in(root) if p.suffix == ".json"]
    assert stat.S_IMODE(session_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(session_file.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    for lock_file in (p for p in files_in(root) if p.suffix == ".lock"):
        assert stat.S_IMODE(lock_file.stat().st_mode) == 0o600


@posix_only
def test_a_rewritten_file_keeps_0600_under_a_permissive_umask(tmp_path: Path) -> None:
    old = os.umask(0)
    try:
        store = FileSessionStore(tmp_path / "state")
        with store.lock(KEY) as slot:
            slot.write(STATE)
            slot.write(SessionState(cookies=(("session", "next"),)))
    finally:
        os.umask(old)

    (session_file,) = [p for p in files_in(tmp_path / "state") if p.suffix == ".json"]
    assert stat.S_IMODE(session_file.stat().st_mode) == 0o600


def test_dod_state_dir_overrides_the_default_directory(tmp_path: Path) -> None:
    store = FileSessionStore.from_environ({"DOD_STATE_DIR": str(tmp_path / "chosen")})
    with store.lock(KEY) as slot:
        slot.write(STATE)

    assert files_in(tmp_path / "chosen")


def test_the_lock_excludes_other_holders_until_it_is_released(
    tmp_path: Path,
) -> None:
    store = FileSessionStore(tmp_path)
    holding = threading.Event()
    release = threading.Event()
    order: list[str] = []

    def first() -> None:
        with store.lock(KEY):
            holding.set()
            release.wait(5)
            order.append("first released")

    def second() -> None:
        holding.wait(5)
        with store.lock(KEY):
            order.append("second entered")

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for thread in threads:
        thread.start()
    holding.wait(5)
    threading.Event().wait(0.3)
    release.set()
    for thread in threads:
        thread.join(5)

    assert order == ["first released", "second entered"]
