# dod

`dod` is a cross-platform test client for DODP v1 (DAISY Online Delivery Protocol) backends. See [GLOSSARY.md](GLOSSARY.md) for the terms used and [docs/adr/](docs/adr/) for design decisions.

## Usage

`dod logon` runs the Initialisation sequence (`logOn`, `getServiceAttributes`, `setReadingSystemAttributes`) against a Service and stores the Session for later commands (see Sessions below). With `--no-session` it is ephemeral: it ends with `logOff` and keeps nothing.

```sh
dod logon --url https://dod.example.org/service --username alice
echo "$PASSWORD" | dod logon --no-session --url https://dod.example.org/service \
    --username alice --password-stdin
```

The password is read from a prompt without echo, or from the first line of stdin with `--password-stdin`; it is never taken from an argument. An `http` address is refused unless `--insecure` is given, also on loopback, and then gives the Observation `transport-security`. Results go to stdout, Observations and diagnostics to stderr. Exit codes: 0 ok, 1 the Service answered with a Fault or contrary to the specification, 2 no usable answer or the command could not be run. `--no-session` can also be set with `DOD_NO_SESSION=1`. See `dod logon --help`.

### Sessions

A Session file is kept per (resolved Service URL, username) so that later commands, also several at once, reuse one Session (ADR 0001, ADR 0005).

