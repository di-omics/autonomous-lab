"""Device-free tests for the teaching layer: expert demonstrations and machine parity.

Four failures are being hunted here, and they are the four ways a transfer report starts
flattering the lab it describes.

A tolerance appearing out of one demonstration. One run establishes a value and no spread,
and every convention that would widen it -- a percentage, a sigma, a rule of thumb -- puts a
number in the report that no measurement supports. The refusal has to survive n=1 and n=2,
and it has to be reported rather than swallowed.

A single good machine run reading as parity. This is the demo-to-assay failure in its purest
form: the number lands inside the expert's range, the report says MEETS, and nothing
anywhere records that the evidence could not distinguish that run from a lucky one.

A vacuous pass. A transfer report handed no operations satisfies every `all()` in it, and an
empty demonstration queue over no protocols looks exactly like a lab that has finished
teaching its machines. Both must read as nothing-was-checked.

And a ranking that is really a list. The queue of what an SME should demonstrate next has to
fall out of the protocols it is given, so that handing it different protocols changes the
order. A hardcoded order is advice about somebody else's lab.
"""

from __future__ import annotations

import dataclasses

import pytest

from autonomous_lab import protocols
from autonomous_lab.intelligence import BENCHMARKS_BY_OP
from autonomous_lab.model import Protocol, Step
from autonomous_lab.teaching import (
  DEMONSTRATIONS,
  MACHINE_OBSERVATIONS,
  MIN_DEMONSTRATIONS,
  TRANSFERABLE,
  TRANSFERABLE_BY_OP,
  Attainment,
  Demonstration,
  Envelope,
  Goal,
  MachineObservation,
  attainment,
  demonstration_queue,
  demonstrations_still_needed,
  taught,
  teaching_summary,
  transfer_report,
  untaught_operations,
)

CLEANUP = "pcr_enrichment_round1_cleanup"  # HIGHER: recovered fraction
POOLING = "library_pool"  # LOWER: representation CV
LYSIS = "wgs_prep_lysis"  # WINDOW: delivered volume


def _demo(value: float, op: str = CLEANUP, by: str = "scientist_a", conditions=None) -> Demonstration:
  spec = TRANSFERABLE_BY_OP[op]
  return Demonstration(
    operation=op,
    metric=spec.metric,
    units=spec.units,
    value=value,
    by=by,
    conditions=conditions if conditions is not None else spec.conditions,
  )


def _obs(value: float, op: str = CLEANUP, conditions=None) -> MachineObservation:
  spec = TRANSFERABLE_BY_OP[op]
  return MachineObservation(
    operation=op,
    metric=spec.metric,
    units=spec.units,
    value=value,
    by="a run card",
    conditions=conditions if conditions is not None else spec.conditions,
  )


def _envelope(values, op: str = CLEANUP, by="scientist_a") -> Envelope:
  spec = TRANSFERABLE_BY_OP[op]
  handles = [by] * len(values) if isinstance(by, str) else list(by)
  return Envelope(
    operation=op,
    metric=spec.metric,
    units=spec.units,
    goal=spec.goal,
    demonstrations=tuple(_demo(v, op=op, by=h) for v, h in zip(values, handles)),
  )


# -- one demonstration is a value, not a tolerance -----------------------------


def test_one_demonstration_gives_a_value_and_no_tolerance():
  """The whole discipline of the module in one assertion."""
  env = _envelope([0.82])
  assert env.center() == 0.82
  assert env.tolerance() is None
  assert env.spread() is None


def test_two_demonstrations_still_give_no_tolerance():
  """Two points have one degree of freedom; the interval they imply IS the two points."""
  env = _envelope([0.82, 0.88])
  assert env.center() == pytest.approx(0.85)
  assert env.tolerance() is None


def test_the_refusal_is_reported_and_says_how_many_more_are_needed():
  """A refusal nobody can read is indistinguishable from an answer nobody checked."""
  env = _envelope([0.82])
  refusal = env.refusal()
  assert refusal is not None
  assert str(MIN_DEMONSTRATIONS) in refusal
  assert str(MIN_DEMONSTRATIONS - 1) in refusal


def test_an_envelope_over_no_demonstrations_states_nothing_at_all():
  """Handed nothing, it must not compute anything -- the vacuous-pass failure at the source."""
  env = _envelope([])
  assert env.n() == 0
  assert env.center() is None
  assert env.tolerance() is None
  assert env.caveat() is None
  assert "no recorded demonstration" in (env.refusal() or "")


def test_the_tolerance_is_the_observed_range_and_nothing_wider():
  """min and max of what happened. A multiplier here would be a number with no author."""
  env = _envelope([0.80, 0.90, 0.85])
  assert env.tolerance() == (0.80, 0.90)
  assert env.spread() == pytest.approx(0.10)


