"""What a predictive world model buys a bench QC layer, and what it provably does not.

`vision` draws two separate lines and this module only moves one of them. That asymmetry
is the whole content here, so it is worth being exact about which line moves.

The first line is INVISIBLE, and it is a claim about physics rather than about model
quality. A well of denatured enzyme and a well of active enzyme emit the same photons. A
model of what the scene should look like next therefore predicts the SAME frame for both,
and the deviation between prediction and observation is zero for the failure that matters
most. No architecture, no scale, and no amount of nominal data moves that boundary by one
micron, because the boundary is not about the model. It is about the light.

The second line is LABELS, and it is a claim about data rather than about physics. A
supervised detector needs labeled examples of the FAILURE; failures are rare by design and
nobody photographs the run that went wrong at the moment it went wrong. This is the
requirement that actually blocks the visible checks, and a model that learns what NORMAL
looks like removes it: deviation from an expected scene flags a departure without anyone
having ever seen that departure before.

So the honest summary is: a world model attacks the labeled-failure blocker and does not
touch the invisible boundary. `lifts()` computes the first claim per check. `unmoved()`
computes the second, from `vision`'s own taxonomy rather than restating it, so the standing
list cannot drift away from the modules that own those records.

WHAT THE APPROACH INTRODUCES, WHICH IS NOT NOTHING

Removing a requirement is not the same as removing a cost, and the label-free literature is
unusually clear about the bill. Two of the introduced requirements cannot be borrowed from
anyone else's bench:

  NOMINAL_DATA. The monitor needs enough nominal runs to define normal HERE, spanning the
  benign variation this bench actually has. OpenOOD v1.5's own conclusion is that the
  dominant failure of these detectors is over-detection: they are sensitive to non-semantic
  covariate shift and tend to flag shifted but perfectly in-distribution samples as
  anomalies. Change the lighting, the camera, or the reagent lot and a normal run reads as
  a failure. Worse, the nominal set is usually not clean: the industrial anomaly-detection
  literature reports human operators missing some defect types up to 25 percent of the
  time, which contaminates the very set that is supposed to define normal.

  FALSE_POSITIVE_RATE. Measured on real nominal variation, on this bench. FIPER
  (NeurIPS 2025), which needs no failure data and calibrates on successful rollouts alone,
  reports at its best operating point a true-positive rate of 0.91 against a true-negative
  rate of 0.65: to catch 91 percent of failures it flags 35 percent of SUCCESSFUL runs.
  Loosen the combination rule and it goes to 95 percent false positives. That is a
  published figure on a robot benchmark and it is a proxy, not a prediction about this
  bench, which is exactly why the rate has to be measured rather than cited.

DYNAMICS is the third introduced requirement and the only transferable one: a pretrained
model of how scenes evolve can be downloaded. That is the entire asymmetry the enum
encodes, and it is why a label-free monitor is not a download.

WHAT A DEVIATION SIGNAL ACTUALLY SAYS

It says the scene is not what was expected. It does not say what went wrong, and it does
not say the deviation matters. An anomaly detector that fires on a technician's sleeve
crossing the frame has detected something real and useless. FIPER states the same finding
from the other direction: the hard problem is separating a SUCCESSFUL out-of-distribution
run from a FAILING in-distribution one, because most novelty is benign. Reporting a
deviation as a failure is an inference the signal does not license, so `Claim` marks the
one claim that survives and the two that do not.

There is a further reason to distrust the reference the deviation is measured against.
Physics-IQ scored generative video models against the natural variance between two real
videos of the same scenario and found visual realism and physical understanding
UNCORRELATED across models: Pearson r = -0.46, p = 0.249. The most visually plausible model
ranked last on physics. A predicted frame that looks right is not thereby a frame that is
right, so a small deviation from a plausible-looking prediction is not evidence that the
bench is behaving.

THE CEILING, WHICH IS THIS REPO'S OWN EXISTING RULE

`vision.VisionRequirement.VALIDATION` is defined as measured sensitivity on held-out real
failures. A label-free approach removes LABELS and does not remove VALIDATION, and it
cannot: a miss rate is a statement about failures, and no quantity of nominal data contains
one. So `safety_device()` refuses for every approach whose miss rate nobody measured, which
is `vision`'s rule applied unchanged -- a detector whose miss rate on real failures nobody
measured is not a safety device but a belief about one, and installing one makes a lab less
safe than having none, because the operator stops looking.

One thing this module does NOT claim. `unmoved()` says no deviation signal reaches a
condition. It does not say nothing catches it: the STAR raising USBError [Errno 16] on a
second driver process catches a condition no camera could ever see. Whether anything in
this lab notices a failure is `recovery`'s question and is resolved there, not recomputed
here; `unmoved_and_silent()` intersects the two and that intersection is the expensive set.

Nothing in this workcell has a camera, so every lift here is hypothetical and every
deployability answer is no. The module reports which requirement is missing rather than
implying the work is nearly done.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .intelligence import BENCHMARKS, BenchmarkStatus
from .qc import Basis
from .recovery import FAILURE_MODES, RecoveryReport, visual_checks_that_would_help
from .vision import (
  CHECKS,
  CHECKS_BY_NAME,
  Observable,
  VisionCapability,
  VisionRequirement,
  VisualCheck,
)


class Introduced(str, Enum):
  """What a label-free monitor needs that `vision.VisionRequirement` does not name.

  The load-bearing line is TRANSFERABLE. A model of dynamics is somebody else's artifact
  and can be downloaded; the dominant convention in the field is exactly that -- pretrain
  on large-scale passive video, post-train a little on the target embodiment. The other
  two are statements about THIS bench under THIS lighting with THIS reagent lot, and no
  paper, vendor, or public checkpoint contains them.

  A lab that reads a published false-positive rate and treats it as its own has satisfied
  nothing. That is the mistake this enum is shaped to make visible.
  """

  NOMINAL_DATA = "nominal_data"  # enough normal runs, spanning this bench's benign variation
  FALSE_POSITIVE_RATE = "false_positive_rate"  # measured here, on real nominal variation
  DYNAMICS = "dynamics"  # a model of what the scene does next

  @property
  def transferable(self) -> bool:
    """Whether another lab's version of this requirement can be borrowed wholesale.

    True only for DYNAMICS. The two that are false are the two that block deployment, and
    they are false for the same reason: both are measurements of a particular bench, and a
    measurement of a different bench is not a weaker version of them, it is a different
    quantity.
    """
    return self is Introduced.DYNAMICS


class Approach(str, Enum):
  """How a monitor learns what wrong looks like.

  The line is NEEDS_LABELED_FAILURES, and it is the only reason to prefer one of these to
  another in a lab. Detection quality is not the axis -- a supervised classifier trained on
  a thousand labeled bead-loss images would beat any of this. The axis is that the thousand
  images do not exist and will not exist, because a lab that could produce them on demand
  would have already fixed the failure.
  """

  SUPERVISED = "supervised"  # learns the failure from labeled examples of the failure
  RECONSTRUCTION = "reconstruction"  # learns nominal appearance; scores what it cannot rebuild
  PREDICTIVE = "predictive"  # learns nominal dynamics; scores what it did not expect

  @property
  def needs_labeled_failures(self) -> bool:
    """The requirement this repo is actually blocked on."""
    return self is Approach.SUPERVISED

  @property
  def removes(self) -> Tuple[VisionRequirement, ...]:
    """Which of `vision`'s requirements this approach genuinely retires.

    Exactly one, and only for the label-free approaches. Notably NOT VALIDATION: a miss
    rate is a fact about failures, so an approach that never sees a failure cannot supply
    one. That omission is the module's ceiling and it is derived here rather than argued.
    """
    if self.needs_labeled_failures:
      return ()
    return (VisionRequirement.LABELS,)

  @property
  def introduces(self) -> Tuple[Introduced, ...]:
    """The bill that comes with the removal.

    SUPERVISED introduces nothing because `vision` already prices it: LABELS and VALIDATION
    are the two requirements it stalls on and they are already on the list.
    """
    if self.needs_labeled_failures:
      return ()
    if self is Approach.PREDICTIVE:
      return (Introduced.NOMINAL_DATA, Introduced.FALSE_POSITIVE_RATE, Introduced.DYNAMICS)
    return (Introduced.NOMINAL_DATA, Introduced.FALSE_POSITIVE_RATE)


class Claim(str, Enum):
  """The three things a deviation signal is routinely read as saying.

  The line is SUPPORTED, and only the first crosses it. The other two are inferences a
  human or a second sensor supplies, and a monitor that reports them as findings is
  overclaiming in the direction that costs a lab its trust in the monitor.
  """

  NOT_AS_EXPECTED = "not_as_expected"  # the scene differs from what the model predicted
  WHAT_WENT_WRONG = "what_went_wrong"  # which failure mode produced the difference
  WHETHER_IT_MATTERS = "whether_it_matters"  # the difference is consequential

  @property
  def supported(self) -> bool:
    """True only for the bare statement of deviation."""
    return self is Claim.NOT_AS_EXPECTED


@dataclass(frozen=True)
class SignalClaim:
  """One claim, and why the deviation signal does or does not license it."""

  claim: Claim
  statement: str
  why: str

  @property
  def supported(self) -> bool:
    """Resolved from the enum rather than stored, so the two cannot disagree."""
    return self.claim.supported


DEVIATION_CLAIMS: Tuple[SignalClaim, ...] = (
  SignalClaim(
    claim=Claim.NOT_AS_EXPECTED,
    statement="the observed scene differs from the model's expectation by more than a threshold",
    why=(
      "this is the measurement itself, and it is the only one the monitor performs. Its "
      "value is entirely set by whether the threshold was calibrated on this bench's own "
      "benign variation"
    ),
  ),
  SignalClaim(
    claim=Claim.WHAT_WENT_WRONG,
    statement="a named failure mode occurred",
    why=(
      "the score is a scalar distance. It carries no attribution, and the deviation "
      "produced by a lost bead pellet is not distinguishable from the deviation produced "
      "by a technician's sleeve crossing the frame. Naming the failure requires the "
      "labeled examples the approach was chosen to avoid needing"
    ),
  ),
  SignalClaim(
    claim=Claim.WHETHER_IT_MATTERS,
    statement="the run should be stopped, retried, or escalated",
    why=(
      "novelty and consequence are different quantities and most novelty is benign. The "
      "published framing of the hard case is separating a SUCCESSFUL out-of-distribution "
      "run from a FAILING in-distribution one, and a deviation score orders neither"
    ),
  ),
)


@dataclass(frozen=True)
class ReportedRate:
  """A false-positive figure somebody else measured, on somebody else's bench.

  Carried as data rather than prose so the reporting rule is enforceable: `basis` is
  `qc.Basis`, the same discipline this repo applies to a QC threshold, and a published
  number is LITERATURE forever. `describes_this_bench` is therefore False for every row
  here and will stay False no matter how many rows are added, which is the point.
  """

  source: str
  setting: str
  true_positive_rate: float
  false_positive_rate: float
  basis: Basis = Basis.LITERATURE
  note: str = ""

  def __post_init__(self) -> None:
    for field_name in ("true_positive_rate", "false_positive_rate"):
      value = getattr(self, field_name)
      if not 0.0 <= value <= 1.0:
        raise ValueError(f"'{self.source}' reports {field_name} {value}, which is not a rate")

  @property
  def describes_this_bench(self) -> bool:
    """Never true for a published figure, and the property exists to say so out loud."""
    return self.basis.validated


# What the label-free literature actually reports at a stated operating point. Included
# because a lab planning this work deserves the order of magnitude, and excluded from every
# computation because none of it is a measurement of this bench. There is no published
# false-alarms-per-shift figure for a deployed label-free detector in any domain, so this
# table is the closest bounded proxy available and is labeled as one.
REPORTED_RATES: Tuple[ReportedRate, ...] = (
  ReportedRate(
    source="FIPER, NeurIPS 2025 (arXiv:2510.09459), Table 2, AND rule, time-varying threshold",
    setting="5 robot manipulation tasks, 3 simulated and 2 real; diffusion and flow-matching",
    true_positive_rate=0.91,
    false_positive_rate=0.35,
    note=(
      "the cleanest published operating point for a monitor that needs no failure data: "
      "calibrated on 50 successful rollouts in simulation and 10 on real hardware. To "
      "catch 91 percent of failures it flags 35 percent of successful runs"
    ),
  ),
  ReportedRate(
    source="FIPER, NeurIPS 2025 (arXiv:2510.09459), Table 2, AND rule, conformal band",
    setting="same benchmark, the conservative combination rule",
    true_positive_rate=0.72,
    false_positive_rate=0.16,
    note="the false-alarm rate is bought with a 19 point drop in detection",
  ),
  ReportedRate(
    source="FIPER, NeurIPS 2025 (arXiv:2510.09459), Table 2, OR rule, time-varying threshold",
    setting="same benchmark, the permissive combination rule",
    true_positive_rate=1.00,
    false_positive_rate=0.95,
    note=(
      "catches everything by flagging almost everything. Reported here because it is the "
      "shape a monitor takes when the threshold is set to avoid misses"
    ),
  ),
  ReportedRate(
    source="CRCL (arXiv:2503.18808), Fig. 6, equal error rate on CUHK Avenue",
    setting="single-scene surveillance video, one-class training on normal video only",
    true_positive_rate=0.892,
    false_positive_rate=0.108,
    note=(
      "at the equal-error operating point the false-positive rate equals the miss rate by "
      "definition, so the true-positive rate is 1 minus the reported 10.8 percent EER. "
      "This is the best case in the table and it is a fixed-camera walkway, not a bench"
    ),
  ),
)


@dataclass(frozen=True)
class DeviationEvidence:
  """What one lab has actually collected for one label-free monitor.

  Every default is empty, which is the truth for every bench in this repo and the correct
  direction for the defaults to point: an unmeasured monitor is untrusted, not provisionally
  trusted. `nominal_spans` is the field a naive version would omit -- a thousand nominal
  runs recorded under one lighting condition on one reagent lot do not define normal, they
  define one corner of it, and a monitor calibrated there flags the next lot.
  """

  monitor: str = "none"
  nominal_runs: int = 0
  nominal_spans: Tuple[str, ...] = ()  # sources of benign variation the nominal set covers
  false_positive_rate: Optional[float] = None
  false_positive_basis: Basis = Basis.INTUITION
  dynamics_model: str = ""  # a named model of scene dynamics, borrowed or trained
  miss_rate: Optional[float] = None
  miss_rate_status: BenchmarkStatus = BenchmarkStatus.UNMEASURED
  note: str = ""

  def __post_init__(self) -> None:
    if self.nominal_runs < 0:
      raise ValueError(f"'{self.monitor}' declares {self.nominal_runs} nominal runs")
    for field_name in ("false_positive_rate", "miss_rate"):
      value = getattr(self, field_name)
      if value is not None and not 0.0 <= value <= 1.0:
        raise ValueError(f"'{self.monitor}' reports {field_name} {value}, which is not a rate")

  @classmethod
  def none(cls) -> "DeviationEvidence":
    """No monitor, no nominal corpus, no measured rate. Every bench in this repo."""
    return cls(
      monitor="none",
      note=(
        "no camera is mounted on any instrument in this repo, so no nominal corpus exists "
        "and no false-positive rate has ever been measured here"
      ),
    )

  def satisfies(self, requirement: Introduced) -> bool:
    """Whether this lab has met one introduced requirement.

    No count threshold is applied to NOMINAL_DATA and none is available to apply: the
    published calibration-set sizes are the authors' own choices for their own benchmarks
    and there is no recommended minimum for anything else. So the test is presence of a
    corpus AND a declared span of benign variation, which is the part that is actually
    load-bearing and the part a run count cannot substitute for.
    """
    if requirement is Introduced.NOMINAL_DATA:
      return self.nominal_runs > 0 and bool(self.nominal_spans)
    if requirement is Introduced.FALSE_POSITIVE_RATE:
      return self.false_positive_rate is not None and self.false_positive_basis.validated
    return bool(self.dynamics_model)

  def missing(self, required: Tuple[Introduced, ...]) -> Tuple[Introduced, ...]:
    return tuple(r for r in required if not self.satisfies(r))


@dataclass(frozen=True)
class Lift:
  """One visual check, one approach, and exactly what the approach does to its blockers.

  `removed` is the claim. `retained` is the honesty: everything `vision` asked for that a
  world model does not supply, VALIDATION above all. `introduced` is the bill. `blocked_on`
  is what this workcell still lacks after the removal, resolved through
  `VisionCapability.missing_for` rather than recomputed here.
  """

  check: VisualCheck
  approach: Approach
  removed: Tuple[VisionRequirement, ...]
  retained: Tuple[VisionRequirement, ...]
  introduced: Tuple[Introduced, ...]
  blocked_on: Tuple[VisionRequirement, ...]
  reason: str

  @property
  def moves_anything(self) -> bool:
    """True only when this approach retires a requirement this check actually had."""
    return bool(self.removed)

  @property
  def validation_retained(self) -> bool:
    """VALIDATION is measured sensitivity on held-out real failures. Nothing here supplies it."""
    return VisionRequirement.VALIDATION in self.retained

  @property
  def untransferable(self) -> Tuple[Introduced, ...]:
    """The introduced requirements no other lab's result can satisfy on this bench's behalf."""
    return tuple(r for r in self.introduced if not r.transferable)

  @property
  def operational_blockers(self) -> Tuple[VisionRequirement, ...]:
    """What stops the monitor RUNNING, as distinct from what stops it being trusted.

    VALIDATION is held out of this set on purpose. It is not a prerequisite for turning a
    monitor on -- it is the entire content of whether the monitor may be relied on, and
    `safety_device` asks that question separately. Folding the two together would make a
    bench with no measured miss rate indistinguishable from a bench with no camera, and
    those need different work.
    """
    return tuple(r for r in self.blocked_on if r is not VisionRequirement.VALIDATION)

  def missing(self, evidence: Optional[DeviationEvidence] = None) -> Tuple[Introduced, ...]:
    return (evidence or DeviationEvidence.none()).missing(self.introduced)

  def deployable(self, evidence: Optional[DeviationEvidence] = None) -> Tuple[bool, str]:
    """Could this monitor be turned on, ignoring for the moment whether it is a safety device.

    Deliberately separate from `safety_device`. A monitor can be legitimately deployable as
    an operator aid -- something that raises a hand for a human to look at -- while being
    nowhere near able to gate an action. Collapsing the two is how an anomaly score ends up
    stopping a run it was never validated to judge.
    """
    if not self.moves_anything:
      return False, self.reason
    ev = evidence or DeviationEvidence.none()
    if self.operational_blockers:
      names = ", ".join(r.value for r in self.operational_blockers)
      return False, f"'{self.check.name}' is still missing {names} in this workcell"
    gap = ev.missing(self.introduced)
    if gap:
      names = ", ".join(r.value for r in gap)
      return False, (
        f"the label-free requirement is not met: missing {names}. A monitor deployed "
        f"without them fires at an unknown rate on runs that were fine"
      )
    return True, (
      f"nominal data spans {', '.join(ev.nominal_spans)} and the false-positive rate was "
      f"measured on this bench at {ev.false_positive_rate}"
    )

  def safety_device(self, evidence: Optional[DeviationEvidence] = None) -> Tuple[bool, str]:
    """Has this monitor earned the right to be relied on to CATCH something?

    A miss rate is the whole question and it is a fact about failures. A label-free
    approach never sees one, so the only way to answer is to collect exactly the labeled
    failures the approach was chosen to avoid needing. That is not an argument against the
    approach; it is an argument against calling the result a safety device before the
    measurement exists.
    """
    ok, why = self.deployable(evidence)
    if not ok:
      return False, why
    ev = evidence or DeviationEvidence.none()
    if not ev.miss_rate_status.trusted:
      return False, (
        f"the miss rate on real failures is {ev.miss_rate_status.value}, so "
        f"'{VisionRequirement.VALIDATION.value}' is unmet. A detector whose miss rate "
        f"nobody measured is a belief about a safety device, not one"
      )
    return True, f"miss rate measured on held-out real failures at {ev.miss_rate}"


def lifts(
  check: VisualCheck,
  approach: Approach,
  capability: Optional[VisionCapability] = None,
) -> Lift:
  """What `approach` does to one visual check's blockers, in one workcell.

  The first branch is the one that matters and it is checked before anything else: an
  INVISIBLE condition produces identical frames whether or not it failed, so the deviation
  between prediction and observation is zero and there is nothing for any approach to
  score. `check.possible` is `vision`'s own property, so this refusal moves if and only if
  `vision`'s taxonomy moves.
  """
  cap = capability or VisionCapability.none()
  if not check.possible:
    return Lift(
      check=check,
      approach=approach,
      removed=(),
      retained=check.requires,
      introduced=(),
      blocked_on=cap.missing_for(check),
      reason=(
        "the failed and the clean run produce identical frames, so the deviation signal is "
        "zero for both. No approach at any capability moves this; it needs a different "
        "sensor, not a different model"
      ),
    )

  removed = tuple(r for r in approach.removes if r in check.requires)
  retained = tuple(r for r in check.requires if r not in removed)
  introduced = approach.introduces if removed else ()
  blocked_on = tuple(r for r in cap.missing_for(check) if r not in removed)

  if not removed:
    reason = (
      f"'{approach.value}' retires nothing this check declares; it still needs "
      f"{VisionRequirement.LABELS.value}, which is the requirement this lab is blocked on"
    )
  else:
    reason = (
      f"'{approach.value}' retires {', '.join(r.value for r in removed)} and introduces "
      f"{', '.join(r.value for r in introduced)}; "
      f"{VisionRequirement.VALIDATION.value} is retained and is not satisfiable without "
      f"the failures the approach avoids needing"
    )

  return Lift(
    check=check,
    approach=approach,
    removed=removed,
    retained=retained,
    introduced=introduced,
    blocked_on=blocked_on,
    reason=reason,
  )


@dataclass(frozen=True)
class UnmovedCondition:
  """One declared condition that no approach in this module touches, and who owns it.

  `what` is the owning record's own words, carried rather than rewritten, so this list
  cannot describe a condition differently from the module that declares it.
  """

  name: str
  owner: str  # the sibling module that declares this condition
  what: str
  observable: Observable

  @property
  def reachable_by_vision(self) -> bool:
    """Resolved from `vision`'s own property. False for every row here, by construction."""
    return self.observable.reachable_by_vision

  def why(self) -> str:
    """The single reason, which is the same reason for every row and is not per-condition.

    Written once as a derivation rather than stored per record: the moment this becomes a
    prose field, somebody edits one row and the list starts asserting different physics in
    different places.
    """
    return (
      f"'{self.name}' is {self.observable.value} in {self.owner}: the failed run and the "
      f"clean run produce the same image, so a model predicting the next frame predicts "
      f"the same frame for both and the deviation is zero"
    )


