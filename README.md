# dod

`dod` is a cross-platform test client for DODP v1 (DAISY Online Delivery Protocol) backends. See [GLOSSARY.md](GLOSSARY.md) for the terms used and [docs/adr/](docs/adr/) for design decisions.

## Development

`dod` needs Python 3.12 or later and uses [uv](https://docs.astral.sh/uv/) for its development environment. The distribution is called `dod-client`, the command `dod` and the import package `dod`; the version comes from the git tag.

```sh
uv sync                      # create .venv with dod and the development tools
uv run dod --help
```

Checks (CI runs the same on Linux, macOS and Windows):

```sh
uv run ruff check            # lint
uv run ruff format --check   # formatting (drop --check to reformat)
uv run mypy                  # strict type checking
uv run tach check            # layer order and module interfaces, see tach.toml
uv run pytest                # tests
```

Tests against a real Service are marked `real_backend` and deselected by default; run them with `uv run pytest -m real_backend`. They never run in CI, and no credentials or addresses belong in the repository.

Build the wheel and sdist with `uv build`, and install the wheel with `pipx install dist/dod_client-*.whl`.

Third-party dependencies and their licences are listed in [THIRD-PARTY.md](THIRD-PARTY.md).

## Credits

The DAISY Online Delivery Protocol is specified by the [DAISY Consortium](https://daisy.org/). This repository keeps an unmodified local copy of the DODP v1 specification (Proposed Recommendation, 2 April 2010) with its WSDL and XML schemas, and of the external schemas that the DODP schemas import, so that documents can be validated without network access:

- Local copy: [docs/spec/dodp-v1/](docs/spec/dodp-v1/) ([specification](docs/spec/dodp-v1/do-spec-20100402.html), [WSDL](docs/spec/dodp-v1/do-wsdl-10.wsdl), [types schema](docs/spec/dodp-v1/do-types-10.xsd))
- Official source: [do-spec-20100402.zip](https://dl.daisy.org/standards/DODP/do-spec-20100402.zip) (SHA-256 `69e45be14f7920823714b31ce1ebcdc5cf53b6c62a95f8274204f1051853c234`), published from the DAISY Consortium's [DODP page](https://daisy.org/?p=492)
- External schemas, kept next to the specification in [docs/spec/dodp-v1/](docs/spec/dodp-v1/), each fetched unchanged from the address the DODP schemas import it from:
  - [KeyExchange-2005-1.xsd](docs/spec/dodp-v1/KeyExchange-2005-1.xsd), DAISY Consortium: <http://www.daisy.org/DRM/KeyExchange-2005-1.xsd>
  - [xml.xsd](docs/spec/dodp-v1/xml.xsd), W3C: <http://www.w3.org/2009/01/xml.xsd>
  - [dc.xsd](docs/spec/dodp-v1/dc.xsd), Dublin Core Metadata Initiative: <http://dublincore.org/schemas/xmls/qdc/2008/02/11/dc.xsd>
  - [xenc-schema.xsd](docs/spec/dodp-v1/xenc-schema.xsd), W3C: <http://www.w3.org/TR/xmlenc-core/xenc-schema.xsd>
  - [xmldsig-core-schema.xsd](docs/spec/dodp-v1/xmldsig-core-schema.xsd), W3C: <http://www.w3.org/TR/2002/REC-xmldsig-core-20020212/xmldsig-core-schema.xsd>

The copies are verbatim and the copyright remains with the DAISY Consortium, the W3C and the Dublin Core Metadata Initiative respectively. These files are not covered by this repository's licence. The spec copy and the schemas are part of the sdist and not of the wheel.

The XML catalog [schemas/catalog.xml](schemas/catalog.xml) maps the remote addresses above to these local copies; `dod.infrastructure.validate_document` uses it to validate a DODP v1 document and returns the findings as values. It needs a source checkout or the sdist, and raises `SchemaUnavailableError` from an installed wheel.
