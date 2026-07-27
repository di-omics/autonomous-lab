"""Capacity math names assumptions and the resource that limits throughput."""

from __future__ import annotations

import pytest

from autonomous_lab.throughput import CapacityStage, ThroughputPlan, illustrative_genomics_plan


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
