"""The `tach` contract rejects imports that break the layering (ADR 0003).

Each case copies the real `src` tree and `tach.toml` into a scratch directory,
adds one offending module and runs `tach check` on the copy.
"""

import os
import shutil
import subprocess
import sysconfig
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def tach_check(project: Path) -> subprocess.CompletedProcess[str]:
    scripts = sysconfig.get_path("scripts")
    executable = shutil.which("tach", path=scripts)
    assert executable is not None, f"'tach' not found in {scripts}"
    return subprocess.run(
        [executable, "check"],
        cwd=project,
        env={**os.environ, "PYTHONUTF8": "1"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    shutil.copytree(
        REPO / "src",
        tmp_path / "src",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy(REPO / "tach.toml", tmp_path / "tach.toml")
    return tmp_path


def add_module(project: Path, relative: str, source: str) -> None:
    path = project / "src" / "dod" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_the_unmodified_tree_passes(project: Path) -> None:
    result = tach_check(project)

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("relative", "source", "expected"),
    [
        pytest.param(
            "domain/service/offender.py",
            "import dod.domain.v1\n",
            "'dod.domain.service' cannot depend on 'dod.domain.v1'",
            id="service-kernel-imports-v1",
        ),
        pytest.param(
            "domain/v1/offender.py",
            "import dod.application\n",
            "Layer 'domain' ('dod.domain.v1') is lower than layer 'application'",
            id="domain-imports-application",
        ),
        pytest.param(
            "application/offender.py",
            "import dod.infrastructure\n",
            "Layer 'application' ('dod.application') is lower than layer "
            "'infrastructure'",
            id="application-imports-infrastructure",
        ),
        pytest.param(
            "presentation/offender.py",
            "import dod.infrastructure\n",
            "'dod.presentation' cannot depend on 'dod.infrastructure'",
            id="presentation-imports-infrastructure",
        ),
        pytest.param(
            "infrastructure/offender.py",
            "import dod.presentation\n",
            "Layer 'infrastructure' ('dod.infrastructure') is lower than layer "
            "'presentation'",
            id="infrastructure-imports-presentation",
        ),
        pytest.param(
            "presentation/offender.py",
            "from dod.main import main\n",
            "is lower than layer 'main'",
            id="layer-imports-composition-root",
        ),
    ],
)
def test_imports_against_the_layer_order_are_rejected(
    project: Path, relative: str, source: str, expected: str
) -> None:
    add_module(project, relative, source)

    result = tach_check(project)

    assert result.returncode != 0
    assert expected in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("target", "imported"),
    [
        pytest.param("domain.service", "dod.domain.service.reply", id="service"),
        pytest.param("domain.v1", "dod.domain.v1.reply", id="v1"),
        pytest.param("application", "dod.application.reply", id="application"),
    ],
)
def test_imports_past_a_module_interface_are_rejected(
    project: Path, target: str, imported: str
) -> None:
    add_module(project, f"{target.replace('.', '/')}/reply.py", "Reply = object\n")
    add_module(project, "infrastructure/offender.py", f"from {imported} import Reply\n")

    result = tach_check(project)

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert f"is not part of the public interface for 'dod.{target}'" in output


def test_private_names_of_a_module_are_not_part_of_its_interface(
    project: Path,
) -> None:
    add_module(project, "domain/v1/__init__.py", "_registry: list[str] = []\n")
    add_module(
        project, "application/offender.py", "from dod.domain.v1 import _registry\n"
    )

    result = tach_check(project)

    assert result.returncode != 0
    assert "'dod.domain.v1._registry' is not part of the public interface" in (
        result.stdout + result.stderr
    )


def test_imports_through_the_interface_in_layer_order_are_accepted(
    project: Path,
) -> None:
    add_module(project, "domain/service/reply.py", "Reply = object\n")
    add_module(
        project,
        "domain/service/__init__.py",
        "from dod.domain.service.reply import Reply\n\n__all__ = ['Reply']\n",
    )
    add_module(project, "domain/v1/uses.py", "from dod.domain.service import Reply\n")
    add_module(
        project, "infrastructure/uses.py", "from dod.domain.service import Reply\n"
    )
    add_module(
        project, "presentation/uses.py", "from dod.domain.service import Reply\n"
    )

    result = tach_check(project)

    assert result.returncode == 0, result.stdout + result.stderr
