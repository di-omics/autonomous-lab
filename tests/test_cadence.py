"""Device-free tests for the cadence model.

Three things are being defended here and they fail in different ways.

The arithmetic is pinned exactly rather than approximately. 500 plates a day is 172.8
seconds and nothing else, and a test that tolerated a percent of drift would let a rounding
bug through into the one number in this package that needs no evidence to be correct.

The refusals have to survive being routed around. A target that does not say whether it
counts plates started, completed, QC-passed, or released must be refused whether it arrives
as a `Target` or as a bare float, because the convenient path is exactly where a caller in
a hurry will push.

And `demonstrated_support` must never return a supporting citation. Not for a large target,
not for a small one, not for any of the four endpoints. The published record cited in this
module contains campaigns and capability demonstrations; it contains no sustained production
rate, and the moment a test tolerates one appearing, the module has started flattering the
field it exists to report on.
"""

from __future__ import annotations

import inspect

import pytest

from autonomous_lab.cadence import (
  DEMONSTRATIONS,
  NO_INTEGRATED_PRODUCTION_RATE,
  REFERENCES,
  Cadence,
  Demonstrated,
  Endpoint,
  Forcing,
  Target,
  cadence_for,
  demonstrated_support,
  headroom,
  intervals,
  launch_interval,
  required_admissions,
  sustained_rate_demonstrations,
)


# -- the arithmetic, pinned exactly --------------------------------------------


def test_500_plates_a_day_is_a_plate_every_172_8_seconds():
  """86400 / 500. The whole module rests on this division being right."""
  assert launch_interval(500, 24) == 172.8


def test_the_same_500_inside_a_staffed_day_is_115_2_seconds():
  """57600 / 500. Same target, no change in scope, 33 percent less time per plate."""
  assert launch_interval(500, 16) == 115.2


def test_172_8_seconds_is_2_88_minutes_and_115_2_is_1_92():
  """The seconds are pinned exactly. Minutes are a display, so they get a tolerance."""
  c = cadence_for(Target(500, Endpoint.STARTED), operating_hours=16)
  assert c.round_the_clock_seconds == 172.8
  assert c.interval_seconds == 115.2
  assert c.round_the_clock_seconds / 60.0 == pytest.approx(2.88)
  assert c.minutes_between_plates == pytest.approx(1.92)


def test_both_intervals_are_reported_not_one():
  """Quoting only the 24-hour figure describes a lab that runs unattended."""
  assert intervals(500, 16) == (172.8, 115.2)


def test_the_walk_away_penalty_is_the_hours_ratio_and_nothing_else():
  """1.5x at 16 hours, and it does not depend on the target, protocol, or instruments."""
  c16 = cadence_for(Target(500, Endpoint.STARTED), operating_hours=16)
  c8 = cadence_for(Target(37, Endpoint.STARTED), operating_hours=8)
  assert c16.walk_away_multiplier == 1.5
  assert c8.walk_away_multiplier == 3.0


def test_a_window_longer_than_the_day_is_refused():
  """A 30-hour window makes any target look achievable by arithmetic alone."""
  with pytest.raises(ValueError, match="does not fit in a day"):
    launch_interval(500, 30)


def test_a_zero_or_negative_window_is_refused():
  with pytest.raises(ValueError):
    launch_interval(500, 0)
  with pytest.raises(ValueError):
    launch_interval(500, -8)


def test_a_zero_or_negative_target_is_not_a_target():
  with pytest.raises(ValueError):
    Target(0, Endpoint.STARTED)
  with pytest.raises(ValueError):
    Target(-1, Endpoint.STARTED)
  with pytest.raises(ValueError):
    launch_interval(0, 24)


# -- the endpoint refusal ------------------------------------------------------


def test_a_target_that_does_not_say_what_it_counts_is_refused():
  """Not answered with the loosest reading. Refused."""
  with pytest.raises(ValueError) as err:
    cadence_for(Target(500))
  assert "does not say what it counts" in str(err.value)


def test_the_refusal_names_all_four_endpoints_so_the_caller_can_pick_one():
  with pytest.raises(ValueError) as err:
    cadence_for(Target(500))
  message = str(err.value)
  for word in ("STARTED", "COMPLETED", "QC_PASSED", "RELEASED"):
    assert word in message


def test_a_bare_number_cannot_route_around_the_refusal():
  """The convenient path is where a caller in a hurry pushes, so it is closed too."""
  with pytest.raises(ValueError, match="does not say what it counts"):
    cadence_for(500)


def test_demonstrated_support_refuses_an_unstated_endpoint_rather_than_answering():
  support = demonstrated_support(500)
  assert support.refused
  assert not support.supported
  assert support.nearest == ()


