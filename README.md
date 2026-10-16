# dod

`dod` is a cross-platform test client for DODP v1 (DAISY Online Delivery Protocol) backends. See [GLOSSARY.md](GLOSSARY.md) for the terms used and [docs/adr/](docs/adr/) for design decisions.

## Usage

`dod logon` runs the Initialisation sequence (`logOn`, `getServiceAttributes`, `setReadingSystemAttributes`) against a Service. Until stored Sessions arrive it only works in ephemeral mode: it ends with `logOff` and keeps nothing.

```sh
dod logon --no-session --url https://dod.example.org/service --username alice
echo "$PASSWORD" | dod logon --no-session --url https://dod.example.org/service \
    --username alice --password-stdin
```

The password is read from a prompt without echo, or from the first line of stdin with `--password-stdin`; it is never taken from an argument. An `http` address is refused unless `--insecure` is given, also on loopback, and then gives the Observation `transport-security`. Results go to stdout, Observations and diagnostics to stderr. Exit codes: 0 ok, 1 the Service answered with a Fault or contrary to the specification, 2 no usable answer or the command could not be run. `--no-session` can also be set with `DOD_NO_SESSION=1`. See `dod logon --help`.

### Finding the endpoint

`dod` never guesses the Service endpoint while logging on (ADR 0002). Name it with `--url` (the SOAP endpoint itself), with `--wsdl` (the Service's WSDL; its `soap:address` is used) or through an Environment that holds one of them. `--url`, `--wsdl` and `--env` cannot be combined.

- The WSDL is fetched without credentials or cookies on every command and read safely: no DTD, no entities, no network, at most 1 MiB, with a timeout. `import` elements are never fetched; the bundled abstract DODP WSDL is used. Exactly one SOAP 1.1 port bound to the DODP portType is accepted; otherwise the ports are listed and the command exits with 2.
- A `soap:address` with another host, port or scheme than the WSDL came from is refused unless `--trust-host` (or `trust_host = true`) is given. A redirect across a host, port or scheme boundary is always refused.
- `https` is required; `http` needs `--insecure`, also on loopback.
- `dod discover <address>` tries `?wsdl` on the address and on the known paths (`/service`, `/dodp`, `/daisy-online`, `/DaisyOnline`), prints every address it tried and the kind of answer (never the content), sends no credentials and stores nothing. It exits with 2 and next steps when nothing is found. `logon` suggests it when an address does not answer like a DODP Service.
- Every command that contacts a Service prints `[environment] url` on stderr (`[-]` when no Environment is used); `--quiet` turns it off.

```sh
dod discover https://dod.example.org
dod logon --no-session --wsdl https://dod.example.org/service?wsdl --username alice
```

### Configuration and Environments

Named Environments live in a TOML file in the platform's configuration directory (`dod config path` prints it; `--config` or `DOD_CONFIG` selects another file). A missing default file is fine; a missing explicit one is an error. There is no project-local file.

```toml
default_environment = "test"

[environments.test]
url = "https://dod.example.org/service"   # exactly one of url and wsdl
username = "alice"
password = "..."        # plaintext, see docs/adr/0006
# insecure = false, trust_host = false, protected = false, quirks = []

[environments.local]
url = "http://127.0.0.1:8080/service"
insecure = true
```

Names match `[a-z0-9][a-z0-9_-]*`. Unknown keys, wrong types, and `token` or `cookie` are rejected every time the file is loaded, for all Environments. Errors exit with 2 and name the file, the key (`environments.<name>.<key>`), the reason and, for TOML syntax errors, the line. Password values are never printed.

- Environment: `--env`, then `DOD_ENV`, then `default_environment`. `--env` cannot be combined with `--url` or `--wsdl`.
- Username: `--username`, then `DOD_USERNAME`, then the file.
- Password: `--password-stdin`, then the file, then a prompt. There is no environment variable for it.
- On Linux and macOS `dod` refuses a file with a `password` that group or others can read (`chmod 600` it). On Windows permissions are not checked and `dod config check` warns about it.

`dod config check` validates every Environment without network access, and `dod config show` prints the effective configuration with the source of each value and `password = ***`. `dod logon --env test --no-session` logs on with an Environment.

## Global options

These flags are global: `--env --url --wsdl --username --config --format --debug --save-exchanges --quiet --no-session --insecure --trust-host --unmask --unmask-password --password-stdin`. They are listed in `dod --help` and are accepted before or after the command (`dod --quiet logon` and `dod logon --quiet` are the same), so every command inherits them. `--format text|json|xml` is `text` by default; a command without JSON or XML output refuses them with exit code 2 instead of ignoring them.

## Diagnostics and masking

Diagnostics only go to stderr or to files; stdout carries the result, so `dod logon --format json > out.json` is always valid JSON.

- `--debug` writes every Exchange as a readable block on stderr: method and URL, masked headers, pretty-printed SOAP, status and duration.
- `--save-exchanges <dir>` writes `NNN-<operation>.request.xml`, `.response.xml` and a small `.json` (method, URL, status, duration, headers) per Exchange; the directory is created if needed.
- `--format xml` writes the raw, masked responses to stdout, one per call. `--format json` writes a small result document.
- Masking is always on for stderr, files and reports (ADR 0007): the `logOn` password, the values of `Cookie`, `Set-Cookie`, `Authorization` and `Proxy-Authorization`, URL userinfo and credential-like query parameters become `***[ab12cd]`, a short fingerprint that is the same for the same value, so you can see that two Exchanges shared a Session. Fingerprints of passwords and userinfo are salted per run.
- `--unmask` (cookies and headers) and `--unmask-password` (the password, after a confirmation on stdin) work only with `--debug`, only from the command line (no environment variable or setting), and only when stderr is a terminal. They are refused with exit code 2 together with `--save-exchanges`, when stderr is not a terminal, and `--unmask-password` also with `--password-stdin` or when stdin is not a terminal. A warning is written before and after, and the secrets are highlighted with colour (not markers, so a copied message stays valid XML); with `NO_COLOR` only the warnings remain.
- Observations (`transport-security`, `cookie-hardening`, `host-boundary`, `interoperability`) are written on stderr, once per run, and never change the exit code.

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

### The fake Service

Tests run against `FakeService` in `tests/support/`, a DODP v1 Service on `127.0.0.1` that exists only in the tests and is not shipped. It answers with hand-written, synthetic documents and validates every response it builds against the local schema copies (`stop()` fails the test if one was invalid). Failures are injected per test and per operation, and each injection is used once:

| Call | The next call of the operation gets |
| --- | --- |
| `inject_fault(op, FaultKind.X, reason)` | one of the five DODP faults, HTTP 500 |
| `inject_http_500(op)` | HTTP 500 with a SOAP fault without a DODP element |
| `inject_not_soap(op, body)` | HTTP 200 with something that is not SOAP |
| `inject_no_answer(op)` | no answer: the connection is closed |
| `inject_delay(op, seconds)` | a correct answer after `seconds`, for timeout tests |
| `inject_redirect(op, location)` | a redirect, for example to another host or to `https` |

```python
def test_a_fault_is_a_value(service: FakeService, port: HttpServicePort) -> None:
    service.add_user("synthetic-user", "synthetic-secret")
    service.inject_fault("logOn", FaultKind.INVALID_PARAMETER, "synthetic reason")

    reply = port.log_on("synthetic-user", Password("synthetic-secret"))

    assert isinstance(reply, Fault) and reply.kind is FaultKind.INVALID_PARAMETER


def test_a_timeout_is_no_usable_answer(service: FakeService) -> None:
    service.inject_delay("logOn", seconds=30)  # never waited for
    port = HttpServicePort(service.url, client=httpx.Client(timeout=0.2))

    with pytest.raises(TransportError):
        port.log_on("synthetic-user", Password("synthetic-secret"))
```

`service.requests` lists what the Service received, which also shows that a redirected call never reached its target. See `tests/port/test_fault_injection.py` for every injection.

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
