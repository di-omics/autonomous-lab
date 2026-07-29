"""Device-free tests for the imitation layer: capture, coupling, and trust.

The tests that matter here try to get a policy reported as trainable, equivalent to
teleoperation, or trusted with material when it is none of those, and the three richest
sources of that are the three the module was written against.

The first is the capture that looks like a demonstration and is not. A video with no action
stream. A retargeting pipeline declared but never measured, which reads in a manifest exactly
like one that was. A capture with nothing set at all, where every default that means "not
checked" has to keep meaning that rather than quietly meaning "fine".

The second is the fixture. A policy learned against a specific printed part, and the part is
the easiest thing in the workcell to change without telling anybody: reprint it with a tuned
clearance and every demonstration behind the policy describes a world that no longer exists.
A revision bump must decouple. A matching revision string on two parts nobody measured must
not couple, because a revision names a model file and `printed` refuses to estimate shrinkage
at all.

The third is the success rate that is not one. Scored on the conditions the demonstrations
came from. Scored by the policy's own confidence. Computed off five trials, where one trial
is twenty percentage points. Each of those has to come back refused rather than reported with
a caveat beside it, because the number is what gets quoted and the caveat is not.

The interval arithmetic is checked against published Clopper-Pearson values, since it is the
one thing in the module that can be wrong silently.
"""

from __future__ import annotations

import pathlib

import pytest

from autonomous_lab import imitation
from autonomous_lab.imitation import (
  Interlock,
  DETERMINANTS,
  INTERLOCK_NOTE,
  MAX_TRIAL_WEIGHT_PP,
  MIN_HELDOUT_TRIALS,
  MODALITY_EVIDENCE,
  NOT_ESTIMATED,
  PUBLISHED_COUNTS,
  Capture,
  Coupling,
  Evaluation,
  FixtureCoupling,
  Modality,
  Policy,
  Retargeting,
  SuccessCriterion,
  Trainable,
  Trust,
  demonstrations_needed,
  equivalent_to_teleop,
  fixture_coupled,
  may_run,
  published_span,
  refusals,
  success_interval,
  success_rate,
  summary,
  trusted_with_material,
  usable_for_training,
)
from autonomous_lab.printed import (
  Basis,
  CriticalDimension,
  DimensionState,
  Fixture,
  MATERIALS,
)


def _measured_part(name="nest", value=128.4):
  return Fixture(
    name=name,
    material=MATERIALS["pla_fdm"],
    dimensions=(
      CriticalDimension(
        name="pocket_length",
        nominal_mm=128.5,
        state=DimensionState.MEASURED,
        measured_mm=value,
        measured_after_processing=True,
        instrument="digital caliper, three positions",
      ),
    ),
  )


def _designed_part(name="nest"):
  return Fixture(
    name=name,
    material=MATERIALS["pla_fdm"],
    dimensions=(CriticalDimension(name="pocket_length", nominal_mm=128.5),),
  )


def _coupling(revision="rev_a", measured=True, fixture_name="plate_nest"):
  return FixtureCoupling(
    fixture_name=fixture_name,
    revision=revision,
    fixture=_measured_part() if measured else _designed_part(),
    constrains=("x", "y", "yaw"),
  )


def _teleop_capture(**kw):
  """A capture with everything a lab controls already done, so a test can vary one thing."""
  defaults = dict(
    name="teleop_session",
    modality=Modality.TELEOPERATION,
    episodes=50,
    timestamps_synchronized=True,
    camera_calibrated=True,
    gripper_state_recorded=True,
    coupling=_coupling(),
  )
  defaults.update(kw)
  return Capture(**defaults)


def _validated_retargeting():
  return Retargeting(
    method="hand pose estimation, then ICP against the depth cloud",
    depth_or_multiview=True,
    error_measured_mm=9.4,
    basis=Basis.IN_HOUSE,
  )


def _video_capture(modality=Modality.INSTRUMENTED_HUMAN_VIDEO, retargeting=None, **kw):
  defaults = dict(
    name="video_session",
    modality=modality,
    episodes=300,
    retargeting=retargeting if retargeting is not None else _validated_retargeting(),
    timestamps_synchronized=True,
    camera_calibrated=True,
    gripper_state_recorded=True,
    coupling=_coupling(),
  )
  defaults.update(kw)
  return Capture(**defaults)


