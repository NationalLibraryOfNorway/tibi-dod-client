# Last reading position (`lastmark`) and resume playback

Research for designing resume-playback in `dod`. Status: research only, no code written.
Date of live observations: 2026-10-15.

## Question

How is the last reading position (`lastmark` in the DODP v1 `bookmarkSet`, written with
`setBookmarks`, read with `getBookmarks`) expressed and used in practice for:

- (a) DAISY 2.02 with audio and text,
- (b) DAISY 2.02 audio only,
- (c) EPUB 3 (media overlays with audio, and text-only EPUB 3)?

`dod` derives a Playlist of Clips from SMIL (DAISY 2.02 via `master.smil` / `ncc.html`; EPUB 3 via spine plus
media overlay), so the goal is to know how a stored position can be mapped back to a Clip.

## How to read this document

Each section is tagged:

- **[Primary]** verified from a primary source (spec text, or source code read at a named commit).
- **[Observed]** observed live against one Service implementation (the library's test backend, referred to as
  `<service>`, with a synthetic test user `<testuser>`). This is not a general rule about DODP Services.
- **[Inference]** my reasoning or recommendation; not verified anywhere.

The three live test books are labelled A, B, C (no identifiers are given):

| Label | Format reported by `getContentMetadata` | Audio / text | Packaging seen in `getContentResources` |
|---|---|---|---|
| A | `DAISY 2.02`, `ncc:multimediaType` = `audioFullText` | audio and text | 147 loose files: `ncc.html`, `master.smil`, 24 per-section SMIL files, MP3, one content XHTML, images, CSS |
| B | `DAISY 2.02`, `ncc:multimediaType` = `audioNcc` | audio only (text is just the NCC headings) | 270 loose files: `ncc.html`, `master.smil`, 133 SMIL, 133 MP3, CSS |
| C | `application/epub+zip`, EPUB `package version="3.0"` | text only (`includesAudio` = false) | a single `.epub` resource (about 23 MB) |

## 1. Structure of `lastmark`

### 1.1 Schema and spec text [Primary]

Local copies: `docs/spec/dodp-v1/bookmark-2005-1.xsd`, `do-wsdl-10.wsdl`, `do-spec-20100402.html`.

- `setBookmarks(contentID: xs:string, bookmarkSet)` returns `xs:boolean`; `getBookmarks(contentID)` returns
  `bookmarkSet` (`do-wsdl-10.wsdl`, `setBookmarks` / `getBookmarks` elements; spec 5.2.4 and 5.2.5). Faults:
  `internalServerError`, `invalidOperation`, `invalidParameter`, `operationNotSupported`, `noActiveSession`.
- `bookmarkSet` = `( title, uid, lastmark?, ( bookmark | hilite )* )` (spec 6.2; XSD `bookmarkSet`). `title/text`
  and `uid` are required; `lastmark` is optional.
- `lastmark` is exactly one `bookmarkContent` group (XSD `lastmark`, `bookmarkContent`):

  ```
  ncxRef                                    required  xs:anyURI
  URI                                       required  xs:anyURI
  ( timeOffset charOffset?  |  charOffset ) required: at least one of the two
  ```

  `timeOffset` is `xs:string` (a SMIL clock value, so not validated by the schema); `charOffset` is `xs:long`.
- XSD documentation strings:
  - `lastmark`: "Location where reader left off and where player will resume play when restarted."
  - `URI`: "pointer to id of `<par>` or `<seq>` in SMIL that contains the bookmark."
  - `timeOffset`: "represented as SMIL 2.0 Clock Value ... relative to the start of the SMIL time container
    referenced in the URI."
  - `charOffset`: "Exact position of bookmark in text-only file referenced (via SMIL) by the URI: measured in
    characters, counting from the start of the content of the referenced element; start- and end-tags are not
    counted, white space is then normalized."
  - `ncxRef`: "Captures current location in NCX (the id of the current navPoint) ..."
- DODP v1 spec 4.6: a Reading System "may use the `lastMark` element of the bookmarkSet to store the User's last
  reading position" and "should check for a last reading position before resuming playback". Note the spec prose
  spells it `lastMark`; the schema element is `lastmark`. The wire name is `lastmark`.
- 4.6 also says that Z39.86-2005 Portable Bookmarks "constitutes the normative reference regarding the use and
  semantics of this type", and that audio notes are not supported in DODP.

