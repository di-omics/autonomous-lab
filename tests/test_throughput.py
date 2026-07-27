"""Capacity math identifies bottlenecks without inventing missing measurements."""

from __future__ import annotations

import pytest

from autonomous_lab import build_ledger, protocols
from autonomous_lab.model import Artifact, Protocol, Step, ZeroDecodeOp
from autonomous_lab.throughput import (
  ATTENDED_SECONDS_PER_DAY,
  DURATIONS,
  CapacityStage,
  Duration,
  ThroughputPlan,
  TimeBasis,
  duration_for,
  estimate,
  illustrative_genomics_plan,
)


def test_bottleneck_is_the_lowest_capacity_stage():
  plan = ThroughputPlan(
    "test",
    (
      CapacityStage("fast", "reader", 96, 30),
      CapacityStage("slow", "cycler", 96, 120),
    ),
  )
  report = plan.report(96)
  assert report.bottlenecks == ("slow",)
  assert report.steady_state_samples_per_hour == pytest.approx(48.0)


def test_setup_and_transfer_time_reduce_capacity():
  bare = CapacityStage("bare", "robot", 96, 60)
  loaded = CapacityStage("loaded", "robot", 96, 60, setup_minutes=20, transfer_minutes=10)
  assert loaded.samples_per_hour < bare.samples_per_hour


def test_parallel_resources_raise_capacity():
  one = CapacityStage("one", "cycler", 96, 120)
  two = CapacityStage("two", "cyclers", 96, 120, parallel_units=2)
  assert two.samples_per_hour == 2 * one.samples_per_hour


def test_serial_upper_bound_includes_every_stage_workload():
  plan = ThroughputPlan(
    "test",
    (
      CapacityStage("a", "a", 96, 10),
      CapacityStage("b", "b", 96, 20),
    ),
  )
  assert plan.report(192).serial_upper_bound_minutes == 60


def test_plan_comparison_reports_fractional_improvement():
  baseline = ThroughputPlan("base", (CapacityStage("a", "a", 96, 120),))
  candidate = ThroughputPlan("candidate", (CapacityStage("a", "a", 96, 60),))
  assert baseline.compare(candidate, 96) == pytest.approx(1.0)


def test_invalid_stage_is_refused():
  with pytest.raises(ValueError, match="positive batch_size"):
    CapacityStage("bad", "robot", 0, 1)


def test_illustrative_plan_never_claims_measurement():
  report = illustrative_genomics_plan().report(96)
  assert not report.measured
  assert "sequencing" in report.bottlenecks


# -- the refusal ---------------------------------------------------------------


def test_makespan_is_none_while_any_step_is_untimed():
  protocol = protocols.get("single_cell_genomics")
  est = estimate(protocol, build_ledger(protocol))
  assert not est.computable
  assert est.makespan(1) is None
  assert est.makespan(10) is None
  assert est.plates_per_day() is None


def test_the_refusal_names_what_to_time_first():
  """A refusal that gives no next action is just an error message."""
  protocol = protocols.get("single_cell_genomics")
  est = estimate(protocol, build_ledger(protocol))
  why = est.why_not()
  assert "never been timed" in why
  assert any(op in why for op in est.unknown_ops)


def test_nothing_in_the_genomics_protocol_has_been_timed():
  """Pinned. If a duration ever appears here it should be because someone measured it."""
  protocol = protocols.get("single_cell_genomics")
  est = estimate(protocol, build_ledger(protocol))
  assert est.measured_fraction == 0.0
  assert est.floor_seconds == 0.0


def test_a_fully_timed_protocol_does_compute():
  """The engine works the moment the data exists; it is the data that is missing."""
  protocol = Protocol(
    name="timed",
    summary="test",
    artifacts=(Artifact("thing"),),
    steps=(
      Step(
        instrument="element_aviti",
        op=ZeroDecodeOp.WATCH_RUN_FOLDER.value,
        summary="read",
        produces=("thing",),
        params={"run_dir": "/tmp/x"},
      ),
    ),
  )
  saved = DURATIONS.get(ZeroDecodeOp.WATCH_RUN_FOLDER.value)
  DURATIONS[ZeroDecodeOp.WATCH_RUN_FOLDER.value] = Duration(
    seconds=10.0, basis=TimeBasis.MEASURED, evidence="test"
  )
  try:
    est = estimate(protocol, build_ledger(protocol))
    assert est.computable
    assert est.makespan(1) == 10.0
    assert est.makespan(5) == 10.0 + 4 * 10.0
  finally:
    if saved is not None:
      DURATIONS[ZeroDecodeOp.WATCH_RUN_FOLDER.value] = saved


# -- worst case ----------------------------------------------------------------


def test_the_scheduler_budgets_the_worst_case_not_the_mean():
  """The Tecan drawer is bimodal. A handoff budgeted on 3.6 s collides at 5.3 s."""
  d = DURATIONS["tray_cycle"]
  assert d.basis is TimeBasis.MEASURED
  assert d.seconds == 3.6
  assert d.worst_case == 5.3
  assert d.budget == 5.3


def test_a_duration_without_a_worst_case_budgets_its_nominal():
  d = Duration(seconds=4.0, basis=TimeBasis.MEASURED)
  assert d.budget == 4.0


def test_unknown_durations_are_not_known_and_have_no_budget():
  d = Duration.unknown()
  assert not d.known
  assert d.budget is None
  assert d.basis is TimeBasis.UNKNOWN


def test_an_unlisted_op_defaults_to_unknown_rather_than_zero():
  """Defaulting an absent key to zero would silently make a protocol look instant."""
  d = duration_for("an_op_nobody_declared")
  assert not d.known
  assert d.basis is TimeBasis.UNKNOWN


def test_only_measured_counts_as_trustworthy():
  assert TimeBasis.MEASURED.trustworthy
  assert not TimeBasis.ESTIMATED.trustworthy
  assert not TimeBasis.UNKNOWN.trustworthy


# -- the operator ceiling ------------------------------------------------------


def test_attended_steps_are_counted_for_every_non_headless_verdict():
  """SUPERVISED, MANUAL, BLOCKED, WRITTEN and BROKEN all consume an operator's day."""
  protocol = protocols.get("single_cell_genomics")
  ledger = build_ledger(protocol)
  est = estimate(protocol, ledger)
  headless = sum(1 for r in ledger.rows if r.verdict.headless)
  assert len(est.attended_ops) == len(protocol.steps) - headless


def test_a_working_day_is_the_ceiling_not_a_full_day():
  assert ATTENDED_SECONDS_PER_DAY < 86400


def test_negative_or_zero_plate_counts_return_nothing():
  protocol = protocols.get("single_cell_genomics")
  est = estimate(protocol, build_ledger(protocol))
  assert est.makespan(0) is None
  assert est.makespan(-1) is None
