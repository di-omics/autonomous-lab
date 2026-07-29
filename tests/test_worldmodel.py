"""Device-free tests for what a predictive world model buys, and what it provably does not.

Three claims carry this module and each has a test written to break it.

The first is the physics one: an INVISIBLE condition is not reachable by ANY approach at
ANY capability. If a lift ever appears for one, the module has started selling a model as a
sensor, and every downstream detection claim inherits that.

The second is the honesty one: removing the labeled-failure requirement introduces two
requirements that cannot be borrowed, and a monitor missing either must not report as
deployable. The natural implementation quietly passes when the fields are empty, which is
exactly the failure mode -- a monitor that fires at an unknown rate on runs that were fine.

The third is the anti-drift one: the standing list of conditions no approach moves must be
DERIVED from `vision`'s taxonomy, never restated. A hardcoded copy would look identical
today and would silently stop matching the moment a condition is reclassified, so the tests
reclassify one and check the list follows.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from autonomous_lab import build_ledger, protocols
from autonomous_lab.intelligence import BENCHMARKS, BenchmarkStatus
from autonomous_lab.qc import Basis, gate_report
from autonomous_lab.recovery import (
  FAILURE_MODES,
  Latency,
  recovery_report,
  visual_checks_that_would_help,
)
from autonomous_lab.vision import (
  CHECKS,
  CHECKS_BY_NAME,
  Observable,
  VisionCapability,
  VisionRequirement,
  VisualCheck,
)
from autonomous_lab.worldmodel import (
  DEVIATION_CLAIMS,
  REPORTED_RATES,
  Approach,
  Claim,
  DeviationEvidence,
  Introduced,
  ReportedRate,
  alarms_per_runs,
  lifts,
  unmoved,
  unmoved_and_silent,
  unsupported_claims,
  world_model_report,
  would_retire_labels,
)

WORLDMODEL_SOURCE = Path(__file__).resolve().parents[1] / "autonomous_lab" / "worldmodel.py"


def _bench_with_everything_but_labels_and_validation() -> VisionCapability:
  """A bench that could actually run a label-free monitor. No such bench exists in this repo.

  LABELS is absent because that is the requirement the approach exists to retire, and
  VALIDATION is absent because no label-free method can supply it. Everything purchasable
  is present.
  """
  return VisionCapability(
    name="hypothetical label-free bench",
    satisfied=(
      VisionRequirement.CAMERA,
      VisionRequirement.POSE,
      VisionRequirement.LIGHTING,
      VisionRequirement.MODEL,
    ),
  )


def _measured_monitor() -> DeviationEvidence:
  """A monitor this lab has actually characterised on its own nominal runs."""
  return DeviationEvidence(
    monitor="bead_pellet_deviation",
    nominal_runs=60,
    nominal_spans=("reagent lot", "time of day", "operator"),
    false_positive_rate=0.12,
    false_positive_basis=Basis.IN_HOUSE,
    dynamics_model="a pretrained latent video predictor, post-trained on this deck",
  )


def _invisible_check() -> VisualCheck:
  """A synthetic check on a condition no camera resolves.

  Synthetic because `vision` declares no INVISIBLE check today, and it should not have to
  in order for this boundary to be testable. Built from `vision`'s own dataclass so it
  cannot drift from the real ones.
  """
  return VisualCheck(
    name="enzyme_still_active",
    step_op="wgs_prep_lysis",
    observes="the enzyme in the tube has not lost activity",
    observable=Observable.INVISIBLE,
    catches="enzyme_activity_lost",
    requires=tuple(VisionRequirement),
  )


# -- the physics boundary: no approach moves it --------------------------------


def test_an_invisible_condition_is_not_lifted_by_any_approach_at_any_capability():
  """The claim the module exists to refuse. Every approach, every capability, no movement."""
  check = _invisible_check()
  capabilities = (
    VisionCapability.none(),
    _bench_with_everything_but_labels_and_validation(),
    VisionCapability(name="hypothetical", satisfied=tuple(VisionRequirement)),
  )
  for approach in Approach:
    for capability in capabilities:
      lift = lifts(check, approach, capability)
      assert not lift.moves_anything, (
        f"'{approach.value}' claims to move an INVISIBLE condition at capability "
        f"'{capability.name}'"
      )
      assert lift.removed == ()
      assert lift.introduced == ()
      assert lift.retained == check.requires


def test_an_invisible_condition_is_never_deployable_however_much_evidence_exists():
  """Even a fully characterised monitor cannot be deployed against identical photons."""
  check = _invisible_check()
  capability = VisionCapability(name="hypothetical", satisfied=tuple(VisionRequirement))
  evidence = replace(
    _measured_monitor(), miss_rate=0.01, miss_rate_status=BenchmarkStatus.MET
  )
  for approach in Approach:
    lift = lifts(check, approach, capability)
    ok, why = lift.deployable(evidence)
    assert not ok
    assert "identical frames" in why
    assert not lift.safety_device(evidence)[0]


def test_a_label_free_approach_does_move_a_visible_check_blocked_on_labels():
  """The counterpart. If nothing ever lifts, the module is refusing rather than computing."""
  check = CHECKS_BY_NAME["tips_present_after_pickup"]
  assert VisionRequirement.LABELS in check.requires
  lift = lifts(check, Approach.PREDICTIVE, _bench_with_everything_but_labels_and_validation())
  assert lift.moves_anything
  assert lift.removed == (VisionRequirement.LABELS,)
  assert VisionRequirement.LABELS not in lift.retained


def test_supervised_retires_nothing_because_labels_are_the_blocker():
  """The approach that needs labeled failures cannot be the answer to needing them."""
  assert Approach.SUPERVISED.needs_labeled_failures
  assert not Approach.RECONSTRUCTION.needs_labeled_failures
  assert not Approach.PREDICTIVE.needs_labeled_failures
  for check in CHECKS:
    lift = lifts(check, Approach.SUPERVISED, _bench_with_everything_but_labels_and_validation())
    assert not lift.moves_anything
    assert lift.introduced == ()


def test_validation_survives_every_lift():
  """The ceiling, stated as a test. No approach here retires measured sensitivity."""
  for approach in Approach:
    for check in CHECKS:
      lift = lifts(check, approach, VisionCapability.none())
      assert VisionRequirement.VALIDATION not in lift.removed
      assert lift.validation_retained


# -- the bill: what a label-free approach introduces ---------------------------


def test_only_the_dynamics_model_is_transferable_between_benches():
  assert Introduced.DYNAMICS.transferable
  assert not Introduced.NOMINAL_DATA.transferable
  assert not Introduced.FALSE_POSITIVE_RATE.transferable


def test_a_label_free_approach_is_not_deployable_without_nominal_data_or_a_measured_fpr():
  """The central refusal: an uncharacterised monitor is not a monitor."""
  check = CHECKS_BY_NAME["bead_pellet_retained_through_wash"]
  lift = lifts(check, Approach.PREDICTIVE, _bench_with_everything_but_labels_and_validation())

  ok, why = lift.deployable(DeviationEvidence.none())
  assert not ok
  assert Introduced.NOMINAL_DATA.value in why
  assert Introduced.FALSE_POSITIVE_RATE.value in why

  no_rate = replace(_measured_monitor(), false_positive_rate=None)
  ok, why = lift.deployable(no_rate)
  assert not ok
  assert Introduced.FALSE_POSITIVE_RATE.value in why

  no_nominal = replace(_measured_monitor(), nominal_runs=0, nominal_spans=())
  ok, why = lift.deployable(no_nominal)
  assert not ok
  assert Introduced.NOMINAL_DATA.value in why


def test_a_borrowed_false_positive_rate_does_not_satisfy_the_requirement():
  """Reading somebody else's benchmark number is not measuring this bench."""
  check = CHECKS_BY_NAME["bead_pellet_retained_through_wash"]
  lift = lifts(check, Approach.PREDICTIVE, _bench_with_everything_but_labels_and_validation())
  for basis in (Basis.INTUITION, Basis.VENDOR, Basis.LITERATURE):
    borrowed = replace(_measured_monitor(), false_positive_rate=0.35, false_positive_basis=basis)
    ok, why = lift.deployable(borrowed)
    assert not ok, f"a {basis.value} false-positive rate was accepted as this bench's own"
    assert Introduced.FALSE_POSITIVE_RATE.value in why


