# Coding standards

Read during review. Anything ruff, mypy, tach (module boundaries, ADR 0003) or the tests enforce is not repeated here. Architectural rules live in `docs/adr/`; a change that breaks one is a finding, whatever this file says.

- **Match the surrounding code**: comment density, naming, idiom. A new module reads like its neighbours.
- **Use the glossary**: names in code, tests, help text and messages are the terms of `GLOSSARY.md` (Service, Session, Exchange, Reply, Observation, Quirk, Baseline).
- **Relogin only through `SessionManager`** (ADR 0005). The conformance runner is the one documented exception; any other caller of a logon outside it is a finding.
- **Untrusted text**: everything the Service names (ids, URLs, paths, messages) is untrusted (ADR 0008); it is sanitised before display and never used as a path or a command unchecked.
- **Secrets**: masking is always on (ADR 0007). Tests, examples and docs use synthetic users, passwords and hosts (`dod.example.org`); the repo is public.
- **Tests go through the interface** (ADR 0003): subprocess or the public `dod` API against the fake Service, not private modules.
- **Environment-sensitive output** (Rich ANSI under `GITHUB_ACTIONS`, Windows box characters, no `miniaudio` wheel on Python 3.15) is asserted on structure, not on exact glyphs or colour codes.
