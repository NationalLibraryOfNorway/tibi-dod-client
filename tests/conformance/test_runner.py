"""The conformance runner through the application interface (ADR 0003, 0005).

Tests are registered on a private `Registry`; the Service is the in-memory one
with injected faults. Users and passwords are synthetic.
"""

import pytest

from dod.application import (
    Context,
    Outcome,
    Registry,
    Result,
    RunReport,
    run_conformance,
)
from dod.domain.service import (
    Observation,
    Ok,
    Password,
    TransportError,
)
from dod.domain.v1 import SPEC_REFS, ServicePort
from dod.infrastructure import InMemoryService

USER = "synthetic-user"
PASSWORD = Password("synthetic-secret")


@pytest.fixture
def service() -> InMemoryService:
    fake = InMemoryService()
    fake.add_user(USER, PASSWORD.reveal())
    return fake


def run(
    service: InMemoryService,
    registry: Registry,
    *,
    password: Password = PASSWORD,
    **options: object,
) -> RunReport:
    return run_conformance(
        lambda url: service.open_port(),
        "https://dod.example.org/service",
        USER,
        password,
        tests=registry,
        **options,  # type: ignore[arg-type]
    )


def outcomes(report: RunReport) -> dict[str, Outcome]:
    return {record.id: record.outcome for record in report.records}


def passing(ctx: Context) -> Result:
    return Result.passed()


def test_a_registered_function_runs_under_its_stable_id(
    service: InMemoryService,
) -> None:
    registry = Registry()

    @registry.test("demo.first.check")
    def first(ctx: Context) -> Result:
        return Result.passed()

    report = run(service, registry)

    assert outcomes(report) == {"demo.first.check": Outcome.PASS}
    assert report.exit_code == 0


def test_ids_are_listed_in_registration_order(service: InMemoryService) -> None:
    registry = Registry()
    registry.test("b.one")(passing)
    registry.test("a.two", state_changing=True)(passing)

    assert [(t.id, t.state_changing) for t in registry.tests] == [
        ("b.one", False),
        ("a.two", True),
    ]


def test_an_id_can_only_be_registered_once() -> None:
    registry = Registry()
    registry.test("demo.one")(passing)

    with pytest.raises(ValueError, match=r"demo\.one"):
        registry.test("demo.one")(passing)


@pytest.mark.parametrize("bad", ["", "Demo.One", "demo..one", "demo one", ".demo"])
def test_an_id_must_be_hierarchical_lower_case(bad: str) -> None:
    with pytest.raises(ValueError):
        Registry().test(bad)(passing)


def test_a_failure_carries_its_message_and_spec_reference(
    service: InMemoryService,
) -> None:
    registry = Registry()

    @registry.test("demo.fails")
    def fails(ctx: Context) -> Result:
        return Result.failed("it broke", SPEC_REFS["operation.logOn"])

    report = run(service, registry)

    (record,) = report.records
    assert record.outcome is Outcome.FAIL
    assert record.message == "it broke"
    assert record.spec_ref == SPEC_REFS["operation.logOn"]
    assert report.exit_code == 1


def test_a_fail_without_a_spec_reference_is_an_error_in_dod(
    service: InMemoryService,
) -> None:
    registry = Registry()

    @registry.test("demo.unreferenced")
    def unreferenced(ctx: Context) -> Result:
        return Result(Outcome.FAIL, "no reference given")

    report = run(service, registry)

    (record,) = report.records
    assert record.outcome is Outcome.ERROR
    assert "Spec reference" in record.message
    assert report.exit_code == 2


def test_skip_ends_the_test_as_skip_with_the_reason(service: InMemoryService) -> None:
    registry = Registry()

    @registry.test("demo.skipped")
    def skipped(ctx: Context) -> Result:
        ctx.skip("nothing to test here")
        raise AssertionError("not reached")

    report = run(service, registry)

    (record,) = report.records
    assert record.outcome is Outcome.SKIP
    assert record.message == "nothing to test here"
    assert report.exit_code == 0


def test_a_transport_error_is_an_error_not_a_fail(service: InMemoryService) -> None:
    registry = Registry()

    @registry.test("demo.no-answer")
    def no_answer(ctx: Context) -> Result:
        raise TransportError("getServiceAttributes: no answer from the Service")

    registry.test("demo.after")(passing)

    report = run(service, registry)

    assert outcomes(report) == {
        "demo.no-answer": Outcome.ERROR,
        "demo.after": Outcome.PASS,
    }
    assert report.records[0].message == (
        "getServiceAttributes: no answer from the Service"
    )
    assert report.exit_code == 2