def test_nominal_runs_without_a_declared_span_of_variation_are_not_nominal_data():
  """Sixty runs on one lot under one lamp define a corner of normal, not normal."""
  evidence = replace(_measured_monitor(), nominal_spans=())
  assert not evidence.satisfies(Introduced.NOMINAL_DATA)
  assert replace(_measured_monitor(), nominal_runs=0).satisfies(Introduced.NOMINAL_DATA) is False
  assert _measured_monitor().satisfies(Introduced.NOMINAL_DATA)


def test_a_fully_characterised_monitor_on_a_real_bench_is_deployable():
  """The module must be able to say yes, or its refusals mean nothing."""
  check = CHECKS_BY_NAME["bead_pellet_retained_through_wash"]
  lift = lifts(check, Approach.PREDICTIVE, _bench_with_everything_but_labels_and_validation())
  ok, why = lift.deployable(_measured_monitor())
  assert ok, why


def test_a_deployable_monitor_is_still_not_a_safety_device():
  """The punchline. Deployable is an operator aid; a miss rate is what gates an action."""
  check = CHECKS_BY_NAME["bead_pellet_retained_through_wash"]
  lift = lifts(check, Approach.PREDICTIVE, _bench_with_everything_but_labels_and_validation())
  evidence = _measured_monitor()
  assert lift.deployable(evidence)[0]

  ok, why = lift.safety_device(evidence)
  assert not ok
  assert BenchmarkStatus.UNMEASURED.value in why
  assert VisionRequirement.VALIDATION.value in why

  measured = replace(evidence, miss_rate=0.04, miss_rate_status=BenchmarkStatus.MET)
  assert lift.safety_device(measured)[0]


