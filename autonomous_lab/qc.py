"""Acceptance criteria, QC gates, and whether this lab can evaluate them at all.

The ledger answers "can the machine perform this step". This module answers the question
that comes immediately after and is the harder one: "can the lab decide what to do with
the result". A robot that executes a protocol flawlessly and cannot tell a good plate from
a bad one is not running an experiment, it is moving liquid.

A gate is a set of criteria evaluated against measurements produced by earlier steps. It
returns a Decision -- continue, retry, recover, escalate, abort -- and that decision is the
actual product of this layer. Everything else is bookkeeping around it.

The load-bearing idea here is READINESS, and it is the same idea as the ledger's verdicts
pointed at data instead of motion. A gate can be perfectly specified and still be
unevaluable, because the measurement it reads comes from a step that is blocked, manual, or
broken. That is not a hypothetical:

  The single-cell genomics protocol quantifies its pooled library on the Tecan Infinite
  200 PRO before committing a flow cell. The Tecan's absorbance read is BROKEN -- written,
  run on the instrument, and it times out deterministically. So the library-quant gate,
  which is the one gate standing between this lab and a wasted flow cell, cannot fire. Not
  "fires with low confidence". Cannot be evaluated at all.

A QC gate whose input never arrives is worse than no gate, because a run configured with
one looks supervised on paper. `readiness()` exists so that never goes unnoticed, and
`unsatisfiable()` is what a planner should call before it believes a protocol is gated.

The second idea is that a threshold is a scientific claim and carries its BASIS. A cutoff
copied from a kit insert, a cutoff derived from this lab's own titration, and a cutoff a
senior scientist believes are three different kinds of thing, and a lab that stores them
identically has thrown away the only information that would let it revise one. Basis is
recorded per criterion and `unvalidated()` lists the ones resting on nothing but judgment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .model import Verdict


class Basis(str, Enum):
  """Where a threshold came from. Ordered weakest to strongest.

  This is not decoration. A lab that cannot say why a cutoff is 0.8 cannot revise it when
  the assay changes, and cannot defend it when a reviewer asks. The weakest two are the
  common case in real labs and pretending otherwise is how tacit knowledge stays tacit.
  """

  INTUITION = "intuition"  # a scientist believes it; nothing written down
  VENDOR = "vendor"  # a kit insert or instrument manual says so
  LITERATURE = "literature"  # published, but not on this assay in this lab
  IN_HOUSE = "in_house"  # derived from this lab's own titration or control data

  @property
  def validated(self) -> bool:
    """True only for a threshold this lab earned with its own data.

    VENDOR and LITERATURE are deliberately excluded. Both are real evidence and neither is
    evidence about THIS assay on THIS input, which is the whole difficulty of low-input
    work: the kit insert's cutoff was established at nanograms and the sample here is
    picograms.
    """
    return self is Basis.IN_HOUSE


class Comparison(str, Enum):
  AT_LEAST = "at_least"
  AT_MOST = "at_most"
  BETWEEN = "between"


class Decision(str, Enum):
  """What to do after a gate evaluates. The actual output of the intelligence layer.

  RETRY and RECOVER are different and the difference is physical. RETRY repeats the step
  on material that is still good. RECOVER runs a different, usually salvage, path because
  the material has changed state. Conflating them is how a lab burns a scarce sample by
  re-amplifying something that needed re-purification instead.
  """

  CONTINUE = "continue"  # criteria met; proceed
  RETRY = "retry"  # repeat the same step; material is still viable
  RECOVER = "recover"  # material changed state; run the salvage path
  ESCALATE = "escalate"  # a human decides; the machine has no defensible next action
  ABORT = "abort"  # stop; continuing would waste a scarce input or a flow cell


class Readiness(str, Enum):
  """Whether a gate can be evaluated at all in a given workcell."""

  READY = "ready"  # its measurement is produced by a step that runs today
  SUPERVISED = "supervised"  # produced, but only with a human at the instrument
  UNSATISFIABLE = "unsatisfiable"  # its input comes from a blocked, manual, or broken step

  @property
  def evaluable(self) -> bool:
    return self is not Readiness.UNSATISFIABLE


@dataclass(frozen=True)
class Measurement:
  """A named quantity a step produces.

  `produced_by` is the artifact name the protocol already uses, so readiness resolves
  through the existing protocol graph rather than a parallel table that could drift. A
  measurement nothing produces is caught the same way a dangling artifact is.

  `instrument_appropriate` is the field a naive QC layer would not have. An instrument can
  return a number that is real, precise, and the wrong measurement for the sample -- and a
  gate that reads it will pass confidently on a library that is not there. See
  LIBRARY_MOLARITY_OD below, which is exactly that case.
  """

  key: str
  units: str
  produced_by: str  # artifact name, as declared in the protocol
  note: str = ""
  instrument_appropriate: bool = True
  inappropriate_reason: str = ""


@dataclass(frozen=True)
class Criterion:
  """One threshold on one measurement, with the reason it is that number.

  `rationale` is prose and no checker reaches it, so it stays narrow and specific -- the
  same discipline the registry applies to its evidence strings. It is the tacit judgment
  this package exists to capture: not "concentration >= 0.5" but why 0.5, and what going
  below it actually means for the sample.
  """

  name: str
  measurement: str  # Measurement.key
  comparison: Comparison
  bound: float
  rationale: str
  basis: Basis
  upper: Optional[float] = None  # required for BETWEEN
  # What to do when this criterion alone fails. A gate takes the most severe response
  # among its failed criteria, so a criterion that means "the sample is gone" can force an
  # abort even when the others only suggest a retry.
  on_fail: Decision = Decision.ESCALATE

  def __post_init__(self) -> None:
    if self.comparison is Comparison.BETWEEN and self.upper is None:
      raise ValueError(f"criterion '{self.name}' is BETWEEN but declares no upper bound")
    if self.upper is not None and self.upper < self.bound:
      raise ValueError(f"criterion '{self.name}' has upper {self.upper} below lower {self.bound}")

  def passes(self, value: float) -> bool:
    if self.comparison is Comparison.AT_LEAST:
      return value >= self.bound
    if self.comparison is Comparison.AT_MOST:
      return value <= self.bound
    return self.bound <= value <= (self.upper if self.upper is not None else self.bound)

  def describe(self) -> str:
    if self.comparison is Comparison.AT_LEAST:
      return f"{self.measurement} >= {self.bound}"
    if self.comparison is Comparison.AT_MOST:
      return f"{self.measurement} <= {self.bound}"
    return f"{self.bound} <= {self.measurement} <= {self.upper}"


# Severity order for combining failed criteria. Later is more severe.
_SEVERITY: Tuple[Decision, ...] = (
  Decision.CONTINUE,
  Decision.RETRY,
  Decision.RECOVER,
  Decision.ESCALATE,
  Decision.ABORT,
)


@dataclass(frozen=True)
class Gate:
  """A checkpoint after a step: evaluate criteria, return a decision.

  `after_step` names the step op the gate follows, so a gate cannot be attached to a step
  that does not exist. `blocks` names what the gate protects -- the expensive, irreversible
  thing downstream that justifies stopping here. A gate that protects nothing is a log line
  and should not be a gate.
  """

  name: str
  after_step: str  # Step.op this gate follows
  criteria: Tuple[Criterion, ...]
  blocks: str  # what is protected by stopping here
  # When a measurement is missing entirely -- the instrument returned nothing, not a bad
  # number. Defaults to ESCALATE rather than CONTINUE: absence of evidence is the single
  # most common way an automated QC gate silently passes everything.
  on_missing: Decision = Decision.ESCALATE

  @property
  def measurements(self) -> Tuple[str, ...]:
    seen: List[str] = []
    for c in self.criteria:
      if c.measurement not in seen:
        seen.append(c.measurement)
    return tuple(seen)

  def unvalidated(self) -> Tuple[Criterion, ...]:
    """Criteria whose threshold this lab has not earned with its own data."""
    return tuple(c for c in self.criteria if not c.basis.validated)


@dataclass(frozen=True)
class GateResult:
  """One gate, evaluated against real numbers."""

  gate: Gate
  decision: Decision
  passed: Tuple[str, ...]
  failed: Tuple[str, ...]
  missing: Tuple[str, ...]
  reason: str

  @property
  def ok(self) -> bool:
    return self.decision is Decision.CONTINUE


def evaluate(gate: Gate, values: Dict[str, float]) -> GateResult:
  """Evaluate a gate against measured values.

  A missing measurement is never a pass. This is the whole reason the function exists
  rather than a comprehension at the call site: the natural implementation iterates the
  values it was given, and a gate written that way returns CONTINUE when the instrument
  returned nothing at all. That failure mode is silent, it looks like a clean run, and it
  is how a lab commits a flow cell to an empty library.
  """
  passed: List[str] = []
  failed: List[str] = []
  missing: List[str] = []
  worst = Decision.CONTINUE

  for c in gate.criteria:
    if c.measurement not in values:
      missing.append(c.measurement)
      if _SEVERITY.index(gate.on_missing) > _SEVERITY.index(worst):
        worst = gate.on_missing
      continue
    if c.passes(values[c.measurement]):
      passed.append(c.name)
    else:
      failed.append(c.name)
      if _SEVERITY.index(c.on_fail) > _SEVERITY.index(worst):
        worst = c.on_fail

  if missing:
    reason = f"no value for {', '.join(sorted(set(missing)))}; absence of a measurement is not a pass"
  elif failed:
    reason = f"failed {', '.join(failed)}"
  else:
    reason = f"all {len(passed)} criteria met"
  return GateResult(
    gate=gate,
    decision=worst,
    passed=tuple(passed),
    failed=tuple(failed),
    missing=tuple(missing),
    reason=reason,
  )


@dataclass(frozen=True)
class GateReadiness:
  """Whether a gate could fire today, and what stands in the way.

  This is the report that matters before a run, and it is computed from the ledger rather
  than asserted. A gate is only as evaluable as the step that feeds it.
  """

  gate: Gate
  readiness: Readiness
  reason: str
  blocking_steps: Tuple[str, ...] = ()

  @property
  def evaluable(self) -> bool:
    return self.readiness.evaluable


def readiness(gate: Gate, ledger, measurements: Dict[str, Measurement]) -> GateReadiness:
  """Can this gate be evaluated against the workcell the ledger was built for?

  Resolves each criterion's measurement to the artifact that carries it, finds the step
  that produces that artifact, and takes that step's verdict. The gate is only as good as
  its weakest input, so the worst verdict wins.

  Deliberately takes the built Ledger rather than a Workcell: the verdicts are the whole
  input, recomputing them here would be a second implementation of cost_step that could
  disagree with the first, and a QC layer that disagreed with the ledger about whether a
  step runs would be worse than no QC layer.
  """
  # artifact -> the verdict of the step that produces it
  producing: Dict[str, object] = {}
  for row in ledger.rows:
    for art in row.step.produces:
      producing[art] = row

  worst: Optional[Readiness] = None
  reasons: List[str] = []
  blocking: List[str] = []

  for key in gate.measurements:
    meas = measurements.get(key)
    if meas is None:
      return GateReadiness(
        gate,
        Readiness.UNSATISFIABLE,
        f"criterion reads '{key}', which is not a declared measurement",
      )
    row = producing.get(meas.produced_by)
    if row is None:
      return GateReadiness(
        gate,
        Readiness.UNSATISFIABLE,
        f"'{key}' comes from artifact '{meas.produced_by}', which no step in this protocol produces",
      )
    verdict = row.verdict
    if verdict is Verdict.AUTOMATED:
      this = Readiness.READY
    elif verdict is Verdict.SUPERVISED:
      this = Readiness.SUPERVISED
    else:
      this = Readiness.UNSATISFIABLE
      # Several criteria commonly read different measurements off the same step, and
      # repeating that step's whole reason once per criterion buries the finding in its
      # own evidence. Report each blocking step once.
      if row.step.op not in blocking:
        blocking.append(row.step.op)
        reasons.append(f"'{key}' needs {row.step.op}, which is {verdict.value}: {row.reason}")
    if worst is None or _READINESS_ORDER.index(this) > _READINESS_ORDER.index(worst):
      worst = this

  if worst is None:
    return GateReadiness(gate, Readiness.UNSATISFIABLE, "gate declares no criteria")
  if worst is Readiness.UNSATISFIABLE:
    return GateReadiness(gate, worst, "; ".join(reasons), tuple(blocking))
  if worst is Readiness.SUPERVISED:
    return GateReadiness(gate, worst, "every input is produced, but only with a human at the instrument")
  return GateReadiness(gate, worst, "every input is produced by a step that runs headless today")


# Worse is later, matching _SEVERITY's convention.
_READINESS_ORDER: Tuple[Readiness, ...] = (
  Readiness.READY,
  Readiness.SUPERVISED,
  Readiness.UNSATISFIABLE,
)


# -- the measurements and gates for the reference protocols --------------------
# These are the real checkpoints of a low-input genomics run, written out so the ledger
# can report whether this lab can actually enforce any of them. The answer is currently no,
# and that is the finding.

MEASUREMENTS: Dict[str, Measurement] = {
  "well_occupancy": Measurement(
    key="well_occupancy",
    units="fraction",
    produced_by="sorted_plate",
    note="fraction of target wells that received exactly one cell",
  ),
  "library_conc_od": Measurement(
    key="library_conc_od",
    units="ng/uL",
    produced_by="library_quant",
    note="A260-derived concentration from the plate reader",
    # The quiet failure this whole package is about, in one field. The Tecan can in
    # principle return a real, precise A260. For a single-cell library at picogram input
    # it is still the wrong measurement: A260 counts every nucleic acid in the well,
    # including the carrier, the primers, and the free dNTPs, and at this input those
    # dominate. The number is not noisy, it is confidently about the wrong thing.
    instrument_appropriate=False,
    inappropriate_reason=(
      "A260 does not discriminate library from primer, carrier, or free nucleotide, and "
      "at single-cell input those dominate the signal. A gate on this number passes an "
      "empty library. Fluorometric quantification or qPCR is the appropriate assay, and "
      "no instrument in this workcell performs either"
    ),
  ),
  "library_purity_260_280": Measurement(
    key="library_purity_260_280",
    units="ratio",
    produced_by="library_quant",
    note="A260/A280; a protein-contamination indicator, not a yield measurement",
  ),
  "run_yield_pf": Measurement(
    key="run_yield_pf",
    units="Gbp",
    produced_by="run_outcome",
    note="passing-filter yield, read off the AVITI run folder",
  ),
}


LIBRARY_QUANT_GATE = Gate(
  name="library_quant_before_flow_cell",
  after_step="read_absorbance",
  blocks="committing a flow cell and a sequencing run to an unquantified library",
  criteria=(
    Criterion(
      name="library_present",
      measurement="library_conc_od",
      comparison=Comparison.AT_LEAST,
      bound=0.5,
      rationale=(
        "below roughly 0.5 ng/uL there is not enough material to pool at a defensible "
        "molarity, and the run will be dominated by whichever wells happened to amplify. "
        "The number is a floor on usefulness, not a specification"
      ),
      basis=Basis.INTUITION,
      on_fail=Decision.ABORT,
    ),
    Criterion(
      name="not_protein_contaminated",
      measurement="library_purity_260_280",
      comparison=Comparison.BETWEEN,
      bound=1.7,
      upper=2.1,
      rationale=(
        "the standard nucleic-acid purity window. Outside it the A260 itself is suspect, "
        "so this criterion guards the other one rather than the sample"
      ),
      basis=Basis.VENDOR,
      on_fail=Decision.ESCALATE,
    ),
  ),
)


SORT_OCCUPANCY_GATE = Gate(
  name="sort_occupancy_before_amplification",
  after_step="wait_complete",
  blocks="spending amplification reagent and a STAR run on a plate that is mostly empty",
  criteria=(
    Criterion(
      name="enough_wells_occupied",
      measurement="well_occupancy",
      comparison=Comparison.AT_LEAST,
      bound=0.7,
      rationale=(
        "below about 70 percent the plate costs a full reagent set and a STAR run to "
        "return a fraction of the cells, and re-sorting is cheaper than amplifying empty "
        "wells. The threshold is a cost judgment, not a biological one"
      ),
      basis=Basis.INTUITION,
      on_fail=Decision.RETRY,
    ),
  ),
)


GATES: Dict[str, Gate] = {g.name: g for g in (SORT_OCCUPANCY_GATE, LIBRARY_QUANT_GATE)}

# Which gates belong to which reference protocol. Keyed by protocol name so a protocol
# without gates is visibly ungated rather than silently so.
PROTOCOL_GATES: Dict[str, Tuple[str, ...]] = {
  "single_cell_genomics": (SORT_OCCUPANCY_GATE.name, LIBRARY_QUANT_GATE.name),
  # No gates. The chemistry loop has no analytical step whose output feeds a decision in
  # this repo: the 6530 writes a chromatogram and nothing reads it back. Saying so is
  # better than inventing a threshold nobody uses.
  "small_molecule_qc": (),
}


@dataclass
class GateReport:
  """Every gate on a protocol, with whether it could fire."""

  protocol: str
  rows: List[GateReadiness] = field(default_factory=list)

  def unsatisfiable(self) -> List[GateReadiness]:
    return [r for r in self.rows if not r.evaluable]

  def inappropriate(self, measurements: Dict[str, Measurement]) -> List[Tuple[str, Measurement]]:
    """Gates resting on a measurement that is the wrong assay for the sample.

    Separate from readiness on purpose. An unsatisfiable gate fails loudly -- no number
    arrives. This one fails quietly: a number arrives, the gate passes, and the answer is
    wrong. Of the two, this is the one that wastes the flow cell.
    """
    out: List[Tuple[str, Measurement]] = []
    for row in self.rows:
      for key in row.gate.measurements:
        meas = measurements.get(key)
        if meas is not None and not meas.instrument_appropriate:
          out.append((row.gate.name, meas))
    return out

  def closes_the_loop(self) -> bool:
    """True only if every gate on this protocol can actually be evaluated.

    The name is the point. A lab that cannot evaluate its gates cannot close a
    hypothesis-to-evidence loop, however much of the protocol it can physically execute.
    """
    return bool(self.rows) and all(r.evaluable for r in self.rows)


def gate_report(protocol_name: str, ledger) -> GateReport:
  """Every gate declared for a protocol, costed for readiness against a real workcell."""
  names = PROTOCOL_GATES.get(protocol_name, ())
  report = GateReport(protocol=protocol_name)
  for name in names:
    report.rows.append(readiness(GATES[name], ledger, MEASUREMENTS))
  return report
