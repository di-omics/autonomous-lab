"""Which decisions a model may make alone, which it may only draft, and which it must not touch.

This is the single most important question in autonomous-lab engineering and the one the
phrase "AI-native lab" is routinely used to skip. Read literally, "AI-native" says the model
drives the instruments. Every other module in this package has been arguing against that
reading from a different direction -- qc says a gate whose input never arrives is not a
gate, vision says no camera resolves a denatured enzyme, intelligence says an unmeasured
operation is not a trusted one -- and none of them says the thing directly. This one does:
authority is a property of the DECISION, not of the system that happens to be holding it.

The evidence people usually reach for is a demo. The evidence that bears is the benchmark.
On LabSafety Bench (Zhou et al., Nature Machine Intelligence 2026), 19 evaluated models --
8 proprietary, 7 open-weight LLMs, 4 open-weight VLMs -- none exceeded 70 percent accuracy
on the open-ended hazards identification test, while the same generation of models scored in
the mid-80s on the benchmark's multiple-choice portion (GPT-4o 86.55 percent). The gap is
the finding, not either number. Structured recall does not carry into open-ended reasoning
about a scenario, and a scenario is the form in which a real hazard arrives. Be precise
about what that does NOT establish: it is constructed text questions across BSL 1-3 aligned
to US OSHA protocols, evaluated on a late-2024 model snapshot; it measures no bench
behavior, no physical task execution, and no incident rate, and it does not show that any
model has caused a laboratory incident. It is enough for exactly one inference, and that
inference is enough: FLUENT OUTPUT IS NOT EVIDENCE OF HAZARD COMPETENCE, so fluency cannot
be the thing that authorizes an action.

The honest position is not that models are useless. It is that decision classes differ and
each has a different required authority:

  MODEL             a model may decide alone. The output commits nothing, and the error is
                    visible to whoever reads it next.
  MODEL_PROPOSES    a model drafts; a deterministic check or a human ratifies before it
                    becomes an action. The draft is genuinely valuable here.
  DETERMINISTIC     a coded interlock decides, with no model anywhere in the path. Not
                    because code is smarter, but because code cannot be argued into a
                    different answer by a well-formed account of the situation.
  HUMAN             a named person approves and is accountable for having approved.

DETERMINISTIC sits ABOVE MODEL_PROPOSES on purpose, and it is the ordering people find
surprising. A drafting model is still in the path: the ratifier reads a proposal that has
already framed the problem, and a plausible frame is the thing a model produces most
reliably when it is wrong. An interlock reading a door sensor cannot be framed. Strength
here means "how little a model's output can move", not "how much intelligence is applied".

The load-bearing computation is `violations(plan)`. A plan assigns an actual authority to
each decision class; a violation is every place the assignment is WEAKER than the class
requires. Assigning MODEL to a DETERMINISTIC or HUMAN class is the failure this module
exists to catch, and it is worth being blunt that this is not a hypothetical failure mode
but the default one, because the weakest assignment is also the fastest to build and the
best to demonstrate.

Authority may always be STRENGTHENED and never weakened. A lab may put a human on a
decision a model could make; the reverse is the defect. `strengthened()` reports where a lab
went above the floor and nothing here ever flags it -- though over-escalation has its own
real cost, which is a human approving so many things that approval stops meaning anything,
and this module measures none of that. RoboCulture is the published example of a deliberate
strengthening: the system detected culture saturation and tracked growth on its own, and the
split was still manually initiated as a safety precaution.

And absence of an assignment is not compliance. A plan that says nothing about batch release
has not permitted a human to decide it; it has left the question to whatever code path
reaches it first. This is the same rule qc.evaluate applies to a missing measurement and
intelligence.trusted_for applies to a missing benchmark, and it is the rule that a plan
document naturally breaks, because the classes nobody thought about are exactly the ones
nobody wrote down.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple


class Authority(str, Enum):
  """Who may decide. Ordered weakest to strongest by how little a model's output can move.

  The ordering is what makes the check computable, so it has to mean one thing. It does not
  rank competence, cost, or speed. It ranks the distance between a generated token and a
  consequence.
  """

  MODEL = "model"  # a model decides; its output is the outcome
  MODEL_PROPOSES = "model_proposes"  # a model drafts; a coded check or a person ratifies
  DETERMINISTIC = "deterministic"  # coded interlock decides; no model in the path
  HUMAN = "human"  # a named person approves and is accountable

  @property
  def model_decides_alone(self) -> bool:
    """True only for MODEL. This is the line the module exists to draw.

    Every safety argument in this package turns on whether generated output becomes an
    outcome with nothing in between. At MODEL_PROPOSES a wrong draft meets a ratifier; at
    DETERMINISTIC and HUMAN the model is not the decider at all. At MODEL there is nothing
    downstream, which is acceptable only for classes where nothing downstream is needed.
    """
    return self is Authority.MODEL

  @property
  def model_in_path(self) -> bool:
    """True where model output reaches the decision at all, whether deciding or drafting.

    Separate from `model_decides_alone` because the hazard classes need the stronger claim.
    A hazard call does not become safe by adding a reviewer to a model's framing of it.
    """
    return self in (Authority.MODEL, Authority.MODEL_PROPOSES)

  @property
  def rank(self) -> int:
    return _ORDER.index(self)

  def satisfies(self, required: "Authority") -> bool:
    """Does an assignment at this authority meet a class that requires `required`?

    Strengthening satisfies. Weakening never does, at any distance: MODEL_PROPOSES against
    a DETERMINISTIC requirement is one step short and is still a model in the path of an
    interlock, which is the whole thing the requirement was written to exclude.
    """
    return self.rank >= required.rank


# Weakest first. Used by rank, satisfies, and every report that orders by strength.
_ORDER: Tuple[Authority, ...] = (
  Authority.MODEL,
  Authority.MODEL_PROPOSES,
  Authority.DETERMINISTIC,
  Authority.HUMAN,
)


@dataclass(frozen=True)
class DecisionClass:
  """One kind of decision, and the weakest authority that may hold it.

  `because` is the mechanism -- why this class sits where it does -- and it is required
  rather than optional. A required authority with no stated mechanism cannot be argued
  with, only obeyed, and a rule that cannot be argued with cannot be revised when the
  evidence changes. That is the same discipline qc.Criterion applies to a threshold and
  intelligence.Judgment applies to a bench rule.

  `evidence_key` names an entry in this repo's verified-literature index. It is a string
  rather than an import so that the bibliography can grow without this module changing, and
  so that a class with no published evidence bearing on it says so by leaving it None
  instead of borrowing a citation that does not fit.
  """

  name: str
  decides: str  # what is being decided, in the terms a bench would use
  required: Authority
  because: str
  evidence_key: Optional[str] = None

  def __post_init__(self) -> None:
    if not self.because.strip():
      raise ValueError(
        f"decision class '{self.name}' states no mechanism; a required authority with no "
        f"reason behind it cannot be revised, only obeyed"
      )

  def permits(self, assigned: Authority) -> bool:
    return assigned.satisfies(self.required)

  @property
  def admits_a_model(self) -> bool:
    """Whether any model output may reach this decision, in any role."""
    return self.required.model_in_path


# -- the classes a real lab actually has to place --------------------------------
# Ordered weakest requirement first, because that ordering is the argument: the top of this
# list is the work models are genuinely good at and should be doing, and the bottom is the
# work that a demo quietly hands them.

DECISION_CLASSES: Tuple[DecisionClass, ...] = (
  DecisionClass(
    name="prior_result_retrieval",
    decides="which prior results bear on a question, and what they say",
    required=Authority.MODEL,
    because=(
      "the output is text, nothing physical is committed by it, and the source travels with "
      "the claim, so an error is visible to the next reader and costs a re-read. That is why "
      "this class sits at MODEL -- not because summarization is reliable. CPJUMP1 is the "
      "standing counterexample: its authors' own conclusion is that matching chemical to "
      "genetic perturbations is a challenging task, so a fluent summary reporting it as "
      "evidence that morphological profiling links compounds to their gene targets inverts "
      "the finding it cites. A summary delivered without its source is a different class, "
      "because nothing downstream of it can catch that"
    ),
    evidence_key="jump",
  ),
  DecisionClass(
    name="hypothesis_generation",
    decides="which candidate targets, conditions, or explanations are worth considering next",
    required=Authority.MODEL,
    because=(
      "a hypothesis commits no material and no instrument time until something else schedules "
      "it, and every class below this one stands between the proposal and an instrument. The "
      "A-Lab is the worked example: its initial recipes came from natural-language models "
      "trained on the literature, and what decided anything afterward was an active-learning "
      "algorithm reading failed reactions, plus the furnace. Generation was safe precisely "
      "because it was not authority"
    ),
    evidence_key="a_lab",
  ),
  DecisionClass(
    name="protocol_drafting",
    decides="the steps, order, reagents, and parameters of a procedure to be run",
    required=Authority.MODEL_PROPOSES,
    because=(
      "a draft becomes an action the moment someone commits reagent and instrument time to "
      "it, and the gap between a proposed route and an executable one is where the omissions "
      "live. The Coley platform reached 15 drug or drug-like substances from AI-proposed "
      "routes that expert chemists then had to turn into recipe files, supplying solvent "
      "choice and precise stoichiometry among other implementation details, because the "
      "chemical literature does not carry enough to get from inspiration to execution. The "
      "ratifier need not be a person: a coded check that every reagent, volume, and "
      "instrument named in the draft is declared in the registry is a ratifier, and it is "
      "cheaper than a reviewer who is reading their fortieth draft that week"
    ),
    evidence_key="coley",
  ),
  DecisionClass(
    name="capacity_forecast",
    decides="how many plates, samples, or runs this lab can complete in a period",
    required=Authority.MODEL_PROPOSES,
    because=(
      "a forecast moves nothing itself and is acted on by everyone, which is the worst "
      "combination for a class with no ratifier. The deterministic check already exists in "
      "this package: throughput refuses to total a protocol containing an UNKNOWN duration "
      "and reports a floor from what was measured, so a drafted forecast can be mechanically "
      "refused rather than argued with. AlabOS is the caution from the other side -- around "
      "3,500 samples over about 1.5 years is a deployment usage statistic, and the scheduler "
      "producing it is first-come-first-serve with no task-duration modeling at all, so "
      "neither number forecasts anything about a different lab"
    ),
    evidence_key="alabos",
  ),
  DecisionClass(
    name="schedule_proposal",
    decides="the order queued work runs in, and which instrument takes which plate",
    required=Authority.MODEL_PROPOSES,
    because=(
      "an ordering stays a proposal until a resource manager grants the device, and the grant "
      "has to be deterministic because the constraint it enforces is physical rather than "
      "preferential: two clients on one instrument is a USBError on the STAR and a silent "
      "callback theft on the ODTC. AlabOS splits it exactly here -- a central resource "
      "manager allocates devices and sample positions per task so that concurrent tasks "
      "cannot conflict, and the framework explicitly does no experiment design of its own"
    ),
    evidence_key="alabos",
  ),
  DecisionClass(
    name="exception_triage",
    decides="what an unexpected observation means, and which recovery path follows from it",
    required=Authority.MODEL_PROPOSES,
    because=(
      "triage is where fluency is most convincing and least checkable, because the input is "
      "by definition off the distribution any rule anticipated. The mobile-robot chemistry "
      "campaign is the case worth memorizing: one target underwent an unexpected "
      "intramolecular cyclization whose product carried the same molecular weight as the "
      "expected one and was not distinguishable by chromatogram or MS, so the workflow's "
      "tiered heuristic let it through. Human inspection of the NMR caught it and "
      "single-crystal diffraction settled it. A drafted triage is useful; a triage that "
      "closes the exception on its own converts an anomaly into a result"
    ),
    evidence_key="dai",
  ),
  DecisionClass(
    name="instrument_motion_limit",
    decides="the travel, force, speed, and temperature bounds a machine may not exceed",
    required=Authority.DETERMINISTIC,
    because=(
      "a limit is only a limit at the layer that can refuse. PyLabRobot draws its own "
      "boundary in exactly the right place: its unit tests check that user input produces "
      "the intended machine-level commands, and once the commands are sent they are "
      "explicitly no longer the library's responsibility. A bound enforced by whatever "
      "composes the command is a bound on the intent, so it is absent precisely when the "
      "intent is wrong. Nothing that can be talked into a different answer belongs in this "
      "path, which rules out a model in either role"
    ),
    evidence_key="pylabrobot",
  ),
  DecisionClass(
    name="actuation_arming",
    decides="whether the machine is permitted to move or energize at all, right now",
    required=Authority.DETERMINISTIC,
    because=(
      "arming is the last point at which a wrong belief is still free. The interlock has to "
      "answer from state a sensor reports -- door closed, plate seated, envelope clear -- "
      "rather than from any account of the situation, because a coherent account of the "
      "situation is exactly what a model produces when it is wrong. RoboCulture is the "
      "stronger case and it is a strengthening, not a counterexample: the system detected "
      "saturation and tracked growth across replicates, and the split was still manually "
      "initiated as a safety precaution. HUMAN on a class whose floor is DETERMINISTIC is "
      "permitted here and is never reported"
    ),
    evidence_key="roboculture",
  ),
  DecisionClass(
    name="qc_result_disposition",
    decides="whether a plate, run, or batch passes, and what happens to the material",
    required=Authority.DETERMINISTIC,
    because=(
      "disposition is codeable, and where it is codeable it must be coded, because a "
      "criterion in code can be versioned, argued with, and shown to a reviewer, while a "
      "judgment call cannot be shown at all. The HTS assay validation guidance demonstrates "
      "that these numbers exist and are writable -- a plate-uniformity study run over three "
      "days, an acceptance criterion of signal window >= 2 or Z' >= 0.4, drift and edge "
      "effects under about 20 percent -- and the same guidance says its replicate-experiment "
      "study is a pre-production readiness tool and is not a substitute for post-production "
      "monitoring. So DETERMINISTIC is the floor and not the end of the argument: qc.Gate is "
      "the interlock, and every criterion in it still carries the Basis it rests on"
    ),
    evidence_key="ncats",
  ),
  DecisionClass(
    name="batch_release",
    decides="whether a result leaves this lab as something another party may rely on",
    required=Authority.HUMAN,
    because=(
      "release is where this lab's uncertainty becomes someone else's assumption, and the "
      "only mechanism anyone has made work for that is a named person who is answerable for "
      "having released it. The drug CGMP data-integrity guidance is cited for the mechanism "
      "and not for jurisdiction -- it is nonbinding guidance clarifying regulations a "
      "research bench is not under -- and the mechanism is specific: production and control "
      "records reviewed and approved by a quality unit, a system administrator role held "
      "independently of the people responsible for record content, and data that cannot be "
      "modified without a record of the modification. A model reporting that it checked "
      "satisfies none of those, because none of them are about checking"
    ),
    evidence_key="fda_di",
  ),
  DecisionClass(
    name="welfare_intervention",
    decides="whether an animal is in distress, and what is done about it",
    required=Authority.HUMAN,
    because=(
      "an automated readout can be genuinely useful here and still not be the decider, and "
      "the multicentric home-cage study states both halves cleanly. Across 1,367 cages at "
      "three institutions the model flagged animals 3 to 6 days before verifiable clinical "
      "signs or death, at 66-80 percent accuracy on day -3 and 80-91 percent on day -6 "
      "against a tolerated 15 percent false-positive budget. It also missed 9 to 20 percent "
      "of verified clinical cases, measures locomotion only, cannot resolve individual "
      "animals in a group-housed cage, delivers its alerts no earlier than the following "
      "morning, and was analyzed retrospectively -- so nothing in it shows that acting on an "
      "alert improved any outcome. A flag is evidence for a person. It is not a decision"
    ),
    evidence_key="homecage_multi",
  ),
  DecisionClass(
    name="hazard_call",
    decides="whether a material, reaction, or situation is dangerous, and what precaution follows",
    required=Authority.HUMAN,
    because=(
      "this is the class the safety benchmark speaks to most directly, and being precise "
      "about it matters more than the headline. Of 19 models evaluated, none exceeded 70 "
      "percent accuracy on the open-ended hazards identification test, while the same "
      "generation scored in the mid-80s on the multiple-choice portion. The gap is the "
      "finding: structured recall does not carry into open-ended reasoning about a scenario, "
      "and a scenario is the form a real hazard arrives in. What the benchmark measured is "
      "constructed text questions at biosafety levels 1-3 aligned to US OSHA protocols, on a "
      "late-2024 model snapshot -- no bench behavior, no incident rate. That is enough to "
      "establish that a fluent hazard assessment is not evidence of one, which leaves "
      "accountability as the only thing this class can rest on"
    ),
    evidence_key="labsafety",
  ),
  DecisionClass(
    name="animal_procedure_authorization",
    decides="whether a procedure on an animal may be performed at all",
    required=Authority.HUMAN,
    because=(
      "authorization is held by a body, not by a document and not by a system. ARRIVE 2.0 is "
      "a reporting guideline: its ethical-statement item asks authors to name the committee "
      "that already approved the work, or to justify the absence of approval. Approval is "
      "granted elsewhere and merely reported, so full compliance with the checklist says a "
      "study was described transparently and says nothing about whether it was permitted or "
      "sound. A pipeline that can produce the paperwork has produced a report, not "
      "permission, and nothing in this package moves who holds it"
    ),
    evidence_key="arrive",
  ),
)


DECISION_CLASSES_BY_NAME: Dict[str, DecisionClass] = {d.name: d for d in DECISION_CLASSES}


# -- a lab's actual plan, and what is wrong with it ------------------------------


@dataclass(frozen=True)
class Assignment:
  """One decision class, and the authority a lab has actually put on it.

  `who` is the named accountable party and matters only at HUMAN. It is checked by
  `unaccountable()` rather than by `violations()`, because an unnamed human approver is a
  different defect from a weakened authority: the authority is right and the accountability
  is missing, so the plan reads compliant and no one is answerable.
  """

  decision_class: str
  authority: Authority
  who: str = ""
  note: str = ""


@dataclass(frozen=True)
class Plan:
  """What a lab intends to let its models decide. The object this module checks.

  Nothing here can declare itself compliant. There is no field an author can set that
  suppresses a violation, for the same reason a Gate has no `ready` field: a report that can
  be silenced is a report about the author rather than the lab.
  """

  name: str
  assignments: Tuple[Assignment, ...] = ()

  def assigned(self, decision_class: str) -> Optional[Assignment]:
    """The single assignment for a class, or None when there is not exactly one.

    Returns None for a duplicated class rather than the first match. First-match is the
    natural implementation and it is a hole in the invariant this module exists to enforce:
    list the strong authority first and a weaker one after it, and the weaker row is never
    read. `violations()` reports every row, so nothing hides behind an earlier one.
    """
    found = self.all_assigned(decision_class)
    return found[0] if len(found) == 1 else None

  def all_assigned(self, decision_class: str) -> Tuple[Assignment, ...]:
    """Every assignment naming this class, in the order the plan lists them."""
    return tuple(a for a in self.assignments if a.decision_class == decision_class)

  @property
  def escalation_only(self) -> bool:
    """True when no assignment in this plan sits below the authority its class requires.

    Necessary and nowhere near sufficient, and the difference is the point. An empty plan is
    trivially escalation-only because it weakens nothing, and it covers nothing at all. Use
    `complies` for the question a lab actually wants answered.
    """
    return not any(v.kind is ViolationKind.WEAKENED for v in violations(self))

  @property
  def complies(self) -> bool:
    """No class is weakened, and no class is left unplaced."""
    return not violations(self)


class ViolationKind(str, Enum):
  """The three ways a plan fails, which need three different fixes."""

  WEAKENED = "weakened"  # an authority below what the class requires
  UNASSIGNED = "unassigned"  # the class exists and the plan is silent about it
  UNDECLARED = "undeclared"  # the plan places a class this registry does not declare
  # The plan assigns one class more than once. Reported in its own right rather than
  # resolved, because every resolution rule picks a winner on the author's behalf and the
  # ambiguity is the finding: a document that says a person releases the batch and also
  # that a model does has not decided, and reading either row as the answer invents one.
  DUPLICATED = "duplicated"


@dataclass(frozen=True)
class Violation:
  """One place a plan does not hold, with enough detail to act on it."""

  decision_class: str
  kind: ViolationKind
  required: Optional[Authority]
  assigned: Optional[Authority]
  reason: str
  evidence_key: Optional[str] = None

  @property
  def model_overreach(self) -> bool:
    """A model was given a decision that requires an interlock or a person.

    The specific defect the module was written for, separated from the others so a report
    can lead with it. Everything else here is a gap in the plan; this is a claim about the
    lab that is false.
    """
    return (
      self.kind is ViolationKind.WEAKENED
      and self.assigned is not None
      and self.assigned.model_in_path
      and self.required is not None
      and not self.required.model_in_path
    )


def violations(
  plan: Plan,
  classes: Optional[Sequence[DecisionClass]] = None,
) -> Tuple[Violation, ...]:
  """Every place `plan` assigns an authority weaker than the class requires, plus every
  class it does not assign at all.

  Iterates the CLASSES, not the assignments. Written the other way round -- walking the
  plan and checking each entry -- it returns clean for a plan that mentions two classes and
  omits eleven, which is the shape every real authority document has. Absence of an
  assignment is not compliance, and the omitted classes are systematically the ones nobody
  thought about, so they are exactly the ones worth naming.
  """
  registry = tuple(classes) if classes is not None else DECISION_CLASSES
  out: List[Violation] = []

  for dc in registry:
    rows = plan.all_assigned(dc.name)
    if len(rows) > 1:
      weakest = min(rows, key=lambda a: _ORDER.index(a.authority))
      out.append(
        Violation(
          decision_class=dc.name,
          kind=ViolationKind.DUPLICATED,
          required=dc.required,
          assigned=weakest.authority,
          reason=(
            f"'{dc.name}' is assigned {len(rows)} times ("
            + ", ".join(a.authority.value for a in rows)
            + f"). The plan has not decided who decides '{dc.decides}', and picking one row "
            "would answer that on the author's behalf. The weakest is reported below on its "
            "own merits"
          ),
          evidence_key=dc.evidence_key,
        )
      )
    assignment = rows[0] if len(rows) == 1 else (
      min(rows, key=lambda a: _ORDER.index(a.authority)) if rows else None
    )
    if assignment is None:
      out.append(
        Violation(
          decision_class=dc.name,
          kind=ViolationKind.UNASSIGNED,
          required=dc.required,
          assigned=None,
          reason=(
            f"the plan says nothing about who decides '{dc.decides}'; this class requires "
            f"{dc.required.value} and an unassigned class is not a permitted one, it is an "
            f"unexamined one"
          ),
          evidence_key=dc.evidence_key,
        )
      )
      continue
    if not dc.permits(assignment.authority):
      out.append(
        Violation(
          decision_class=dc.name,
          kind=ViolationKind.WEAKENED,
          required=dc.required,
          assigned=assignment.authority,
          reason=(
            f"'{dc.name}' is assigned {assignment.authority.value} and requires "
            f"{dc.required.value}: {dc.because}"
          ),
          evidence_key=dc.evidence_key,
        )
      )

  declared = {dc.name for dc in registry}
  for a in plan.assignments:
    if a.decision_class not in declared:
      out.append(
        Violation(
          decision_class=a.decision_class,
          kind=ViolationKind.UNDECLARED,
          required=None,
          assigned=a.authority,
          reason=(
            f"the plan assigns '{a.decision_class}', which no decision class declares; "
            f"either the registry is missing a real decision or the plan is placing "
            f"authority on something nobody defined"
          ),
        )
      )

  return tuple(out)


def strengthened(
  plan: Plan,
  classes: Optional[Sequence[DecisionClass]] = None,
) -> Tuple[Tuple[str, Authority, Authority], ...]:
  """(class, required, assigned) wherever a lab went above the floor.

  Reported and never flagged, which is the asymmetry the whole module rests on. It is worth
  seeing, though: a lab that has strengthened eleven of thirteen classes has bought a lot of
  approvals, and approval fatigue is a real failure mode that nothing here measures.
  """
  registry = tuple(classes) if classes is not None else DECISION_CLASSES
  out: List[Tuple[str, Authority, Authority]] = []
  for dc in registry:
    a = plan.assigned(dc.name)
    if a is not None and a.authority.rank > dc.required.rank:
      out.append((dc.name, dc.required, a.authority))
  return tuple(out)


def unaccountable(
  plan: Plan,
  classes: Optional[Sequence[DecisionClass]] = None,
) -> Tuple[str, ...]:
  """Classes placed at HUMAN with nobody named.

  A human in the loop who is not named is not accountable; it is a queue. Kept out of
  `violations()` because the authority level is correct and only the accountability is
  missing, so folding them together would let a fix for one look like a fix for the other.
  """
  registry = tuple(classes) if classes is not None else DECISION_CLASSES
  declared = {dc.name for dc in registry}
  return tuple(
    a.decision_class
    for a in plan.assignments
    if a.decision_class in declared and a.authority is Authority.HUMAN and not a.who.strip()
  )


# -- the qualification ladder -----------------------------------------------------
# A separate structure from authority, and deliberately not merged with it. Authority asks
# who may decide; the ladder asks what has been PROVEN about a capability. A lab can get
# both wrong independently, and conflating them produces the most common overclaim in this
# field: a system that passed a simulation, is described as validated, and is then handed a
# decision that requires an interlock.
#
# A rung is not a Verdict, and the two answer different questions. Verdict says what the
# machine can do today -- BROKEN, MANUAL, WRITTEN, BLOCKED, SUPERVISED, AUTOMATED. A rung
# says what anyone has established about doing it. WRITTEN is the verdict of a step standing
# on SIMULATION and nothing above it: dry-validated, never on the instrument. AUTOMATED is
# not a rung at all -- a step can run headless every night and stand on no rung, which is
# precisely the gap intelligence.Benchmark exists to name and the reason trusted_for()
# answers no for an operation nobody measured.


class Rung(str, Enum):
  """The qualification ladder, bottom to top. A rung cannot be skipped."""

  SIMULATION = "simulation"
  DEVICE_ACCEPTANCE = "device_acceptance"
  INTEGRATED_DRY_RUN = "integrated_dry_run"
  VOLUMETRIC_QUALIFICATION = "volumetric_qualification"
  ASSAY_TRANSFER = "assay_transfer"
  SUSTAINED_PRODUCTION = "sustained_production"

  @property
  def height(self) -> int:
    return _RUNG_ORDER.index(self)

  @property
  def physical(self) -> bool:
    """True for every rung that requires the machine to have moved real material.

    The line the ladder exists to hold. SIMULATION is below it, and everything a simulation
    establishes is a statement about generated commands rather than about matter.
    """
    return self is not Rung.SIMULATION


_RUNG_ORDER: Tuple[Rung, ...] = (
  Rung.SIMULATION,
  Rung.DEVICE_ACCEPTANCE,
  Rung.INTEGRATED_DRY_RUN,
  Rung.VOLUMETRIC_QUALIFICATION,
  Rung.ASSAY_TRANSFER,
  Rung.SUSTAINED_PRODUCTION,
)


@dataclass(frozen=True)
class QualificationRung:
  """One rung, what passing it establishes, and what it explicitly does not.

  `does_not_qualify` is required for the same reason `because` is required on a decision
  class. A rung stated without its limit is how a real result becomes an overclaim: nobody
  fabricates the tip-insertion rate, they just let it stand in for the assay.
  """

  rung: Rung
  qualifies: str
  does_not_qualify: str
  evidence_key: Optional[str] = None

  def __post_init__(self) -> None:
    if not self.does_not_qualify.strip():
      raise ValueError(
        f"rung '{self.rung.value}' states no limit; a qualification with no stated limit "
        f"will be read as qualifying everything above it"
      )


LADDER: Tuple[QualificationRung, ...] = (
  QualificationRung(
    rung=Rung.SIMULATION,
    qualifies=(
      "that the commands a protocol generates are the ones intended, and that the sequence "
      "is internally coherent against a deck model"
    ),
    does_not_qualify=(
      "anything the machine does with them. PyLabRobot states the boundary itself: its unit "
      "tests establish that user input produces consistent machine-level commands, and after "
      "the commands are transmitted they are explicitly no longer the library's "
      "responsibility. Its simulator is designed to work with any robot for which a deck "
      "model exists, and the authors say plainly that some development still requires "
      "physical access to a robot. No accuracy or precision data is reported anywhere in "
      "that work, so nothing at this rung is a statement about volume in a well"
    ),
    evidence_key="pylabrobot",
  ),
  QualificationRung(
    rung=Rung.DEVICE_ACCEPTANCE,
    qualifies=(
      "that one device performs the mechanical action it claims, repeatably, measured on "
      "that device in that configuration"
    ),
    does_not_qualify=(
      "the assay, another device, or the same device in a different cell. RoboCulture "
      "reports 99.0 percent pipette-tip insertion across 576 attempts at six random plate "
      "placements -- a real number about a manipulator that says nothing about what ends up "
      "in the well. Its perception depends on fiducial tags, assumes they remain unoccluded, "
      "requires a calibration the authors call fragile to maintain, and is stated not to "
      "generalize beyond well plates"
    ),
    evidence_key="roboculture",
  ),
  QualificationRung(
    rung=Rung.INTEGRATED_DRY_RUN,
    qualifies=(
      "that stations, transfers, scheduling, and error paths survive an end-to-end pass with "
      "no material at risk"
    ),
    does_not_qualify=(
      "wet behavior, or any failure class the dry run did not contain. AlabOS is explicit "
      "that failures from worn-out hardware and newly emerged software communication "
      "exceptions were not detected in its soak test and still required operators, and its "
      "user-intervention module -- dashboard, Slack, email prompts for robot-arm error "
      "recovery and consumable replacement -- is load-bearing rather than vestigial. "
      "Autonomy at this rung means orchestration, not unattended operation"
    ),
    evidence_key="alabos",
  ),
  QualificationRung(
    rung=Rung.VOLUMETRIC_QUALIFICATION,
    qualifies=(
      "that delivered volume has been determined and reported for this installed system by a "
      "stated procedure, with the statistics indexed and tracked"
    ),
    does_not_qualify=(
      "acceptance. ISO 23783-1 covers vocabulary and general requirements and 23783-3 covers "
      "determination, specification and reporting of volumetric performance; the measurement "
      "procedures themselves are in Part 2, which is a separate document. None of them set a "
      "pass/fail tolerance for any particular assay, none certify an instrument, and the "
      "series is voluntary and scoped to complete installed systems that handle liquid "
      "without human intervention. It also addresses volume only -- not carryover, not "
      "sterility, not whether the assay means anything. The lab still has to say what volume "
      "error its assay tolerates, and that is a scientific claim carrying a Basis"
    ),
    evidence_key="iso23783",
  ),
  QualificationRung(
    rung=Rung.ASSAY_TRANSFER,
    qualifies=(
      "that this assay performs on this system, against criteria fixed before the data were "
      "collected"
    ),
    does_not_qualify=(
      "production. The HTS assay validation guidance is direct about its own scope: the "
      "replicate-experiment study is a diagnostic and decision tool for establishing that an "
      "assay is ready to go into production, and is explicitly not intended as a substitute "
      "for post-production monitoring. Its plate-uniformity design is three days of plates "
      "and its recommended acceptance criterion is signal window >= 2 or Z' >= 0.4 -- that "
      "manual's recommendation for HTS screening in drug discovery, not a universal quality "
      "bar and not a regulatory validation. Passing it says the assay is fit to screen; it "
      "says nothing about whether any hit it finds is real"
    ),
    evidence_key="ncats",
  ),
  QualificationRung(
    rung=Rung.SUSTAINED_PRODUCTION,
    qualifies=(
      "that the system held together across a real campaign, under the conditions of that "
      "campaign"
    ),
    does_not_qualify=(
      "a rate, or the next campaign, or the quality of what came out. The A-Lab realized 36 "
      "compounds from 57 targets over 17 days of continuous operation: one uncontrolled run "
      "on one instrument, no baseline against human chemists and no replicate campaign, so 63 "
      "percent describes that run and is not a capability benchmark. The same work is the "
      "reason this rung stays separate from the one below it -- four reported successes were "
      "later reclassified as inconclusive from diffraction alone, the title's claim of "
      "novelty was withdrawn in correction, and the senior author concedes a human can "
      "perform a higher-quality refinement than the automated pipeline did"
    ),
    evidence_key="a_lab",
  ),
)


LADDER_BY_RUNG: Dict[Rung, QualificationRung] = {r.rung: r for r in LADDER}


def implies(passed: Rung, claimed: Rung) -> bool:
  """Does passing `passed` establish `claimed`?

  True only when `claimed` sits at or below `passed`. Passing rung N never implies rung
  N+1, and the reason is not caution: each rung is qualified by a different measurement on a
  different thing. A simulation measures generated commands, device acceptance measures a
  mechanism, volumetric qualification measures delivered liquid. There is no inference from
  one to the next, only a further experiment.
  """
  return claimed.height <= passed.height


def qualified_for(passed: Sequence[Rung]) -> Tuple[Rung, ...]:
  """The rungs actually supported by a set of passed rungs: the contiguous run from the
  bottom, and nothing above the first gap.

  A lab that has passed simulation and assay transfer but never qualified volume is
  qualified for simulation. The assay-transfer result is not discarded -- it just does not
  stand on anything, and a result that does not stand on anything is not a qualification,
  because the thing it would have to be true of has not been characterized.
  """
  have = set(passed)
  out: List[Rung] = []
  for rung in _RUNG_ORDER:
    if rung not in have:
      break
    out.append(rung)
  return tuple(out)


def missing_below(claimed: Rung, passed: Sequence[Rung]) -> Tuple[Rung, ...]:
  """Every rung below `claimed` that has not been passed. Empty means the claim stands."""
  have = set(passed)
  return tuple(r for r in _RUNG_ORDER if r.height < claimed.height and r not in have)


def unsupported_claims(
  claimed: Sequence[Rung],
  passed: Sequence[Rung],
) -> Tuple[Tuple[Rung, Tuple[Rung, ...]], ...]:
  """(claim, the rungs missing under it) for every claim a lab cannot support.

  A claimed rung that was never itself passed counts as missing under itself, so claiming a
  rung on the strength of the one below it is caught by the same computation that catches
  skipping.
  """
  out: List[Tuple[Rung, Tuple[Rung, ...]]] = []
  have = set(passed)
  for c in claimed:
    gaps = missing_below(c, passed)
    if c not in have:
      gaps = gaps + (c,)
    if gaps:
      out.append((c, tuple(sorted(gaps, key=lambda r: r.height))))
  return tuple(out)


__all__ = [
  "Assignment",
  "Authority",
  "DECISION_CLASSES",
  "DECISION_CLASSES_BY_NAME",
  "DecisionClass",
  "LADDER",
  "LADDER_BY_RUNG",
  "Plan",
  "QualificationRung",
  "Rung",
  "Violation",
  "ViolationKind",
  "implies",
  "missing_below",
  "qualified_for",
  "strengthened",
  "unaccountable",
  "unsupported_claims",
  "violations",
]
