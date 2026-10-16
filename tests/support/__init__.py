"""Test support: the contract harness, the fake Service and the CLI runner."""

from dod.domain.service import Password
from support._cli import run_dod
from support._fake_service import FakeService, HttpHarness, service_wsdl
from support._harness import Harness

PASSWORD = "synthetic-secret"
"""The one synthetic password of the tests (never a real one)."""
SECRET = Password(PASSWORD)
"""The same, as the `Password` value the library takes."""

__all__ = [
    "PASSWORD",
    "SECRET",
    "FakeService",
    "Harness",
    "HttpHarness",
    "run_dod",
    "service_wsdl",
]