def test_an_envelope_from_one_demonstrator_carries_that_caveat():
  """Three runs by one person describe the person, and the claim has to travel with it."""
  env = _envelope([0.80, 0.85, 0.90], by="scientist_a")
  assert env.tolerance() is not None
  assert "one" in (env.caveat() or "")
  wide = _envelope([0.80, 0.85, 0.90], by=("scientist_a", "scientist_b", "scientist_c"))
  assert wide.caveat() is None


# -- one good machine run is not parity ----------------------------------------


def test_one_good_machine_run_does_not_report_meets():
  """The demo-to-assay failure. The value lands inside the range and proves nothing."""
  env = _envelope([0.80, 0.85, 0.90])
  parity = attainment(env, [_obs(0.88)])
  assert parity.attainment is Attainment.INDISTINGUISHABLE_FROM_UNMEASURED
  assert not parity.demonstrated
  assert "lucky" in parity.reason


def test_two_good_machine_runs_are_still_not_meets():
  env = _envelope([0.80, 0.85, 0.90])
  parity = attainment(env, [_obs(0.88), _obs(0.87)])
  assert parity.attainment is Attainment.INDISTINGUISHABLE_FROM_UNMEASURED
  assert parity.machine_n == 2


def test_enough_machine_runs_inside_the_range_do_report_meets():
  """The module has to be able to say yes, or its refusals mean nothing."""
  env = _envelope([0.80, 0.85, 0.90])
  parity = attainment(env, [_obs(0.88), _obs(0.87), _obs(0.91)])
  assert parity.attainment is Attainment.MEETS
  assert parity.demonstrated
  assert parity.expert_n == 3 and parity.machine_n == 3


def test_a_machine_nobody_measured_is_unmeasured_rather_than_below():
  """A skip must not read as a result in either direction."""
  env = _envelope([0.80, 0.85, 0.90])
  parity = attainment(env, [])
  assert parity.attainment is Attainment.UNMEASURED
  assert not parity.demonstrated
  assert parity.machine_n == 0


def test_parity_is_judged_on_the_worst_run_not_the_mean():
  """A mean lets one excellent run pay for a bad one; the bad plate is the one that costs."""
  env = _envelope([0.80, 0.85, 0.90])
  runs = [_obs(0.98), _obs(0.98), _obs(0.55)]
  assert sum(o.value for o in runs) / 3 >= 0.80  # the mean would have passed
  assert attainment(env, runs).attainment is Attainment.BELOW


def test_a_machine_measured_under_other_conditions_is_unmeasured():
  """A picogram run against a nanogram demonstration is not a comparison."""
  env = _envelope([0.80, 0.85, 0.90])
  elsewhere = [_obs(0.99, conditions="ten times the input amount") for _ in range(5)]
  parity = attainment(env, elsewhere)
  assert parity.attainment is Attainment.UNMEASURED
  assert "conditions" in parity.reason


def test_a_thin_envelope_cannot_be_attained_by_any_number_of_machine_runs():
  """The mirror case: the machine side is fine and there is nothing to place it against."""
  env = _envelope([0.85])
  parity = attainment(env, [_obs(0.88) for _ in range(20)])
  assert parity.attainment is Attainment.INDISTINGUISHABLE_FROM_UNMEASURED
  assert parity.expert_n == 1 and parity.machine_n == 20


def test_no_envelope_at_all_is_unmeasured_not_meets():
  parity = attainment(None, [_obs(0.99) for _ in range(10)])
  assert parity.attainment is Attainment.UNMEASURED
  assert parity.expert_n == 0


def test_only_meets_reads_as_parity():
  """Three ways of not knowing are not degrees of knowing."""
  assert Attainment.MEETS.demonstrated_parity
  for other in (
    Attainment.BELOW,
    Attainment.UNMEASURED,
    Attainment.INDISTINGUISHABLE_FROM_UNMEASURED,
  ):
    assert not other.demonstrated_parity


# -- direction: better is not always bigger ------------------------------------


def test_a_machine_beating_the_expert_on_a_lower_is_better_metric_meets():
  env = _envelope([10.0, 12.0, 14.0], op=POOLING)
  assert TRANSFERABLE_BY_OP[POOLING].goal is Goal.LOWER
  parity = attainment(env, [_obs(v, op=POOLING) for v in (5.0, 6.0, 7.0)])
  assert parity.attainment is Attainment.MEETS


