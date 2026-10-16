"""The `bookmarks`, `key-exchange` and `questions` families: the optional operations.

Each test gates on `supportedOptionalOperations` through `Context.optional`:
an operation that is neither declared nor supported is SKIP, one that is
declared but refused is FAIL. The commands themselves can always be called.
The only State-changing test, the round trip, writes back exactly the set it
read (read, then write, then read again), so the stored set is left as found.
The key exchange test sends no real key name and reads no key material.
"""

from __future__ import annotations

from dod.application._conformance import Context, Result, conformance_test
from dod.domain.service import FaultKind, Ok
from dod.domain.v1 import SPEC_REFS, BookmarkSet, UserResponse, operation_ref

_UNKNOWN_CONTENT = "dod-conformance-unknown-content"
_UNKNOWN_KEY = "dod-conformance-unknown-key"
_BOOKMARK_SET = SPEC_REFS["type.bookmarkSet"]


def _a_book(ctx: Context) -> str:
    """`--content-id`, else the first book on the shelf or the `new` list."""
    if ctx.target.content_id is not None:
        return ctx.target.content_id
    for list_id in ("issued", "new"):
        reply = ctx.call(lambda p: p.get_content_list(list_id, 0, 0))  # noqa: B023
        if isinstance(reply, Ok) and reply.value.items:
            return reply.value.items[0].id
    ctx.skip("no --content-id and no book on the issued or new list to ask about")


def _read(ctx: Context, content_id: str) -> BookmarkSet:
    reply = ctx.optional(
        "GET_BOOKMARKS",
        lambda p: p.get_bookmarks(content_id),
        operation_ref("getBookmarks"),
    )
    return ctx.expect_ok(reply, _BOOKMARK_SET)


def _summary(shown: BookmarkSet) -> tuple[object, ...]:
    """What a round trip must keep: everything but the formatting of the XML."""
    return (shown.title, shown.uid, shown.lastmark, shown.bookmarks, shown.hilites)


@conformance_test("bookmarks.get.known")
def bookmarks_get_known(ctx: Context) -> Result:
    """getBookmarks answers a schema-valid bookmarkSet for a known book."""
    _read(ctx, _a_book(ctx))
    return Result.passed()


@conformance_test("bookmarks.get.unknown-id")
def bookmarks_get_unknown_id(ctx: Context) -> Result:
    """getBookmarks for content the Service does not know is invalidParameter."""
    reply = ctx.optional(
        "GET_BOOKMARKS",
        lambda p: p.get_bookmarks(_UNKNOWN_CONTENT),
        operation_ref("getBookmarks"),
    )
    ctx.expect_fault(reply, FaultKind.INVALID_PARAMETER)
    return Result.passed()


@conformance_test("bookmarks.set.round-trip", state_changing=True)
def bookmarks_set_round_trip(ctx: Context) -> Result:
    """setBookmarks stores the set it is given: write back what was read.

    Only the content named by `--content-id` is used. The set is read, sent back
    as it is, and read again; title, uid, lastmark and the number of bookmarks
    and highlights must be the same.
    """
    content_id = ctx.target.content_id
    if content_id is None:
        ctx.skip("no --content-id: the round trip never chooses content itself")
    original = _read(ctx, content_id)
    ref = operation_ref("setBookmarks")
    stored = ctx.optional(
        "SET_BOOKMARKS", lambda p: p.set_bookmarks(content_id, original.xml), ref
    )
    if not ctx.expect_ok(stored, ref):
        ctx.fail("setBookmarks answered false for the set that was read", ref)
    again = _read(ctx, content_id)
    if _summary(again) != _summary(original):
        ctx.fail("the set read back differs from the set that was stored", ref)
    return Result.passed()


@conformance_test("key-exchange.unknown-key")
def key_exchange_unknown_key(ctx: Context) -> Result:
    """getKeyExchangeObject for a key the Service does not have is invalidParameter."""
    reply = ctx.optional(
        "PDTB2_KEY_PROVISION",
        lambda p: p.get_key_exchange_object(_UNKNOWN_KEY),
        operation_ref("getKeyExchangeObject"),
    )
    ctx.expect_fault(reply, FaultKind.INVALID_PARAMETER)
    return Result.passed()


@conformance_test("questions.default")
def questions_default(ctx: Context) -> Result:
    """getQuestions answers the reserved `default` with a schema-valid root menu.

    Only `default` is sent: it is the one answer every Service with menus has to
    understand. Which questions follow, and what `back` does, is up to the Service.
    """
    reply = ctx.optional(
        "DYNAMIC_MENUS",
        lambda p: p.get_questions([UserResponse("default")]),
        operation_ref("getQuestions"),
    )
    ctx.expect_ok(reply, SPEC_REFS["type.questions"])
    return Result.passed()