def _measured_evaluation(successes=17, trials=20, **kw):
  defaults = dict(
    trials=trials,
    successes=successes,
    held_out=True,
    criterion=SuccessCriterion.EXTERNAL_MEASUREMENT,
    blinded=True,
  )
  defaults.update(kw)
  return Evaluation(**defaults)


def _policy(**kw):
  defaults = dict(
    name="pick_and_nest",
    method="action chunking",
    captures=(_teleop_capture(),),
    evaluation=_measured_evaluation(),
  )
  defaults.update(kw)
  return Policy(**defaults)


# -- vacuous passes -----------------------------------------------------------------


def _interlock(**kw):
  """A complete interlock. Every field must be set, so the helper states them explicitly
  rather than relying on defaults that would quietly re-open the hole this leg closed."""
  base = dict(
    workspace_bounded=True,
    speed_bounded=True,
    force_bounded=True,
    enforced_by="controller soft limits and a hardware E-stop",
    miss_rate_measured=True,
  )
  base.update(kw)
  return Interlock(**base)


def test_a_capture_with_nothing_set_is_not_usable():
  """The single most important test in the file.

  A dataclass of booleans and empty defaults is the easiest thing here to get wrong, because
  every default that reads as True or as 'nothing to check' turns a recording nobody looked
  at into a training set. A bare capture has to come back refused, and it has to name every
  one of the things it lacks rather than only the first.
  """
  standing = usable_for_training(Capture())
  assert not standing.usable
  assert standing.verdict is not Trainable.USABLE
  for reason in (
    Trainable.MODALITY_UNDECLARED,
    Trainable.NO_EPISODES,
    Trainable.NO_ACTION_STREAM,
    Trainable.TIMESTAMPS_UNSYNCHRONIZED,
    Trainable.CAMERA_UNCALIBRATED,
    Trainable.GRIPPER_STATE_MISSING,
  ):
    assert reason in standing.reasons()


def test_a_policy_with_no_captures_does_not_read_as_trained_on_flawless_data():
  """`all()` over an empty tuple is True; a policy nobody fed must not inherit that."""
  bare = Policy()
  assert not bare.trainable()
  assert bare.episodes() == 0
  assert bare.training_coupling() is None
  assert not may_run(bare, _coupling()).permitted


def test_a_bare_capture_is_not_equivalent_to_anything():
  ok, why = equivalent_to_teleop(Capture())
  assert not ok
  assert "no modality is declared" in why


# -- a video is not a demonstration --------------------------------------------------


def test_a_capture_with_no_action_stream_is_refused():
  """Pixels are the observation half. A capture that carries no actions trains nothing."""
  pixels_only = _video_capture(
    modality=Modality.MONOCULAR_HUMAN_VIDEO, retargeting=Retargeting()
  )
  assert not pixels_only.carries_actions

  standing = usable_for_training(pixels_only)
  assert not standing.usable
  assert Trainable.NO_ACTION_STREAM in standing.reasons()
  detail = standing.details()[standing.reasons().index(Trainable.NO_ACTION_STREAM)]
  assert "no action stream" in detail
  assert "injective" in detail  # the case where the action is unrecoverable in principle
  assert Trainable.NO_ACTION_STREAM.needs_recapture


def test_retargeted_video_does_not_report_as_equivalent_to_teleop():
  """The refusal that keeps an exchange rate from becoming a silent multiplier.

  It has to hold for the BEST version of the video pipeline, not only the worst: depth,
  multi-view, a measured retargeting error, in-house basis. That capture is usable for
  training and is still not a teleoperated episode.
  """
  best_video = _video_capture()
  assert usable_for_training(best_video).usable

  ok, why = equivalent_to_teleop(best_video)
  assert not ok
  assert "no measured action stream" in why
  assert "a measured estimator is still an estimator" in why

  worst_video = _video_capture(
    modality=Modality.MONOCULAR_HUMAN_VIDEO,
    retargeting=Retargeting(method="monocular hand pose", depth_or_multiview=False),
  )
  assert not equivalent_to_teleop(worst_video)[0]


def test_a_handheld_gripper_is_not_teleoperation_either():
  """The nearest miss in the enum, and the one most likely to be filed as equivalent."""
  assert Modality.HANDHELD_GRIPPER.measured_action_stream
  assert not Modality.HANDHELD_GRIPPER.on_the_robots_own_kinematics

  ok, why = equivalent_to_teleop(_teleop_capture(modality=Modality.HANDHELD_GRIPPER))
  assert not ok
  assert "proprioception" in why


