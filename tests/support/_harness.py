"""What the contract tests need from a fake Service, whichever adapter is used."""

from collections.abc import Sequence
from typing import Protocol

from dod.domain.v1 import (
    Announcement,
    ContentList,
    ContentMetadata,
    ContentResource,
    ServicePort,
)


class Harness(Protocol):
    """A fresh fake Service plus a way to open a `ServicePort` towards it."""

    def add_user(self, username: str, password: str) -> None: ...

    def inject_fault(self, operation: str, kind: str, reason: str) -> None:
        """Make the next call of `operation` answer with the DODP fault `kind`."""
        ...

    def inject_deviation(self, operation: str) -> None:
        """Make the next call of `operation` answer contrary to the specification."""
        ...

    def inject_false(self, operation: str) -> None:
        """Make the next call of `operation` answer a result of `false`."""
        ...

    def offer_announcements(self, *announcements: Announcement) -> None:
        """Publish announcements, and let the Service declare the operations."""
        ...

    def declare_operations(self, *tokens: str) -> None:
        """Declare optional operations in `supportedOptionalOperations`."""
        ...

    def offer_bookmarks(
        self, content_id: str, bookmark_set: str, *, schema_valid: bool = True
    ) -> None:
        """Store the bookmark set of a book (`schema_valid=False`: it breaks the
        schema on purpose and is answered as it is)."""
        ...

    def offer_key_exchange(self, key_name: str, key_exchange: str) -> None:
        """Answer `getKeyExchangeObject` for `key_name` with this element."""
        ...

    def offer_catalog(
        self, lists: Sequence[ContentList], metadata: Sequence[ContentMetadata]
    ) -> None:
        """Publish content lists (by id) and book metadata (by identifier)."""
        ...

    def offer_resources(
        self,
        content_id: str,
        resources: Sequence[ContentResource],
        *,
        issued: bool = True,
    ) -> None:
        """Publish the files of a book; unless `issued` they are not available."""
        ...

    def offer_file(self, path: str, body: bytes) -> None:
        """Serve `body` at `file_url(path)`."""
        ...

    def file_url(self, path: str) -> str:
        """The absolute address of a file offered with `offer_file`."""
        ...

    def open_port(self) -> ServicePort: ...
