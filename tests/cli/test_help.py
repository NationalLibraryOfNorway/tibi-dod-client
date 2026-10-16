"""`dod --help` through the CLI boundary: the installed console script."""

import re

import pytest

from support import run_dod

PANELS = [
    "Session and setup",
    "Browse and issue",
    "Download and play",
    "Testing and tools",
]


def test_help_exits_zero_and_writes_only_to_stdout() -> None:
    result = run_dod("--help")

    assert result.returncode == 0, result.stderr
    assert "Usage: dod" in result.stdout
    assert result.stderr == ""


@pytest.mark.parametrize("panel", PANELS)
def test_help_shows_command_groups_as_panels(panel: str) -> None:
    result = run_dod("--help")

    # The panel border depends on the platform's box-drawing support: rounded
    # corners (╭─), square corners (┌─, legacy Windows consoles) or ASCII (+-).
    title = re.compile(rf"^\S[-─] {re.escape(panel)} ")
    assert any(title.match(line.lstrip()) for line in result.stdout.splitlines()), (
        result.stdout
    )


@pytest.mark.parametrize(
    ("group", "commands"),
    [
        ("attributes", ["service", "reading-system"]),
        ("announcements", ["list", "mark-read"]),
    ],
)
def test_attribute_and_announcement_commands_are_listed(
    group: str, commands: list[str]
) -> None:
    result = run_dod(group, "--help")

    assert result.returncode == 0, result.stderr
    for command in commands:
        assert re.search(rf"^\W*{re.escape(command)}\s", result.stdout, re.M), (
            result.stdout
        )


def test_mark_read_help_explains_all_and_the_one_by_one_fallback() -> None:
    result = run_dod("announcements", "mark-read", "--help")

    text = " ".join(result.stdout.split())
    assert "--all" in text
    assert "invalidParameter" in text