def test_only_captures_on_the_robots_own_kinematics_report_equivalent():
  for modality in Modality:
    ok, _ = equivalent_to_teleop(_teleop_capture(modality=modality))
    assert ok is modality.on_the_robots_own_kinematics
  assert sum(1 for m in Modality if m.on_the_robots_own_kinematics) == 2
  assert sum(1 for m in Modality if m.measured_action_stream) == 3


def test_a_declared_retargeting_that_nobody_measured_is_refused():
  """A pipeline that exists is not a pipeline that was validated."""
  unmeasured = _video_capture(
    retargeting=Retargeting(method="hand pose then wrist mapping", depth_or_multiview=True)
  )
  standing = usable_for_training(unmeasured)
  assert not standing.usable
  assert Trainable.RETARGETING_UNVALIDATED in standing.reasons()
  assert not Trainable.RETARGETING_UNVALIDATED.needs_recapture  # measure it; do not recollect


def test_somebody_elses_retargeting_error_does_not_validate_this_one():
  borrowed = Retargeting(
    method="published pipeline",
    depth_or_multiview=True,
    error_measured_mm=9.4,
    basis=Basis.LITERATURE,
  )
  assert not borrowed.validated
  standing = usable_for_training(_video_capture(retargeting=borrowed))
  assert Trainable.RETARGETING_UNVALIDATED in standing.reasons()


def test_a_capture_cannot_both_measure_and_estimate_its_actions():
  with pytest.raises(ValueError) as excinfo:
    Capture(
      name="incoherent",
      modality=Modality.TELEOPERATION,
      episodes=10,
      retargeting=_validated_retargeting(),
    )
  assert "cannot both" in str(excinfo.value)


def test_each_refusal_names_what_specifically_is_missing():
  """One field off at a time, so no refusal can be hiding behind another."""
  cases = {
    "timestamps_synchronized": (Trainable.TIMESTAMPS_UNSYNCHRONIZED, "common clock"),
    "camera_calibrated": (Trainable.CAMERA_UNCALIBRATED, "camera pose"),
    "gripper_state_recorded": (Trainable.GRIPPER_STATE_MISSING, "gripper state"),
  }
  for field_name, (reason, phrase) in cases.items():
    standing = usable_for_training(_teleop_capture(**{field_name: False}))
    assert standing.reasons() == (reason,), field_name
    assert phrase in standing.details()[0]


def test_the_camera_refusal_resolves_the_requirement_vision_already_owns():
  standing = usable_for_training(_teleop_capture(camera_calibrated=False))
  assert "pose" in standing.details()[0]


def test_a_fully_specified_teleop_capture_is_usable_and_claims_nothing_more():
  standing = usable_for_training(_teleop_capture())
  assert standing.usable
  assert standing.verdict is Trainable.USABLE
  assert "not a trained policy" in standing.reason


def test_every_modality_carries_its_evidence():
  assert set(MODALITY_EVIDENCE) == set(Modality)
  assert all(len(v) > 100 for v in MODALITY_EVIDENCE.values())


# -- the fixture is part of the policy's world ----------------------------------------


def test_a_fixture_revision_change_decouples_an_existing_policy():
  """The finding the module exists for: nothing in the run reports this on its own."""
  policy = _policy()
  check = fixture_coupled(policy, _coupling(revision="rev_b"))
  assert not check.holds
  assert check.state is Coupling.REVISED
  assert "rev_b" in check.reason
  assert "shrinkage" in check.reason


def test_a_matching_revision_on_two_parts_nobody_measured_does_not_couple():
  """A revision names a model file. The policy was trained against a part."""
  policy = _policy(captures=(_teleop_capture(coupling=_coupling(measured=False)),))
  check = fixture_coupled(policy, _coupling(measured=False))
  assert not check.holds
  assert check.state is Coupling.UNVERIFIED
  assert "fact about a model file" in check.reason


def test_a_measured_pair_at_the_same_revision_couples():
  check = fixture_coupled(_policy(), _coupling())
  assert check.holds
  assert check.state is Coupling.COUPLED
  assert "says nothing about whether it learned it" in check.reason


