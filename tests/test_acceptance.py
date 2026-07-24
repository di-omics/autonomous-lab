"""Device-free tests for acceptance criteria.

The tests that matter try to make a gate pass something it should not: gate a run on an
invented threshold, promote a number the instrument never produced, or return PASS from a
rubric standing in front of a reader that has never read a plate.
"""

from __future__ import annotations

import json
import random
import statistics

import pytest

from autonomous_lab import criteria
from autonomous_lab.acceptance import (
  ConformalBand,
  Criterion,
  EvidenceTier,
  Gate,
  Judgement,
  Measurement,
  Origin,
  UnsourcedCriterion,
  earned_tier,
  promote,
  triage,
)
from autonomous_lab.workcell import Workcell


def _wired():
  wc = Workcell.default()
  wc.plr_tested_root = "/nonexistent/plr-tested"  # wired, not checked here; doctor does that
  return wc


def _crit(**kw):
  base = dict(
    metric="m", comparator=">=", threshold=1.0, units="ng", source="a real document",
    origin=Origin.TRANSCRIBED,
  )
  base.update(kw)
  return Criterion(**base)


# -- criteria refuse to be invented -------------------------------------------


def test_a_criterion_without_a_source_cannot_be_constructed():
  with pytest.raises(UnsourcedCriterion, match="no source"):
    _crit(source="")


def test_whitespace_is_not_a_source():
  with pytest.raises(UnsourcedCriterion):
    _crit(source="   ")


def test_an_unknown_comparator_raises():
  with pytest.raises(ValueError, match="unknown comparator"):
    _crit(comparator="~=")


def test_only_a_transcribed_threshold_is_not_provisional():
  assert not _crit(origin=Origin.TRANSCRIBED).provisional
  for origin in (Origin.TUNABLE, Origin.CALIBRATE, Origin.TODO):
    assert _crit(origin=origin).provisional


def test_calibrate_and_todo_block_a_hardware_run_and_the_others_do_not():
  assert Origin.CALIBRATE.blocking and Origin.TODO.blocking
  assert not Origin.TRANSCRIBED.blocking and not Origin.TUNABLE.blocking


# -- evidence tiers are earned ------------------------------------------------


def test_a_claim_on_a_broken_instrument_is_downgraded():
  """The Tecan's absorbance run card exists and fails. A number attributed to it did not
  come from it, whatever the caller says."""
  m = Measurement("c", 18.4, "ng/uL", "tecan", "read_absorbance", claimed=EvidenceTier.MEASURED)
  tier, why = earned_tier(m, _wired())
  assert tier is EvidenceTier.MODELED
  assert "FAILED" in why


def test_a_dry_only_run_card_caps_at_simulated():
  m = Measurement(
    "c", 1.0, "x", "star", "pcr_enrichment_round1_cleanup", claimed=EvidenceTier.VALIDATED
  )
  assert earned_tier(m, _wired())[0] is EvidenceTier.SIMULATED


def test_a_validated_run_card_reaches_measured_but_not_validated():
  """VALIDATED means the physical gates also passed, which is not knowable at this point."""
  m = Measurement(
    "c", 0.4, "profile_units", "odtc", "pcr_enrichment_round1",
    claimed=EvidenceTier.VALIDATED,
  )
  assert earned_tier(m, _wired())[0] is EvidenceTier.MEASURED


def test_an_unwired_workcell_cannot_reach_measured():
  m = Measurement(
    "c", 0.4, "profile_units", "odtc", "pcr_enrichment_round1",
    claimed=EvidenceTier.MEASURED,
  )
  assert earned_tier(m, Workcell.default())[0] is EvidenceTier.SIMULATED


def test_underclaiming_is_always_allowed():
  m = Measurement(
    "c", 0.4, "profile_units", "odtc", "pcr_enrichment_round1",
    claimed=EvidenceTier.MODELED,
  )
  assert earned_tier(m, _wired())[0] is EvidenceTier.MODELED


