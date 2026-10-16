"""The first Conformance test families: session, service attributes and catalog.

Each test is a function `(ctx) -> Result` registered under a stable id. Tests
only classify what the Service answered; fault kinds are read from the DODP
element in `detail`, never from HTTP status or `faultstring`. The tests that
log on or call without a Session open ports of their own, so the setup's
Session is not disturbed.
"""

from __future__ import annotations

from dod.application._conformance import Context, Result, conformance_test
from dod.domain.service import FaultKind, Ok, Password
from dod.domain.v1 import (
    SPEC_REFS,
    ContentList,
    ContentMetadata,
    ServicePort,
    operation_ref,
)

# What the wrong-password test sends: never the password of the run.
_WRONG_PASSWORD = Password("dod-conformance-wrong-password")
_UNKNOWN_LIST = "dod-conformance-unknown-list"
_UNKNOWN_CONTENT = "dod-conformance-unknown-content"


def _log_on(ctx: Context, port: ServicePort, password: Password) -> bool:
    reply = ctx.call(lambda p: p.log_on(ctx.username, password), on=port)
    return ctx.expect_ok(reply, operation_ref("logOn"))


# -- session --------------------------------------------------------------------


@conformance_test("session.logon.valid-credentials")
def logon_valid_credentials(ctx: Context) -> Result:
    """logOn accepts valid credentials and issues a Session."""
    port = ctx.open_port()
    if not _log_on(ctx, port, ctx.password):
        ctx.fail(
            "logOn answered false for the credentials of this run",
            operation_ref("logOn"),
        )
    if port.session is None:
        ctx.fail(
            "logOn succeeded but the Service issued no Session cookie",
            SPEC_REFS["session.initialization"],
        )
    ctx.call(lambda p: p.log_off(), on=port)
    return Result.passed()


@conformance_test("session.logon.wrong-password")
def logon_wrong_password(ctx: Context) -> Result:
    """logOn answers false for a wrong password."""
    port = ctx.open_port()
    if _log_on(ctx, port, _WRONG_PASSWORD):
        ctx.call(lambda p: p.log_off(), on=port)
        ctx.fail("logOn answered true for a wrong password", operation_ref("logOn"))
    return Result.passed()


@conformance_test("session.logoff.invalidates-session")
def logoff_invalidates_session(ctx: Context) -> Result:
    """After logOff the Session is gone: noActiveSession on another port."""
    port = ctx.open_port()
    if not _log_on(ctx, port, ctx.password):
        ctx.fail(
            "logOn answered false for the credentials of this run",
            operation_ref("logOn"),
        )
    ended = port.session
    if not ctx.expect_ok(
        ctx.call(lambda p: p.log_off(), on=port), operation_ref("logOff")
    ):
        ctx.fail("logOff answered false for an active Session", operation_ref("logOff"))
    if ended is None:
        ctx.fail(
            "logOn succeeded but the Service issued no Session cookie",
            SPEC_REFS["session.initialization"],
        )
    after = ctx.open_port()
    after.resume(ended)
    reply = ctx.call(lambda p: p.get_service_attributes(), on=after)
    ctx.expect_fault(reply, FaultKind.NO_ACTIVE_SESSION)
    return Result.passed()


@conformance_test("session.call.without-session")
def call_without_session(ctx: Context) -> Result:
    """An operation outside the initialisation sequence needs a Session."""
    reply = ctx.call(lambda p: p.get_service_attributes(), on=ctx.open_port())
    ctx.expect_fault(reply, FaultKind.NO_ACTIVE_SESSION)
    return Result.passed()


# -- service attributes ---------------------------------------------------------


@conformance_test("attributes.service.get")
def service_attributes(ctx: Context) -> Result:
    """getServiceAttributes answers a schema-valid serviceAttributes."""
    reply = ctx.call(lambda p: p.get_service_attributes())
    ctx.expect_ok(reply, operation_ref("getServiceAttributes"))
    return Result.passed()


@conformance_test("attributes.reading-system.set")
def reading_system_set(ctx: Context) -> Result:
    """setReadingSystemAttributes accepts the declaration of dod."""
    reply = ctx.call(lambda p: p.set_reading_system_attributes(ctx.reading_system))
    ref = operation_ref("setReadingSystemAttributes")
    if not ctx.expect_ok(reply, ref):
        ctx.fail("setReadingSystemAttributes answered false", ref)
    return Result.passed()