def test_a_different_fixture_is_not_a_degraded_coupling():
  check = fixture_coupled(_policy(), _coupling(fixture_name="tube_rack"))
  assert check.state is Coupling.DIFFERENT_FIXTURE


def test_captures_against_two_revisions_couple_to_neither():
  """The same refusal `teaching` makes about pooling two sets of conditions into one range."""
  policy = _policy(
    captures=(
      _teleop_capture(name="monday", coupling=_coupling(revision="rev_a")),
      _teleop_capture(name="tuesday", coupling=_coupling(revision="rev_b")),
    )
  )
  assert policy.training_coupling() is None
  assert len(policy.distinct_couplings()) == 2
  check = fixture_coupled(policy, _coupling(revision="rev_a"))
  assert not check.holds
  assert check.state is Coupling.MIXED


def test_a_policy_that_names_no_fixture_cannot_be_shown_to_have_changed_one():
  policy = _policy(captures=(_teleop_capture(coupling=None),))
  check = fixture_coupled(policy, _coupling())
  assert check.state is Coupling.UNIDENTIFIED
  assert "cannot be reproduced" in check.reason


def test_a_proposed_run_naming_no_fixture_does_not_couple():
  assert fixture_coupled(_policy(), None).state is Coupling.UNIDENTIFIED
  unnamed = FixtureCoupling(fixture_name="plate_nest")  # no revision
  assert not unnamed.identified
  assert fixture_coupled(_policy(), unnamed).state is Coupling.UNIDENTIFIED


def test_coupling_anchors_on_printed_rather_than_on_a_boolean_here():
  """The measured-ness of the part is `printed`'s question and is resolved there."""
  anchored = _coupling()
  assert anchored.anchored
  assert not _coupling(measured=False).anchored
  assert not FixtureCoupling(fixture_name="a", revision="b").anchored
  # A fixture that declares no dimensions at all must not read as measured either.
  bare = FixtureCoupling(fixture_name="a", revision="b", fixture=Fixture())
  assert not bare.anchored


def test_only_one_coupling_state_holds():
  assert sum(1 for c in Coupling if c.holds) == 1


# -- a policy is untrusted until measured ----------------------------------------------


def test_a_training_set_success_rate_is_not_a_success_rate():
  """The number that gets quoted, refused at both layers that could report it."""
  policy = _policy(evaluation=_measured_evaluation(successes=48, trials=50, held_out=False))
  report = success_rate(policy.evaluation)
  assert not report.stated
  assert report.point is None
  assert "not a success rate" in report.reason

  standing = trusted_with_material(policy)
  assert not standing.trusted
  assert standing.verdict is Trust.TRAINING_SET_ONLY


def test_a_policy_scored_by_its_own_confidence_is_not_trusted():
  for criterion in (SuccessCriterion.POLICY_CONFIDENCE, SuccessCriterion.TRAINING_LOSS):
    policy = _policy(
      evaluation=_measured_evaluation(successes=95, trials=100, criterion=criterion)
    )
    standing = trusted_with_material(policy)
    assert not standing.trusted
    assert standing.verdict is Trust.SELF_SCORED
    assert standing.rate.point is None
    assert not criterion.external


def test_a_thousand_self_scored_trials_do_not_substitute_for_an_external_criterion():
  policy = _policy(
    evaluation=_measured_evaluation(
      successes=900, trials=1000, criterion=SuccessCriterion.POLICY_CONFIDENCE
    )
  )
  assert trusted_with_material(policy).verdict is Trust.SELF_SCORED


def test_too_few_trials_is_refused_rather_than_given_a_rate():
  """At 5 trials one trial is 20 points, which is the published row where 40 percent is 2."""
  policy = _policy(evaluation=_measured_evaluation(successes=2, trials=5))
  report = success_rate(policy.evaluation)
  assert not report.stated
  assert report.point is None and report.low is None and report.high is None
  assert "20.0 percentage points" in report.reason
  assert "convention" in report.reason  # the floor is declared, not discovered

  standing = trusted_with_material(policy)
  assert not standing.trusted
  assert standing.verdict is Trust.UNDERPOWERED


def test_an_unevaluated_policy_is_untrusted_by_default():
  assert trusted_with_material(_policy(evaluation=None)).verdict is Trust.UNEVALUATED
  assert trusted_with_material(_policy(evaluation=Evaluation())).verdict is Trust.UNEVALUATED


