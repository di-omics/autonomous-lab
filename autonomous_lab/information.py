"""How much this lab learns per dollar per cycle -- and why the number is not the answer.

Every other layer in this package answers a piece of one question, and nobody in it states
the question. The ledger asks whether a step runs. `qc` asks whether a gate can fire.
`recovery` asks whether a failure would be noticed. `lineage` asks whether a read can be
tied to a cell. `throughput` asks how many plates a day. Each is a real question and none of
them is the one a lab is actually being funded to answer, which is:

    HOW MUCH DOES THIS LAB LEARN, PER DOLLAR, PER EXPERIMENTAL CYCLE?

Everything else here is instrumental to that. Saying so plainly reframes the package: the
autonomy percentage is not the product, it is one term in a denominator nobody wrote down.

THE TEMPTATION IS TO RETURN A NUMBER. This module refuses, and the reason is specific
rather than modest. Expected information gain is defined as the mutual information between
the parameters and the outcome of a design, and every equivalent form of it contains the
prior explicitly: EIG(xi) = E_{Y|xi}[D_KL(p(theta|y,xi) || p(theta))] = H(Theta) -
H(Theta|Y,xi) = I(Y;Theta|xi) (Lindley, Ann. Math. Statist. 27:986-1005, 1956; Huan,
Jagalur and Marzouk, Acta Numerica 33, 2024). EIG is a functional OF the prior. Absent
p(theta) you cannot form the joint, the prior-predictive, the posterior, or any KL, so
there is no ceiling and no "is this worth running" in information units. The objects do not
exist. A module that emitted a number over an unstated prior would be doing exactly what
`throughput` refuses to do with unmeasured durations -- one level of abstraction up, and
with far more authority, because a figure in bits reads as a measurement.

The question is a second, separate requirement. Bernardo's inequality (Ann. Statist.
7:686-690, 1979) gives U_Z(xi) <= U_Theta(xi) with equality only when the map from Theta to
the quantity of interest Z is bijective, so reporting parameter-EIG when the real question
is a prediction biases the figure upward. The size of the effect is not hypothetical: in a
stochastic SIR model with one observation time on [0,3], the optimal design is xi* = 0.4
for the parameters and xi* = 0.2 for a cumulative-recovered prediction -- same model, same
prior, same likelihood, and the optimum moves by a factor of two purely because the
question changed (arXiv:2408.09582).

So this module computes the STRUCTURE, which is real without a prior, in four parts.

1. THE CEILING. What can this design distinguish at all? Resolved from `lineage` and `qc`.
   If attribution to the unit of interest is LOST, the per-unit outcome is independent of
   the per-unit parameter, so I(Y;Theta) = 0 for EVERY prior and EVERY budget. Zero is the
   one value in this module's subject matter that does not need a prior to state, and it is
   the only one emitted. Note that zero nats is zero bits, so it is also the one figure
   whose log base need not be disclosed. If instead every gate that would produce a
   decision is unevaluable, the cycle produces data and no decision. Both are caps set by
   DESIGN rather than by spend, and separating those is the single most useful thing here:
   it tells a lab whether it is short of money or short of an experiment that can work.

   The asymmetry is deliberate and is not an implementation limit. This module can prove
   the zero and cannot prove any positive value, because a positive mutual information is a
   functional of a prior it does not have. For discrete Theta a stated prior would cap EIG
   at H(Theta) -- a uniform prior over 8 hypotheses caps it at log2(8) = 3.000 bits = 2.079
   nats -- and for continuous Theta mutual information is unbounded above, so even a stated
   prior gives no finite ceiling without a stated noise model (McAllester and Stratos,
   AISTATS 2020). Hence `Cap` has two values and neither of them is "spend more".

2. THE DISCOUNT. What fraction of runs produce data that looks fine and is not? Resolved
   from `coverage.uncovered_destructive`. This is the term nobody applies. A campaign
   carrying destructive failures that nothing would catch does not yield its nominal
   information: some fraction of its output is confidently wrong, and confidently wrong
   output is worse than missing output, because it is acted upon. Howard's value-of-
   information theory (IEEE Trans. SSC 2:22-26, 1966) licenses the direction -- imperfect
   information is worth strictly less than perfect -- and supplies no silent-failure
   discount function.

   This module therefore counts the uncovered destructive modes and states that the
   discount is UNQUANTIFIED until each has a measured rate. It does not invent one, and the
   reason is that no such rate exists to borrow: there is no published measured rate of
   undetected failure in wet-lab execution itself. The nearest published items each cover
   part of it and none is the derivation -- Ioannidis's bias term u (PLoS Med 2:e124,
   2005), Gordon et al.'s exchange rate of 2-8 percent more subjects per 1 percent
   genotyping error (Hum Hered 54:22-33, 2002), Parvin's E(Nuf) (Clin Chem 54:2049-2054,
   2008), and Bross-style misclassification attenuation (Biometrics 10:478-486, 1954).
   Naming the measurement is the deliverable. See `Discount.highest_value_measurement`.

3. THE REWORK. What does a failure cost when caught late? Resolved from `recovery`'s
   effective Latency. A failure caught at the step costs one step. Caught at the end of the
   cycle it costs the cycle. Caught in the data it costs the cycle plus the decision made
   on it. Never caught, it is not bounded in cycles at all, because nothing triggers the
   rerun. This is computable in CYCLES with no dollar figure anywhere, which is the honest
   currency: the published cost anchors are a point estimate inside a five-fold bound
   (Freedman, Cockburn and Simcoe, PLOS Biology 13:e1002165, 2015 -- US$28B/yr from a 50
   percent rate whose own probability bounds run 18 to 88.5 percent) and a per-replication
   figure that prices confirming somebody else's result rather than one's own bad run
   (US$500K to US$2M, 3 to 24 months, same paper).

4. THE BINDING CONSTRAINT. The procurement question, and the one worth computing precisely.
   Across execution, measurement, decision, record, coverage, durability and expert
   transfer, WHICH LAYER CAPS INFORMATION PER DOLLAR RIGHT NOW? `binding_constraint` is an
   ordered evaluation returning the FIRST binding layer and what would relieve it.

   The order is argued, not stylistic. The first four are the loop legs `intelligence`
   already computes, and each masks the ones after it: a gate cannot be evaluated on a step
   that never ran, a decision cannot be made on a measurement that never arrived, and a
   decision that was never made cannot be recorded. If the loop does not close, coverage
   and durability and expertise are questions about a lab that is not producing cycles at
   all. Among the last three, COVERAGE precedes DURABILITY because an uncovered destructive
   mode discounts every cycle the lab will ever run while a lapsed calibration discounts
   the cycles run since the lapse; and DURABILITY precedes EXPERT_TRANSFER because a
   benchmark measured on an unentitled instrument is a number about the wrong machine.
   EXPERT_TRANSFER is last because it is the constraint that only surfaces once everything
   purchasable has been bought, which is exactly when labs are most surprised by it.

   An UNRESOLVED layer is not a pass. If a layer before the binding one was never resolved,
   the answer is reported with `certain()` False rather than presented as the finding,
   because the unresolved layer may bind harder and a confident wrong recommendation here
   costs an instrument.

Finally `information_per_dollar` REFUSES, always, and `PerDollarRefusal.why_not` names the
three missing inputs: a stated question, a stated prior, and measured per-cycle costs. It
also states which the lab could obtain this week, and the answer is the question -- it
costs a sentence. Writing down a prior also costs an afternoon and does not make it right:
in an item-response-theory study over 1,000 simulated experiments per condition, a
misinformative prior led inference to favour the wrong model and adaptive design made that
worse rather than mitigating it (Sloman, Cavagnaro and Broomell, Behavior Research Methods,
2024). And the costs cannot be obtained this week at all, because `throughput` refuses over
18 untimed steps and the micro-costing literature has no stable split to borrow: across six
cancer-genomics projects in one country in one era, consumables ran 1.7 to 74.5 percent of
per-person cost and labour 2.7 to 26.9 percent (Gordon et al., BMC Health Serv Res, 2020).

A refusal that names the cheapest next measurement is more useful than an estimate.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

from .intelligence import Leg, LoopClosure, loop_closure
from .ledger import build_ledger
from .lineage import LineageReport, Traceability, lineage_report
from .provenance import provenance_report
from .qc import MEASUREMENTS, GateReport, Measurement, gate_report
from .recovery import EffectiveDetection, Latency, RecoveryReport, recovery_report
from .vision import VisionCapability

# -- 1. the ceiling: what the design can distinguish at all ---------------------


class Cap(str, Enum):
  """What limits the information this design can yield, once the design is fixed.

  There is no SPEND member, and its absence is the module's central claim rather than an
  omission. A cap set by DESIGN is provable without a prior: if the outcome carries no
  dependence on the parameter, the mutual information is zero for every prior and every
  budget. A cap set by spend is not provable without one, because any positive information
  quantity is a functional of the prior nobody wrote down. So this enum can say "no
  purchase order relieves this" and can never say "buy more", and reporting the second
  would be the fabrication the module exists to refuse.
  """

  DESIGN = "design"  # the design itself forecloses the question; no budget reaches it
  UNDETERMINED = "undetermined"  # the design does not foreclose it; nothing more can be said

  @property
  def no_purchase_relieves_it(self) -> bool:
    """The line between 'this cannot work' and 'not established either way'.

    True only for DESIGN. UNDETERMINED deliberately does not mean 'spending helps'; it
    means the question of whether spending helps needs a prior this module does not have.
    """
    return self is Cap.DESIGN


@dataclass(frozen=True)
class InformationCeiling:
  """What this design can distinguish, resolved from `lineage` and `qc`.

  Both sibling reports are carried whole rather than summarised into fields, so nothing
  here can drift from the layer that owns it. Every quantity below is a method over them.
  """

  lineage: LineageReport
  gates: GateReport
  measurements: Dict[str, Measurement]

  @property
  def protocol(self) -> str:
    return self.lineage.protocol

  @property
  def unit(self) -> str:
    return self.lineage.unit

  @property
  def attribution(self) -> Traceability:
    """Lineage's own best case, not its state today.

    `LineageReport.ceiling` already assumes the entire reverse-engineering queue is
    finished, which is precisely the "at any budget" reading this module needs. Taking
    `verdict` instead would report a design as foreclosed when it is merely blocked, and
    those have opposite next actions.
    """
    return self.lineage.ceiling

  @property
  def attribution_lost(self) -> bool:
    return self.attribution is Traceability.LOST

  def distinguishable_units(self) -> int:
    """How many units of interest this design can tell apart, at best.

    Zero when attribution is LOST, and that zero is the load-bearing value: it is the
    cardinality of the partition the design induces on the material, so a per-unit question
    asked of it has no observable to condition on.
    """
    if self.attribution_lost:
      return 0
    cohort = self.lineage.graph.cohorts.get(self.lineage.datum)
    return cohort.members if cohort is not None else 0

  def decisions_per_cycle(self) -> int:
    """How many gates could actually return a decision in this workcell.

    Resolved from `qc`'s readiness, never recomputed. Zero means the cycle produces data
    and no decision, which is a design cap in exactly the same sense as lost attribution:
    more reads produce more data and still no decision.
    """
    return sum(1 for row in self.gates.rows if row.evaluable)

  def wrong_assay_gates(self) -> int:
    """Gates that will return a number about something other than the sample.

    Counted but not subtracted from `decisions_per_cycle`, because these are the opposite
    failure: the decision IS produced, and it is confidently wrong. That belongs to the
    discount, not to the ceiling, and double-counting it here would flatter neither.
    """
    return len(self.gates.inappropriate(self.measurements))

  def cap(self) -> Cap:
    if self.attribution_lost:
      return Cap.DESIGN
    if not self.decisions_per_cycle():
      return Cap.DESIGN
    return Cap.UNDETERMINED

  def capped_by(self) -> str:
    """Which design fact forecloses the question, in the words of the layer that owns it."""
    if self.attribution_lost:
      return (
        f"attribution to the {self.unit} is LOST at best, not merely unproven today: "
        f"{self.lineage.ceiling_reason}. A per-{self.unit} question has no observable to "
        "condition on, so its answer does not depend on how much is spent"
      )
    if not self.decisions_per_cycle():
      total = len(self.gates.rows)
      if not total:
        return (
          "this protocol declares no QC gates at all, so the cycle emits data and returns "
          "no decision. Nothing in the run distinguishes a result worth acting on from one "
          "that is not"
        )
      return (
        f"all {total} declared gate(s) are unevaluable, so the cycle emits data and returns "
        "no decision. More reads over the same design produce more data and still no "
        "decision"
      )
    return (
      f"the design does not foreclose a per-{self.unit} question: "
      f"{self.distinguishable_units()} {self.unit}(s) stay distinguishable and "
      f"{self.decisions_per_cycle()} of {len(self.gates.rows)} gate(s) can return a "
      "decision. Whether more spend buys more information cannot be said from here"
    )

  def bits_at_budget(self, dollars: float) -> Optional[float]:
    """Expected information gain in bits at a stated budget, where that is statable.

    Returns 0.0 exactly when the design forecloses the question, and None otherwise. The
    zero is not a floor or a placeholder: an outcome independent of the parameter has
    I(Y;Theta) = 0 under every prior, so it is the one figure in this subject that is
    reportable without disclosing a prior, a likelihood, a target, an estimator or a log
    base. Zero nats and zero bits are the same number, which is why the base is omitted.

    `dollars` is accepted and deliberately unused in the DESIGN case, because the whole
    claim is that the value does not move with it. It is still validated, because a
    negative budget is an incoherent input and silently accepting one would let a caller
    believe this function ranges over budgets in some other case.
    """
    if dollars < 0:
      raise ValueError(f"a budget of {dollars} is not a budget; expected zero or more")
    if self.cap().no_purchase_relieves_it:
      return 0.0
    return None

  def why_not(self) -> str:
    """Why no positive figure is returned, for the case where the design allows one."""
    if self.cap().no_purchase_relieves_it:
      return "the ceiling is zero and is stated; nothing is being withheld"
    return (
      "a positive expected information gain is a functional of a prior, a likelihood and a "
      "stated target quantity, none of which this lab has written down. See "
      "information_per_dollar().why_not() for what is missing and which of it is cheap"
    )

  def counts(self) -> Dict[str, int]:
    return {
      "distinguishable_units": self.distinguishable_units(),
      "gates": len(self.gates.rows),
      "decisions_per_cycle": self.decisions_per_cycle(),
      "wrong_assay_gates": self.wrong_assay_gates(),
    }


def information_ceiling(
  lineage: LineageReport,
  gates: GateReport,
  measurements: Optional[Dict[str, Measurement]] = None,
) -> InformationCeiling:
  """What this design can distinguish, composed from the two layers that know."""
  if lineage.protocol != gates.protocol:
    raise ValueError(
      f"the lineage report is about '{lineage.protocol}' and the gate report about "
      f"'{gates.protocol}'. A ceiling composed across protocols describes no lab."
    )
  return InformationCeiling(
    lineage=lineage,
    gates=gates,
    measurements=measurements if measurements is not None else MEASUREMENTS,
  )


# -- 2. the discount: output that looks fine and is not -------------------------


@dataclass(frozen=True)
class Discount:
  """The fraction of a campaign's output that is confidently wrong -- as a count, not a rate.

  `resolved` is the field to read first and it is not the same as `applies`. Unresolved
  means nobody handed this module a coverage report, so the discount is unknown rather than
  absent, and treating the two alike is how a lab concludes it has no silent failures by
  never having looked. UNRESOLVED is not a pass, the same convention `intelligence`
  applies to an unbenchmarked operation and `qc` applies to an absent measurement.

  Deliberately NOT resolved from `recovery.destructive_and_silent()` when coverage is
  missing. Those two lists differ in both directions -- `recovery` resolves only a
  failure's DECLARED path, so it misses a failure a camera would hold and counts one an
  operator's eye would catch -- and substituting the available answer for the correct one
  is the flattering shortcut this package exists to refuse.
  """

  protocol: str
  resolved: bool
  modes: Tuple[str, ...]
  source: str

  @property
  def count(self) -> int:
    return len(self.modes)

  @property
  def applies(self) -> bool:
    """Whether a discount is owed at all. False is meaningful only when `resolved`."""
    return bool(self.modes)

  @property
  def quantified(self) -> bool:
    """Always False, and structurally so.

    A quantified discount needs a measured per-occurrence rate for each mode, on this
    bench, with this material. No such rate exists anywhere to borrow: there is no
    published measured rate of undetected failure in wet-lab execution. This property is a
    constant because the alternative is a field somebody could set.
    """
    return False

  def rate(self) -> None:
    """The fraction of runs silently invalidated. Always None, on purpose.

    Returned as a function rather than omitted so a caller that wants the number gets an
    explicit None and a reason, instead of an AttributeError they route around.
    """
    return None

  def why_not(self) -> str:
    if not self.resolved:
      return (
        "no coverage report was supplied, so the count of uncovered destructive modes is "
        "unknown rather than zero. Resolve it from coverage.uncovered_destructive(); this "
        "module will not substitute recovery.destructive_and_silent(), which answers a "
        "different question and would quietly disagree"
      )
    if not self.applies:
      return (
        "every failure that destroys material has a machine check standing on it, so no "
        "silent-invalidation discount is owed by this protocol. That is a statement about "
        "coverage, not about execution error rates, which remain unmeasured"
      )
    return (
      f"{self.count} failure mode(s) destroy material with no camera and no gate on them. "
      "The discount they impose on this campaign's information yield is UNQUANTIFIED and "
      "stays unquantified until each has a measured per-occurrence rate on this bench. No "
      "published rate exists to borrow, and inventing one would put a fabricated "
      "denominator under every result the campaign produces"
    )

  def highest_value_measurement(self) -> str:
    """The single measurement that would do most to make the discount computable."""
    if not self.resolved:
      return (
        "compute the coverage report first; until then the discount has no subject and "
        "the measurement to run cannot be chosen"
      )
    if not self.applies:
      return (
        "no uncovered destructive mode remains, so the next measurement is not about "
        "coverage. Time the steps `throughput` names, which is what the per-cycle "
        "denominator is waiting on"
      )
    return (
      f"the per-occurrence rate of '{self.modes[0]}', measured on this bench with a "
      "deliberate positive control, is worth more than any further coverage analysis. It "
      "converts the count below from a hazard into a discount, and note that the cost of "
      "an undetected failure scales with magnitude x time-to-detection x throughput "
      "(Parvin, Clin Chem 54:2049-2054, 2008), so the rate must be paired with how often "
      "the check runs rather than quoted alone"
    )

  def counts(self) -> Dict[str, int]:
    return {"uncovered_destructive": self.count, "resolved": int(self.resolved)}


def _mode_name(row: object) -> str:
  """The failure name on a coverage row, without importing a module that may not be here."""
  failure = getattr(row, "failure", None)
  name = getattr(failure, "name", None)
  if isinstance(name, str):
    return name
  own = getattr(row, "name", None)
  return own if isinstance(own, str) else str(row)


def discount(coverage: Optional[object] = None, protocol: str = "") -> Discount:
  """Count the modes that silently invalidate output, from the layer that composes them.

  `coverage` is a `coverage.CoverageReport`, taken structurally rather than by import so
  this module composes with it wherever it lives. It must expose `uncovered_destructive()`;
  anything else is refused rather than duck-typed into a zero, because a silent zero here
  is exactly the confidently-clean report the module is about.
  """
  if coverage is None:
    return Discount(
      protocol=protocol,
      resolved=False,
      modes=(),
      source="nothing; no coverage report was supplied",
    )
  fn = getattr(coverage, "uncovered_destructive", None)
  if not callable(fn):
    raise TypeError(
      "the discount is resolved from coverage.uncovered_destructive(); the object supplied "
      f"({type(coverage).__name__}) does not expose it. Refused rather than defaulted: a "
      "zero here would read as 'nothing is uncovered'"
    )
  rows = list(fn())
  return Discount(
    protocol=str(getattr(coverage, "protocol", protocol) or protocol),
    resolved=True,
    modes=tuple(_mode_name(r) for r in rows),
    source="coverage.uncovered_destructive()",
  )


# -- 3. the rework: what a failure costs when it is caught late -----------------


class Rework(str, Enum):
  """What a failure costs to undo, in cycles, as a function of when it surfaces.

  Cycles rather than dollars because cycles are what this repo can actually resolve. The
  published dollar anchors price something else -- replicating another lab's result, at
  US$500K to US$2M over 3 to 24 months -- and no published figure prices one's own silently
  bad run, in dollars or in days.
  """

  ONE_STEP = "one_step"  # the material is still in hand; the step repeats inside the cycle
  ONE_CYCLE = "one_cycle"  # the cycle's committed work is spent and must be run again
  CYCLE_PLUS_DECISION = "cycle_plus_decision"  # the cycle, plus a decision taken on bad data
  UNBOUNDED = "unbounded"  # never surfaced, so nothing ever triggers the rerun

  @property
  def whole_cost(self) -> bool:
    """Whether `cycles` is the entire cost or only the part that can be counted.

    The load-bearing line in this enum. ONE_STEP and ONE_CYCLE are fully priced in cycles.
    CYCLE_PLUS_DECISION reports 1.0 and that 1.0 is a floor: the decision made on the bad
    data has its own downstream cost, and the only measured conversion rate from undetected
    error to a downstream wrong action comes from clinical chemistry, where roughly 1 in 4
    errors triggered further investigation and about 1 in 16 changed care (Plebani and
    Carraro, Clin Chem 43:1348-51, 1997). UNBOUNDED reports None because a failure nothing
    surfaces is acted upon indefinitely.
    """
    return self in (Rework.ONE_STEP, Rework.ONE_CYCLE)

  @property
  def cycles(self) -> Optional[float]:
    """Cycles charged per occurrence, or None where the cost is not bounded in cycles."""
    if self is Rework.ONE_STEP:
      return 0.0
    if self in (Rework.ONE_CYCLE, Rework.CYCLE_PLUS_DECISION):
      return 1.0
    return None


_REWORK_FOR_LATENCY: Dict[Latency, Rework] = {
  Latency.IMMEDIATE: Rework.ONE_STEP,
  Latency.AT_NEXT_STEP: Rework.ONE_STEP,
  Latency.AT_NEXT_GATE: Rework.ONE_CYCLE,
  Latency.AFTER_SEQUENCING: Rework.CYCLE_PLUS_DECISION,
  Latency.NEVER: Rework.UNBOUNDED,
}


def rework_for(latency: Latency) -> Rework:
  """Map `recovery`'s effective latency onto a rework cost.

  A total mapping over `Latency`, checked at import by `_REWORK_FOR_LATENCY`'s coverage
  test, so a new latency cannot silently fall through to the cheapest bucket.
  """
  try:
    return _REWORK_FOR_LATENCY[latency]
  except KeyError:  # pragma: no cover - guarded by test_every_latency_has_a_rework_cost
    raise ValueError(
      f"latency '{latency}' has no rework cost; add one rather than defaulting, because "
      "the default that feels safe is the cheapest bucket and it is the wrong one"
    ) from None


@dataclass(frozen=True)
class ReworkRow:
  """One failure, priced in cycles by when this lab would actually find it."""

  effective: EffectiveDetection

  @property
  def failure(self) -> str:
    return self.effective.failure.name

  @property
  def latency(self) -> Latency:
    """Effective, not declared. The plan's latency is what the plan hoped for."""
    return self.effective.latency

  @property
  def cost(self) -> Rework:
    return rework_for(self.latency)


