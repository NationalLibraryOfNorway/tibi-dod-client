# Acceptance test plan against Tibi

An end-to-end check of `dod` against a real DODP v1 Service, run by hand by the owner of the test backend after all implementation layers are in. It covers every command, every Conformance test family, the State-changing steps (each opt-in, each with a way back), Quirks and Baselines, the TUI and the three test books. It answers the question "does `dod` do what the [specification](https://github.com/NationalLibraryOfNorway/tibi-dod-client/issues/18) says, against a real Service?" and collects what the fake Service could not tell us.

This repository is public. The plan uses placeholders and contains no address, user name, password or patron data. Keep it that way in everything you record (see "Recording a finding").

| Placeholder | Stands for |
| --- | --- |
| `<service>` | The full `https` address of the Service's SOAP endpoint. |
| `<service-host>` | The address of the Service's web root, for `dod discover`. |
| `<wsdl>` | The address of the Service's WSDL, if it publishes one. |
| `<env>` | The name of the Environment you create for the Service under test. |
| `<testuser>` | Your personal test user. Never a real patron. |
| `<id>`, `<localURI>`, `<ref>`, `<questionID>`, `<choiceID>` | Values you copy from earlier output. |

Written against the commands of `dod --help` after layer #45 (`dod` 0.x, report `schema_version` 4). Terms follow [GLOSSARY.md](../../GLOSSARY.md); decisions are in [docs/adr/](../adr/). Story numbers (S1 to S124) are the user stories of the specification (issue #18).

## 1. How to use this plan

- Work through the parts in order; later parts use what earlier ones recorded. Every step has an id (A1, B3, ...), the command, what to expect according to the specification, what to record, and, for State-changing steps, how to restore.
- "Expect" is what the specification and the ADRs say should happen. If the Service answers otherwise, that is the finding, not a failure of the step: record it and go on. A step is only blocked when the next step needs its result.
- Exit codes are the ones of the README: 0 ok, 1 the Service answered with a Fault or contrary to the specification, 2 no usable answer or the command could not be run. Results are on stdout, diagnostics and Observations on stderr.
- Steps marked **STATE-CHANGING (opt-in)** change data on the Service (loan state, bookmarks, announcements). Do not run one unless you have decided to and have recorded the initial state in part C. Each has a **Restore** line; if restoring is impossible, the step says so.
- Steps marked **LOCAL** change only your machine (configuration, Session files, downloaded files). Their Restore line says how to undo them.
- Steps marked **OPTIONAL** can be skipped when the Service does not offer the feature; write "not offered" in the log.
- Use only `<testuser>` and the three test books. Do not run this plan with a real patron's account.

### The test books

| Id | Format | Used for |
| --- | --- | --- |
| 684942 | DAISY 2.02, audio and text | The main book: issue, resources, download, play (full SMIL), fetch-missing, return, bookmarks, content tests. |
| 628190 | DAISY 2.02, audio only | Play of a book that may have no SMIL (the audioOnly refusal, S88), a second download, `--keep-local`. |
| 373799 | EPUB, text only | Play refusal of an EPUB without media overlays (S88), the not-issued tests, EPUB delivery shape. |

If a book turns out to be different from this description (for example 628190 has SMIL files), say so in the log; the expectations below name both outcomes.

### Prerequisites

- `dod` installed with both extras: `pipx install './dod_client-X.Y.Z-py3-none-any.whl[tui,play]'` from a release, or, until a release exists, build it with `uv build` and install the wheel in `dist/` the same way (S1, S4, S5). Python 3.12 or later.
- `jq`, `diff`, `ls`, `file` and a terminal that supports the TUI. For the play steps, an audio device you can hear.
- Enough disk space for the three books (the audio of 684942 may be hundreds of megabytes) in the data directory below.
- A second shell, for the concurrency step.

### Working directory and shell variables

Keep everything of the run in one directory outside any clone of this repository, so no evidence or Session file can be committed by accident. Use separate state and data directories so the run never touches your daily `dod` use (S22).

```sh
export ACC=~/dod-acceptance-$(date +%F)          # outside the repository
mkdir -p "$ACC"/{state,data,evidence,private} && chmod 700 "$ACC" "$ACC/private"
export DOD_STATE_DIR="$ACC/state"                 # Session files (hold cookies)
export DOD_DATA_DIR="$ACC/data"                   # downloaded books
export DOD_CONFIG="$ACC/config.toml"              # the configuration file of the run
export DOD_ENV=<env>
EV="$ACC/evidence"
```

`$ACC/private` is for anything that holds a secret or patron-like data: Session backups, saved bookmark sets. It is deleted in part J. Everything else in `$EV` is masked by `dod`, but still contains the Service address and metadata, so scrub it before sharing (see "Recording a finding").

The Environment (S7, S15; ADR 0006). The password is in the file as plaintext, so the file must be `0600`. Type it with an editor; never on the command line.

```toml
default_environment = "<env>"

[environments.<env>]
url = "<service>"
username = "<testuser>"
password = "..."          # your own test user's password, from your own store
# protected = true        # switched on in step G5, and off again in step J1

[environments.<env>-nopw]   # same Service and user, no password: for "no credentials" cases
url = "<service>"
username = "<testuser>"
```

```sh
chmod 600 "$DOD_CONFIG"
```

The commands are written for bash (`PIPESTATUS`, `read -rs`, here-strings); in zsh use `pipestatus` and `read -rs 'p?password: '`.

### Recording a step

Append `; echo "exit=$?"` to a command, and keep what you see. A simple way to keep everything is to run the whole session in `script -q "$EV/transcript.txt"`; do not use `--unmask-password` under `script`. Per step write one line in your log (`$ACC/log.md`): the step id, the exit code, PASS/DEVIATES/BLOCKED, and the finding id if there is one.

## 2. Part A: installation, help and configuration (local, nothing is sent)

#### A1. Install and help. Stories 1, 2, 4, 5, 117

```sh
dod --help; echo "exit=$?"
dod <command> --help        # for logon, test run, play, bookmarks set, questions, download
```

- Expect: exit 0. Four panels (Session and setup, Browse and issue, Download and play, Testing and tools) and the global options panel. `play` and `tui` help name `pip install 'dod-client[play]'` and `[tui]` (check that `[play]` is shown, not swallowed). Command `dod`, package `dod-client` (`pipx list`).
- Record: version (`pipx list`), Python version, operating system.

#### A2. Configuration commands. Stories 8, 13, 20, 21

```sh
dod config path; dod config check; dod config show
```

- Expect: `path` prints `$DOD_CONFIG`; `check` validates `<env>` and `<env>-nopw` without network, exit 0; `show` gives the effective values with the source of each and `password = ***`.
- Record: any password visible anywhere (this would be a finding of the first order and a reason to rotate the password).

#### A3. Strict configuration. Stories 9, 12, 14, 16, 18, 23. LOCAL

```sh
dod --config "$ACC/does-not-exist.toml" config check; echo "exit=$?"      # explicit file missing
chmod 644 "$DOD_CONFIG"; dod config check; echo "exit=$?"; chmod 600 "$DOD_CONFIG"
printf '[environments.scratch]\nurl = "https://dod.example.org/service"\ntoken = "x"\n' > "$ACC/scratch.toml"
dod --config "$ACC/scratch.toml" config check; echo "exit=$?"
printf '[environments.scratch]\nurl = "https://dod.example.org/service"\nfrobnicate = 1\n' > "$ACC/scratch.toml"
dod --config "$ACC/scratch.toml" config check; echo "exit=$?"
dod status --env <env> --url https://dod.example.org/service; echo "exit=$?"
DOD_USERNAME=other dod config show | grep -i user
```

- Expect: missing explicit file: exit 2. A group- or other-readable file with a password: refused, exit 2, tells you to `chmod 600` (Linux and macOS; on Windows only a warning from `check`, S17). `token` and `frobnicate`: exit 2 naming file, key (`environments.scratch.token`) and reason. `--env` with `--url`: exit 2. `DOD_USERNAME` beats the file (S23).
- Restore: `chmod 600 "$DOD_CONFIG"` (already in the commands); `rm "$ACC/scratch.toml"`.
- Note: these are local checks and every address is the placeholder `dod.example.org`; nothing is sent.

#### A4. No project-local configuration. Story 10. LOCAL

```sh
mkdir "$ACC/cwd" && cd "$ACC/cwd"
printf '[environments.local-trap]\nurl = "https://dod.example.org/service"\n' > config.toml
cp config.toml dod.toml; dod config path; dod config show | grep -c local-trap; cd "$ACC"
```

- Expect: the path is still `$DOD_CONFIG` and `local-trap` is not shown (count 0).

#### A5. Quirks and status before any logon. Stories 36, 119

```sh
dod quirks list; dod quirks list --env <env>; dod quirks list --format json | jq .
dod status
```

- Expect: `http-500-without-fault-as-invalid-operation` with description and Spec reference, enabled in none. `status` shows `<env>`, the URL, `<testuser>` and Session `none`; nothing is sent.

## 3. Part B: address, Session and diagnostics

#### B1. Discover. Stories 27, 28, 29

