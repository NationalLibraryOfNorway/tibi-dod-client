"""`dod attributes ...` and the declared Reading System, through the CLI boundary.

Subprocess tests run the installed console script against the fake Service on
localhost, with `DOD_STATE_DIR` in a temporary directory. Users and passwords
are synthetic.
"""

import json
from collections.abc import Iterator
from importlib.metadata import version
from pathlib import Path

import pytest
from lxml import etree

from support import PASSWORD, FakeService, run_dod

USER = "synthetic-user"
NS = {"d": "http://www.daisy.org/ns/daisy-online/"}
INIT = ["logOn", "getServiceAttributes", "setReadingSystemAttributes"]

CUSTOM = """\
<readingSystemAttributes xmlns="http://www.daisy.org/ns/daisy-online/">
  <manufacturer>Synthetic Maker</manufacturer>
  <model>custom-model</model>
  <version>9.9</version>
  <config>
    <supportsMultipleSelections>true</supportsMultipleSelections>
    <preferredUILanguage>nb</preferredUILanguage>
    <supportedContentFormats>
      <contentFormat>EPUB 3</contentFormat>
    </supportedContentFormats>
    <supportedContentProtectionFormats/>
    <supportedMimeTypes><mimeType type="audio/ogg"/></supportedMimeTypes>
    <supportedInputTypes><input type="AUDIO"/></supportedInputTypes>
    <requiresAudioLabels>true</requiresAudioLabels>
  </config>
</readingSystemAttributes>
"""


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD)
    yield fake
    fake.stop()


def dod(  # type: ignore[no-untyped-def]
    service: FakeService, state: Path, *args: str, env: dict[str, str] | None = None
):
    return run_dod(
        *args,
        "--url",
        service.url,
        "--username",
        USER,
        "--password-stdin",
        "--insecure",
        stdin=PASSWORD + "\n",
        env={"DOD_STATE_DIR": str(state)} | (env or {}),
    )


def operations(service: FakeService) -> list[str | None]:
    return [request.operation for request in service.requests]


def declared(service: FakeService, index: int = -1) -> etree._Element:
    sent = [r for r in service.requests if r.operation == "setReadingSystemAttributes"]
    body = etree.fromstring(sent[index].body)
    found = body.find(".//d:readingSystemAttributes", NS)
    assert found is not None
    return found


def texts(element: etree._Element, path: str) -> list[str | None]:
    return [found.text for found in element.findall(path, NS)]


def test_attributes_service_shows_what_the_service_says(
    service: FakeService, tmp_path: Path
) -> None:
    dod(service, tmp_path, "logon")
    service.requests.clear()

    result = dod(service, tmp_path, "attributes", "service")

    assert result.returncode == 0, result.stderr
    assert operations(service) == ["getServiceAttributes"]
    assert "service_id: synthetic-service" in result.stdout.splitlines()
    assert "supports_search: false" in result.stdout.splitlines()
    assert "supported_content_selection_methods: BROWSE" in result.stdout.splitlines()


def test_attributes_service_as_json_and_as_the_raw_response(
    service: FakeService, tmp_path: Path
) -> None:
    dod(service, tmp_path, "logon")

    as_json = dod(service, tmp_path, "attributes", "service", "--format", "json")
    as_xml = dod(service, tmp_path, "attributes", "service", "--format", "xml")

    assert json.loads(as_json.stdout)["service_id"] == "synthetic-service"
    assert "<serviceAttributes" in as_xml.stdout


def test_attributes_service_passes_a_fault_on_as_it_is(
    service: FakeService, tmp_path: Path
) -> None:
    dod(service, tmp_path, "logon")
    service.inject_fault("getServiceAttributes", "internalServerError", "synthetic")

    result = dod(service, tmp_path, "attributes", "service")

    assert result.returncode == 1
    assert "fault internalServerError: synthetic" in result.stdout


def test_attributes_service_with_no_stored_session_logs_on_first(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "attributes", "service")

    assert result.returncode == 0, result.stderr
    assert operations(service) == [*INIT, "getServiceAttributes"]


def test_attributes_service_without_credentials_asks_for_a_logon(
    service: FakeService, tmp_path: Path
) -> None:
    result = run_dod(
        "attributes",
        "service",
        "--url",
        service.url,
        "--username",
        USER,
        "--insecure",
        env={"DOD_STATE_DIR": str(tmp_path)},
    )

    assert result.returncode == 2
    assert "dod logon" in result.stderr
    assert operations(service) == []


def test_attributes_service_in_ephemeral_mode_logs_on_and_off(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "attributes", "service", "--no-session")

    assert result.returncode == 0, result.stderr
    assert operations(service) == [*INIT, "getServiceAttributes", "logOff"]


