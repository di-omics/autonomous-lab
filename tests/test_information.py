"""Device-free tests for the information layer, written to make it overclaim.

This module is the one in the package with the most authority and the least evidence
behind it, which is exactly the combination that produces a confident wrong number. So the
tests here are adversarial in one direction only: every one of them tries to get a figure
out of the module that a prior would be needed to justify, or tries to get an all-clear out
of a report that was never handed the thing it is clearing.

Four attacks matter.

The first pools cells untagged and then asks for information at a large budget. A layer
that treats the ceiling as a function of spend will return something positive, because the
run still produces reads. It must return zero, at every budget, because the outcome no
longer depends on the per-cell parameter and a mutual information of zero is the one value
that holds for every prior.

The second hands the module a protocol with uncovered destructive failures and checks that
nothing downstream reports an undiscounted yield. The failure mode is subtle: the natural
implementation counts the modes, cannot price them, and quietly drops the term.

The third walks all eight subsets of the three required inputs and demands a refusal from
every one of them, including the full set. Two of three is the dangerous case, because two
of three is what a lab actually has.

The fourth proves the binding constraint is RESOLVED rather than recomputed, by changing a
sibling report and watching the answer move. A layer that recomputed the fact would keep
returning the old answer, and it would be right about the lab and wrong about the report.
"""

from __future__ import annotations

import itertools
import re

import pytest

from autonomous_lab import build_ledger, protocols
from autonomous_lab.information import (
  Cap,
  Layer,
  LayerStanding,
  MissingInput,
  Rework,
  binding_constraint,
  discount,
  information_ceiling,
  information_per_dollar,
  information_report,
  rework_for,
  rework_profile,
)
from autonomous_lab.intelligence import Leg, LegStatus, LoopClosure, untrusted_ops
from autonomous_lab.lineage import Traceability, lineage_report
from autonomous_lab.model import Artifact, Protocol, Step, Transform
from autonomous_lab.qc import (
  SORT_OCCUPANCY_GATE,
  GateReadiness,
  GateReport,
  Readiness,
  gate_report,
)
from autonomous_lab.recovery import Latency, recovery_report
from autonomous_lab.vision import VisionCapability


# -- fixtures ------------------------------------------------------------------


def _genomics():
  return protocols.get("single_cell_genomics")


def _report(**kwargs):
  return information_report(_genomics(), datum="run_outcome", unit="cell", **kwargs)


def _untagged_pool() -> Protocol:
  """Sort 96 cells, pool them with no index. Attribution is destroyed at the pool."""
  return Protocol(
    name="untagged_pool",
    summary="sort, then pool with no index",
    artifacts=(
      Artifact("susp", physical=True),
      Artifact("plate", physical=True),
      Artifact("pool", physical=True),
    ),
    steps=(
      Step(
        instrument="namocell",
        op="manual_load",
        summary="load",
        produces=("susp",),
        manual_reason="bench action",
        transform=Transform.ENTER,
      ),
      Step(
        instrument="namocell",
        op="start_sort",
        summary="sort",
        consumes=("susp",),
        produces=("plate",),
        manual_reason="bench action",
        transform=Transform.SPLIT,
        fanout=96,
      ),
      Step(
        instrument="namocell",
        op="library_pool",
        summary="pool",
        consumes=("plate",),
        produces=("pool",),
        manual_reason="bench action",
        transform=Transform.MERGE,
      ),
    ),
  )


class _FakeCoverage:
  """The narrowest thing that satisfies the coverage contract this module consumes.

  Deliberately not a real CoverageReport. `coverage` is not on this branch, and a test that
  imported it would test the import rather than the composition. What the module is
  entitled to require is one method, so that is what the fake supplies -- and a fake that
  supplies exactly the contract is also the proof that the contract is narrow.
  """

  def __init__(self, protocol: str, modes):
    self.protocol = protocol
    self._modes = list(modes)

  def uncovered_destructive(self):
    return [_FakeRow(name) for name in self._modes]


class _FakeRow:
  def __init__(self, name: str):
    self.failure = _FakeFailure(name)


class _FakeFailure:
  def __init__(self, name: str):
    self.name = name


def _closure(protocol: str, **legs) -> LoopClosure:
  """A loop closure with every leg settable, so a sibling report can be changed at will."""
  return LoopClosure(
    protocol=protocol,
    legs=[
      LegStatus(leg, legs.get(leg.value, True), f"{leg.value} set to {legs.get(leg.value, True)}")
      for leg in (Leg.EXECUTE, Leg.MEASURE, Leg.DECIDE, Leg.RECORD)
    ],
  )