def test_a_refused_target_gets_no_citations_at_all():
  """Listing the nearest evidence before the question is well posed invites cherry-picking."""
  support = demonstrated_support(Target(500))
  assert support.refused
  assert support.supporting() == ()
  assert len(support.nearest) == 0


def test_only_started_is_an_admission_rate():
  assert Endpoint.STARTED.is_admission_rate
  assert not Endpoint.COMPLETED.is_admission_rate
  assert not Endpoint.QC_PASSED.is_admission_rate
  assert not Endpoint.RELEASED.is_admission_rate


def test_a_downstream_target_has_no_admission_rate_without_a_measured_yield():
  """None, not an assumed yield of 1.0. Assuming 1.0 under-admits by exactly the failure rate."""
  assert required_admissions(Target(500, Endpoint.RELEASED)) is None
  assert required_admissions(Target(500, Endpoint.QC_PASSED)) is None
  assert required_admissions(Target(500, Endpoint.COMPLETED)) is None


def test_a_started_target_needs_no_yield_and_ignores_one_offered():
  assert required_admissions(Target(500, Endpoint.STARTED)) == 500
  assert required_admissions(Target(500, Endpoint.STARTED), yield_fraction=0.5) == 500


def test_a_rerun_rate_raises_the_admission_rate_and_shortens_the_interval():
  """500 released at 80 percent yield is 625 admitted, and 138.24 s rather than 172.8 s."""
  admissions = required_admissions(Target(500, Endpoint.RELEASED), yield_fraction=0.8)
  assert admissions == 625
  assert launch_interval(admissions, 24) == 138.24
  assert launch_interval(admissions, 24) < launch_interval(500, 24)


def test_required_admissions_refuses_an_ambiguous_target_and_a_non_fraction_yield():
  with pytest.raises(ValueError, match="does not say what it counts"):
    required_admissions(Target(500))
  with pytest.raises(ValueError):
    required_admissions(Target(500, Endpoint.RELEASED), yield_fraction=0)
  with pytest.raises(ValueError):
    required_admissions(Target(500, Endpoint.RELEASED), yield_fraction=1.4)


# -- what the interval forces --------------------------------------------------


def test_a_target_below_the_slowest_declared_step_is_unachievable_on_one_line():
  """The step holds the line for 600 s and a plate must enter every 172.8 s."""
  c = cadence_for(Target(500, Endpoint.STARTED), slowest_step_seconds=600)
  assert c.single_line_feasible is False
  assert c.lines_required == 4
  lines = _forcing(c, Forcing.LINES)
  assert lines.unachievable
  assert "unachievable on a single line" in lines.statement


def test_the_unachievable_finding_says_other_instruments_do_not_help():
  """'Just make the rest faster' is the reflex, and the arithmetic says it changes nothing."""
  c = cadence_for(Target(500, Endpoint.STARTED), slowest_step_seconds=600)
  statement = _forcing(c, Forcing.LINES).statement
  assert "Speeding up every OTHER instrument changes nothing" in statement


def test_the_line_count_rounds_up_because_three_and_a_half_lines_do_not_exist():
  c = cadence_for(Target(500, Endpoint.STARTED), slowest_step_seconds=600)
  assert 600 / c.interval_seconds > 3
  assert c.lines_required == 4


def test_a_step_inside_the_interval_needs_one_line_and_says_what_that_does_not_prove():
  c = cadence_for(Target(500, Endpoint.STARTED), slowest_step_seconds=60)
  assert c.single_line_feasible is True
  assert c.lines_required == 1
  lines = _forcing(c, Forcing.LINES)
  assert not lines.unachievable
  assert "assumes the caller named the true slowest step" in lines.statement


def test_an_undeclared_slowest_step_is_refused_rather_than_defaulted():
  """Defaulting to zero would report one line as sufficient for every target ever stated."""
  c = cadence_for(Target(500, Endpoint.STARTED))
  assert c.lines_required is None
  assert c.single_line_feasible is None
  lines = _forcing(c, Forcing.LINES)
  assert not lines.computable
  assert lines.value is None
  assert "not computable" in lines.statement


def test_buffer_is_refused_without_an_end_to_end_duration():
  c = cadence_for(Target(500, Endpoint.STARTED))
  assert c.plates_in_flight is None
  buffer = _forcing(c, Forcing.BUFFER)
  assert not buffer.computable
  assert buffer.value is None