### 1.2 Z39.86-2005 section 9 [Primary]

Source: ANSI/NISO Z39.86-2005, "9. Portable Bookmarks and Highlights" (9.1 Introduction, 9.2 Elements, 9.3 Examples),
<https://www.daisy.org/z3986/2005/Z3986-2005.html#Bkmk>. Licence: NISO/DAISY copyright, freely readable, no open
licence; only short excerpts are quoted here.

- 9.2 `lastmark`: URI points "to the id attribute of the `<par>` or `<seq>` element in the SMIL file that contains the
  lastmark, plus a time offset and/or character offset to the exact point". Comment: "The `<lastmark>` is set
  automatically by the playback device." Content model: `(ncxRef, URI, ((timeOffset, charOffset?) | charOffset))`.
- 9.2 `URI`: pointer to the `id` of a `par` or `seq` in SMIL (never directly to an audio or text file).
- 9.2 `timeOffset`: "a non-negative clock value, relative to the start of the SMIL time container referenced in
  the URI" with syntax from SMIL 2.0 as profiled in section 7.7.
- 9.1: offsets from element boundaries in audio are `timeOffset`; offsets in textual content are `charOffset`,
  counted from "the start of the content of the referenced element" with whitespace collapsed. Players must be able
  to set marks at any point, not only at element boundaries.
- 7.7 clock values (same document): full (`3:22:55.91`), partial (`43:15.044`) and timecount (`34.6s`, `356ms`,
  `58.214`) forms, each with an optional `npt=` prefix; SMPTE is not allowed. So a bare decimal such as `97.826` is a
  valid timecount (seconds).
- 9.3 examples, all with the NCX file name in `ncxRef`, a `file.smil#parId` URI, and for audio a partial clock value
  (as paraphrased from the examples):
  - `ncxRef` = `<book>.ncx#lvl1_5`, `URI` = `<book>_ch5.smil#para023`, `timeOffset` = `03:52.00`
  - a text-only book: `URI` = `<book>.smil#para297`, `charOffset` = `130` (no `timeOffset`).

  The prose describing example 9.1 ("22 seconds from the start of paragraph 8") confirms that, when the URI names a
  `par`, `timeOffset` is relative to the start of that `par`, not the file.
- The Z39.86 text does not say how the URI is resolved. Bookmark files were exported next to the DTB, so the natural
  base is the DTB directory (the directory holding the NCC/NCX), see 2.3 below.

### 1.3 What the Service accepts and returns [Observed]

Tested with `setBookmarks` and read back with `getBookmarks` on books A and C (B was read only). Observed against one
Service implementation, not a general rule.

- Accepted as sent, and returned unchanged:
  - schema order (`ncxRef, URI, timeOffset`);
  - any element order: a lastmark sent as `charOffset, ncxRef, timeOffset, URI` came back in that order;
  - `timeOffset` as `1.656`, `00:01:15.489`, `75.489s`, `npt=75.489s`, and even `abc` (no clock validation);
  - a `URI` naming a non-existent SMIL file;
  - `timeOffset` together with `charOffset`;
  - `charOffset` only on an audio book;
  - **missing `ncxRef`** and **empty `ncxRef`** (schema-invalid, still `true`);
  - neither `timeOffset` nor `charOffset` (schema-invalid, still `true`);
  - a negative `charOffset` (`-1`).
- Normalised or dropped: `charOffset` is typed (`xs:long`). A non-integer (`1.5`) was stored as
  `<charOffset xsi:nil="true"/>` on readback. A client must tolerate that form.
- Rejected: a `bookmarkSet` whose `uid` differs from the `contentID`, and a body that is not a `bookmarkSet`
  (`<foo/>`). Both returned HTTP 500 with a plain SOAP `Server` fault whose `faultstring` is a Java EJB exception, i.e.
  not a DODP fault element (`invalidParameter` would have been expected; this is a Spec deviation in `dod` terms).
- Replace semantics: every `setBookmarks` replaces the whole stored set, including title and any `bookmark` elements.
  `setBookmarks` with no `lastmark` cleared the lastmark. A `bookmark` sent together with a `lastmark` came back
  alongside it.
- Title: `title/text` is stored as sent; with nothing stored the Service synthesises `<title><text/></title>` and
  `uid` = the content ID.
