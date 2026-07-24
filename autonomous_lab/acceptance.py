"""Acceptance criteria: the scientific judgement that decides whether a run should go on.

The ledger answers "can this step run". This module answers the question that actually
stops experiments: given the numbers that came back, *should* the next one start? That
judgement is the thing a senior scientist supplies and a protocol document never quite
writes down, and encoding it is the point of the whole package.

Four ideas, each of which exists to stop a gate from passing something it should not.

  A criterion cannot be written without a source. `Criterion` refuses to construct with an
  empty `source`. Thresholds are where invented numbers do their damage: an undocumented
  cutoff looks exactly like a qualified one in code, and it will be obeyed. Requiring
  provenance on the number makes an unsourced threshold a
  construction error rather than a silent decision. Put the protocol section, the vendor
  spec, or the internal validation run in the field. "TODO: confirm with the method owner"
  is a legitimate source and an honest one; an empty string is not.

  Evidence tiers are earned, not declared. A caller says what it thinks a number is; this
  module decides what it is allowed to claim, by checking the instrument that produced it
  against the registry. Claim a measurement came off an instrument whose run card has
  never returned data and the claim is downgraded, with a reason. Nothing gets to promote
  itself.

  UNMEASURABLE is a verdict. If no instrument in this workcell can produce a metric today,
  the gate does not pass and does not fail: it reports that the number does not exist. A
  gate that returned PASS because it found no contradicting data would be the single most
  dangerous thing in this package. This mirrors the ledger's BROKEN row -- work that was
  attempted and failed is not the same as work nobody did, and the next action differs.

  Uncertainty gets a say. With a calibration set, `ConformalBand` produces an interval
  with a finite-sample coverage guarantee, and the gate only decides when the whole
  interval falls on one side of the threshold. When it straddles, the verdict is ESCALATE:
  go get ground truth. Without a calibration set there is no band and no guarantee, and
  the module says so rather than quietly comparing point estimates as if they were exact.

Stdlib only. The conformal layer is model-agnostic -- it needs a (prediction, spread) pair
from something, and the guarantee holds even when the spread is a crude heuristic, because
the calibration quantile absorbs the miscalibration.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

from .registry import FEDERATED, registry
from .workcell import Workcell


class EvidenceTier(str, Enum):
  """What a number is entitled to claim about where it came from. Weakest first."""

  MODELED = "modeled"  # a simulator or a calculation produced it; no instrument involved
  SIMULATED = "simulated"  # real orchestration code, but against a simulated backend
  MEASURED = "measured"  # a physical instrument returned it
  VALIDATED = "validated"  # measured AND the physical gates on that measurement passed

  @property
  def rank(self) -> int:
    return {"modeled": 0, "simulated": 1, "measured": 2, "validated": 3}[self.value]


class Judgement(str, Enum):
  """What a gate concluded.

  ESCALATE and UNMEASURABLE are both refusals to decide, and they are not the same
  refusal. ESCALATE means the data exists and is too uncertain to call, so a human or a
  better measurement settles it. UNMEASURABLE means the data does not exist and cannot be
  produced on this bench today, so the next action is engineering, not judgement.
  """

  PASS = "pass"
  FAIL = "fail"
  ESCALATE = "escalate"  # the interval straddles the threshold; get ground truth
  UNMEASURABLE = "unmeasurable"  # nothing in this workcell can produce this number


class Origin(str, Enum):
  """Where a threshold came from. The vocabulary is plr-tested's `provenance.Origin`,
  reused rather than reinvented so a rubric can move between the two packages.

  TRANSCRIBED is the only one that means "somebody wrote this number down somewhere I can
  point at". The other three are admissions, in decreasing order of comfort, and the last
  two block a hardware run outright.
  """

  TRANSCRIBED = "transcribed"  # copied from a protocol, kit insert, spec, or validated run
  TUNABLE = "tunable"  # a working default; defensible, not externally cited, verify locally
  CALIBRATE = "calibrate"  # cannot be known until this bench is calibrated
  TODO = "todo"  # nobody has decided this yet

  @property
  def blocking(self) -> bool:
    """True for origins that must not gate a real run.

    A gate cannot be passed against a threshold nobody has pinned. That sounds harsh and
    it is the honest reading: comparing a measurement to a number somebody intends to
    decide later is not a decision, it is the appearance of one.
    """
    return self in (Origin.CALIBRATE, Origin.TODO)


class UnsourcedCriterion(ValueError):
  """A threshold with no stated origin. Raised at construction, deliberately: an unsourced
  number that reaches a gate is indistinguishable from a sourced one, and it will be
  obeyed just as faithfully."""


_COMPARATORS = {
  ">=": lambda v, t: v >= t,
  "<=": lambda v, t: v <= t,
  ">": lambda v, t: v > t,
  "<": lambda v, t: v < t,
}


@dataclass(frozen=True)
class Criterion:
  """One numeric condition on one metric.

  `source` is mandatory and checked. See the module docstring: this is the field that
  keeps invented thresholds out of the gates.
  """

  metric: str
  comparator: str
  threshold: Optional[float]
  units: str
  source: str
  origin: Origin = Origin.TUNABLE
  note: str = ""

  def __post_init__(self):
    if not self.source or not self.source.strip():
      raise UnsourcedCriterion(
        f"criterion on '{self.metric}' has no source. Cite the protocol section, vendor "
        "spec, or validation run the threshold comes from. An admitted placeholder is "
        "acceptable and honest (origin=TODO, source='nobody has set this yet'); silence "
        "is not."
      )
    if self.comparator not in _COMPARATORS:
      raise ValueError(
        f"unknown comparator '{self.comparator}'; use one of {sorted(_COMPARATORS)}"
      )
    if self.threshold is None and not self.origin.blocking:
      raise ValueError(
        f"criterion on '{self.metric}' has no threshold but origin is "
        f"'{self.origin.value}'; unset thresholds must be CALIBRATE or TODO"
      )
    if self.threshold is not None and not math.isfinite(self.threshold):
      raise ValueError(f"criterion on '{self.metric}' has a non-finite threshold")

  @property
  def provisional(self) -> bool:
    """True for any threshold that is not transcribed from something citable.

    Surfaced everywhere a gate is reported. A threshold nobody has confirmed still stops
    or passes a run, and the report should not let it pass for settled science.
    """
    return self.origin is not Origin.TRANSCRIBED

  def holds(self, value: float) -> bool:
    if self.threshold is None:
      raise RuntimeError(
        f"criterion on '{self.metric}' has no operator-supplied threshold"
      )
    return _COMPARATORS[self.comparator](value, self.threshold)

  def describe(self) -> str:
    threshold = "unset" if self.threshold is None else f"{self.threshold:g}"
    return f"{self.metric} {self.comparator} {threshold} {self.units}"


@dataclass(frozen=True)
class Measurement:
  """A number that came back, and the claim its producer makes about it.

  `claimed` is what the caller says this is. It is a request, not a fact: `earned_tier`
  decides what the number may actually claim, and it never rounds up.

  `spread` is an optional uncertainty (a standard deviation, or any positive scale). It
  does not need to be calibrated. If a `ConformalBand` is available the band turns
  whatever this is into an interval with a real coverage guarantee; if it is not, the
  spread is reported and not otherwise trusted.
  """

  metric: str
  value: float
  units: str
  instrument: str
  op: str
  claimed: EvidenceTier = EvidenceTier.MODELED
  spread: Optional[float] = None
  note: str = ""


def earned_tier(m: Measurement, wc: Optional[Workcell] = None) -> Tuple[EvidenceTier, str]:
  """What this measurement is actually entitled to claim, and why.

  The rule is that a claim is capped by the state of the instrument that supposedly
  produced it, and the cap is read out of the registry rather than taken on trust:

    an op whose run card FAILED on the instrument caps at MODELED. The instrument has
    never returned this number, so a value attributed to it did not come from it.

    an op whose run card exists but has only ever run dry caps at SIMULATED. Real
    orchestration, no contact with material.

    an op with a validated run card may reach MEASURED. Not VALIDATED: that tier means the
    physical gates on the measurement also passed, which is not knowable until they run.
    `promote` handles it, after the fact, on evidence.

    anything else caps at MODELED.

  The returned tier is the weaker of what was claimed and what was earned, so a caller can
  always under-claim and can never over-claim.
  """
  wc = wc or Workcell.default()
  cap = EvidenceTier.MODELED
  why = f"'{m.instrument}' is not a federated instrument with run cards; nothing to earn a claim from"

  fed = FEDERATED.get(m.instrument)
  if fed is not None:
    if m.op in fed.known_failures:
      cap = EvidenceTier.MODELED
      why = (
        f"the run card for '{m.op}' on {fed.device} exists and FAILED on the instrument; "
        "it has never returned this number"
      )
    elif m.op in fed.written_ops:
      cap = EvidenceTier.SIMULATED
      why = f"the run card for '{m.op}' on {fed.device} runs dry and has never run wet"
    elif m.op in fed.validated_ops:
      if m.instrument in wc.federated and wc.plr_tested_root:
        cap = EvidenceTier.MEASURED
        why = f"'{m.op}' has a validated run card on {fed.device}"
      else:
        cap = EvidenceTier.SIMULATED
        why = (
          f"'{m.op}' has a validated run card on {fed.device}, but this workcell is not "
          "wired to the checkout that holds it"
        )
    else:
      why = f"no run card for '{m.op}' has been validated on {fed.device}"

  if m.claimed.rank <= cap.rank:
    return m.claimed, f"claimed {m.claimed.value}, which it is entitled to: {why}"
  return cap, f"claimed {m.claimed.value}, downgraded to {cap.value}: {why}"


def promote(tier: EvidenceTier, gates_passed: bool) -> EvidenceTier:
  """Raise MEASURED to VALIDATED, but only on passed physical gates.

  The one upward move in the module, and it is earned by evidence rather than asserted by
  a caller. A measured value whose gates failed stays MEASURED: it is a real number about
  a bad run, which is worth keeping and is not validation.
  """
  if tier is EvidenceTier.MEASURED and gates_passed:
    return EvidenceTier.VALIDATED
  return tier


# -- conformal intervals -------------------------------------------------------


@dataclass
class ConformalBand:
  """Split-conformal intervals with a finite-sample coverage guarantee.

  Calibrate on held-out points the model did not fit, then every interval covers the truth
  with probability at least 1 - alpha, whatever the model is. The nonconformity score is
  normalized by the predicted spread, so intervals widen exactly where the process is
  noisy instead of applying one flat width everywhere -- which matters here because the
  noisy regime is the low-input regime for the active laboratory method.

  The guarantee is honest but narrow, and it is worth being precise about what it assumes:
  calibration and future points are exchangeable. A reagent lot change, a new operator, or
  a different plate model breaks that, and the interval quietly stops meaning what it says.
  `coverage()` is here so the assumption can be audited against held-out truth rather than
  believed.
  """

  alpha: float = 0.1
  q: Optional[float] = None
  n_calibration: int = 0

  def calibrate(
    self, truths: Sequence[float], predictions: Sequence[float], spreads: Sequence[float]
  ) -> float:
    """Fit the quantile. Returns it, and stores it."""
    if not (len(truths) == len(predictions) == len(spreads)):
      raise ValueError("truths, predictions, and spreads must be the same length")
    n = len(truths)
    if n < 2:
      raise ValueError(
        f"a conformal band needs at least 2 calibration points, got {n}. With fewer, there "
        "is no quantile to take and an interval would be decoration."
      )
    scores = sorted(
      abs(t - p) / (s + 1e-12) for t, p, s in zip(truths, predictions, spreads)
    )
    # The finite-sample correction. Without the +1 the interval undercovers on small
    # calibration sets, which is exactly the regime a lab is in.
    level = min(1.0, math.ceil((n + 1) * (1 - self.alpha)) / n)
    idx = min(n - 1, max(0, math.ceil(level * n) - 1))
    self.q = scores[idx]
    self.n_calibration = n
    return self.q

  def interval(self, prediction: float, spread: float) -> Tuple[float, float]:
    if self.q is None:
      raise RuntimeError("band is not calibrated; call calibrate() first")
    half = self.q * (spread + 1e-12)
    return prediction - half, prediction + half

  def coverage(
    self, truths: Sequence[float], predictions: Sequence[float], spreads: Sequence[float]
  ) -> float:
    """Fraction of held-out truths the intervals actually cover.

    The self-audit. Compare it to 1 - alpha: materially below means exchangeability broke
    and the guarantee is not currently being kept.
    """
    if self.q is None:
      raise RuntimeError("band is not calibrated; call calibrate() first")
    if not truths:
      return 0.0
    hits = 0
    for t, p, s in zip(truths, predictions, spreads):
      lo, hi = self.interval(p, s)
      if lo <= t <= hi:
        hits += 1
    return hits / len(truths)


def triage(criterion: Criterion, lo: float, hi: float) -> Judgement:
  """Decide a criterion from an interval rather than a point.

  PASS only when the entire interval satisfies the criterion, FAIL only when none of it
  does, ESCALATE when it straddles. The asymmetry is the point: a gate that decided on the
  midpoint would be confidently wrong exactly in the cases where the measurement was too
  uncertain to support a decision.
  """
  if criterion.holds(lo) and criterion.holds(hi):
    return Judgement.PASS
  if not criterion.holds(lo) and not criterion.holds(hi):
    return Judgement.FAIL
  return Judgement.ESCALATE


# -- gates ---------------------------------------------------------------------


@dataclass(frozen=True)
class CriterionResult:
  criterion: Criterion
  judgement: Judgement
  value: Optional[float]
  interval: Optional[Tuple[float, float]]
  reason: str


@dataclass(frozen=True)
class GateResult:
  """What a gate concluded, and everything needed to argue with it."""

  gate: str
  judgement: Judgement
  results: Tuple[CriterionResult, ...]
  tier: Optional[EvidenceTier]
  reason: str

  @property
  def proceed(self) -> bool:
    """True only on PASS. Both refusals stop the run, and so does FAIL."""
    return self.judgement is Judgement.PASS

  def render(self) -> str:
    lines = [f"gate {self.gate}: {self.judgement.value.upper()}", f"  {self.reason}"]
    for r in self.results:
      shown = "no value" if r.value is None else f"{r.value:g}"
      if r.interval is not None:
        shown += f" [{r.interval[0]:.4g}, {r.interval[1]:.4g}]"
      flag = "" if r.criterion.origin is Origin.TRANSCRIBED else f"  [{r.criterion.origin.value.upper()}]"
      lines.append(f"    {r.judgement.value.upper():<12} {r.criterion.describe()}   got {shown}{flag}")
      lines.append(f"      source: {r.criterion.source}")
      # Always show how the number was rated, including any downgrade. A gate that passed
      # on a modeled value is a different fact from one that passed on a measured value,
      # and hiding the difference in a field nobody prints would defeat the tier system.
      lines.append(f"      evidence: {r.reason}")
    return "\n".join(lines)


@dataclass(frozen=True)
class Gate:
  """A named set of criteria guarding one point in a protocol.

  `produced_by` names the (instrument, op) that has to return the numbers. It is what
  lets the gate report UNMEASURABLE instead of inventing a pass: if that op cannot produce
  data on this bench, no threshold on it means anything today.
  """

  name: str
  guards: str  # the step or artifact this gate stands in front of
  criteria: Tuple[Criterion, ...]
  produced_by: Tuple[str, str]  # (instrument, op)
  note: str = ""

  @property
  def provisional(self) -> bool:
    return any(c.provisional for c in self.criteria)

  def blocking_criteria(self) -> Tuple[Criterion, ...]:
    """Criteria whose threshold is not settled enough to gate a real run."""
    return tuple(c for c in self.criteria if c.origin.blocking)

  def ready_for_hardware(self) -> Tuple[bool, List[str]]:
    """Whether this rubric may be used to gate material.

    The analogue of plr-tested's `RunGuard.assert_ready_for_hardware`, and it exists for
    the same reason: the moment a gate touches real samples, an unpinned threshold stops
    being a documentation gap and becomes a decision made by accident.
    """
    reasons = [
      f"{c.metric}: threshold "
      f"{'unset' if c.threshold is None else f'{c.threshold:g}'} "
      f"{c.units} is {c.origin.value} ({c.source})"
      for c in self.blocking_criteria()
    ]
    return (not reasons), reasons

  def measurable(self, wc: Optional[Workcell] = None) -> Tuple[bool, str]:
    """Whether this bench can produce the numbers this gate needs, at all.

    Checked against the same registry the ledger uses, so a gate cannot believe in a
    measurement the rest of the package knows is impossible.
    """
    wc = wc or Workcell.default()
    instrument, op = self.produced_by
    fed = FEDERATED.get(instrument)
    if fed is None:
      # A reverse-engineered instrument. Same test the ledger applies to a step: a
      # zero-decode read works today, anything else needs its command decoded. Deferring
      # to "not decided here" would let a gate believe in a number the rest of the package
      # knows nothing can produce.
      reg = registry()
      if instrument not in reg:
        return False, f"'{instrument}' is not an instrument this workcell knows about"
      spec = reg[instrument]
      cfg = wc.instruments.get(instrument)
      if cfg is None or not cfg.present:
        return False, f"{spec.device} is not in this workcell"
      if op in {o.value for o in spec.zero_decode}:
        return True, f"{spec.device} produces '{op}' read-only, with no decoding"
      cmd = wc.protocol_map(instrument).commands.get(op)
      if cmd is None:
        return False, (
          f"'{op}' is neither a zero-decode read nor a command in the map for {spec.device}; "
          "no path to this number exists"
        )
      if not cmd.decoded:
        return False, (
          f"'{op}' is undecoded on {spec.device}; nothing can produce this number today"
        )
      return True, f"'{op}' is decoded on {spec.device}"
    if op in fed.known_failures:
      run = fed.known_failures[op]
      return False, (
        f"{fed.device} cannot produce '{op}': the run card {run.script} exists and FAILED "
        f"on the instrument. {run.evidence}"
      )
    if op in fed.written_ops:
      return False, (
        f"{fed.device} has a run card for '{op}' that has only ever run dry; it has never "
        "returned a number from material"
      )
    if op in fed.validated_ops:
      return True, f"{fed.device} has a validated run card for '{op}'"
    return False, f"no run card for '{op}' has been validated on {fed.device}"

  def evaluate(
    self,
    measurements: Sequence[Measurement],
    wc: Optional[Workcell] = None,
    band: Optional[ConformalBand] = None,
  ) -> GateResult:
    """Judge this gate against the numbers that came back.

    Order matters and is deliberate. Measurability is checked first, before any value is
    looked at, so a gate in front of a broken instrument reports UNMEASURABLE even if
    somebody handed it a number. A value that arrives from an instrument that cannot
    produce it is evidence about the caller, not about the sample.
    """
    wc = wc or Workcell.default()
    ok, why = self.measurable(wc)
    if not ok:
      return GateResult(self.name, Judgement.UNMEASURABLE, (), None, why)

    by_metric: Dict[str, Measurement] = {m.metric: m for m in measurements}
    results: List[CriterionResult] = []
    tier: Optional[EvidenceTier] = None

    for c in self.criteria:
      m = by_metric.get(c.metric)
      if m is None:
        results.append(
          CriterionResult(c, Judgement.UNMEASURABLE, None, None, "no measurement supplied")
        )
        continue
      earned, tier_why = earned_tier(m, wc)
      tier = earned if tier is None else (earned if earned.rank < tier.rank else tier)
      # A threshold nobody has pinned cannot decide anything, however good the measurement
      # is. Escalate rather than compare: the number is fine, the rubric is the problem,
      # and the person who can fix it is the method owner rather than the operator.
      if c.origin.blocking:
        results.append(
          CriterionResult(
            c,
            Judgement.ESCALATE,
            m.value,
            None,
            f"threshold origin is {c.origin.value}, which is not settled enough to gate "
            f"on: {c.source}",
          )
        )
        continue
      if band is not None and band.q is not None and m.spread is not None:
        lo, hi = band.interval(m.value, m.spread)
        j = triage(c, lo, hi)
        reason = (
          f"{tier_why}; conformal interval at alpha={band.alpha:g} "
          f"from {band.n_calibration} calibration points"
        )
        results.append(CriterionResult(c, j, m.value, (lo, hi), reason))
      else:
        j = Judgement.PASS if c.holds(m.value) else Judgement.FAIL
        reason = f"{tier_why}; point comparison, no calibrated interval, no coverage guarantee"
        results.append(CriterionResult(c, j, m.value, None, reason))

    judgements = [r.judgement for r in results]
    if not judgements:
      return GateResult(self.name, Judgement.UNMEASURABLE, (), tier, "this gate has no criteria")
    # Refusals dominate, and UNMEASURABLE dominates ESCALATE. A missing number is a worse
    # position than an uncertain one, and reporting the milder of the two would understate
    # what is wrong.
    if Judgement.UNMEASURABLE in judgements:
      verdict, reason = Judgement.UNMEASURABLE, "at least one metric has no measurement"
    elif Judgement.FAIL in judgements:
      verdict, reason = Judgement.FAIL, "at least one criterion is definitively not met"
    elif Judgement.ESCALATE in judgements:
      verdict, reason = (
        Judgement.ESCALATE,
        "at least one interval straddles its threshold; get ground truth before proceeding",
      )
    else:
      verdict, reason = Judgement.PASS, "every criterion clears on the whole interval"
    unpinned = self.blocking_criteria()
    if unpinned:
      reason += (
        f". NOTE: {len(unpinned)} threshold(s) here are not pinned "
        f"({', '.join(c.metric for c in unpinned)}); this rubric cannot gate material yet"
      )
    elif self.provisional:
      reason += ". NOTE: at least one threshold here is a local default, not externally cited"
    return GateResult(self.name, verdict, tuple(results), tier, reason)
