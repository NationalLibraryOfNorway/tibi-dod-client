"""Contract tests for `getQuestions` on every adapter (dynamic menus).

Users, menus and answers are synthetic. The port sends the answers it is given
as they are; which ones to send is up to the caller.
"""

import pytest

from dod.domain.service import Fault, FaultKind, Ok
from dod.domain.v1 import (
    InputQuestion,
    MultipleChoiceQuestion,
    ServicePort,
    UserResponse,
)
from support import SECRET as PASSWORD
from support import Harness
from support.samples import input_question, label, multiple_choice, questions

USER = "synthetic-user"
ROOT = questions(
    multiple_choice("main", "Pick", ("new", "New books"), ("old", "Old books"))
    + input_question("find", "Search for", "TEXT_ALPHANUMERIC", "AUDIO")
)


@pytest.fixture
def port(adapter: Harness) -> ServicePort:
    adapter.add_user(USER, PASSWORD.reveal())
    adapter.declare_operations("DYNAMIC_MENUS")
    adapter.offer_menu(ROOT, answer_to="default")
    port = adapter.open_port()
    port.log_on(USER, PASSWORD)
    return port


def test_the_default_answer_gives_the_root_menu(port: ServicePort) -> None:
    reply = port.get_questions([UserResponse("default")])

    assert isinstance(reply, Ok), reply
    assert reply.schema_violations == ()
    menu, search = reply.value.questions
    assert isinstance(menu, MultipleChoiceQuestion)
    assert (menu.id, menu.label, menu.allow_multiple_selections) == (
        "main",
        "Pick",
        False,
    )
    assert [(c.id, c.label) for c in menu.choices] == [
        ("new", "New books"),
        ("old", "Old books"),
    ]
    assert isinstance(search, InputQuestion)
    assert (search.id, search.input_types) == ("find", ("TEXT_ALPHANUMERIC", "AUDIO"))
    assert reply.value.content_list_ref is None


def test_a_choice_id_with_a_space_is_read_and_sent_as_given(
    adapter: Harness, port: ServicePort
) -> None:
    adapter.offer_menu(
        questions(multiple_choice("main", "Pick", ("two words", "Spaces"))),
        answer_to="other",
        schema_valid=False,
    )
    adapter.offer_menu(
        questions("<contentListRef>list-1</contentListRef>"),
        answer_to="main",
        value="two words",
    )

    menu = port.get_questions([UserResponse("other")])
    reply = port.get_questions([UserResponse("main", "two words")])

    assert isinstance(menu, Ok), menu
    assert isinstance(menu.value.questions[0], MultipleChoiceQuestion)
    assert menu.value.questions[0].choices[0].id == "two words"
    assert isinstance(reply, Ok), reply
    assert reply.value.questions == ()
    assert reply.value.content_list_ref == "list-1"


def test_a_label_is_an_endpoint(adapter: Harness, port: ServicePort) -> None:
    adapter.offer_menu(questions(label("Nothing here")), answer_to="search", value="x")

    reply = port.get_questions([UserResponse("search", "x")])

    assert isinstance(reply, Ok), reply
    assert reply.value.label == "Nothing here"
    assert reply.value.questions == ()


def test_an_unknown_answer_is_an_invalid_parameter(port: ServicePort) -> None:
    reply = port.get_questions([UserResponse("nothing", "x")])

    assert isinstance(reply, Fault)
    assert reply.kind is FaultKind.INVALID_PARAMETER


def test_menus_need_a_session(adapter: Harness) -> None:
    adapter.offer_menu(ROOT, answer_to="default")

    reply = adapter.open_port().get_questions([UserResponse("default")])

    assert isinstance(reply, Fault)
    assert reply.kind is FaultKind.NO_ACTIVE_SESSION
