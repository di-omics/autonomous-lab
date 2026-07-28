"""Where vision and QC gates meet: for every failure that destroys material, what catches it.

Three layers in this package each hold a third of one answer and none of them can state it.
`vision` says what a camera can and cannot ever see, and INVISIBLE there is a claim about
physics rather than about model quality. `qc` says which gates exist and whether their
inputs arrive at all. `recovery` says which failures exist, what each one costs, and how
late its declared path would find it. A lab asks none of those questions on its own. It asks
one question, and nobody composes the three layers well enough to answer it: FOR EVERY
FAILURE THAT DESTROYS MATERIAL, IS THERE ANYTHING AT ALL THAT WOULD CATCH IT?

Composing them is not bookkeeping, because the two instruments are complementary rather than
alternative. Where a camera is physically incapable a gate is the ONLY remaining option, so
an INVISIBLE failure with no gate is uncovered and no CV budget ever changes that. In the
other direction, a failure a camera catches cheaply does not need an assay, and a lab that
buys one has spent wet-lab money on a problem a lens solves. Neither layer can tell those
two apart on its own. Telling them apart is what this module is for.

The composition also finds coverage that neither layer reports. `recovery` resolves each
failure's DECLARED path and nothing else, so bead_pellet_aspirated -- which declares a gate
-- comes back silent in that report whether or not a camera would see the pellet. A visual
check for exactly that condition is declared in `vision`. Asking vision directly instead of
through the declared path is what turns "the plan names a gate and the gate is dead" into "a
camera would hold this one, and here is precisely what the camera still needs".

THE RULE THIS MODULE EXISTS TO ENFORCE. A vision check that exists and is not deployable is
not coverage. A gate that exists and is UNSATISFIABLE is not coverage. A gate that is
evaluable and rests on the wrong assay for the sample is not coverage either, and that third
one is the quietest of the three: a number arrives, the gate passes, and the library was
never there. All three are the vacuous pass in a new costume. A plan that counts unbuilt
detectors and unevaluable gates reports a lab as covered while its material is being
destroyed silently -- and reports it in the exact language a reviewer would accept.

COVERED here means covered by something that works with nobody in the room, and only two
things qualify: a deployed and validated visual check, and a gate that fires headless on an
appropriate assay. An operator noticing is not coverage in a package about unattended
operation; it is the condition this whole package exists to remove, and a SUPERVISED gate is
that same operator holding a pipette in one hand and a screen in the other. Data analysis
after sequencing is not coverage of a sample either, because the flow cell is already spent
by the time it speaks. All of those are real all the same, so every row carries the path
`recovery` resolved, and nothing here ever claims that nothing anywhere would notice when a
sibling layer says something would. The claim is narrower and worth more: NO DECLARED
DETECTOR AND NO EVALUABLE GATE stands between this failure and the material. It is
deliberately not the broader claim that nothing machine-checkable does -- an instrument
raising USBError before it moves is machine-checkable and is not a detector this module
counts -- and `residual` is where an instrument-raised or post-hoc path is reported instead.

`sota_lift` is the buying decision. Given a better vision capability it reports which
failures move from uncovered to covered -- and, more prominently, which do not move at ANY
capability, because they are INVISIBLE. The second list is the point of the function.
Upgrading a model has a ceiling, the ceiling is physics rather than engineering, and a lab
reading only the first list will keep buying model upgrades against failures no model
resolves. A third list is required for the same reason the second one is: a real proposal is
partial, and a failure that a camera could reach and that THIS proposal does not reach is
neither lifted nor at the ceiling. Reported in neither list it disappears, and the report
becomes the purchase justification the second list was added to prevent.

`mandatory_gates` states the same fact from the other side, as a demand rather than a gap.
For an INVISIBLE failure that destroys material a gate is not one option among several; it
is the only one. Where that gate does not exist the report says a gate MUST exist, which is
a different sentence from "coverage is incomplete" and implies a different budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .ledger import build_ledger
from .qc import MEASUREMENTS, GateReport, Measurement, Readiness, gate_report
from .recovery import (
  FAILURE_MODES,
  Detection,
  EffectiveDetection,
  FailureMode,
  Latency,
  RecoveryReport,
  Severity,
  recovery_report,
)
from .vision import Observable, VisionCapability, VisionRequirement, check_catching


def _destroys_material(failure: FailureMode) -> bool:
  """Whether this failure destroys material, asked of the layer that draws that line.

  `recovery.EffectiveDetection.destructive_and_silent` already decides which severities count
  as destruction. Restating the severity set here would be a second definition of one line,
  and two definitions of one line eventually disagree -- invisibly, because both keep
  returning a plausible boolean. So the question is put to recovery in the only form recovery
  answers it: hold the latency at NEVER, which satisfies the silent half of its conjunction,
  and what the property reports back is the severity half on its own.
  """
  probe = EffectiveDetection(
    failure, Detection.NONE, Latency.NEVER, "a severity probe, not a finding about this lab"
  )
  return probe.destructive_and_silent


class GateStanding(str, Enum):
  """What a declared gate actually does for one failure in one workcell.

  A boolean would collapse six situations that call for six different actions, and two of
  the collapses are how a coverage report starts lying. The first is SUPERVISED read as
  evaluable: `qc.Readiness.evaluable` is true for it, because from qc's side the number does
  arrive, and it arrives with a human at the instrument -- which is the exact condition an
  unattended workcell is built to remove. The second is UNMEASURED read as appropriate: a
  gate whose measurement nobody declared has an unknown assay, and unknown is not a pass
  here any more than it is in `qc.evaluate`.

  DEAD and ABSENT are separated for the same reason `Uncovered` separates its two members.
  A dead gate is an instrument repair. A gate that is not on the protocol is an assay
  somebody still has to design, and the two are not the same budget.
  """

  COUNTS = "counts"  # evaluable with nobody in the room, on an assay that suits the sample
  SUPERVISED = "supervised"  # a number arrives, and only with a human at the instrument
  UNMEASURED = "unmeasured"  # the assay it reads was never declared, so it is unverified
  WRONG_ASSAY = "wrong_assay"  # a real, precise number about something other than the sample
  DEAD = "dead"  # unsatisfiable: no number arrives at all
  ABSENT = "absent"  # no gate on this protocol reads what this failure changes

  @property
  def counts_as_coverage(self) -> bool:
    """The load-bearing line: the one member that holds a failure with nobody in the room."""
    return self is GateStanding.COUNTS

  @property
  def reveals_the_failure(self) -> bool:
    """Whether the gate would surface THIS failure at all, coverage or not.

    SUPERVISED is the only member that is not coverage and still reveals: a person reads
    the number and the failure is found. That is why it is reported as a residual path
    rather than dropped -- the module refuses to count it and equally refuses to claim
    nobody would notice. WRONG_ASSAY is on the other side of the line and it is worth being
    precise about why: the number arrives, the gate passes, and it passes on an empty
    library, so the path does not merely fail to be unattended, it fails to detect.
    """
    return self in (GateStanding.COUNTS, GateStanding.SUPERVISED)


class Cover(str, Enum):
  """How a failure is actually caught in a given workcell.

  Only two instruments can put a member other than NEITHER on a row, and the restriction is
  deliberate. A visual check and a QC gate are the two things that keep working when the lab
  is running unattended, which is the only condition this package cares about. An operator's
  eye and a post-run analysis are real and are not this: one requires the human the lab is
  trying to do without, the other speaks after the flow cell is already spent.

  BOTH is not redundancy for its own sake. It is the only state where one instrument can go
  down -- a fouled lens, a reader out for service -- and the failure is still caught, which
  is a different property from being covered today and worth being able to see.
  """

  VISION = "vision"  # a declared visual check is deployed and validated here
  GATE = "gate"  # a declared gate fires headless and reads an appropriate assay
  BOTH = "both"  # either alone would hold it
  NEITHER = "neither"  # no camera and no gate; the row says which kind of nothing

  @property
  def covered(self) -> bool:
    """True where a deployed visual check or an evaluable gate stands before the material.

    Narrower than "something machine-checkable", and the narrowness is deliberate rather
    than an oversight. An instrument that raises before it moves is machine-checkable and
    is not one of these two; it is reported on the row as a residual path. A NEITHER row
    means no declared detector and no gate this module counts, never that the lab is blind.
    """
    return self is not Cover.NEITHER

  @property
  def closed_by(self) -> str:
    """What holds this failure, named -- or, for NEITHER, that nothing does.

    Prose rather than a structure because the caller printing a coverage table needs a
    phrase, and a phrase that says "covered" without naming the instrument is how a table
    survives an audit it should not survive.
    """
    if self is Cover.VISION:
      return "a deployed, validated visual check"
    if self is Cover.GATE:
      return (
        "a gate that fires with nobody at the instrument, reading an assay appropriate to "
        "the sample"
      )
    if self is Cover.BOTH:
      return (
        "a deployed visual check and a gate that fires unattended; either alone would hold it"
      )
    return "nothing; the row states whether a detector or a different instrument would close it"


class Uncovered(str, Enum):
  """Why a failure is uncovered. Two cases that produce the same NEITHER and are not alike.

  This distinction is the reason NEITHER is not the end of the analysis. Both cases print as
  an empty coverage cell and both feel like the same problem to whoever reads the report, and
  they have nothing in common except that appearance.

  UNCOVERED_FIXABLE is a detector nobody has built, or a gate whose input nobody has made
  arrive. The work is known, it is schedulable, and a capability upgrade or an instrument
  repair closes it.

  UNCOVERED_STRUCTURAL is a failure that is physically invisible AND that no declared assay
  reads. No camera resolves it at any model quality and no gate in the protocol looks at the
  quantity it changes, so the only fixes are a sensor this lab does not have or a protocol
  that never creates the condition. Spending a CV budget against one of these buys nothing,
  and a report that cannot tell the two apart will recommend exactly that.
  """

  FIXABLE = "uncovered_fixable"
  STRUCTURAL = "uncovered_structural"

  @property
  def needs_a_new_instrument(self) -> bool:
    """True only for STRUCTURAL: the line between schedulable work and a different sensor."""
    return self is Uncovered.STRUCTURAL


@dataclass(frozen=True)
class CoverageRow:
  """One failure, both instruments resolved against this workcell, and what closes the gap.

  Severity, Observable, the Cover, and the uncovered kind are all METHODS rather than fields.
  Every one of them is derivable from what is already stored, and a derived value kept beside
  the values it derives from eventually disagrees with them, with nothing to reveal which one
  is wrong. This matters more here than elsewhere in the package: a stored `cover` field would
  be an author-settable claim of coverage, which is precisely the thing the module exists to
  refuse.

  `effective` is what `recovery` computed for this failure and is never recomputed here. It is
  carried so that a NEITHER row can say what else, if anything, would surface the failure --
  the STAR raising USBError is real coverage of star_resource_busy and no camera is needed for
  it, and a report that demanded one would be noise.
  """

  failure: FailureMode
  effective: EffectiveDetection
  vision_check: Optional[str]  # the declared check that watches this failure, if any
  vision_deployable: bool  # exists AND every requirement is met in this workcell
  vision_reason: str
  gate: Optional[str]  # the declared gate that would reveal it, if any
  gate_standing: GateStanding  # what that gate does here: the six answers, not a boolean
  gate_reason: str

  @property
  def gate_evaluable(self) -> bool:
    """Whether the gate counts as coverage. Derived, so it cannot drift from the standing.

    Kept as a name because it is what a caller asks, and kept as a property because the
    two-valued answer is one reading of a six-valued fact and the six-valued fact is the
    one this module stores.
    """
    return self.gate_standing.counts_as_coverage

  @property
  def severity(self) -> Severity:
    return self.failure.severity

  @property
  def observable(self) -> Observable:
    return self.failure.observable

  @property
  def cover(self) -> Cover:
    """The composition, and the only place the two arms are combined.

    Both arms are already the strict form of their question -- exists AND is usable -- so
    this is a plain conjunction. It is written out rather than inlined at the call sites
    because a second combination of these two booleans somewhere else is how a report starts
    counting an unbuilt detector.
    """
    if self.vision_deployable and self.gate_evaluable:
      return Cover.BOTH
    if self.vision_deployable:
      return Cover.VISION
    if self.gate_evaluable:
      return Cover.GATE
    return Cover.NEITHER

  @property
  def uncovered(self) -> Optional[Uncovered]:
    """Which kind of nothing this is, or None when something holds it.

    STRUCTURAL requires both halves: no camera can ever see it, and no gate in this protocol
    reads what it changes. A failure that is invisible but that a declared gate reads is not
    structural, however dead that gate is today -- the assay exists, and repairing an
    instrument is a different budget from commissioning a sensor.
    """
    if self.cover.covered:
      return None
    if self.observable.reachable_by_vision:
      return Uncovered.FIXABLE
    if self.gate is None:
      return Uncovered.STRUCTURAL
    return Uncovered.FIXABLE

  @property
  def destroys_material(self) -> bool:
    return _destroys_material(self.failure)

  @property
  def residual(self) -> Optional[Detection]:
    """The path `recovery` resolved that this module does not count, where one survives.

    None when something already holds the failure, and None when recovery found nothing
    either. Anything else is a real path this module deliberately does not count as
    coverage, and reporting it is what keeps an uncovered row from being read as a claim
    that the failure is invisible to the entire lab.

    A path this row has already REFUSED is also None, and that is the difference between a
    residual and an excuse. `recovery` resolves the declared path against its own inputs,
    which are not always these: it takes a QC_GATE on trust when nobody handed it a gate
    report, and it asks only whether a gate can fire, not whether the number is about this
    sample. Republishing its answer beside a gate_reason that says the gate is unsatisfiable
    would put two computations of one fact on one row, disagreeing, with the reader left to
    pick. SUPERVISED survives here on purpose: that gate does reveal the failure, to a
    person, which is precisely a path worth naming and not worth counting.
    """
    if self.cover.covered or self.effective.silent:
      return None
    if self.effective.detection is Detection.QC_GATE:
      return self.effective.detection if self.gate_standing.reveals_the_failure else None
    if self.effective.detection is Detection.VISION and not self.vision_deployable:
      return None
    return self.effective.detection

  @property
  def unwatched(self) -> bool:
    """No camera, no gate, and nothing else either. The rows that should be read first.

    Asked of `residual` rather than of `effective.silent` directly, because a failure whose
    only remaining path this row just refused is unwatched in fact however loudly the plan
    claims otherwise.
    """
    return not self.cover.covered and self.residual is None

  def closes_it(self) -> str:
    """The next action that would put a machine check between this failure and the material.

    One sentence, specific enough to be scheduled. A coverage report whose remedy column reads
    "improve coverage" has handed the problem back to the reader with a number attached.
    """
    if self.cover.covered:
      return f"already held by {self.cover.closed_by}"

    if self.uncovered is Uncovered.STRUCTURAL:
      residual = self.residual
      if residual is not None:
        tail = (
          "; that is after the flow cell is spent, so it prices the loss rather than "
          "preventing it"
          if self.effective.latency is Latency.AFTER_SEQUENCING
          else ""
        )
        return (
          f"no camera resolves '{self.failure.name}' and no declared gate reads what it "
          f"changes. The only thing standing on it is the declared {residual.value} path, "
          f"which finds it {self.effective.latency.value}{tail}"
        )
      return (
        f"no camera resolves '{self.failure.name}' and no declared gate reads what it "
        f"changes, so nothing schedulable closes it: it needs a sensor this workcell does "
        f"not have, or a protocol that never creates the condition"
      )

    options: List[str] = []
    if self.observable.reachable_by_vision:
      if self.vision_check is not None:
        options.append(f"deploy '{self.vision_check}' -- {self.vision_reason}")
      else:
        options.append(
          "the condition is imageable and no visual check is declared for it; a check has to "
          "be written before a camera buys anything"
        )
    if self.gate is not None:
      options.append(f"make gate '{self.gate}' count -- {self.gate_reason}")
    if not options:
      # Unreachable while `uncovered` is computed as it is above. Kept because the alternative
      # to an explicit refusal is an empty remedy string, which reads as "nothing to do".
      return "uncovered, and this module cannot name what would close it"
    return "; or ".join(options)


@dataclass
class CoverageReport:
  """Every failure on a protocol, with both instruments resolved against one workcell."""

  protocol: str
  capability: VisionCapability
  rows: List[CoverageRow] = field(default_factory=list)

  def covered(self) -> List[CoverageRow]:
    return [r for r in self.rows if r.cover.covered]

  def uncovered(self) -> List[CoverageRow]:
    return [r for r in self.rows if not r.cover.covered]

  def fixable(self) -> List[CoverageRow]:
    return [r for r in self.rows if r.uncovered is Uncovered.FIXABLE]

  def structural(self) -> List[CoverageRow]:
    """Uncovered, and no capability or repair closes it. The re-instrument list."""
    return [r for r in self.rows if r.uncovered is Uncovered.STRUCTURAL]

  def uncovered_destructive(self) -> List[CoverageRow]:
    """Destroys material, and no camera or gate stands on it. The headline of the report.

    Ordered worst first, and never filtered by whether some other path exists. A row here
    whose residual path is an operator's eye still belongs here: the operator is the thing an
    autonomous lab removes, so a run-destroying failure held only by a person is a hole the
    moment the lab does what it was built to do.
    """
    out = [r for r in self.rows if not r.cover.covered and r.destroys_material]
    out.sort(key=lambda r: (not r.unwatched, r.failure.name))
    return out

  def unwatched(self) -> List[CoverageRow]:
    """No camera, no gate, and `recovery` found nothing else."""
    return [r for r in self.rows if r.unwatched]

  def destructive(self) -> List[CoverageRow]:
    """Every row whose failure destroys material, held or not. What `complete` is about."""
    return [r for r in self.rows if r.destroys_material]

  def in_scope(self) -> bool:
    """Whether this report contains anything for an all-clear to be an all-clear ABOUT.

    A report over rows none of which destroy material has no material-destroying failure
    left uncovered, and answering "complete" to that is the vacuous pass wearing the last
    costume this module had left. A row count does not test it: one row about a reader
    timing out is enough to make an empty destructive population look like a cleared one,
    and a caller scoping a report to a subprotocol gets an all-clear for a lab with no
    machine check anywhere.

    Separated rather than folded into `complete` because "nothing here destroys material"
    is a real and different verdict from "everything that does is held", the same way
    `Uncovered` splits one empty cell into two findings that imply different budgets.
    """
    return bool(self.destructive())

  def complete(self) -> bool:
    """True only when this report has material-destroying failures and all are held.

    Both halves are load-bearing. The second is the claim; the first is what keeps the
    claim from being earned by an empty population, which is the same bug this package
    chases everywhere else -- a check that passes because it was handed nothing. An empty
    report fails the first half, and so does a report that resolved only failures which
    cost time.
    """
    return self.in_scope() and not self.uncovered_destructive()

  def counts(self) -> Dict[str, int]:
    return {
      "total": len(self.rows),
      "covered": len(self.covered()),
      "destructive": len(self.destructive()),
      "vision": sum(1 for r in self.rows if r.cover is Cover.VISION),
      "gate": sum(1 for r in self.rows if r.cover is Cover.GATE),
      "both": sum(1 for r in self.rows if r.cover is Cover.BOTH),
      "uncovered": len(self.uncovered()),
      "uncovered_destructive": len(self.uncovered_destructive()),
      "fixable": len(self.fixable()),
      "structural": len(self.structural()),
      "unwatched": len(self.unwatched()),
    }


def _vision_arm(
  failure: FailureMode, capability: VisionCapability
) -> Tuple[Optional[str], bool, str]:
  """(check name, deployable, reason) for the camera side of one failure.

  Resolved through `vision.check_catching` rather than through the failure's declared
  detection path, and that is the whole reason this module exists. `recovery` consults vision
  only for failures whose PLAN names a camera, so a failure whose plan names a gate is
  reported silent even where a declared visual check would see it. bead_pellet_aspirated is
  exactly that case, and it is the most destructive routine failure in the protocol.

  Deployability is asked of `VisionCapability.available`, which already refuses an impossible
  check. Recomputing that test here would be a second opinion on a question vision owns.

  Observability is recorded twice in this package -- on the VisualCheck and on the
  FailureMode -- and this function is the only place the two records meet. `available`
  consults the check's; every consumer downstream of this row consults the failure's. So a
  disagreement is refused here rather than resolved, because resolving it would mean this
  module picking a winner between two siblings that each own their half of the fact, and a
  silent pick makes "can a camera ever see this" answerable two ways in one report.
  """
  check = check_catching(failure.name)
  if check is None:
    if failure.observable.reachable_by_vision:
      return None, False, "the condition is imageable and no visual check is declared for it"
    return None, False, "no camera resolves this condition at any model quality"
  if check.observable is not failure.observable:
    raise ValueError(
      f"vision and the failure model disagree about '{failure.name}': the check "
      f"'{check.name}' records it as {check.observable.value} while the failure mode "
      f"records it as {failure.observable.value}. Composing the two would let a deployed "
      f"check close a failure this package calls physically unreachable, or hold a ceiling "
      f"over one a camera sees. Correct it in vision or in recovery; coverage will not "
      f"choose between them."
    )
  if capability.available(check):
    return check.name, True, f"'{check.name}' is deployed and validated in this workcell"
  if not check.possible:
    return check.name, False, f"'{check.name}' watches a condition no camera resolves"
  missing = capability.missing_for(check)
  return (
    check.name,
    False,
    f"'{check.name}' is declared but not deployable: missing "
    + ", ".join(m.value for m in missing),
  )


def _gate_arm(
  failure: FailureMode, gates: GateReport, measurements: Dict[str, Measurement]
) -> Tuple[Optional[str], GateStanding, str]:
  """(gate name, standing, reason) for the assay side of one failure.

  Five ways a declared gate fails to be coverage, in increasing order of how quietly it
  does so. It may not be on this protocol at all. It may be UNSATISFIABLE, which at least
  fails loudly -- no number arrives. It may fire only with a human at the instrument, which
  is a real check and is not one this workcell has when it runs the way it was built to run.
  It may read a measurement nobody declared, in which case whether the assay suits the
  sample is unknown and unknown is not a pass. Or it may be evaluable and resting on a
  measurement that is the wrong assay, which is the one that spends the flow cell: the
  instrument returns a real, precise, reproducible number about something other than the
  library, and the gate passes on it.

  Every row bearing the name is resolved, not the first one. A report carrying two rows for
  one gate is malformed, and the failure mode of `next(...)` over a malformed report is that
  an optimistic duplicate placed above a dead one silences the dead one -- an author-settable
  field that silences a report, by ordering rather than by value. The worst row wins, which
  is also what `qc.GateReport.unsatisfiable` and `closes_the_loop` already say about the same
  object: a gate that is unsatisfiable in any row of the report is unsatisfiable.
  """
  name = failure.via_gate
  if name is None:
    return (
      None,
      GateStanding.ABSENT,
      "no gate on this protocol reads what this failure changes",
    )
  matches = [r for r in gates.rows if r.gate.name == name]
  if not matches:
    # The name is reported in the reason and deliberately NOT returned as the gate. A gate
    # that is not on this protocol reads nothing here, and returning its name would let the
    # uncovered classification treat a dangling reference as an assay that exists.
    return (
      None,
      GateStanding.ABSENT,
      f"the plan names '{name}' for this failure, and no such gate is on this protocol",
    )
  dead = next((r for r in matches if not r.evaluable), None)
  if dead is not None:
    return name, GateStanding.DEAD, f"'{name}' is unsatisfiable: {dead.reason}"
  attended = next((r for r in matches if r.readiness is not Readiness.READY), None)
  if attended is not None:
    return (
      name,
      GateStanding.SUPERVISED,
      f"'{name}' can be evaluated only with a human at the instrument, which is not coverage "
      f"in a workcell that runs unattended: {attended.reason}",
    )
  undeclared: List[str] = []
  for row in matches:
    for key in row.gate.measurements:
      if key not in measurements and key not in undeclared:
        undeclared.append(key)
  if undeclared:
    # `qc.GateReport.inappropriate` skips a key it cannot resolve, which is correct for the
    # question it answers -- it lists the assays known to be wrong -- and is fail-open for
    # the question asked here. Silence about an assay is not a statement that the assay
    # suits the sample, and converting it into one is the same bug as a gate evaluated
    # against an empty measurement dict passing every criterion it was never handed.
    return (
      name,
      GateStanding.UNMEASURED,
      f"'{name}' reads '{undeclared[0]}', which is not a declared measurement here, so "
      f"whether that assay suits this sample is unknown -- an unchecked assay is not an "
      f"appropriate one",
    )
  wrong = [m for gate_name, m in gates.inappropriate(measurements) if gate_name == name]
  if wrong:
    return (
      name,
      GateStanding.WRONG_ASSAY,
      f"'{name}' can be evaluated and rests on '{wrong[0].key}', which is the wrong assay "
      f"for this sample: {wrong[0].inappropriate_reason}",
    )
  return (
    name,
    GateStanding.COUNTS,
    f"'{name}' is evaluable and reads an assay appropriate to the sample",
  )


def coverage_report(
  protocol,
  ledger,
  gates: GateReport,
  recovery: RecoveryReport,
  vision_capability: Optional[VisionCapability] = None,
  measurements: Optional[Dict[str, Measurement]] = None,
) -> CoverageReport:
  """Compose the three layers into the answer a lab actually asks for.

  Every input is a report some other module already computed, and nothing here is
  re-derived: the failure list comes from `recovery`, gate readiness from `qc`, and
  deployability from `vision`. That is why this cannot disagree with any of them.

  It refuses three kinds of incoherent input rather than averaging over them. Reports about
  different protocols compose into a number about no lab at all. A recovery report built
  against a different vision capability than the one passed here does the same thing more
  quietly, because every row still looks well-formed -- so the mismatch is checked against
  the one place the two are forced to agree: a failure whose declared path is a camera is
  resolved by `recovery` exactly when its check is deployable.

  The gate axis is checked the same way and for the same reason. `recovery_report(protocol)`
  with no gate report is a valid public call and takes every declared QC_GATE path on trust,
  so composing one with a real gate report produces rows that assert a gate is dead and that
  the declared path still stands on it, in the same row -- and `unwatched()`, the list a
  reader is told to read first, quietly loses the failures that matter most. Guarding one
  axis and not the other is worse than guarding neither, because the guarded one makes the
  gap look deliberate.
  """
  cap = vision_capability or VisionCapability.none()
  meas = measurements if measurements is not None else MEASUREMENTS

  built_for = {
    "ledger": ledger.protocol.name,
    "gate report": gates.protocol,
    "recovery report": recovery.protocol,
  }
  wrong = sorted((label, name) for label, name in built_for.items() if name != protocol.name)
  if wrong:
    raise ValueError(
      f"coverage composes reports about one protocol; '{protocol.name}' was asked for but "
      + ", ".join(f"the {label} is about '{name}'" for label, name in wrong)
      + ". Composing across protocols returns a number about no lab."
    )

  rows: List[CoverageRow] = []
  for eff in recovery.rows:
    failure = eff.failure
    check_name, deployable, vision_reason = _vision_arm(failure, cap)
    gate_name, standing, gate_reason = _gate_arm(failure, gates, meas)
    if failure.declared_detection is Detection.VISION:
      if (eff.detection is Detection.VISION) != deployable:
        raise ValueError(
          f"the recovery report and the vision capability disagree about "
          f"'{failure.name}': recovery resolved it to '{eff.detection.value}' while "
          f"'{cap.name}' says the check is "
          f"{'deployable' if deployable else 'not deployable'}. The recovery report was "
          f"built against a different capability, and composing the two would report a "
          f"workcell nobody has."
        )
    if failure.declared_detection is Detection.QC_GATE:
      # Compared against the gate report's own evaluability and not against `standing`.
      # This arm additionally refuses a supervised gate and an assay that does not suit the
      # sample, questions `recovery.effective` never asks, so comparing to the standing
      # would raise on the library_conc_od case where the two layers agree exactly.
      declared = [r for r in gates.rows if r.gate.name == failure.via_gate]
      live = bool(declared) and all(r.evaluable for r in declared)
      if (eff.detection is Detection.QC_GATE) != live:
        raise ValueError(
          f"the recovery report and the gate report disagree about '{failure.name}': "
          f"recovery resolved it to '{eff.detection.value}' while the gate report for "
          f"'{gates.protocol}' says '{failure.via_gate}' is "
          f"{'evaluable' if live else 'not evaluable'}. The recovery report was built "
          f"against different gates, or against none at all, and composing the two would "
          f"put a dead gate and a live detection path on one row."
        )
    rows.append(
      CoverageRow(
        failure=failure,
        effective=eff,
        vision_check=check_name,
        vision_deployable=deployable,
        vision_reason=vision_reason,
        gate=gate_name,
        gate_standing=standing,
        gate_reason=gate_reason,
      )
    )
  return CoverageReport(protocol=protocol.name, capability=cap, rows=rows)


# -- what a better model buys, and what it does not -----------------------------


@dataclass(frozen=True)
class Lift:
  """One failure a better vision capability actually moves from uncovered to covered."""

  failure: FailureMode
  before: Cover
  after: Cover
  check: str
  gained: Tuple[VisionRequirement, ...]  # the requirements the proposal adds that this needed

  @property
  def destroys_material(self) -> bool:
    return _destroys_material(self.failure)


@dataclass(frozen=True)
class Ceiling:
  """One failure no vision capability moves, at any price, and the reason it cannot.

  Named for what it is. This is not a gap in a roadmap; it is the roof of the room.
  """

  failure: FailureMode
  reason: str

  @property
  def destroys_material(self) -> bool:
    return _destroys_material(self.failure)


@dataclass(frozen=True)
class StillBlocked:
  """One failure a camera could reach that THIS proposal does not reach.

  Neither a lift nor a ceiling, and the row that decides whether a partial purchase is worth
  making. The ceiling says a failure is out of reach at any price. This says it is in reach
  and that the money on the table does not buy it, and it names the requirement that would.
  """

  failure: FailureMode
  check: Optional[str]
  missing: Tuple[VisionRequirement, ...]  # what the proposal still lacks for this check
  reason: str

  @property
  def destroys_material(self) -> bool:
    return _destroys_material(self.failure)


@dataclass
class SotaLift:
  """What a proposed vision capability buys, what it provably cannot, and what it misses.

  All three lists are required output. A report that showed only `lifted` would be a
  purchase justification, and every purchase justification for a better model is correct
  about the failures it lists and silent about the ones that make the purchase
  insufficient. `ceiling` alone does not fix that, because the ceiling only holds the
  failures no capability reaches: a real proposal is partial, and the failures it leaves
  uncovered while a further purchase would close them fall between the two lists and
  vanish. `still_blocked` is where they land, and for the single-cell loop it is where the
  most destructive routine failure in low-input prep lands under any proposal missing
  LIGHTING.
  """

  protocol: str
  current: VisionCapability
  proposed: VisionCapability
  lifted: List[Lift] = field(default_factory=list)
  ceiling: List[Ceiling] = field(default_factory=list)
  still_blocked: List[StillBlocked] = field(default_factory=list)

  @property
  def buys_nothing(self) -> bool:
    return not self.lifted

  def destructive_ceiling(self) -> List[Ceiling]:
    """The ceiling rows that cost material. The sentence a budget meeting needs."""
    return [c for c in self.ceiling if c.destroys_material]

  def destructive_still_blocked(self) -> List[StillBlocked]:
    """The still-blocked rows that cost material. The sentence that prices the next step."""
    return [b for b in self.still_blocked if b.destroys_material]

  def counts(self) -> Dict[str, int]:
    return {
      "lifted": len(self.lifted),
      "lifted_destructive": sum(1 for lift in self.lifted if lift.destroys_material),
      "ceiling": len(self.ceiling),
      "ceiling_destructive": len(self.destructive_ceiling()),
      "still_blocked": len(self.still_blocked),
      "still_blocked_destructive": len(self.destructive_still_blocked()),
    }


def sota_lift(
  current_capability: VisionCapability,
  proposed_capability: VisionCapability,
  protocol,
  ledger=None,
  gates: Optional[GateReport] = None,
  measurements: Optional[Dict[str, Measurement]] = None,
) -> SotaLift:
  """Deploy a better model, or buy an assay? This is the computation that decides.

  Two coverage reports over one protocol and one gate report, differing only in the vision
  capability, because gates do not move when a model does. What changes between them is what
  the capability buys. What is uncovered and INVISIBLE in the second is the ceiling, and no
  further capability moves it -- so a lab reading only the lift will keep spending against
  failures that are not a model problem. What is uncovered and still imageable in the second
  is what the proposal misses, and a lab reading only the first two lists will believe a
  partial purchase was a complete one.

  Every uncovered row of the second report lands in the ceiling or in still_blocked, and the
  partition is checked rather than assumed. A row that falls out of both is not an omission a
  reader can see: the counts still add up, the lists still read cleanly, and the failure is
  simply absent.
  """
  led = ledger if ledger is not None else build_ledger(protocol)
  gts = gates if gates is not None else gate_report(protocol.name, led)

  before = coverage_report(
    protocol, led, gts, recovery_report(protocol, gts, current_capability), current_capability,
    measurements,
  )
  after = coverage_report(
    protocol, led, gts, recovery_report(protocol, gts, proposed_capability), proposed_capability,
    measurements,
  )
  prior = {row.failure.name: row for row in before.rows}

  lifted: List[Lift] = []
  ceiling: List[Ceiling] = []
  still_blocked: List[StillBlocked] = []
  for row in after.rows:
    was = prior.get(row.failure.name)
    moved = was is not None and not was.cover.covered and row.cover.covered
    # A lift has to be attributable to a deployed check. The gate report is shared between
    # the two runs, so nothing but vision can move a row -- and the INVISIBLE test cannot
    # fire, because `_vision_arm` refuses a check whose observability disagrees with the
    # failure's and `VisionCapability.available` refuses an impossible check. Both are
    # checked anyway: a lift reported for an INVISIBLE failure is the exact overclaim this
    # function exists to prevent, and a guard that never fires costs nothing next to one
    # that fires once against a real purchase.
    attributable = (
      row.observable.reachable_by_vision
      and row.vision_deployable
      and row.vision_check is not None
    )
    if moved and attributable:
      check = check_catching(row.failure.name)
      requires = check.requires if check is not None else ()
      lifted.append(
        Lift(
          failure=row.failure,
          before=was.cover,
          after=row.cover,
          check=row.vision_check,
          gained=tuple(
            r
            for r in requires
            if r in proposed_capability.satisfied and r not in current_capability.satisfied
          ),
        )
      )
      continue
    if row.cover.covered:
      continue
    if row.observable is Observable.INVISIBLE:
      # The residual is named where one survives, so that a row like star_resource_busy --
      # invisible, and loudly raised by the instrument itself -- is not read as a hole
      # merely because a camera cannot reach it. The ceiling is a statement about vision,
      # not a claim that nothing in the lab notices.
      residual = row.residual
      carried = (
        f" The declared {residual.value} path still stands on it at "
        f"{row.effective.latency.value}."
        if residual is not None
        else ""
      )
      ceiling.append(
        Ceiling(
          failure=row.failure,
          reason=(
            f"'{row.failure.name}' is INVISIBLE: the failed run and the clean run produce "
            f"identical images, so no vision capability reaches it at any model quality. "
            f"{row.gate_reason}.{carried}"
          ),
        )
      )
      continue
    check = check_catching(row.failure.name)
    missing = proposed_capability.missing_for(check) if check is not None else ()
    if check is None:
      reason = (
        f"'{row.failure.name}' is imageable and no visual check is declared for it, so this "
        f"proposal cannot reach it at any capability until one is written"
      )
    elif missing:
      reason = (
        f"'{row.failure.name}' is imageable and '{check.name}' would hold it, and "
        f"'{proposed_capability.name}' still misses "
        + ", ".join(m.value for m in missing)
        + ". This is a purchase away, not a physics problem, and the proposal on the table "
        "does not make it"
      )
    else:
      # Unreachable while `available` is a subset test over exactly `missing_for`. Kept
      # because the alternative is a StillBlocked row whose reason column is empty, which
      # reads as a failure nobody could account for.
      reason = (
        f"'{row.failure.name}' is imageable, '{check.name}' is deployable under this "
        f"proposal, and the row is still uncovered; this module cannot say why"
      )
    still_blocked.append(
      StillBlocked(
        failure=row.failure,
        check=row.vision_check,
        missing=missing,
        reason=reason,
      )
    )

  reported = {c.failure.name for c in ceiling} | {b.failure.name for b in still_blocked}
  remaining = {row.failure.name for row in after.uncovered()}
  if reported != remaining:
    # The three lists are the whole product, so a row that reaches none of them is a failure
    # this function computed and then dropped. Refusing is the only honest response: a
    # SotaLift missing a row is indistinguishable, to its reader, from one where the
    # proposal covered it.
    raise ValueError(
      "sota_lift resolved failures it then reported in no list: "
      + ", ".join(sorted(remaining - reported))
      + ". Every uncovered failure under the proposed capability belongs to the ceiling or "
      "to still_blocked, and a report that drops one is the purchase justification the "
      "second and third lists exist to prevent."
    )

  lifted.sort(key=lambda lift: (not lift.destroys_material, lift.failure.name))
  ceiling.sort(key=lambda c: (not c.destroys_material, c.failure.name))
  still_blocked.sort(key=lambda b: (not b.destroys_material, b.failure.name))
  return SotaLift(
    protocol=protocol.name,
    current=current_capability,
    proposed=proposed_capability,
    lifted=lifted,
    ceiling=ceiling,
    still_blocked=still_blocked,
  )


# -- the gates that are not optional --------------------------------------------


@dataclass(frozen=True)
class Demand:
  """A gate that must exist, because no camera can substitute for it.

  A demand rather than a gap, and the word is the content. A gap invites prioritization
  against other gaps. A demand says that for this failure there is no second option: the
  condition is invisible, the failure destroys material, and an assay is the only instrument
  left. `met` is False by default in every path that cannot prove otherwise, including the
  path where nobody supplied a gate report to check against.
  """

  failure: FailureMode
  gate: Optional[str]
  met: bool
  reason: str

  def statement(self) -> str:
    """The demand written out, in the form a planning document has to answer."""
    verb = "is met" if self.met else "is NOT met"
    named = f"'{self.gate}'" if self.gate else "a gate that does not exist yet"
    return (
      f"a gate must exist for '{self.failure.name}' ({self.failure.description}): the "
      f"condition is INVISIBLE, so no camera substitutes, and the failure costs "
      f"{self.failure.severity.value}. The demand names {named} and {verb} -- {self.reason}"
    )


def mandatory_gates(
  gates: Optional[GateReport] = None,
  measurements: Optional[Dict[str, Measurement]] = None,
) -> Tuple[Demand, ...]:
  """For every INVISIBLE failure that destroys material, the gate that has to exist.

  These are the rows where the vision layer's hard boundary becomes a purchasing
  requirement. A camera cannot see a denatured enzyme, a short transfer inside the
  instrument's own tolerance, or two clear liquids swapped between identical tubes, so for
  each of them the assay is not one option among several. It is the option.

  Called with no gate report, every demand comes back unmet. That is not a placeholder: an
  unchecked demand is not a met one, which is the same convention `intelligence.trusted_for`
  applies to a missing benchmark and `qc.evaluate` applies to a missing measurement. A
  default that read as satisfied would let a caller establish full compliance by supplying
  nothing at all.
  """
  meas = measurements if measurements is not None else MEASUREMENTS
  out: List[Demand] = []
  for failure in FAILURE_MODES:
    if failure.observable is not Observable.INVISIBLE or not _destroys_material(failure):
      continue
    if gates is None:
      out.append(
        Demand(
          failure=failure,
          gate=failure.via_gate,
          met=False,
          reason=(
            "no gate report was supplied, so this demand stands unresolved; an unchecked "
            "demand is not a met one"
          ),
        )
      )
      continue
    name, standing, reason = _gate_arm(failure, gates, meas)
    out.append(Demand(failure=failure, gate=name, met=standing.counts_as_coverage, reason=reason))
  return tuple(out)


def unmet_demands(
  gates: Optional[GateReport] = None,
  measurements: Optional[Dict[str, Measurement]] = None,
) -> Tuple[Demand, ...]:
  """The subset of `mandatory_gates` a lab has not answered. Usually all of it."""
  return tuple(d for d in mandatory_gates(gates, measurements) if not d.met)


__all__ = [
  "Ceiling",
  "Cover",
  "CoverageReport",
  "CoverageRow",
  "Demand",
  "GateStanding",
  "Lift",
  "SotaLift",
  "StillBlocked",
  "Uncovered",
  "coverage_report",
  "mandatory_gates",
  "sota_lift",
  "unmet_demands",
]