```sh
dod discover <service-host>; echo "exit=$?"
dod discover https://dod.example.org; echo "exit=$?"
```

- Expect: every address tried is printed with the kind of answer (never the content); for the real host a WSDL is found or the next steps are given. Nothing stored, no credentials sent (check with `--debug` that no `Authorization` header or `logOn` body appears). For `dod.example.org`: exit 2 with next steps (this one cannot reach a Service).
- Record: which of `?wsdl`, `/service`, `/dodp`, `/daisy-online`, `/DaisyOnline` the Service answers on. Whether `<service>` is among them is Tibi-specific: if it is not, discovery will not find it and that is not a defect, but write it down.

#### B2. WSDL and host boundary. Stories 26, 31, 32, 34. OPTIONAL (when `<wsdl>` exists)

```sh
dod logon --no-session --wsdl <wsdl> --quiet; echo "exit=$?"
```

- Expect: exactly one SOAP 1.1 port bound to the DODP portType is accepted, and its `soap:address` is used. If that address has another host, port or scheme than `<wsdl>` (typical behind a proxy), the command is refused with exit 2 (host boundary); then try once with `--trust-host` and expect logon to work and a `host-boundary` Observation.
- Record: the host/port/scheme relation of the WSDL and the `soap:address` (as "same" or "different", not the values).

#### B3. Refusals before anything is sent. Stories 30, 33

```sh
dod logon --no-session --url http://dod.example.org/service; echo "exit=$?"
```

- Expect: exit 2: an `http` address is refused without `--insecure`; nothing is sent. (Do not run this against `<service>` over `http`; it would be refused the same way, but the point is that nothing leaves the machine.) A redirect across a host boundary is a fake-Service test; if the real Service redirects `<service>` somewhere (record if the logon notes it), the redirect must be refused and shown as ERROR.

#### B4. Ephemeral logon. Stories 19, 30, 38, 43, 50, 54, 61

```sh
dod logon --no-session; echo "exit=$?"
read -rs -p 'password: ' DOD_PW; echo                                 # typed, not echoed, not in history
dod logon --no-session --password-stdin <<<"$DOD_PW"                  # stdin password beats the file
unset DOD_PW
dod logon --no-session --format json | jq .; echo "exit=${PIPESTATUS[0]}"
DOD_NO_SESSION=1 dod logon; ls "$DOD_STATE_DIR/sessions" 2>&1
```

- Expect: exit 0. One line per step: `logOn`, `getServiceAttributes`, `setReadingSystemAttributes`, then announcements if the Service declares `SERVICE_ANNOUNCEMENTS` (S104), then `logOff`. JSON is valid even with Observations on stderr. Nothing stored (`$DOD_STATE_DIR/sessions` is empty or absent). `[<env>] <address>` on stderr unless `--quiet` (S35). The password never appears.
- Observations on stderr (once each): `cookie-hardening` is likely (a session cookie without `HttpOnly` or `Secure`, seen earlier on Tibi); `transport-security` only if the Service is `http`.
- Record: the Observations and the declared `supportedOptionalOperations` (next step).

#### B5. Wrong password. Stories 64, 68. Run once

```sh
dod logon --no-session --password-stdin <<<"not-the-password"; echo "exit=$?"
```

- Expect: exit 1, the sequence stops after `logOn` (`logOnResult` false per the specification), nothing stored. The Conformance test `session.logon.wrong-password` (step G2) does the same again; if the test user could be locked out by failed attempts, do not repeat either more than needed.
- Record: whether the Service answered `false` or a Fault.

#### B6. Stored Session. Stories 38, 39, 44

```sh
dod logon; echo "exit=$?"
ls -l "$DOD_STATE_DIR" "$DOD_STATE_DIR/sessions"
grep -ril password "$DOD_STATE_DIR"; echo "grep-exit=$?"
dod status; dod session status; dod session status --check; echo "exit=$?"
```

- Expect: logon exit 0, announcements (if any) shown and not marked read. Session file `0600` in a `0700` directory (Linux, macOS); `grep` finds nothing (exit 1): the file holds the cookie in clear text and never the password (ADR 0001). `status` and `session status` say `stored`; `--check` exits 0.
- Record: the file's permissions and whether anything password-like is in it.

#### B7. Diagnostics and masking. Stories 49, 51, 55 to 58

```sh
dod attributes service --debug 2> "$EV/B7.debug.txt"
dod attributes service --save-exchanges "$EV/B7-saved" > /dev/null
ls "$EV/B7-saved"; cat "$EV"/B7-saved/001-*.json | jq .
grep -ci 'cookie' "$EV/B7.debug.txt"; grep -E '\*\*\*\[[0-9a-f]{6}\]' "$EV/B7.debug.txt" | head -3
```

Open the Session file in `$DOD_STATE_DIR/sessions/`, copy the cookie value, and check that it appears nowhere in the evidence:

```sh
read -rs COOKIE; grep -rF -- "$COOKIE" "$EV"; echo "grep-exit=$?"; unset COOKIE      # expect exit 1
```

- Expect: `--debug` shows each Exchange as a block (method and URL, masked headers, pretty-printed SOAP, status, duration). `Cookie`/`Set-Cookie` values and the `logOn` password are `***[ab12cd]`; the same cookie has the same fingerprint in every Exchange of a Session. `--save-exchanges` writes `NNN-<operation>.request.xml`, `.response.xml` and `.json` per Exchange. The cookie value is nowhere in the evidence.
- Record: any unmasked secret (finding of the first order, rotate it).

#### B8. Unmasking is terminal-only. Stories 59, 60

```sh
dod --debug --unmask attributes service 2> "$EV/B8.err" > /dev/null; echo "exit=$?"       # stderr is a file
dod --debug --unmask --save-exchanges "$EV/B8-saved" attributes service; echo "exit=$?"
dod attributes service --unmask; echo "exit=$?"                                           # no --debug
DOD_UNMASK=1 dod --debug attributes service 2>&1 >/dev/null | head -3                     # no environment variable
```

- Expect: exit 2 for the first three (stderr not a terminal, with `--save-exchanges`, without `--debug`), refused before anything is sent. `DOD_UNMASK` has no effect. Optionally, in a terminal: `dod --debug --unmask attributes service` shows cookies unmasked between warnings and highlighted in colour. Do not use `--unmask-password` unless you need it, and never under `script`.

#### B9. Expired Session and relogin. Stories 40, 41. LOCAL (it logs the stored Session off at the Service)

```sh
f=$(ls "$DOD_STATE_DIR"/sessions/*.json); cp "$f" "$ACC/private/"          # backup of the live Session
dod logoff; echo "exit=$?"                                                 # ends it at the Service, deletes the file
cp "$ACC/private/$(basename "$f")" "$f"                                    # put the now stale Session back
dod session status --check; echo "exit=$?"                                 # expect 1, and no relogin
dod list --save-exchanges "$EV/B9-relogin" >/dev/null; echo "exit=$?"
ls "$EV/B9-relogin"
```

- Expect: `logoff` exit 0 ("logged off"), file removed. `--check` on the stale Session: exit 1 (expired), and it never logs on. The next ordinary command (`dod list`) gets `noActiveSession`, logs on exactly once with the Environment's password and repeats the call: exit 0, the saved Exchanges show `getContentList` (fault), `logOn`, `getServiceAttributes`, `setReadingSystemAttributes`, `getContentList` (ok).
- Then the case without credentials. Make a Session stale again, this time for the Environment without a password (Sessions are keyed by Service URL and user, so `<env>-nopw` finds the same file):

```sh
f=$(ls "$DOD_STATE_DIR"/sessions/*.json); cp "$f" "$ACC/private/"          # the live Session from the relogin above
dod logoff; cp "$ACC/private/$(basename "$f")" "$f"                        # stale again
dod list --env <env>-nopw; echo "exit=$?"
```

- Expect: exit 2 and a message that asks you to run `dod logon`; no second login attempt. Whether the Service signals the stale Session with a `noActiveSession` fault or something else is the real question: if it is something else (for instance an HTTP 500 without a DODP element), `dod` does not relogin; record exactly what the Service answered (`--debug`) as a Quirk candidate (part H).
- Restore: `dod logon` to get a live Session again.

#### B10. Concurrent processes. Story 42

Make the Session stale as in B9, then:

```sh
for i in 1 2 3 4; do dod list --quiet --save-exchanges "$EV/B10-$i" >/dev/null 2>"$EV/B10-$i.err" & done; wait
ls "$EV"/B10-*/*logOn.request.xml | wc -l                  # expect 1
ls "$DOD_STATE_DIR/sessions"
```

- Expect: all four finish with exit 0; exactly one `logOn` in total (one process logs on, the others use the Session it wrote); one valid Session file.
- Restore: `dod session status --check` is exit 0 afterwards.

#### B11. Logoff and clear. Story 44

```sh
dod logoff; echo "exit=$?"; dod logoff; echo "exit=$?"; ls "$DOD_STATE_DIR/sessions"
dod logon; dod session clear; echo "exit=$?"; dod session status --check; echo "exit=$?"
dod logon
```

