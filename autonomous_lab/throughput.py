"""Transparent capacity math and evidence-bounded throughput estimates.

This is a capacity model, not a scheduler and not hardware evidence. Every number is an
input assumption. Keeping the arithmetic in code makes it possible to identify the real
bottleneck, include manual transfers, and compare a proposed optimization without
quietly treating optimistic demo timing as measured performance.

``CapacityStage`` supports explicit scenario assumptions. The measured-duration model
refuses a makespan whenever any operation is untimed, so an illustrative capacity plan
cannot be mistaken for hardware evidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Optional, Tuple

from .model import Verdict


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
class TimeBasis(str, Enum):
  """Where a duration came from. Same discipline as qc.Basis, pointed at seconds."""

  UNKNOWN = "unknown"  # nobody has timed it
  ESTIMATED = "estimated"  # a scientist's guess, recorded as a guess
  MEASURED = "measured"  # timed on this instrument, and the evidence says where

  @property
  def trustworthy(self) -> bool:
    return self is TimeBasis.MEASURED


@dataclass(frozen=True)
class Duration:
  """How long a step takes, and how much that number is worth.

  `worst_case` exists because bimodal timings are the norm on real instruments and a mean
  is the wrong summary for scheduling. The Tecan's drawer is the example this repo owns:
  it opens in 3.2 s or 5.3 s depending on where the stage started, and a handoff budgeted
  on the mean collides with an arm that arrived on time.
  """

  seconds: Optional[float]
  basis: TimeBasis
  evidence: str = ""
  worst_case: Optional[float] = None

  @property
  def known(self) -> bool:
    return self.seconds is not None and self.basis is not TimeBasis.UNKNOWN

  @property
  def budget(self) -> Optional[float]:
    """What a scheduler should actually reserve: the worst case where one is known."""
    if self.worst_case is not None:
      return self.worst_case
    return self.seconds

  @classmethod
  def unknown(cls, note: str = "never timed") -> "Duration":
    return cls(seconds=None, basis=TimeBasis.UNKNOWN, evidence=note)


# Durations for the operations in this repo. Almost all are UNKNOWN, and that is the
# finding rather than an omission. The two MEASURED entries come from this repo's own
# registry evidence, timed on starpi2 on 2026-07-16.
DURATIONS: Dict[str, Duration] = {
  "tray_cycle": Duration(
    seconds=3.6,
    basis=TimeBasis.MEASURED,
    worst_case=5.3,
    evidence=(
      "five clean cycles on starpi2 2026-07-16; close stable at 3.6 s, open bimodal 3.2 s "
      "vs 5.3 s and tracking the stage's start position rather than the plate. Budget 5.3 "
      "for an iSWAP handoff"
    ),
  ),
  "iswap_lid_move": Duration.unknown("6/6 clean transfers recorded, with no timing captured"),
  "iswap_to_hhs": Duration.unknown("6/6 repeatability recorded, with no timing captured"),
  # Everything below is genuinely untimed. Listed explicitly rather than defaulted, so the
  # report can name them instead of silently treating an absent key as zero.
  "discover_usb": Duration.unknown(),
  "probe_tcp": Duration.unknown(),
  "probe_http": Duration.unknown(),
  "watch_run_folder": Duration.unknown(),
  "manual_load": Duration.unknown(),
  "load_protocol": Duration.unknown(),
  "prime": Duration.unknown(),
  "set_deposition": Duration.unknown(),
  "start_sort": Duration.unknown(),
  "wait_complete": Duration.unknown(),
  "wgs_prep_lysis": Duration.unknown(),
  "pcr_enrichment_round1": Duration.unknown(),
  "pcr_enrichment_round1_cleanup": Duration.unknown(),
  "library_pool": Duration.unknown(),
  "read_absorbance": Duration.unknown("the run card fails before it returns; there is nothing to time"),
  "upload_manifest": Duration.unknown(),
  "set_run_parameters": Duration.unknown(),
  "start_run": Duration.unknown(),
  "upload_program": Duration.unknown(),
  "select_program": Duration.unknown(),
  "run_program": Duration.unknown(),
  "set_temperature": Duration.unknown(),
  "start_method": Duration.unknown(),
  "get_status": Duration.unknown(),
  "set_injection": Duration.unknown(),
}


def duration_for(step_op: str) -> Duration:
  """The duration for an op, defaulting to UNKNOWN for anything not listed.

  Defaulting to unknown rather than raising is the safe direction: a new op should make
  the throughput report less confident, not crash it.
  """
  return DURATIONS.get(step_op, Duration.unknown("no entry in DURATIONS"))


# A working day of attended time. Steps needing a human cannot run outside it, and this is
# the ceiling that instrument speed cannot raise.
ATTENDED_SECONDS_PER_DAY = 8 * 3600


@dataclass
class ThroughputEstimate:
  """What can and cannot be said about this protocol's throughput.

  `computable` is the field to read first. When it is False, `floor_seconds` is a real
  lower bound and every other total is meaningless; the report says so rather than
  printing a number that would be quoted out of context.
  """

  protocol: str
  computable: bool
  floor_seconds: float
  unknown_ops: Tuple[str, ...]
  measured_ops: Tuple[str, ...]
  per_instrument: Dict[str, float]
  bottleneck: Optional[str]
  bottleneck_seconds: float
  attended_ops: Tuple[str, ...]
  attended_seconds: float

  @property
  def measured_fraction(self) -> float:
    total = len(self.unknown_ops) + len(self.measured_ops)
    return len(self.measured_ops) / total if total else 0.0

  def makespan(self, plates: int) -> Optional[float]:
    """Seconds to finish `plates` plates, pipelined, one process per instrument.

    Returns None when any duration is unknown. That is the whole point: a makespan over
    guessed durations is a guess wearing a total's clothing.
    """
    if not self.computable or plates < 1:
      return None
    return self.floor_seconds + (plates - 1) * self.bottleneck_seconds

  def plates_per_day(self) -> Optional[float]:
    """Plates per attended day, if that can be said at all.

    Bounded by the operator rather than the instruments whenever the protocol needs a human,
    which for every protocol in this repo it does.
    """
    if not self.computable:
      return None
    if self.attended_seconds > 0:
      return ATTENDED_SECONDS_PER_DAY / self.attended_seconds
    if self.bottleneck_seconds <= 0:
      return None
    return 86400.0 / self.bottleneck_seconds

  def why_not(self) -> str:
    """One line on what would have to be timed to make this computable."""
    if self.computable:
      return "every step has a measured duration"
    n = len(self.unknown_ops)
    return (
      f"{n} of {n + len(self.measured_ops)} steps have never been timed; a throughput "
      f"number over them would be a guess. Time these first: "
      f"{', '.join(self.unknown_ops[:5])}"
      + (" ..." if n > 5 else "")
    )


def estimate(protocol, ledger) -> ThroughputEstimate:
  """Cost a protocol's throughput against measured durations and the serialization rule.

  Attended time counts every step the ledger does not call AUTOMATED. That is the honest
  reading: SUPERVISED needs a human at the E-stop, and MANUAL, BLOCKED, WRITTEN, and BROKEN
  all need a human for reasons the ledger already explains. All of them consume the
  operator's day.
  """
  per_instrument: Dict[str, float] = {}
  unknown: List[str] = []
  measured: List[str] = []
  attended: List[str] = []
  floor = 0.0
  attended_seconds = 0.0

  headless = {row.step.op: row.verdict is Verdict.AUTOMATED for row in ledger.rows}

  for step in protocol.steps:
    d = duration_for(step.op)
    if d.known:
      measured.append(step.op)
      budget = d.budget or 0.0
      floor += budget
      per_instrument[step.instrument] = per_instrument.get(step.instrument, 0.0) + budget
      if not headless.get(step.op, False):
        attended_seconds += budget
    else:
      unknown.append(step.op)
    if not headless.get(step.op, False):
      attended.append(step.op)

  bottleneck: Optional[str] = None
  bottleneck_seconds = 0.0
  if per_instrument:
    bottleneck = max(per_instrument, key=lambda k: per_instrument[k])
    bottleneck_seconds = per_instrument[bottleneck]

  return ThroughputEstimate(
    protocol=protocol.name,
    computable=not unknown,
    floor_seconds=floor,
    unknown_ops=tuple(unknown),
    measured_ops=tuple(measured),
    per_instrument=per_instrument,
    bottleneck=bottleneck,
    bottleneck_seconds=bottleneck_seconds,
    attended_ops=tuple(attended),
    attended_seconds=attended_seconds,
  )