def test_buffer_counts_the_plates_that_must_be_physically_resident():
  """A 2-hour end-to-end at a 172.8 s interval means 42 plates are in the workcell at once."""
  c = cadence_for(Target(500, Endpoint.STARTED), end_to_end_seconds=7200)
  assert c.plates_in_flight == 42
  buffer = _forcing(c, Forcing.BUFFER)
  assert buffer.computable
  assert buffer.value == 42.0


def test_recovery_and_upkeep_need_no_declared_duration_at_all():
  """Both are arithmetic on the interval, so neither can be refused for missing data."""
  c = cadence_for(Target(500, Endpoint.STARTED))
  assert _forcing(c, Forcing.RECOVERY).computable
  assert _forcing(c, Forcing.UPKEEP).computable


def test_a_stoppage_costs_admissions_at_exactly_the_launch_rate():
  """An hour down at 500/day costs 20.8 plates, and the day has no slack to make them back."""
  c = cadence_for(Target(500, Endpoint.STARTED))
  assert c.admissions_lost(3600) == 3600 / 172.8
  assert c.admissions_lost(0) == 0.0
  with pytest.raises(ValueError):
    c.admissions_lost(-1)


def test_a_short_stop_is_not_rounded_down_to_free():
  c = cadence_for(Target(500, Endpoint.STARTED))
  assert 0 < c.admissions_lost(60) < 1


def test_upkeep_shortens_the_interval_because_it_shares_the_window():
  """An hour of daily upkeep turns 172.8 s into 165.6 s for the same target."""
  c = cadence_for(Target(500, Endpoint.STARTED))
  assert c.interval_net_of(3600) == 165.6
  assert c.interval_net_of(0) == c.interval_seconds


def test_upkeep_that_consumes_the_window_is_refused_not_returned_as_a_number():
  """A negative interval formats as a number and would be quoted as one."""
  c = cadence_for(Target(500, Endpoint.STARTED))
  with pytest.raises(ValueError, match="consumes the whole"):
    c.interval_net_of(86400)
  with pytest.raises(ValueError):
    c.interval_net_of(90000)


def test_every_forcing_appears_exactly_once_including_the_refused_ones():
  """An omitted constraint reads as inapplicable, which is not what a missing duration means."""
  c = cadence_for(Target(500, Endpoint.STARTED))
  seen = [i.forcing for i in c.implied_constraints()]
  assert seen == [Forcing.LINES, Forcing.BUFFER, Forcing.RECOVERY, Forcing.UPKEEP]
  assert len(set(seen)) == len(Forcing)


def test_only_lines_and_buffer_are_relieved_by_hardware():
  """Two of the four are purchases. The other two are charges against the same clock."""
  assert Forcing.LINES.relieved_by_hardware
  assert Forcing.BUFFER.relieved_by_hardware
  assert not Forcing.RECOVERY.relieved_by_hardware
  assert not Forcing.UPKEEP.relieved_by_hardware


def test_every_implication_shows_its_arithmetic():
  c = cadence_for(Target(500, Endpoint.STARTED), slowest_step_seconds=600, end_to_end_seconds=7200)
  for imp in c.implied_constraints():
    assert imp.arithmetic
    assert imp.statement


def test_a_declared_duration_of_zero_or_less_is_refused():
  with pytest.raises(ValueError, match="not a duration"):
    cadence_for(Target(500, Endpoint.STARTED), slowest_step_seconds=0)
  with pytest.raises(ValueError, match="not a duration"):
    cadence_for(Target(500, Endpoint.STARTED), end_to_end_seconds=-5)


# -- the human share of the clock ----------------------------------------------


def test_an_intervention_rate_high_enough_to_consume_the_clock_makes_the_target_unreachable():
  """A human on half of all plates for 10 minutes is 300 s against a 172.8 s interval."""
  h = headroom(172.8, intervention_rate=0.5, minutes_per_intervention=10)
  assert h.human_seconds_per_plate == 300.0
  assert h.consumed_fraction > 1.0
  assert not h.reachable
  assert h.slack_seconds < 0
  assert h.operators_required == 2


def test_exactly_one_hundred_percent_of_the_clock_is_not_reachable():
  """Zero slack plus any variance is a backlog that grows rather than one that hovers."""
  h = headroom(172.8, intervention_rate=1.0, minutes_per_intervention=172.8 / 60.0)
  assert h.consumed_fraction == 1.0
  assert h.slack_seconds == 0.0
  assert not h.reachable


def test_a_survivable_intervention_rate_reports_what_is_left_and_what_still_wants_it():
  h = headroom(172.8, intervention_rate=0.1, minutes_per_intervention=2)
  assert h.human_seconds_per_plate == 12.0
  assert h.reachable
  assert h.slack_seconds == 160.8
  assert "upkeep and the recovery" in h.why()