# -- 1. the ceiling ------------------------------------------------------------


def test_lost_attribution_reports_zero_information_at_any_budget():
  """The load-bearing test of the module.

  A pooled-untagged design still produces reads, so a layer that reasons from output
  volume returns something positive. It must return zero, and it must return zero at a
  budget large enough that no plausible implementation reaches it by rounding.
  """
  p = _untagged_pool()
  ledger = build_ledger(p)
  lineage = lineage_report(p, ledger, "pool", unit="cell")
  assert lineage.ceiling is Traceability.LOST

  ceiling = information_ceiling(lineage, gate_report(p.name, ledger))
  assert ceiling.attribution_lost
  assert ceiling.distinguishable_units() == 0
  assert ceiling.cap() is Cap.DESIGN
  assert ceiling.cap().no_purchase_relieves_it

  for budget in (0.0, 1.0, 1e6, 1e12):
    assert ceiling.bits_at_budget(budget) == 0.0, f"budget {budget} moved a design cap"


def test_a_negative_budget_is_refused_rather_than_absorbed():
  """The zero must not be reachable by an incoherent input; it is a claim, not a default."""
  p = _untagged_pool()
  ledger = build_ledger(p)
  ceiling = information_ceiling(
    lineage_report(p, ledger, "pool", unit="cell"), gate_report(p.name, ledger)
  )
  with pytest.raises(ValueError):
    ceiling.bits_at_budget(-1.0)


def test_a_design_that_is_not_foreclosed_gets_no_number_at_all():
  """The asymmetry: the module can prove the zero and must never assert a positive.

  This is the test that stops the layer becoming an estimator. The genomics protocol tags
  before it pools, so attribution survives; the gates are given to it as evaluable, so no
  design fact forecloses the question. A layer that reasoned 'nothing is broken, therefore
  a number' would return one here. There is still no prior, so there is still no number.
  """
  p = _genomics()
  ledger = build_ledger(p)
  lineage = lineage_report(p, ledger, "run_outcome", unit="cell")
  assert lineage.ceiling is not Traceability.LOST

  live = GateReport(
    protocol=p.name,
    rows=[
      GateReadiness(SORT_OCCUPANCY_GATE, Readiness.READY, "hypothetical: the sorter reports"),
    ],
  )
  ceiling = information_ceiling(lineage, live)
  assert ceiling.decisions_per_cycle() == 1
  assert ceiling.distinguishable_units() > 1
  assert ceiling.cap() is Cap.UNDETERMINED
  assert not ceiling.cap().no_purchase_relieves_it
  assert ceiling.bits_at_budget(1e9) is None
  assert "prior" in ceiling.why_not()
  assert "cannot be said" in ceiling.capped_by()


def test_every_gate_unevaluable_caps_the_cycle_by_design_not_by_spend():
  """This lab's actual state: the run yields data and produces no decision.

  Pinned because it is the finding. Both genomics gates are unsatisfiable, so no number of
  additional reads over the same design converts the cycle into a decision.
  """
  p = _genomics()
  ledger = build_ledger(p)
  gates = gate_report(p.name, ledger)
  assert len(gates.unsatisfiable()) == len(gates.rows) > 0

  ceiling = information_ceiling(lineage_report(p, ledger, "run_outcome", unit="cell"), gates)
  assert ceiling.decisions_per_cycle() == 0
  assert ceiling.cap() is Cap.DESIGN
  assert ceiling.bits_at_budget(1e9) == 0.0
  assert "no decision" in ceiling.capped_by()


def test_a_wrong_assay_gate_is_not_counted_as_a_lost_decision():
  """The two failures are opposite and must not be merged.

  An unsatisfiable gate produces nothing. A gate reading the wrong assay produces a number
  that is confidently about something else. Folding the second into the decision count
  would report the lab as producing fewer decisions when the real problem is that it
  produces a wrong one.
  """
  p = _genomics()
  ledger = build_ledger(p)
  ceiling = information_ceiling(
    lineage_report(p, ledger, "run_outcome", unit="cell"), gate_report(p.name, ledger)
  )
  assert ceiling.wrong_assay_gates() >= 1
  assert ceiling.counts()["wrong_assay_gates"] == ceiling.wrong_assay_gates()


def test_a_ceiling_cannot_be_composed_across_two_protocols():
  """A figure averaged over two labs describes neither."""
  genomics = _genomics()
  chem = protocols.get("small_molecule_qc")
  lineage = lineage_report(genomics, build_ledger(genomics), "run_outcome", unit="cell")
  with pytest.raises(ValueError):
    information_ceiling(lineage, gate_report(chem.name, build_ledger(chem)))