- Expect: first `logoff` says "logged off"; the second "no stored Session" (exit 0). `session clear` deletes the file without any request (check with `--debug`: nothing sent); `status` and `session status --check` then say `session: none` (exit 0): with no stored Session there is nothing to check, and `--check` never logs on.
- Note: after `session clear` the Service still holds the Session until it times out. Record how long (see later calls) only if you notice it.
- Restore: the last `dod logon` leaves a live Session for the rest of the plan.

## 4. Part C: Service information and initial state

#### C1. Service attributes. Stories 47, 48, 49, 51, 53

```sh
dod attributes service | tee "$EV/C1.service.txt"
dod attributes service --format json | jq . > "$EV/C1.service.json"
dod attributes service --format xml > "$EV/C1.service.xml"
```

- Expect: what the Service says it supports; JSON is a document; xml is the raw, masked response (not a re-creation). Unknown elements do not break anything (S52).
- Record: `supportedOptionalOperations`. It decides what to expect in G6 and for the optional commands. Write it down as the list `OPS` (for example: `SERVICE_ANNOUNCEMENTS`, `DYNAMIC_MENUS`, `GET_BOOKMARKS`, `SET_BOOKMARKS`, `PDTB2_KEY_PROVISION`, ...). Note stderr schema violations.

#### C2. Reading System declaration. Stories 106, 107

```sh
dod attributes reading-system --save-exchanges "$EV/C2-default"; echo "exit=$?"
```

- Expect: exit 0; the request in `$EV/C2-default` declares DAISY 2.02 and EPUB 3, `audio/mpeg` and `audio/wav`, and the input types `TEXT_NUMERIC` and `TEXT_ALPHANUMERIC`, plus the producer and version of the installed package.
- With a file: take the `readingSystemAttributes` element out of the saved request into `$ACC/rs.xml` (the element only, not the SOAP envelope) and send it back with one change:

```sh
dod attributes reading-system --file "$ACC/rs.xml"; echo "exit=$?"        # valid: exit 0
# remove a required child element from rs.xml, then:
dod attributes reading-system --file "$ACC/rs.xml"; echo "exit=$?"        # expect 2, nothing sent
dod attributes reading-system --file "$ACC/missing.xml"; echo "exit=$?"   # expect 2, nothing sent
```

- Expect: an invalid or missing file is refused locally with exit 2 before anything is sent (confirm with `--debug`). The declaration only affects the current Session at the Service, so nothing needs restoring; a later `dod logon` declares the default again.

#### C3. Announcements. Stories 104, 105

```sh
dod announcements list; echo "exit=$?"
```

- Expect: the unread announcements, or none. Nothing is marked as read by listing (run it twice; the output is the same).
- **STATE-CHANGING (opt-in), only if you have announcements you do not mind marking as read:**

```sh
dod announcements mark-read <id>; echo "exit=$?"
dod announcements list
dod announcements mark-read --all; echo "exit=$?"
```

- Expect: `mark-read` first fetches (the specification only accepts identifiers from a fetch in the same Session), then marks; the marked ones are gone from `list`. If the Service answers `invalidParameter` for a set, `dod` tries one at a time; `false` is reported as "already read".
- Restore: **not possible.** There is no operation to mark an announcement unread. Skip this step if the announcements matter; write "no announcements" or "skipped" in the log.
- Record: how the Service handled the fallback (one at a time) and the `false` case, if you hit them.

#### C4. Capture the initial state (before any State-changing step)

This is the baseline for every Restore line. Run it once, now, with a live Session:

```sh
dod list --format json > "$EV/S0.shelf.json"
dod list --id new  --format json > "$EV/S0.new.json"
dod list --id expired --format json > "$EV/S0.expired.json"
for b in 684942 628190 373799; do
  dod metadata $b --format json > "$EV/S0.metadata-$b.json"
  dod bookmarks get $b > "$ACC/private/S0.bookmarks-$b.xml"      # private: your test user's data
done
dod announcements list > "$EV/S0.announcements.txt"
```

- Record in the log table (this is the "initial state"):

| Item | Initial value |
| --- | --- |
| 684942 on the shelf (issued)? | yes / no |
| 628190 on the shelf (issued)? | yes / no |
| 373799 on the shelf (issued)? | yes / no |
| Number of items on the shelf, new, expired | n / n / n |
| `requiresReturn` of each book (from the metadata) | true / false per book |
| Bookmark set of each book | empty / has lastmark / has N bookmarks (the files are in `$ACC/private`) |
| Unread announcements | n |

- Plan around it: the return and content tests in parts E and G are only a clean round trip for a book that was **not** on the shelf at the start. For a book that was already issued, skip the `return` steps for that book (returning and re-issuing would change its loan date), and say so in the log. For the not-issued steps you need 373799 not to be issued; if it is, return it first (F9) or use another book you know is not issued and write its role down.
- Where the bookmark files are empty or `getBookmarks` is refused for a book, say so; the restore in F3 then means "write back an empty-ish set", which the Service may not accept. Record how it behaves.

## 5. Part D: shelf, catalogue and metadata (read-only)

#### D1. The shelf. Stories 48, 49, 50, 108

```sh
dod list; dod list --format json | jq '.list.items | length'; dod list --format xml | head -20
dod list --format json > "$EV/D1.json" && jq empty "$EV/D1.json" && echo valid
```

- Expect: the issued books (matches `S0.shelf.json`), JSON `result` plus `list`, valid JSON even though Observations go to stderr; xml is the raw masked response.
- Record: schema violations on stderr, for instance identifiers that are not `xs:NMTOKEN` (reported as schema violations, not failures, S52).

#### D2. Other lists and ranges. Stories 108, 115

```sh
dod list --id new; dod list --id expired
dod list --id new --first 0 --last 1
dod list --id new --first 5 --last 2; echo "exit=$?"
dod list --id no-such-list; echo "exit=$?"
```

- Expect: `new` and `expired` are lists; the segment gives items 0 and 1 with the total; an invalid range gives an empty list and the total (exit 0); an unknown list is a Fault `invalidParameter`, exit 1, shown as it came.
- Record: what each answers if different, and exact Fault element (this is `catalog.list.invalid-range` and `catalog.list.unknown-id` in part G).

#### D3. Metadata of the test books. Stories 109, 49

```sh
for b in 684942 628190 373799; do dod metadata $b; dod metadata $b --format json | jq .; done
dod metadata 000000; echo "exit=$?"
```

- Expect: metadata for each book whether issued or not (S109): title, format, `requiresReturn`, and so on. An unknown id: Fault `invalidParameter`, exit 1.
- Record: `requiresReturn` per book (needed for E8), and the media kinds (audio, text) each book claims. Compare them with the table of test books.

## 6. Part E: menus (read-only)

Menus are read-only; every call is one step and `dod` keeps no position. The Service decides what comes next. Skip the part if `DYNAMIC_MENUS` is not in `OPS` and the root call fails (record that).

#### E0. Root menu and following a choice. Stories 114, 115

```sh
dod questions; echo "exit=$?"
dod questions --format json | jq .
```

- Expect: the root question; every choice printed as the arguments of the next command, with the label as a comment, for example `answer main 'two words'    # Old books`. Ids and values with spaces are quoted.
- Copy a line of that output and run it, then go deeper until the menu ends:

```sh
dod questions answer <questionID> <choiceID>
```

- Expect: the reply of the Service, one step. An endpoint is either `contentListRef: <ref>`, which you follow with `dod list --id '<ref>'` (quote it), or `label: <text>`, a message.
- Record: the shape of the menu (ids only, as a tree in the log), the endpoint you reached, and whether a `contentListRef` list opens (S115). Do the same for at least two different paths.

#### E1. Ids with spaces. Story 114 (known deviation of Tibi, ADR 0010)

Some choice ids of the Service contain spaces, against `xs:NMTOKEN`. Find one in E0 (`answer ... 'two words'`) and run it exactly as printed, with `--debug`:

```sh
dod --debug questions answer <questionID> '<choice id with spaces>' 2> "$EV/E1.debug.txt"; echo "exit=$?"
grep -n 'choice id with spaces' "$EV/E1.debug.txt" | head -3
```

- Expect: the id is sent as given (in the request body, not mangled, split or percent-encoded); the Service answers with the next step; a schema-violation note about `NMTOKEN` may appear on stderr; exit 0. This is tolerant reading and **not** a Quirk (ADR 0010).
- Record: the id (without anything that identifies the Service) and the answer.

#### E2. Search. Story 114

```sh
dod questions search; echo "exit=$?"
dod questions search <a word that occurs in a title>; echo "exit=$?"
```

- Expect: `search` without text sends only the reserved `search` and the Service shows its search question or a result; with text, the text is the value and the Service answers with a result (a `contentListRef` or an input question). Record what comes back; follow a `contentListRef` with `dod list --id`.

#### E3. `back`. Story 114 (known deviation of Tibi)

```sh
dod --debug questions back 2> "$EV/E3.debug-1.txt"; echo "exit=$?"
dod --debug questions back 2> "$EV/E3.debug-2.txt"; echo "exit=$?"
```