def _declared_conditions() -> Tuple[Tuple[str, str, str, Observable], ...]:
  """(name, owning module, the record's own words, its observability).

  Assembled from the three modules that carry `vision.Observable` on their records. Nothing
  is restated: each tuple's description is the owning dataclass's own field, and each
  observability is the owning dataclass's own classification. A condition reclassified in
  `recovery` or `intelligence` changes this list on the next call with no edit here.
  """
  rows: List[Tuple[str, str, str, Observable]] = []
  for failure in FAILURE_MODES:
    rows.append((failure.name, "recovery", failure.description, failure.observable))
  for benchmark in BENCHMARKS:
    rows.append((benchmark.name, "intelligence", benchmark.target, benchmark.observable))
  for check in CHECKS:
    rows.append((check.name, "vision", check.observes, check.observable))
  return tuple(rows)


def unmoved() -> Tuple[UnmovedCondition, ...]:
  """Every declared condition no approach here moves, computed from `vision`'s taxonomy.

  The filter is `Observable.reachable_by_vision`, which `vision` owns. That is deliberate
  and it is the reason this function exists rather than a list: the standing set of things
  a world model does not buy has to be a consequence of the physics taxonomy, not a second
  copy of it that somebody forgets to update.

  Note what this does NOT claim. Unmoved means no deviation signal reaches the condition.
  It does not mean nothing catches it: an instrument that raises on its own error catches
  a condition no camera could see, and `recovery` owns that question. Use
  `unmoved_and_silent()` to intersect the two.
  """
  return tuple(
    UnmovedCondition(name=name, owner=owner, what=what, observable=observable)
    for name, owner, what, observable in _declared_conditions()
    if not observable.reachable_by_vision
  )


