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

## Planned runtime dependencies

Decided in the specification and added by the tickets that need them.

| Package | Licence | Notes |
| --- | --- | --- |
| [HTTPX](https://pypi.org/project/httpx/) | BSD-3-Clause | HTTP transport. |
| [certifi](https://pypi.org/project/certifi/) | MPL-2.0 | Via HTTPX; CA bundle. |
| [lxml](https://pypi.org/project/lxml/) | BSD-3-Clause | XML and schema validation. The binary wheels bundle libiconv, which is LGPL-2.1. |
| [platformdirs](https://pypi.org/project/platformdirs/) | MIT | Configuration, state and data directories. |
| [filelock](https://pypi.org/project/filelock/) | Unlicense | Session file locking. |
| [Textual](https://pypi.org/project/textual/) | MIT | Optional, `dod-client[tui]`. |
| [miniaudio](https://pypi.org/project/miniaudio/) | MIT | Optional, `dod-client[play]`. |

**lxml and redistribution.** `dod` is distributed as a wheel and an sdist only; lxml is installed by the user's package installer from PyPI, not shipped by us. The assessment that this is compatible with the LGPL-2.1 libiconv in the lxml wheels is a technical assessment by the developers, not a legal opinion. Distributing standalone binaries, Docker images or anything else that contains lxml, or vendoring lxml, requires a new licence assessment first.

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