def test_overshooting_a_two_sided_metric_is_not_better_performance():
  """Delivering 11 uL where 10 was demonstrated is a different failure, not an improvement."""
  env = _envelope([9.8, 10.0, 10.2], op=LYSIS)
  assert TRANSFERABLE_BY_OP[LYSIS].goal.outside_is_always_worse
  parity = attainment(env, [_obs(v, op=LYSIS) for v in (11.0, 11.1, 11.2)])
  assert parity.attainment is Attainment.BELOW
  # And the same numbers would have passed a one-sided comparison, which is the bug.
  assert min(11.0, 11.1, 11.2) >= env.tolerance()[0]


# -- taught, and the backlog ---------------------------------------------------


def test_an_operation_nobody_demonstrated_is_untaught_rather_than_passing():
  ok, why = taught(CLEANUP)
  assert not ok
  assert "zero recorded" in why


def test_an_operation_with_no_specification_at_all_is_untaught_and_says_so():
  ok, why = taught("an_operation_nobody_ever_wrote_down")
  assert not ok
  assert "as good as the expert" in why


def test_every_operation_in_this_repo_is_untaught():
  """A coverage claim the module's own data would contradict. There are no demonstrations."""
  assert DEMONSTRATIONS == ()
  assert MACHINE_OBSERVATIONS == ()
  for op in TRANSFERABLE_BY_OP:
    ok, _why = taught(op)
    assert not ok, f"'{op}' reports taught with no demonstration recorded"
  assert teaching_summary()["operations_with_envelope"] == 0


def test_untaught_operations_covers_every_distinct_step_of_the_genomics_protocol():
  protocol = protocols.get("single_cell_genomics")
  untaught = untaught_operations(protocol)
  assert len(untaught) == len({s.op for s in protocol.steps})


def test_every_specified_operation_is_one_a_reference_protocol_actually_runs():
  """A backlog naming work no flow needs is a list somebody will do and nobody will use."""
  ops = set()
  for name in ("single_cell_genomics", "small_molecule_qc"):
    ops.update(s.op for s in protocols.get(name).steps)
  for t in TRANSFERABLE:
    assert t.op in ops, f"'{t.op}' is specified for demonstration and no protocol runs it"


def test_demonstrations_still_needed_is_the_full_minimum_when_there_are_none():
  assert demonstrations_still_needed(CLEANUP) == MIN_DEMONSTRATIONS
  assert demonstrations_still_needed("an_operation_nobody_ever_wrote_down") == MIN_DEMONSTRATIONS


# -- the queue is computed, not listed -----------------------------------------


def test_the_queue_ranks_the_station_whose_sitting_settles_the_most():
  queue = demonstration_queue([protocols.get("single_cell_genomics")])
  by_instrument = {q.instrument: len(q.operations) for q in queue}
  assert by_instrument["star"] == max(by_instrument.values())
  assert queue[0].instrument == "star"
  assert queue[0].cost == sum(demonstrations_still_needed(op) for op in queue[0].operations)


def test_the_ranking_follows_the_protocols_it_is_given():
  """Move the same operations to another station and the queue reorders.

  This is what separates a computed ranking from a table someone wrote in a plausible order.
  """
  synthetic = Protocol(
    name="synthetic",
    summary="the same operations at a different station",
    steps=(
      Step(instrument="namocell", op="start_sort", summary=""),
      Step(instrument="namocell", op=POOLING, summary=""),
      Step(instrument="star", op=LYSIS, summary=""),
    ),
  )
  queue = demonstration_queue([synthetic])
  assert queue[0].instrument == "namocell"
  assert set(queue[0].operations) == {"start_sort", POOLING}


def test_a_different_protocol_set_gives_a_different_queue():
  chemistry = demonstration_queue([protocols.get("small_molecule_qc")])
  assert [q.instrument for q in chemistry] == ["viaflo96"]
  both = demonstration_queue(
    [protocols.get("single_cell_genomics"), protocols.get("small_molecule_qc")]
  )
  assert "viaflo96" in {q.instrument for q in both}
  assert both[0].instrument == "star"


def test_the_top_of_the_queue_is_not_the_first_thing_declared():
  """A ranking that agreed with declaration order would be untestable as a ranking."""
  first_declared = TRANSFERABLE[0].op
  queue = demonstration_queue([protocols.get("single_cell_genomics")])
  assert first_declared not in queue[0].operations


def test_an_empty_queue_over_no_protocols_is_not_a_finished_programme():
  """Nothing to rank must not read as nothing left to do."""
  assert demonstration_queue([]) == []
  assert not transfer_report([]).transfers()
  assert demonstration_queue([protocols.get("single_cell_genomics")])


# -- the transfer report -------------------------------------------------------


def test_a_report_over_no_operations_does_not_report_a_transfer():
  """`all()` over an empty list is True, which is how a report certifies a lab it never read."""
  report = transfer_report([])
  assert report.rows == []
  assert not report.transfers()
  assert report.counts()["operations"] == 0


