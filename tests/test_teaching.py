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
import enum
import itertools

import pytest

from autonomous_lab import protocols, teaching
from autonomous_lab.intelligence import BENCHMARKS_BY_OP, BenchmarkStatus
from autonomous_lab.model import Protocol, Step
from autonomous_lab.qc import MEASUREMENTS, SORT_OCCUPANCY_GATE, Basis
from autonomous_lab.teaching import (
  DEMONSTRATIONS,
  EXEMPT,
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


# Every helper-built record gets its own source. Two runs of one operation are two runs
# because they happened separately, and the evidence string is where that separateness is
# recorded; a helper that stamped them all identically would be manufacturing the duplicate
# the module now refuses, in every fixture in this file.
_RUNS = itertools.count(1)


def _demo(
  value: float,
  op: str = CLEANUP,
  by: str = "scientist_a",
  conditions=None,
  evidence=None,
) -> Demonstration:
  spec = TRANSFERABLE_BY_OP[op]
  return Demonstration(
    operation=op,
    metric=spec.metric,
    units=spec.units,
    value=value,
    by=by,
    conditions=conditions if conditions is not None else spec.conditions,
    evidence=evidence if evidence is not None else f"notebook page {next(_RUNS)}",
  )


def _obs(
  value: float,
  op: str = CLEANUP,
  conditions=None,
  metric=None,
  units=None,
  evidence=None,
) -> MachineObservation:
  spec = TRANSFERABLE_BY_OP[op]
  return MachineObservation(
    operation=op,
    metric=spec.metric if metric is None else metric,
    units=spec.units if units is None else units,
    value=value,
    by="a run card",
    conditions=conditions if conditions is not None else spec.conditions,
    evidence=evidence if evidence is not None else f"run {next(_RUNS)}",
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
  """Nothing to rank must not read as nothing left to do.

  Asserting the empty value is asserting the ambiguity: `== []` is exactly what a lab that
  had finished teaching its machines would also return, so the queue has to REFUSE rather
  than come back empty, and the refusal is what this asserts.
  """
  nothing = demonstration_queue([])
  assert len(nothing) == 0
  assert nothing.operations_considered == 0
  assert nothing.refusal() is not None
  assert not transfer_report([]).transfers()
  assert transfer_report([]).refusal() is not None
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
    evidence="notebook page 91",
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
  supplying it the refusal reads "no expert envelope places 'unknown'", which names nothing
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


# -- the machine side gets the checks the expert side already had ---------------
# Every test above this line places a well-formed observation. The observations below are
# the malformed ones, and they are the ones that arrive from a script rather than from the
# person who measured, which is why they are the ones that reach a report unchallenged.


def test_a_machine_observation_in_other_units_is_refused_rather_than_compared():
  """Recovery logged in percent against an envelope in fractions is not a comparison.

  The mirror of `test_an_envelope_refuses_to_pool_two_different_metrics`, on the side the
  original only trusted. Untouched, 85.0 percent placed against a 0.80-0.90 fraction band
  reads as MEETS and the prose prints the machine's value beside the ENVELOPE's unit.
  """
  env = _envelope([0.80, 0.85, 0.90])
  percent = [_obs(85.0, units="percent"), _obs(88.0, units="percent"), _obs(90.0, units="percent")]
  with pytest.raises(ValueError, match="two metrics pooled"):
    attainment(env, percent)


def test_a_machine_observation_on_another_metric_is_refused():
  env = _envelope([0.80, 0.85, 0.90])
  renamed = [_obs(v, metric="fraction of wells with one cell") for v in (0.85, 0.88, 0.90)]
  with pytest.raises(ValueError, match="two metrics pooled"):
    attainment(env, renamed)


def test_a_machine_observation_of_another_operation_is_refused():
  """A sort occupancy filed under a cleanup must not read as that cleanup's parity."""
  spec = TRANSFERABLE_BY_OP[CLEANUP]
  env = _envelope([0.80, 0.85, 0.90])
  misfiled = [
    MachineObservation(
      operation="start_sort",
      metric=spec.metric,
      units=spec.units,
      value=0.99,
      by="a run card",
      conditions=spec.conditions,
      evidence=f"run {i}",
    )
    for i in range(3)
  ]
  with pytest.raises(ValueError, match="two metrics pooled"):
    attainment(env, misfiled)


def test_the_worst_run_is_reported_in_the_units_of_the_run():
  """The prose reads its unit off the observation, so a mismatch cannot hide in a sentence."""
  env = _envelope([10.0, 12.0, 14.0], op=POOLING)
  parity = attainment(env, [_obs(v, op=POOLING) for v in (5.0, 6.0, 7.0)])
  assert parity.attainment is Attainment.MEETS
  assert f"7.0 {TRANSFERABLE_BY_OP[POOLING].units}" in parity.reason


# -- an envelope is a range over one experiment ---------------------------------


def test_an_envelope_refuses_to_pool_two_sets_of_conditions():
  """The failure the module says it exists to prevent, on the side nothing was checking.

  Two demonstrations at 0.80 and 0.82 plus one at 0.30 under ten times the input pooled to
  a 0.30-0.82 band, and three machine runs at a third of the expert's recovery then read as
  MEETS against a floor the expert never produced under those conditions.
  """
  spec = TRANSFERABLE_BY_OP[CLEANUP]
  with pytest.raises(ValueError, match="one set of conditions"):
    Envelope(
      operation=CLEANUP,
      metric=spec.metric,
      units=spec.units,
      goal=spec.goal,
      demonstrations=(
        _demo(0.80),
        _demo(0.82),
        _demo(0.30, conditions="ten times the input amount"),
      ),
    )


def test_an_off_condition_demonstration_cannot_widen_the_band_into_a_pass(monkeypatch):
  """Adding a demonstration under conditions the machine never ran at must not flip a verdict."""
  nanogram = tuple(_demo(v) for v in (0.85, 0.88, 0.90))
  picogram = (_demo(0.40, conditions="picogram spike-in of known quantity"),)
  runs = tuple(_obs(v) for v in (0.45, 0.50, 0.55))

  monkeypatch.setattr(teaching, "DEMONSTRATIONS", nanogram)
  monkeypatch.setattr(teaching, "MACHINE_OBSERVATIONS", runs)
  monkeypatch.setattr(teaching, "ENVELOPES", teaching._build_envelopes())
  control = teaching.transfer_report([CLEANUP])
  assert control.counts()["below"] == 1

  monkeypatch.setattr(teaching, "DEMONSTRATIONS", nanogram + picogram)
  monkeypatch.setattr(teaching, "ENVELOPES", teaching._build_envelopes())
  widened = teaching.transfer_report([CLEANUP])
  assert widened.counts()["below"] == 1, "an off-condition demonstration widened the band"
  assert not widened.transfers()
  # The picogram run is its own experiment, and it keeps its own envelope.
  assert len(teaching.envelopes_for(CLEANUP)) == 2
  assert teaching.envelope_for(CLEANUP) is None
  assert "different sets of conditions" in taught(CLEANUP)[1]


# -- goal comes from the spec, and the comparison reads it off the enum ---------


def test_an_envelope_cannot_redeclare_which_direction_is_better():
  """The one field that flips a verdict, checked against the layer that owns it.

  `test_no_field_anywhere_declares_a_tolerance_or_an_attainment` enumerates `goal` as an
  acceptable field name. It is acceptable only because a mismatched one is refused, and a
  test on names alone would bless the field that turns BELOW into MEETS.
  """
  for op, spec in TRANSFERABLE_BY_OP.items():
    wrong = Goal.LOWER if spec.goal is not Goal.LOWER else Goal.HIGHER
    with pytest.raises(ValueError, match="is better"):
      Envelope(operation=op, metric=spec.metric, units=spec.units, goal=wrong)


def test_an_envelope_cannot_restate_the_metric_or_the_units_either():
  spec = TRANSFERABLE_BY_OP[CLEANUP]
  with pytest.raises(ValueError, match="is better"):
    Envelope(operation=CLEANUP, metric=spec.metric, units="percent", goal=spec.goal)


def test_an_envelope_for_an_operation_nobody_specified_is_refused():
  """`_build_envelopes` already treats this as an error; the public constructor must too."""
  with pytest.raises(ValueError, match="no Transferable declares"):
    Envelope(
      operation="an_operation_nobody_ever_wrote_down",
      metric="something",
      units="units",
      goal=Goal.HIGHER,
    )


def test_leaving_the_range_the_better_way_is_a_failure_exactly_where_the_goal_says_so():
  """The two-sided rule is read off `Goal.outside_is_always_worse`, not restated as an else.

  Every Goal member is exercised, so a fourth one cannot inherit WINDOW semantics from a
  fall-through while the property reports False for it.
  """
  cases = (
    (CLEANUP, [0.80, 0.85, 0.90], (0.95, 0.96, 0.97)),  # HIGHER: above the band
    (POOLING, [10.0, 12.0, 14.0], (5.0, 6.0, 7.0)),  # LOWER: below the band
    (LYSIS, [9.8, 10.0, 10.2], (11.0, 11.1, 11.2)),  # WINDOW: above the band
  )
  seen = set()
  for op, demonstrated, runs in cases:
    goal = TRANSFERABLE_BY_OP[op].goal
    seen.add(goal)
    env = _envelope(demonstrated, op=op)
    parity = attainment(env, [_obs(v, op=op) for v in runs])
    beyond_is_a_failure = parity.attainment is Attainment.BELOW
    assert beyond_is_a_failure is goal.outside_is_always_worse, op
  assert seen == set(Goal), "a Goal member no test reaches is a branch nobody checks"


def test_a_goal_the_comparison_does_not_handle_is_refused_rather_than_defaulted(monkeypatch):
  """A fourth direction must reach a refusal, not the two-sided branch by accident."""

  class _Centered(str, enum.Enum):
    CENTERED = "centered"

    @property
    def outside_is_always_worse(self) -> bool:
      return False

  spec = TRANSFERABLE_BY_OP[CLEANUP]
  monkeypatch.setitem(
    teaching.TRANSFERABLE_BY_OP, CLEANUP, dataclasses.replace(spec, goal=_Centered.CENTERED)
  )
  env = Envelope(
    operation=CLEANUP,
    metric=spec.metric,
    units=spec.units,
    goal=_Centered.CENTERED,
    demonstrations=tuple(_demo(v) for v in (0.80, 0.85, 0.90)),
  )
  with pytest.raises(ValueError, match="does not handle"):
    attainment(env, [_obs(v) for v in (0.85, 0.86, 0.87)])


# -- a verdict against the machine has to be readable ---------------------------


def test_a_machine_below_the_expert_is_readable_in_the_report(monkeypatch):
  """The only verdict that says the machine performs worse, and it had no accessor at all."""
  monkeypatch.setattr(teaching, "DEMONSTRATIONS", tuple(_demo(v) for v in (0.80, 0.85, 0.90)))
  monkeypatch.setattr(teaching, "MACHINE_OBSERVATIONS", tuple(_obs(v) for v in (0.10, 0.12, 0.11)))
  monkeypatch.setattr(teaching, "ENVELOPES", teaching._build_envelopes())
  report = teaching.transfer_report([CLEANUP])
  assert [r.operation for r in report.below()] == [CLEANUP]
  assert report.counts()["below"] == 1
  assert not report.transfers()


def test_relabelling_the_conditions_cannot_erase_a_verdict_without_trace(monkeypatch):
  """`conditions` is free text on both sides, so the erasure has to leave a count behind."""
  monkeypatch.setattr(teaching, "DEMONSTRATIONS", tuple(_demo(v) for v in (0.80, 0.85, 0.90)))
  monkeypatch.setattr(teaching, "ENVELOPES", teaching._build_envelopes())

  monkeypatch.setattr(teaching, "MACHINE_OBSERVATIONS", tuple(_obs(v) for v in (0.10, 0.12, 0.11)))
  stated = teaching.transfer_report([CLEANUP]).counts()

  elsewhere = tuple(_obs(v, conditions="a condition nobody demonstrated") for v in (0.10, 0.12, 0.11))
  monkeypatch.setattr(teaching, "MACHINE_OBSERVATIONS", elsewhere)
  silenced = teaching.transfer_report([CLEANUP])
  assert silenced.counts() != stated
  assert silenced.counts()["discarded_observations"] == 3
  assert silenced.rows[0].parity.machine_n == 3
  assert silenced.rows[0].parity.matched_n == 0


def test_every_row_lands_in_exactly_one_verdict_bucket():
  """Buckets that do not sum are buckets with somewhere for a verdict to go missing."""
  protocol = protocols.get("single_cell_genomics")
  counts = transfer_report([s.op for s in protocol.steps]).counts()
  assert (
    counts["attained"] + counts["below"] + counts["unmeasured"] + counts["unplaceable"]
    == counts["operations"]
  )


def test_a_met_benchmark_is_not_a_target_nobody_has_hit():
  """`asserted_only` resolves the STATUS, which is the property `intelligence` draws it with."""
  for op in ("tray_cycle", "iswap_to_hhs"):
    row = transfer_report([op]).rows[0]
    assert row.benchmarks and all(b.status is BenchmarkStatus.MET for b in row.benchmarks)
    assert not row.asserted_only
    assert row.met_without_envelope
  unmet = transfer_report(["read_absorbance"]).rows[0]
  assert unmet.benchmarks[0].status is BenchmarkStatus.UNMET
  assert unmet.asserted_only


# -- the backlog names what nobody has specified --------------------------------


def test_a_protocol_of_operations_nobody_specified_still_produces_a_backlog():
  """The most untaught operations there are, and the queue used to omit them entirely."""
  nameless = Protocol(
    name="unspecified",
    summary="two operations nobody ever wrote a spec for",
    steps=(
      Step(instrument="star", op="an_operation_nobody_ever_wrote_down", summary=""),
      Step(instrument="star", op="another_undeclared_op", summary=""),
    ),
  )
  queue = demonstration_queue([nameless])
  assert {u.operation for u in queue.unspecified} == {
    "an_operation_nobody_ever_wrote_down",
    "another_undeclared_op",
  }
  assert all(u.demonstrations_needed == MIN_DEMONSTRATIONS for u in queue.unspecified)
  assert queue.operations_considered == 2
  assert queue.refusal() is None
  assert queue.cost() == 2 * MIN_DEMONSTRATIONS
  # The module used to disagree with itself on this exact input.
  assert {op for op, _why in untaught_operations(nameless)} == {
    u.operation for u in queue.unspecified
  }


def test_the_queue_accounts_for_every_operation_the_protocol_runs():
  """Ranked, unspecified, or exempt. Nothing is dropped on the way out of the loop."""
  protocol = protocols.get("single_cell_genomics")
  queue = demonstration_queue([protocol])
  named = (
    {op for entry in queue for op in entry.operations}
    | {u.operation for u in queue.unspecified}
    | set(queue.exempt)
  )
  assert named == {s.op for s in protocol.steps}
  assert queue.operations_considered == len(named)
  assert queue.unspecified, "a real protocol with nothing unspecified would be suspicious"


def test_an_exemption_has_to_say_why_and_cannot_double_as_a_specification():
  """An exemption removes work from a backlog, so it is the shape of a silencer."""
  assert EXEMPT
  for op, why in EXEMPT.items():
    assert why.strip(), f"'{op}' is exempt and says nothing about why"
    assert op not in TRANSFERABLE_BY_OP
    ok, reason = taught(op)
    assert not ok, f"'{op}' reads as taught because it was exempted"
    assert "exempt" in reason


def test_a_queue_over_a_protocol_with_no_steps_is_not_a_queue_over_no_protocols():
  """Three states that used to return the same empty list."""
  stepless = Protocol(name="stepless", summary="", steps=())
  nothing_handed = demonstration_queue([])
  nothing_in_it = demonstration_queue([stepless])
  assert nothing_handed.refusal() is not None
  assert nothing_in_it.refusal() is not None
  assert untaught_operations(stepless).refusal() is not None
  assert untaught_operations(protocols.get("single_cell_genomics")).refusal() is None


# -- three entries is not three measurements ------------------------------------


def test_one_measurement_recorded_three_times_is_not_three_measurements():
  """The repo's own last-audit precedent: a duplicate entry defeating a gate."""
  once = _demo(0.85)
  spec = TRANSFERABLE_BY_OP[CLEANUP]
  with pytest.raises(ValueError, match="not two measurements"):
    Envelope(
      operation=CLEANUP,
      metric=spec.metric,
      units=spec.units,
      goal=spec.goal,
      demonstrations=(once, once, once),
    )


def test_one_machine_run_counted_three_times_is_not_three_runs():
  """The sub-case at the API level: one run repeated cleared a minimum one run cannot."""
  env = _envelope([0.80, 0.85, 0.90])
  once = _obs(0.88)
  assert attainment(env, [once]).attainment is Attainment.INDISTINGUISHABLE_FROM_UNMEASURED
  with pytest.raises(ValueError, match="one run counted"):
    attainment(env, [once, once, once])


def test_a_range_of_width_zero_over_three_runs_is_refused():
  """Three independent runs of a continuous quantity do not agree to full precision."""
  env = _envelope([0.85, 0.85, 0.85])
  assert env.n() == MIN_DEMONSTRATIONS
  assert env.tolerance() is None
  assert env.spread() is None
  assert "transcribed" in (env.refusal() or "")


def test_two_numbers_copied_do_not_certify_a_transfer(monkeypatch):
  """The end-to-end version. This is the test that catches the whole family."""
  monkeypatch.setattr(
    teaching, "DEMONSTRATIONS", tuple(_demo(0.85, evidence=f"page {i}") for i in range(3))
  )
  monkeypatch.setattr(
    teaching, "MACHINE_OBSERVATIONS", tuple(_obs(0.88, evidence=f"run {i}") for i in range(3))
  )
  monkeypatch.setattr(teaching, "ENVELOPES", teaching._build_envelopes())
  report = teaching.transfer_report([CLEANUP])
  assert not report.transfers()
  assert report.counts()["attained"] == 0
  assert report.counts()["with_envelope"] == 0
  assert not taught(CLEANUP)[0]
  assert teaching.demonstrations_still_needed(CLEANUP) >= 1


def test_the_backlog_never_says_zero_while_the_verdict_says_untaught():
  """Two numbers a reader puts side by side, and no reader could resolve a disagreement."""
  for op in list(TRANSFERABLE_BY_OP) + ["an_operation_nobody_ever_wrote_down"]:
    if not taught(op)[0]:
      assert demonstrations_still_needed(op) >= 1, op


# -- a number with no source, and a number that is not a number -----------------


def test_a_demonstration_with_no_evidence_is_refused():
  """Every sibling module carries a basis or an evidence string. This one has to as well."""
  spec = TRANSFERABLE_BY_OP[CLEANUP]
  with pytest.raises(ValueError, match="records no evidence"):
    Demonstration(
      operation=CLEANUP,
      metric=spec.metric,
      units=spec.units,
      value=0.85,
      by="scientist_a",
      conditions=spec.conditions,
      evidence="   ",
    )


def test_a_machine_observation_with_no_evidence_is_refused():
  spec = TRANSFERABLE_BY_OP[CLEANUP]
  with pytest.raises(ValueError, match="records no evidence"):
    MachineObservation(
      operation=CLEANUP,
      metric=spec.metric,
      units=spec.units,
      value=0.88,
      by="a run card",
      conditions=spec.conditions,
      evidence="",
    )


def test_a_run_whose_outcome_could_not_be_measured_is_not_an_observation():
  """A NaN pads n while being invisible to min and max, and min/max short-circuit on it.

  Untouched, two real demonstrations plus one non-measurement produced the tolerance two
  real demonstrations alone are refused, and the machine verdict depended on input order.
  """
  for bad in (float("nan"), float("inf"), float("-inf")):
    with pytest.raises(ValueError, match="not an observation of the operation"):
      _demo(bad)
    with pytest.raises(ValueError, match="not an observation of the operation"):
      _obs(bad)


def test_every_specified_metric_says_where_the_choice_of_metric_came_from():
  """A metric choice is a scientific claim, and this package attributes those everywhere."""
  for spec in TRANSFERABLE:
    assert isinstance(spec.basis, Basis)
    assert not spec.basis.validated, (
      f"'{spec.op}' claims a validated basis for its metric; no titration in this repo "
      "established that this is the quantity that decides the operation"
    )


# -- a demonstrator handle is an identifier, not free text ----------------------


def test_a_trailing_space_does_not_turn_one_person_into_three():
  """The caveat that must travel with every parity claim, defeated by whitespace."""
  env = _envelope([0.80, 0.85, 0.90], by=("scientist_a", "Scientist_A", "scientist_a "))
  assert env.demonstrators() == ("scientist_a",)
  assert "one person's performance" in (env.caveat() or "")
  parity = attainment(env, [_obs(v) for v in (0.88, 0.87, 0.91)])
  assert parity.attainment is Attainment.MEETS
  assert "Caveat" in parity.reason
  assert taught(CLEANUP)[0] is False


def test_a_demonstration_with_no_handle_at_all_is_refused():
  with pytest.raises(ValueError, match="records no handle"):
    _demo(0.85, by="  ")


# -- qc owns the quantities it already names ------------------------------------


def test_the_sort_metric_is_resolved_from_qc_rather_than_restated():
  """Two statements of one quantity drift the first time either is edited."""
  spec = TRANSFERABLE_BY_OP["start_sort"]
  known = MEASUREMENTS[spec.measurement]
  assert spec.measurement == "well_occupancy"
  assert spec.metric == known.note
  assert spec.units == known.units


def test_a_specification_cannot_restate_a_qc_measurement_differently():
  spec = TRANSFERABLE_BY_OP["start_sort"]
  with pytest.raises(ValueError, match="qc owns this quantity"):
    dataclasses.replace(spec, units="percent")
  with pytest.raises(ValueError, match="qc does not define"):
    dataclasses.replace(spec, measurement="a_measurement_qc_never_heard_of")


def test_the_threshold_a_gate_will_enforce_travels_beside_the_benchmark():
  """The asserted number with a value on it, and the row used to carry only the one without."""
  row = transfer_report(["start_sort"]).rows[0]
  enforced = {c.name for c in row.criteria}
  assert "enough_wells_occupied" in enforced
  assert row.criteria[0] is SORT_OCCUPANCY_GATE.criteria[0]
  assert row.benchmarks  # and intelligence's target, which states no number, is still here
  assert row.asserted_only
