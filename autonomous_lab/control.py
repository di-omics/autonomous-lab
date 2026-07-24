"""Feedback control: learn from the runs that happened, propose the next one, touch nothing.

This is the loop that makes a lab get better rather than merely run. It has two halves and
one invariant, and the invariant is the reason the rest of it is safe to have.

  Learning. Runs produce outcomes; outcomes update a per-step reliability estimate and a
  surrogate over laboratory-process parameters. Both report their own uncertainty,
  because the interesting regime for a real lab is five runs, not five hundred, and an
  estimator that hides how little it knows at n=3 is worse than no estimator.

  Proposing. Given what has been learned, the controller suggests the next setpoint to
  try, by optimizing an acquisition function over a bounded design space.

  The invariant: THE CONTROLLER CANNOT MOVE A GATE. It proposes parameters. It has no API
  that alters a `Criterion`, widens a threshold, or overrides a judgement, and there is a
  test that says so. This is the difference between a supervisory controller and an
  unsafe one. An optimizer that can relax its own acceptance criteria will eventually
  discover that the cheapest way to satisfy a constraint is to delete it, and in a lab
  that failure mode is indistinguishable from a scientist quietly lowering a cutoff until
  the run passes. The gates are the interlock, the controller sits outside it.

Two more refusals worth naming:

  Only real observations train. An observation carrying a modeled or simulated evidence
  tier is recorded and then ignored by the surrogate. A controller that learned from its
  own simulator would converge confidently on the simulator's biases, and it would look
  exactly like learning.

  No evidence, no proposal. Below a minimum number of trustworthy observations, `propose`
  refuses and says how many it has. The honest zero state of a controller is silence, not
  a confident suggestion drawn from a prior nobody chose.

Stdlib only: math and random. The surrogate is a kernel-weighted regression rather than a
Gaussian process, and its spread is a heuristic. That is fine, and deliberately so: the
conformal layer in `acceptance` is model-agnostic, so wrapping this crude spread in a
calibrated band still yields a real coverage guarantee. The good GP lives in
di-omics/ml-bio-eval behind numpy and sklearn, and this package stays laptop-computable.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .acceptance import ConformalBand, Criterion, EvidenceTier, Measurement, earned_tier
from .model import Protocol


# -- Bayesian reliability ------------------------------------------------------


def _betacf(a: float, b: float, x: float, itmax: int = 300, eps: float = 3e-16) -> float:
  """Continued fraction for the incomplete beta function (Lentz's method)."""
  tiny = 1e-300
  qab, qap, qam = a + b, a + 1.0, a - 1.0
  c = 1.0
  d = 1.0 - qab * x / qap
  if abs(d) < tiny:
    d = tiny
  d = 1.0 / d
  h = d
  for m in range(1, itmax + 1):
    m2 = 2 * m
    aa = m * (b - m) * x / ((qam + m2) * (a + m2))
    d = 1.0 + aa * d
    if abs(d) < tiny:
      d = tiny
    c = 1.0 + aa / c
    if abs(c) < tiny:
      c = tiny
    d = 1.0 / d
    h *= d * c
    aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
    d = 1.0 + aa * d
    if abs(d) < tiny:
      d = tiny
    c = 1.0 + aa / c
    if abs(c) < tiny:
      c = tiny
    d = 1.0 / d
    delta = d * c
    h *= delta
    if abs(delta - 1.0) < eps:
      break
  return h


def beta_cdf(x: float, a: float, b: float) -> float:
  """Regularized incomplete beta I_x(a, b). The Beta distribution's CDF."""
  if x <= 0.0:
    return 0.0
  if x >= 1.0:
    return 1.0
  lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
  front = math.exp(lbeta + a * math.log(x) + b * math.log1p(-x))
  if x < (a + 1.0) / (a + b + 2.0):
    return front * _betacf(a, b, x) / a
  return 1.0 - math.exp(lbeta + b * math.log1p(-x) + a * math.log(x)) * _betacf(b, a, 1.0 - x) / b


def beta_quantile(p: float, a: float, b: float, tol: float = 1e-9) -> float:
  """Inverse Beta CDF by bisection. Slow and exact enough; this runs on tens of points."""
  lo, hi = 0.0, 1.0
  for _ in range(200):
    mid = 0.5 * (lo + hi)
    if beta_cdf(mid, a, b) < p:
      lo = mid
    else:
      hi = mid
    if hi - lo < tol:
      break
  return 0.5 * (lo + hi)


@dataclass(frozen=True)
class Reliability:
  """What the record says about how often one step works.

  A Beta-Binomial posterior over the success rate, with a Jeffreys prior (0.5, 0.5). The
  credible interval is the part that matters: at n=3 it is nearly the whole unit interval,
  and printing it next to the point estimate is what stops "this step fails two thirds of
  the time" from being read as a fact when it is three data points.
  """

  step: str
  successes: int
  failures: int
  prior_a: float = 0.5
  prior_b: float = 0.5

  @property
  def n(self) -> int:
    return self.successes + self.failures

  @property
  def posterior(self) -> Tuple[float, float]:
    return self.prior_a + self.successes, self.prior_b + self.failures

  @property
  def success_rate(self) -> float:
    a, b = self.posterior
    return a / (a + b)

  @property
  def failure_rate(self) -> float:
    return 1.0 - self.success_rate

  def interval(self, mass: float = 0.9) -> Tuple[float, float]:
    """Equal-tailed credible interval on the success rate."""
    a, b = self.posterior
    tail = (1.0 - mass) / 2.0
    return beta_quantile(tail, a, b), beta_quantile(1.0 - tail, a, b)

  @property
  def informative(self) -> bool:
    """Whether this estimate is worth acting on at all.

    A 90% interval wider than half the unit interval means the data has barely moved the
    prior. Reported rather than hidden, so a ranking built on it can be labelled honestly.
    """
    lo, hi = self.interval()
    return (hi - lo) < 0.5

  def render(self) -> str:
    lo, hi = self.interval()
    tag = "" if self.informative else "   (too few runs to act on)"
    return (
      f"{self.step:<32} {self.success_rate:5.1%} success   90% CI "
      f"[{lo:.2f}, {hi:.2f}]   n={self.n}{tag}"
    )


@dataclass(frozen=True)
class WasteRank:
  """One entry in the do-this-first queue, ranked by what a failure there costs.

  Expected waste, not failure rate. A step that fails half the time at position 1 costs
  almost nothing -- you find out immediately and start again. The same failure rate at
  position 17 throws away sixteen completed steps, a plate, and a day. Ranking by
  probability alone would put those two in the wrong order, and the bench cares about the
  second one.
  """

  step: str
  position: int
  failure_rate: float
  steps_at_risk: int
  informative: bool

  @property
  def expected_waste(self) -> float:
    """Expected completed steps thrown away per run, from failing here."""
    return self.failure_rate * self.steps_at_risk


class ReliabilityModel:
  """Per-step reliability, accumulated from run outcomes."""

  def __init__(self):
    self._tally: Dict[str, List[int]] = {}

  def observe(self, step: str, ok: bool) -> None:
    s, f = self._tally.setdefault(step, [0, 0])
    if ok:
      self._tally[step] = [s + 1, f]
    else:
      self._tally[step] = [s, f + 1]

  def of(self, step: str) -> Reliability:
    s, f = self._tally.get(step, [0, 0])
    return Reliability(step=step, successes=s, failures=f)

  @classmethod
  def from_record(cls, record) -> "ReliabilityModel":
    """Learn from an audited run record. This is what closes the loop.

    Reads only entries of kind 'outcome', which carry `step` and `ok`. Proposals and
    decisions are deliberately not counted: a step that was refused did not run, and
    scoring a refusal as a failure would teach the controller that the gates are the
    problem. Over enough runs that is exactly the wrong lesson to learn.
    """
    m = cls()
    for e in record.of_kind("outcome"):
      step = e.payload.get("step")
      if step is None or "ok" not in e.payload:
        continue
      m.observe(str(step), bool(e.payload["ok"]))
    return m

  def known_steps(self) -> List[str]:
    return sorted(self._tally)

  def rank_by_expected_waste(self, protocol: Protocol) -> List[WasteRank]:
    """The engineering queue, ranked by what failing at each step throws away.

    Complements `ledger.unlocks`, which ranks by how many steps a decode would free. That
    one asks what is impossible; this one asks what is expensive. A lab with a working
    protocol and a flaky step 14 gets nothing from the first queue and everything from
    this one.

    Steps with no observations are omitted rather than given a prior-driven rate. Inventing
    a failure rate for a step nobody has run would put fiction at the top of a queue meant
    to direct real work.
    """
    out: List[WasteRank] = []
    for i, step in enumerate(protocol.steps):
      if step.op not in self._tally:
        continue
      r = self.of(step.op)
      out.append(
        WasteRank(
          step=step.op,
          position=i + 1,
          failure_rate=r.failure_rate,
          steps_at_risk=i,  # everything already completed when this one fails
          informative=r.informative,
        )
      )
    out.sort(key=lambda w: (-w.expected_waste, w.step))
    return out


# -- the surrogate and the controller -----------------------------------------


@dataclass(frozen=True)
class Bound:
  """One tunable parameter and the range it may be proposed within.

  `source` is mandatory for the same reason it is on a `Criterion`: an operating range is
  a scientific claim about what is safe to try, and an invented one will be obeyed.
  """

  name: str
  lo: float
  hi: float
  units: str
  source: str

  def __post_init__(self):
    if not self.source or not self.source.strip():
      raise ValueError(
        f"bound on '{self.name}' has no source. An operating range with no stated origin "
        "is a guess the controller will treat as physics."
      )
    if not self.hi > self.lo:
      raise ValueError(f"bound on '{self.name}' is empty: lo={self.lo}, hi={self.hi}")

  def unit(self, value: float) -> float:
    return (value - self.lo) / (self.hi - self.lo)

  def clamp(self, value: float) -> float:
    return min(self.hi, max(self.lo, value))


@dataclass(frozen=True)
class Observation:
  """One completed run: what was set, what came back, and how much it is worth.

  `tier` is load-bearing. Only MEASURED and VALIDATED observations train the surrogate;
  anything modeled or simulated is kept for the record and ignored for learning.
  """

  params: Dict[str, float]
  metrics: Dict[str, float]
  tier: EvidenceTier
  run_id: str = ""

  @property
  def trains(self) -> bool:
    return self.tier.rank >= EvidenceTier.MEASURED.rank

  @classmethod
  def earned(
    cls,
    params: Dict[str, float],
    measurements: Sequence["Measurement"],
    wc=None,
    run_id: str = "",
  ) -> "Observation":
    """Build an observation whose tier is earned from the instruments that produced it.

    Prefer this to the constructor. Constructing an `Observation` directly takes the
    caller's word for the tier, which is the one thing the rest of this package refuses to
    do; it stays possible because a record replayed from disk already carries a tier that
    was earned when it was written. Here the tier is recomputed, and it is the weakest
    across all the measurements: an observation is only as trustworthy as its worst number.
    """
    tier = EvidenceTier.VALIDATED
    for m in measurements:
      earned, _ = earned_tier(m, wc)
      if earned.rank < tier.rank:
        tier = earned
    return cls(
      params=dict(params),
      metrics={m.metric: m.value for m in measurements},
      tier=tier if measurements else EvidenceTier.MODELED,
      run_id=run_id,
    )


class KernelSurrogate:
  """Gaussian-kernel-weighted regression over a bounded parameter space.

  Not a Gaussian process. The mean is a Nadaraya-Watson average and the spread is the
  heuristic 1/sqrt(1 + sum of weights), which is 1 where no data lives and shrinks toward
  0 where data is dense. It is uncalibrated and makes no claim not to be. Wrap it in a
  `ConformalBand` and the resulting intervals carry a genuine finite-sample coverage
  guarantee anyway, because conformal calibration does not care how bad the underlying
  spread is -- it only needs it to be a consistent notion of scale.
  """

  def __init__(self, bounds: Sequence[Bound], length_scale: float = 0.15):
    self.bounds = list(bounds)
    self.length_scale = length_scale
    self._x: List[List[float]] = []
    self._y: List[float] = []

  def _encode(self, params: Dict[str, float]) -> List[float]:
    missing = [b.name for b in self.bounds if b.name not in params]
    if missing:
      raise KeyError(f"parameters missing for the surrogate: {', '.join(missing)}")
    return [b.unit(params[b.name]) for b in self.bounds]

  def fit(self, observations: Sequence[Observation], objective: str) -> int:
    """Train on the trustworthy observations only. Returns how many were used."""
    self._x, self._y = [], []
    for o in observations:
      if not o.trains or objective not in o.metrics:
        continue
      self._x.append(self._encode(o.params))
      self._y.append(float(o.metrics[objective]))
    return len(self._y)

  @property
  def n(self) -> int:
    return len(self._y)

  def predict(self, params: Dict[str, float]) -> Tuple[float, float]:
    """(mean, spread). With no data the spread is 1.0 and the mean is meaningless."""
    if not self._y:
      return 0.0, 1.0
    z = self._encode(params)
    weights = []
    for xi in self._x:
      d2 = sum((a - b) ** 2 for a, b in zip(z, xi))
      weights.append(math.exp(-d2 / (2.0 * self.length_scale ** 2)))
    total = sum(weights)
    if total <= 1e-12:
      return sum(self._y) / len(self._y), 1.0
    mean = sum(w * y for w, y in zip(weights, self._y)) / total
    return mean, 1.0 / math.sqrt(1.0 + total)


@dataclass(frozen=True)
class Proposal:
  """A suggested next setpoint. A suggestion, not a permission.

  Nothing about a proposal authorizes anything. It goes to `permission.decide`, which
  applies the gates, and either of them can refuse it. Keeping the two apart in the type
  system is what makes "an agent proposes, deterministic gates decide" a property of the
  code rather than a sentence in a README.
  """

  params: Dict[str, float]
  predicted: float
  spread: float
  interval: Optional[Tuple[float, float]]
  objective: str
  rationale: str
  trained_on: int


@dataclass(frozen=True)
class Refusal:
  """Why the controller declined to propose."""

  reason: str
  observations: int
  needed: int

  def render(self) -> str:
    return f"no proposal: {self.reason} ({self.observations} of {self.needed} needed)"


class Controller:
  """A supervisory controller over laboratory-process parameters.

  It reads criteria; it never writes them. The `criteria` passed in are used only to
  filter candidates whose predicted outcome would confidently violate one, and they are
  stored as a tuple of frozen dataclasses so there is nothing to mutate even by accident.
  """

  MIN_OBSERVATIONS = 4

  def __init__(
    self,
    bounds: Sequence[Bound],
    objective: str,
    maximize: bool = True,
    criteria: Sequence[Criterion] = (),
    kappa: float = 1.0,
    seed: int = 0,
  ):
    self.bounds = list(bounds)
    self.objective = objective
    self.maximize = maximize
    # Read-only by construction. There is deliberately no setter, no update method, and no
    # code path in this module that constructs a modified Criterion.
    self._criteria: Tuple[Criterion, ...] = tuple(criteria)
    self.kappa = kappa
    self.surrogate = KernelSurrogate(bounds)
    self.band = ConformalBand()
    self._rng = random.Random(seed)

  @property
  def criteria(self) -> Tuple[Criterion, ...]:
    return self._criteria

  def calibrate(self, observations: Sequence[Observation]) -> Optional[float]:
    """Fit the conformal band by leave-one-out over the trustworthy observations.

    Returns the quantile, or None when there is not enough held-out data to take one. The
    None case is not a failure; it means the proposals that follow carry an uncalibrated
    spread, and `Proposal.interval` will be None to say so.
    """
    usable = [o for o in observations if o.trains and self.objective in o.metrics]
    if len(usable) < 4:
      return None
    truths, preds, spreads = [], [], []
    for i, held in enumerate(usable):
      rest = usable[:i] + usable[i + 1 :]
      sub = KernelSurrogate(self.bounds, self.surrogate.length_scale)
      sub.fit(rest, self.objective)
      mu, sd = sub.predict(held.params)
      truths.append(float(held.metrics[self.objective]))
      preds.append(mu)
      spreads.append(sd)
    return self.band.calibrate(truths, preds, spreads)

  def _violates(self, value: float) -> Optional[Criterion]:
    """The first criterion a predicted outcome would definitively miss."""
    for c in self._criteria:
      if c.metric == self.objective and not c.origin.blocking and not c.holds(value):
        return c
    return None

  def propose(self, observations: Sequence[Observation], candidates: int = 800):
    """Propose the next setpoint, or refuse.

    Refuses below MIN_OBSERVATIONS trustworthy runs. A controller that answered anyway
    would be reporting the shape of its kernel rather than the shape of the process.
    """
    trustworthy = [o for o in observations if o.trains and self.objective in o.metrics]
    if len(trustworthy) < self.MIN_OBSERVATIONS:
      return Refusal(
        reason=(
          f"not enough measured observations of '{self.objective}' to propose from. "
          "Modeled and simulated runs are recorded but do not train the surrogate"
        ),
        observations=len(trustworthy),
        needed=self.MIN_OBSERVATIONS,
      )

    self.surrogate.fit(trustworthy, self.objective)
    q = self.calibrate(trustworthy)

    best = None
    best_score = -math.inf
    rejected = 0
    for _ in range(candidates):
      params = {b.name: self._rng.uniform(b.lo, b.hi) for b in self.bounds}
      mu, sd = self.surrogate.predict(params)
      if q is not None:
        lo, hi = self.band.interval(mu, sd)
        half = (hi - lo) / 2.0
      else:
        lo = hi = mu
        half = sd
      # Filter on the confident end: a candidate is rejected only when even its optimistic
      # bound misses the criterion. A candidate whose interval straddles is exactly the
      # one worth running, which is what exploration means here.
      optimistic = hi if self.maximize else lo
      missed = self._violates(optimistic)
      if missed is not None:
        rejected += 1
        continue
      score = (mu + self.kappa * half) if self.maximize else -(mu - self.kappa * half)
      if score > best_score:
        best_score, best = score, (params, mu, sd, (lo, hi) if q is not None else None)

    if best is None:
      return Refusal(
        reason=(
          f"every candidate would confidently miss an acceptance criterion on "
          f"'{self.objective}'. The controller will not propose a run it expects to fail, "
          "and it cannot relax the criterion to make one fit"
        ),
        observations=len(trustworthy),
        needed=self.MIN_OBSERVATIONS,
      )

    params, mu, sd, interval = best
    guarantee = (
      f"conformal interval at alpha={self.band.alpha:g} from "
      f"{self.band.n_calibration} leave-one-out points"
      if interval is not None
      else "uncalibrated spread; no coverage guarantee behind this interval"
    )
    return Proposal(
      params=params,
      predicted=mu,
      spread=sd,
      interval=interval,
      objective=self.objective,
      rationale=(
        f"upper-confidence-bound over {candidates} candidates, {rejected} rejected for "
        f"confidently missing a criterion. {guarantee}"
      ),
      trained_on=len(trustworthy),
    )