- Metadata `user:lastRead` (in `getContentMetadata`) did not change when I set a lastmark, issued, listed resources or
  returned. Its meaning is unknown.
- `getBookmarks` worked for books that were not issued. `setBookmarks` was only tried while the book was issued
  (not known whether it also works when not issued).

Service attributes of this Service list `SET_BOOKMARKS` and `GET_BOOKMARKS` (plus `DYNAMIC_MENUS` and
`SERVICE_ANNOUNCEMENTS`), so the capability check in spec 4.6 is applicable.

## 2. DAISY 2.02: what real clients write

### 2.1 A real lastmark found on the Service (book B) [Observed]

Book B already had a lastmark, written some time ago by an unknown Reading System (not by me). It was returned exactly as:

```xml
<lastmark>
  <charOffset>0</charOffset>
  <ncxRef>hix00023</ncxRef>
  <timeOffset>97.826</timeOffset>
  <URI>s023.smil#main</URI>
</lastmark>
```

Interpretation, checked against B's own files (`ncc.html` and `s023.smil`, read in scratch and deleted afterwards):

- `ncxRef` = `hix00023` is the `id` of an NCC heading: `<h1 id="hix00023"><a href="s023.smil#hix00023">`. No file name
  and no `#`, so this is a bare id, unlike the Z39.86 examples (`file.ncx#id`). DAISY 2.02 has no NCX, so the NCC
  heading id stands in for the navPoint id.
- `URI` = `s023.smil#main`: a relative file name in the same directory as `ncc.html` / `master.smil` (this Service
  serves all files flat), and the fragment is the id of the SMIL's root `<seq id="main" dur="655.475s">`, not a `par`.
- `timeOffset` = `97.826`: bare decimal seconds (a valid timecount), relative to the start of the `seq` named in the
  URI. That is the same as the start of the SMIL file, since `main` is the root container. `97.826` lies inside the
  first audio chunk of that file (0 to 120 s).
- `charOffset` = `0`: written although the book has no text content; harmless, and it satisfies schema readers that
  insist on the text branch.
- Why `#main` rather than a `par`: in B the whole 10-minute file is a single `par id="par1"` containing a nested
  `seq` of 120-second `audio` elements (ids `aud001_1`, ...). A `par` id therefore gives no resolution; the only way
  to say "97 s into this file" is the root `seq` plus an offset. Audio-only DAISY 2.02 books from this producer
  look like that.

I do not know which Reading System wrote it, so this shows one real-world usage, not a convention.

### 2.2 Structure of book A (audio and text) [Observed]

Per-section SMIL files (`s003.smil`, `s005.smil`, ...) each have a root `<seq id="main" dur="...">` containing
`<par id="par1" endsync="last">`, `<par id="par2" ...>`, ... Each `par` holds `<text id="hix..." src="<book>.html#hix...">` and
`<audio id="aud001" clip-begin="npt=0.000s" clip-end="npt=9.452s" src="<file>.mp3">`. `par` ids restart at `par1` in
every SMIL file, so `URI` must include the file. `ncc.html` items are `<h1 id="hix00006"><a href="s003.smil#hix00006">`
(and `<span class="page-normal" id="page-3">` page items); `master.smil` lists `<ref src="s003.smil" id="smil003">`
in play order. Here `ncxRef` could be the heading id, the page-item id, or the text id: all are ids in `ncc.html`
space.

### 2.3 Resolution base [Primary and Observed]

- The Z39.86 text does not define the base for `URI`/`ncxRef` [Primary].
- Observed: the one real lastmark uses a bare file name, and the Service stores whatever string it is given [Observed].
- AMIS (see 3.3) resolves the stored URI relative to the book file (`FilePathTools::goRelativePath(mFilePath, uri)`),
  i.e. relative to the book directory [Primary, source].
- Conclusion [Inference]: resolve relative to the directory containing `ncc.html` / `master.smil`. A reader should
  also accept an absolute path-less name and a leading `./`, and treat anything with a scheme or `..` as untrusted
  (see ADR 0008, everything a Service names is untrusted).

### 2.4 What `timeOffset` is relative to [Primary, with an Observed data point]

By the standard: the start of the SMIL time container the URI points to.

- URI points to `#main` (root `seq`): offset from the start of the SMIL file, which equals the sum of the preceding
  `par` durations within that file.
- URI points to a `par`: offset from that `par`'s start (Z39.86 example text); the audio file time is
  `clip-begin` of the par's audio plus the offset (for a single audio element).
