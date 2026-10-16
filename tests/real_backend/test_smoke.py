"""Opt-in smoke test of `dod` against a real Service (specification US 99).

Deselected by default (`-m "not real_backend"` in pyproject.toml) and skipped
unless the Service is named by environment variables. Select it explicitly:

    DOD_REAL_ADDRESS=... DOD_REAL_URL=... DOD_REAL_USERNAME=... \\
    DOD_REAL_PASSWORD=... uv run pytest -m real_backend

The variables are the only source of the address, the endpoint and the
credentials; nothing is read from a file and nothing is printed. The password
reaches `dod` on stdin only. `DOD_REAL_INSECURE=1` allows an http address.

Everything goes through the CLI boundary, in ephemeral mode (`--no-session`),
so no Session file is stored and the Service is left as it was.
"""

import os
import subprocess
from pathlib import Path

import pytest

from support import run_dod

pytestmark = pytest.mark.real_backend

_NAMES = (
    "DOD_REAL_ADDRESS",
    "DOD_REAL_URL",
    "DOD_REAL_USERNAME",
    "DOD_REAL_PASSWORD",
)
_MISSING = [name for name in _NAMES if not os.environ.get(name)]


@pytest.fixture(autouse=True)
def _configured() -> None:
    if _MISSING:
        pytest.skip("set " + ", ".join(_MISSING) + " to run against a real Service")


def _insecure() -> list[str]:
    return ["--insecure"] if os.environ.get("DOD_REAL_INSECURE") == "1" else []


def _dod(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run_dod(
        *args,
        "--url",
        os.environ["DOD_REAL_URL"],
        "--username",
        os.environ["DOD_REAL_USERNAME"],
        "--password-stdin",
        "--no-session",
        *_insecure(),
        stdin=os.environ["DOD_REAL_PASSWORD"] + "\n",
        env={"DOD_STATE_DIR": str(tmp_path / "state")},
    )


def test_discover_finds_an_endpoint() -> None:
    result = run_dod("discover", os.environ["DOD_REAL_ADDRESS"], *_insecure())

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("endpoint: ")


def test_logon_runs_the_initialisation_sequence_and_logs_off(tmp_path: Path) -> None:
    result = _dod(tmp_path, "logon")

    assert result.returncode == 0, result.stderr
    assert "logOn: ok" in result.stdout
    assert "logOff: ok" in result.stdout


def test_the_service_attributes_are_shown(tmp_path: Path) -> None:
    result = _dod(tmp_path, "attributes", "service")

    assert result.returncode == 0, result.stderr
    assert "getServiceAttributes: ok" in result.stdout
    assert not list((tmp_path / "state").rglob("*.json"))
