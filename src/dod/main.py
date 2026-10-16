"""Composition root: wires the layers together and runs the `dod` command."""

from dod.presentation import create_app


def main() -> None:
    """Entry point of the `dod` console script."""
    create_app()()