@dataclass
class ReworkProfile:
  """Every failure on a protocol, priced in cycles rather than dollars."""

  protocol: str
  rows: List[ReworkRow]

  def unbounded(self) -> List[ReworkRow]:
    """Failures whose rework cost is not bounded in cycles, because nothing surfaces them."""
    return [r for r in self.rows if r.cost is Rework.UNBOUNDED]

  def underpriced(self) -> List[ReworkRow]:
    """Failures whose reported cycle figure is a floor rather than the cost."""
    return [r for r in self.rows if not r.cost.whole_cost]

  def worst(self) -> Optional[Rework]:
    for cost in (
      Rework.UNBOUNDED,
      Rework.CYCLE_PLUS_DECISION,
      Rework.ONE_CYCLE,
      Rework.ONE_STEP,
    ):
      if any(r.cost is cost for r in self.rows):
        return cost
    return None

  def cycles_if_each_occurred_once(self) -> Optional[float]:
    """Cycles lost if every listed failure happened exactly once. NOT an expected cost.

    Named for what it is, at length, because the short name for this quantity is "cost per
    cycle" and that name is a lie: turning this into an expectation needs a per-mode rate,
    which is the same missing measurement the discount is waiting on. Returns None as soon
    as any failure is UNBOUNDED, because a sum containing an unbounded term is not a sum.
    """
    if self.unbounded():
      return None
    total = 0.0
    for row in self.rows:
      cycles = row.cost.cycles
      if cycles is None:  # pragma: no cover - unbounded already returned above
        return None
      total += cycles
    return total

  def why_not(self) -> str:
    unbounded = self.unbounded()
    if not unbounded:
      return (
        "every failure here surfaces somewhere, so the per-occurrence rework is bounded in "
        "cycles. Converting it to a cost per cycle still needs per-mode rates"
      )
    return (
      f"{len(unbounded)} failure mode(s) are never surfaced by anything in this lab, so "
      "their rework cost is not bounded in cycles: nothing triggers the rerun, and the "
      "wrong result is carried into whatever is decided next. Named: "
      + ", ".join(r.failure for r in unbounded)
    )

  def counts(self) -> Dict[str, int]:
    return {
      "total": len(self.rows),
      "one_step": sum(1 for r in self.rows if r.cost is Rework.ONE_STEP),
      "one_cycle": sum(1 for r in self.rows if r.cost is Rework.ONE_CYCLE),
      "cycle_plus_decision": sum(
        1 for r in self.rows if r.cost is Rework.CYCLE_PLUS_DECISION
      ),
      "unbounded": len(self.unbounded()),
      "underpriced": len(self.underpriced()),
    }