# -- 2. the discount -----------------------------------------------------------


def test_uncovered_destructive_modes_never_produce_an_undiscounted_yield():
  """Counting the modes and dropping the term is the failure this test exists for."""
  cov = _FakeCoverage("single_cell_genomics", ["bead_pellet_aspirated", "odtc_callback_theft"])
  disc = discount(cov)

  assert disc.resolved
  assert disc.applies
  assert disc.count == 2
  # The yield is discounted and the discount is not a number. Both halves matter.
  assert not disc.quantified
  assert disc.rate() is None
  assert "UNQUANTIFIED" in disc.why_not()
  assert "bead_pellet_aspirated" in disc.highest_value_measurement()


def test_an_unsupplied_coverage_report_is_unknown_rather_than_clean():
  """Absence of a coverage report is not evidence of coverage."""
  disc = discount(None, protocol="single_cell_genomics")
  assert not disc.resolved
  assert not disc.applies
  assert disc.rate() is None
  assert "unknown rather than zero" in disc.why_not()


def test_the_discount_does_not_fall_back_to_the_recovery_report():
  """The tempting substitution, refused.

  `recovery.destructive_and_silent()` is available on this branch and answers a different
  question. If the module ever silently used it, an unresolved discount would start
  reporting a count -- and the count would be wrong in both directions.
  """
  p = _genomics()
  ledger = build_ledger(p)
  gates = gate_report(p.name, ledger)
  recovery = recovery_report(p, gates, VisionCapability.none())
  assert recovery.destructive_and_silent(), "the substitution would have had material to use"

  report = _report()
  assert not report.discount.resolved
  assert report.discount.count == 0
  assert report.discount.source.startswith("nothing")


def test_a_coverage_like_object_without_the_method_is_refused():
  """Duck-typed into a zero is how a report starts claiming coverage it never checked."""
  with pytest.raises(TypeError):
    discount(object())


# -- 3. the rework -------------------------------------------------------------


def test_every_latency_has_a_rework_cost():
  """A new latency must not fall through to the cheapest bucket."""
  for latency in Latency:
    assert rework_for(latency) in tuple(Rework)


def test_later_detection_never_costs_fewer_cycles():
  """The ordering that makes the whole layer worth computing."""
  order = [
    Latency.IMMEDIATE,
    Latency.AT_NEXT_STEP,
    Latency.AT_NEXT_GATE,
    Latency.AFTER_SEQUENCING,
    Latency.NEVER,
  ]
  seen = -1.0
  for latency in order:
    cost = rework_for(latency)
    cycles = cost.cycles
    if cycles is None:
      assert cost is Rework.UNBOUNDED
      assert latency is Latency.NEVER
      continue
    assert cycles >= seen
    seen = cycles


def test_an_unbounded_rework_refuses_a_total_rather_than_dropping_the_term():
  """A sum containing an unbounded term is not a sum, and must not silently become one."""
  p = _genomics()
  ledger = build_ledger(p)
  recovery = recovery_report(p, gate_report(p.name, ledger), VisionCapability.none())
  profile = rework_profile(recovery)

  assert profile.unbounded(), "this lab has failures nothing would ever surface"
  assert profile.worst() is Rework.UNBOUNDED
  assert profile.cycles_if_each_occurred_once() is None
  assert "not bounded in cycles" in profile.why_not()


def test_a_cycle_plus_decision_reports_a_floor_and_says_so():
  """1.0 cycles is what can be counted, not what it costs."""
  cost = rework_for(Latency.AFTER_SEQUENCING)
  assert cost is Rework.CYCLE_PLUS_DECISION
  assert cost.cycles == 1.0
  assert not cost.whole_cost
  assert rework_for(Latency.AT_NEXT_GATE).whole_cost
  assert rework_for(Latency.IMMEDIATE).cycles == 0.0


# -- 4. the binding constraint -------------------------------------------------


def test_the_binding_constraint_is_resolved_from_the_loop_closure():
  """Changing the sibling report must change the answer.

  The whole point of resolving rather than recomputing: nothing here re-derives whether a
  gate can fire, so a loop closure that says MEASURE is fine produces a report that says
  MEASUREMENT is clear, whatever the real lab looks like.
  """
  clear = _closure("p", execute=True, measure=True, decide=True, record=True)
  bound = binding_constraint(clear, coverage=_FakeCoverage("p", []), durability=[], expertise=[])
  assert bound.binding() is None
  assert bound.certain()

  broken = _closure("p", execute=True, measure=False, decide=True, record=True)
  moved = binding_constraint(broken, coverage=_FakeCoverage("p", []), durability=[], expertise=[])
  assert moved.binding() is not None
  assert moved.binding().layer is Layer.MEASUREMENT
  assert moved.binding().reason == "measure set to False"


