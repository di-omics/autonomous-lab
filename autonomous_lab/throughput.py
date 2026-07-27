"""How many plates a day this lab could do, and why that number does not exist yet.

Throughput is the claim automation is usually sold on and the one least often computed.
The arithmetic is not hard -- it is a pipeline with a bottleneck -- but it needs a measured
duration for every step, and a lab that has never timed its steps does not have those. The
usual response is to estimate them, publish a plate-per-day figure, and quietly turn a
guess into a specification.

This module refuses that. Every duration carries a Basis, and a throughput estimate over
any UNKNOWN duration is reported as NOT COMPUTABLE with the unmeasured steps named. It
still computes a FLOOR from what is measured, because a floor is a real fact and a bound
is more useful than a refusal. What it will not do is fill a gap with a plausible number
and return a total that looks like an answer.

The scheduling model is the standard pipelined one, and its constraint comes from this
repo rather than from a textbook. ONE_PROCESS_PER_INSTRUMENT is a hard rule in plr-tested:
two STAR clients raise USBError [Errno 16] Resource busy, and on the ODTC the collision is
silent. So instruments serialize across concurrent plates, the busiest instrument sets the
cycle time, and:

    makespan(n) = one_plate_end_to_end + (n - 1) * bottleneck_occupancy

The second constraint is the one automation vendors leave out. Steps that need a human are
not merely slower, they are unavailable outside attended hours. A lab whose protocol needs
an operator six times cannot run overnight no matter how fast the robot is, and its real
throughput ceiling is set by the operator's day rather than by the instruments. Both
numbers are reported, because the gap between them is the actual case for closing the
remaining gaps.

What this lab has measured today: one instrument's drawer. That is not a joke about the
lab, it is the state of the evidence, and it is why every genomics number here is a floor.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .model import Verdict


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