def test_promotion_needs_passed_gates_and_a_measured_starting_point():
  assert promote(EvidenceTier.MEASURED, True) is EvidenceTier.VALIDATED
  assert promote(EvidenceTier.MEASURED, False) is EvidenceTier.MEASURED
  # Nothing promotes out of simulated on the strength of a passing gate.
  assert promote(EvidenceTier.SIMULATED, True) is EvidenceTier.SIMULATED


# -- gates ---------------------------------------------------------------------


def test_a_gate_in_front_of_a_broken_reader_is_unmeasurable_even_when_handed_a_number():
  """The flagship refusal. A value that arrives from an instrument that cannot produce it
  is evidence about the caller, not about the sample."""
  gate = criteria.get("loading_window")
  result = gate.evaluate(
    [Measurement("loading_concentration", 0.5, "profile_units", "tecan", "read_absorbance")],
    _wired(),
  )
  assert result.judgement is Judgement.UNMEASURABLE
  assert not result.proceed


def test_an_unpinned_threshold_escalates_even_when_the_value_clears_it():
  gate = Gate(
    name="g",
    guards="x",
    produced_by=("odtc", "pcr_enrichment_round1"),
    criteria=(_crit(metric="v", comparator=">=", threshold=1.0, origin=Origin.TODO,
                    source="nobody has decided this"),),
  )
  m = Measurement("v", 2.0, "x", "odtc", "pcr_enrichment_round1")
  assert gate.evaluate([m], _wired()).judgement is Judgement.ESCALATE


def test_a_rubric_with_an_unpinned_threshold_is_not_ready_for_hardware():
  ready, reasons = criteria.get("thermal_performance").ready_for_hardware()
  assert not ready and any("todo" in r for r in reasons)


def test_a_missing_measurement_is_unmeasurable_not_a_pass():
  """The single most dangerous possible bug: a gate that passes because it found no
  contradicting data."""
  gate = Gate(
    name="g", guards="x", produced_by=("odtc", "pcr_enrichment_round1"), criteria=(_crit(),)
  )
  assert gate.evaluate([], _wired()).judgement is Judgement.UNMEASURABLE


def test_refusals_dominate_and_unmeasurable_dominates_escalate():
  gate = Gate(
    name="g",
    guards="x",
    produced_by=("odtc", "pcr_enrichment_round1"),
    criteria=(
      _crit(metric="present", threshold=0.0),
      _crit(metric="absent", threshold=0.0),
    ),
  )
  m = Measurement("present", 5.0, "ng", "odtc", "pcr_enrichment_round1")
  assert gate.evaluate([m], _wired()).judgement is Judgement.UNMEASURABLE


def test_an_undecoded_command_cannot_produce_a_number():
  """A well-sourced rubric in front of an instrument with no decoded read is not closer to
  running than an unsourced one."""
  can, why = criteria.get("run_control_quality").measurable(_wired())
  assert not can and "no path to this number exists" in why


def test_reference_gates_have_no_embedded_method_thresholds():
  all_criteria = [
    criterion
    for gate in criteria.REFERENCE_GATES.values()
    for criterion in gate.criteria
  ]
  assert all_criteria
  assert all(criterion.threshold is None for criterion in all_criteria)
  assert all(criterion.origin is Origin.TODO for criterion in all_criteria)


def test_an_operator_profile_populates_only_its_cited_thresholds():
  key = "thermal_performance.maximum_setpoint_error"
  profile = {
    key: criteria.ProfileValue(
      threshold=0.5,
      source="synthetic qualification record section 2",
      units="synthetic units",
      origin=Origin.TRANSCRIBED,
    )
  }
  gate = criteria.get("thermal_performance", criteria.build_reference_gates(profile))
  configured = [c for c in gate.criteria if c.metric == "setpoint_error"][0]
  remaining = [c for c in gate.criteria if c.metric != "setpoint_error"][0]
  assert configured.threshold == 0.5
  assert configured.source == "synthetic qualification record section 2"
  assert remaining.threshold is None
  assert not gate.ready_for_hardware()[0]