- `dod logon` calls `logOff` for a stored Session (a failure is ignored), runs the Initialisation sequence and writes the Session file only when the whole sequence succeeded. If `setReadingSystemAttributes` fails after `logOn`, `dod` tries `logOff` and stores nothing.
- Session files are JSON in `sessions/` under the state directory: `DOD_STATE_DIR`, else the platform's user state directory (on Linux `~/.local/state/dod`). They hold the Session cookie in clear text and never a password. On Linux and macOS the file is `0600` and the directories `dod` creates are `0700`; on Windows the user profile's default ACL applies and permissions are not set by `dod`. Writes are atomic and every access takes a file lock (`filelock`), which is never held during an ordinary Service call.
- A command that finds the Session expired (a `noActiveSession` fault in `detail`, nothing else) logs on again exactly once and repeats the call, but only when credentials exist (`--password-stdin`, the Environment's password); otherwise it asks you to run `dod logon`. When several processes meet an expired Session, only one logs on.
- `--no-session` or `DOD_NO_SESSION=1` is ephemeral mode: initialise, run, `logOff`, store nothing.
- `dod logoff` calls `logOff` and deletes the file whatever the Service answers (a failure is a warning). `dod session clear` deletes the file without network. `dod session status` is local; `--check` asks the Service with `getServiceAttributes` and exits 1 when the Session has expired. `dod status` shows the Environment, URL, user and whether the Session is `stored`, `none` or `ephemeral`; it sends nothing. The commands that do not send anything need `--url` or an Environment with a `url` (a WSDL is not fetched for them).

### Attributes and announcements

Ordinary commands reach the Service through the session manager: they reuse the stored Session and log on again once, with the credentials above, when it has expired (ADR 0005). With `--no-session` they log on, run and log off.

- `dod attributes service` shows what the Service says it supports (`getServiceAttributes`), `--format json` as a document and `--format xml` as the raw, masked response.
- `dod attributes reading-system [--file <xml>]` sends the declaration (`setReadingSystemAttributes`) and shows the answer. By default `dod` declares the producer and version of the installed package, DAISY 2.02 and EPUB 3, `audio/mpeg` and `audio/wav`, and the input types `TEXT_NUMERIC` and `TEXT_ALPHANUMERIC`. `--file` names a `readingSystemAttributes` XML document that replaces all of it; so does the Environment's `reading_system` key (a path, relative to the configuration file), which `dod logon` and every relogin then declare as well. The flag beats the key. The file is validated against the local schemas before anything is sent; elements from other namespaces are not sent on.
- `dod logon` asks for the announcements right after the Initialisation sequence when the Service declares `SERVICE_ANNOUNCEMENTS`, and shows them without marking them as read. A fault on that call is shown as it is and does not end the Session.
- `dod announcements list` shows the unread announcements. `dod announcements mark-read <id>...` or `--all` marks them; because the specification only accepts identifiers from a `getServiceAnnouncements` of the same Session, it fetches first, and `--all` uses the identifiers of that fetch. If the Service answers `invalidParameter` for the set, the identifiers are tried one at a time; `false` from the Service is reported as "already read".
- A Service that does not support an operation gives its `Fault` or `Deviation` as it is (exit code 1). Text from the Service is shown with control characters replaced by spaces.

### The shelf and the catalogue

- `dod list` shows the shelf (`getContentList` with `issued`). `dod list --id <list>` shows another list: `new`, `expired`, a dynamic list from a menu or a `contentListRef`. Quote an id that has spaces; it is sent as given. `--first` and `--last` pick a segment counted from 0 (`--last -1`, the default, is the end of the list); an invalid range gives an empty list and the total.
- `dod metadata <id>` shows `getContentMetadata` for any book, issued or not.
- `--format json` is a stable document (`result` plus `list` or `metadata`) that can go to `jq`; `--format xml` is the raw, masked response. Elements `dod` does not model are left out of text and JSON but stay in the raw response.
- Reading is tolerant: an identifier that is not an `xs:NMTOKEN` (some menus have spaces in theirs) or any other schema violation is reported on stderr as a schema violation, not as a failure.

### Conformance tests

`dod test run` runs Conformance tests against a Service and reports one Outcome per test; `dod test list` shows the stable, hierarchical test ids (`session.logon.wrong-password`). The first families are `session`, `attributes` and `catalog`, and `negative` (explicit, see below).

- Outcomes: **PASS** (the Service answered as the specification requires), **FAIL** (it answered contrary to it), **SKIP** (the test does not apply or was not opted into) and **ERROR** (the test could not be evaluated, for example no answer or not SOAP). A fault is classified on its DODP element in `detail`, never on the HTTP status or `faultstring`; HTTP 500 without a DODP element is a FAIL. An optional operation is SKIP when it is not in `supportedOptionalOperations` and answers `operationNotSupported`, FAIL when it is declared but answers `operationNotSupported`, and PASS with a note when it works without being declared.
- The run logs on with a Session of its own (never a stored one, ADR 0005) and ends it afterwards. A setup that cannot log on is an ERROR that ends the run at once; the tests of logging on, such as a wrong password, are separate PASS/FAIL tests.
- `--only <prefix>` and `--skip <prefix>` (repeatable) choose tests by id prefix on whole dotted segments. State-changing tests are SKIP unless `--state-changing` is given, and against an Environment with `protected = true` that also needs `--confirm-env <name>`.
- The text report is one line per test, a summary and an `Observations` section; a FAIL names the section of the specification with a link to the published HTML version (clickable on a terminal that supports it). `--format json` is a versioned report (`schema_version`) with Exchange ids and the masked Exchanges of FAIL and ERROR tests; `--report-exchanges all|failures|none` changes which are included.
- The negative tests (`negative.*`) send deliberately invalid requests through a `RawChannel`: no Session (`noActiveSession`), an operation before the Initialisation sequence is complete (`invalidOperation`), an unknown operation, and invalid parameters (`invalidParameter`). Each works in an Ephemeral-mode Session of its own, so a stored Session is never touched. They are explicit: an ordinary run leaves them out and `dod test run --only negative` runs them (`dod test list` shows them). A `logOff` that fails afterwards is an ERROR on a record of its own, `<test id>.cleanup`, and the test keeps its PASS or FAIL.
- Exit code 0 without FAIL or ERROR, 1 with FAIL and no ERROR, 2 with any ERROR. There are no requirement levels and no `--strict`.

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
# reading_system = "reading-system.xml"   # replaces the default declaration

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
| `defer_injection(op, calls)` | lets `calls` normal answers through before an injection for `op` fires, e.g. to get past a test's setup |

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