def unmoved_and_silent(report: RecoveryReport) -> List[UnmovedCondition]:
  """Unmoved conditions that nothing in this lab would notice either.

  The intersection is the expensive set: no world model reaches them and no existing path
  catches them, so they are the failures for which the answer is a different sensor, a
  control, or a barcode. Silence is read off `recovery`'s own resolution rather than
  recomputed, so this cannot disagree with the failure report.
  """
  silent = {row.failure.name for row in report.silent()}
  return [row for row in unmoved() if row.name in silent]


@dataclass
class WorldModelReport:
  """Every visual check under one approach, costed against a real workcell."""

  approach: Approach
  rows: List[Lift]

  def moved(self) -> List[Lift]:
    """Checks whose blocking requirement this approach genuinely retires."""
    return [row for row in self.rows if row.moves_anything]

  def deployable(self, evidence: Optional[DeviationEvidence] = None) -> List[Lift]:
    return [row for row in self.rows if row.deployable(evidence)[0]]

  def safety_devices(self, evidence: Optional[DeviationEvidence] = None) -> List[Lift]:
    return [row for row in self.rows if row.safety_device(evidence)[0]]

  def unmoved(self) -> Tuple[UnmovedCondition, ...]:
    """Delegates, so a report and a direct call cannot give different answers."""
    return unmoved()

  def counts(self, evidence: Optional[DeviationEvidence] = None) -> Dict[str, int]:
    return {
      "checks": len(self.rows),
      "labels_retired": len(self.moved()),
      "deployable": len(self.deployable(evidence)),
      "safety_devices": len(self.safety_devices(evidence)),
      "unmoved_conditions": len(self.unmoved()),
    }


