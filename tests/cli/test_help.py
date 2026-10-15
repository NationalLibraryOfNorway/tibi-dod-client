"""`dod --help` through the CLI boundary: the installed console script."""

import os
import re
import shutil
import subprocess
import sysconfig

import pytest

PANELS = [
    "Session and setup",
    "Browse and issue",
    "Download and play",
    "Testing and tools",
]


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
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def run_dod(*args: str) -> subprocess.CompletedProcess[str]:
    scripts = sysconfig.get_path("scripts")
    executable = shutil.which("dod", path=scripts)
    assert executable is not None, f"console script 'dod' not found in {scripts}"
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in FORCE_TERMINAL_VARS
    }
    env |= {"NO_COLOR": "1", "PYTHONIOENCODING": "utf-8", "COLUMNS": "100"}
    result = subprocess.run(
        [executable, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )
    # Defence in depth: assert on content, not on styling.
    result.stdout = ANSI_ESCAPE.sub("", result.stdout)
    return result


def test_help_exits_zero_and_writes_only_to_stdout() -> None:
    result = run_dod("--help")

    assert result.returncode == 0, result.stderr
    assert "Usage: dod" in result.stdout
    assert result.stderr == ""


@pytest.mark.parametrize("panel", PANELS)
def test_help_shows_command_groups_as_panels(panel: str) -> None:
    result = run_dod("--help")

    assert any(
        line.lstrip().startswith(("╭─ " + panel, "+- " + panel))
        for line in result.stdout.splitlines()
    ), result.stdout