- Expect per specification: `back` is a reserved answer; the Service's reply is shown unchanged. It is a thin probe and `dod` keeps no position (the Tibi Service is stateless for menu position, so `back` after `answer` has nothing to go back to). Seen earlier on Tibi: HTTP 500 instead of an `invalidParameter` Fault. If so, `dod` shows a Deviation (exit 1) with the Service's answer as it came and does not relogin.
- Record: the exact answer both times (it must be reproduced twice for ADR 0010), whether the HTTP 500 has a DODP fault element, and the saved masked Exchange. This is a candidate for a Baseline-style note rather than a Quirk: no Quirk covers `back` (the existing one covers only operations that need the initialisation sequence), and no Conformance test sends `back`. Decide in part H.

#### E4. Input questions. Story 114. OPTIONAL

If any menu shows an input question that accepts only `AUDIO` (or another input type `dod` does not declare), check:

```sh
dod questions --format json | jq '.questions.questions[] | select(.answerable == false)'
```

- Expect: the question is shown, marked as one `dod` cannot answer (`answerable: false`).

## 7. Part F: content delivery

Preconditions: the initial state of C4 is written down. The steps in this part change what is issued. They are marked individually.

#### F1. Reading a book that is not issued. Stories 78, 86

Run this while 373799 is not issued (C4).

```sh
dod resources 373799; echo "exit=$?"
dod download 373799; echo "exit=$?"
ls "$DOD_DATA_DIR" 2>&1
```

- Expect: the Service's `invalidParameter` Fault from `getContentResources`, shown as it came, exit 1; `download` does **not** issue the book and writes nothing. `dod list` still does not show it.
- Record: the answer, in particular whether it is a DODP `invalidParameter` Fault or something else.

#### F2. Issue. Stories 77, 108. **STATE-CHANGING (opt-in)**

```sh
dod issue 684942; echo "exit=$?"
dod list | grep 684942
dod issue 684942; echo "exit=$?"            # the second time
```

- Expect: `issueContent: ok`, exit 0; the book is on the shelf. The second issue of an issued book: record the answer (true or a Fault) without judging; the specification leaves loan semantics to the Service.
- Restore: `dod return 684942` (step F9), or leave it issued if it was issued at the start (C4).

#### F3. Resources. Stories 83, 111. (Needs the book issued)

```sh
dod resources 684942 | tee "$EV/F3.resources.txt"
dod resources 684942 --format json | jq '.resources.resources | length'
```

- Expect: the file list as the Service gave it: address, `localURI`, size, MIME type; nothing downloaded; userinfo in an address is masked.
- Record: the number of files, whether the addresses are relative or absolute, whether they point at the Service's host or another one (Service Delegate), `http` or `https`, the MIME types (audio/mpeg? audio/x-m4a?), and any `localURI` that looks unusual (leading slash, `..`, backslash). Say "same host / other host", not the host.

#### F4. Download. Stories 79 to 84, 112. **LOCAL**

```sh
dod download 684942 --save-exchanges "$EV/F4-saved"; echo "exit=$?"
ls -lR "$DOD_DATA_DIR" | head -60; find "$DOD_DATA_DIR" -name '*.part'
dod download 684942; echo "exit=$?"                                   # again, files exist
dod download 684942 --force; echo "exit=$?"
dod download 684942 --force --file <localURI>; echo "exit=$?"         # only one file
dod download 684942 --output "$ACC/out-684942"; echo "exit=$?"
```

- Expect: the files go to `$DOD_DATA_DIR/<env>/books/684942/` in the layout of the `localURI`s; no `.part` file remains; sizes on disk equal the sizes of F3 (`ls -l` against the `size` values). A second download without `--force` refuses the existing files and fetches nothing. `--force` overwrites. `--file` fetches only the named file (it may be repeated). `--output` puts the files in the directory instead. Every `localURI` is checked before the first byte; no zip is made.
- If a resource address is on another host than `<service>`: refused with a `host-boundary` Observation unless `--trust-host`. Run it once without and once with `--trust-host`, and check with `--debug` that the second request to that host carries **no** `Cookie` header and no password (S82, S32). If the address is `http`, it is refused without `--insecure`.
- A non-2xx status for a resource must be a Deviation and never trigger a relogin (S84): if you see one, record the status and the `--debug` block.
- Record: download time and whether a large file succeeded in one go (there is no resume, ADR 0008); any partial or mismatched size (the file is then discarded, so check that nothing is left).
- Restore: `rm -r "$DOD_DATA_DIR/<env>/books/684942" "$ACC/out-684942"` (or keep them for the play steps and delete in part J).

#### F5. Download the other two books. **STATE-CHANGING (opt-in)** (issues them) and **LOCAL**

```sh
dod issue 628190; dod resources 628190; dod download 628190
dod issue 373799; dod resources 373799; dod download 373799
find "$DOD_DATA_DIR/<env>/books/628190" "$DOD_DATA_DIR/<env>/books/373799" -type f | head -50
file "$DOD_DATA_DIR"/<env>/books/*/* | head -40
```

- Expect: as F4. Record the file layout of each book (names of the structure files, not the content):
  - 684942: `ncc.html`, SMIL files, `master.smil`?, audio files, text files.
  - 628190: with or without `ncc.html` and SMIL; audio format (`file` shows MP3, WAV or other).
  - 373799: a directory with `META-INF/container.xml` and an OPF, or **a single `.epub` archive**. `dod` does not unpack archives: if the Service delivers one `.epub` file, `dod play` will not find the book structure (see F8). This is exactly the kind of thing only a real book shows; write it down.
- Do **not** run F1 again after issuing 373799; the not-issued test for it is `--unissued-content-id` in G7 and needs the book not issued then. Return it (F9) before G7, or pick another book you know is not issued.
- Restore: see F9.

#### F6. Play DAISY 2.02 audio and text. Stories 87, 89 to 91. Needs the audio device

```sh
dod play 684942
```

At the prompt, type each command and press Enter: an empty line (status), `p`, `p`, `n`, `n`, `b`, `f`, `r`, `q`.

- Expect: the audio plays in the order of the book's own SMIL (`master.smil`, or the SMIL files `ncc.html` links to first, each once), not file-name order and not the `resources` order. The status line shows the audio file's path in the book, `file k of n` and elapsed/total Playlist time. `p` pauses and resumes; `n`, `b` go to the next and previous Clip; `f` and `r` jump 30 seconds; `q` stops. Headings and text are ignored.
- Check the order by hand: open `ncc.html` (or `master.smil`) and compare the first three and last two Clips with what plays. The position runs slightly ahead of what you hear (frames handed to the device, ADR 0009).
- Record: whether the audio plays at all; the audio format (a format `miniaudio` cannot decode, such as AAC, gives an error and an `audio-format` Observation: record the format, S91); clicks or gaps at pause, resume and jumps; whether `file k of n` matches the distinct audio files; the total time against the real length.
- Also: `dod play 684942 --directory "$ACC/out-684942"` (if still there) plays the same; `printf 'n\nn\nq\n' | dod play 684942` applies the lines in order.

#### F7. Play audio only. Stories 87, 88

```sh
dod play 628190; echo "exit=$?"
```

- Expect, depending on the files recorded in F5:
  - Without `master.smil` and `ncc.html`: refused with an explanation, exit 2, nothing plays, no fallback to file-name order (S88).
  - With them: it plays in SMIL order as F6.
- Record: which of the two applies. If the book has SMIL but is called "audio only", or lacks it while the Service describes it as DAISY 2.02 audio, record how the book is shaped.

#### F8. Play EPUB text only. Stories 87, 88

```sh
dod play 373799; echo "exit=$?"
```

- Expect: for an extracted EPUB 3 with no media overlay on any spine item: refused with a message naming the missing media overlay, exit 2, the player is never started, never played in silence. If the book has overlays: it plays in spine order, each overlay once. If the download was a single `.epub` archive: `dod` cannot find a structure to play ("no order to play"), exit 2; record this as a finding about EPUB delivery (it is not an unpacking feature in `dod`, ADR 0009).
- Record: which of the three applies.

#### F9. Return. Stories 77, 110. **STATE-CHANGING (opt-in)** and deletes local files

Only for books that were **not** issued at the start (C4). For each:

```sh
cp -r "$DOD_DATA_DIR/<env>/books/684942" "$ACC/private/684942-copy"     # optional, for F10
dod return 684942                      # answer "n" at the prompt
ls "$DOD_DATA_DIR/<env>/books/684942" | head -3; dod list | grep 684942
dod --debug return 684942 2> "$EV/F9.debug.txt"                # answer "y"
grep -c returnContent "$EV/F9.debug.txt"
ls "$DOD_DATA_DIR/<env>/books/684942" 2>&1; dod list | grep -c 684942
dod return 684942; echo "exit=$?"      # again: no local copy, no prompt
```

