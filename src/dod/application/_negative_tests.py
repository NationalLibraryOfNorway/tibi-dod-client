"""The negative tests: deliberately invalid requests over a `RawChannel`.

They are explicit (`--only negative` chooses them; an ordinary run never does)
and each one works in an Ephemeral-mode Session of its own: it logs on, goes
through the Initialisation sequence when the test needs it, and registers the
logOff as a cleanup step. A logOff that goes wrong is therefore an ERROR on the
cleanup record, never a FAIL of the test (ADR 0005, ADR 0004).
"""

from __future__ import annotations

from dod.application._conformance import Context, Result, conformance_test
from dod.domain.service import Fault, FaultKind
from dod.domain.v1 import SPEC_REFS, RawChannel, operation_ref

_UNKNOWN_OPERATION = "dodConformanceUnknownOperation"
_VALID_LIST = "<id>issued</id><firstItem>0</firstItem><lastItem>-1</lastItem>"


def _session(ctx: Context, *, initialised: bool) -> RawChannel:
    """A raw channel on a Session of its own, logged off when the test ends."""
    port = ctx.open_port()
    reply = ctx.call(lambda p: p.log_on(ctx.username, ctx.password), on=port)
    ref = operation_ref("logOn")
    if not ctx.expect_ok(reply, ref):
        ctx.fail("logOn answered false for the credentials of this run", ref)
    ctx.cleanup(lambda: ctx.call(lambda p: p.log_off(), on=port))
    if initialised:
        ctx.expect_ok(
            ctx.call(lambda p: p.get_service_attributes(), on=port),
            operation_ref("getServiceAttributes"),
        )
        sent = ctx.call(
            lambda p: p.set_reading_system_attributes(ctx.reading_system), on=port
        )
        if not ctx.expect_ok(sent, operation_ref("setReadingSystemAttributes")):
            ctx.fail(
                "setReadingSystemAttributes answered false",
                operation_ref("setReadingSystemAttributes"),
            )
    session = port.session
    if session is None:
        ctx.fail(
            "logOn succeeded but the Service issued no Session cookie",
            SPEC_REFS["session.initialization"],
        )
    channel = ctx.open_raw()
    channel.resume(session)
    return channel


def _invalid_parameter(ctx: Context, operation: str, body: str) -> Result:
    channel = _session(ctx, initialised=True)
    ctx.expect_fault(
        ctx.send_raw(channel, operation, body), FaultKind.INVALID_PARAMETER
    )
    return Result.passed()


@conformance_test("negative.session.no-session", explicit=True)
def no_session(ctx: Context) -> Result:
    """An operation with no Session at all is a noActiveSession fault."""
    reply = ctx.send_raw(ctx.open_raw(), "getContentList", _VALID_LIST)
    ctx.expect_fault(reply, FaultKind.NO_ACTIVE_SESSION)
    return Result.passed()


@conformance_test("negative.init.operation-before-init", explicit=True)
def operation_before_init(ctx: Context) -> Result:
    """After logOn but before the Initialisation sequence is complete, any other
    operation is an invalidOperation fault."""
    channel = _session(ctx, initialised=False)
    reply = ctx.send_raw(channel, "getContentList", _VALID_LIST)
    ctx.expect_fault(
        reply, FaultKind.INVALID_OPERATION, SPEC_REFS["session.initialization"]
    )
    return Result.passed()


@conformance_test("negative.operation.unknown", explicit=True)
def unknown_operation(ctx: Context) -> Result:
    """An operation the specification does not define is refused with a DODP fault.

    invalidOperation is the natural fault; operationNotSupported is accepted too.
    """
    channel = _session(ctx, initialised=True)
    reply = ctx.send_raw(channel, _UNKNOWN_OPERATION, "")
    if isinstance(reply, Fault) and reply.kind is FaultKind.OPERATION_NOT_SUPPORTED:
        return Result.passed()
    ctx.expect_fault(reply, FaultKind.INVALID_OPERATION)
    return Result.passed()


@conformance_test("negative.parameter.content-list-non-numeric-range", explicit=True)
def content_list_non_numeric_range(ctx: Context) -> Result:
    """A firstItem that is not a number is an invalidParameter fault."""
    return _invalid_parameter(
        ctx,
        "getContentList",
        "<id>issued</id><firstItem>abc</firstItem><lastItem>-1</lastItem>",
    )


@conformance_test("negative.parameter.content-list-empty-id", explicit=True)
def content_list_empty_id(ctx: Context) -> Result:
    """An empty list id is an invalidParameter fault."""
    return _invalid_parameter(
        ctx,
        "getContentList",
        "<id></id><firstItem>0</firstItem><lastItem>-1</lastItem>",
    )


@conformance_test("negative.parameter.content-metadata-empty-id", explicit=True)
def content_metadata_empty_id(ctx: Context) -> Result:
    """An empty content id is an invalidParameter fault."""
    return _invalid_parameter(ctx, "getContentMetadata", "<contentID></contentID>")