def test_the_binding_constraint_moves_when_the_coverage_report_changes():
  """Same lab, same legs, different coverage report -- and the answer must move."""
  legs = _closure("p")
  clean = binding_constraint(
    legs, coverage=_FakeCoverage("p", []), durability=[], expertise=[]
  )
  assert clean.binding() is None

  dirty = binding_constraint(
    legs,
    coverage=_FakeCoverage("p", ["bead_pellet_aspirated"]),
    durability=[],
    expertise=[],
  )
  assert dirty.binding() is not None
  assert dirty.binding().layer is Layer.COVERAGE
  assert "bead_pellet_aspirated" in dirty.binding().reason
  assert dirty.binding().relief
  assert dirty.certain()


def test_the_first_binding_layer_wins_and_the_order_is_the_declared_one():
  """Everything binds at once. The answer must be EXECUTION, not the worst-sounding one."""
  legs = _closure("p", execute=False, measure=False, decide=False, record=False)
  bound = binding_constraint(
    legs,
    coverage=_FakeCoverage("p", ["a", "b"]),
    durability=[object()],
    expertise=[("op", "why")],
  )
  assert bound.binding().layer is Layer.EXECUTION
  assert [r.layer for r in bound.rows] == list(Layer)
  assert Layer.EXECUTION.blocks_the_rest
  assert not Layer.COVERAGE.blocks_the_rest


def test_an_unresolved_layer_in_front_of_the_answer_makes_it_provisional():
  """UNRESOLVED is not a pass, and it must not be skipped over silently.

  Coverage is unresolved and durability binds. Reporting durability as the finding would
  send a service budget at a lab whose real hole might be an uncovered failure mode.
  """
  legs = _closure("p")
  bound = binding_constraint(legs, coverage=None, durability=[object()], expertise=[])
  assert bound.binding().layer is Layer.DURABILITY
  assert not bound.certain()
  assert [r.layer for r in bound.masked()] == [Layer.COVERAGE]
  assert "provisional" in bound.why()


def test_an_all_clear_needs_every_layer_resolved():
  """The vacuous pass: nothing binds because nothing was ever looked at."""
  legs = _closure("p")
  bound = binding_constraint(legs, coverage=None, durability=None, expertise=None)
  assert bound.binding() is None
  assert not bound.certain()
  assert len(bound.unresolved()) == 3


def test_every_layer_names_the_module_that_owns_its_fact():
  """The module's own rule, made checkable rather than merely asserted."""
  for layer in Layer:
    assert layer.owned_by, f"{layer.value} does not say where its fact comes from"
  assert "coverage" in Layer.COVERAGE.owned_by
  assert "durability" in Layer.DURABILITY.owned_by
  assert "intelligence" in Layer.EXPERT_TRANSFER.owned_by


def test_a_clear_layer_offers_no_advice():
  """Advice about a layer that is fine is how a lab buys what it already has."""
  legs = _closure("p")
  bound = binding_constraint(
    legs, coverage=_FakeCoverage("p", []), durability=[], expertise=[]
  )
  for row in bound.rows:
    assert row.standing is not LayerStanding.BINDING
    assert row.relief == ""


def test_execution_relief_names_the_instrument_the_queue_puts_first():
  """Generic advice is correct and unschedulable; the named decode is actionable."""
  p = _genomics()
  ledger = build_ledger(p)
  legs = _closure(p.name, execute=False)
  bound = binding_constraint(
    legs, ledger=ledger, coverage=_FakeCoverage(p.name, []), durability=[], expertise=[]
  )
  top = ledger.unlocks()[0]
  found = bound.binding()
  assert found.layer is Layer.EXECUTION
  assert top.instrument in found.relief
  assert str(top.steps_unblocked) in found.relief
  # The named step goes in the relief, never inside the owning layer's own words.
  assert top.instrument not in found.reason
  assert found.reason == "execute set to False"


# -- the refusal ---------------------------------------------------------------


