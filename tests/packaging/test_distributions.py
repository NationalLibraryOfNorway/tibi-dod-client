"""The built distributions, as a release publishes them (issue 45).

The seam is `uv build` on a tagged checkout: the version comes from the git tag
(hatch-vcs), the sdist carries the specification copy and the schemas, and the
wheel carries neither. No network beyond what `uv build` needs for the build backend.
"""

import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TAG = "v7.8.9"

pytestmark = pytest.mark.skipif(
    shutil.which("uv") is None or shutil.which("git") is None,
    reason="needs uv and git",
)


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build a tagged snapshot of the working tree; returns the dist directory."""
    snapshot = tmp_path_factory.mktemp("snapshot")
    files = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")
    for name in filter(None, (f.decode() for f in files)):
        source = ROOT / name
        if source.is_file():
            (snapshot / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, snapshot / name)
    _run(["git", "init", "-q"], snapshot)
    _run(["git", "add", "-A"], snapshot)
    identity = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    _run(
        ["git", *identity, "commit", "-q", "--no-gpg-sign", "-m", "snapshot"], snapshot
    )
    _run(["git", *identity, "tag", "--no-sign", TAG], snapshot)
    _run(["uv", "build", "--out-dir", "dist"], snapshot)
    return snapshot / "dist"


def test_the_version_comes_from_the_git_tag(built: Path) -> None:
    assert sorted(p.name for p in built.iterdir() if p.suffix in {".whl", ".gz"}) == [
        "dod_client-7.8.9-py3-none-any.whl",
        "dod_client-7.8.9.tar.gz",
    ]


def test_the_sdist_carries_the_specification_and_the_schemas(built: Path) -> None:
    with tarfile.open(built / "dod_client-7.8.9.tar.gz") as sdist:
        names = sdist.getnames()
    prefix = "dod_client-7.8.9/"
    assert prefix + "docs/spec/dodp-v1/do-spec-20100402.html" in names
    assert prefix + "schemas/catalog.xml" in names
    assert prefix + "CHANGELOG.md" in names
    assert not [n for n in names if "/.claude/" in n or "/.agents/" in n]


def test_the_wheel_carries_neither_the_specification_nor_the_schemas(
    built: Path,
) -> None:
    with zipfile.ZipFile(built / "dod_client-7.8.9-py3-none-any.whl") as wheel:
        names = wheel.namelist()
    assert any(n.startswith("dod/") for n in names)
    assert not [n for n in names if "spec" in n.split("/")[:1] or "catalog.xml" in n]
    assert not [n for n in names if n.endswith((".xsd", ".wsdl"))]