def rework_profile(recovery: RecoveryReport) -> ReworkProfile:
  """Price every failure `recovery` resolved, in cycles, by when this lab would find it."""
  return ReworkProfile(
    protocol=recovery.protocol,
    rows=[ReworkRow(effective=eff) for eff in recovery.rows],
  )


# -- 4. the binding constraint --------------------------------------------------


class Layer(str, Enum):
  """The seven layers any one of which can cap information per dollar.

  Declaration order IS the evaluation order, and the ordering is argued in the module
  docstring rather than chosen for presentation. `blocks_the_rest` records why an earlier
  binding layer ends the search instead of merely ranking above a later one.
  """

  EXECUTION = "execution"
  MEASUREMENT = "measurement"
  DECISION = "decision"
  RECORD = "record"
  COVERAGE = "coverage"
  DURABILITY = "durability"
  EXPERT_TRANSFER = "expert_transfer"

  @property
  def blocks_the_rest(self) -> bool:
    """Whether a break here makes the later layers unaskable rather than merely worse.

    True for the four loop legs. A lab that cannot execute, measure, decide or record is
    not producing cycles, so coverage, durability and expertise are questions about a lab
    that does not exist yet -- and money spent on them buys nothing until the leg is fixed.
    False for the last three, which degrade the information a running lab yields without
    stopping it from yielding any.
    """
    return self in (
      Layer.EXECUTION,
      Layer.MEASUREMENT,
      Layer.DECISION,
      Layer.RECORD,
    )

  @property
  def owned_by(self) -> str:
    """The sibling module that owns this layer's fact.

    Present so the module's own rule is checkable rather than merely stated: nothing here
    is computed, everything is resolved, and this property names where from.
    """
    return _OWNER[self]