- Expect: declining deletes nothing and sends no `returnContent` (exit 2 or 1 per the command's message; record it). Accepting deletes only `$DOD_DATA_DIR/<env>/books/684942/` first, then calls `returnContent`, which answers `true`; the book leaves the shelf. Returning again: no local copy so no prompt, and `true` again (also for a book never borrowed: record that too, with 373799 if it was never issued). A result of `false` is a Spec deviation, exit 1.
- `requiresReturn`: for a book whose metadata says `requiresReturn` is `false` (D3), `dod return <id>` is refused with exit 2 and nothing is deleted; `--force` calls it anyway. Run the refusal on such a book if you have one.
- `--keep-local`: `dod issue 628190 && dod return 628190 --keep-local` returns without deleting and warns that this breaks the specification; the local files remain.
- `--yes` skips the prompt: use it on the third book.
- Restore: the Service is back to the initial state when the book is on the shelf as in C4: compare `dod list --format json | jq -S . | diff - <(jq -S . "$EV/S0.shelf.json")`. For a book that was issued at the start and that you returned, `dod issue <id>` puts it back (the loan date changes; record it). Delete the local copies you no longer need.

#### F10. `play --fetch-missing`. Stories 89, 78. **STATE-CHANGING (opt-in)** (issues) and **LOCAL**

```sh
dod issue 684942 && dod download 684942
rm "$DOD_DATA_DIR/<env>/books/684942/<one audio file>"
dod play 684942; echo "exit=$?"                       # without the flag
dod play 684942 --fetch-missing --save-exchanges "$EV/F10"; echo "exit=$?"
ls "$EV/F10"
```

- Expect: without the flag: refused (exit 2), no request, and the message names `--fetch-missing`. With the flag: only the deleted audio file is fetched (one `getContentResources` and one GET; never `issueContent`), then the book plays. With everything on disk and the flag: the Service is not contacted. Structure files (SMIL, `ncc.html`) are not fetched.
- Not issued: after F9, put the saved structure back into a directory and try `dod play 684942 --fetch-missing --directory "$ACC/private/684942-copy"` with an audio file removed: expect the Service's `invalidParameter` Fault, exit 1, nothing issued, nothing played.
- Restore: return the book (F9) if it was not issued at the start.

## 8. Part G: Conformance tests

The tests run with a Session of their own and never use a stored one (ADR 0005), so a stored Session is unaffected: `sha256sum "$DOD_STATE_DIR"/sessions/*.json` before and after must be identical. Exit codes: 0 without FAIL or ERROR, 1 with FAIL, 2 with any ERROR. Keep every report.

#### G1. List and select. Stories 63, 72

```sh
dod test list; dod test list --format json | jq '.tests | length'
dod test list --only negative
dod test run --only no-such-family; echo "exit=$?"
```

- Expect: stable hierarchical ids in the families `session`, `attributes`, `catalog`, `content` (State-changing), `negative` (explicit), `bookmarks`, `key-exchange`, `questions`: 28 ids at layer #45. An `--only` prefix that matches nothing is a usage error (exit 2); nothing is sent.

#### G2. The default run (read-only). Stories 63 to 68, 73, 74, 76

```sh
sha256sum "$DOD_STATE_DIR"/sessions/*.json > "$EV/G2.session-before.sha"
dod test run | tee "$EV/G2.txt"; echo "exit=${PIPESTATUS[0]}"
dod test run --format json --report-exchanges failures > "$EV/G2.report.json"; echo "exit=$?"
sha256sum -c "$EV/G2.session-before.sha"
jq '{schema_version, exit_code, quirks, baseline}' "$EV/G2.report.json"
```

- Expect per test (all against a Service that conforms to DODP v1; anything else is a finding):

| Test id | PASS means | Stories |
| --- | --- | --- |
| `session.logon.valid-credentials` | `logOn` answers true | 63, 68 |
| `session.logon.wrong-password` | a wrong password is `false` or a Fault, never a Session | 68 |
| `session.logoff.invalidates-session` | after `logOff` a call gets `noActiveSession` | 40, 65 |
| `session.call.without-session` | a call with no Session gets `noActiveSession` | 65 |
| `attributes.service.get` | schema-valid service attributes | 106 |
| `attributes.reading-system.set` | the declaration is accepted (`true`) | 106, 107 |
| `catalog.list.issued`, `catalog.list.segment` | a valid list, and a valid segment (SKIP if the shelf is empty) | 108 |
| `catalog.list.invalid-range` | an empty list and the total, or a DODP fault | 108 |
| `catalog.list.unknown-id` | `invalidParameter` | 65, 108 |
| `catalog.metadata.get`, `catalog.metadata.unknown-id` | valid metadata; `invalidParameter` | 109 |
| `bookmarks.get.known`, `bookmarks.get.unknown-id` | a valid set; `invalidParameter` (see G6) | 113 |
| `key-exchange.unknown-key` | `invalidParameter` for a key the Service does not have (see G6) | 116 |
| `questions.default` | a schema-valid root menu (see G6) | 114 |
| `content.*`, `bookmarks.set.round-trip`, `negative.*` | SKIP in this run (State-changing, or explicit) | 69, 71 |

- Also expect: a FAIL names a section of the specification with a link (S62); an HTTP 500 without a DODP fault element is a FAIL (S66), and a fault is classified by the element in `detail`, never by HTTP status or `faultstring` (S65); ERROR is for "could not be judged" (no answer, not SOAP), not for a Service that answered wrongly (S64); the text report ends with a summary and an `Observations` section separate from the Outcomes (S76); there is no requirement level and no `--strict` (S75). JSON: `schema_version` 4, `exit_code`, `quirks` `[]`, `baseline` `null`, masked Exchanges for FAIL and ERROR tests only.
- Record: every FAIL and ERROR with its id, the Service's answer in short (fault element, HTTP status) and the report file. Each FAIL is a finding: either a Service deviation (finding type D) or a defect in `dod` (type T). Decide using the local specification copy in `docs/spec/dodp-v1/` (namespace, parameter order, soapAction, element order) before you call it a Service deviation.
- Check also `--report-exchanges all` and `none` change what the JSON holds, and `grep -F` the password and the cookie value in the JSON (expect no hit).

#### G3. A single test. Story 72

```sh
dod test run --only session.logon --skip session.logon.wrong-password
dod test run --only catalog.metadata.get
```

- Expect: only those ids run (whole dotted segments); the others are not listed.

#### G4. Negative tests. Stories 46, 71

```sh
dod test run --only negative | tee "$EV/G4.txt"; echo "exit=${PIPESTATUS[0]}"
dod test run --only negative --format json --report-exchanges all > "$EV/G4.report.json"
```

- Expect: the six `negative.*` tests, each in an Ephemeral-mode Session of its own: no Session gives `noActiveSession`; an operation before the Initialisation sequence gives `invalidOperation`; an unknown operation gives a DODP fault or `operationNotSupported`; invalid parameters give `invalidParameter`. A failing `logOff` afterwards is an ERROR on `<id>.cleanup` and the test keeps its Outcome.
- Expect on Tibi (observed earlier, not yet confirmed twice): HTTP 500 with no DODP fault element where the specification requires a fault, a FAIL for the affected tests. That is the Quirk candidate of part H.
- Record: each FAIL and the HTTP answer; the saved masked Exchange (`$EV/G4.report.json`).
- Run it a second time (`$EV/G4b.report.json`): a deviation counts as reproduced only when it is the same twice.

#### G5. State-changing tests and the protection of an Environment. Stories 37, 69, 70, 85, 86. **STATE-CHANGING (opt-in)**

First check the opt-ins, in order. Add `protected = true` to `[environments.<env>]` in `$DOD_CONFIG` (LOCAL):

```sh
dod test run --state-changing; echo "exit=$?"                          # protected: needs --confirm-env
dod test run --confirm-env <env>; echo "exit=$?"                       # not state-changing: content stays SKIP
dod test run --state-changing --confirm-env <env> --only content; echo "exit=$?"   # no --content-id: SKIP
```

- Expect: the first is refused with exit 2 and nothing is sent; the second and third run but the content tests are SKIP and nothing is issued. Check with `dod list` that nothing changed.

Then the real run. Make sure 684942 is not issued (or accept that it stays issued, C4), and that 373799 is not issued:

```sh
dod test run --state-changing --confirm-env <env> --only content \
  --content-id 684942 --unissued-content-id 373799 --format json --report-exchanges all \
  > "$EV/G5.content.report.json"; echo "exit=$?"
dod test run --state-changing --confirm-env <env> --only content \
  --content-id 684942 --unissued-content-id 373799 | tee "$EV/G5.content.txt"
dod list --format json | jq -S . | diff - <(jq -S . "$EV/S0.shelf.json") && echo "shelf unchanged"
```

- Expect: `content.issue.returns-true` (`issueContent` true), `content.resources.list` (schema-valid list, safe `localURI`s), `content.resource.fetch` (the first resource arrives with `Content-Length` equal to its size; at most 64 KiB are read), `content.resource.range` (a Range request gets `206` with a matching `Content-Range`; a Service that ignores Range gives an `interoperability` Observation, not a FAIL, S85), `content.resources.not-issued` (`getContentResources` on 373799 is `invalidParameter`; SKIP if it is actually issued). Each test returns what it issued; a `returnContent` that fails is an ERROR on `<id>.cleanup`. A resource on another host is SKIP without `--trust-host`.
- Restore: the shelf diff above must say "shelf unchanged". If a book the run issued is still on the shelf (an ERROR on a cleanup, or the book was issued before), `dod return <id> --keep-local` brings it back, or follow F9.

#### G6. Optional operations and `supportedOptionalOperations`. Stories 53, 67, 113, 114, 116

Compare the `bookmarks.*`, `key-exchange.unknown-key` and `questions.default` results of G2 with `OPS` from C1:

| Declared in `OPS`? | The operation works? | Expected Outcome |
| --- | --- | --- |
| yes | yes | PASS |
| yes | no (`operationNotSupported`) | FAIL |
| no | no (`operationNotSupported`) | SKIP |
| no | yes | PASS with a note |

- Record any row that does not hold, as a finding (D: Service declares wrongly).

Then the bookmark round trip. **STATE-CHANGING (opt-in)**:

```sh
dod bookmarks get 684942 > "$EV/G6.before.xml"
dod test run --state-changing --confirm-env <env> --only bookmarks --content-id 684942 | tee "$EV/G6.txt"
dod bookmarks get 684942 > "$EV/G6.after.xml"; diff "$EV/G6.before.xml" "$EV/G6.after.xml" && echo same
```

- Expect: `bookmarks.set.round-trip` reads the set, writes it back as it is and reads it again: PASS when title, uid, lastmark and the counts of bookmarks and highlights are unchanged; FAIL if one changed or `setBookmarks` answered `false`.
- Restore: if the sets differ, write back the one from C4 (step H3, `dod bookmarks set 684942 --file "$ACC/private/S0.bookmarks-684942.xml"`). Remember that `setBookmarks` replaces the whole set.
- Remove `protected = true` again in J1 if you do not want it on.

#### G7. Exit codes. Story 74

From the runs above, confirm: 0 for a run with no FAIL or ERROR (for example `--only session.logon.valid-credentials`), 1 with a FAIL and no ERROR, 2 with any ERROR (for example `dod test run --url https://dod.example.org/service; echo $?`: no usable answer, the setup is an ERROR, exit 2, the run ends at once; the address is a placeholder that does not answer).

## 9. Part H: bookmarks, key exchange, Quirks and Baselines

#### H1. Read bookmarks. Stories 47, 113

```sh
for b in 684942 628190 373799; do dod bookmarks get $b; echo "exit=$?"; done
dod bookmarks get 684942 --format json | jq .
dod bookmarks get 000000; echo "exit=$?"
```

- Expect: the `bookmarkSet` as the Service sent it (title, uid, lastmark, bookmarks, highlights); JSON adds a summary (title, uid, lastmark, counts). A lastmark with parts missing or `xsi:nil` is shown as it is (lenient read). An unknown id is `invalidParameter`, exit 1.
- Record: whether `uid` equals the book id, and the shape of the lastmark (which of `ncxRef`, `URI`, `timeOffset`, `charOffset` are present). This feeds the resume planning, step K1.

#### H2. Local refusals for `setBookmarks`. Story 113

```sh
cp "$ACC/private/S0.bookmarks-684942.xml" "$ACC/bad.xml"      # then delete a required element, e.g. uid
dod bookmarks set 684942 --file "$ACC/bad.xml"; echo "exit=$?"
dod bookmarks set 684942 --file "$ACC/missing.xml"; echo "exit=$?"
```

- Expect: a file that does not conform to the local bookmark schema (or has a DOCTYPE, or is over 1 MiB) is refused locally with exit 2 and nothing is sent (check with `--debug`).

#### H3. Set bookmarks. Story 113. **STATE-CHANGING (opt-in)**

Uses only your test user's own data and the initial set of C4. `setBookmarks` replaces the whole set.

```sh
cp "$ACC/private/S0.bookmarks-684942.xml" "$ACC/private/H3.xml"
# edit H3.xml: add " (acceptance)" to the title text. Keep uid equal to 684942.
dod bookmarks set 684942 --file "$ACC/private/H3.xml"; echo "exit=$?"
dod bookmarks get 684942 | diff "$ACC/private/S0.bookmarks-684942.xml" - 
# deviating uid (known Tibi deviation): in H3.xml change uid to 000000
dod bookmarks set 684942 --file "$ACC/private/H3.xml"; echo "exit=$?"
```

- Expect: `setBookmarks: ok` (`true`); `get` shows the new title and the rest of the set unchanged. A deviating `uid`: on Tibi earlier, `setBookmarks` validated almost nothing and rejected the deviating `uid` with an EJB fault (not a DODP fault element): shown as it came, exit 1 (a Deviation). Record exactly what happens, twice. If the Service accepts it instead, the set now has the wrong uid: restore immediately.
- Restore (always run, also after a failure):

```sh
dod bookmarks set 684942 --file "$ACC/private/S0.bookmarks-684942.xml"; echo "exit=$?"
dod bookmarks get 684942 | diff "$ACC/private/S0.bookmarks-684942.xml" - && echo restored
```

- If the initial set was empty and the Service refuses to write it back, or normalises it (timestamps, ordering), record that: the difference is the finding.

#### H4. Key exchange. Stories 53, 116

```sh
dod key-exchange acceptance-test-key; echo "exit=$?"
dod key-exchange acceptance-test-key --format xml; echo "exit=$?"
```

- Expect: read-only. If `PDTB2_KEY_PROVISION` is not in `OPS`: a Fault, normally `operationNotSupported`, shown as it came (exit 1). If it is: `invalidParameter` for a key the Service does not have. No key name of the Service is needed or sent. If a key object were ever returned, `UAK` and `CipherValue` contents are masked in every output. `dod` interprets nothing and supports no DRM.

#### H5. Quirks. Stories 118, 119, 120; ADR 0010. **LOCAL**

Only for a deviation you reproduced **twice** (G4 and G4b, or E3 twice) and saved masked. Procedure (ADR 0010, README "Adding a Quirk"):

1. Reproduced twice, the masked Exchange saved (`--save-exchanges`).
2. Checked once more against the local specification copy (`docs/spec/dodp-v1/`): namespace, parameter order, soapAction, element order. It must not be a defect in `dod`. Where tolerant reading already copes (such as ids that break `xs:NMTOKEN`), there is no Quirk.
3. Record it in an issue (see "Recording a finding"). A Quirk is added by a later change, with fault injection in the fake Service and a test; not by this plan.

To try the existing Quirk against the real Service, add `quirks = ["http-500-without-fault-as-invalid-operation"]` to `[environments.<env>]`, and:

```sh
dod config check; dod quirks list --env <env>
dod test run --only negative | tee "$EV/H5.without.txt"                 # ignored: FAILs stay FAILs
dod test run --only negative --with-quirks | tee "$EV/H5.with.txt"
dod test run --only negative --with-quirks --format json | jq '{quirks, exit_code}'
```

- Expect: `check` validates the name (a misspelt name is refused with exit 2 by every command); `quirks list --env <env>` shows it as enabled. Without `--with-quirks` the Conformance tests ignore it, so a tolerated deviation stays a FAIL. With it, the text report has a `Quirks on:` line, the JSON a `quirks` list, and every use is an `interoperability` Observation. Data commands (`dod list ...`) use the Environment's Quirks without a flag and say so with the Observation. The Quirk only reads an HTTP 500 without a DODP element as `invalidOperation` for operations that need the Initialisation sequence; it does not touch real DODP faults or the Initialisation sequence.
- Record: for each FAIL in G4 that the Quirk turns into PASS, and each that it does not (those are the ones that need something else).
- Restore: remove the `quirks` line from `$DOD_CONFIG`; `dod config check`; `dod quirks list --env <env>` shows nothing enabled.

#### H6. Baseline. Stories 121; ADR 0010. **LOCAL**

The Baseline belongs in the Service's own repository, never in this one. Here it only exercises the mechanism.

```sh
dod test run --write-baseline "$EV/baseline.toml"; echo "exit=$?"
cat "$EV/baseline.toml"
grep -nE 'https?://|<testuser>' "$EV/baseline.toml"; echo "grep-exit=$?"     # expect 1
dod test run --baseline "$EV/baseline.toml"; echo "exit=$?"
dod test run --baseline "$EV/baseline.toml" --fail-on-resolved; echo "exit=$?"
```

- Expect: `--write-baseline` writes one `[[known]]` table per FAIL with `id` and a short `reason` (the specification section the FAIL cites), nothing else, no address or credential; nothing is written when the setup failed. The run against it exits 0 when only baselined FAILs remain (ERROR still gives 2); the report says `Baseline: 0 new, 0 resolved, N known`. The Outcomes in the report are unchanged (a baselined FAIL is still FAIL).
- Now the other cases, on a copy:

```sh
cp "$EV/baseline.toml" "$EV/b-new.toml"        # delete one [[known]] entry
dod test run --baseline "$EV/b-new.toml"; echo "exit=$?"                   # expect 1 and a "NEW <id>" line
cp "$EV/baseline.toml" "$EV/b-resolved.toml"
printf '\n[[known]]\nid = "session.logon.valid-credentials"\nreason = "test"\n' >> "$EV/b-resolved.toml"
dod test run --baseline "$EV/b-resolved.toml"; echo "exit=$?"              # expect 0 and "RESOLVED <id>"
dod test run --baseline "$EV/b-resolved.toml" --fail-on-resolved; echo "exit=$?"   # expect 1
printf '\n[[known]]\nid = "no.such.test"\nreason = "x"\n' >> "$EV/b-resolved.toml"
dod test run --baseline "$EV/b-resolved.toml"; echo "exit=$?"              # warning on stderr
dod test run --baseline "$ACC/missing.toml"; echo "exit=$?"                # expect 2, nothing sent
dod test run --only catalog --baseline "$EV/baseline.toml"; echo "exit=$?" # entries of tests that did not run are neither new nor resolved
dod test run --baseline "$EV/baseline.toml" --format json | jq '{exit_code, baseline}'
```

- Expect as commented. JSON: a `baseline` section with sorted `new`, `resolved`, `known`.
- Record: the **Baseline proposal** (the list of ids with reasons you would commit to the Service's repository), in "Findings" below. Do not commit it here.

## 10. Part I: the terminal interface

Needs `dod-client[tui]` and, for playing, `dod-client[play]`. Run `dod logon` first (the TUI uses the stored Session). Stories 92, 93, 94. All keys are in `dod --help` and the README.

#### I1. Refusals and missing extras

```sh
dod tui --unmask; echo "exit=$?"; dod tui --debug; echo "exit=$?"
dod tui --password-stdin; echo "exit=$?"; dod tui --format json; echo "exit=$?"
```

- Expect: exit 2 each (always masked, ADR 0007; also `--no-session`, `--save-exchanges`, `--unmask-password`). Optionally, in a clean environment without Textual: `dod tui` exits 2 and names `dod-client[tui]`, no traceback.

#### I2. Shelf, metadata and paging. Stories 92, 94

```sh
dod tui
```

- Check: the shelf shows `issued` (25 per page); `Enter` opens the metadata of the selected book and `Escape` goes back; `l`, type `new`, `Enter` shows another list; `n` and `p` page (use a list with more than 25 items; if none, record that); `r` reloads; `q` quits. The screen shows "Loading..." and still reacts to keys while a call is under way. A Fault, a failed logon or no answer is shown as the Service answered and the TUI stays up (stop the Session at the Service first, with `dod logoff` in another shell: `r` must relogin once, with the Environment's password).
- Record: anything garbled, slow or frozen; control characters or markup from titles shown literally and not interpreted.

#### I3. Files and download. Stories 92. **LOCAL** (and needs the books issued)

In the TUI: select a book, `f`, then `d`. Then, on another book, `d` and `c` (or `Escape`) in the middle of a file.

- Expect: the files with sizes and a state column; `N of M bytes` while a file is fetched, then `downloaded`; `c` cancels and leaves no partial file (`find "$DOD_DATA_DIR" -name '*.part'` is empty) and the state says `cancelled`; existing files are not overwritten (`failed` with the reason `dod download` would give); a book that is not issued shows the Service's `invalidParameter` Fault and nothing is issued. Files go to the directory `dod download` uses.
- Restore: delete the downloaded files you do not need.

#### I4. Player bar. Stories 87, 90

In the TUI: select a downloaded book, `P`. Then `Space`, `x`, `]`, `[`, `.`, `,`. Browse while it plays.

- Expect: the bar shows the state, `file k of n` and elapsed/total time on every screen; `Space` pauses and resumes; `x` stops; `]` and `[` go to the next and previous Clip; `.` and `,` move 30 seconds; playing continues while you browse. A book that is not downloaded (any audio file missing) is refused with a line saying to download first (`f`, then `d`); nothing is streamed or fetched. Without `miniaudio` the bar says what is missing and browsing still works. Compare the order and the refusals of 628190 and 373799 with F7 and F8.

#### I5. Log panel. Story 93

`L` opens it, `Escape` closes it.

- Expect: the Exchanges of the run (method, address, status, time, headers, first 2000 characters of each body) and the Observations, oldest first, always masked (no password, cookie values are fingerprints). No way to unmask.
- Record: any secret visible (finding of the first order).

## 11. Part J: cleanup and the final comparison

#### J1. Restore the Service, your configuration and your machine

```sh
dod list --format json | jq -S . | diff - <(jq -S . "$EV/S0.shelf.json") && echo "shelf as at the start"
for b in 684942 628190 373799; do dod bookmarks get $b | diff -q "$ACC/private/S0.bookmarks-$b.xml" - ; done
dod announcements list | diff - "$EV/S0.announcements.txt"
```

- Expect: the shelf and the bookmark sets as in C4. Announcements marked as read in C3 cannot be restored and will differ; say so.
- Remove `protected = true` and `quirks` from `$DOD_CONFIG` if you do not want them; `dod config check`.
- `dod logoff`.
- Delete what holds secrets: `rm -r "$ACC/private" "$DOD_STATE_DIR"`. Delete the downloaded books when you are done with them: `rm -r "$DOD_DATA_DIR"`. Keep `$EV` and the log until the findings are filed, then delete them too if they contain anything you should not keep.
- Confirm nothing of this run is in a git checkout: `git status` in any clone you used is clean and `$ACC` is outside it.

## 12. Part K: resume from `lastmark` (waiting for the planning issue)

**Waiting for the planning issue** ([#47](https://github.com/NationalLibraryOfNorway/tibi-dod-client/issues/47)). Story 124 (`dod play` continuing from the last reading position for DAISY 2.02 and EPUB 3) is built last, after a planning decision about the mapping between a `lastmark` and a Clip and a deliberate change of ADR 0009. Nothing in `dod` writes or reads a `lastmark` while playing today, so there is nothing to run. This part is a placeholder; do not mark the plan complete on it, and do not treat the absence as a defect.

- K1. When the planning issue is done, write the steps here: set a `lastmark` (with the mapping to `ncxRef`, `URI` (`file.smil#id`) and `timeOffset`/`charOffset` the issue chooses), stop playback, start again and check that it resumes at the same Clip (DAISY 2.02) and at the corresponding place (EPUB 3, which has no standard encoding), and restore with step H3.
- Collect now: the shape of the lastmark of the three books as recorded in H1 and the Service's behaviour on `setBookmarks` (H3: validates almost nothing, rejects a deviating `uid`). That is the input the planning issue needs.
- Related and also not covered: an interactive menu screen in the TUI ([#48](https://github.com/NationalLibraryOfNorway/tibi-dod-client/issues/48)). Menus are checked only through `dod questions` (part E) for now.

## 13. Findings

Open one issue per finding in this repository's tracker (it is public: see the rules below), and note its number in your log. A finding is anything that deviates from the "Expect" lines, from the specification, or from the ADRs.

### Recording a finding

Use this template for the log and for the issue:

```markdown
**Finding:** <short title>                      **Step:** <id>      **Type:** D / T / E / S
**Command:** `dod ...` (flags only; no address, no user name)
**Expected (spec section or ADR):** ...
**Observed:** exit code, stdout/stderr in short, the Outcome, the Fault element or HTTP status
**Reproduced:** twice? yes/no (dates of both runs; a deviation counts only when it is the same twice)
**Exchange:** attached masked Exchange file (`--save-exchanges`), scrubbed as below
**Proposal:** Quirk candidate / Baseline entry / fix in dod / documentation / none
```

Types: **D** Service deviation (the Service answered against DODP v1; checked against `docs/spec/dodp-v1/`), **T** defect in `dod` (including a wrong `--help` or README), **E** environment (network, device, account, platform), **S** the specification or an ADR is silent or contradictory.

Rules for what goes into an issue or a pull request (the repository is public, and so is the issue tracker):

- No address of the Service (also none in saved Exchanges: the `.json` and the request files contain URLs; replace with `<service>`), no user name, no password, no cookie value or fingerprint of a real secret, no patron data, no internal host or system name. Book ids of the three test books and metadata of the catalogue are fine; titles are not needed.
- Use only masked output. If a secret ever appeared unmasked, that is a finding of the first order: report it without the value, and rotate the credential.
- Check the "Observed" text with a search for `https://`, the user name and the host name before you post it.
- The deviations seen earlier on Tibi (`back` giving HTTP 500, ids with spaces, `setBookmarks` and `uid`) are listed in the specification, but nobody has reproduced them twice with a saved masked Exchange yet; do that and file them with the evidence.

### Findings log (copy and fill in)

| # | Step | Type | Short description | Reproduced twice | Issue | Proposal |
| --- | --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |  |

### Quirk candidates (ADR 0010)

A candidate needs: reproduced twice with a saved masked Exchange; checked against `docs/spec/dodp-v1/`; shown not to be a defect in `dod`; no tolerant-reading answer. This plan only collects them.

| Behaviour (generic, no backend name) | Operations | Reproduced twice | Checked against the spec | Spec reference | Issue |
| --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |

### Baseline proposal

The ids that FAIL and that you accept for now, with one-line reasons. It goes in the Service's own repository as `[[known]]` tables (`id`, `reason`), not here.

| Test id | Reason (spec section) | Fix expected? |
| --- | --- | --- |
|  |  |  |

## 14. Coverage of the specification's user stories

Every story is covered by a step or is a development or CI matter that this manual run does not check. Story numbers are those of issue #18.

| Stories | Where |
| --- | --- |
| 1, 2, 4, 5, 117 | A1 |
| 7, 8, 9, 13, 20, 21 | A2, A3 |
| 10 | A4 |
| 11, 12, 14, 16, 18, 23 | A3 |
| 15, 19 | Environment setup, B4, B5 |
| 17 | A3 (Windows only; see open items) |
| 22 | Working directory setup (`DOD_STATE_DIR`, `DOD_DATA_DIR`) |
| 26, 31, 34 | B2 |
| 27, 28, 29 | B1 |
| 30, 32, 33 | B3, B4, F4 |
| 35, 36 | A5, B4 |
| 37 | G5 |
| 38, 39, 43, 44 | B4, B6, B11 |
| 40, 41, 42 | B9, B10 |
| 45 | covered by the fake Service only (needs a Service that fails `setReadingSystemAttributes`) |
| 46, 71 | G4 |
| 47, 48, 52, 53 | C1, D, H1, H4 |
| 49, 50, 51 | B4, B7, C1, D1 |
| 54 | every step (exit codes), G7 |
| 55 to 58 | B7 |
| 59, 60 | B8 |
| 61, 76 | B4, G2 |
| 62 | G2 |
| 63 to 68, 73, 74, 75 | G2, G7 |
| 69, 70, 85, 86 | G5, F1 |
| 72 | G1, G3 |
| 77 | F2, F9 |
| 78, 79, 80, 81, 82, 83, 84 | F1, F4 |
| 87 to 91 | F6, F7, F8, F10 |
| 92, 93, 94 | I1 to I5 |
| 104, 105 | B4, B6, C3 |
| 106, 107 | C2 |
| 108, 109, 111, 112, 115 | D, F3, F4, E0 |
| 110 | F9 |
| 113 | H1, H2, H3 |
| 114 | E0 to E4 |
| 116 | H4 |
| 118, 119, 120 | A5, H5 |
| 121 | H6 |
| 123 | this plan |
| 124 | K1, waiting for the planning issue |
| 3, 6, 24, 25, 95 to 103, 122 | Not checked by hand: development, packaging, CI and licence matters (macOS and Windows runs, the missing `miniaudio` wheels, `THIRD-PARTY.md`, the fake Service, `tach`, the CI matrix); see the open items |

## 15. Open items from the implementation

Collected from the pull requests of the implementation layers (#49 to #75) and the ADRs. These are what the agents did not or could not check, and decisions that were deferred. Each is either exercised by a step above or needs a decision after the run.

| # | Item | Source | Where |
| --- | --- | --- | --- |
| 1 | No layer was run against the real Service. The explicit "not checked against Tibi" notes are on Sessions (#57), attributes and announcements (#58), `list` and `metadata` (#59), the conformance runner (#60), `resources`/`download` (#64), bookmarks and key exchange (#67), `play` (#69, #70, #71), the TUI (#72, #73, #74) and Quirks (#63). | PR bodies | Whole plan |
| 2 | The one Quirk, `http-500-without-fault-as-invalid-operation`, has never been reproduced against a real Service, only by fault injection. Whether the Service really answers HTTP 500 without a DODP element, and for which operations, is unconfirmed. | #63, ADR 0010 | G4, H5 |
| 3 | Deviations observed earlier on Tibi but not yet reproduced twice with a saved masked Exchange (so no Quirk): `back` answers HTTP 500 instead of `invalidParameter`; menu choice ids with spaces against `xs:NMTOKEN` (tolerant reading, not a Quirk); `setBookmarks` validates almost nothing and rejects a deviating `uid` with an EJB fault. | #18, ADR 0010 | E1, E3, H3 |
| 4 | No Quirk or Conformance test covers `back`; the existing Quirk only applies to operations that need the Initialisation sequence. Decide after E3 whether `back` needs a Quirk, a test, or just a note. | #38, #63 | E3, H5 |
| 5 | A real Session expiry has not been seen: it is assumed to be a `noActiveSession` fault in `detail`. If the Service signals expiry differently, `dod` will not relogin. | #27, ADR 0005 | B9 |
| 6 | The real WSDL has not been read: exactly one SOAP 1.1 port on the DODP portType, and whether its `soap:address` is on the same host, port and scheme as the WSDL. | #25, ADR 0002 | B1, B2 |
| 7 | The session cookie Observations (`cookie-hardening`, `transport-security`) on the real Service; whether the cookie is set without a login. | #26 | B4 |
| 8 | Resource addresses of the real books: relative or absolute, same host or a Service Delegate, `http` or `https`, `localURI` shapes, sizes against `Content-Length`; `Range` support (a Service need honour it, a Service Delegate need not). | #34, #36, ADR 0008 | F3, F4, G5 |
| 9 | Download has no resume and no parallelism; behaviour on the real size of 684942 is unknown. | #34, ADR 0008 | F4 |
| 10 | Real audio formats against `miniaudio` (WAV, FLAC, MP3, Ogg Vorbis, no AAC); a book in a format it cannot decode gives an error and an `audio-format` Observation. Tests used synthetic WAV files and `Backend.NULL`; no audio device was ever opened. | #39, ADR 0009 | F6 |
| 11 | Real DAISY 2.02 structure: `master.smil`, `ncc.html` order, nested `seq`/`par`, missing clip times. The position shown runs slightly ahead of what is heard; pause, resume and jumps are stop and restart. | #39, ADR 0009 | F6 |
| 12 | 628190 "audio only": whether it has SMIL (plays) or not (refused). | #39, #40 | F7 |
| 13 | EPUB 3 delivery: extracted files or a single `.epub` archive. `dod` does not unpack; a single archive will not play and may need a decision. 373799 has no media overlay, so the expected result is the refusal. | #40, ADR 0009 | F5, F8 |
| 14 | `--fetch-missing` fetches before playing starts (not "just before each file"), and fetches audio only; ADR 0009's wording was changed to match. Real behaviour on a missing file unchecked. | #41 | F10 |
| 15 | TUI never run in a real terminal; resource list with progress and cancel against real downloads; player bar and log panel with a real book; Gateway lock held during a download (other TUI calls wait). | #42, #43, #44 | I1 to I5 |
| 16 | `announcements mark-read` fallbacks (set rejected with `invalidParameter`, one at a time; `false` as "already read") against the real Service. Irreversible. | #28 | C3 |
| 17 | `returnContent` for a never-borrowed or already returned book answers `true` according to the spec; `requiresReturn` false books are refused. Not seen on the real Service. | #35 | F9 |
| 18 | `getContentList` with an invalid range: empty list and the total per specification; the real answer is unknown. | #29 | D2, G2 |
| 19 | Declared against actual `supportedOptionalOperations` for bookmarks, key exchange and menus. | #37, #38, ADR 0010 | G6 |
| 20 | `real_backend` pytest marker is declared and deselected by default, but no test uses it yet (story 99). Decide after the run whether the stable checks of this plan become `real_backend` tests. | pyproject, #8 | after the run |
| 21 | macOS and Windows have not been exercised by hand (story 3); on Windows file permissions are not set or checked (`dod config check` warns). CI runs them on 3.12 and 3.15 only; the 3.15 jobs are non-blocking until `lxml` and `miniaudio` publish wheels; `dod play` exits 2 on platforms without a `miniaudio` wheel (story 6). | #20, #49 | outside this plan |
| 22 | The release workflow (#45) has not run: no tag exists, so the install from a GitHub release (story 1) is untested. Run it once with `workflow_dispatch` (build and checks only), then with the first tag. Until then install the wheel from `uv build`. | #45 (#75) | A1, outside this plan |
| 23 | Resume from `lastmark` (story 124) and the interactive TUI menu screen are planned in [#47](https://github.com/NationalLibraryOfNorway/tibi-dod-client/issues/47) and [#48](https://github.com/NationalLibraryOfNorway/tibi-dod-client/issues/48); this plan has a placeholder for the first. | #18, ADR 0009 | K1 |
| 24 | Risks accepted on purpose and not part of this run: the specification copy without written permission, and the iconv assessment without legal review (story 25, `THIRD-PARTY.md`). | #9, #15, #18 | outside this plan |

## 16. Sign-off

When every step has a result in the log and every finding has an issue, tick the boxes and keep the log with the issue that tracks the run.

- [ ] Parts A to J run (parts that do not apply are marked "not offered" with the reason).
- [ ] Every State-changing step had its initial state recorded, and J1 shows the Service as at the start (announcements marked read excepted).
- [ ] Every FAIL and ERROR of G2 and G4 is a finding with a type.
- [ ] Quirk candidates and the Baseline proposal are filled in, or "none".
- [ ] No secret, address or patron data in any issue, and `$ACC/private` and the Session files are deleted.
- [ ] Part K stays "waiting for the planning issue" until that issue is done.
