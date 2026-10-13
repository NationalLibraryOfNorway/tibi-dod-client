# Libraries and licences (issue #4)

Research for wayfinder map #1. Question: which third-party dependencies should be pinned, what licence does each carry, and do we need a SOAP library or build the SOAP layer ourselves?

Retrieved 2026-10-13. Sources are PyPI JSON metadata (`https://pypi.org/pypi/<name>/json`, fields `license_expression`, `license`, `classifiers`, `requires_python`, `requires_dist`), and the projects' own documentation and repositories. Licence identifiers are SPDX. Where PyPI has no SPDX `license_expression`, the identifier is taken from the `license` field or classifier.

## Recommendation in short

| Component | Role | Version seen | Licence (SPDX) | Verdict |
|---|---|---|---|---|
| Typer | CLI | 0.27.3 | MIT | Use |
| Textual | TUI (M6) | 8.2.8 | MIT | Use, as an optional extra |
| HTTPX | HTTP transport | 0.28.1 | BSD-3-Clause | Use |
| lxml | XML build and parse | 6.1.3 | BSD-3-Clause (wheels also bundle zlib, libxml2, libxslt, iconv; see below) | Use |
| pytest | Tests | 9.1.1 | MIT | Use (dev dependency) |
| mpv | External player process | n/a (not a Python dependency) | GPL-2.0-or-later, or LGPL-2.1-or-later when built with `-Dgpl=false` | Optional external program; never bundle or link |
| SOAP library (zeep) | Not needed | 4.3.3 | MIT | Do not use; build a thin SOAP layer on lxml and HTTPX |

Additional dependencies worth adding (all permissive): `platformdirs` (MIT) for per-OS config/session directories, `filelock` (MIT) for the session-file locking the design requires. Reading TOML needs only the stdlib `tomllib` (Python 3.11+); writing needs `tomli-w` (MIT) if ever required. Test helper candidates: `respx` (BSD-3-Clause) or `pytest-httpx` (MIT), both mock HTTPX. Add them only when the PRD needs them.

The only copyleft component inside the Python distribution is the LGPL-2.1 `iconv` bundled in lxml binary wheels (see lxml). `certifi` (an HTTPX dependency) is MPL-2.0.

## Per-dependency findings

### Typer (MIT)

- PyPI: `license_expression` is `MIT`; `requires_python >=3.10`; classifier `OS Independent`. Runtime dependencies: `shellingham` (ISC), `rich` (MIT), `annotated-doc` (MIT), `colorama` on Windows only (BSD). Click is not in `requires_dist`; the Typer docs navigation mentions a "Vendored Click" section, so check the Typer docs before importing `click` directly.
- Fit: hierarchical subcommands (`dod service info`) are the core Typer feature. Data to stdout and diagnostics to stderr is supported via a Rich `Console(stderr=True)` (Typer docs, "Printing and Colors"). The same page warns PowerShell may not show stderr in the terminal by default; relevant when testing "diagnostics to stderr" on Windows.
- Risk: Rich adds ANSI styling; commands emitting machine-readable output must bypass Rich markup and honour non-TTY and `NO_COLOR`. Verify during M1.

### Textual (MIT)

- PyPI: `license` field `MIT`, classifiers `MIT License`, `Linux`, `MacOS`, `Windows 10`, `Windows 11`; `requires_python >=3.9,<4.0`. Dependencies: `rich` (MIT), `markdown-it-py` (MIT), `mdit-py-plugins` (MIT), `platformdirs` (MIT), `pygments` (BSD-2-Clause). Tree-sitter packages are only in the optional `syntax` extra.
- Fit: the Textual getting-started page lists Linux, macOS and Windows. It notes macOS Terminal.app supports only 256 colours and recommends Windows Terminal on Windows.
- Recommendation: declare as an optional extra (`dod[tui]`) so the CLI and test tooling install without the TUI stack. Textual requires `rich>=14.2.0`, which also constrains the Rich version Typer gets.

### HTTPX (BSD-3-Clause)

- PyPI: `license` field `BSD-3-Clause`; `requires_python >=3.8`. Core dependencies: `anyio` (MIT), `certifi` (MPL-2.0), `httpcore` (BSD-3-Clause), `idna` (BSD-3-Clause). `httpcore` pulls `h11` (MIT). HTTP/2 is an optional extra (`h2`, MIT).
- `certifi` is MPL-2.0 (PyPI `license` field and classifier): file-level copyleft, unproblematic as an unmodified package dependency, but note it for procurement.
- Sessions and cookies: "cookies should always be set on the client rather than on a per-request basis" (HTTPX compatibility docs). It exposes `httpx.Cookies`, so a jar can be loaded into `Client(cookies=...)` at start and read back at exit; the on-disk format is ours to choose. Redirects are not followed by default (same page), which suits diagnostics because every hop is visible.
- Raw XML diagnostics: event hooks receive the `Request` before sending and the `Response` before it is returned; "Response event hooks are called before determining if the response body should be read", so a hook must call `response.read()` to see the body (HTTPX event hooks docs). Built-in debug logging (`httpx`, `httpcore` loggers) shows headers but not bodies, and its format "may be subject to change" (HTTPX logging docs). Conclusion: built-in logging is not enough; build transcripts ourselves from request and response bytes via event hooks or by wrapping `Client.send`.
- Limit: exact wire bytes (header order and casing) are not exposed; transcripts are reconstructed from the parsed objects. Acceptable for protocol diagnosis; state it in the diagnostics ADR.