def test_a_measured_policy_reports_an_interval_rather_than_a_point_alone():
  policy = _policy(evaluation=_measured_evaluation(successes=17, trials=20))
  standing = trusted_with_material(policy, acceptable_rate=0.50)
  assert standing.trusted
  assert standing.verdict is Trust.MEASURED
  assert standing.rate.stated
  assert standing.rate.point == pytest.approx(0.85)
  assert "interval" in standing.rate.describe()
  assert "17 of 20" in standing.rate.describe()
  assert standing.rate.width_pp is not None and standing.rate.width_pp > 30.0


def test_only_one_trust_state_is_trusted():
  assert sum(1 for t in Trust if t.evidence_complete) == 1


def test_blinding_is_reported_and_not_required():
  """Requiring it would be inventing a threshold out of hygiene nobody has measured."""
  unblinded = _policy(evaluation=_measured_evaluation(blinded=False))
  standing = trusted_with_material(unblinded, acceptable_rate=0.50)
  assert standing.trusted
  assert "unblinded" in standing.rate.reason


def test_an_evaluation_cannot_report_more_successes_than_trials():
  with pytest.raises(ValueError) as excinfo:
    Evaluation(trials=10, successes=11, held_out=True)
  assert "not an observation" in str(excinfo.value)
  with pytest.raises(ValueError):
    Evaluation(trials=-1)


def test_the_interval_matches_published_clopper_pearson_values():
  """The one thing here that could be wrong silently, checked against known values."""
  expected = {
    (9, 10): (55.5, 99.7),
    (18, 20): (68.3, 98.8),
    (45, 50): (78.2, 96.7),
    (90, 100): (82.4, 95.1),
    (180, 200): (85.0, 93.8),
    (900, 1000): (88.0, 91.8),
    (5, 10): (18.7, 81.3),
    (10, 20): (27.2, 72.8),
    (25, 50): (35.5, 64.5),
    (50, 100): (39.8, 60.2),
  }
  for (successes, trials), (low, high) in expected.items():
    got_low, got_high = success_interval(successes, trials)
    assert round(100 * got_low, 1) == pytest.approx(low, abs=0.05)
    assert round(100 * got_high, 1) == pytest.approx(high, abs=0.05)


def test_the_interval_refuses_impossible_observations():
  with pytest.raises(ValueError):
    success_interval(1, 0)
  with pytest.raises(ValueError):
    success_interval(11, 10)
  assert success_interval(0, 20)[0] == 0.0
  assert success_interval(20, 20)[1] == 1.0


def test_the_trial_floor_is_derived_from_the_declared_ceiling():
  """The constant is computed from a stated convention rather than picked and defended."""
  assert MIN_HELDOUT_TRIALS == int(round(100.0 / MAX_TRIAL_WEIGHT_PP))
  assert 100.0 / MIN_HELDOUT_TRIALS <= MAX_TRIAL_WEIGHT_PP


# -- how many demonstrations -------------------------------------------------------------


def test_demonstrations_needed_returns_no_number():
  estimate = demonstrations_needed("place a plate in a printed nest")
  assert estimate.estimate is None
  assert isinstance(estimate.refusal.why, str)
  assert "not knowable in advance" in estimate.refusal.why
  assert estimate.refusal.what_it_would_take
  assert estimate.determinants == DETERMINANTS and len(DETERMINANTS) >= 4


def test_the_published_table_names_its_tasks_and_methods_and_spans_two_orders_of_magnitude():
  low, high = published_span()
  assert (low, high) == (20, 8658)
  assert high / low > 100
  assert all(row.system and row.task and row.source for row in PUBLISHED_COUNTS)
  described = demonstrations_needed("anything").describe()
  assert "20 to 8658" in described


def test_the_table_keeps_the_row_that_contradicts_the_usual_reading():
  """Twice the demonstrations of any other task in its paper, and the worst result in it."""
  velcro = [r for r in PUBLISHED_COUNTS if r.task == "Thread Velcro"]
  assert velcro and velcro[0].demonstrations == 100 and velcro[0].success == 0.20
  # And the row whose own paper contradicts itself keeps a null count rather than a guess.
  unresolved = [r for r in PUBLISHED_COUNTS if r.demonstrations is None]
  assert unresolved and all("contradict" in r.note or "HOURS" in r.note for r in unresolved)


