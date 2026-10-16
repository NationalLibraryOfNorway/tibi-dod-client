"""The one `mask` function every renderer uses (ADR 0007); secrets are synthetic."""

import re

from dod.domain.service import Exchange
from dod.presentation import MaskPolicy, mask, mask_url

PASSWORD = "synthetic-password"
COOKIE = "synthetic-cookie-value"
FINGERPRINT = re.compile(r"\*\*\*\[[0-9a-f]{6}\]")


def exchange(**overrides: object) -> Exchange:
    fields: dict[str, object] = {
        "method": "POST",
        "url": "https://dod.example.org/service",
        "request_headers": (
            ("Content-Type", "text/xml"),
            ("Cookie", f"session={COOKIE}; other=second"),
            ("Authorization", "Basic c3ludGhldGljOnNlY3JldA=="),
            ("Proxy-Authorization", "Bearer synthetic-proxy-token"),
        ),
        "request_body": (
            '<?xml version="1.0"?><soap:Envelope xmlns:soap="x"><soap:Body>'
            '<logOn xmlns="y"><username>synthetic-user</username>'
            f"<password>{PASSWORD}</password></logOn></soap:Body></soap:Envelope>"
        ),
        "status": 200,
        "response_headers": (
            ("Set-Cookie", f"session={COOKIE}; Path=/; HttpOnly"),
            ("Location", "https://user:pw-secret@dod.example.org/next?token=abc"),
        ),
        "response_body": "<ok/>",
        "duration_seconds": 0.5,
    }
    fields.update(overrides)
    return Exchange(**fields)  # type: ignore[arg-type]


def headers(masked: Exchange) -> dict[str, str]:
    return dict(masked.request_headers) | dict(masked.response_headers)


def test_the_logon_password_is_masked_but_the_rest_of_the_message_is_kept() -> None:
    masked = mask(exchange())

    assert PASSWORD not in masked.request_body
    assert "<username>synthetic-user</username>" in masked.request_body
    assert FINGERPRINT.search(masked.request_body)


def test_cookie_and_authorization_values_are_masked_names_are_kept() -> None:
    result = headers(mask(exchange()))

    assert result["Content-Type"] == "text/xml"
    assert result["Cookie"].startswith("session=***[")
    assert "; other=***[" in result["Cookie"]
    assert result["Set-Cookie"].startswith("session=***[")
    assert result["Set-Cookie"].endswith("; Path=/; HttpOnly")
    assert result["Authorization"].startswith("Basic ***[")
    assert result["Proxy-Authorization"].startswith("Bearer ***[")
    assert COOKIE not in repr(result)
    assert "c3ludGhldGljOnNlY3JldA==" not in repr(result)
    assert "synthetic-proxy-token" not in repr(result)


def test_header_names_are_matched_without_regard_to_case() -> None:
    masked = mask(exchange(request_headers=(("cOOkie", f"a={COOKIE}"),)))

    assert COOKIE not in repr(masked)


def test_the_same_secret_gets_the_same_fingerprint_so_sessions_can_be_compared() -> (
    None
):
    result = headers(mask(exchange()))

    request_print = FINGERPRINT.search(result["Cookie"])
    response_print = FINGERPRINT.search(result["Set-Cookie"])
    assert request_print and response_print
    assert request_print.group() == response_print.group()


def test_different_secrets_get_different_fingerprints() -> None:
    first = mask(exchange(request_headers=(("Cookie", "a=one-value"),)))
    second = mask(exchange(request_headers=(("Cookie", "a=another-value"),)))

    assert first.request_headers != second.request_headers


def test_userinfo_and_credential_like_query_parameters_in_urls_are_masked() -> None:
    masked = mask(
        exchange(url="https://alice:pw-secret@dod.example.org/s?id=7&apiKey=k-secret")
    )

    assert "alice" not in masked.url
    assert "pw-secret" not in masked.url
    assert "k-secret" not in masked.url
    assert masked.url.startswith("https://***[")
    assert "@dod.example.org/s?id=7&apiKey=***[" in masked.url


def test_a_url_without_secrets_is_unchanged() -> None:
    assert (
        mask_url("https://dod.example.org/s?id=7") == "https://dod.example.org/s?id=7"
    )


def test_urls_in_response_headers_are_masked() -> None:
    result = headers(mask(exchange()))

    assert "pw-secret" not in result["Location"]
    assert "token=abc" not in result["Location"]


def test_unmask_shows_cookies_and_headers_but_not_the_password() -> None:
    masked = mask(exchange(), MaskPolicy(unmask=True))

    assert COOKIE in headers(masked)["Cookie"]
    assert PASSWORD not in masked.request_body


def test_unmask_password_shows_only_the_password() -> None:
    masked = mask(exchange(), MaskPolicy(unmask_password=True))

    assert PASSWORD in masked.request_body
    assert COOKIE not in headers(masked)["Cookie"]


def test_unmasked_secrets_are_wrapped_in_removable_highlight_markers() -> None:
    masked = mask(exchange(), MaskPolicy(unmask_password=True, unmask=True))

    plain = masked.request_body
    for marker in (HIGHLIGHT_START, HIGHLIGHT_END):
        plain = plain.replace(marker, "")
    assert f"<password>{PASSWORD}</password>" in plain


HIGHLIGHT_START = ""
HIGHLIGHT_END = ""


def test_userinfo_of_an_address_inside_a_body_is_masked() -> None:
    body = (
        '<resources><resource uri="https://dg-user:dg-secret@cdn.example.net/a.mp3" '
        'size="1"/><resource uri="files/b.mp3" size="2"/></resources>'
    )

    masked = mask(exchange(response_body=body))

    assert "dg-secret" not in masked.response_body
    assert "dg-user" not in masked.response_body
    assert "@cdn.example.net/a.mp3" in masked.response_body
    assert 'uri="files/b.mp3"' in masked.response_body
