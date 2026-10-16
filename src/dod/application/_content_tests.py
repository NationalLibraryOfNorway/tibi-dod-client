"""The `content` family: issue, resources, fetch and Range (ADR 0008).

These tests are State-changing (they borrow content) and use only the content
the user names with `--content-id`; they never pick a book themselves. Each one
issues the content, and registers `returnContent` as a cleanup step unless the
content was already issued before the run, so the loan state is left as found.
A `returnContent` that goes wrong is an ERROR on the cleanup record (ADR 0005).
At most 64 KiB of any resource is read.
"""

from __future__ import annotations

import re

from dod.application._conformance import Context, Result, conformance_test
from dod.application._download import (
    ResourceRefused,
    resolve_resource_uri,
    validate_resources,
)
from dod.domain.service import Exchange, Fault, FaultKind, Ok
from dod.domain.v1 import (
    SPEC_REFS,
    ContentResource,
    ContentResources,
    SinkRefused,
    operation_ref,
)

_LIMIT = 64 * 1024
"""The most bytes of one resource a test reads."""
_RANGE_BYTES = 1024
_RESOURCES = SPEC_REFS["type.resources"]


def _header(exchange: Exchange | None, name: str) -> str | None:
    if exchange is None:
        return None
    for key, value in exchange.response_headers:
        if key.lower() == name:
            return value
    return None


def _content(ctx: Context) -> str:
    if ctx.target.content_id is None:
        ctx.skip("no --content-id: the content tests never choose content themselves")
    return ctx.target.content_id


def _issued_ids(ctx: Context) -> set[str]:
    """The ids on the `issued` list, or SKIP when that cannot be read, because
    then the loan state could not be restored safely."""
    reply = ctx.call(lambda p: p.get_content_list("issued", 0, -1))
    if not isinstance(reply, Ok) or reply.schema_violations:
        ctx.skip(
            "the issued list cannot be read, so it is not known whether the "
            "content is already issued and the loan state could not be restored"
        )
    return {item.id for item in reply.value.items}


def _issue(ctx: Context) -> str:
    """Issue the chosen content and arrange for it to be returned afterwards.

    Content that cannot be issued (a fault or `false`) is an ERROR: the test
    cannot be evaluated with it. Content that was already issued is left issued.
    """
    content_id = _content(ctx)
    already = content_id in _issued_ids(ctx)
    reply = ctx.call(lambda p: p.issue_content(content_id))
    refused = isinstance(reply, Fault) or (isinstance(reply, Ok) and not reply.value)
    if not refused and not already:
        ctx.cleanup(lambda: ctx.call(lambda p: p.return_content(content_id)))
    if isinstance(reply, Fault):
        ctx.error(
            f"issueContent answered the fault {reply.kind}: the content cannot be "
            "issued, so the test cannot be evaluated"
        )
    if not ctx.expect_ok(reply, operation_ref("issueContent")):
        ctx.error("issueContent answered false: the content cannot be issued")
    return content_id


def _resources(ctx: Context, content_id: str) -> ContentResources:
    reply = ctx.call(lambda p: p.get_content_resources(content_id))
    return ctx.expect_ok(reply, operation_ref("getContentResources"))


def _first_resource(ctx: Context) -> tuple[ContentResource, str]:
    """Issue the content and give its first resource with the address to fetch."""
    listed = _resources(ctx, _issue(ctx)).resources
    if not listed:
        ctx.skip("the content has no resources to fetch")
    first = listed[0]
    if first.size is None:
        ctx.skip("the first resource declares no size")
    try:
        resolved = resolve_resource_uri(
            first.uri,
            ctx.target.url,
            trust_host=ctx.target.trust_host,
            insecure=ctx.target.insecure,
        )
    except ResourceRefused as refusal:
        ctx.skip(f"{refusal}; --trust-host allows a Service Delegate's host")
    for observation in resolved.observations:
        ctx.observe(observation.message, observation.id)
    return first, resolved.url