# -- catalog --------------------------------------------------------------------


def _issued(ctx: Context) -> ContentList:
    reply = ctx.call(lambda p: p.get_content_list("issued", 0, -1))
    return ctx.expect_ok(reply, operation_ref("getContentList"))


def _lists(ctx: Context) -> list[ContentList]:
    """`issued`, which every lending Service has, and `new` where it answers."""
    found = [_issued(ctx)]
    reply = ctx.call(lambda p: p.get_content_list("new", 0, -1))
    if isinstance(reply, Ok) and not reply.schema_violations:
        found.append(reply.value)
    return found


def _first_item_of(ctx: Context, list_id: str) -> ContentList:
    reply = ctx.call(lambda p: p.get_content_list(list_id, 0, 0))
    return ctx.expect_ok(reply, operation_ref("getContentList"))


def _metadata_of(ctx: Context, book: str) -> ContentMetadata:
    reply = ctx.call(lambda p: p.get_content_metadata(book))
    return ctx.expect_ok(reply, operation_ref("getContentMetadata"))


@conformance_test("catalog.list.issued")
def list_issued(ctx: Context) -> Result:
    """getContentList knows `issued` and answers with that id."""
    shown = _issued(ctx)
    ref = operation_ref("getContentList")
    if shown.id != "issued":
        ctx.fail(f"the list answered has the id {shown.id!r}, not issued", ref)
    if len(shown.items) > shown.total_items:
        ctx.fail(
            f"the list has {len(shown.items)} items but totalItems is "
            f"{shown.total_items}",
            ref,
        )
    return Result.passed()


@conformance_test("catalog.list.segment")
def list_segment(ctx: Context) -> Result:
    """firstItem and lastItem pick a segment of a list."""
    ref = operation_ref("getContentList")
    for shown in _lists(ctx):
        if len(shown.items) >= 2:
            segment = _first_item_of(ctx, shown.id)
            if [item.id for item in segment.items] != [shown.items[0].id]:
                ctx.fail(
                    f"asked for item 0 of {shown.id!r}, got {len(segment.items)} items",
                    ref,
                )
            return Result.passed()
    return ctx.skip("no list with at least two items to take a segment of")


@conformance_test("catalog.list.invalid-range")
def list_invalid_range(ctx: Context) -> Result:
    """An invalid range gives an empty list with totalItems set."""
    ref = operation_ref("getContentList")
    full = _issued(ctx)
    start = full.total_items + 1000
    reply = ctx.call(lambda p: p.get_content_list("issued", start, -1))
    empty = ctx.expect_ok(reply, ref)
    if empty.items:
        ctx.fail(f"an invalid range answered with {len(empty.items)} items", ref)
    if empty.total_items != full.total_items:
        ctx.fail(
            f"totalItems is {empty.total_items} for an invalid range but "
            f"{full.total_items} for the whole list",
            ref,
        )
    return Result.passed()


@conformance_test("catalog.list.unknown-id")
def list_unknown_id(ctx: Context) -> Result:
    """A list id the Service does not know is an invalidParameter fault."""
    reply = ctx.call(lambda p: p.get_content_list(_UNKNOWN_LIST, 0, -1))
    ctx.expect_fault(reply, FaultKind.INVALID_PARAMETER)
    return Result.passed()


@conformance_test("catalog.metadata.get")
def metadata_get(ctx: Context) -> Result:
    """getContentMetadata answers schema-valid metadata for a listed book."""
    for shown in _lists(ctx):
        if shown.items:
            _metadata_of(ctx, shown.items[0].id)
            return Result.passed()
    return ctx.skip("no book in the issued or new list to ask for")


@conformance_test("catalog.metadata.unknown-id")
def metadata_unknown_id(ctx: Context) -> Result:
    """A content id the Service does not know is an invalidParameter fault."""
    reply = ctx.call(lambda p: p.get_content_metadata(_UNKNOWN_CONTENT))
    ctx.expect_fault(reply, FaultKind.INVALID_PARAMETER)
    return Result.passed()