def test_every_published_success_rate_carries_the_trial_count_where_the_paper_gave_one():
  """A rate off 5 rollouts and a rate off 25 are not the same kind of number."""
  cheap = [r for r in PUBLISHED_COUNTS if r.trials is not None and r.trials < 10]
  assert cheap and all(r.note for r in cheap)


# -- composition and refusals --------------------------------------------------------------


def test_a_trusted_policy_on_a_revised_fixture_may_not_run():
  """Each leg is answerable alone and none of them is the question a lab asks."""
  policy = _policy()
  assert may_run(policy, _coupling(), acceptable_rate=0.50, interlock=_interlock()).permitted

  revised = may_run(
    policy, _coupling(revision="rev_b"), acceptable_rate=0.50, interlock=_interlock()
  )
  assert not revised.permitted
  assert any("fixture coupling" in b for b in revised.blockers())
  assert revised.trust.trusted  # the policy is fine; the world changed


def test_a_measured_policy_trained_on_an_unusable_capture_may_not_run():
  policy = _policy(captures=(_teleop_capture(gripper_state_recorded=False),))
  standing = may_run(policy, _coupling(), acceptable_rate=0.50, interlock=_interlock())
  assert not standing.permitted
  assert any("not usable for training" in b for b in standing.blockers())


def test_may_run_reports_every_blocker_rather_than_the_first():
  policy = Policy(name="nothing", captures=(Capture(),))
  standing = may_run(policy, None)
  assert not standing.permitted
  assert len(standing.blockers()) >= 3


def test_the_refusals_are_returned_as_data():
  assert refusals() is NOT_ESTIMATED
  assert len(NOT_ESTIMATED) >= 5
  for r in NOT_ESTIMATED:
    assert r.quantity and r.why and r.what_it_would_take
  quantities = " ".join(r.quantity for r in NOT_ESTIMATED)
  assert "demonstrations required for a new task" in quantities
  assert "exchange rate" in quantities


def test_the_module_exposes_no_helper_that_returns_a_demonstration_count():
  """A module that refuses a number in prose and returns one elsewhere has no discipline."""
  for name in imitation.__all__:
    obj = getattr(imitation, name)
    assert not name.startswith("estimate_")
    assert getattr(obj, "__name__", "") not in ("demos_for", "how_many_demos")


def test_the_authority_boundary_is_referenced_in_prose_and_not_imported():
  assert "interlock" in INTERLOCK_NOTE.lower()
  assert "proposes" in INTERLOCK_NOTE.lower() and "disposes" in INTERLOCK_NOTE.lower()
  source = open(imitation.__file__, encoding="ascii").read()
  assert "import authority" not in source
  assert "from .authority" not in source


def test_the_module_is_ascii():
  """House rule, enforced here as well as in CI, because it is cheap to check and easy to break."""
  with open(imitation.__file__, "rb") as handle:
    body = handle.read()
  body.decode("ascii")


def test_the_summary_counts_what_it_says_it_counts():
  counts = summary()
  assert counts["modalities"] == len(Modality)
  assert counts["modalities_with_a_measured_action_stream"] == 3
  assert counts["published_task_rows_with_a_count"] < counts["published_task_rows"]
  assert counts["min_heldout_trials"] == MIN_HELDOUT_TRIALS


# -- what the adversarial audit found, and what must stay found ------------------


def test_a_policy_that_failed_every_trial_is_not_trusted():
  """The audit's first blocker, and the worst kind of bug this package can have.

  A policy evaluated correctly -- held out, externally scored, twenty trials -- that
  succeeded in NONE of them came back trusted, because `trusted` was `verdict is MEASURED`
  and the evaluation had indeed been conducted properly. Every word of the Trust docstring
  said MEASURED does not mean good; the boolean said the opposite to anyone who read it
  instead of the prose, and it is the boolean that gets branched on.
  """
  failed = _policy(evaluation=_measured_evaluation(successes=0, trials=20))
  standing = trusted_with_material(failed, acceptable_rate=0.50)
  assert standing.verdict is Trust.MEASURED  # the evaluation WAS done properly
  assert standing.evidence_complete
  assert not standing.trusted
  assert not may_run(failed, _coupling(), acceptable_rate=0.50, interlock=_interlock()).permitted