def world_model_report(
  approach: Approach = Approach.PREDICTIVE,
  capability: Optional[VisionCapability] = None,
) -> WorldModelReport:
  """Cost every declared visual check under one approach."""
  cap = capability or VisionCapability.none()
  return WorldModelReport(
    approach=approach,
    rows=[lifts(check, approach, cap) for check in CHECKS],
  )


def would_retire_labels(
  report: RecoveryReport,
  approach: Approach = Approach.PREDICTIVE,
  capability: Optional[VisionCapability] = None,
) -> List[Lift]:
  """The label-free shopping list, in the order `recovery` already ranks it.

  `recovery.visual_checks_that_would_help` decides which checks are worth wanting, because
  it owns the question of which failures are currently silent and which conditions are
  imageable at all. This function only asks what a label-free approach does to each one, so
  the two cannot disagree about which checks matter.
  """
  return [
    lifts(CHECKS_BY_NAME[name], approach, capability)
    for name in visual_checks_that_would_help(report)
  ]


def unsupported_claims() -> Tuple[SignalClaim, ...]:
  """The two things a deviation signal is read as saying and does not say."""
  return tuple(row for row in DEVIATION_CLAIMS if not row.supported)


def alarms_per_runs(evidence: DeviationEvidence, runs: int) -> Optional[float]:
  """Expected false alarms over `runs` nominal runs, or None when the rate is borrowed.

  Returns None rather than a number whenever the false-positive rate was not measured on
  this bench, and that is the entire function. There is no published false-alarms-per-shift
  figure for a deployed label-free detector in any domain, so multiplying somebody else's
  benchmark rate by this lab's run count produces a figure with no measured joint. A
  refusal is the correct output.
  """
  if runs < 0:
    raise ValueError(f"cannot project alarms over {runs} runs")
  if evidence.false_positive_rate is None or not evidence.false_positive_basis.validated:
    return None
  return evidence.false_positive_rate * runs


__all__ = [
  "Approach",
  "Claim",
  "DEVIATION_CLAIMS",
  "DeviationEvidence",
  "Introduced",
  "Lift",
  "REPORTED_RATES",
  "ReportedRate",
  "SignalClaim",
  "UnmovedCondition",
  "WorldModelReport",
  "alarms_per_runs",
  "lifts",
  "unmoved",
  "unmoved_and_silent",
  "unsupported_claims",
  "world_model_report",
  "would_retire_labels",
]