class _Limited:
    """A sink that counts the bytes and stops the transfer beyond the limit."""

    def __init__(self) -> None:
        self.received = 0

    def __call__(self, chunk: bytes) -> None:
        self.received += len(chunk)
        if self.received > _LIMIT:
            raise SinkRefused("more than 64 KiB; the test reads no more")


@conformance_test("content.issue.returns-true", state_changing=True)
def issue_returns_true(ctx: Context) -> Result:
    """issueContent answers true for content that can be issued."""
    _issue(ctx)
    return Result.passed()


@conformance_test("content.resources.list", state_changing=True)
def resources_list(ctx: Context) -> Result:
    """getContentResources answers a valid list: schema, sizes and localURI rules."""
    listed = _resources(ctx, _issue(ctx))
    problems = validate_resources(listed.resources)
    if problems:
        ctx.fail("; ".join(problems[:3]), _RESOURCES)
    return Result.passed()


@conformance_test("content.resource.fetch", state_changing=True)
def resource_fetch(ctx: Context) -> Result:
    """The first resource can be fetched and its Content-Length is its size."""
    resource, url = _first_resource(ctx)
    size = resource.size
    assert size is not None
    sink = _Limited()
    reply = ctx.call(lambda p: p.fetch_resource(url, sink))
    cut_off = sink.received > _LIMIT
    if not cut_off:
        ctx.expect_ok(reply, _RESOURCES)
    if cut_off and size <= _LIMIT:
        ctx.fail(f"the resource declares {size} bytes but sends more", _RESOURCES)
    length = _header(reply.exchange, "content-length")
    if length is not None and length.strip() != str(size):
        ctx.fail(
            f"Content-Length is {length.strip()} but the resource declares size {size}",
            _RESOURCES,
        )
    if not cut_off and sink.received != size:
        ctx.fail(
            f"the resource declares {size} bytes but {sink.received} arrived",
            _RESOURCES,
        )
    if length is None:
        ctx.note("the answer has no Content-Length")
    if cut_off:
        ctx.note("read only the first 64 KiB")
    return Result.passed()


@conformance_test("content.resource.range", state_changing=True)
def resource_range(ctx: Context) -> Result:
    """A Range request is answered 206 with a matching Content-Range.

    A Service Delegate that does not support Range is an Observation, not a FAIL.
    """
    resource, url = _first_resource(ctx)
    size = resource.size
    assert size is not None
    if size < 2:
        ctx.skip("the first resource is too small to ask for a range of")
    last = min(size, _RANGE_BYTES) - 1
    sink = _Limited()
    reply = ctx.call(lambda p: p.fetch_resource(url, sink, (0, last)))
    status = None if reply.exchange is None else reply.exchange.status
    if status is None:
        ctx.skip("the adapter reports no HTTP status to judge a range by")
    if status in {200, 416}:
        ctx.observe(
            f"a resource answered HTTP {status} to a Range request: Range is not "
            "supported"
        )
        ctx.note("Range is not supported (see the Observations)")
        return Result.passed()
    got = ctx.expect_ok(reply, _RESOURCES)
    if status != 206:
        ctx.fail(f"a Range request was answered HTTP {status}, not 206", _RESOURCES)
    given = _header(reply.exchange, "content-range")
    if given is None or not re.fullmatch(
        rf"bytes 0-{last}/(?:{size}|\*)", given.strip()
    ):
        ctx.fail(
            f"Content-Range is {given!r}, expected bytes 0-{last}/{size}", _RESOURCES
        )
    if got != last + 1:
        ctx.fail(f"{last + 1} bytes were asked for but {got} arrived", _RESOURCES)
    return Result.passed()


@conformance_test("content.resources.not-issued", state_changing=True)
def resources_not_issued(ctx: Context) -> Result:
    """getContentResources on content that is not issued is invalidParameter."""
    content_id = ctx.target.unissued_content_id
    if content_id is None:
        ctx.skip("no --unissued-content-id to ask about")
    if content_id in _issued_ids(ctx):
        ctx.skip("the content named by --unissued-content-id is issued")
    reply = ctx.call(lambda p: p.get_content_resources(content_id))
    ctx.expect_fault(reply, FaultKind.INVALID_PARAMETER)
    return Result.passed()
