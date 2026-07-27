"""What goes wrong, whether anything in this lab would notice, and what to do about it.

Execution layers model the happy path and treat failure as an exception to be raised. A
lab does the opposite: the failures ARE the work, and the difference between a good
automated lab and a bad one is not how often it fails but how fast it finds out.

So this module models failure as a first-class thing with four properties, and the third
is the one that gets skipped:

  WHAT it is             -- the physical event, in bench terms
  HOW it would be caught -- instrument error, QC gate, camera, operator, or the data
  WHEN it would be caught -- immediately, at the next gate, only after sequencing, or never
  WHAT TO DO             -- retry, recover, escalate, abort

The point of separating DECLARED detection from EFFECTIVE detection is that a lab's failure
plan is usually written against instruments it does not have working. A failure whose
detection path is "the QC gate catches it" is undetected in practice when that gate is
unsatisfiable, and this repo's genomics gates are all unsatisfiable. `effective()` resolves
each declared path against the real ledger, the real gate readiness, and the real vision
capability, and downgrades the latency accordingly. The result is usually much worse than
the plan on paper, and that gap is the honest finding.

Two failures here are worth reading even if nothing else is:

  bead_pellet_aspirated destroys the sample completely and silently. Every downstream step
  runs normally on an empty well. Its only detection paths are a camera this lab does not
  have and a quantification gate this lab cannot evaluate, so its effective latency is
  NEVER: the first evidence is a sequencing run that cost a flow cell to produce.

  odtc_callback_theft is documented in this repo's own registry note. Start a second driver
  process against the ODTC and it re-registers the event receiver, silently stealing the
  first process's callbacks. Nothing raises. The first process simply waits forever for a
  thermal-complete event that is being delivered somewhere else. It is the cleanest example
  in this lab of a failure that no sensor catches because it is not a physical event at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .qc import Decision, GateReport
from .vision import CHECKS_BY_NAME, Observable, VisionCapability, check_catching


class Detection(str, Enum):
  """How a failure would be noticed, if anything noticed it."""

  INSTRUMENT = "instrument"  # the instrument itself raises, times out, or reports an error
  VISION = "vision"  # a camera would see it, if one existed and were validated
  QC_GATE = "qc_gate"  # a downstream measurement reveals it
  OPERATOR = "operator"  # a human standing at the bench sees it
  DATA_ANALYSIS = "data_analysis"  # only visible in the sequencing output, after the run
  NONE = "none"  # nothing in any lab would catch this without a dedicated experiment


class Latency(str, Enum):
  """When the failure would be found. Ordered best to worst; later costs more.

  The jump from AT_NEXT_GATE to AFTER_SEQUENCING is where the money is. A failure caught at
  a gate costs a plate and a reagent set. The same failure caught in the data costs a flow
  cell, an instrument run, and the calendar time of both -- and for a scarce sample it
  costs the sample, which cannot be rebought at any price.
  """

  IMMEDIATE = "immediate"  # at the step, while the material is still recoverable
  AT_NEXT_STEP = "at_next_step"
  AT_NEXT_GATE = "at_next_gate"
  AFTER_SEQUENCING = "after_sequencing"  # the flow cell is already spent
  NEVER = "never"  # nothing in this lab would ever surface it


_LATENCY_ORDER: Tuple[Latency, ...] = (
  Latency.IMMEDIATE,
  Latency.AT_NEXT_STEP,
  Latency.AT_NEXT_GATE,
  Latency.AFTER_SEQUENCING,
  Latency.NEVER,
)


class Severity(str, Enum):
  """What the failure costs when it happens."""

  RECOVERABLE = "recoverable"  # repeat the step; nothing is lost but time
  REAGENT = "reagent"  # a reagent set or a plate is spent
  SAMPLE = "sample"  # the input material is destroyed and cannot be regenerated
  RUN = "run"  # a flow cell and a sequencing run are spent
  MECHANICAL = "mechanical"  # the instrument itself is at risk


@dataclass(frozen=True)
class FailureMode:
  """One thing that goes wrong at one step.

  `declared_detection` is the plan. `observable` records whether a camera could ever help,
  which is what makes the vision module's taxonomy actionable rather than descriptive: a
  failure that is INVISIBLE will not be fixed by buying cameras, however much the plan
  wants it to be.
  """

  name: str
  step_op: str
  description: str
  observable: Observable
  declared_detection: Detection
  declared_latency: Latency
  severity: Severity
  response: Decision
  note: str = ""
  # The gate whose measurement would reveal it, when declared_detection is QC_GATE. Named
  # so effective() can check whether that gate is actually evaluable.
  via_gate: Optional[str] = None


@dataclass(frozen=True)
class EffectiveDetection:
  """A failure mode resolved against what this lab can actually do today."""

  failure: FailureMode
  detection: Detection
  latency: Latency
  reason: str

  @property
  def degraded(self) -> bool:
    """True when reality is worse than the plan."""
    return (
      _LATENCY_ORDER.index(self.latency) > _LATENCY_ORDER.index(self.failure.declared_latency)
    )

  @property
  def silent(self) -> bool:
    """Nothing in this lab would ever surface it."""
    return self.latency is Latency.NEVER

  @property
  def destructive_and_silent(self) -> bool:
    """The worst category: destroys material and nothing notices.

    These are the failures that make an automated lab dangerous rather than merely
    unreliable, because the run completes, the report is clean, and the answer is wrong.
    """
    return self.silent and self.failure.severity in (Severity.SAMPLE, Severity.RUN)


# -- the failure modes of the single-cell genomics loop -------------------------

FAILURE_MODES: Tuple[FailureMode, ...] = (
  FailureMode(
    name="tip_not_picked_up",
    step_op="wgs_prep_lysis",
    description="a channel fails to seat a tip and pipettes air for the rest of the transfer",
    observable=Observable.VISIBLE,
    declared_detection=Detection.VISION,
    declared_latency=Latency.IMMEDIATE,
    severity=Severity.RECOVERABLE,
    response=Decision.RETRY,
    note="the STAR reports nothing; the move completes normally with an empty channel",
  ),
  FailureMode(
    name="plate_misseated",
    step_op="wgs_prep_lysis",
    description="a plate sits proud of its nest, or its lid was never removed",
    observable=Observable.VISIBLE,
    declared_detection=Detection.VISION,
    declared_latency=Latency.IMMEDIATE,
    severity=Severity.MECHANICAL,
    response=Decision.ABORT,
    note="a crash risk to the head as well as a scientific failure",
  ),
  FailureMode(
    name="bead_pellet_aspirated",
    step_op="pcr_enrichment_round1_cleanup",
    description="the magnetic pellet is drawn off with the supernatant and the library goes to waste",
    observable=Observable.VISIBLE,
    declared_detection=Detection.QC_GATE,
    declared_latency=Latency.AT_NEXT_GATE,
    severity=Severity.SAMPLE,
    response=Decision.ABORT,
    via_gate="library_quant_before_flow_cell",
    note=(
      "the single most destructive routine failure in low-input prep. The beads carry the "
      "entire library; losing them loses everything, and every subsequent step runs "
      "normally on an empty well"
    ),
  ),
  FailureMode(
    name="empty_well_after_sort",
    step_op="start_sort",
    description="the dispenser fires but no cell lands, leaving an empty well that looks sorted",
    observable=Observable.VISIBLE_INDIRECT,
    declared_detection=Detection.QC_GATE,
    declared_latency=Latency.AT_NEXT_GATE,
    severity=Severity.REAGENT,
    response=Decision.RETRY,
    via_gate="sort_occupancy_before_amplification",
  ),
  FailureMode(
    name="evaporation_during_incubation",
    step_op="pcr_enrichment_round1",
    description="wells lose volume during the thermal hold, concentrating or drying the reaction",
    observable=Observable.VISIBLE_INDIRECT,
    declared_detection=Detection.VISION,
    declared_latency=Latency.AT_NEXT_STEP,
    severity=Severity.SAMPLE,
    response=Decision.RECOVER,
    note=(
      "live in this lab rather than theoretical: this repo's own registry records that the "
      "PCR enrichment choreography never closes the ODTC door around the thermal leg"
    ),
  ),
  FailureMode(
    name="wrong_reagent_right_position",
    step_op="wgs_prep_lysis",
    description="the correct position on the deck holds the wrong tube",
    observable=Observable.INVISIBLE,
    declared_detection=Detection.OPERATOR,
    declared_latency=Latency.AFTER_SEQUENCING,
    severity=Severity.SAMPLE,
    response=Decision.ABORT,
    note=(
      "invisible in the strict sense: two clear liquids in identical tubes at the same "
      "position produce identical images. Barcoding the consumable, not imaging it, is "
      "what closes this"
    ),
  ),
  FailureMode(
    name="enzyme_activity_lost",
    step_op="wgs_prep_lysis",
    description="a reagent lost activity to freeze-thaw or time at temperature",
    observable=Observable.INVISIBLE,
    declared_detection=Detection.QC_GATE,
    declared_latency=Latency.AT_NEXT_GATE,
    severity=Severity.SAMPLE,
    response=Decision.ABORT,
    via_gate="library_quant_before_flow_cell",
    note="only a yield measurement reveals it, and only against a control that also ran",
  ),
  FailureMode(
    name="volume_short_within_tolerance",
    step_op="wgs_prep_lysis",
    description="a transfer delivers meaningfully less than nominal but inside the instrument's spec",
    observable=Observable.INVISIBLE,
    declared_detection=Detection.NONE,
    declared_latency=Latency.NEVER,
    severity=Severity.SAMPLE,
    response=Decision.ESCALATE,
    note=(
      "the failure that biases a dataset instead of breaking it. At picogram input a ten "
      "percent volume error is a real efficiency change, it is within the instrument's own "
      "tolerance, and nothing flags it. Gravimetric or dye-based calibration is the answer "
      "and it is an experiment, not a sensor"
    ),
  ),
  FailureMode(
    name="cross_contamination",
    step_op="pcr_enrichment_round1_cleanup",
    description="material moves between wells via aerosol, splash, or a reused tip",
    observable=Observable.INVISIBLE,
    declared_detection=Detection.DATA_ANALYSIS,
    declared_latency=Latency.AFTER_SEQUENCING,
    severity=Severity.RUN,
    response=Decision.ABORT,
    note="only separable in the data, and only if the plate carried negative controls",
  ),
  FailureMode(
    name="index_misassignment",
    step_op="library_pool",
    description="reads are attributed to the wrong well through index hopping or a plating error",
    observable=Observable.INVISIBLE,
    declared_detection=Detection.DATA_ANALYSIS,
    declared_latency=Latency.AFTER_SEQUENCING,
    severity=Severity.RUN,
    response=Decision.ABORT,
    note="unique dual indices bound it; nothing in the physical layer detects it",
  ),
  FailureMode(
    name="star_resource_busy",
    step_op="wgs_prep_lysis",
    description="a second driver process opens the STAR and the USB claim fails",
    observable=Observable.INVISIBLE,
    declared_detection=Detection.INSTRUMENT,
    declared_latency=Latency.IMMEDIATE,
    severity=Severity.RECOVERABLE,
    response=Decision.RETRY,
    note=(
      "loud and safe: USBError [Errno 16] Resource busy, raised before anything moves. "
      "This is what a good failure looks like"
    ),
  ),
  FailureMode(
    name="odtc_callback_theft",
    step_op="pcr_enrichment_round1",
    description=(
      "a second process re-registers the ODTC event receiver and silently takes over the "
      "first process's callbacks"
    ),
    observable=Observable.INVISIBLE,
    declared_detection=Detection.NONE,
    declared_latency=Latency.NEVER,
    severity=Severity.SAMPLE,
    response=Decision.ESCALATE,
    note=(
      "the counterexample to star_resource_busy and the reason ONE_PROCESS_PER_INSTRUMENT "
      "is a hard constraint rather than a style rule. Nothing raises. The first process "
      "waits forever for a thermal-complete event that is being delivered elsewhere, while "
      "the plate sits in a block whose actual state nobody is tracking"
    ),
  ),
  FailureMode(
    name="tecan_read_timeout",
    step_op="read_absorbance",
    description="the reader accepts the scan command and never answers it",
    observable=Observable.INVISIBLE,
    declared_detection=Detection.INSTRUMENT,
    declared_latency=Latency.IMMEDIATE,
    severity=Severity.RECOVERABLE,
    response=Decision.ESCALATE,
    note=(
      "not hypothetical: this is the BROKEN run card in the registry, reproducible 2 of 2. "
      "It fails loudly, which is the only good thing about it. Escalates rather than "
      "retries because it is deterministic -- a retry loop here spins forever"
    ),
  ),
  FailureMode(
    name="flow_cell_misloaded",
    step_op="manual_load",
    description="the flow cell is not fully latched or a reagent bottle is in the wrong position",
    observable=Observable.VISIBLE,
    declared_detection=Detection.OPERATOR,
    declared_latency=Latency.IMMEDIATE,
    severity=Severity.RUN,
    response=Decision.ABORT,
  ),
)


FAILURES_BY_NAME: Dict[str, FailureMode] = {f.name: f for f in FAILURE_MODES}


def failures_for(step_op: str) -> Tuple[FailureMode, ...]:
  return tuple(f for f in FAILURE_MODES if f.step_op == step_op)


def effective(
  failure: FailureMode,
  gate_report_: Optional[GateReport] = None,
  capability: Optional[VisionCapability] = None,
) -> EffectiveDetection:
  """Resolve a failure's declared detection path against what this lab actually has.

  Each declared path is checked for whether it exists:

    VISION     needs a validated visual check that is available in this workcell.
    QC_GATE    needs the named gate to be evaluable -- which, in this repo, none are.
    INSTRUMENT is believed as declared: an instrument that raises does so regardless of
               what else is wired, and this repo has hardware evidence for both cases.
    OPERATOR   is believed only when the failure is visible; asking a human to notice an
               invisible condition is not a detection path, it is a wish.
    DATA_ANALYSIS is believed, with its cost already priced in by AFTER_SEQUENCING.

  A path that does not exist downgrades the latency to NEVER rather than leaving the
  declared value in place. That downgrade is the whole point of the function.
  """
  cap = capability or VisionCapability.none()
  d = failure.declared_detection

  if d is Detection.VISION:
    check = check_catching(failure.name)
    if check is None:
      return EffectiveDetection(
        failure, Detection.NONE, Latency.NEVER,
        "the plan says a camera catches it, but no visual check is declared for it",
      )
    if not cap.available(check):
      missing = cap.missing_for(check)
      detail = ", ".join(m.value for m in missing) if missing else "the condition is not imageable"
      return EffectiveDetection(
        failure, Detection.NONE, Latency.NEVER,
        f"the plan says vision catches it, but '{check.name}' is unavailable: missing {detail}",
      )
    return EffectiveDetection(
      failure, Detection.VISION, failure.declared_latency,
      f"'{check.name}' is available and validated in this workcell",
    )

  if d is Detection.QC_GATE:
    if gate_report_ is None:
      return EffectiveDetection(
        failure, Detection.QC_GATE, failure.declared_latency,
        "no gate report supplied; the declared path is taken on trust",
      )
    row = next((r for r in gate_report_.rows if r.gate.name == failure.via_gate), None)
    if row is None:
      return EffectiveDetection(
        failure, Detection.NONE, Latency.NEVER,
        f"the plan says gate '{failure.via_gate}' catches it, but that gate is not on this protocol",
      )
    if not row.evaluable:
      return EffectiveDetection(
        failure, Detection.NONE, Latency.NEVER,
        f"the plan says gate '{row.gate.name}' catches it, but that gate is unsatisfiable: {row.reason}",
      )
    return EffectiveDetection(
      failure, Detection.QC_GATE, failure.declared_latency,
      f"gate '{row.gate.name}' is evaluable and would reveal it",
    )

  if d is Detection.OPERATOR and failure.observable is Observable.INVISIBLE:
    return EffectiveDetection(
      failure, Detection.NONE, Latency.NEVER,
      "the plan relies on an operator noticing a condition that is not visible to anyone",
    )

  if d is Detection.NONE:
    return EffectiveDetection(
      failure, Detection.NONE, Latency.NEVER,
      failure.note or "no detection path is claimed for this failure",
    )

  return EffectiveDetection(
    failure, d, failure.declared_latency, f"declared {d.value} path is intact"
  )


@dataclass
class RecoveryReport:
  """Every failure mode on a protocol, resolved against this lab."""

  protocol: str
  rows: List[EffectiveDetection]

  def silent(self) -> List[EffectiveDetection]:
    return [r for r in self.rows if r.silent]

  def destructive_and_silent(self) -> List[EffectiveDetection]:
    """Destroys material, and nothing in this lab would ever notice."""
    return [r for r in self.rows if r.destructive_and_silent]

  def degraded(self) -> List[EffectiveDetection]:
    """Failures whose real detection is worse than the plan claims."""
    return [r for r in self.rows if r.degraded]

  def unreachable_by_vision(self) -> List[EffectiveDetection]:
    """Silent failures that buying cameras would not fix.

    Reported separately because the natural response to a list of undetected failures is
    to buy a camera, and for these that is money spent on the wrong sensor.
    """
    return [r for r in self.rows if r.silent and r.failure.observable is Observable.INVISIBLE]

  def counts(self) -> Dict[str, int]:
    return {
      "total": len(self.rows),
      "silent": len(self.silent()),
      "destructive_and_silent": len(self.destructive_and_silent()),
      "degraded": len(self.degraded()),
      "vision_would_not_help": len(self.unreachable_by_vision()),
    }


def recovery_report(
  protocol,
  gate_report_: Optional[GateReport] = None,
  capability: Optional[VisionCapability] = None,
) -> RecoveryReport:
  """Resolve every failure mode that applies to a protocol's steps.

  Scoped to the steps the protocol actually contains, so a failure mode belonging to a
  different flow does not inflate the count.
  """
  ops = {s.op for s in protocol.steps}
  rows = [
    effective(f, gate_report_, capability) for f in FAILURE_MODES if f.step_op in ops
  ]
  return RecoveryReport(protocol=protocol.name, rows=rows)


def visual_checks_that_would_help(report: RecoveryReport) -> List[str]:
  """Visual checks that would convert a currently-silent failure into a caught one.

  This is the camera shopping list, ranked by what it buys rather than by what is easy to
  install. A check appears here only if the failure it catches is currently silent AND the
  condition is imageable at all.
  """
  out: List[str] = []
  for row in report.silent():
    if row.failure.observable is Observable.INVISIBLE:
      continue
    check = check_catching(row.failure.name)
    if check is not None and check.name not in out:
      out.append(check.name)
  return out


__all__ = [
  "CHECKS_BY_NAME",
  "Detection",
  "EffectiveDetection",
  "FAILURES_BY_NAME",
  "FAILURE_MODES",
  "FailureMode",
  "Latency",
  "RecoveryReport",
  "Severity",
  "effective",
  "failures_for",
  "recovery_report",
  "visual_checks_that_would_help",
]