def test_a_defect_in_a_test_is_an_error_and_does_not_stop_the_run(
    service: InMemoryService,
) -> None:
    registry = Registry()

    @registry.test("demo.broken")
    def broken(ctx: Context) -> Result:
        raise RuntimeError("synthetic defect")

    registry.test("demo.after")(passing)

    report = run(service, registry)

    assert outcomes(report) == {
        "demo.broken": Outcome.ERROR,
        "demo.after": Outcome.PASS,
    }
    assert "synthetic defect" in report.records[0].message


def test_exit_code_is_two_when_there_is_an_error_and_a_fail(
    service: InMemoryService,
) -> None:
    registry = Registry()
    registry.test("demo.fail")(lambda ctx: Result.failed("x", SPEC_REFS["faults"]))

    @registry.test("demo.error")
    def error(ctx: Context) -> Result:
        raise TransportError("no answer")

    assert run(service, registry).exit_code == 2


def test_only_selects_by_id_prefix_on_whole_segments(service: InMemoryService) -> None:
    registry = Registry()
    for name in ("a.one", "a.two", "ab.one", "b.one"):
        registry.test(name)(passing)

    report = run(service, registry, only=("a",))

    assert list(outcomes(report)) == ["a.one", "a.two"]


def test_skip_prefixes_are_left_out_of_the_run(service: InMemoryService) -> None:
    registry = Registry()
    for name in ("a.one", "a.two", "b.one"):
        registry.test(name)(passing)

    report = run(service, registry, skip=("a.two",), only=("a", "b"))

    assert list(outcomes(report)) == ["a.one", "b.one"]


def test_a_prefix_that_matches_nothing_is_refused(service: InMemoryService) -> None:
    registry = Registry()
    registry.test("a.one")(passing)

    with pytest.raises(ValueError, match="nope"):
        run(service, registry, only=("nope",))


def test_state_changing_tests_are_skipped_without_opt_in(
    service: InMemoryService,
) -> None:
    registry = Registry()
    ran: list[str] = []

    @registry.test("demo.change", state_changing=True)
    def change(ctx: Context) -> Result:
        ran.append("change")
        return Result.passed()

    report = run(service, registry)

    (record,) = report.records
    assert record.outcome is Outcome.SKIP
    assert "state-changing" in record.message
    assert ran == []


def test_state_changing_tests_run_with_opt_in(service: InMemoryService) -> None:
    registry = Registry()
    registry.test("demo.change", state_changing=True)(passing)

    report = run(service, registry, state_changing=True)

    assert outcomes(report) == {"demo.change": Outcome.PASS}


def test_a_failed_logon_in_the_setup_is_an_error_that_ends_the_run(
    service: InMemoryService,
) -> None:
    registry = Registry()
    ran: list[str] = []

    @registry.test("demo.never")
    def never(ctx: Context) -> Result:
        ran.append("never")
        return Result.passed()

    report = run(service, registry, password=Password("wrong"))

    assert ran == []
    assert report.records == ()
    assert report.setup_error is not None
    assert "logOn" in report.setup_error
    assert report.exit_code == 2


def test_a_fault_during_setup_is_an_error_that_ends_the_run(
    service: InMemoryService,
) -> None:
    registry = Registry()
    registry.test("demo.never")(passing)
    service.inject_fault("getServiceAttributes", "internalServerError", "synthetic")

    report = run(service, registry)

    assert report.records == ()
    assert report.setup_error is not None
    assert "getServiceAttributes" in report.setup_error
    assert report.exit_code == 2


def test_the_run_never_uses_a_stored_session(service: InMemoryService) -> None:
    opened: list[ServicePort] = []

    def open_port(url: str) -> ServicePort:
        port = service.open_port()
        opened.append(port)
        return port

    registry = Registry()
    registry.test("demo.a")(passing)

    run_conformance(
        open_port, "https://dod.example.org/service", USER, PASSWORD, tests=registry
    )

    # One port of its own with a Session of its own, ended and released again.
    assert len(opened) == 1
    assert opened[0].session is not None
    assert service._sessions == set()


def test_exchanges_are_numbered_and_tied_to_the_test_that_made_them(
    service: InMemoryService,
) -> None:
    registry = Registry()

    @registry.test("demo.calls")
    def calls(ctx: Context) -> Result:
        ctx.call(lambda port: port.get_service_attributes())
        return Result.passed()

    registry.test("demo.silent")(passing)

    report = run(service, registry)

    calls_record, silent_record = report.records
    assert len(calls_record.exchange_ids) == 1
    assert silent_record.exchange_ids == ()
    assert calls_record.exchange_ids[0] in report.exchanges
    assert report.setup_exchange_ids  # logOn, getServiceAttributes, setReading...