_OWNER: Dict[Layer, str] = {
  Layer.EXECUTION: "intelligence.loop_closure (Leg.EXECUTE, over ledger)",
  Layer.MEASUREMENT: "intelligence.loop_closure (Leg.MEASURE, over qc)",
  Layer.DECISION: "intelligence.loop_closure (Leg.DECIDE, over recovery)",
  Layer.RECORD: "intelligence.loop_closure (Leg.RECORD, over provenance)",
  Layer.COVERAGE: "coverage.uncovered_destructive",
  Layer.DURABILITY: "durability.untrusted_instruments",
  Layer.EXPERT_TRANSFER: "intelligence.untrusted_ops",
}


_LEG_LAYER: Dict[Leg, Layer] = {
  Leg.EXECUTE: Layer.EXECUTION,
  Leg.MEASURE: Layer.MEASUREMENT,
  Leg.DECIDE: Layer.DECISION,
  Leg.RECORD: Layer.RECORD,
}


_RELIEF: Dict[Layer, str] = {
  Layer.EXECUTION: (
    "finish the command set that unblocks the most steps, or federate the leg to a "
    "workcell that already drives it. No camera and no assay moves this one"
  ),
  Layer.MEASUREMENT: (
    "an instrument that returns the quantity the gate reads, on the input the sample "
    "actually is. For a picogram library that is fluorometric or qPCR quantification, and "
    "repairing the plate reader does not supply it"
  ),
  Layer.DECISION: (
    "a detection path in front of the failures a decision must react to. A decision that "
    "cannot see the failure it is deciding about is a coin flip with a rationale"
  ),
  Layer.RECORD: (
    "a machine-readable label read at both ends of every physical hop, or an arm that "
    "reports the move. Nothing in software closes a hop a human carries"
  ),
  Layer.COVERAGE: (
    "one machine check per uncovered destructive mode, chosen per mode rather than in "
    "bulk: a camera where the condition is imageable, a different sensor where it is not. "
    "A CV budget spent on an invisible condition buys nothing at any model quality"
  ),
  Layer.DURABILITY: (
    "discharge the lapsed obligation and start counting the charge it is measured in. An "
    "instrument whose service history nobody kept is unmeasured, not healthy"
  ),
  Layer.EXPERT_TRANSFER: (
    "run the calibration experiment that retires the unmet benchmark. This is the one "
    "layer no purchase order reaches: it is a scientist's time and a measurement, not a box"
  ),
}


