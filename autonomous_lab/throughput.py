"""Transparent throughput and bottleneck arithmetic for laboratory workflows.

This is a capacity model, not a scheduler and not hardware evidence. Every number is an
input assumption. Keeping the arithmetic in code makes it possible to identify the real
bottleneck, include manual transfers, and compare a proposed optimization without
quietly treating optimistic demo timing as measured performance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Tuple


@dataclass(frozen=True)
class CapacityStage:
  name: str
  resource: str
  batch_size: int
  process_minutes: float
  setup_minutes: float = 0.0
  transfer_minutes: float = 0.0
  parallel_units: int = 1
  measured: bool = False
  note: str = ""

  def __post_init__(self):
    if not self.name or not self.resource:
      raise ValueError("stage name and resource must not be empty")
    if self.batch_size <= 0 or self.parallel_units <= 0:
      raise ValueError(f"stage {self.name} needs positive batch_size and parallel_units")
    if self.process_minutes <= 0:
      raise ValueError(f"stage {self.name} needs positive process_minutes")
    if self.setup_minutes < 0 or self.transfer_minutes < 0:
      raise ValueError(f"stage {self.name} has negative overhead")

  @property
  def cycle_minutes(self) -> float:
    return self.process_minutes + self.setup_minutes + self.transfer_minutes

  @property
  def samples_per_hour(self) -> float:
    return 60.0 * self.batch_size * self.parallel_units / self.cycle_minutes

  def work_minutes(self, samples: int) -> float:
    batches = math.ceil(samples / self.batch_size)
    waves = math.ceil(batches / self.parallel_units)
    return waves * self.cycle_minutes


@dataclass(frozen=True)
class StageCapacity:
  stage: CapacityStage
  samples_per_hour: float
  work_minutes: float


@dataclass(frozen=True)
class ThroughputReport:
  sample_count: int
  stages: Tuple[StageCapacity, ...]
  bottlenecks: Tuple[str, ...]
  steady_state_samples_per_hour: float
  serial_upper_bound_minutes: float
  measured: bool


class ThroughputPlan:
  def __init__(self, name: str, stages: Iterable[CapacityStage], note: str = ""):
    if not name:
      raise ValueError("throughput plan name must not be empty")
    self.name = name
    self.stages = tuple(stages)
    self.note = note
    if not self.stages:
      raise ValueError(f"throughput plan {name} needs at least one stage")
    names = [stage.name for stage in self.stages]
    if len(names) != len(set(names)):
      raise ValueError(f"throughput plan {name} contains duplicate stage names")

  def report(self, sample_count: int) -> ThroughputReport:
    if sample_count <= 0:
      raise ValueError("sample_count must be positive")
    rows = tuple(
      StageCapacity(stage, stage.samples_per_hour, stage.work_minutes(sample_count))
      for stage in self.stages
    )
    rate = min(row.samples_per_hour for row in rows)
    bottlenecks = tuple(
      row.stage.name for row in rows if math.isclose(row.samples_per_hour, rate, rel_tol=1e-9)
    )
    return ThroughputReport(
      sample_count=sample_count,
      stages=rows,
      bottlenecks=bottlenecks,
      steady_state_samples_per_hour=rate,
      # Deliberately conservative. A real scheduler can overlap stages; this bound cannot
      # accidentally promise that overlap before resource and handoff constraints exist.
      serial_upper_bound_minutes=sum(row.work_minutes for row in rows),
      measured=all(stage.measured for stage in self.stages),
    )

  def compare(self, other: "ThroughputPlan", sample_count: int) -> float:
    """Fractional steady-state improvement of `other` over this plan."""
    baseline = self.report(sample_count).steady_state_samples_per_hour
    candidate = other.report(sample_count).steady_state_samples_per_hour
    return candidate / baseline - 1.0


def illustrative_genomics_plan() -> ThroughputPlan:
  """Synthetic assumptions for exercising the model; not measured lab performance."""
  return ThroughputPlan(
    "illustrative_low_input_genomics",
    (
      CapacityStage("sort", "single-cell dispenser", 96, 70, setup_minutes=10),
      CapacityStage(
        "plate_handoff_1", "operator or plate mover", 96, 5, transfer_minutes=3
      ),
      CapacityStage("lysis", "liquid handler", 96, 55, setup_minutes=15),
      CapacityStage("amplification", "thermocycler", 96, 130, setup_minutes=10),
      CapacityStage("cleanup", "liquid handler", 96, 80, setup_minutes=15),
      CapacityStage("plate_reader_qc", "plate reader", 96, 18, setup_minutes=7),
      CapacityStage("sequencing", "sequencer", 96, 1320, setup_minutes=45),
    ),
    note="Illustrative timings only. Replace every stage with measured workcell data.",
  )


def render_report(plan: ThroughputPlan, report: ThroughputReport) -> str:
  evidence = "MEASURED" if report.measured else "ASSUMPTIONS - NOT HARDWARE EVIDENCE"
  lines = [
    f"plan: {plan.name}",
    f"evidence: {evidence}",
    f"samples: {report.sample_count}",
    "",
  ]
  for row in report.stages:
    marker = " < bottleneck" if row.stage.name in report.bottlenecks else ""
    lines.append(
      f"  {row.stage.name:<22} {row.samples_per_hour:7.2f} samples/hour"
      f"  {row.work_minutes:7.1f} min work{marker}"
    )
  lines.extend(
    [
      "",
      f"steady-state ceiling: {report.steady_state_samples_per_hour:.2f} samples/hour",
      f"serial upper bound:   {report.serial_upper_bound_minutes:.1f} minutes",
      f"bottleneck:           {', '.join(report.bottlenecks)}",
    ]
  )
  if plan.note:
    lines.append(f"note: {plan.note}")
  return "\n".join(lines)
