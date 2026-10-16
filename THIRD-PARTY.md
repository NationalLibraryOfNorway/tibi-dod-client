# Third-party software

`dod` itself is MIT-licensed (see [LICENSE](LICENSE)); the DODP v1 specification copy in [docs/spec/](docs/spec/) is not (see the README). This file lists the third-party software `dod` depends on and its licence. Keep it up to date when a dependency is added or removed.

## Runtime dependencies

Installed with `dod-client`, directly or transitively.

| Package | Licence | Notes |
| --- | --- | --- |
| [Typer](https://pypi.org/project/typer/) | MIT | Command line. Contains an adapted copy of [Click](https://github.com/pallets/click) (BSD-3-Clause), with its licence. |
| [Rich](https://pypi.org/project/rich/) | MIT | Via Typer; help panels and terminal output. |
| [markdown-it-py](https://pypi.org/project/markdown-it-py/) | MIT | Via Rich. |
| [mdurl](https://pypi.org/project/mdurl/) | MIT | Via markdown-it-py. |
| [Pygments](https://pypi.org/project/Pygments/) | BSD-2-Clause | Via Rich. |
| [shellingham](https://pypi.org/project/shellingham/) | ISC | Via Typer. |
| [annotated-doc](https://pypi.org/project/annotated-doc/) | MIT | Via Typer. |
| [HTTPX](https://pypi.org/project/httpx/) | BSD-3-Clause | HTTP transport. |
| [httpcore](https://pypi.org/project/httpcore/) | BSD-3-Clause | Via HTTPX. |
| [h11](https://pypi.org/project/h11/) | MIT | Via httpcore. |
| [anyio](https://pypi.org/project/anyio/) | MIT | Via HTTPX. |
| [certifi](https://pypi.org/project/certifi/) | MPL-2.0 | Via HTTPX; CA bundle. |
| [idna](https://pypi.org/project/idna/) | BSD-3-Clause | Via HTTPX. |
| [platformdirs](https://pypi.org/project/platformdirs/) | MIT | Platform configuration, state and data directories. |
| [filelock](https://pypi.org/project/filelock/) | Unlicense | Session file locking (public domain dedication). |
| [lxml](https://pypi.org/project/lxml/) | BSD-3-Clause | XML and schema validation. The binary wheels bundle libiconv, which is LGPL-2.1. |

**lxml and redistribution.** `dod` is distributed as a wheel and an sdist only; lxml is installed by the user's package installer from PyPI, not shipped by us. The assessment that this is compatible with the LGPL-2.1 libiconv in the lxml wheels is a technical assessment by the developers, not a legal opinion. Distributing standalone binaries, Docker images or anything else that contains lxml, or vendoring lxml, requires a new licence assessment first.

## Optional runtime dependencies

### `dod-client[play]`

Installed only with `dod-client[play]` (audio playback for `dod play`). There are no wheels for every platform (not for Linux arm64, Windows arm64 or Python 3.15), where `dod play` explains what is missing. The development environment installs it too, for the tests on its NULL backend.

| Package | Licence | Notes |
| --- | --- | --- |
| [miniaudio](https://pypi.org/project/miniaudio/) | MIT | Python bindings; the wheels bundle the C libraries miniaudio, dr_libs and stb_vorbis, which are public domain or MIT-0. |
| [cffi](https://pypi.org/project/cffi/) | MIT-0 | Via miniaudio. |
| [pycparser](https://pypi.org/project/pycparser/) | BSD-3-Clause | Via cffi. |

### `dod-client[tui]`

Installed only with `dod-client[tui]` (the terminal user interface, `dod tui`). All of them are pure Python wheels, so there is no platform or Python version without them (Python 3.15 included). The development environment installs Textual too, for the TUI tests on its headless `Pilot`.

| Package | Licence | Notes |
| --- | --- | --- |
| [Textual](https://pypi.org/project/textual/) | MIT | The terminal user interface framework. Playing in it needs `dod-client[play]`, as `dod play` does. |
| [markdown-it-py](https://pypi.org/project/markdown-it-py/) | MIT | Via Textual (with its `linkify` extra); already listed above. |
| [mdit-py-plugins](https://pypi.org/project/mdit-py-plugins/) | MIT | Via Textual. |
| [linkify-it-py](https://pypi.org/project/linkify-it-py/) | MIT | Via markdown-it-py's `linkify` extra. |
| [typing-extensions](https://pypi.org/project/typing-extensions/) | PSF-2.0 | Via Textual. |

## Build backend

Used to build the wheel and sdist; not installed with `dod-client`.

| Package | Licence |
| --- | --- |
| [hatchling](https://pypi.org/project/hatchling/) | MIT |
| [hatch-vcs](https://pypi.org/project/hatch-vcs/) | MIT |

## Development tools

Used for development and CI only; not distributed. Their own transitive dependencies are not listed here.

| Tool | Licence | Notes |
| --- | --- | --- |
| [uv](https://pypi.org/project/uv/) | MIT OR Apache-2.0 | Environment and dependency management, builds. |
| [pytest](https://pypi.org/project/pytest/) | MIT | Tests. |
| [Ruff](https://pypi.org/project/ruff/) | MIT | Lint and format. |
| [mypy](https://pypi.org/project/mypy/) | MIT | Static type checking (strict). |
| [tach](https://pypi.org/project/tach/) | MIT | Module boundary checks. The Rust libraries compiled into its wheels have not been licence-reviewed. |
| [lxml-stubs](https://pypi.org/project/lxml-stubs/) | Apache-2.0 | Type stubs for lxml, for mypy. |
