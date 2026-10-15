"""The configuration file on disk, in the platform's configuration directory."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

from platformdirs import user_config_dir

from dod.application import ConfigFile


class FileConfigStore:
    """Reads the configuration file from the file system.

    The default file is `config.toml` in the platform's user configuration
    directory for `dod`. There is no project-local file.
    """

    def default_path(self) -> str:
        return str(Path(user_config_dir("dod", appauthor=False)) / "config.toml")

    def read(self, path: str) -> ConfigFile | None:
        try:
            content = Path(path).read_bytes()
            mode = os.stat(path).st_mode
        except FileNotFoundError:
            return None
        # Windows has no group or other permission bits to look at.
        others_can_read = (
            None
            if sys.platform == "win32"
            else bool(mode & (stat.S_IRWXG | stat.S_IRWXO))
        )
        return ConfigFile(path, content, others_can_read)
