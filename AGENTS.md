## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues (NationalLibraryOfNorway/tibi-dod-client) via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Checks

There is no global `python`; run everything through `uv run`. Before every commit run `uvx pre-commit run --all-files` (ruff, format, mypy, tach, pytest; the same steps as CI, defined in `.pre-commit-config.yaml`).

### Coding standards

Judgement calls for review are in `CODING_STANDARDS.md`; mechanical rules are enforced by ruff, mypy and tach, not written down.