def test_an_operator_profile_round_trips_from_json(tmp_path):
  key = "loading_window.minimum"
  path = tmp_path / "evidence-profile.json"
  path.write_text(
    json.dumps(
      {
        key: {
          "threshold": 0.25,
          "units": "synthetic units",
          "source": "synthetic qualification record section 4",
          "origin": "transcribed",
        }
      }
    ),
    encoding="utf-8",
  )
  profile = criteria.load_profile(str(path))
  assert profile[key].threshold == 0.25
  assert profile[key].units == "synthetic units"


def test_an_operator_profile_rejects_unknown_fields(tmp_path):
  path = tmp_path / "evidence-profile.json"
  path.write_text(
    json.dumps(
      {
        "unknown.limit": {
          "threshold": 1.0,
          "units": "x",
          "source": "synthetic source",
        }
      }
    ),
    encoding="utf-8",
  )
  with pytest.raises(ValueError, match="unknown evidence-profile"):
    criteria.load_profile(str(path))


def test_reference_steps_resolve_to_the_generic_evidence_gates():
  assert [g.name for g in criteria.gates_for("wgs_prep_lysis")] == [
    "liquid_handling_qualification"
  ]
  assert [g.name for g in criteria.gates_for("pcr_enrichment_round1")] == [
    "thermal_performance"
  ]
  assert [g.name for g in criteria.gates_for("pcr_enrichment_round1_cleanup")] == [
    "preparation_output"
  ]


# -- uncertainty ---------------------------------------------------------------


def test_triage_decides_only_when_the_whole_interval_is_on_one_side():
  c = _crit(comparator=">=", threshold=10.0)
  assert triage(c, 11.0, 12.0) is Judgement.PASS
  assert triage(c, 1.0, 2.0) is Judgement.FAIL
  assert triage(c, 9.0, 11.0) is Judgement.ESCALATE


def test_a_band_needs_calibration_points():
  with pytest.raises(ValueError, match="at least 2"):
    ConformalBand().calibrate([1.0], [1.0], [1.0])


def test_an_uncalibrated_band_refuses_to_produce_an_interval():
  with pytest.raises(RuntimeError, match="not calibrated"):
    ConformalBand().interval(1.0, 1.0)


def test_the_coverage_guarantee_actually_holds():
  """The claim worth checking empirically rather than asserting in a docstring.

  Deliberately hostile setup: the spread handed to the band is a constant 1.0 while the
  true noise grows with the input. Conformal calibration is supposed to absorb exactly
  that miscalibration, so coverage must still clear 1 - alpha.
  """
  rng = random.Random(11)

  def draw():
    x = rng.uniform(0, 10)
    return x + rng.gauss(0, 0.5 + 0.3 * x), x, 1.0

  def trial(n_cal, alpha):
    cal = [draw() for _ in range(n_cal)]
    band = ConformalBand(alpha=alpha)
    band.calibrate([c[0] for c in cal], [c[1] for c in cal], [c[2] for c in cal])
    test = [draw() for _ in range(400)]
    return band.coverage([t[0] for t in test], [t[1] for t in test], [t[2] for t in test])

  for alpha in (0.1, 0.2):
    for n_cal in (10, 40):
      mean = statistics.mean(trial(n_cal, alpha) for _ in range(120))
      assert mean >= 1 - alpha, f"undercovered at alpha={alpha}, n_cal={n_cal}: {mean:.3f}"


def test_a_point_comparison_admits_it_carries_no_guarantee():
  gate = Gate(
    name="g", guards="x", produced_by=("odtc", "pcr_enrichment_round1"), criteria=(_crit(),)
  )
  m = Measurement("m", 5.0, "ng", "odtc", "pcr_enrichment_round1")
  result = gate.evaluate([m], _wired())
  assert "no coverage guarantee" in result.results[0].reason
