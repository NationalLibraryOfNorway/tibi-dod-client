"""Run the installed `dod` console script as a subprocess."""

import os
import re
import shutil
import subprocess
import sysconfig
import tempfile

# Typer's Rich output is forced into terminal mode (ANSI styling) by these
# variables, which CI sets (GITHUB_ACTIONS) or developers export. NO_COLOR alone
# does not remove bold/dim styling, so they must not reach the child process.
FORCE_TERMINAL_VARS = {
    "FORCE_COLOR",
    "PY_COLORS",
    "GITHUB_ACTIONS",
    "TTY_COMPATIBLE",
    "TTY_INTERACTIVE",
    "TERMINAL_WIDTH",
}
# Tests must never touch the developer's own Session files: unless a test says
# otherwise, the child process gets a throwaway state directory.
_STATE_DIR = tempfile.TemporaryDirectory(prefix="dod-test-state-")
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def run_dod(
    *args: str,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    scripts = sysconfig.get_path("scripts")
    executable = shutil.which("dod", path=scripts)
    assert executable is not None, f"console script 'dod' not found in {scripts}"
    child_env = {
        key: value
        for key, value in os.environ.items()
        if key not in FORCE_TERMINAL_VARS and not key.startswith("DOD_")
    }
    child_env |= {
        "NO_COLOR": "1",
        "PYTHONIOENCODING": "utf-8",
        "COLUMNS": "100",
        "DOD_STATE_DIR": _STATE_DIR.name,
    }
    child_env |= env or {}
    result = subprocess.run(
        [executable, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=child_env,
        input=stdin,
        check=False,
    )
    # Defence in depth: assert on content, not on styling.
    result.stdout = ANSI_ESCAPE.sub("", result.stdout)
    return result
