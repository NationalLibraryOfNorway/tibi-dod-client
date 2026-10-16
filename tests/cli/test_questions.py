"""`dod questions` through the CLI boundary (ADR 0003, 0005, 0008).

Subprocess tests run the installed console script against the fake Service on
localhost, with `DOD_STATE_DIR` in a temporary directory. The password is the
first line of stdin. Users and menus are synthetic; nothing about the menus is
the shape of a real backend.
"""

import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from support import FakeService, run_dod
from support.samples import input_question, label, multiple_choice, questions

USER = "synthetic-user"
PASSWORD = "synthetic-secret"
ROOT = questions(
    multiple_choice("main", "Pick one", ("new", "New books"), ("old", "Old books"))
    + input_question("find", "Search for", "TEXT_ALPHANUMERIC", "AUDIO")
    + input_question("voice", "Say a title", "AUDIO")
)


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD)
    fake.offer_menu(ROOT, answer_to="default")
    yield fake
    fake.stop()


def dod(  # type: ignore[no-untyped-def]
    service: FakeService, tmp_path: Path, *args: str
):
    """Run `dod` against the fake Service, in an Environment named `test`."""
    config = tmp_path / "config.toml"
    config.write_text(
        f'[environments.test]\nurl = "{service.url}"\ninsecure = true\n'
        f'username = "{USER}"\n',
        encoding="utf-8",
    )
    if sys.platform != "win32":
        config.chmod(0o600)
    return run_dod(
        *args,
        "--env",
        "test",
        "--config",
        str(config),
        "--password-stdin",
        stdin=PASSWORD + "\n",
        env={"DOD_STATE_DIR": str(tmp_path / "state")},
    )


def sent(service: FakeService) -> str:
    """The `userResponses` of the last getQuestions request."""
    bodies = [
        r.body.decode() for r in service.requests if r.operation == "getQuestions"
    ]
    match = re.search(r"<userResponses.*</userResponses>", bodies[-1])
    assert match is not None
    return match.group(0)


# -- the root menu ---------------------------------------------------------------


def test_questions_sends_default_and_shows_every_question_and_choice_copyably(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "questions")

    assert result.returncode == 0, result.stderr
    assert 'questionID="default"' in sent(service)
    assert "value=" not in sent(service)
    lines = result.stdout.splitlines()
    assert "question main: Pick one" in lines
    assert any(re.fullmatch(r"\s+answer main new\s+# New books", x) for x in lines)
    assert any(re.fullmatch(r"\s+answer main old\s+# Old books", x) for x in lines)
    assert any(x.startswith("input question find: Search for") for x in lines)
    assert any(re.fullmatch(r"\s+answer find <text>", x) for x in lines)


def test_an_input_question_needing_undeclared_input_is_shown_but_not_answerable(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "questions")

    voice = [x for x in result.stdout.splitlines() if "voice" in x]
    assert voice, result.stdout
    assert "cannot be answered" in voice[0]
    assert "AUDIO" in voice[0]
    assert not any(re.search(r"answer voice", x) for x in result.stdout.splitlines())


def test_dod_declares_only_the_input_types_it_supports(
    service: FakeService, tmp_path: Path
) -> None:
    dod(service, tmp_path, "questions")

    declared = [
        r.body.decode()
        for r in service.requests
        if r.operation == "setReadingSystemAttributes"
    ][-1]
    assert 'type="TEXT_ALPHANUMERIC"' in declared
    assert 'type="AUDIO"' not in declared


def test_the_command_can_be_called_without_dynamic_menus_being_declared(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "questions")

    assert "DYNAMIC_MENUS" not in service.service_attributes_xml
    assert result.returncode == 0, result.stderr


# -- answer, search, back --------------------------------------------------------


def test_answer_sends_exactly_one_question_id_and_value(
    service: FakeService, tmp_path: Path
) -> None:
    service.offer_menu(
        questions(multiple_choice("sub", "Sub", ("x", "X"))),
        answer_to="main",
        value="new",
    )

    result = dod(service, tmp_path, "questions", "answer", "main", "new")

    assert result.returncode == 0, result.stderr
    assert sent(service).count("<userResponse ") == 1
    assert 'questionID="main"' in sent(service)
    assert 'value="new"' in sent(service)
    assert "question sub: Sub" in result.stdout


def test_a_value_with_spaces_is_shown_quoted_and_sent_as_given(
    service: FakeService, tmp_path: Path
) -> None:
    service.offer_menu(
        questions(multiple_choice("main", "Pick", ("two words", "Spaces"))),
        answer_to="other",
        value="x",
        schema_valid=False,
    )
    service.offer_menu(questions(label("Done")), answer_to="main", value="two words")

    menu = dod(service, tmp_path, "questions", "answer", "other", "x")
    result = dod(service, tmp_path, "questions", "answer", "main", "two words")

    assert menu.returncode == 0, menu.stderr
    assert "answer main 'two words'" in menu.stdout
    assert result.returncode == 0, result.stderr
    assert 'value="two words"' in sent(service)
    assert "label: Done" in result.stdout