def test_the_default_declaration_names_formats_types_and_the_package(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(service, tmp_path, "attributes", "reading-system")

    assert result.returncode == 0, result.stderr
    sent = declared(service)
    assert sent.findtext("d:manufacturer", namespaces=NS)
    assert sent.findtext("d:version", namespaces=NS) == version("dod-client")
    assert texts(sent, ".//d:contentFormat") == ["Daisy 2.02", "EPUB 3"]
    mime = [m.get("type") for m in sent.findall(".//d:mimeType", NS)]
    assert mime == ["audio/mpeg", "audio/wav"]
    inputs = [i.get("type") for i in sent.findall(".//d:input", NS)]
    assert inputs == ["TEXT_NUMERIC", "TEXT_ALPHANUMERIC"]


def test_attributes_reading_system_shows_the_reply(
    service: FakeService, tmp_path: Path
) -> None:
    dod(service, tmp_path, "logon")
    service.requests.clear()

    result = dod(service, tmp_path, "attributes", "reading-system")

    assert operations(service) == ["setReadingSystemAttributes"]
    assert result.stdout.splitlines()[0] == "setReadingSystemAttributes: ok"


def test_attributes_reading_system_passes_a_fault_on_as_it_is(
    service: FakeService, tmp_path: Path
) -> None:
    dod(service, tmp_path, "logon")
    service.inject_fault(
        "setReadingSystemAttributes", "invalidParameter", "synthetic reason"
    )

    result = dod(service, tmp_path, "attributes", "reading-system")

    assert result.returncode == 1
    assert (
        "setReadingSystemAttributes: fault invalidParameter: synthetic reason"
        in result.stdout
    )


def test_a_file_replaces_the_whole_declaration(
    service: FakeService, tmp_path: Path
) -> None:
    declaration = tmp_path / "rs.xml"
    declaration.write_text(CUSTOM, encoding="utf-8")

    result = dod(
        service, tmp_path, "attributes", "reading-system", "--file", str(declaration)
    )

    assert result.returncode == 0, result.stderr
    sent = declared(service)
    assert sent.findtext("d:model", namespaces=NS) == "custom-model"
    assert texts(sent, ".//d:contentFormat") == ["EPUB 3"]
    assert [m.get("type") for m in sent.findall(".//d:mimeType", NS)] == ["audio/ogg"]


def test_a_file_that_breaks_the_schemas_is_refused_before_anything_is_sent(
    service: FakeService, tmp_path: Path
) -> None:
    declaration = tmp_path / "rs.xml"
    declaration.write_text(CUSTOM.replace("<model>custom-model</model>", ""))

    result = dod(
        service, tmp_path, "attributes", "reading-system", "--file", str(declaration)
    )

    assert result.returncode == 2
    assert "rs.xml" in result.stderr
    assert operations(service) == []


def test_a_missing_file_is_refused_before_anything_is_sent(
    service: FakeService, tmp_path: Path
) -> None:
    result = dod(
        service,
        tmp_path,
        "attributes",
        "reading-system",
        "--file",
        str(tmp_path / "missing.xml"),
    )

    assert result.returncode == 2
    assert "missing.xml" in result.stderr
    assert operations(service) == []


def write_config(
    service: FakeService, directory: Path, extra: str = 'reading_system = "rs.xml"'
) -> Path:
    config = directory / "config.toml"
    config.write_text(
        f'[environments.test]\nurl = "{service.url}"\ninsecure = true\n'
        f'username = "{USER}"\n{extra}\n',
        encoding="utf-8",
    )
    config.chmod(0o600)
    return config


def test_the_environment_key_changes_what_logon_declares(
    service: FakeService, tmp_path: Path
) -> None:
    (tmp_path / "rs.xml").write_text(CUSTOM, encoding="utf-8")
    config = write_config(service, tmp_path)

    result = run_dod(
        "logon",
        "--config",
        str(config),
        "--env",
        "test",
        "--password-stdin",
        stdin=PASSWORD + "\n",
        env={"DOD_STATE_DIR": str(tmp_path / "state")},
    )

    assert result.returncode == 0, result.stderr
    assert declared(service).findtext("d:model", namespaces=NS) == "custom-model"


def test_a_file_beats_the_environment_key(service: FakeService, tmp_path: Path) -> None:
    (tmp_path / "rs.xml").write_text(CUSTOM, encoding="utf-8")
    other = tmp_path / "other.xml"
    other.write_text(CUSTOM.replace("custom-model", "other-model"), encoding="utf-8")
    config = write_config(service, tmp_path)

    result = run_dod(
        "attributes",
        "reading-system",
        "--file",
        str(other),
        "--config",
        str(config),
        "--env",
        "test",
        "--password-stdin",
        stdin=PASSWORD + "\n",
        env={"DOD_STATE_DIR": str(tmp_path / "state")},
    )

    assert result.returncode == 0, result.stderr
    assert declared(service).findtext("d:model", namespaces=NS) == "other-model"


def test_config_show_names_the_reading_system_file(
    service: FakeService, tmp_path: Path
) -> None:
    config = write_config(service, tmp_path)

    result = run_dod("config", "show", "--config", str(config), "--env", "test")

    assert result.returncode == 0, result.stderr
    assert "reading_system = " in result.stdout
    assert "rs.xml" in result.stdout


def test_the_environment_key_must_be_a_string(
    service: FakeService, tmp_path: Path
) -> None:
    config = write_config(service, tmp_path, "reading_system = 3")

    result = run_dod("config", "check", "--config", str(config))

    assert result.returncode == 2
    assert "environments.test.reading_system" in result.stderr