def test_no_interventions_leaves_the_whole_clock_and_names_no_operator():
  h = headroom(172.8, intervention_rate=0.0, minutes_per_intervention=30)
  assert h.consumed_fraction == 0.0
  assert h.reachable
  assert h.operators_required == 0
  assert h.ceiling_interval_seconds is None
  assert h.ceiling_plates_per_day() is None


def test_the_finding_says_instrument_speed_is_not_in_the_arithmetic():
  """This is the sentence the module exists to be able to print."""
  h = headroom(172.8, intervention_rate=0.5, minutes_per_intervention=10)
  why = h.why()
  assert "Instrument speed appears nowhere in this arithmetic" in why
  assert "faster robot does not move it" in why


def test_headroom_takes_no_instrument_argument_of_any_kind():
  """Structural, not textual: there is no parameter a faster machine could be declared in."""
  params = list(inspect.signature(headroom).parameters)
  assert params == ["interval_seconds", "intervention_rate", "minutes_per_intervention"]


def test_only_the_product_of_rate_and_duration_matters():
  """Rare-and-long and frequent-and-short cost the identical share of the clock."""
  rare = headroom(172.8, intervention_rate=0.5, minutes_per_intervention=10)
  frequent = headroom(172.8, intervention_rate=1.0, minutes_per_intervention=5)
  assert rare.human_seconds_per_plate == frequent.human_seconds_per_plate
  assert rare.consumed_fraction == frequent.consumed_fraction


def test_one_operator_has_a_plates_per_day_ceiling_that_ignores_the_robot_entirely():
  """5 minutes of attention per plate caps a 24-hour day at 288 plates, whatever is installed."""
  h = headroom(172.8, intervention_rate=1.0, minutes_per_intervention=5)
  assert h.ceiling_interval_seconds == 300.0
  assert h.ceiling_plates_per_day(24) == 288.0
  assert h.ceiling_plates_per_day(8) == 96.0


def test_headroom_refuses_impossible_inputs():
  with pytest.raises(ValueError):
    headroom(0, 0.1, 2)
  with pytest.raises(ValueError):
    headroom(172.8, -0.1, 2)
  with pytest.raises(ValueError):
    headroom(172.8, 0.1, -2)


# -- the honest check ----------------------------------------------------------


def test_demonstrated_support_never_returns_a_supporting_citation():
  """For any endpoint, at any target. This is the assertion the module is built around."""
  for endpoint in Endpoint:
    support = demonstrated_support(Target(500, endpoint))
    assert not support.refused
    assert not support.supported
    assert support.supporting() == ()


def test_lowering_the_target_does_not_manufacture_support():
  """A cited campaign is not a rate, so shrinking the number does not turn one into one."""
  for plates in (1, 6, 500, 50_000):
    support = demonstrated_support(Target(plates, Endpoint.STARTED))
    assert not support.supported
    assert support.supporting() == ()


def test_no_cited_work_claims_a_sustained_rate():
  assert sustained_rate_demonstrations() == ()
  assert all(d.demonstrated is not Demonstrated.SUSTAINED_RATE for d in DEMONSTRATIONS)
  assert all(not d.establishes_a_rate for d in DEMONSTRATIONS)


def test_the_reason_states_that_no_cited_system_establishes_it():
  support = demonstrated_support(Target(500, Endpoint.RELEASED))
  assert NO_INTEGRATED_PRODUCTION_RATE in support.reason
  assert "No cited published system establishes integrated multi-domain" in support.reason


def test_the_support_flag_is_computed_from_the_table_rather_than_hard_coded():
  """If a genuine sustained-rate work is ever added, this flips without editing the flag."""
  support = demonstrated_support(Target(500, Endpoint.STARTED))
  assert support.supported == bool(support.supporting())
  assert support.nearest == DEMONSTRATIONS


def test_every_demonstration_records_what_it_does_not_establish():
  """A citation table whose caveats are optional degrades into a list of names."""
  for d in DEMONSTRATIONS:
    assert d.does_not_establish.strip()
    assert len(d.does_not_establish) > 100
    assert d.ran_for.strip()
    assert d.scale.strip()


def test_every_demonstration_resolves_to_a_full_citation():
  for d in DEMONSTRATIONS:
    assert d.key in REFERENCES
    assert d.citation == REFERENCES[d.key]