def test_information_per_dollar_refuses_every_combination_of_inputs():
  """All eight subsets, including the full one. Two of three is the dangerous case."""
  values = {
    "question": "does compound X change the per-cell mutation rate",
    "prior": {"rate": "beta(2, 8)"},
    "cycle_costs": {"usd_per_cycle": 1234.0},
  }
  names = list(values)
  for size in range(len(names) + 1):
    for present in itertools.combinations(names, size):
      kwargs = {k: values[k] for k in present}
      refusal = information_per_dollar(**kwargs)
      assert refusal.refused, f"accepted with {present}"
      assert refusal.value() is None
      assert len(refusal.supplied) == size
      assert len(refusal.missing) == 3 - size


def test_two_of_three_is_still_a_refusal_and_names_the_third():
  refusal = information_per_dollar(question="does X change the rate", prior={"rate": "beta"})
  assert refusal.refused
  assert refusal.missing == (MissingInput.CYCLE_COSTS,)
  assert "measured_per_cycle_costs" in refusal.why_not()


def test_a_falsy_input_does_not_count_as_a_stated_one():
  """An empty question is not a question, and an empty prior is an implicit one."""
  refusal = information_per_dollar(question="", prior={}, cycle_costs=0)
  assert len(refusal.missing) == 3


def test_the_refusal_names_what_the_lab_could_get_this_week():
  refusal = information_per_dollar()
  cheap = refusal.obtainable_this_week()
  assert cheap == (MissingInput.QUESTION,)
  assert MissingInput.QUESTION.obtainable_this_week
  assert not MissingInput.PRIOR.obtainable_this_week
  assert not MissingInput.CYCLE_COSTS.obtainable_this_week
  assert "stated_question" in refusal.why_not()


def test_supplying_all_three_still_names_what_is_missing_beyond_them():
  """The honest end of the argument: the three inputs are the lab's, not the whole set."""
  refusal = information_per_dollar(question="q", prior="p", cycle_costs="c")
  assert refusal.refused
  assert refusal.missing == ()
  why = refusal.why_not()
  assert "likelihood" in why
  assert "log base" in why


def test_the_refusal_names_the_next_measurement_from_the_discount():
  """A refusal that names the cheapest next measurement beats an estimate."""
  refusal = information_per_dollar()
  assert "state the question" in refusal.cheapest_next_measurement()

  disc = discount(_FakeCoverage("p", ["bead_pellet_aspirated"]))
  named = refusal.cheapest_next_measurement(disc)
  assert "bead_pellet_aspirated" in named
  assert "time-to-detection" in named


# -- the whole report ----------------------------------------------------------


def test_the_report_requires_a_stated_datum_and_unit():
  """The module practises what it argues: it will not guess the question's subject."""
  with pytest.raises(TypeError):
    information_report(_genomics())  # type: ignore[call-arg]


def test_the_genomics_report_is_capped_by_design_and_binds_at_execution():
  """The finding, pinned. If this ever flips, either the lab improved or a report started
  flattering it, and both are worth a failed test until someone looks."""
  report = _report(expertise=untrusted_ops(_genomics()))

  assert report.ceiling.cap() is Cap.DESIGN
  assert report.ceiling.bits_at_budget(1e9) == 0.0
  assert report.constraint.binding().layer is Layer.EXECUTION
  # Coverage and durability were not supplied, so the answer is provisional -- but they sit
  # AFTER execution, so nothing masks it.
  assert report.constraint.certain()
  assert report.rework.cycles_if_each_occurred_once() is None
  assert report.per_dollar().refused


def test_the_headline_names_the_cap_and_the_constraint_and_quotes_no_information_unit():
  """The headline is the sentence that gets pasted into a slide, so it is the one most
  likely to acquire a number. It may name the cap and the binding layer; it may not carry
  an information quantity, because there is none to carry."""
  report = _report(coverage=_FakeCoverage("single_cell_genomics", ["bead_pellet_aspirated"]))
  headline = report.headline()
  assert report.ceiling.cap().value in headline
  assert report.constraint.binding().layer.value in headline
  # The refusal leads, so a reader cannot take silence about the yield for a good yield.
  assert headline.index("UNQUANTIFIED") < headline.index("capped by")
  # And the discount is carried as a word plus a named mode, never as a factor.
  assert "Discount:" in headline
  assert "bead_pellet_aspirated" in headline
  for token in (r"\bbits?\b", r"\bnats?\b", r"\bpercent\b", "%", r"\$"):
    assert re.search(token, headline, re.IGNORECASE) is None, (
      f"the headline quoted an information or money unit matching {token}"
    )


def test_counts_expose_every_layer_without_summing_across_them():
  report = _report()
  counts = report.counts()
  assert counts["decisions_per_cycle"] == 0
  assert counts["resolved"] == 0
  assert counts["rework_unbounded"] >= 1
  assert counts["layers_unresolved"] == 3
