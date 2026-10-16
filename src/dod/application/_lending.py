"""Return borrowed content: delete the local copy, then call `returnContent`.

The specification requires a Reading System to delete its copy before it
returns content, so `return_content` does that first, and only the book's own
directory under the data area (ADR 0008). Use cases do not print and do not
exit; they return what happened and presentation renders it. Each Service call
goes through `SessionManager.call` (ADR 0005).
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from dod.application._session import SessionManager
from dod.domain.service import Ok, Reply
from dod.domain.v1 import ContentMetadata


class LocalCopy(StrEnum):
    """What became of the local copy of the book."""

    DELETED = "deleted"
    NONE = "none"
    KEPT = "kept"


@dataclass(frozen=True)
class ReturnRequest:
    """What to return and what to do with the local copy.

    `directory` is the one directory the local copy may live in, or `None` when
    it is not known (only allowed with `keep_local`).
    """

    content_id: str
    directory: Path | None
    keep_local: bool = False
    force: bool = False


@dataclass(frozen=True)
class ReturnReport:
    """Where the return stopped, or the Service's answer to `returnContent`.

    `refusal` is set when `dod` itself declined to go on, before the content
    was returned. `metadata` is the Reply that stopped the return when it was
    not an `Ok`.
    """

    refusal: str | None = None
    metadata: Reply[ContentMetadata] | None = None
    local_copy: LocalCopy | None = None
    returned: Reply[bool] | None = None

    @property
    def succeeded(self) -> bool:
        return (
            self.refusal is None
            and isinstance(self.returned, Ok)
            and self.returned.value is True
        )


def return_content(
    manager: SessionManager,
    request: ReturnRequest,
    confirm_delete: Callable[[Path], bool],
) -> ReturnReport:
    """Return `request.content_id` after dealing with the local copy.

    Unless `force`, the content's `requiresReturn` is read first and `false`
    refuses the return with nothing deleted. An existing local copy is deleted
    only when `confirm_delete` says yes; no is a refusal with nothing sent.
    """
    if not request.force:
        metadata = manager.call(
            lambda port: port.get_content_metadata(request.content_id)
        )
        if not isinstance(metadata, Ok):
            return ReturnReport(metadata=metadata)
        if metadata.value.requires_return is False:
            return ReturnReport(
                refusal=(
                    "the Service says requiresReturn is false for this content, so "
                    "it needs no return; pass --force to call returnContent anyway"
                ),
            )
    local = LocalCopy.KEPT
    if not request.keep_local:
        directory = request.directory
        if directory is None:
            return ReturnReport(refusal="there is no local copy directory to delete")
        if not (directory.is_symlink() or directory.exists()):
            local = LocalCopy.NONE
        else:
            if not confirm_delete(directory):
                return ReturnReport(
                    refusal=f"{directory} was not deleted, so nothing was returned"
                )
            try:
                _delete(directory)
            except OSError as error:
                return ReturnReport(
                    refusal=f"could not delete {directory}: {error.strerror or error}"
                )
            local = LocalCopy.DELETED
    returned = manager.call(lambda port: port.return_content(request.content_id))
    return ReturnReport(local_copy=local, returned=returned)


def _delete(directory: Path) -> None:
    """Delete the directory; a symbolic link is removed, never followed."""
    if directory.is_symlink():
        directory.unlink()
    else:
        shutil.rmtree(directory)