class LayerStanding(str, Enum):
  """Where one layer stands. UNRESOLVED is not a pass and is not a failure.

  The three-way split is the point. A boolean would force an unresolved layer into one of
  the other two, and either choice is wrong in a way that survives review: called clear, it
  disappears from the report and a harder constraint downstream gets recommended; called
  binding, it displaces a constraint that was actually computed.
  """

  CLEAR = "clear"  # resolved, and this layer is not what caps information today
  BINDING = "binding"  # resolved, and this layer caps information today
  UNRESOLVED = "unresolved"  # nobody supplied the report that owns this fact

  @property
  def caps_information(self) -> bool:
    return self is LayerStanding.BINDING


@dataclass(frozen=True)
class Constraint:
  """One layer, its standing, and what would relieve it if it binds.

  `named_next` is the resolved half of the relief: `_RELIEF` describes the SHAPE of the
  work, which is correct and unschedulable, and this carries the specific instrument or
  step some sibling report already ranked first. Kept separate from `reason`, because the
  reason is the owning layer's own words and appending advice to it would put this module's
  opinion inside a quotation.
  """

  layer: Layer
  standing: LayerStanding
  reason: str
  named_next: str = ""

  @property
  def relief(self) -> str:
    """What would move this layer. Empty unless it binds -- advice about a clear layer is
    how a lab ends up buying the thing it already has."""
    if not self.standing.caps_information:
      return ""
    return _RELIEF[self.layer] + self.named_next

  @property
  def resolved_from(self) -> str:
    return self.layer.owned_by


