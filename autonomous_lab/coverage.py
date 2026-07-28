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
things qualify: a deployed and validated visual check, and an evaluable gate reading an
appropriate assay. An operator noticing is not coverage in a package about unattended
operation; it is the condition this whole package exists to remove. Data analysis after
sequencing is not coverage of a sample either, because the flow cell is already spent by the
time it speaks. Both are real all the same, so every row carries the path `recovery`
resolved, and nothing here ever claims that nothing anywhere would notice when a sibling
layer says something would. The claim is narrower and worth more: nothing MACHINE-CHECKABLE
stands between this failure and the material.

`sota_lift` is the buying decision. Given a better vision capability it reports which
failures move from uncovered to covered -- and, more prominently, which do not move at ANY
capability, because they are INVISIBLE. The second list is the point of the function.
Upgrading a model has a ceiling, the ceiling is physics rather than engineering, and a lab
reading only the first list will keep buying model upgrades against failures no model
resolves.

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
from .qc import MEASUREMENTS, GateReport, Measurement, gate_report
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
  GATE = "gate"  # a declared gate is evaluable and reads an appropriate assay
  BOTH = "both"  # either alone would hold it
  NEITHER = "neither"  # no camera and no gate; the row says which kind of nothing

  @property
  def covered(self) -> bool:
    """True where something machine-checkable stands between the failure and the material."""
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
      return "an evaluable gate reading an assay appropriate to the sample"
    if self is Cover.BOTH:
      return "a deployed visual check and an evaluable gate; either alone would hold it"
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
  gate_evaluable: bool  # exists AND its inputs arrive AND the assay suits the sample
  gate_reason: str

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
    """The path `recovery` resolved that is neither a camera nor a gate, where one survives.

    None when something machine-checkable already holds the failure, and None when recovery
    found nothing either. Anything else is a real path this module deliberately does not count
    as coverage, and reporting it is what keeps an uncovered row from being read as a claim
    that the failure is invisible to the entire lab.
    """
    if self.cover.covered or self.effective.silent:
      return None
    return self.effective.detection

  @property
  def unwatched(self) -> bool:
    """No camera, no gate, and nothing else either. The rows that should be read first."""
    return not self.cover.covered and self.effective.silent

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

  def complete(self) -> bool:
    """True only when every material-destroying failure has a machine check on it.

    `bool(self.rows)` is load-bearing, not defensive. An empty report satisfies the
    all-clear by vacuity, and a composition that answered "complete" for a protocol it
    resolved no failures on would be the same bug this package chases everywhere else: a
    check that passes because it was handed nothing.
    """
    return bool(self.rows) and not self.uncovered_destructive()

  def counts(self) -> Dict[str, int]:
    return {
      "total": len(self.rows),
      "covered": len(self.covered()),
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
  """
  check = check_catching(failure.name)
  if check is None:
    if failure.observable.reachable_by_vision:
      return None, False, "the condition is imageable and no visual check is declared for it"
    return None, False, "no camera resolves this condition at any model quality"
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
) -> Tuple[Optional[str], bool, str]:
  """(gate name, counts as coverage, reason) for the assay side of one failure.

  Three ways a declared gate fails to be coverage, in increasing order of how quietly it
  does so. It may not be on this protocol at all. It may be UNSATISFIABLE, which at least
  fails loudly -- no number arrives. Or it may be evaluable and resting on a measurement that
  is the wrong assay for the sample, which is the one that spends the flow cell: the
  instrument returns a real, precise, reproducible number about something other than the
  library, and the gate passes on it.
  """
  name = failure.via_gate
  if name is None:
    return None, False, "no gate on this protocol reads what this failure changes"
  row = next((r for r in gates.rows if r.gate.name == name), None)
  if row is None:
    # The name is reported in the reason and deliberately NOT returned as the gate. A gate
    # that is not on this protocol reads nothing here, and returning its name would let the
    # uncovered classification treat a dangling reference as an assay that exists.
    return (
      None,
      False,
      f"the plan names '{name}' for this failure, and no such gate is on this protocol",
    )
  if not row.evaluable:
    return name, False, f"'{name}' is unsatisfiable: {row.reason}"
  wrong = [m for gate_name, m in gates.inappropriate(measurements) if gate_name == name]
  if wrong:
    return (
      name,
      False,
      f"'{name}' can be evaluated and rests on '{wrong[0].key}', which is the wrong assay "
      f"for this sample: {wrong[0].inappropriate_reason}",
    )
  return name, True, f"'{name}' is evaluable and reads an assay appropriate to the sample"


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

  It refuses two kinds of incoherent input rather than averaging over them. Reports about
  different protocols compose into a number about no lab at all. A recovery report built
  against a different vision capability than the one passed here does the same thing more
  quietly, because every row still looks well-formed -- so the mismatch is checked against
  the one place the two are forced to agree: a failure whose declared path is a camera is
  resolved by `recovery` exactly when its check is deployable.
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
    gate_name, evaluable, gate_reason = _gate_arm(failure, gates, meas)
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
    rows.append(
      CoverageRow(
        failure=failure,
        effective=eff,
        vision_check=check_name,
        vision_deployable=deployable,
        vision_reason=vision_reason,
        gate=gate_name,
        gate_evaluable=evaluable,
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


@dataclass
class SotaLift:
  """What a proposed vision capability buys, and what it provably does not.

  Both lists are required output. A report that showed only `lifted` would be a purchase
  justification, and every purchase justification for a better model is correct about the
  failures it lists and silent about the ones that make the purchase insufficient.
  """

  protocol: str
  current: VisionCapability
  proposed: VisionCapability
  lifted: List[Lift] = field(default_factory=list)
  ceiling: List[Ceiling] = field(default_factory=list)

  @property
  def buys_nothing(self) -> bool:
    return not self.lifted

  def destructive_ceiling(self) -> List[Ceiling]:
    """The ceiling rows that cost material. The sentence a budget meeting needs."""
    return [c for c in self.ceiling if c.destroys_material]

  def counts(self) -> Dict[str, int]:
    return {
      "lifted": len(self.lifted),
      "lifted_destructive": sum(1 for lift in self.lifted if lift.destroys_material),
      "ceiling": len(self.ceiling),
      "ceiling_destructive": len(self.destructive_ceiling()),
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
  failures that are not a model problem.
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
  for row in after.rows:
    was = prior.get(row.failure.name)
    moved = was is not None and not was.cover.covered and row.cover.covered
    # A lift has to be attributable to a deployed check. The gate report is shared between
    # the two runs, so nothing but vision can move a row -- and the INVISIBLE test is
    # unreachable by construction, since VisionCapability.available already refuses an
    # impossible check. Both are checked anyway: a lift reported for an INVISIBLE failure is
    # the exact overclaim this function exists to prevent, and a guard that never fires costs
    # nothing next to one that fires once against a real purchase.
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
    if not row.cover.covered and row.observable is Observable.INVISIBLE:
      # The residual is named where one survives, so that a row like star_resource_busy --
      # invisible, and loudly raised by the instrument itself -- is not read as a hole
      # merely because a camera cannot reach it. The ceiling is a statement about vision,
      # not a claim that nothing in the lab notices.
      residual = row.residual
      standing = (
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
            f"{row.gate_reason}.{standing}"
          ),
        )
      )

  lifted.sort(key=lambda lift: (not lift.destroys_material, lift.failure.name))
  ceiling.sort(key=lambda c: (not c.destroys_material, c.failure.name))
  return SotaLift(
    protocol=protocol.name,
    current=current_capability,
    proposed=proposed_capability,
    lifted=lifted,
    ceiling=ceiling,
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
    name, evaluable, reason = _gate_arm(failure, gates, meas)
    out.append(Demand(failure=failure, gate=name, met=evaluable, reason=reason))
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
  "Lift",
  "SotaLift",
  "Uncovered",
  "coverage_report",
  "mandatory_gates",
  "sota_lift",
  "unmet_demands",
]