def test_a_retired_requirement_stops_blocking_but_validation_does_not():
  """The bare workcell shows both halves at once: LABELS leaves the list, VALIDATION stays."""
  check = CHECKS_BY_NAME["bead_pellet_retained_through_wash"]
  lift = lifts(check, Approach.PREDICTIVE, VisionCapability.none())
  assert VisionRequirement.LABELS not in lift.blocked_on
  assert VisionRequirement.CAMERA in lift.blocked_on
  assert VisionRequirement.VALIDATION in lift.blocked_on
  assert VisionRequirement.VALIDATION not in lift.operational_blockers
  assert VisionRequirement.CAMERA in lift.operational_blockers


def test_a_missing_camera_is_reported_before_the_label_free_bill():
  """A bench with no camera has a hardware problem, not a calibration problem."""
  check = CHECKS_BY_NAME["bead_pellet_retained_through_wash"]
  lift = lifts(check, Approach.PREDICTIVE, VisionCapability.none())
  ok, why = lift.deployable(_measured_monitor())
  assert not ok
  assert VisionRequirement.CAMERA.value in why


def test_a_monitor_this_workcell_cannot_run_is_not_deployable():
  """No camera is mounted anywhere in this repo, so every real answer here is no."""
  report = world_model_report(Approach.PREDICTIVE, VisionCapability.none())
  assert report.counts(_measured_monitor())["deployable"] == 0
  assert report.counts(_measured_monitor())["safety_devices"] == 0
  assert report.moved(), "a predictive approach should retire labels on the possible checks"


# -- the standing list: derived from vision, never restated --------------------


def test_unmoved_matches_an_independent_derivation_from_visions_taxonomy():
  """Recompute the list here from the owning modules and require exact agreement."""
  expected = set()
  for failure in FAILURE_MODES:
    if not failure.observable.reachable_by_vision:
      expected.add(failure.name)
  for benchmark in BENCHMARKS:
    if not benchmark.observable.reachable_by_vision:
      expected.add(benchmark.name)
  for check in CHECKS:
    if not check.observable.reachable_by_vision:
      expected.add(check.name)

  assert {row.name for row in unmoved()} == expected
  assert expected, "the taxonomy declares no INVISIBLE condition; this test would be vacuous"


def test_every_unmoved_row_is_unreachable_by_vision_and_says_why():
  for row in unmoved():
    assert not row.reachable_by_vision
    assert row.observable is Observable.INVISIBLE
    assert row.name in row.why()
    assert row.owner in ("recovery", "intelligence", "vision")
    assert row.what, f"'{row.name}' carries no description from its owning module"