@dataclass
class BindingConstraint:
  """The ordered evaluation: which layer caps information per dollar right now."""

  protocol: str
  rows: List[Constraint]

  def binding(self) -> Optional[Constraint]:
    """The first layer that binds, in declaration order. None when every layer is clear."""
    return next((r for r in self.rows if r.standing.caps_information), None)

  def unresolved(self) -> List[Constraint]:
    return [r for r in self.rows if r.standing is LayerStanding.UNRESOLVED]

  def _stop(self) -> int:
    """The index the search ended at. Positional rather than by value, because two rows
    can compare equal and `list.index` would silently return the earlier one."""
    for i, row in enumerate(self.rows):
      if row.standing.caps_information:
        return i
    return len(self.rows)

  def masked(self) -> List[Constraint]:
    """Unresolved layers sitting in front of the binding one, which may bind harder."""
    return [
      r for r in self.rows[: self._stop()] if r.standing is LayerStanding.UNRESOLVED
    ]

  def certain(self) -> bool:
    """Whether the answer can be acted on, or whether an earlier layer was never resolved.

    False when any layer strictly before the binding one is unresolved, because that layer
    may bind harder and the recommendation would send a budget to the wrong place. With
    nothing binding, every layer must be resolved for the all-clear to be an all-clear.
    """
    return not self.masked()

  def relief(self) -> str:
    found = self.binding()
    if found is None:
      return (
        "no layer in this evaluation binds. That is a statement about the seven layers "
        "resolved here and not a claim that information per dollar is unconstrained"
      )
    return found.relief

  def why(self) -> str:
    found = self.binding()
    if found is None:
      return "every resolved layer is clear"
    lead = f"{found.layer.value} binds first: {found.reason}"
    masked = self.masked()
    if masked:
      names = ", ".join(r.layer.value for r in masked)
      return (
        f"{lead}. Read this as provisional: {names} sit(s) earlier in the order and was "
        "never resolved, so a harder constraint may be hiding in front of this one"
      )
    return lead


def _leg_rows(closure: LoopClosure) -> List[Constraint]:
  """The four loop legs, taken verbatim from `intelligence` rather than re-derived."""
  by_leg = {status.leg: status for status in closure.legs}
  rows: List[Constraint] = []
  for leg, layer in _LEG_LAYER.items():
    status = by_leg.get(leg)
    if status is None:
      rows.append(
        Constraint(
          layer=layer,
          standing=LayerStanding.UNRESOLVED,
          reason=f"the loop closure supplied carries no {leg.value} leg",
        )
      )
      continue
    rows.append(
      Constraint(
        layer=layer,
        standing=LayerStanding.CLEAR if status.ok else LayerStanding.BINDING,
        reason=status.reason,
      )
    )
  return rows


def _execution_relief(ledger) -> str:
  """Name the specific decode that frees the most steps, when a ledger is to hand.

  Resolved from `ledger.unlocks()`, which already ranks the queue by finished map rather
  than by command. The generic advice is fine; the named instrument is what gets scheduled.
  """
  if ledger is None:
    return ""
  unlocks = ledger.unlocks()
  if not unlocks:
    return ""
  top = unlocks[0]
  return (
    f". The ranked queue puts '{top.instrument}' first: {top.cost} command(s) still to "
    f"decode, {top.steps_unblocked} step(s) freed"
  )


def _coverage_row(disc: Discount) -> Constraint:
  if not disc.resolved:
    return Constraint(Layer.COVERAGE, LayerStanding.UNRESOLVED, disc.why_not())
  if disc.applies:
    return Constraint(
      Layer.COVERAGE,
      LayerStanding.BINDING,
      f"{disc.count} failure mode(s) destroy material with no machine check on them: "
      + ", ".join(disc.modes),
    )
  return Constraint(
    Layer.COVERAGE,
    LayerStanding.CLEAR,
    "every material-destroying failure has a camera or a gate standing on it",
  )


def _durability_row(durability: Optional[Sequence[object]]) -> Constraint:
  if durability is None:
    return Constraint(
      Layer.DURABILITY,
      LayerStanding.UNRESOLVED,
      "no instrument-health report was supplied; an instrument whose obligations nobody "
      "recorded is unmeasured rather than entitled, so this cannot default to clear",
    )
  rows = list(durability)
  if rows:
    names = ", ".join(str(getattr(r, "instrument", r)) for r in rows)
    return Constraint(
      Layer.DURABILITY,
      LayerStanding.BINDING,
      f"{len(rows)} instrument(s) are not entitled to be trusted with this work: {names}",
    )
  return Constraint(
    Layer.DURABILITY,
    LayerStanding.CLEAR,
    "every instrument in this workcell is entitled to the work being asked of it",
  )


