"""Device-free tests for the feedback controller.

The tests that matter are the ones that try to make the controller overstep: propose from
nothing, learn from its own simulator, or -- the one that would matter most in a real lab
-- relax an acceptance criterion until a run it wants to make becomes legal.
"""

from __future__ import annotations

import dataclasses
import itertools

import pytest

from autonomous_lab.acceptance import Criterion, EvidenceTier, Measurement, Origin
from autonomous_lab.control import (
  Bound,
  Controller,
  Observation,
  Proposal,
  Refusal,
  Reliability,
  ReliabilityModel,
  beta_cdf,
  beta_quantile,
)
from autonomous_lab.protocols import SINGLE_CELL_GENOMICS
from autonomous_lab.record import RunRecord
from autonomous_lab.workcell import Workcell


def _bounds():
  return [
    Bound("cycles", 20, 35, "cycles", "protocol range"),
    Bound("input_ng", 0.5, 10.0, "ng", "protocol range"),
  ]


def _obs(n, tier=EvidenceTier.MEASURED):
  out = []
  for i in range(n):
    c = 20 + i
    out.append(
      Observation(
        params={"cycles": c, "input_ng": 1.0 + i * 0.5},
        metrics={"yield_ng": 10.0 * i},
        tier=tier,
      )
    )
  return out


# -- the Beta machinery --------------------------------------------------------


def test_beta_cdf_matches_known_values():
  assert beta_cdf(0.5, 1, 1) == pytest.approx(0.5, abs=1e-9)
  assert beta_cdf(0.5, 2, 2) == pytest.approx(0.5, abs=1e-9)
  assert beta_cdf(0.0, 2, 5) == 0.0 and beta_cdf(1.0, 2, 5) == 1.0


def test_beta_quantile_inverts_the_cdf():
  for a, b in ((2, 5), (0.5, 0.5), (10, 3)):
    for p in (0.05, 0.5, 0.95):
      assert beta_cdf(beta_quantile(p, a, b), a, b) == pytest.approx(p, abs=1e-6)


def test_three_observations_are_not_enough_to_act_on():
  """At n=3 the interval is nearly the whole unit interval, and a report that printed only
  the point estimate would read as a fact."""
  r = Reliability("s", successes=2, failures=1)
  lo, hi = r.interval()
  assert hi - lo > 0.5
  assert not r.informative


def test_forty_observations_are():
  assert Reliability("s", successes=40, failures=2).informative


def test_an_unobserved_step_has_no_reliability_entry():
  m = ReliabilityModel()
  m.observe("a", True)
  assert m.known_steps() == ["a"]


# -- ranking -------------------------------------------------------------------


def test_ranking_is_by_expected_waste_not_by_failure_rate():
  """A step that fails half the time at position 1 costs almost nothing. The same rate at
  position 10 throws away everything before it."""
  m = ReliabilityModel()
  for _ in range(20):
    m.observe("start_sort", False)  # step 6, fails always
  for _ in range(20):
    m.observe("targeted_pcr_round1_cleanup", False)  # step 10, fails always
  ranked = m.rank_by_expected_waste(SINGLE_CELL_GENOMICS)
  assert [w.step for w in ranked][0] == "targeted_pcr_round1_cleanup"
  assert ranked[0].expected_waste > ranked[1].expected_waste


def test_steps_with_no_observations_are_omitted_rather_than_given_a_prior():
  """Inventing a failure rate for a step nobody has run would put fiction at the top of a
  queue meant to direct real work."""
  m = ReliabilityModel()
  m.observe("start_sort", False)
  ranked = m.rank_by_expected_waste(SINGLE_CELL_GENOMICS)
  assert [w.step for w in ranked] == ["start_sort"]


def test_learning_from_a_record_counts_outcomes_and_ignores_refusals():
  """A refused step did not run. Scoring a refusal as a failure would teach the controller
  that the gates are the problem."""
  clock = itertools.count(1.0, 1.0)
  rec = RunRecord("r", clock=lambda: next(clock))
  rec.append("proposed", step="s")
  rec.append("decided", step="s", grant="refused")
  rec.append("refused", step="s", commands_issued=0)
  rec.append("outcome", step="s", ok=True)
  rec.append("outcome", step="s", ok=False)
  m = ReliabilityModel.from_record(rec)
  assert m.of("s").successes == 1 and m.of("s").failures == 1