def test_the_only_continuous_multi_site_work_in_the_table_actuates_nothing():
  """The longest-running system cited does not run experiments. It watches cages."""
  keys = [d.key for d in DEMONSTRATIONS if not d.actuates]
  assert "homecage_multi" in keys
  watcher = next(d for d in DEMONSTRATIONS if d.key == "homecage_multi")
  assert watcher.demonstrated is Demonstrated.CAMPAIGN
  assert "It observes" in watcher.does_not_establish
  assert "retrospective" in watcher.does_not_establish


def test_the_only_per_day_figure_in_the_table_is_flagged_as_a_peak():
  """A peak day is the opposite of a sustained cadence, and it is the only number available."""
  alabos = next(d for d in DEMONSTRATIONS if d.key == "alabos")
  assert "peak" in alabos.scale
  assert "PEAK day" in alabos.does_not_establish


def test_a_published_plates_per_day_number_exists_and_is_a_study_design():
  """3 or 6 plates a day, from pre-production validation guidance, not an achieved throughput."""
  ncats = next(d for d in DEMONSTRATIONS if d.key == "ncats")
  assert ncats.demonstrated is Demonstrated.NO_RATE_CLAIM
  assert "STUDY DESIGN" in ncats.does_not_establish


def test_the_authors_own_throughput_disclaimers_are_recorded_not_paraphrased_away():
  roboculture = next(d for d in DEMONSTRATIONS if d.key == "roboculture")
  assert "explicitly disclaim throughput" in roboculture.does_not_establish
  smartkage = next(d for d in DEMONSTRATIONS if d.key == "smartkage")
  assert "low throughput" in smartkage.does_not_establish


# -- shape ---------------------------------------------------------------------


def test_a_cadence_is_frozen_so_a_reported_interval_cannot_be_edited_afterwards():
  c = cadence_for(Target(500, Endpoint.STARTED))
  assert isinstance(c, Cadence)
  with pytest.raises(Exception):
    c.interval_seconds = 1.0  # type: ignore[misc]


def test_the_constraints_recompute_rather_than_being_stored():
  """Two calls agree because both derive from the interval, not from a cached list."""
  c = cadence_for(Target(500, Endpoint.STARTED), slowest_step_seconds=600)
  first = c.implied_constraints()
  second = c.implied_constraints()
  assert [i.forcing for i in first] == [i.forcing for i in second]
  assert [i.value for i in first] == [i.value for i in second]


def _forcing(cadence: Cadence, forcing: Forcing):
  return next(i for i in cadence.implied_constraints() if i.forcing is forcing)


# -- the negative claim must be behaviour, not a permanently-false constant --------


def test_support_would_flip_if_a_sustained_rate_work_ever_appeared():
  """The module's headline is that nothing cited establishes a sustained rate. Proven only
  against the current table, that passes just as well for an implementation hard-wired to
  return nothing -- and it would keep passing after real evidence arrived.

  So inject one and check the behaviour flips. This is the test that makes the claim a
  computation rather than a constant.
  """
  import autonomous_lab.cadence as mod

  planted = mod.Demonstration(
    **{
      **{f: getattr(mod.DEMONSTRATIONS[0], f) for f in mod.DEMONSTRATIONS[0].__dataclass_fields__},
      "key": "planted_sustained_rate",
      "demonstrated": mod.Demonstrated.SUSTAINED_RATE,
    }
  )
  original = mod.DEMONSTRATIONS
  try:
    mod.DEMONSTRATIONS = original + (planted,)
    assert mod.sustained_rate_demonstrations() == (planted,)
    support = mod.demonstrated_support(mod.Target(500, mod.Endpoint.STARTED))
    assert support.supported, "a genuine sustained-rate work must flip the answer to yes"
    assert planted in support.supporting()
  finally:
    mod.DEMONSTRATIONS = original

  # And the table is back, so the standing claim is negative again.
  assert sustained_rate_demonstrations() == ()


def test_a_downstream_target_without_a_measured_yield_is_refused_not_answered():
  """A released target is a RETURN rate. Dividing its face value returns the STARTED
  interval under a RELEASED label -- the loosest reading, silently, which is the exact
  substitution this module refuses one step earlier."""
  with pytest.raises(ValueError) as err:
    cadence_for(Target(500, Endpoint.RELEASED))
  assert "admission rate" in str(err.value)

  # With a measured survival fraction it converts rather than refusing.
  converted = cadence_for(Target(500, Endpoint.RELEASED), yield_fraction=0.8)
  assert converted.interval_seconds == pytest.approx(138.24)
  # Strictly shorter than the naive division, by exactly the failure rate.
  assert converted.interval_seconds < launch_interval(500, 24)


def test_a_started_target_still_needs_no_yield():
  assert cadence_for(Target(500, Endpoint.STARTED)).interval_seconds == pytest.approx(172.8)