def test_observations_of_every_reply_are_collected_once(
    service: InMemoryService,
) -> None:
    registry = Registry()

    @registry.test("demo.observed")
    def observed(ctx: Context) -> Result:
        reply = ctx.call(lambda port: port.get_service_attributes())
        assert isinstance(reply, Ok)
        return Result.passed()

    service_port = service.open_port

    def noisy_port() -> ServicePort:
        return _Noisy(service_port())

    def open_port(url: str) -> ServicePort:
        return noisy_port()

    report = run_conformance(
        open_port, "https://dod.example.org/service", USER, PASSWORD, tests=registry
    )

    assert report.observations == (Observation("synthetic", "noticed"),)


class _Noisy:
    """A port whose Replies all carry the same Observation."""

    def __init__(self, port: ServicePort) -> None:
        self._port = port

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        attribute = getattr(self._port, name)
        if not callable(attribute):
            return attribute

        def call(*args, **kwargs):  # type: ignore[no-untyped-def]
            from dataclasses import replace

            reply = attribute(*args, **kwargs)
            if hasattr(reply, "exchange"):
                return replace(
                    reply, observations=(Observation("synthetic", "noticed"),)
                )
            return reply

        return call


# -- classifying what the Service answered ----------------------------------


def test_expect_ok_makes_a_fault_a_fail_with_the_operations_reference(
    service: InMemoryService,
) -> None:
    registry = Registry()
    ref = SPEC_REFS["operation.getContentList"]

    @registry.test("demo.fault")
    def fault(ctx: Context) -> Result:
        reply = ctx.call(lambda port: port.get_content_list("no-such-list", 0, -1))
        ctx.expect_ok(reply, ref)
        raise AssertionError("not reached")

    (record,) = run(service, registry).records

    assert record.outcome is Outcome.FAIL
    assert "invalidParameter" in record.message
    assert record.spec_ref == ref


def test_expect_ok_makes_a_deviation_a_fail_with_the_deviations_own_reference(
    service: InMemoryService,
) -> None:
    registry = Registry()

    @registry.test("demo.deviation")
    def deviation(ctx: Context) -> Result:
        # One-shot injection, set after the setup has run.
        service.inject_deviation("getServiceAttributes")
        reply = ctx.call(lambda port: port.get_service_attributes())
        ctx.expect_ok(reply, SPEC_REFS["type.serviceAttributes"])
        raise AssertionError("not reached")

    (record,) = run(service, registry).records

    assert record.outcome is Outcome.FAIL
    assert "contrary to the specification" in record.message
    assert record.spec_ref == SPEC_REFS["operation.getServiceAttributes"]


# -- optional operations ----------------------------------------------------------


def optional_test(registry: Registry) -> None:
    @registry.test("demo.announcements")
    def announcements(ctx: Context) -> Result:
        ctx.optional(
            "SERVICE_ANNOUNCEMENTS",
            lambda port: port.get_service_announcements(),
            SPEC_REFS["operation.getServiceAnnouncements"],
        )
        return Result.passed()


def test_an_optional_operation_that_is_not_declared_and_not_supported_is_skip(
    service: InMemoryService,
) -> None:
    registry = Registry()
    optional_test(registry)

    (record,) = run(service, registry).records

    assert record.outcome is Outcome.SKIP
    assert "SERVICE_ANNOUNCEMENTS" in record.message


def test_an_optional_operation_that_is_declared_but_not_supported_is_fail(
    service: InMemoryService,
) -> None:
    registry = Registry()
    optional_test(registry)
    service.offer_announcements()  # declares the operation, publishes nothing

    (record,) = run(service, registry).records

    assert record.outcome is Outcome.FAIL
    assert "operationNotSupported" in record.message
    assert record.spec_ref == SPEC_REFS["fault.operationNotSupported"]


def test_an_optional_operation_that_works_without_being_declared_passes_with_a_note(
    service: InMemoryService,
) -> None:
    from dod.domain.v1 import Announcement, ServiceAttributes

    registry = Registry()
    optional_test(registry)
    service.offer_announcements(Announcement(id="a1", text="synthetic"))
    # The announcements are published, but the declaration is taken away again.
    service.attributes = ServiceAttributes(supported_optional_operations=())

    (record,) = run(service, registry).records

    assert record.outcome is Outcome.PASS
    assert record.note is not None
    assert "not declared" in record.note


def test_an_optional_operation_that_is_declared_and_works_passes_without_a_note(
    service: InMemoryService,
) -> None:
    from dod.domain.v1 import Announcement

    registry = Registry()
    optional_test(registry)
    service.offer_announcements(Announcement(id="a1", text="synthetic"))

    (record,) = run(service, registry).records

    assert record.outcome is Outcome.PASS
    assert record.note is None