def _expertise_row(expertise: Optional[Sequence[Tuple[str, str]]]) -> Constraint:
  if expertise is None:
    return Constraint(
      Layer.EXPERT_TRANSFER,
      LayerStanding.UNRESOLVED,
      "no benchmark report was supplied; an unbenchmarked operation is untrusted by "
      "default, so this cannot default to clear either",
    )
  rows = list(expertise)
  if rows:
    ops = ", ".join(op for op, _why in rows[:4]) + (" ..." if len(rows) > 4 else "")
    return Constraint(
      Layer.EXPERT_TRANSFER,
      LayerStanding.BINDING,
      f"{len(rows)} operation(s) have not earned unattended execution: {ops}",
    )
  return Constraint(
    Layer.EXPERT_TRANSFER,
    LayerStanding.CLEAR,
    "every operation in this protocol has a met benchmark",
  )


def binding_constraint(
  closure: LoopClosure,
  ledger=None,
  coverage: Optional[object] = None,
  durability: Optional[Sequence[object]] = None,
  expertise: Optional[Sequence[Tuple[str, str]]] = None,
) -> BindingConstraint:
  """Which of the seven layers caps information per dollar, and what would relieve it.

  Every standing is RESOLVED from the report that owns the fact and none is recomputed
  here. The four loop legs come verbatim from `intelligence.loop_closure`, which itself
  composes the ledger, the gate readiness, the failure model and the custody chain -- so a
  second opinion about whether a gate can fire is not possible from this module, by
  construction. Coverage comes from `coverage.uncovered_destructive`, durability from a
  health report, expert transfer from `intelligence.untrusted_ops`.

  `ledger` is optional and buys only one thing: when EXECUTION binds, the relief names the
  instrument the ranked decode queue puts first, instead of describing the shape of the
  work in the abstract.
  """
  rows = _leg_rows(closure)
  rows.append(_coverage_row(discount(coverage, protocol=closure.protocol)))
  rows.append(_durability_row(durability))
  rows.append(_expertise_row(expertise))

  named = _execution_relief(ledger)
  if named:
    rows = [
      Constraint(r.layer, r.standing, r.reason, named)
      if r.layer is Layer.EXECUTION and r.standing.caps_information
      else r
      for r in rows
    ]
  return BindingConstraint(protocol=closure.protocol, rows=rows)


# -- the refusal ----------------------------------------------------------------


class MissingInput(str, Enum):
  """The three things a lab must supply before information per dollar exists at all.

  Two of the three are inputs to the numerator and one to the denominator, and they fail
  differently. The question and the prior are missing DEFINITIONS -- without them there is
  no functional to evaluate, not merely an uncertain value. The costs are a missing
  MEASUREMENT, which is a smaller and more tractable kind of absent.
  """

  QUESTION = "stated_question"
  PRIOR = "stated_prior"
  CYCLE_COSTS = "measured_per_cycle_costs"

  @property
  def obtainable_this_week(self) -> bool:
    """Which of the three costs a sentence rather than an experiment.

    True only for QUESTION. Naming the target quantity Z is writing one sentence, and it
    is not cosmetic: Bernardo's inequality makes parameter-EIG an upper bound on the EIG
    about any derived quantity, and in a stochastic SIR model the optimal observation time
    moved from xi* = 0.4 to xi* = 0.2 on the same model and prior purely because the target
    changed.

    False for PRIOR, and the reason is the interesting one. Writing a prior down also takes
    an afternoon; what takes longer is earning one, and a prior written to unblock a
    calculation is worse than no calculation. In an item-response-theory study of 1,000
    simulated experiments per condition, a misinformative prior led inference to favour the
    wrong model and adaptive design amplified the error rather than mitigating it. Note the
    asymmetry in that same study: for parameter ESTIMATION adaptive design still beat fixed
    designs under a misinformative prior. So the harm is specific to model selection, which
    is what a screening campaign mostly does.

    False for CYCLE_COSTS because it is a measurement this lab has not made: `throughput`
    refuses a plates-per-day figure over 18 untimed steps, and there is no published split
    to borrow -- consumables ran 1.7 to 74.5 percent of per-person cost across six cancer
    genomics projects in one country (Gordon et al., 2020), and 16 to 33 percent with
    maintenance at up to 59 percent in three public-health labs (Marklewitz et al., 2025).
    """
    return self is MissingInput.QUESTION


@dataclass(frozen=True)
class PerDollarRefusal:
  """The return of `information_per_dollar`. There is no variant of it that carries a number.

  `refused` is a property rather than a field so no caller and no future edit can construct
  an accepted one. The dataclass exists to make the refusal inspectable -- what was
  supplied, what is missing, which piece is cheap -- because a bare exception would be
  routed around and a bare None would be filled in with a guess.
  """

  supplied: Tuple[MissingInput, ...]
  missing: Tuple[MissingInput, ...]

  @property
  def refused(self) -> bool:
    """Always True, including when all three inputs are supplied.

    Supplying all three makes the question well posed; it does not make this module the
    thing that answers it. EIG is a map from (prior, likelihood, target) to a real number,
    and the likelihood is not among the three -- nor is the estimator, its bound direction,
    or the log base, and a figure missing any of those is unauditable. See `why_not`.
    """
    return True

  def value(self) -> None:
    """The number. None, always, and returned rather than raised so it can be logged."""
    return None

  def obtainable_this_week(self) -> Tuple[MissingInput, ...]:
    return tuple(m for m in self.missing if m.obtainable_this_week)

  def why_not(self) -> str:
    if not self.missing:
      return (
        "all three inputs are supplied, and this module still does not compute the figure. "
        "Expected information gain is a map from (prior, likelihood, target) to a real "
        "number, and the likelihood is not one of the three inputs above -- nor is the "
        "estimator, its bound direction, or the log base. Minimum disclosure for any "
        "reported EIG: prior, likelihood, target quantity, estimator, log base, sample "
        "counts, and whether the estimate is an upper or a lower bound. Nested Monte Carlo "
        "is an upper bound and overestimates; contrastive estimators are lower bounds and "
        "saturate at log(L+1) nats, which is 4.615 nats at L = 100. Take the well-posed "
        "question to a Bayesian design tool, not to this module"
      )
    names = ", ".join(m.value for m in self.missing)
    cheap = self.obtainable_this_week()
    lead = (
      f"information per dollar per cycle is not computable here: {len(self.missing)} of 3 "
      f"inputs are missing ({names}). Without a prior there is no joint, no prior-"
      "predictive, no posterior and therefore no KL -- the objects do not exist, so this "
      "is not an uncertain number, it is the absence of a functional to evaluate"
    )
    if not cheap:
      return (
        lead
        + ". None of the missing inputs is obtainable this week; the costs need the steps "
        "`throughput` names to be timed first"
      )
    return (
      lead
      + ". Obtainable this week: "
      + ", ".join(m.value for m in cheap)
      + ". Naming the target quantity costs one sentence and changes the answer -- "
      "parameter-EIG is an upper bound on the gain about any derived quantity, so an "
      "unstated target makes any figure reported here an overestimate of what is learned"
    )

  def cheapest_next_measurement(self, disc: Optional[Discount] = None) -> str:
    """The measurement worth running first, resolved from the discount where one exists.

    A refusal that names the next measurement is more useful than an estimate, and the
    named measurement is not the one a lab expects: it is a rate on a failure mode, not a
    cost per plate. Note that a rate quoted without the check cadence is not enough --
    undetected-failure cost scales with time-to-detection and throughput, so doubling
    throughput without changing check frequency doubles the damage from the same rate.
    """
    if disc is None:
      return (
        "state the question. It is the only missing input that costs a sentence rather "
        "than an experiment, and no measurement makes the figure computable without it"
      )
    return disc.highest_value_measurement()

  def counts(self) -> Dict[str, int]:
    return {
      "supplied": len(self.supplied),
      "missing": len(self.missing),
      "obtainable_this_week": len(self.obtainable_this_week()),
    }