def test_without_a_declared_acceptance_rate_the_question_is_refused():
  """What rate is acceptable is a property of the task, not of this module. A tolerable
  failure rate for a tip pickup a retry fixes is not one for a transfer that consumes the
  last of a sample. Defaulting it would answer, invisibly, the only question here that
  requires knowing what the robot is holding."""
  good = _policy(evaluation=_measured_evaluation(successes=98, trials=100))
  standing = trusted_with_material(good)
  assert standing.evidence_complete
  assert not standing.trusted
  assert "no acceptable rate was declared" in standing.reason


def test_acceptance_is_judged_on_the_interval_not_the_point_estimate():
  """A point estimate is what the policy did on those trials. The lower bound is what the
  trials support saying about the next one, and the gap is why the trial count is reported."""
  wide = _policy(evaluation=_measured_evaluation(successes=18, trials=20))  # point 90 percent
  narrow = _policy(evaluation=_measured_evaluation(successes=90, trials=100))  # point 90 percent
  assert not trusted_with_material(wide, acceptable_rate=0.80).trusted
  assert trusted_with_material(narrow, acceptable_rate=0.80).trusted


def test_a_run_needs_a_bound_that_lives_outside_the_policy():
  """A learned policy carries no guarantee about an input it has not seen, so the bound on
  what it can reach, how fast and how hard cannot come from the policy or from a model
  checking the policy."""
  policy = _policy()
  assert not may_run(policy, _coupling(), acceptable_rate=0.50).permitted
  assert any("interlock" in b for b in may_run(policy, _coupling(), acceptable_rate=0.50).blockers())

  # An interlock whose own miss rate nobody measured is a belief, not a safety device.
  unmeasured = _interlock(miss_rate_measured=False)
  standing = may_run(policy, _coupling(), acceptable_rate=0.50, interlock=unmeasured)
  assert not standing.permitted
  assert any("miss rate" in b for b in standing.blockers())


def test_an_unrecorded_fixture_is_not_agreement_with_a_recorded_one():
  """The audit's fourth finding. `distinct_couplings` skipped a capture whose coupling was
  None, so one fixtured session plus two unrecorded ones reported a single clean coupling.
  Two thirds of the training data came from a world nobody wrote down."""
  fixtured = _teleop_capture(coupling=_coupling())
  unrecorded = _teleop_capture(coupling=None)
  policy = _policy(captures=(fixtured, unrecorded, unrecorded))
  assert policy.training_coupling() is None
  assert not fixture_coupled(policy, _coupling()).holds

  # Two captures against the SAME recorded revision still couple.
  assert _policy(captures=(fixtured, fixtured)).training_coupling() is not None


def test_a_retargeting_error_must_be_a_positive_distance():
  """Zero and negative are the signature of a defaulted or sign-flipped value rather than a
  measurement, in the one field the module says is almost never filled in."""
  for bad in (0.0, -5.0):
    with pytest.raises(ValueError) as excinfo:
      Retargeting(method="x", error_measured_mm=bad, basis=Basis.IN_HOUSE)
    assert "not a measurement" in str(excinfo.value)
  assert Retargeting(method="x", error_measured_mm=12.5, basis=Basis.IN_HOUSE).validated


def test_no_success_figure_is_quoted_as_a_bare_percentage():
  """The module quoted 91.7 percent against 45.8 percent five times as established. Those
  are 11 of 12 and 11 of 24 -- trial counts this module's own `success_rate` refuses, since
  one trial at n=12 moves the rate by 8.3 points. A module that refuses the caller's
  12-trial rate while quoting its own has no discipline."""
  import autonomous_lab.imitation as module

  source = pathlib.Path(module.__file__).read_text()
  for stripped in ("91.7", "45.8", "52.8", "76.5"):
    assert stripped not in source, f"{stripped} is a point estimate quoted without its count"
  assert "11 of 12" in source and "11 of 24" in source


def test_the_simulation_result_is_marked_as_simulation():
  """It was welded onto a real-robot sentence with an 'and', cherry-picked to the worst of
  nine models. The guide names that exact move as the trap it warns about."""
  import autonomous_lab.imitation as module

  source = pathlib.Path(module.__file__).read_text()
  assert "SIMULATION" in source
  assert "nine models" in source