# -- the safety invariant ------------------------------------------------------


def test_the_controller_cannot_move_a_criterion():
  """The invariant the whole module is built around. An optimizer that can relax its own
  acceptance criteria eventually discovers that the cheapest way to satisfy a constraint
  is to delete it."""
  c = Criterion("yield_ng", ">=", 5.0, "ng", "a document", origin=Origin.TRANSCRIBED)
  ctrl = Controller(_bounds(), "yield_ng", criteria=[c])
  before = ctrl.criteria
  ctrl.propose(_obs(8))
  assert ctrl.criteria is before  # same tuple object, untouched by proposing
  assert ctrl.criteria[0] is c
  with pytest.raises(dataclasses.FrozenInstanceError):
    c.threshold = 0.0
  # And there is no setter to reach for.
  assert not [m for m in dir(ctrl) if m.startswith(("set_", "relax", "override", "update_c"))]


def test_the_controller_refuses_rather_than_proposing_a_run_it_expects_to_fail():
  impossible = Criterion(
    "yield_ng", ">=", 1e9, "ng", "a threshold nothing can reach", origin=Origin.TRANSCRIBED
  )
  ctrl = Controller(_bounds(), "yield_ng", criteria=[impossible])
  result = ctrl.propose(_obs(8))
  assert isinstance(result, Refusal)
  assert "cannot relax the criterion" in result.reason


# -- what may train ------------------------------------------------------------


def test_no_proposal_below_the_minimum_number_of_real_observations():
  result = Controller(_bounds(), "yield_ng").propose(_obs(2))
  assert isinstance(result, Refusal)
  assert result.observations == 2 and result.needed == Controller.MIN_OBSERVATIONS


def test_modeled_and_simulated_observations_do_not_train():
  """A controller that learned from its own simulator would converge confidently on the
  simulator's biases, and it would look exactly like learning."""
  for tier in (EvidenceTier.MODELED, EvidenceTier.SIMULATED):
    result = Controller(_bounds(), "yield_ng").propose(_obs(20, tier=tier))
    assert isinstance(result, Refusal), tier
    assert result.observations == 0


def test_measured_observations_do_train():
  result = Controller(_bounds(), "yield_ng").propose(_obs(8))
  assert isinstance(result, Proposal)
  assert result.trained_on == 8
  for b in _bounds():
    assert b.lo <= result.params[b.name] <= b.hi


def test_a_proposal_carries_a_calibrated_interval_once_there_is_enough_data():
  result = Controller(_bounds(), "yield_ng").propose(_obs(10))
  assert result.interval is not None
  assert "conformal interval" in result.rationale


def test_an_observations_tier_can_be_earned_instead_of_declared():
  """`Observation.earned` recomputes the tier from the instruments, and takes the weakest
  across the measurements: an observation is only as good as its worst number."""
  wc = Workcell.default()
  wc.plr_tested_root = "/nonexistent"
  good = Measurement(
    "setpoint_error_C", 0.27, "C", "odtc", "targeted_pcr_round1",
    claimed=EvidenceTier.MEASURED,
  )
  # Claims just as loudly, off an instrument whose run card has never returned a number.
  bad = Measurement(
    "library_conc", 18.4, "ng/uL", "tecan", "read_absorbance",
    claimed=EvidenceTier.MEASURED,
  )
  assert Observation.earned({}, [good], wc).tier is EvidenceTier.MEASURED
  assert Observation.earned({}, [good], wc).trains
  # One unearnable number drags the whole observation down, and out of the training set.
  assert Observation.earned({}, [good, bad], wc).tier is EvidenceTier.MODELED
  assert not Observation.earned({}, [good, bad], wc).trains


# -- bounds --------------------------------------------------------------------


def test_a_bound_without_a_source_is_refused():
  with pytest.raises(ValueError, match="no source"):
    Bound("cycles", 20, 35, "cycles", "")


def test_an_empty_bound_is_refused():
  with pytest.raises(ValueError, match="empty"):
    Bound("cycles", 35, 20, "cycles", "backwards")


def test_a_parameter_the_surrogate_has_no_bound_for_raises():
  ctrl = Controller(_bounds(), "yield_ng")
  with pytest.raises(KeyError, match="missing"):
    ctrl.surrogate._encode({"cycles": 25})
