"""The tacit layer: what a senior scientist knows that the protocol does not say.

A written protocol is not what an experienced scientist does. It is the subset of what they
do that survived being written down. The rest -- when a result is real, when a sample is
still recoverable, when a clean-looking plate should be thrown away -- lives in one head,
gets applied a hundred times a week, and is the actual thing that fails to transfer when a
lab automates. Encoding it is the entire product thesis of this repo, so this module holds
it explicitly rather than leaving it in prose.

Two kinds of thing live here.

A JUDGMENT is a conditional a scientist applies at the bench: given this observation, do
this. Every one carries the basis it rests on and whether this lab has validated it. The
uncomfortable and correct result is that most are INTUITION -- true, useful, load-bearing,
and unvalidated. Recording that honestly is what makes them improvable. A judgment stored
without its basis is indistinguishable from a rule, and a lab that cannot tell a rule from
a hunch cannot revise either.

A BENCHMARK is the thing that has to be true before a robot is trusted with a task. This is
the part usually skipped between "the script runs" and "we use it for real data". A liquid
handler that executes a 2 uL transfer perfectly on the first try has demonstrated nothing
until someone has measured its CV across a plate, and the difference between those two
states is the difference between a demo and an assay. `trusted_for()` answers whether an
operation has a met benchmark, and it answers no for almost everything here.

The capstone is `loop_closure()`. An autonomous lab has to do four things to close a single
hypothesis-to-evidence loop: EXECUTE the experiment, MEASURE the result, DECIDE what
follows, and RECORD it well enough to replay. Three of those are usually assumed. This
function checks all four against the real ledger, the real gates, and the real custody
chain, and names the leg that breaks. For the genomics protocol every leg breaks, and they
break for four different reasons -- which is more useful than a single autonomy percentage,
because each names a different next action.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .qc import MEASUREMENTS, Basis, GateReport
from .recovery import RecoveryReport
from .vision import Observable


class BenchmarkStatus(str, Enum):
  """Whether a robot has earned the right to do a task unattended."""

  MET = "met"  # measured, and it passed
  UNMET = "unmet"  # measured, and it did not pass
  UNMEASURED = "unmeasured"  # nobody has run the measurement

  @property
  def trusted(self) -> bool:
    return self is BenchmarkStatus.MET


@dataclass(frozen=True)
class Benchmark:
  """A measurable target standing between a script that runs and a task that is trusted.

  `observable` records whether the property can be seen at all, which is what connects
  benchmarks to the vision taxonomy. The benchmarks that matter most for low-input work --
  volumetric accuracy, thermal uniformity, carryover -- are all INVISIBLE, so no camera
  retires them. They need a dedicated calibration experiment, and saying so is the point.
  """

  name: str
  op: str  # the operation this benchmark qualifies
  target: str  # what has to be true, in measurable terms
  status: BenchmarkStatus
  observable: Observable
  evidence: str = ""
  how_to_measure: str = ""


@dataclass(frozen=True)
class Judgment:
  """One piece of tacit expert reasoning, written down.

  `when` and `then` are prose on purpose. This module's job is to make tacit knowledge
  explicit and attributable, not to pretend it is executable: a judgment that could be
  safely compiled into a rule would already be in the protocol. The value is that it is
  recorded, sourced, and marked validated or not, so it can be argued with and tested.
  """

  name: str
  when: str  # the observation
  then: str  # what the scientist does
  because: str  # the mechanism; why the rule is not arbitrary
  basis: Basis
  # The failure mode this judgment guards against, where it maps to one. Links tacit
  # knowledge to the failure model rather than leaving it as unattached wisdom.
  guards: Optional[str] = None

  @property
  def validated(self) -> bool:
    return self.basis.validated


# -- the tacit knowledge of a low-input genomics bench -------------------------
# Every one of these is a real decision made routinely and written in no protocol.

JUDGMENTS: Tuple[Judgment, ...] = (
  Judgment(
    name="diffuse_pellet_means_rebind",
    when="the bead pellet looks diffuse or smeared rather than tight after the magnet step",
    then="do not proceed to elution; add binding buffer and re-collect on the magnet",
    because=(
      "a diffuse pellet means the beads have not fully collected, so aspirating the "
      "supernatant now removes library along with it. Eluting a partial pellet gives a low "
      "yield that looks like a failed reaction rather than a failed cleanup, and the two "
      "have opposite fixes"
    ),
    basis=Basis.INTUITION,
    guards="bead_pellet_aspirated",
  ),
  Judgment(
    name="sort_duration_bounds_comparability",
    when="a sort runs materially longer than usual for the same cell count",
    then="treat the last-sorted wells as a different condition from the first, or re-sort",
    because=(
      "cells sitting in the sheath and in the source tube are changing the whole time. A "
      "long sort turns one experiment into a time course nobody designed, and the effect "
      "loads onto plate position, which is exactly where a batch effect hides"
    ),
    basis=Basis.LITERATURE,
  ),
  Judgment(
    name="column_wise_failure_is_hardware",
    when="wells fail in a column-wise or channel-wise pattern rather than at random",
    then="stop and inspect the instrument before repeating any biology",
    because=(
      "biology fails randomly across a plate; hardware fails geometrically. A whole column "
      "failing is a channel, a tip, or a deck position, and repeating the prep will "
      "reproduce it exactly. This single pattern distinction saves more material than any "
      "other rule here"
    ),
    basis=Basis.IN_HOUSE,
  ),
  Judgment(
    name="signal_in_negative_invalidates_plate",
    when="the no-template control shows any product",
    then="discard the whole plate, not just the control well",
    because=(
      "contamination is not local. A control showing product means the contaminating "
      "material was present during setup, so every well saw it; the other wells simply had "
      "real template to compete with it. Keeping the wells that 'look fine' is how a "
      "contaminated dataset gets published"
    ),
    basis=Basis.IN_HOUSE,
  ),
  Judgment(
    name="quant_without_size_is_not_a_library",
    when="a library quantifies at an acceptable concentration",
    then="do not pool it until the size distribution has been checked",
    because=(
      "adapter dimer quantifies beautifully and sequences to nothing useful. Concentration "
      "alone cannot distinguish a good library from a tube of dimer, and dimer "
      "preferentially clusters, so it takes over the flow cell"
    ),
    basis=Basis.VENDOR,
    guards="bead_pellet_aspirated",
  ),
  Judgment(
    name="never_refreeze_the_enzyme_mix",
    when="an enzyme master mix has been thawed once already",
    then="discard it rather than returning it to the freezer",
    because=(
      "activity loss across freeze-thaw is real, gradual, and invisible. The failure it "
      "causes appears as a modest yield drop that gets attributed to the sample, which "
      "means the actual cause is never found"
    ),
    basis=Basis.VENDOR,
    guards="enzyme_activity_lost",
  ),
  Judgment(
    name="low_input_needs_fluorometric_quant",
    when="quantifying a library built from single-cell or otherwise picogram input",
    then="use a fluorometric or qPCR method; do not trust A260",
    because=(
      "A260 counts every nucleic acid in the well, including carrier, primer, and free "
      "nucleotide. At this input those dominate, so the reading is precise, reproducible, "
      "and not about the library. This is the judgment that makes the plate reader the "
      "wrong instrument for this assay even when it works"
    ),
    basis=Basis.IN_HOUSE,
  ),
  Judgment(
    name="one_driver_process_per_instrument",
    when="scheduling any two operations against the same instrument",
    then="serialize them; never open a second driver process",
    because=(
      "the STAR raises USBError [Errno 16] and stops, which is survivable. The ODTC does "
      "not: a second process re-registers the event receiver and silently steals the "
      "first's callbacks, so the first waits forever on a plate whose real state nobody is "
      "tracking. The quiet failure is the dangerous one"
    ),
    basis=Basis.IN_HOUSE,
    guards="odtc_callback_theft",
  ),
)


JUDGMENTS_BY_NAME: Dict[str, Judgment] = {j.name: j for j in JUDGMENTS}


# -- what a robot must prove before it is trusted -------------------------------

BENCHMARKS: Tuple[Benchmark, ...] = (
  Benchmark(
    name="low_volume_pipetting_cv",
    op="wgs_prep_lysis",
    target="coefficient of variation below 5 percent across a full plate at the working volume",
    status=BenchmarkStatus.UNMEASURED,
    observable=Observable.INVISIBLE,
    how_to_measure=(
      "gravimetric or dye-based measurement across all 96 positions, at the volume actually "
      "used, with the tips actually used. No camera substitutes for this"
    ),
    evidence="dry motion is validated; volumetric accuracy has never been measured",
  ),
  Benchmark(
    name="iswap_plate_transfer_repeatability",
    op="iswap_to_hhs",
    target="repeatable pickup and placement across consecutive transfers",
    status=BenchmarkStatus.MET,
    observable=Observable.VISIBLE,
    evidence="6 of 6 transfers clean, pickup landed at z 0.950 every time",
  ),
  Benchmark(
    name="tecan_tray_cycle_timing",
    op="tray_cycle",
    target="a bounded, known worst case for the drawer, for handoff scheduling",
    status=BenchmarkStatus.MET,
    observable=Observable.VISIBLE,
    evidence=(
      "five clean cycles on starpi2 2026-07-16; close stable at 3.6 s, open bimodal 3.2 s "
      "vs 5.3 s. Bounded, so schedulable, provided the worst case is budgeted"
    ),
  ),
  Benchmark(
    name="tecan_absorbance_read",
    op="read_absorbance",
    target="returns a complete OD matrix for a 96-well plate",
    status=BenchmarkStatus.UNMET,
    observable=Observable.INVISIBLE,
    evidence=(
      "FAILED on the instrument from starpi2 2026-07-16: TimeoutError on 'ABSOLUTE MTP,Y=', "
      "deterministic 2 of 2. The reader has never returned an OD matrix"
    ),
    how_to_measure="read a plate; the benchmark is currently blocked by the defect, not unmeasured",
  ),
  Benchmark(
    name="odtc_thermal_uniformity",
    op="pcr_enrichment_round1",
    target="well-to-well temperature spread within the block's specification, door closed",
    status=BenchmarkStatus.UNMEASURED,
    observable=Observable.INVISIBLE,
    how_to_measure="a calibrated thermal plate, or an amplification uniformity experiment across the block",
    evidence=(
      "cycling was observed on hardware, but the choreography does not close the door "
      "around the thermal leg, so any uniformity number measured today would not describe "
      "the intended configuration"
    ),
  ),
  Benchmark(
    name="bead_retention_through_wash",
    op="pcr_enrichment_round1_cleanup",
    target="measured recovery through the full bead protocol, with a known loss distribution",
    status=BenchmarkStatus.UNMEASURED,
    observable=Observable.VISIBLE_INDIRECT,
    how_to_measure="a spike-in of known quantity through the full cleanup, quantified at both ends",
    evidence="the state machine is written and dry-validated; it has never run wet",
  ),
  Benchmark(
    name="sort_well_occupancy",
    op="start_sort",
    target="measured single-cell occupancy across a plate, with the empty-well rate known",
    status=BenchmarkStatus.UNMEASURED,
    observable=Observable.VISIBLE_INDIRECT,
    how_to_measure="imaging or an amplification-based readout on a full plate of a known cell line",
    evidence="the command set is undecoded; the instrument cannot be driven at all yet",
  ),
)


BENCHMARKS_BY_OP: Dict[str, List[Benchmark]] = {}
for _b in BENCHMARKS:
  BENCHMARKS_BY_OP.setdefault(_b.op, []).append(_b)


def trusted_for(op: str) -> Tuple[bool, str]:
  """Has this operation earned unattended execution?

  A missing benchmark is not a pass. An operation nobody has benchmarked is untrusted by
  default, which is the opposite of the usual convention and the correct one: the absence
  of a measurement is not evidence of adequacy.
  """
  bench = BENCHMARKS_BY_OP.get(op)
  if not bench:
    return False, f"no benchmark is declared for '{op}'; an unmeasured operation is not a trusted one"
  unmet = [b for b in bench if not b.status.trusted]
  if unmet:
    names = ", ".join(f"{b.name} ({b.status.value})" for b in unmet)
    return False, f"benchmark not met: {names}"
  return True, f"all {len(bench)} benchmark(s) met"


# -- loop closure ---------------------------------------------------------------


class Leg(str, Enum):
  """The four things a lab must do to close one hypothesis-to-evidence loop."""

  EXECUTE = "execute"  # perform the experiment
  MEASURE = "measure"  # obtain a result that means something
  DECIDE = "decide"  # conclude what follows, defensibly
  RECORD = "record"  # capture it well enough to replay and audit


@dataclass(frozen=True)
class LegStatus:
  leg: Leg
  ok: bool
  reason: str


@dataclass
class LoopClosure:
  """Whether this lab can close a loop on a protocol, and which leg breaks.

  The value over a single autonomy percentage is that each broken leg implies a different
  next action: EXECUTE means reverse-engineering, MEASURE means an instrument that works,
  DECIDE means a gate whose input exists, RECORD means barcodes or an arm. A lab that only
  tracks autonomy will spend all four budgets on the first one.
  """

  protocol: str
  legs: List[LegStatus]

  @property
  def closes(self) -> bool:
    return all(leg.ok for leg in self.legs)

  def broken(self) -> List[LegStatus]:
    return [leg for leg in self.legs if not leg.ok]


def loop_closure(
  ledger,
  gates: GateReport,
  recovery: RecoveryReport,
  provenance,
) -> LoopClosure:
  """Check all four legs against real computed state.

  Every input is a report computed elsewhere. Nothing is re-derived here, so this cannot
  disagree with the ledger, the gate readiness, or the custody chain -- it only combines
  them.
  """
  legs: List[LegStatus] = []

  # EXECUTE: an unattended run has to reach the end.
  prefix = ledger.headless_prefix()
  total = len(ledger.rows)
  legs.append(
    LegStatus(
      Leg.EXECUTE,
      prefix == total,
      f"an unattended run reaches step {prefix} of {total}"
      + ("" if prefix == total else f"; it stops at '{ledger.first_stop().step.op}'"),
    )
  )

  # MEASURE: the gates need inputs that actually arrive, from an appropriate assay.
  unsat = gates.unsatisfiable()
  wrong_assay = gates.inappropriate(MEASUREMENTS)
  if not gates.rows:
    measure_ok, measure_why = False, "this protocol declares no QC gates, so no result is checked at all"
  elif unsat:
    measure_ok = False
    measure_why = (
      f"{len(unsat)} of {len(gates.rows)} gate(s) cannot be evaluated: "
      + "; ".join(g.gate.name for g in unsat)
    )
  elif wrong_assay:
    measure_ok = False
    measure_why = (
      f"{len(wrong_assay)} gate(s) rest on a measurement that is the wrong assay for the sample"
    )
  else:
    measure_ok, measure_why = True, f"all {len(gates.rows)} gate(s) can be evaluated"
  legs.append(LegStatus(Leg.MEASURE, measure_ok, measure_why))

  # DECIDE: a decision is only defensible if the failures it must react to are detectable.
  silent = recovery.destructive_and_silent()
  legs.append(
    LegStatus(
      Leg.DECIDE,
      not silent,
      f"all {len(recovery.rows)} failure mode(s) have a detection path"
      if not silent
      else (
        f"{len(silent)} failure mode(s) destroy material with nothing in this lab to notice: "
        + ", ".join(r.failure.name for r in silent)
      ),
    )
  )

  # RECORD: the chain has to survive the physical hops.
  legs.append(
    LegStatus(
      Leg.RECORD,
      provenance.unbroken,
      "the custody chain is unbroken"
      if provenance.unbroken
      else f"{len(provenance.gaps)} unobserved custody transfer(s); the record's identity claim is an assertion",
    )
  )

  return LoopClosure(protocol=ledger.protocol.name, legs=legs)


def knowledge_summary() -> Dict[str, int]:
  """How much of the encoded expert knowledge this lab has actually validated."""
  return {
    "judgments": len(JUDGMENTS),
    "judgments_validated": sum(1 for j in JUDGMENTS if j.validated),
    "benchmarks": len(BENCHMARKS),
    "benchmarks_met": sum(1 for b in BENCHMARKS if b.status.trusted),
    "benchmarks_unmeasured": sum(1 for b in BENCHMARKS if b.status is BenchmarkStatus.UNMEASURED),
    "benchmarks_failed": sum(1 for b in BENCHMARKS if b.status is BenchmarkStatus.UNMET),
  }


def unvalidated_judgments() -> List[Judgment]:
  """Expert rules this lab acts on and has never tested.

  Not a criticism. This is the normal state of a working bench and the reason the tacit
  layer is worth writing down at all: an unwritten rule cannot be validated, and a written
  one can be put in a queue.
  """
  return [j for j in JUDGMENTS if not j.validated]


def untrusted_ops(protocol) -> List[Tuple[str, str]]:
  """(op, reason) for every step in a protocol whose benchmark is not met.

  Deliberately includes steps the ledger already calls blocked. The two questions are
  independent: 'can the machine perform this' and 'has it earned the right to' fail for
  different reasons and are fixed by different work.
  """
  out: List[Tuple[str, str]] = []
  seen = set()
  for step in protocol.steps:
    if step.op in seen:
      continue
    seen.add(step.op)
    ok, why = trusted_for(step.op)
    if not ok:
      out.append((step.op, why))
  return out


__all__ = [
  "BENCHMARKS",
  "BENCHMARKS_BY_OP",
  "Benchmark",
  "BenchmarkStatus",
  "JUDGMENTS",
  "JUDGMENTS_BY_NAME",
  "Judgment",
  "Leg",
  "LegStatus",
  "LoopClosure",
  "knowledge_summary",
  "loop_closure",
  "trusted_for",
  "untrusted_ops",
  "unvalidated_judgments",
]