def test_unmoved_carries_the_owning_modules_own_words():
  """A second copy of a description is a copy that will eventually disagree with its source."""
  descriptions = {f.name: f.description for f in FAILURE_MODES}
  descriptions.update({b.name: b.target for b in BENCHMARKS})
  descriptions.update({c.name: c.observes for c in CHECKS})
  for row in unmoved():
    assert row.what == descriptions[row.name]


def test_unmoved_follows_a_reclassification_in_recovery(monkeypatch):
  """Proof of derivation: reclassify a condition and the list must move with it.

  A hardcoded list passes every test above and fails this one, which is the only reason
  this test exists.
  """
  invisible = next(f for f in FAILURE_MODES if f.observable is Observable.INVISIBLE)
  assert invisible.name in {row.name for row in unmoved()}

  reclassified = tuple(
    replace(f, observable=Observable.VISIBLE) if f.name == invisible.name else f
    for f in FAILURE_MODES
  )
  monkeypatch.setattr("autonomous_lab.worldmodel.FAILURE_MODES", reclassified)
  assert invisible.name not in {row.name for row in unmoved()}


def test_unmoved_follows_a_reclassification_in_visions_own_checks(monkeypatch):
  """The taxonomy under test is `vision`'s. Change a check there and the list must follow."""
  visible_check = next(c for c in CHECKS if c.observable is Observable.VISIBLE)
  assert visible_check.name not in {row.name for row in unmoved()}

  reclassified = tuple(
    replace(c, observable=Observable.INVISIBLE) if c.name == visible_check.name else c
    for c in CHECKS
  )
  monkeypatch.setattr("autonomous_lab.worldmodel.CHECKS", reclassified)
  rows = {row.name: row for row in unmoved()}
  assert visible_check.name in rows
  assert rows[visible_check.name].owner == "vision"

  # And the lift for that same check must now refuse, from the same taxonomy change.
  now_invisible = next(c for c in reclassified if c.name == visible_check.name)
  assert not lifts(now_invisible, Approach.PREDICTIVE).moves_anything


def test_no_unmoved_condition_is_named_as_a_literal_in_the_module():
  """Belt and braces on the anti-drift claim: the names are computed, not typed.

  Reads the module's own source and requires that no INVISIBLE condition's name appears in
  it. A restated list is caught here even if somebody also rewires the derivation to match.
  """
  source = WORLDMODEL_SOURCE.read_text(encoding="ascii")
  for row in unmoved():
    assert row.name not in source, (
      f"'{row.name}' is written into worldmodel.py; the standing list must be derived from "
      f"vision's taxonomy, not restated"
    )


def test_unmoved_and_silent_reads_silence_from_recovery():
  """The expensive intersection: no deviation signal reaches them and nothing else catches them."""
  protocol = protocols.get("single_cell_genomics")
  ledger = build_ledger(protocol)
  gates = gate_report(protocol.name, ledger)
  report = recovery_report(protocol, gates, VisionCapability.none())

  silent = {row.failure.name for row in report.silent()}
  rows = unmoved_and_silent(report)
  assert rows, "this protocol should have invisible failures nothing would notice"
  for row in rows:
    assert row.name in silent
    assert not row.reachable_by_vision


def test_unmoved_does_not_claim_that_nothing_catches_the_condition():
  """A loud instrument error is invisible to a camera and still caught. The list must allow it."""
  names = {row.name for row in unmoved()}
  loud = {
    f.name
    for f in FAILURE_MODES
    if f.observable is Observable.INVISIBLE and f.declared_latency is Latency.IMMEDIATE
  }
  assert loud, "the failure model should contain an invisible failure the instrument raises on"
  assert loud <= names


# -- what a deviation signal says ----------------------------------------------


def test_only_the_bare_deviation_claim_is_supported():
  assert Claim.NOT_AS_EXPECTED.supported
  assert not Claim.WHAT_WENT_WRONG.supported
  assert not Claim.WHETHER_IT_MATTERS.supported

  supported = [row for row in DEVIATION_CLAIMS if row.supported]
  assert len(supported) == 1
  assert supported[0].claim is Claim.NOT_AS_EXPECTED
  assert len(unsupported_claims()) == 2
  for row in DEVIATION_CLAIMS:
    assert row.why, f"'{row.claim.value}' states no reason"


