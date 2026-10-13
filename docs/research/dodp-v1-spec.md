# DODP v1: operations, namespaces and fault model

Research note for issue #2 (child of map #1). Throwaway research branch: not merged, no PR.
Only public primary sources. Quotes are short; see the sources for the full text.

## Sources

| Id | Source | Notes |
|----|--------|-------|
| S1 | [Specification for the DAISY Online Delivery Protocol v1](https://daisy.org/?p=2568) (archived page) | "Approved May 29, 2010 by the DAISY Consortium Board." Links the zip below. |
| S2 | [do-spec-20100402.zip](https://dl.daisy.org/standards/DODP/do-spec-20100402.zip) | Contains `do-spec-20100402.html` (the spec), `do-wsdl-10.wsdl`, `do-types-10.xsd`, `bookmark-2005-1.xsd`, `do-dm-primer.html`. Fetched and read on 2026-10-13. |
| S3 | [DAISY DODP standards area](https://daisy.org/activities/standards/dodp/) | Index of v1 and v2. Does not link the WSDL or XSD files separately. |

Section numbers below refer to S2's `do-spec-20100402.html`. WSDL/XSD facts were extracted by parsing the files in S2, not from prose.
Note: the XSD header in S2 labels the schema "Version: 20100402 (Proposed Recommendation)", while S1 says the final approval was 2010-05-29. No later v1 file set was found publicly.

## 1. Technology stack (spec section 3)

- SOAP messages over HTTP 1.1; "compliant with WS-I Basic Profile 1.1" (section 1). HTTPS is recommended for all traffic (3.1.2); Reading Systems must support HTTP and HTTPS (SSL 3.0 / TLS 1.0 as written in 2010; treat as TLS 1.2+ in practice, which is our inference, not the spec).
- Binding (WSDL `DaisyOnlineService`): `soap:binding style="document"`, transport `http://schemas.xmlsoap.org/soap/http`, every body `use="literal"`. This is SOAP 1.1 / WSDL 1.1.
- `soapAction` per operation is `"/<operationName>"`, for example `/logOn`.
- Message parts are all named `parameters` and point at a wrapper element, so requests are bare document/literal wrappers, for example `<logOn>` containing `<username>` and `<password>`.
- Authentication of the SOAP session is by `logOn` (section 4.2). HTTP Basic Authentication appears only for resources hosted by a Service Delegate (3.1.3, 4.4.2).

## 2. Namespaces

| Prefix (convention) | URI | Use |
|---|---|---|
| `do` / `tns` | `http://www.daisy.org/ns/daisy-online/` | WSDL targetNamespace, operation wrappers, all types in `do-types-10.xsd`. `elementFormDefault="qualified"`, so child elements are in this namespace too. |
| `daisy` | `http://www.daisy.org/z3986/2005/bookmark/` | `bookmarkSet` (setBookmarks / getBookmarks), from `bookmark-2005-1.xsd`. |
| `pdtb2` | `http://www.daisy.org/DRM/2005/KeyExchange` | `KeyExchange` (getKeyExchangeObject). |
| `dc` | `http://purl.org/dc/elements/1.1/` | Dublin Core elements inside `contentMetadata/metadata`. |
| `soap` | `http://schemas.xmlsoap.org/wsdl/soap/` | WSDL SOAP binding. |

The XSD imports `http://www.w3.org/2009/01/xml.xsd`, `http://dublincore.org/schemas/xmls/qdc/2008/02/11/dc.xsd` and `http://www.daisy.org/DRM/KeyExchange-2005-1.xsd`. All are external URLs and may be dead or slow; a client should bundle local copies of the schemas it needs instead of resolving them at runtime (recommendation).

## 3. Operations

Required (section 5.1) vs optional (5.2). Parameter order is the `xs:sequence` order in the WSDL; types are from the WSDL/XSD. Response element names are the wrapper `<op>Response` with the child shown.

| # | Operation | Class | Request children, in order | Response child | Faults (per WSDL portType) |
|---|-----------|-------|----------------------------|----------------|-----------|
| 1 | `logOn` | required | `username` string, `password` string | `logOnResult` boolean | internalServerError, invalidOperation |
| 2 | `logOff` | required | none | `logOffResult` boolean | internalServerError, invalidOperation |
| 3 | `setReadingSystemAttributes` | required | `readingSystemAttributes` (do:) | `setReadingSystemAttributesResult` boolean | internalServerError, invalidOperation, invalidParameter, noActiveSession |
| 4 | `getServiceAttributes` | required | none | `serviceAttributes` (do:) | internalServerError, invalidOperation, noActiveSession |
| 5 | `getContentList` | required | `id` NMTOKEN, `firstItem` int, `lastItem` int | `contentList` (do:) | internalServerError, invalidOperation, invalidParameter, noActiveSession |
| 6 | `getContentMetadata` | required | `contentID` string | `contentMetadata` (do:) | as 5 |
| 7 | `issueContent` | required | `contentID` string | `issueContentResult` boolean | as 5 |
| 8 | `getContentResources` | required | `contentID` string | `resources` (do:) | as 5 |
| 9 | `getServiceAnnouncements` | optional (SERVICE_ANNOUNCEMENTS) | none | `announcements` (do:) | internalServerError, invalidOperation, operationNotSupported, noActiveSession |
| 10 | `markAnnouncementsAsRead` | optional (SERVICE_ANNOUNCEMENTS) | `read` (do:, list of `item` strings) | `markAnnouncementsAsReadResult` boolean | 9 plus invalidParameter |
| 11 | `returnContent` | optional | `contentID` string | `returnContentResult` boolean | as 10 |
| 12 | `setBookmarks` | optional (SET_BOOKMARKS) | `contentID` string, `daisy:bookmarkSet` | `setBookmarksResult` boolean | as 10 |
| 13 | `getBookmarks` | optional (GET_BOOKMARKS) | `contentID` string | `daisy:bookmarkSet` | as 10 |
| 14 | `getQuestions` | optional (DYNAMIC_MENUS) | `userResponses` (do:) | `questions` (do:) | as 10 |
| 15 | `getKeyExchangeObject` | optional (PDTB2_KEY_PROVISION) | `requestedKeyName` string | `pdtb2:KeyExchange` | as 10 |

Notes on the table:

- The `Result` suffix in response children is from the WSDL, not the prose. Response children for the complex types carry their own element name (no `Result` suffix).
- `returnContent` is not in the `supportedOptionalOperations` enumeration, so a Service cannot declare it. Its section places it under 5.2 and says "A Reading System must not call this function for a Content item that has a requiresReturn attribute with a value of false" (5.2.3). Treat the `contentMetadata/@requiresReturn` flag as the gate and `operationNotSupported` as the failure signal.
- Which optional operations a Service supports is declared in `serviceAttributes/supportedOptionalOperations/operation`, with enumeration values `SET_BOOKMARKS`, `GET_BOOKMARKS`, `DYNAMIC_MENUS`, `SERVICE_ANNOUNCEMENTS`, `PDTB2_KEY_PROVISION`. `SERVICE_ANNOUNCEMENTS` covers both announcement operations (5.2.1/5.2.2 and the enumeration docs).
- Conditional requirements (section 4.3): a Service must offer at least one content selection method (`OUT_OF_BAND` or `BROWSE`). `BROWSE` requires the dynamic menus feature, so `getQuestions` becomes effectively required there. `getContentList` ids: `issued`, `new`, `expired` are reserved (see 5, getContentList). Services offering borrowable content must recognise `issued`; services with the out-of-band method must recognise `new`.
- `getQuestions` reserved ids are `default` (root question, always supported if dynamic menus are), `search` and `back` (optional, declared via `supportsSearch` / `supportsServerSideBack`); unsupported use gives `invalidParameter` (4.7.6).
- `getContentList`: `firstItem` is zero-based, `lastItem = -1` means "to the end". Invalid range yields an empty `contentList` with `totalItems` set, not a fault (5.1.8).

## 4. Session initialisation sequence (section 4.2.1)

1. `logOn` with credentials. The Service issues a cookie with the session id on success.
2. `getServiceAttributes`.
3. `setReadingSystemAttributes`.

Calling anything else before step 3 completes must give `invalidOperation`, except `logOff`, which is allowed anywhere. After a new `logOn`, the sequence must be repeated.

Content retrieval sequence (4.4.1), order must be preserved per content item: `getContentMetadata`, then `issueContent` (must return true before continuing), then `getContentResources`. `getContentResources` for a content item that is not issued must return `invalidParameter`.

## 5. Types in brief (do-types-10.xsd, order as in XSD)

Only the parts a protocol layer needs. Required = minOccurs 1.

- `readingSystemAttributes`: `manufacturer`, `model`, `serialNumber` (0..1), `version`, `config`. `config`: `supportsMultipleSelections` boolean, `preferredUILanguage` xs:language, `bandwidth` int (0..1), `supportedContentFormats/contentFormat*`, `supportedContentProtectionFormats/protectionFormat*` (enum `PDTB2`) plus optional `keyRing`, `supportedMimeTypes/mimeType*`, `supportedInputTypes/input*` (enum `TEXT_NUMERIC`, `TEXT_ALPHANUMERIC`, `AUDIO`), `requiresAudioLabels` boolean, `additionalTransferProtocols/protocol+` (0..1).
- `serviceAttributes`: `serviceProvider` (0..1, attr `id`), `service` (0..1, attr `id`), `supportedContentSelectionMethods/method` (1..2), `supportsServerSideBack`, `supportsSearch`, `supportedUplinkAudioCodecs/codec*`, `supportsAudioLabels`, `supportedOptionalOperations/operation*`.
- `contentList`: attrs `id` NMTOKEN, `totalItems` int, optional `firstItem`, `lastItem`; optional `label`, then `contentItem*` (attrs `id` string, optional `lastModifiedDate`; child `label`).
- `label`: `text` string, optional `audio`; optional direction attribute (`ltr`/`rtl`).
- `contentMetadata`: attrs `requiresReturn` (required boolean), `category`; optional `sample` (attr `id`); `metadata` with Dublin Core (`dc:title`, `dc:identifier`, `dc:format` required), `narrator*`, `size` long (required), `meta*` (name/content), then any `##other` extension elements.
- `resources`: attrs optional `returnBy`, `lastModifiedDate`; `resource+` with attrs `uri`, `mimeType`, `size`, `localURI` (all required), optional `lastModifiedDate`. `uri` is where to fetch; `localURI` is the path relative to the content root (4.4.2).
- `questions`: a choice of one-or-more `multipleChoiceQuestion` / `inputQuestion`, or `contentListRef` (end point leading to a content list), or `label` (end point message) (4.7.5). `userResponses/userResponse+` with attrs `questionID`, optional `value`, optional base64 `data` child.
- `announcements/announcement*`: attrs `id`, `type` (WARNING, ERROR, INFORMATION, SYSTEM; default INFORMATION), `priority` 1..3 (default 3); child `label`.

## 6. Faults and error codes (section 5.3, WSDL)

- Five faults, each declared as a WSDL fault message whose part is an element of a type with one optional child `reason` (string): `internalServerErrorFault`, `invalidOperationFault`, `invalidParameterFault`, `operationNotSupportedFault`, `noActiveSessionFault`. Fault elements live in the `do` namespace.
- On the wire, "an instance of one of the following types must be the child of the detail element" of a SOAP Fault (5.3). `reason` is "debugging information" that "should not be rendered to the User in most circumstances".
- The spec defines no numeric error codes, and no `faultcode` / `faultstring` values. The fault kind is identified by the name of the element inside `detail`. A client should key on that element name, and treat `faultcode` / `faultstring` as free text (inference from the absence of a definition, then verify against a real backend).
- Precedence when several apply: internalServerError, noActiveSession, operationNotSupported, invalidOperation, invalidParameter (5.3).
- Semantics: noActiveSession for any call outside the initialisation sequence with no valid session; operationNotSupported for an unsupported optional operation; invalidOperation for a call at the wrong stage; invalidParameter for an unrecognised parameter; internalServerError is the catch-all, and "Reading Systems may attempt to call the operation that failed again" (5.3.1).
- `logOn` / `logOff` return booleans too. `logOff`: "A return value of false or a Fault both indicate that the operation was not successful" (5.1.2). `returnContent` must return true or fault, never false.
- HTTP level: "A Service must return the appropriate HTTP status code" (3.1). WS-I BP 1.1 requires HTTP 500 for SOAP faults (from the profile, not restated in the DODP spec; verify in the BP source before relying on it).

## 7. Sessions and cookies (sections 3.1, 3.1.1, 4.2)

- Sessions are tracked with HTTP cookies. Spec: "requires the use of [HTTP Cookies] ... to maintain stateful sessions" (3.1.1). Reading Systems "must be able to receive and send any cookies that are transmitted to it by a Service" and must not process or manipulate them. A cookie jar is therefore required in the client, and the cookie name/format is opaque.
- The Service issues the cookie in the successful `logOn` response. "A Service may issue a cookie even if logOn fails" (note in 4.2.1), so a client must not treat a Set-Cookie as proof of login; only the `logOnResult` true value does. Section 3.1 says the same about an HTTP session.
- Session lifetime: from successful `logOn` until `logOff` or Service termination. "This protocol does not define behaviors relating to the termination of Sessions" (4.2.2); time-outs are implementation-defined. After expiry the Service answers `noActiveSession`; the client must re-run the initialisation sequence.
- Content resource URIs should be reachable outside a session: "A Service should allow a Reading System to access resources outside of an active Session" (4.4.2, a note, not a requirement). Service Delegate resources secured with Basic Authentication embed credentials in the resource URI (4.4.2); a diagnostic layer must mask these.

## 8. WSDL location and discovery

- The spec explicitly has no discovery mechanism: "One feature that could not be tackled in this version of the protocol is the discovery of DAISY Online Delivery services" (section 1; none exists to integrate).
- Appendix A: the Service Provider "must publish a WSDL document at some URI". The document must import the abstract WSDL (`http://www.daisy.org/projects/daisy-online-delivery/do-wsdl-10.wsdl`) into the `do` namespace and define one service with one port bound to `DaisyOnlineService`, whose `soap:address location` is the endpoint. The spec gives an example (`example.org` host) and does not fix the path.
- There is no convention in the spec such as `?wsdl` or a well-known path. The `?wsdl` suffix is a common SOAP-stack habit (an inference, not DODP). For `dod`, the endpoint URL (the `soap:address`) should therefore be a required config value, with the WSDL URL as an optional input that is parsed only to discover that address.
- Abstract WSDL URL status (checked 2026-10-13): `http://www.daisy.org/projects/daisy-online-delivery/do-wsdl-10.wsdl` answers 301 to `https://daisy.org/projects/daisy-online-delivery/do-wsdl-10.wsdl`, which answers 404. Published backend WSDLs that `<import>` the abstract one by that URL will fail to resolve it with a strict importer. The copy in S2 is the authoritative file; bundle it, and do not resolve the import over the network.
- Example endpoint form for docs and tests: `https://dod.example.org/daisy-online/` (synthetic).

## 9. Minimal wire example (synthetic)

```xml
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <logOn xmlns="http://www.daisy.org/ns/daisy-online/">
      <username>testuser</username>
      <password>example-only</password>
    </logOn>
  </soap:Body>
</soap:Envelope>
```

Sent as `POST https://dod.example.org/daisy-online/` with `SOAPAction: "/logOn"`.

## 10. Open points to verify against a real backend (issue siblings under map #1)

1. Exact HTTP status and `faultcode`/`faultstring` actually used for faults.
2. Cookie name, attributes and expiry in practice.
3. Whether the backend serves a WSDL (and where), and whether it imports the dead abstract URL.
4. Which optional operations are declared and whether `returnContent` is exposed when `requiresReturn` is true.
5. `SOAPAction` header form accepted (`/logOn` vs `"/logOn"` vs empty).
6. DODP v2 differences are out of scope for this note (map #1).
