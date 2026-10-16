# dod

`dod` is a cross-platform test client for DODP v1 (DAISY Online Delivery Protocol) backends. See [GLOSSARY.md](GLOSSARY.md) for the terms used and [docs/adr/](docs/adr/) for design decisions.

## Install

Releases are published on [GitHub](https://github.com/NationalLibraryOfNorway/tibi-dod-client/releases); there is no PyPI package yet. Each release has a wheel, an sdist and a `SHA256SUMS` file. Download the files, check them, and install the wheel (extras go in brackets, for example `[tui]` and `[play]`):

```sh
sha256sum --check --ignore-missing SHA256SUMS
pipx install ./dod_client-X.Y.Z-py3-none-any.whl
pipx install './dod_client-X.Y.Z-py3-none-any.whl[tui,play]'
```

Or install straight from a tag (needs git; the version is taken from the tag):

```sh
pipx install 'git+https://github.com/NationalLibraryOfNorway/tibi-dod-client@vX.Y.Z'
```

Versions follow [SemVer](https://semver.org/) and are `0.x` for now, so minor versions may break; see [CHANGELOG.md](CHANGELOG.md). The sdist contains the specification copy and the schemas, the wheel does not.

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

### Menus

- `dod questions` calls `getQuestions` with the reserved answer `default` and shows the root question. Every call is one step and `dod` keeps no position in the menus: the Service decides what comes next. Each question and choice is shown as the arguments of the next command, with the choice's label as a comment, for example `answer main 'two words'    # Old books`; ids and values with spaces are quoted. `--format json` lists the questions with their `id`, `label`, `choices` or `input_types` and whether `dod` can answer them; `--format xml` is the raw, masked response.
- `dod questions answer <questionID> <value>` sends one answer per call (multiple selections are not supported). `dod questions search [<text>]` sends the reserved `search`, with the text as the value when given. `dod questions back` sends the reserved `back` and shows the Service's reply unchanged; some Services do not support it and answer with a fault or an HTTP error, which is shown as it came.
- A menu ends in an endpoint: `contentListRef: <ref>` is followed with `dod list --id <ref>`, and `label: <text>` is a message. Nothing is built into `dod` about any one backend's question ids. IDs are read and sent as given, also when they have spaces against `xs:NMTOKEN`.
- `dod` declares the input types it supports in `setReadingSystemAttributes` (`TEXT_NUMERIC` and `TEXT_ALPHANUMERIC`, not `AUDIO`). An input question that only accepts other types is shown, marked as one `dod` cannot answer.
- The command can always be called, whatever `supportedOptionalOperations` says (`DYNAMIC_MENUS`). The Conformance test `questions.default` sends only `default` and expects a schema-valid answer; it is SKIP for a Service that neither declares nor supports the operation.

### Issue and return

- `dod issue <id>` calls `issueContent` and shows the Reply unchanged (`issueContent: ok`, or the fault as it came). It is the only command that borrows a book.
- `dod return <id>` deletes the local copy first, as the specification requires, and then calls `returnContent`. Only `<data>/<environment>/books/<id>/` is ever deleted (see below for `<data>`), after a confirmation unless `--yes`; when the Service's metadata says `requiresReturn` is `false` the return is refused with nothing deleted, unless `--force`. `--keep-local` returns without deleting and warns that this breaks the specification; it is also the only way to return without an Environment, since the local copy cannot be located then. A declined confirmation, a failed deletion or a refusal sends no `returnContent` (exit 2 for a refusal).
- `returnContent` answers `true` or a fault, also when the book was already returned; `false` is reported as a Spec deviation (exit 1). `--format json` is a document with `result`, `local_copy` (`deleted`, `none` or `kept`) and `directory`; `return` has no xml output.

### Bookmarks and key exchange

- `dod bookmarks get <id>` calls `getBookmarks` and shows the `bookmarkSet` as the Service sent it (`--format json` adds a summary: title, uid, lastmark and the number of bookmarks and highlights; `--format xml` is the raw, masked response). It is read leniently: a lastmark with parts missing or `xsi:nil` is shown as it is.
- `dod bookmarks set <id> --file <xml>` calls `setBookmarks`. The file is checked against the local bookmark schema first (and must have no DOCTYPE and be at most 1 MiB); a file that does not conform is refused with exit code 2 and nothing is sent, otherwise it is sent as it is. **`setBookmarks` replaces the whole set** (title, lastmark, bookmarks and highlights): read the current set with `get` first, change that and send it back. The `uid` should be the book's identifier, which some Services insist on.
- `dod key-exchange <name>` calls `getKeyExchangeObject`, which asks the Service for a PDTB2 Key Exchange Object. It is rarely used. `dod` does not interpret the key and supports no DRM (PDTB2, Readium LCP). The answer is shown as it came, except that key material (`UAK` and `CipherValue` contents) is masked in every output (ADR 0007).
- The commands can always be called, whatever `supportedOptionalOperations` says (`GET_BOOKMARKS`, `SET_BOOKMARKS`, `PDTB2_KEY_PROVISION`); a Service without the operation answers `operationNotSupported`, shown as it came. The Conformance tests are the ones that look at the declaration.

### Resources and download

- `dod resources <id>` shows `getContentResources` for an issued book as the Service gave it: address, `localURI`, size and MIME type. Nothing is downloaded. Userinfo in an address is masked.
- `dod download <id>` calls `getContentResources` and then fetches each file with one HTTP GET, one after the other (no resume, no parallelism, no zip). It never issues the book itself: run `dod issue` first. For a book that is not issued the Service's `invalidParameter` fault is shown as it came (exit 1).
- `--file <localURI>` (repeatable) fetches only the chosen files. The files go to `<data>/<environment>/books/<id>/`, where `<data>` is `DOD_DATA_DIR`, else the platform's user data directory (on Linux `~/.local/share/dod`) and the book id is encoded as one safe path segment. `--output <dir>` puts them in `<dir>` instead and is required without an Environment.
- Everything the Service names is untrusted. Every `localURI` of the list is checked before the first byte is fetched: relative, no `..`, backslashes, drive letters or characters Windows forbids, no duplicates, and inside the target directory. One bad entry aborts with nothing written and is reported as a Spec deviation (exit 1). A file is written to a `.part` file and renamed only when its size is the announced one; otherwise it is discarded. Existing files are not overwritten without `--force`.
- A relative address is resolved against the Service URL (Observation `interoperability`). An address on another host, port or scheme (a Service Delegate) is refused without `--trust-host` (Observation `host-boundary`); the Session cookie and your password are never sent there, only userinfo in the address itself and only to that host. `https` is required unless `--insecure`. Redirects are not followed.
- Any status but 2xx is a Spec deviation and never causes a new login. An Exchange keeps the headers and the first 4 KiB of a resource body, marked as cut.
- `--format json` is a stable document; `download` has no xml output.

### Play

`dod play <id>` plays a downloaded DAISY 2.02 or EPUB 3 book from the files on disk (ADR 0009). It never streams and fetches nothing unless you pass `--fetch-missing`: run `dod issue` and `dod download` first. Audio needs the optional `miniaudio` (MIT): `pip install 'dod-client[play]'`. It decodes WAV, FLAC, MP3 and Ogg Vorbis, not AAC. Where it has no wheels (for example Linux arm64, Windows arm64, Python 3.15) `dod play` exits with 2 and says what is missing.

- The order is derived from the book's own SMIL: `master.smil` if there is one, otherwise the SMIL files `ncc.html` first links to, each once; every `audio` element of them (nested `seq` included) is one Clip. Headings, page numbers and text are ignored. There is no fallback to file-name order or to the `resources` order: a book without SMIL (`audioOnly`) is refused with an explanation. A `clip-begin` or `clip-end` that is missing means from the start of the file or to its end.
- For EPUB 3 (a book with `META-INF/container.xml` and neither `master.smil` nor `ncc.html`) the order is the package document's spine; the `media-overlay` of each spine item names its SMIL overlay, each played once, and every `audio` element of it (nested `par` and `seq` included, `clipBegin`/`clipEnd` or `clip-begin`/`clip-end`) is one Clip. An audio path may climb out of the overlay's directory with `..` but never out of the book. Spine items without an overlay are skipped; an EPUB where none has one (a text-only book) is refused with an explanation, never played in silence.
- SMIL and `ncc.html` are untrusted: they are parsed without entities, DTDs or network access (a document that declares entities is refused), and every path in them is validated like a `localURI` (relative, no `..`, no links out of the book directory).
- The book is read from `<data>/<environment>/books/<id>/` (see above), or from `--directory <dir>`. Every audio file must be on disk and decodable before the first sound; a missing file is refused, and a format `miniaudio` cannot decode is an error with the Observation `audio-format`.
- While playing, type a command and press Enter: `p` pause or resume, `n` next Clip, `b` previous Clip, `f` forward 30 seconds, `r` back 30 seconds, `q` stop, and an empty line shows the status. The status line shows the audio file's path in the book, its place among the distinct files (`file 3 of 7`) and the elapsed and total Playlist time. Pause, resume and jumps stop the device and restart it from a frame offset; the position is the count of frames handed to the device and runs slightly ahead of what is heard. From a pipe the lines are applied in order and the book then plays to its end.
- `--fetch-missing` fetches the audio files that are not in the book directory, one at a time and before playing starts (the lengths of the files are needed to play), and stores them in the book directory as `download` does. It is `download` of just those files: `getContentResources` on content that is already issued, every `localURI` of the list checked, other hosts only with `--trust-host`, `.part` files renamed when complete. It never issues the book (a book that is not issued gives the Service's `invalidParameter` fault as it came, exit 1), and it fetches audio only: the SMIL, `ncc.html` and package files must already be on disk. A file the Service does not list is refused (exit 2). Progress goes to stderr, a failed fetch ends the command with exit 1 and nothing is played.
- `play` has text output only. Tests never open an audio device: they use a fake Player and miniaudio's `Backend.NULL`.

### The terminal interface

`dod tui` is an interactive terminal for browsing the shelf, seeing the metadata of a book, downloading its files and playing them. It needs the optional Textual (MIT): `pip install 'dod-client[tui]'`; without it the command exits with 2 and says so. Playing needs the optional `miniaudio` as `dod play` does (`pip install 'dod-client[play]'`); without it, or where it has no wheels, everything else works and the player bar says what is missing. It is a thin layer over the operations `dod list`, `dod metadata`, `dod resources` and `dod download` use, called through the same Session manager (ADR 0005), in thread workers so the screen never waits for the Service (ADR 0004).

- The shelf screen shows `issued` and pages 25 items at a time: `Enter` opens the metadata of the selected book, `l` chooses another list by id (`new`, `expired`, a `contentListRef`), `n` and `p` page, `r` reloads, `q` quits. On the metadata screen `Escape` goes back.
- `f` on a book opens its file screen: the files of `getContentResources` with their sizes and a state column. `d` downloads every file, one after the other, with the `download` use case: every `localURI` is checked first, other hosts need `--trust-host`, a file is written as `.part` and renamed when its size is the announced one. The state column shows `N of M bytes` while a file is fetched, then `downloaded`, `failed` (the reason is on the status line, as `dod download` says it) or `cancelled`; `c` cancels and leaves no partial file, and `Escape` cancels too. Files go to the directory `dod download` uses (an Environment and `DOD_DATA_DIR` are needed; the screen says so otherwise). The TUI never issues a book (a book that is not issued shows the Service's `invalidParameter` Fault) and never overwrites a file: use `dod download --force`. File names from the Service are untrusted text.
- A Fault, a Deviation, a failed logon or no answer is shown on the screen as the Service answered; the TUI uses the stored Session, so run `dod logon` first (or keep a password in the Environment). Ids, labels and metadata are untrusted text: control characters are replaced and no markup in them is interpreted.
- The TUI is always masked (ADR 0007): `--unmask` and `--unmask-password` are refused with exit 2. So are `--password-stdin` (the keyboard is stdin), `--debug` and `--save-exchanges` (stderr belongs to the screen), `--no-session` and `--format`.
- The player bar is on every screen and drives the same `Playback` over the same `Player` seam as `dod play`, so no audio logic lives in the TUI. `P` plays the selected book (or the one on the metadata and file screens) from the files on disk: nothing is streamed and nothing is fetched, so a book that is not downloaded (all audio files) is refused with a line saying to download first (`f`, then `d`). `Space` pauses and resumes, `x` stops, `]` and `[` go to the next and previous Clip, `.` and `,` move 30 seconds forward and back. The bar shows the state, the file's place in the book (`file 3 of 7`) and the elapsed and total Playlist time, and playing goes on while you browse. The player is opened on the first `P`; if it cannot be (no `miniaudio`), the bar says so.
- `L` opens the log panel: the Exchanges (method, address, status, time, headers and the first 2000 characters of each body) and the Observations of this run, oldest first, the last 500 kept. It is always masked (ADR 0007): what it holds was masked on the way in, there is no way to unmask in the TUI, and control characters from the network are replaced. `Escape` closes it. The TUI runs no Conformance tests.
- Tests drive it headless with Textual's `Pilot` against the in-memory Service and a fake Player; no terminal or audio device is needed.

### Conformance tests

`dod test run` runs Conformance tests against a Service and reports one Outcome per test; `dod test list` shows the stable, hierarchical test ids (`session.logon.wrong-password`). The families are `session`, `attributes`, `catalog` and `content` (State-changing, see below), and `negative` (explicit, see below).

- Outcomes: **PASS** (the Service answered as the specification requires), **FAIL** (it answered contrary to it), **SKIP** (the test does not apply or was not opted into) and **ERROR** (the test could not be evaluated, for example no answer or not SOAP). A fault is classified on its DODP element in `detail`, never on the HTTP status or `faultstring`; HTTP 500 without a DODP element is a FAIL. An optional operation is SKIP when it is not in `supportedOptionalOperations` and answers `operationNotSupported`, FAIL when it is declared but answers `operationNotSupported`, and PASS with a note when it works without being declared.
- The run logs on with a Session of its own (never a stored one, ADR 0005) and ends it afterwards. A setup that cannot log on is an ERROR that ends the run at once; the tests of logging on, such as a wrong password, are separate PASS/FAIL tests.
- `--only <prefix>` and `--skip <prefix>` (repeatable) choose tests by id prefix on whole dotted segments. State-changing tests are SKIP unless `--state-changing` is given, and against an Environment with `protected = true` that also needs `--confirm-env <name>`.
- The text report is one line per test, a summary and an `Observations` section; a FAIL names the section of the specification with a link to the published HTML version (clickable on a terminal that supports it). `--format json` is a versioned report (`schema_version`, now 4) with a `quirks` list, Exchange ids and the masked Exchanges of FAIL and ERROR tests; `--report-exchanges all|failures|none` changes which are included.
- The negative tests (`negative.*`) send deliberately invalid requests through a `RawChannel`: no Session (`noActiveSession`), an operation before the Initialisation sequence is complete (`invalidOperation`), an unknown operation, and invalid parameters (`invalidParameter`). Each works in an Ephemeral-mode Session of its own, so a stored Session is never touched. They are explicit: an ordinary run leaves them out and `dod test run --only negative` runs them (`dod test list` shows them). A `logOff` that fails afterwards is an ERROR on a record of its own, `<test id>.cleanup`, and the test keeps its PASS or FAIL.
- The content tests (`content.*`) borrow content, so they are State-changing and opt-in twice: `--state-changing` and an explicit `--content-id <id>` (never chosen automatically; without it they are SKIP, and so is the whole family without `--state-changing`). They check that `issueContent` answers `true`, that `getContentResources` gives a valid list (schema, sizes and the `localURI` rules of ADR 0008), that the first resource can be fetched with a `Content-Length` equal to its size, and that a Range request is answered `206` with a matching `Content-Range`. At most 64 KiB of a resource is read. A Service that ignores Range gets an `interoperability` Observation, not a FAIL; content that cannot be issued is an ERROR. `--unissued-content-id <id>` names content that is not issued, for the test that `getContentResources` on it is `invalidParameter` (SKIP without it). Content that was already issued before the run is left issued; otherwise each test returns what it issued, and a `returnContent` that fails is an ERROR on the `<test id>.cleanup` record. A resource on another host than the Service is SKIP unless `--trust-host` is given.
- The optional operations have tests that follow `supportedOptionalOperations` as described above: `bookmarks.get.known` (a schema-valid set for `--content-id`, else the first book of `issued` or `new`), `bookmarks.get.unknown-id` and `key-exchange.unknown-key` (`invalidParameter` for a key the Service does not have; no key name of the Service is ever sent) and `questions.default` (a schema-valid root menu for the reserved `default`). `bookmarks.set.round-trip` is State-changing and needs `--content-id`: it reads the set, writes it back as it is and reads it again, and FAILs if title, uid, lastmark or the number of bookmarks and highlights changed or `setBookmarks` answered `false`.
- Exit code 0 without FAIL or ERROR, 1 with FAIL and no ERROR, 2 with any ERROR. There are no requirement levels and no `--strict`.

#### Quirks for a Service's known deviations

Where an answer cannot be read at all (such as an HTTP 500 with no DODP fault element where the specification requires a fault), a **Quirk** is a named, generic workaround in the HTTP adapter (ADR 0010). Quirks are off by default and are switched on per Environment with `quirks = ["<name>"]`; names are validated strictly every time the file is loaded (`dod config check` too). Each use adds an `interoperability` Observation, so a deviation is never hidden.

- `dod quirks list` shows every known Quirk with its description, Spec reference and the Environments that enable it; `--env <name>` shows only those enabled for that Environment; `--format json` gives the same as JSON. Nothing is sent to a Service.
- Conformance runs ignore Quirks, so a tolerated deviation stays a FAIL. `dod test run --with-quirks` applies the Environment's Quirks; the text report then has a `Quirks on:` line and the JSON report a `quirks` list (empty without the flag).
- Known Quirk: `http-500-without-fault-as-invalid-operation` reads an HTTP 500 whose SOAP fault has no DODP fault element as `invalidOperation` for operations that need the initialisation sequence.

#### Baseline for a Service's known deviations

A Service that deviates from DODP v1 can still be checked in CI. Keep a **Baseline** in the Service's own repository (never in this one): a TOML file with one `[[known]]` table per test id that is known to FAIL, and a short reason. It holds no addresses or credentials.

```toml
[[known]]
id = "catalog.list.invalid-range"
reason = "DODP 5.3 Faults: answers HTTP 500 without a fault element"
```

- `dod test run --baseline baseline.toml` compares the run with the file. A FAIL that is not in it is **new** (`NEW <id>`, exit code 1). An entry that now passes is **resolved** (`RESOLVED <id>`); that exits 1 only with `--fail-on-resolved`. An ERROR always exits 2 (ADR 0010). An entry whose test did not run (`--only`, SKIP) or ended in ERROR is neither new nor resolved; an entry that names no known test id gives a warning on stderr.
- `dod test run --write-baseline baseline.toml` writes a Baseline from the run's FAILs: the test id and a short reason (the section of the specification the FAIL cites, or the reason an `--baseline` file already gave). Edit the reasons freely and review the file before committing it. Nothing is written when the setup failed.
- Outcomes do not change: a baselined FAIL is still FAIL in the text and JSON report, and only the exit code takes the Baseline into account. The JSON report (`schema_version` 4) has a `baseline` section, `null` without `--baseline`, with the sorted lists `new`, `resolved` and `known`; `exit_code` is the one the run ends with.

A CI step (GitHub Actions) that fails on new deviations and on a stale Baseline:

```yaml
- name: DODP conformance
  run: |
    dod test run --env ci --password-stdin \
      --baseline conformance/baseline.toml --fail-on-resolved \
      --format json --report-exchanges failures > conformance-report.json <<< "$DOD_PASSWORD"
  env:
    DOD_PASSWORD: ${{ secrets.DOD_PASSWORD }}
- uses: actions/upload-artifact@v4
  if: always()
  with:
    name: conformance-report
    path: conformance-report.json
```

Start with `dod test run --write-baseline conformance/baseline.toml`, review it, and commit it. Fix the deviations over time and delete resolved entries; `--fail-on-resolved` reminds you to.

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
# insecure = false, trust_host = false, protected = false
# quirks = []             # names from `dod quirks list`, see Quirks below
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
- Masking is always on for stderr, files and reports (ADR 0007): the `logOn` password, key material in a key exchange object (`UAK` and `CipherValue`; `--unmask` shows it on a terminal like the other secrets, but `dod key-exchange` never prints it to stdout unmasked), the values of `Cookie`, `Set-Cookie`, `Authorization` and `Proxy-Authorization`, URL userinfo and credential-like query parameters become `***[ab12cd]`, a short fingerprint that is the same for the same value, so you can see that two Exchanges shared a Session. Fingerprints of passwords and userinfo are salted per run.
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

Before a release the owner of the test backend runs the [acceptance test plan](docs/acceptance/tibi-acceptance-plan.md) by hand against a real Service: every command, the test families, the State-changing steps with their restore, Quirks and Baselines, the TUI, and a section for findings. It uses placeholders only.

### Releasing

Add the changes to [CHANGELOG.md](CHANGELOG.md) (move `Unreleased` under the new version), then push a final version tag on the commit to release:

```sh
git tag -s vX.Y.Z && git push origin vX.Y.Z
```

[.github/workflows/release.yml](.github/workflows/release.yml) runs only on such a tag. It builds the wheel and sdist, checks that their version equals the tag, smoke-tests `pipx install` of both, and creates the GitHub release with the files and `SHA256SUMS`. Running the workflow by hand (`workflow_dispatch`) does the build and checks only and uploads the files as a workflow artifact; it creates no release. Publishing to PyPI is deferred (issue 17).

### Adding a Quirk

A Quirk may be added by an agent working unattended only when all of this holds (ADR 0010); record each point in the issue that led to it:

1. The deviation was reproduced at least twice against the Service, and its Exchange saved masked (`--save-exchanges`).
2. It was checked a second time against the local specification copy in `docs/spec/` and shown not to be a defect in `dod` (namespace, parameter order, soapAction, element order). Where tolerant reading already copes, it is not a Quirk.
3. It is reproduced as fault injection in the fake Service, with a test in `tests/port/test_quirks.py` that shows the answer without the Quirk and with it, and the `interoperability` Observation.
4. It has a Spec reference from `SPEC_REFS`, a name that describes the behaviour (never a backend), a description, and is off by default.

Then add it to `QUIRKS` in `src/dod/domain/v1/_quirks.py` and implement it in `HttpServicePort`. A test checks that every registered Quirk is accepted by the adapter.

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
