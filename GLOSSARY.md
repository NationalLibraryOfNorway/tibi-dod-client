# dod

`dod` is a cross-platform test client for DODP v1 (DAISY Online Delivery Protocol) backends. It acts as a Reading System against any conforming Service.

## Language

**Service**:
A DODP backend that implements the protocol and is addressed by one SOAP endpoint URL.
_Avoid_: Server, API

**Reading System**:
The DODP role `dod` plays towards a Service; it identifies itself to the Service through `setReadingSystemAttributes`.
_Avoid_: Client, agent

**Session**:
The stateful relationship between a Reading System and a Service, from a successful `logOn` until `logOff` or expiry on the Service side. It is carried by an opaque HTTP cookie.
_Avoid_: Login, connection

**Initialisation sequence**:
The mandatory `logOn`, `getServiceAttributes`, `setReadingSystemAttributes` calls that make a Session usable.
_Avoid_: Handshake

**Session file**:
The local record of one Session, identified by Service URL and username, that lets separate `dod` invocations reuse it. It never holds a password.
_Avoid_: Cache, token file

**Expired session**:
A Session the Service no longer recognises, signalled by a `noActiveSession` fault.
_Avoid_: Invalid session, stale cookie

**Ephemeral mode**:
Running a command with its own Session that is never persisted and is ended with `logOff` afterwards.
_Avoid_: Stateless mode

**Conformance test**:
A check of one aspect of a Service's behaviour against the DODP v1 specification. Each ends in exactly one Outcome.
_Avoid_: Test case, probe

**Outcome**:
The result of a Conformance test: **PASS** (the Service answered as the specification requires), **FAIL** (the Service answered, but contrary to the specification), **SKIP** (the test does not apply or was not opted into) or **ERROR** (the test could not be evaluated).
_Avoid_: Status, verdict

**Spec deviation**:
A Service answer that contradicts the DODP v1 specification, such as a fault with no recognisable DODP fault element. Reported as FAIL.
_Avoid_: Bug, quirk

**Negative test**:
A Conformance test that deliberately sends an invalid request, such as an operation with no Session or a parameter the specification forbids, and expects a DODP fault. Negative tests send through the **RawChannel**, run in an Ephemeral-mode Session of their own, and are explicit: an ordinary run never includes them, only `--only negative` does.
_Avoid_: Fuzzing

**RawChannel**:
A port narrower than `ServicePort` (`send_raw(operation, body)`) that sends any operation name with any body, unchecked. Only the HTTP adapter implements it.
_Avoid_: Raw port

**State-changing test**:
A Conformance test that alters data on the Service, such as the loan state of a content item. Skipped unless explicitly enabled.
_Avoid_: Destructive test

**Environment**:
A named, locally configured address to one Service (for example prod, test or local), selected instead of typing the full URL. It may also hold the username and password to use against that Service, but is otherwise only an alias: Sessions are identified by the resolved Service URL.
_Avoid_: Profile, target

**Observation**:
Something `dod` notices about a Service while talking to it that is not a Conformance test Outcome, such as an unencrypted endpoint. It never affects the exit code.
_Avoid_: Warning, finding


**Exchange**:
The raw request and response of one call to a Service as they went over the wire. It is unmasked; hiding secrets is the job of whatever presents it.
_Avoid_: Transcript, trace

**Reply**:
A Service's answer to one call, whatever it contains: a result, a fault, or an answer that contradicts the specification. Only a call that got no usable answer at all has no Reply.
_Avoid_: Response, result

**Masking**:
Replacing secrets in a presented Exchange, such as the password and cookie values, with a short fingerprint. Always applied to files and reports.
_Avoid_: Redaction, scrubbing

**Spec reference**:
A pointer from a FAIL or a Spec deviation to the part of the DODP v1 specification it contradicts, given as section number, title, anchor, an optional short rule and a link to the published HTML version. They come from a closed registry.
_Avoid_: Citation, rule id

**Issued content**:
A content item the Service has granted the Reading System access to through `issueContent`, and the only kind whose resources can be listed and downloaded.
_Avoid_: Borrowed book, checked-out item

**Service Delegate**:
A host other than the Service that serves content resources on its behalf, possibly with credentials embedded in the resource URI.
_Avoid_: CDN, mirror

**Playlist**:
The ordered sequence of Clips that makes up the playing order of a book, derived from the book's own structure.
_Avoid_: Queue

**Clip**:
One stretch of audio in a Playlist: an audio file with a start and an end within it.
_Avoid_: Segment, track

**Quirk**:
A named, opt-in workaround in the HTTP adapter for a known Service deviation that would otherwise make an answer unreadable. It is enabled per Environment, always produces an Observation, and is ignored by Conformance tests unless asked for.
_Avoid_: Hack, workaround flag, backend profile

**Baseline**:
A file, kept in the Service's own repository, listing the Conformance test ids that are known to FAIL, each with a short reason. A run compared against it reports new and resolved deviations; Outcomes themselves are unchanged.
_Avoid_: Allowlist, expected failures