def test_a_content_list_ref_is_an_endpoint_that_dod_list_follows(
    service: FakeService, tmp_path: Path
) -> None:
    service.offer_menu(
        questions("<contentListRef>list-1</contentListRef>"),
        answer_to="main",
        value="new",
    )

    result = dod(service, tmp_path, "questions", "answer", "main", "new")

    assert result.returncode == 0, result.stderr
    assert "contentListRef: list-1" in result.stdout
    assert "dod list --id list-1" in result.stdout


def test_a_label_endpoint_is_shown_as_text(
    service: FakeService, tmp_path: Path
) -> None:
    service.offer_menu(questions(label("Nothing found")), answer_to="main", value="old")

    result = dod(service, tmp_path, "questions", "answer", "main", "old")

    assert result.returncode == 0, result.stderr
    assert "label: Nothing found" in result.stdout


def test_search_sends_the_reserved_search_id_with_the_text_as_value(
    service: FakeService, tmp_path: Path
) -> None:
    service.offer_menu(questions(label("2 hits")), answer_to="search", value="the text")

    result = dod(service, tmp_path, "questions", "search", "the text")

    assert result.returncode == 0, result.stderr
    assert 'questionID="search"' in sent(service)
    assert 'value="the text"' in sent(service)


def test_search_without_text_sends_no_value(
    service: FakeService, tmp_path: Path
) -> None:
    service.offer_menu(questions(label("Type something")), answer_to="search")

    result = dod(service, tmp_path, "questions", "search")

    assert result.returncode == 0, result.stderr
    assert 'questionID="search"' in sent(service)
    assert "value=" not in sent(service)


def test_back_sends_the_reserved_back_id_and_shows_the_answer_unchanged(
    service: FakeService, tmp_path: Path
) -> None:
    service.offer_menu(questions(label("Up")), answer_to="back")

    result = dod(service, tmp_path, "questions", "back")

    assert result.returncode == 0, result.stderr
    assert 'questionID="back"' in sent(service)
    assert "value=" not in sent(service)
    assert "label: Up" in result.stdout


def test_a_fault_is_shown_as_it_came_with_exit_1(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "questions", "back")

    assert result.returncode == 1
    assert "getQuestions: fault invalidParameter: unknown question" in result.stdout


def test_a_menu_that_breaks_the_schema_is_still_shown_with_a_finding(
    service: FakeService, tmp_path: Path
) -> None:
    service.offer_menu(
        questions(multiple_choice("main", "Pick", ("two words", "Spaces"))),
        answer_to="back",
        schema_valid=False,
    )

    result = dod(service, tmp_path, "questions", "back")

    assert result.returncode == 0, result.stderr
    assert "answer main 'two words'" in result.stdout
    assert "NMTOKEN" in result.stderr


# -- formats and untrusted text ---------------------------------------------------


def test_json_describes_questions_choices_and_what_dod_can_answer(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "questions", "--format", "json")

    document = json.loads(result.stdout)
    assert document["result"] == "ok"
    main, find, voice = document["questions"]["questions"]
    assert main["id"] == "main"
    assert main["choices"][0] == {"id": "new", "label": "New books", "lang": "en"}
    assert find["input_types"] == ["TEXT_ALPHANUMERIC", "AUDIO"]
    assert (main["answerable"], find["answerable"], voice["answerable"]) == (
        True,
        True,
        False,
    )
    assert document["questions"]["content_list_ref"] is None


def test_xml_is_the_raw_response(service: FakeService, tmp_path: Path) -> None:
    result = dod(service, tmp_path, "questions", "--format", "xml")

    assert "<getQuestionsResponse" in result.stdout


def test_control_characters_of_the_service_never_reach_the_terminal(
    service: FakeService, tmp_path: Path
) -> None:
    service.offer_menu(
        questions(multiple_choice("main", "a&#x9b;31mb", ("new", "c&#x9b;[2Jd"))),
        answer_to="back",
    )

    result = dod(service, tmp_path, "questions", "back")

    assert not re.search(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", result.stdout)
    assert "a 31mb" in result.stdout


# -- help ----------------------------------------------------------------------


def test_help_lists_the_subcommands_and_the_reserved_ids() -> None:
    result = run_dod("questions", "--help")

    assert result.returncode == 0, result.stderr
    text = " ".join(result.stdout.split())
    for command in ("answer", "search", "back"):
        assert re.search(rf"\b{command}\b", text)
    assert "DYNAMIC_MENUS" in text and "default" in text