### lxml (BSD-3-Clause, with bundled third-party libraries in wheels)

- PyPI: `license` field `BSD-3-Clause`; `requires_python >=3.8`; no mandatory dependencies.
- Wheel licence file (downloaded `lxml-6.1.3` manylinux x86_64 wheel for CPython 3.12, `dist-info/licenses/LICENSES.txt`): lxml itself is BSD-3-Clause (Infrae). The file also lists the statically included libraries `zlib` (zlib licence), `iconv` (LGPL-2.1), and `libxml2`, `libxslt`, `libexslt` (MIT-style). The LGPL-2.1 `iconv` is the item to raise with procurement. Installing lxml unmodified from PyPI is the ordinary case; do not repackage lxml wheels into a single-file binary without a licence review.
- Platforms: lxml's installation page states binary wheels for macOS (universal2, Python 3.9+) and says it tries to provide up-to-date Windows wheels; Linux manylinux wheels are on PyPI (confirmed by download). Verify wheel availability per supported Python and architecture in CI.
- Fit for raw XML diagnostics: namespace-aware building (`etree.Element` with `nsmap`), explicit control over serialisation, and XPath. That is what a hand-built SOAP envelope needs. Parse responses from arbitrary backends with a restricted `XMLParser` (`resolve_entities=False`, `no_network=True`, `huge_tree=False`) to limit XXE and entity-expansion risk.

### pytest (MIT)

- PyPI: `license_expression` `MIT`; `requires_python >=3.10`; dependencies `pluggy` (MIT), `iniconfig` (MIT), `packaging` (Apache-2.0 OR BSD-2-Clause), `pygments` (BSD-2-Clause), `colorama` on Windows (BSD).
- Fit: classifiers list `POSIX`, `Unix`, `MacOS`, `Windows`. Development dependency only. Markers (for example a `backend` marker deselected by default) cover the acceptance criterion that real-backend tests run only when explicitly started. For mocking HTTPX: `respx` (BSD-3-Clause) or `pytest-httpx` (MIT; pins `httpx==0.28.*` and `pytest==9.*`, which couples upgrades).

### mpv (external process; GPL-2.0-or-later / LGPL-2.1-or-later)

- mpv's `Copyright` file: the project as a whole is GPLv2+, or LGPLv2.1+ if built without GPL-only files; the `-Dgpl=false` build switch excludes them. The same file cautions that linked libraries can still affect the final binary's licence. Distribution binaries are normally GPL builds.
- If `dod` only launches `mpv` as a separate process (command line or its IPC), it is not linked, bundled or redistributed, so mpv's licence does not constrain `dod`'s licence. Do not add `python-mpv` (PyPI: `GPLv2+ or LGPLv2.1+`, loads libmpv in-process) without a licence review.
- Cross-platform: the user installs mpv; locate it on `PATH` with a configurable override. `dod` must run without it (design requirement).

### SOAP library: not needed

- Candidates checked: `zeep` 4.3.3 (MIT; depends on `lxml`, `requests` (Apache-2.0), `requests-toolbelt`, `requests-file`, `attrs`, `isodate`, `platformdirs`). Its default transport is `requests`; an async transport uses `httpx` (zeep transport docs). `suds-community` 1.2.0 is LGPL (PyPI classifier).
- Why not zeep: (1) a second HTTP stack (`requests`) next to HTTPX, or a forced async split; (2) it builds the envelope from the WSDL, so deliberately malformed requests (negative tests, M4) and byte-exact control are harder; (3) raw XML is reachable only through a logging or `HistoryPlugin` side channel, while the design makes raw XML the primary output; (4) the design already says the protocol logic must be our own.
- Open item for the protocol-spec research issue, not decided here: whether the DODP v1 WSDL uses a binding style that generic libraries handle poorly. That would reinforce this recommendation, not change it.
- The own layer needs only: an envelope builder on lxml, a POST of the bytes via HTTPX returning raw bytes plus the parsed tree, a Fault detector, and per-operation builders derived from the WSDL. No extra dependency.

## Pinning policy suggestion

- Declare compatible ranges in `pyproject.toml` (for example `typer>=0.27,<1`, `httpx>=0.28,<1`, `lxml>=6,<7`, `textual>=8,<9` in an extra) and commit a lock file for reproducible CI. Which locker to use is a separate decision; its licence must be checked before adoption (not verified here).
- HTTPX is pre-1.0 and documents unstable log formats; keep an upper bound.
- Python floor: Textual 3.9+, Typer 3.10+, pytest 9 3.10+, latest `platformdirs` and `filelock` 3.11+. The proposed 3.12+ is compatible with all.

## Not verified

- The `iconv` licence as bundled in macOS and Windows lxml wheels; only the Linux x86_64 wheel was inspected.
- Whether Typer vendors Click in every release (inferred from `requires_dist` and docs navigation).
- Rich behaviour under `NO_COLOR` and piping; to be tested in M1.
