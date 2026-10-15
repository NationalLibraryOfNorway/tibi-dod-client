"""The password type hides its value everywhere it could be printed."""

from dataclasses import dataclass

from dod.domain.service import Password


@dataclass
class Credentials:
    username: str
    password: Password


def test_the_value_is_hidden_in_repr_str_and_containing_dataclasses() -> None:
    credentials = Credentials("synthetic-user", Password("synthetic-secret"))

    for text in (
        repr(credentials.password),
        str(credentials.password),
        repr(credentials),
    ):
        assert "synthetic-secret" not in text


def test_the_value_is_available_where_it_goes_on_the_wire() -> None:
    assert Password("synthetic-secret").reveal() == "synthetic-secret"