def information_per_dollar(
  question: Optional[str] = None,
  prior: Optional[object] = None,
  cycle_costs: Optional[object] = None,
) -> PerDollarRefusal:
  """Refuse to return information per dollar, and say precisely what is missing.

  Takes the three inputs so that the refusal can be specific about which are present,
  rather than a flat "not implemented" that reads as an oversight. An empty string, an
  empty mapping and zero all count as NOT supplied: an empty question is not a question,
  and treating a falsy placeholder as a stated input is how an unstated prior becomes an
  implicit one. There is no argument combination that yields a number -- see
  `PerDollarRefusal.refused` for why supplying all three is still not enough.
  """
  given = {
    MissingInput.QUESTION: bool(question),
    MissingInput.PRIOR: bool(prior),
    MissingInput.CYCLE_COSTS: bool(cycle_costs),
  }
  return PerDollarRefusal(
    supplied=tuple(k for k, v in given.items() if v),
    missing=tuple(k for k, v in given.items() if not v),
  )


# -- the whole report -----------------------------------------------------------


@dataclass
class InformationReport:
  """The four structural answers, for one protocol, over one workcell."""

  protocol: str
  ceiling: InformationCeiling
  discount: Discount
  rework: ReworkProfile
  constraint: BindingConstraint

  def per_dollar(self) -> PerDollarRefusal:
    """The refusal, always. Carried on the report so it cannot be reached around."""
    return information_per_dollar()

  def headline(self) -> str:
    """One paragraph a lab can act on, with no number in it that was not resolved.

    It leads with the refusal rather than closing on it. This is the sentence that gets
    pasted into a slide, and a headline naming a cap, a constraint and two caveats while
    saying nothing about the yield itself reads as though the yield were fine and merely
    omitted for brevity. An unstated refusal is filled in by the reader, optimistically.
    """
    found = self.constraint.binding()
    where = found.layer.value if found is not None else "nothing in the seven layers"
    return (
      f"{self.protocol}: information per dollar per cycle is UNQUANTIFIED here and this "
      "module will not put a figure on it. What is resolved instead: information is capped "
      f"by {self.ceiling.cap().value} -- {self.ceiling.capped_by()}. The binding constraint "
      f"is {where}. Discount: {self.discount.why_not()}. Rework: {self.rework.why_not()}."
    )

  def counts(self) -> Dict[str, int]:
    out: Dict[str, int] = {}
    out.update(self.ceiling.counts())
    out.update(self.discount.counts())
    out.update({f"rework_{k}": v for k, v in self.rework.counts().items()})
    out["layers_unresolved"] = len(self.constraint.unresolved())
    return out


def information_report(
  protocol,
  datum: str,
  unit: str,
  workcell=None,
  coverage: Optional[object] = None,
  durability: Optional[Sequence[object]] = None,
  expertise: Optional[Sequence[Tuple[str, str]]] = None,
  capability: Optional[VisionCapability] = None,
) -> InformationReport:
  """Wire every layer that owns a fact, in the only order that is correct.

  `datum` and `unit` are required rather than defaulted, and that is the module practising
  what it argues: it refuses a figure over an unstated question, so it also refuses to
  guess which datum the question is about or what a unit of interest is. Defaulting them
  would reintroduce the unstated target Bernardo's inequality warns about, in the one place
  it would be invisible.

  Nothing is computed here. The ledger is built first because every other layer costs
  against its verdicts, then `qc`, `recovery`, `provenance` and `lineage` in turn, and
  `intelligence.loop_closure` composes the four legs. This function only hands each report
  to the layer that consumes it.
  """
  ledger = build_ledger(protocol, workcell)
  gates = gate_report(protocol.name, ledger)
  cap = capability or VisionCapability.none()
  recovery = recovery_report(protocol, gates, cap)
  provenance = provenance_report(ledger)
  closure = loop_closure(ledger, gates, recovery, provenance)
  lineage = lineage_report(protocol, ledger, datum, unit=unit)

  return InformationReport(
    protocol=protocol.name,
    ceiling=information_ceiling(lineage, gates),
    discount=discount(coverage, protocol=protocol.name),
    rework=rework_profile(recovery),
    constraint=binding_constraint(
      closure,
      ledger=ledger,
      coverage=coverage,
      durability=durability,
      expertise=expertise,
    ),
  )


__all__ = [
  "BindingConstraint",
  "Cap",
  "Constraint",
  "Discount",
  "InformationCeiling",
  "InformationReport",
  "Layer",
  "LayerStanding",
  "MissingInput",
  "PerDollarRefusal",
  "Rework",
  "ReworkProfile",
  "ReworkRow",
  "binding_constraint",
  "discount",
  "information_ceiling",
  "information_per_dollar",
  "information_report",
  "rework_for",
  "rework_profile",
]