def test_the_genomics_report_attains_nothing_and_names_every_operation():
  protocol = protocols.get("single_cell_genomics")
  report = transfer_report([s.op for s in protocol.steps])
  assert report.counts()["operations"] == len({s.op for s in protocol.steps})
  assert report.attained() == []
  assert not report.transfers()
  assert len(report.untaught()) == len(report.rows)


def test_benchmarks_are_resolved_from_intelligence_rather_than_restated():
  """Two statements of one target eventually disagree, and nothing reveals which is wrong."""
  report = transfer_report([CLEANUP])
  row = report.rows[0]
  assert row.benchmarks
  assert list(row.benchmarks) == list(BENCHMARKS_BY_OP[CLEANUP])
  assert row.benchmarks[0] is BENCHMARKS_BY_OP[CLEANUP][0]


def test_asserted_only_names_targets_nobody_has_shown_are_reachable():
  """A benchmark with no envelope: a number with a unit that no person has hit here."""
  protocol = protocols.get("single_cell_genomics")
  report = transfer_report([s.op for s in protocol.steps])
  asserted = {r.operation for r in report.asserted_only()}
  assert CLEANUP in asserted
  assert "start_sort" in asserted
  for row in report.asserted_only():
    assert not row.has_expert_envelope


def test_the_counts_do_not_claim_more_than_the_rows_hold():
  protocol = protocols.get("single_cell_genomics")
  report = transfer_report([s.op for s in protocol.steps])
  counts = report.counts()
  assert counts["with_envelope"] == 0
  assert counts["attained"] == 0
  assert counts["specified"] <= counts["operations"]
  assert counts["asserted_only"] <= counts["operations"]


def test_teaching_summary_matches_the_module_data():
  s = teaching_summary()
  assert s["operations_specified"] == len(TRANSFERABLE)
  assert s["demonstrations_recorded"] == len(DEMONSTRATIONS)
  assert s["machine_observations_recorded"] == len(MACHINE_OBSERVATIONS)
  assert s["minimum_demonstrations"] == MIN_DEMONSTRATIONS


# -- nothing an author writes can silence the refusal --------------------------


def test_no_field_anywhere_declares_a_tolerance_or_an_attainment():
  """The author-settable field that quiets a report is the failure this rules out.

  Every number an envelope states is a method over the demonstrations, so there is no
  attribute to set and no stored value to drift from the data it summarizes.
  """
  fields = {f.name for f in dataclasses.fields(Envelope)}
  assert fields == {"operation", "metric", "units", "goal", "demonstrations"}
  for name in ("tolerance", "center", "spread", "refusal", "caveat", "n"):
    assert callable(getattr(Envelope, name)), f"{name} must be derived, not stored"
  spec_fields = {f.name for f in dataclasses.fields(TRANSFERABLE_BY_OP[CLEANUP])}
  for forbidden in ("taught", "tolerance", "attainment", "demonstrated"):
    assert forbidden not in spec_fields


def test_an_envelope_refuses_to_pool_two_different_metrics():
  """One range over two quantities is a number about nothing."""
  spec = TRANSFERABLE_BY_OP[CLEANUP]
  wrong_units = Demonstration(
    operation=CLEANUP,
    metric=spec.metric,
    units="percent",
    value=85.0,
    by="scientist_b",
    conditions=spec.conditions,
  )
  with pytest.raises(ValueError, match="two metrics pooled"):
    Envelope(
      operation=CLEANUP,
      metric=spec.metric,
      units=spec.units,
      goal=spec.goal,
      demonstrations=(_demo(0.85), _demo(0.80), wrong_units),
    )


def test_an_envelope_refuses_a_demonstration_of_another_operation():
  spec = TRANSFERABLE_BY_OP[CLEANUP]
  with pytest.raises(ValueError, match="holds a demonstration of"):
    Envelope(
      operation=CLEANUP,
      metric=spec.metric,
      units=spec.units,
      goal=spec.goal,
      demonstrations=(_demo(0.85), _demo(9.9, op=LYSIS)),
    )


def test_an_untaught_operation_is_named_in_its_own_refusal():
  """The untaught case is the common one, and it is the case where neither the envelope nor
  the observations carry the operation's name -- both are absent. Without the caller
  supplying it the refusal reads "no expert has demonstrated 'unknown'", which names nothing
  and is useless as a queue entry, in the report whose entire job is to be that queue.
  """
  report = transfer_report(["library_pool"])
  row = report.rows[0]
  assert row.parity.operation == "library_pool"
  assert "library_pool" in row.parity.reason
  assert "unknown" not in row.parity.reason

  # And the bare function still works when the caller does not supply it.
  assert attainment(None, (), operation="named_op").operation == "named_op"
  assert attainment(None, ()).operation == "unknown"