- It is *not* a time in the audio file's own timeline and not a book-wide (global) time. In A, `s005.smil` runs from
  0 to 543.590 s, while its MP3 time and the book clock differ again (`ncc:totalElapsedTime` = 00:02:27.681 in the
  SMIL head).
- Observed B data point: `main` + 97.826 is consistent with this; because `par1` also starts at 0 it cannot
  distinguish "relative to seq" from "relative to par".

## 3. EPUB 3

### 3.1 What the EPUB specs say [Primary]

- EPUB 3.3 (W3C Recommendation), <https://www.w3.org/TR/epub-33/>, and EPUB Reading Systems 3.3,
  <https://www.w3.org/TR/epub-rs-33/>. Licence: W3C Document License. Neither specifies how a reading system stores
  the last reading position, nor a bookmark exchange format. The only related hook: EPUB CFI
  (<https://idpf.org/epub/linking/cfi/epub-cfi.html>) is the standard way to address a location in a publication.
- Media overlays (EPUB 3.3 section 9; <https://www.w3.org/TR/epub-33/#sec-media-overlays>):
  - the overlay is SMIL 3 subset: `body`/`seq`/`par`, and a `par` has exactly one `text` and at most one `audio`;
  - `par` and `seq` `id` are **optional**; there is no `<seq id="main">` convention;
  - `text src` is a URL into an EPUB content document (usually with a fragment id); `audio src` plus optional
    `clipBegin`/`clipEnd` are SMIL clock values (examples `23s`, `0s`);
  - 9.3.1: location in the content document and in the overlay are interlinked; after navigation "synchronized playback
    MUST resume at that point".
- Nothing in the EPUB specs gives `ncxRef` or `URI` meaning; EPUB 3 has no NCX (a navigation document, `nav.xhtml`,
  replaces it).

### 3.2 DODP v2 as a hint at the ecosystem direction [Primary]

DODP 2.0.2, <https://daisy.org/activities/standards/dodp/specification-for-the-daisy-online-delivery-protocol-v2-0-2/>
(licence: CC BY-ND 3.0, per the copyright notice on that page). Section 4.6 "Bookmarks":

- Bookmarks still use the Z39.86 `bookmarkSet` grammar, with the same `lastMark` sentence as v1. `lastmark` is also in
  the `contentList` item, and the spec recommends reading it from `getContentList` instead of calling `getBookmarks`
  while building a bookshelf.
- `setBookmarks` became `updateBookmarks` with an `action` (`REPLACE_ALL`, `ADD`, `REMOVE`); `getBookmarks` can request
  `LASTMARK`, `BOOKMARK` or all.
- v2 supports EPUB 3 packaged content, but I found **no EPUB-specific definition** of `lastmark` content (no CFI, no
  new element) in the spec text (grep for `epub` in the spec finds only the definition of Content, resource kinds
  and delivery). So even DODP 2 leaves the encoding for EPUB undefined.

### 3.3 Open-source readers and servers [Primary, source read; no code copied]

Searched GitHub for DODP/DAISY implementations (repository search for "daisy online delivery protocol" and the Kolibre
organisation). All Kolibre repositories below are LGPL-2.1 (per `COPYING`/`LICENSE` and file headers); only short
paraphrases and line references are used here, no code is reused.

- **kolibre/libkolibre-amis** at `e4e34f7e6f95b73bea50bded497eef988e62b8e5` (a refactored branch of AMIS 2, a DAISY
  2.02/3 player), `src/DaisyHandler/DaisyHandler.cpp`:
  - lines about 4436 to 4470 (`loadSmilContent`): on every SMIL load it records a lastmark with `mUri` = the URI loaded,
    `mTextRef`, `mAudioRef` (the id of the audio element) and `mNcxRef` = id of the current navMap node, no
    `timeOffset`. So AMIS resumes at the granularity of an audio/`par` node, not mid-clip;
  - lines about 649 to 670: on opening a book, it resolves `mUri` relative to the book path
    (`FilePathTools::goRelativePath`), loads that SMIL, positions on `mAudioRef`, then syncs the navigation model from
    `mNcxRef` (`syncNavModel`);
  - `src/AmisCommon/BookmarksWriter.cpp` lines about 366 to 410: its own file format writes `uri`, `ncxRef`, `textRef`,
    `audioRef`, `playOrder` and optionally `timeOffset`/`charOffset`. These extra fields are AMIS extensions, not the
    Z39.86 lastmark; they would not survive a round trip through a Service.
- **kolibre/libkolibre-clientcore** at `99bd03aaf16dc5878f540dbfc58f399bdc98ff4f` (the player built on that): no reference to
  `getBookmarks`/`setBookmarks` in `src/DaisyOnlineNode.cpp` or `src/DaisyOnlineBookNode.cpp`; `src/DaisyNavi.cpp` line
  about 460 uses `continueFromLastmark()` from the local AMIS bookmark file ("continuing from last known position").
  I found no evidence that this client round-trips lastmark through a Service.
- **kolibre/libkolibre-daisyonline** at `2674dd707f238a2acac19defd9496d7b89a8676f` (a DODP 1.0 client library) has a
  `Lastmark` class (`src/Lastmark.h`) with constructors for `(ncxRef, URI)`, `+ timeOffset`, `+ charOffset`; its tests
  use placeholder strings (`"ncxRef"`, `"URI"`), so they show shape support, not real values.
- **kolibre/Kolibre-KADOS** at `0f51f42b5982c37e89748027ef906a06969f152e` (a DODP 1 and 2 server), `include/bookmarkSet_serialize.php`
  lines about 53 to 75: copies `ncxRef`, `URI`, `timeOffset` (string) and `charOffset` (int) from the backend object and
  does no semantic validation. Consistent with the Service tested here, which also stores opaque strings.
- No open-source DODP Reading System with EPUB 3 lastmark handling was found. Not searched: closed-source clients, and
  the Swedish (TPB) and other national clients whose sources may not be public.

## 4. Live test notes (summary of procedure)

Procedure, in order, all on the personal test user and only the three test books:

1. Initial state recorded: the issued list (14 items; none of A, B, C), and `getBookmarks` for A, B, C (A and C empty
   sets, B the lastmark in 2.1). All three have `requiresReturn="true"`.
2. `issueContent` for A, B, C; `getContentResources`; small SMIL/NCC/OPF/nav files read into scratch (C's EPUB was
   fetched whole because the Service does not support range requests for it; it was kept only in memory).
3. `setBookmarks`/`getBookmarks` cases listed in 1.3 on A (17 cases) and C (8 cases). B was not modified.
4. Restore: `setBookmarks` with the empty set on A and C; `getBookmarks` compared byte for byte with the initial
   response (A, B and C identical); `returnContent` for A, B and C (all `true`); issued list compared with the initial
   one (identical, 14 items); `getBookmarks` rechecked after the returns (still identical). No local copies of
   books were kept; scratch files were deleted.

## 5. Text-only EPUB (book C) [Observed]

Findings about the book:

- `package.opf` has `version="3.0"` and **no** `media-overlay` attributes or overlay documents, so there is no audio and
  no SMIL. The spine has about 20 XHTML documents plus `nav.xhtml` (with `toc`, `page-list` and `landmarks` navs).
- Ids exist on headings, sections and page markers (`h1_2`, `page-6`, `poem_1`, `generated-headline-d1e361`); in the
  one chapter I inspected 107 `p` elements had no `id`. So `file.xhtml#id` + `charOffset` from the nearest id is
  the only sub-chapter address available without an EPUB CFI.
- The EPUB is delivered as a single zip resource, so a Reading System must download the whole publication before any
  of this can be resolved.

What the Service did when lastmark was set for it (all `true`, all returned as sent, none validated):

| Case | Result |
|---|---|
| `ncxRef` = heading id, `URI` = `chapter.xhtml#id`, `charOffset` = 120 | stored |
| `URI` = `package.opf#epubcfi(...)`, `charOffset` = 0 | stored |
| `timeOffset` = 0 on a book with no audio | stored |
| `URI` without a fragment, `charOffset` = 5 | stored |
| neither offset | stored (schema-invalid) |
| `charOffset` = -1 | stored |
| `charOffset` = 1.5 | stored as `xsi:nil` |
| `ncxRef` = `nav.xhtml#id`, `URI` with `EPUB/` path prefix | stored |

So the Service gives no protection and no hint; any structure survives a round trip as long as it is a well-formed
`bookmarkSet` with a matching `uid`.

## 6. Recommendation for `dod` [Inference throughout]

Principles: write the schema-valid, Z39.86-conformant form so other Reading Systems and a stricter Service can read it;
read leniently (Section 1.3 shows services store anything and real data uses non-standard details like a bare `ncxRef`
id); never trust what comes back (ADR 0008); always check `GET_BOOKMARKS`/`SET_BOOKMARKS` in `supportedOptionalOperations`
first (spec 4.6). Always send `title/text` (book title) and `uid` equal to the `contentID`; a mismatching `uid` gave a
500.

### 6.1 Encoding

**(a) DAISY 2.02, audio and text (and (b) audio only, same rule)**: write

```xml
<lastmark>
  <ncxRef>{id of the NCC item (heading or page item) in effect at the position}</ncxRef>
  <URI>{smil file name}#{id of the par containing the position}</URI>
  <timeOffset>{seconds into that par, e.g. 3.250}</timeOffset>
</lastmark>
```

- Use `URI` = `sNNN.smil#parId` relative to the directory of `ncc.html`, as the Z39.86 examples do.
- `ncxRef`: the id of the heading or NCC item in effect (for B-style books, the same bare id as the one real client
  wrote; do not add a file name, since that is what has been seen in the field). If no NCC item can be determined, write
  the id of the SMIL file's first NCC item or the `par`'s own text id rather than leaving it out, because the field is
  required.
- `timeOffset`: bare decimal seconds with three decimals (a valid timecount, same as the real B value), relative to
  the container named in the URI.
- When the position lies in a `par` that contains several audio clips (B style, where a `par` spans a whole file),
  use `URI` = `sNNN.smil#<root seq id>` (observed `main`) and the offset from the start of the SMIL file, because a
  `par` id cannot locate the point.
- Optionally add `charOffset` `0`, as the real client did, only if the target Service turns out to reject lastmarks
  without it; the schema does not require it when `timeOffset` is present.

**(c1) EPUB 3 with media overlays** (no sample available; nothing was observed live):

- `URI` = path of the overlay document relative to the package base `#parId` if the `par` has an `id`; otherwise the
  content document and fragment from the `text src` (the overlay `par` has no mandatory id).
- `timeOffset` relative to that `par`, in seconds (the media overlay `par` holds one audio clip, so this is easy to map to
  `clipBegin` + offset).
- `ncxRef`: the `href` of the nearest preceding `nav toc` entry as `nav.xhtml#fragment`, or its fragment alone. No real
  data exists, so any choice is a convention that only `dod` follows. Marked experimental.

**(c2) Text-only EPUB 3**: 

- `URI` = `contentdoc.xhtml#id`, relative to the package document directory; `id` is the nearest preceding element with
  an `id` in that document; `charOffset` = characters from the start of that element's content, whitespace collapsed
  (Z39.86 9.1), integer >= 0.
- No `timeOffset`. `ncxRef` as for (c1).
- An EPUB CFI is more precise but is not defined as a `URI` value anywhere; if a CFI is wanted it is better placed in
  the `URI` fragment (`package.opf#epubcfi(...)`, which the Service stores) only as an addition under a clear `dod` convention,
  never instead of the id-plus-`charOffset` form. Marked experimental.
- Resume for this case has no audio, so it is not a Playlist concern at all; it is a text-position hint that `dod` can
  only print.

### 6.2 Mapping a lastmark back to a Clip in the Playlist

1. Parse leniently: accept any element order, missing `ncxRef`, `xsi:nil` offsets, and `timeOffset` in any of the forms
   in Z39.86 7.7 (plus optional `npt=`), including partial clocks such as `03:52.00`. Reject (treat as "no usable
   lastmark", start from the beginning) a `URI` that is absolute, has a scheme, contains `..`, or names a file not in the
   issued resource list.
2. Split `URI` at `#`: file part to the SMIL file in the Playlist's source list (the DAISY `master.smil` order, or the EPUB
   overlay); fragment is the target id.
3. Find the container by id inside that SMIL: a `par` (use its first/only audio) or a `seq` (use the first `par` in it).
   If the id is missing (a `par` id that does not exist), fall back to the start of the SMIL file.
4. Convert the offset: if the target is the root `seq` (or any `seq`), the offset is from the container start, so walk the
   `par` clips by cumulative duration until the sum exceeds the offset (a `par` with a nested `seq` of audio elements is
   walked the same way). If the target is a `par`, add the offset to that `par`'s `clip-begin`.
5. Clamp the offset into the Clip (`clip-begin` .. `clip-end`); if the offset exceeds the container duration, resume at the
   container's end, not at the next book. Resume in the Clip that results, at the computed time inside its audio file.
6. If `timeOffset` is absent (a `charOffset`-only lastmark from another Reading System), resume at the start of the target
   `par`; this matches what AMIS does (3.3).
7. Ignore `ncxRef` for playback; use it only for later navigation context (it never selects a Clip).

For writing, run step 2 to 5 backwards from the Clip that is playing at the stop position: SMIL file, `par` id within it,
offset from the `par` start (or from the root `seq` for B style). Write at stop, pause, and at intervals while playing.

### 6.3 Unsafe or unspecified

- **EPUB 3, all cases**: unspecified in DODP v1, in DODP 2.0.2 and in the EPUB specs. Anything `dod` writes is a private
  convention and other Reading Systems may misread or ignore it. Document it as such and keep it behind an explicit
  option if it is ever written.
- **Text-only EPUB**: no audio, so no Playlist; `charOffset` addressing is fragile without ids on paragraphs (book C has none).
- **Reading real data from other clients**: the one real lastmark differs from the standard examples (bare `ncxRef`,
  bare decimal seconds, `#main`, non-schema element order, a `charOffset` on an audio-only book). Do not validate strictly on read.
- **Whether `timeOffset` is relative to a `seq` or the `par` when a client points at a `par`**: the standard says container
  start; I cannot tell what other clients do. A `par`-addressed offset larger than the `par` duration is a hint that the
  writer meant file-relative; treat that as a tolerated quirk, not a rule.
- **Writing to a Service that validates**: this Service validates nothing meaningful, so a schema-invalid lastmark would
  look fine against it and fail against another. Conformance tests should include a schema validation of
  what `dod` itself writes.
- **Concurrent Reading Systems**: replace semantics (every set replaces all bookmarks and the title) means a write from
  `dod` removes any `bookmark`/`hilite` entries, unless `dod` reads the set first and writes it back with the lastmark replaced.
  Always read-modify-write.

## 7. Open questions

- Which Reading System wrote the real lastmark on B, and is its `timeOffset` relative to the `seq` or to the whole book?
  It would be answered by a second sample in which a `par` boundary is not at 0.
- Does `setBookmarks` require the content to be issued? (Only tested while issued.)
- Does the Service update anything (for example `user:lastRead`) on lastmark writes? Observed: no.
- Do other DODP Services validate or fault on invalid lastmark content, and with which fault?
- How do production EPUB 3 audiobooks (when they exist) carry media overlays: one overlay per chapter, are `par` ids
  present, does the Service serve the EPUB as one resource (as the text-only one is) or loose files?
- Is a lastmark with only a `charOffset` and an audio-less `par` produced by any DAISY 2.02 text-only (`textNcc`) producer? Not tested.

## Sources

- DODP v1 spec, local copy `docs/spec/dodp-v1/` (`do-spec-20100402.html` 4.6, 5.2.4, 5.2.5, 6.2; `bookmark-2005-1.xsd`;
  `do-wsdl-10.wsdl`). Local copy; see the repo `LICENSE` note on `docs/spec`.
- ANSI/NISO Z39.86-2005, section 9 and 7.7: <https://www.daisy.org/z3986/2005/Z3986-2005.html> (NISO copyright; excerpts only).
- DAISY Online Delivery Protocol 2.0.2, section 4.6, 5.2.3, 5.2.4, 6.3:
  <https://daisy.org/activities/standards/dodp/specification-for-the-daisy-online-delivery-protocol-v2-0-2/> (CC BY-ND 3.0).
- EPUB 3.3, Media Overlays: <https://www.w3.org/TR/epub-33/#sec-media-overlays> and EPUB Reading Systems 3.3:
  <https://www.w3.org/TR/epub-rs-33/> (W3C Document License).
- EPUB Canonical Fragment Identifiers: <https://idpf.org/epub/linking/cfi/epub-cfi.html>.
- Kolibre repositories (LGPL-2.1): <https://github.com/kolibre/libkolibre-amis>,
  <https://github.com/kolibre/libkolibre-clientcore>, <https://github.com/kolibre/libkolibre-daisyonline>,
  <https://github.com/kolibre/Kolibre-KADOS>, at the commits named in 3.3.
