"""Plain GET of a document: no credentials, no cookies, no redirects."""

from __future__ import annotations

import httpx

from dod.application import FetchResponse
from dod.domain.service import TransportError

_TIMEOUT_SECONDS = 15.0


class HttpFetcher:
    """The `Fetcher` seam over HTTPX.

    A fresh client per request keeps cookies from one request out of the next,
    and `trust_env=False` keeps `.netrc` credentials out of it. Redirects are
    reported to the caller, which decides whether they stay on the same host.
    """

    def __init__(self, *, timeout: float = _TIMEOUT_SECONDS) -> None:
        self._timeout = timeout

    def get(self, url: str, *, max_bytes: int) -> FetchResponse:
        try:
            with (
                httpx.Client(
                    timeout=self._timeout, follow_redirects=False, trust_env=False
                ) as client,
                client.stream("GET", url) as response,
            ):
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise TransportError(
                            f"the answer is larger than {max_bytes} bytes"
                        )
                    chunks.append(chunk)
                headers = {
                    name.lower(): value for name, value in response.headers.items()
                }
                return FetchResponse(
                    url=url,
                    status=response.status_code,
                    headers=headers,
                    body=b"".join(chunks),
                )
        except httpx.HTTPError as error:
            raise TransportError(
                f"no answer from {url}: {error or type(error).__name__}"
            ) from error
