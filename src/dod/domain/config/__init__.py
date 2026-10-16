"""The configuration model and its structural validation.

Pure: it parses text and never touches the file system. Depends only on the
shared kernel.
"""

from dod.domain.config._model import Config, ConfigError, Environment
from dod.domain.config._parse import ENVIRONMENT_NAME, parse_config

__all__ = [
    "ENVIRONMENT_NAME",
    "Config",
    "ConfigError",
    "Environment",
    "parse_config",
]