def test_every_claim_in_the_enum_has_a_declared_statement():
  assert {row.claim for row in DEVIATION_CLAIMS} == set(Claim)


# -- the reported ceiling, and the refusal to project from it ------------------


def test_no_reported_rate_describes_this_bench():
  assert REPORTED_RATES
  for rate in REPORTED_RATES:
    assert not rate.describes_this_bench
    assert rate.basis is Basis.LITERATURE
    assert rate.source and rate.setting


def test_reported_rates_are_rates():
  with pytest.raises(ValueError):
    ReportedRate(source="x", setting="y", true_positive_rate=1.4, false_positive_rate=0.1)
  with pytest.raises(ValueError):
    ReportedRate(source="x", setting="y", true_positive_rate=0.9, false_positive_rate=-0.1)


def test_the_reported_ceiling_keeps_the_headline_trade_visible():
  """Whatever else changes, the table must keep showing what a high catch rate costs.

  The published label-free operating point closest to useful flags roughly a third of
  SUCCESSFUL runs. If that row is ever dropped, the table starts flattering the method.
  """
  assert any(
    r.true_positive_rate >= 0.91 and r.false_positive_rate >= 0.35 for r in REPORTED_RATES
  )
  assert all(r.false_positive_rate > 0.0 for r in REPORTED_RATES)


def test_alarm_projection_refuses_on_a_borrowed_rate():
  """Multiplying somebody else's benchmark rate by this lab's run count has no measured joint."""
  assert alarms_per_runs(DeviationEvidence.none(), 100) is None
  borrowed = replace(
    _measured_monitor(), false_positive_rate=0.35, false_positive_basis=Basis.LITERATURE
  )
  assert alarms_per_runs(borrowed, 100) is None


def test_alarm_projection_computes_on_this_benchs_own_rate():
  assert alarms_per_runs(_measured_monitor(), 100) == pytest.approx(12.0)
  assert alarms_per_runs(_measured_monitor(), 0) == pytest.approx(0.0)
  with pytest.raises(ValueError):
    alarms_per_runs(_measured_monitor(), -1)


def test_evidence_rejects_impossible_rates():
  with pytest.raises(ValueError):
    DeviationEvidence(monitor="bad", false_positive_rate=1.5)
  with pytest.raises(ValueError):
    DeviationEvidence(monitor="bad", miss_rate=-0.1)
  with pytest.raises(ValueError):
    DeviationEvidence(monitor="bad", nominal_runs=-1)


# -- composition with the sibling reports --------------------------------------


def test_the_shopping_list_follows_recoverys_ranking():
  """Which checks are worth wanting is `recovery`'s question; this module only prices them."""
  protocol = protocols.get("single_cell_genomics")
  ledger = build_ledger(protocol)
  gates = gate_report(protocol.name, ledger)
  report = recovery_report(protocol, gates, VisionCapability.none())

  wanted = visual_checks_that_would_help(report)
  priced = would_retire_labels(report, Approach.PREDICTIVE, VisionCapability.none())
  assert [lift.check.name for lift in priced] == list(wanted)
  for lift in priced:
    assert lift.moves_anything
    assert lift.check.possible


def test_the_report_and_the_module_agree_about_the_standing_list():
  report = world_model_report(Approach.RECONSTRUCTION, VisionCapability.none())
  assert report.unmoved() == unmoved()
  assert report.counts()["unmoved_conditions"] == len(unmoved())
  assert report.counts()["checks"] == len(CHECKS)


def test_a_predictive_approach_introduces_a_dynamics_model_and_reconstruction_does_not():
  check = CHECKS_BY_NAME["tips_present_after_pickup"]
  predictive = lifts(check, Approach.PREDICTIVE, VisionCapability.none())
  reconstruction = lifts(check, Approach.RECONSTRUCTION, VisionCapability.none())
  assert Introduced.DYNAMICS in predictive.introduced
  assert Introduced.DYNAMICS not in reconstruction.introduced
  assert predictive.untransferable == reconstruction.untransferable
  assert set(predictive.untransferable) == {
    Introduced.NOMINAL_DATA,
    Introduced.FALSE_POSITIVE_RATE,
  }
