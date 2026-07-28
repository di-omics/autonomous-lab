"""Device-free tests for the authority layer.

The tests worth writing here are the ones that try to get a model an authority it has not
earned. Three attacks matter more than the rest: handing a model a decision that requires an
interlock or a person, handing a plan a silence and having it read as permission, and
handing the ladder a passed simulation and having it read as a qualified machine. All three
produce a document that looks like governance, which is what makes them worth a test rather
than a paragraph.
"""

from __future__ import annotations

import pytest

from autonomous_lab.authority import (
  DECISION_CLASSES,
  DECISION_CLASSES_BY_NAME,
  LADDER,
  LADDER_BY_RUNG,
  Assignment,
  Authority,
  DecisionClass,
  Plan,
  QualificationRung,
  Rung,
  ViolationKind,
  implies,
  missing_below,
  qualified_for,
  strengthened,
  unaccountable,
  unsupported_claims,
  violations,
)

# The keys of this repo's verified-literature index. Written out here rather than imported
# so that a typo or an invented citation in the registry fails a test instead of resolving
# to nothing.
KNOWN_EVIDENCE_KEYS = {
  "a_lab",
  "alabos",
  "arrive",
  "coley",
  "dai",
  "fda_di",
  "homecage_multi",
  "iso23783",
  "jump",
  "labsafety",
  "ncats",
  "provo",
  "pylabrobot",
  "roboculture",
  "smartkage",
}


def _plan_assigning(**pairs) -> Plan:
  """A plan covering every declared class, overridden where the test names one.

  Defaults to the required authority everywhere so that a test about one class is not
  drowned in twelve unassigned-class violations.
  """
  return Plan(
    name="test",
    assignments=tuple(
      Assignment(
        decision_class=dc.name,
        authority=pairs.get(dc.name, dc.required),
        who="a named person" if pairs.get(dc.name, dc.required) is Authority.HUMAN else "",
      )
      for dc in DECISION_CLASSES
    ),
  )


# -- the failure this module exists to catch -----------------------------------


def test_a_model_may_not_release_a_batch():
  """The single most important test in the file.

  Release is where this lab's uncertainty becomes another party's assumption. A plan that
  puts a model there must be reported, and reported as overreach rather than as a note.
  """
  plan = _plan_assigning(batch_release=Authority.MODEL)
  found = [v for v in violations(plan) if v.decision_class == "batch_release"]
  assert len(found) == 1
  assert found[0].kind is ViolationKind.WEAKENED
  assert found[0].required is Authority.HUMAN
  assert found[0].assigned is Authority.MODEL
  assert found[0].model_overreach


def test_a_model_may_not_arm_actuation():
  plan = _plan_assigning(actuation_arming=Authority.MODEL)
  found = [v for v in violations(plan) if v.decision_class == "actuation_arming"]
  assert len(found) == 1
  assert found[0].kind is ViolationKind.WEAKENED
  assert found[0].model_overreach


def test_a_model_may_not_make_a_welfare_or_hazard_decision():
  plan = _plan_assigning(
    welfare_intervention=Authority.MODEL,
    hazard_call=Authority.MODEL,
    animal_procedure_authorization=Authority.MODEL,
  )
  names = {v.decision_class for v in violations(plan) if v.kind is ViolationKind.WEAKENED}
  assert names == {"welfare_intervention", "hazard_call", "animal_procedure_authorization"}


def test_every_class_requiring_more_than_a_model_refuses_a_model():
  """Swept across the whole registry so a new class cannot be added without this holding."""
  for dc in DECISION_CLASSES:
    if dc.required is Authority.MODEL:
      continue
    plan = _plan_assigning(**{dc.name: Authority.MODEL})
    weakened = [
      v
      for v in violations(plan)
      if v.decision_class == dc.name and v.kind is ViolationKind.WEAKENED
    ]
    assert weakened, f"{dc.name} requires {dc.required.value} and accepted a model"


def test_drafting_does_not_satisfy_an_interlock():
  """One step short is still a model in the path, which is what the requirement excludes."""
  plan = _plan_assigning(actuation_arming=Authority.MODEL_PROPOSES)
  found = [v for v in violations(plan) if v.decision_class == "actuation_arming"]
  assert found and found[0].kind is ViolationKind.WEAKENED
  assert found[0].model_overreach


def test_a_deterministic_interlock_satisfies_a_deterministic_class():
  plan = _plan_assigning(actuation_arming=Authority.DETERMINISTIC)
  assert not [v for v in violations(plan) if v.decision_class == "actuation_arming"]


# -- strengthening is never the defect -----------------------------------------


def test_putting_a_human_on_a_model_permissible_class_is_not_a_violation():
  """A lab may always spend a person on a decision a model could make.

  The asymmetry is the whole design. If this ever fails, the check has become a rule about
  conformity rather than a rule about safety.
  """
  plan = _plan_assigning(prior_result_retrieval=Authority.HUMAN)
  assert not [v for v in violations(plan) if v.decision_class == "prior_result_retrieval"]
  assert plan.escalation_only


def test_strengthening_every_class_to_human_produces_no_violations():
  plan = Plan(
    name="everything-to-a-person",
    assignments=tuple(
      Assignment(dc.name, Authority.HUMAN, who="the study director") for dc in DECISION_CLASSES
    ),
  )
  assert violations(plan) == ()
  assert plan.complies


def test_strengthening_is_reported_but_not_flagged():
  plan = _plan_assigning(
    prior_result_retrieval=Authority.HUMAN,
    actuation_arming=Authority.HUMAN,
  )
  raised = {name for name, _req, _got in strengthened(plan)}
  assert raised == {"prior_result_retrieval", "actuation_arming"}
  assert not violations(plan)


def test_authority_ordering_runs_model_to_human():
  assert Authority.MODEL.rank < Authority.MODEL_PROPOSES.rank
  assert Authority.MODEL_PROPOSES.rank < Authority.DETERMINISTIC.rank
  assert Authority.DETERMINISTIC.rank < Authority.HUMAN.rank
  assert Authority.HUMAN.satisfies(Authority.MODEL)
  assert not Authority.MODEL.satisfies(Authority.HUMAN)


def test_only_one_authority_lets_a_model_decide_alone():
  """The load-bearing line on the enum. Everything else is a claim about review."""
  alone = [a for a in Authority if a.model_decides_alone]
  assert alone == [Authority.MODEL]
  in_path = {a for a in Authority if a.model_in_path}
  assert in_path == {Authority.MODEL, Authority.MODEL_PROPOSES}


def test_no_hazard_or_welfare_class_admits_a_model_in_any_role():
  """Adding a reviewer to a model's framing of a hazard does not make it a hazard call."""
  for name in ("hazard_call", "welfare_intervention", "animal_procedure_authorization"):
    assert not DECISION_CLASSES_BY_NAME[name].admits_a_model


# -- silence is not compliance --------------------------------------------------


def test_an_unassigned_class_is_a_violation():
  """The defect every real authority document has: it covers what someone thought of."""
  plan = Plan(
    name="two-lines",
    assignments=(
      Assignment("prior_result_retrieval", Authority.MODEL),
      Assignment("protocol_drafting", Authority.MODEL_PROPOSES),
    ),
  )
  unassigned = {v.decision_class for v in violations(plan) if v.kind is ViolationKind.UNASSIGNED}
  assert "batch_release" in unassigned
  assert "actuation_arming" in unassigned
  assert len(unassigned) == len(DECISION_CLASSES) - 2
  assert not plan.complies


def test_an_empty_plan_does_not_pass():
  plan = Plan(name="nothing")
  found = violations(plan)
  assert len(found) == len(DECISION_CLASSES)
  assert all(v.kind is ViolationKind.UNASSIGNED for v in found)


def test_an_empty_plan_is_escalation_only_and_still_not_compliant():
  """The distinction that keeps escalation_only from being read as a pass.

  A plan weakening nothing is trivially escalation-only. It is also governing nothing, and
  a property that could not tell those apart would be the most flattering number in the
  package.
  """
  plan = Plan(name="nothing")
  assert plan.escalation_only
  assert not plan.complies


def test_the_unassigned_reason_names_the_required_authority():
  """A finding a reader cannot act on is a finding they will not act on."""
  plan = Plan(name="nothing")
  found = next(v for v in violations(plan) if v.decision_class == "batch_release")
  assert "human" in found.reason
  assert found.required is Authority.HUMAN


def test_an_assignment_to_an_undeclared_class_is_reported_not_ignored():
  plan = _plan_assigning()
  plan = Plan(
    name="with-a-stray",
    assignments=plan.assignments + (Assignment("vibes_check", Authority.MODEL),),
  )
  stray = [v for v in violations(plan) if v.kind is ViolationKind.UNDECLARED]
  assert len(stray) == 1
  assert stray[0].decision_class == "vibes_check"


def test_a_human_class_with_nobody_named_is_reported_separately():
  """HUMAN authority with no name is a queue, not accountability.

  Deliberately not a violation: the authority level is right and only the accountability is
  missing, so folding them together would let a fix for one look like a fix for the other.
  """
  plan = Plan(
    name="anonymous",
    assignments=tuple(
      Assignment(dc.name, dc.required, who="") for dc in DECISION_CLASSES
    ),
  )
  assert violations(plan) == ()
  missing = set(unaccountable(plan))
  assert "batch_release" in missing
  assert "hazard_call" in missing


# -- the registry itself --------------------------------------------------------


def test_every_decision_class_states_its_because():
  """A required authority with no mechanism cannot be argued with, only obeyed."""
  for dc in DECISION_CLASSES:
    assert dc.because.strip(), f"{dc.name} declares a requirement with no mechanism"
    assert len(dc.because) > 80, f"{dc.name} states a mechanism too thin to argue with"


def test_a_decision_class_cannot_be_built_without_a_mechanism():
  with pytest.raises(ValueError, match="no mechanism"):
    DecisionClass(
      name="bare",
      decides="something",
      required=Authority.HUMAN,
      because="   ",
    )


def test_every_decision_class_says_what_is_being_decided():
  for dc in DECISION_CLASSES:
    assert dc.decides.strip(), f"{dc.name} does not say what it decides"


def test_evidence_keys_resolve_to_the_verified_index():
  """An invented citation is worse than no citation, so an unknown key fails here."""
  for dc in DECISION_CLASSES:
    if dc.evidence_key is not None:
      assert dc.evidence_key in KNOWN_EVIDENCE_KEYS, f"{dc.name} cites an unknown source"


def test_the_registry_spans_every_authority_level():
  """A registry with nothing at MODEL would be posturing rather than an argument."""
  levels = {dc.required for dc in DECISION_CLASSES}
  assert levels == set(Authority)


def test_class_names_are_unique():
  names = [dc.name for dc in DECISION_CLASSES]
  assert len(names) == len(set(names))
  assert len(DECISION_CLASSES_BY_NAME) == len(names)


def test_the_hazard_argument_cites_the_safety_benchmark():
  assert DECISION_CLASSES_BY_NAME["hazard_call"].evidence_key == "labsafety"
  assert DECISION_CLASSES_BY_NAME["hazard_call"].required is Authority.HUMAN


# -- the qualification ladder ---------------------------------------------------


def test_a_passed_simulation_does_not_qualify_the_physical_rungs():
  """The overclaim the ladder exists to refuse.

  A simulation establishes that the generated commands are the intended ones. Every rung
  above it is a statement about matter, and there is no inference from one to the other.
  """
  for rung in Rung:
    if rung is Rung.SIMULATION:
      continue
    assert rung.physical
    assert not implies(Rung.SIMULATION, rung)
  assert implies(Rung.SIMULATION, Rung.SIMULATION)


def test_passing_rung_n_never_implies_rung_n_plus_one():
  order = list(Rung)
  for lower, higher in zip(order, order[1:]):
    assert not implies(lower, higher)
    assert implies(higher, lower)


def test_a_rung_cannot_be_skipped():
  """Assay transfer on top of a simulation is qualified for the simulation.

  The upper result is not discarded; it simply stands on nothing, and a result about a
  system nobody characterized is not a qualification of that system.
  """
  passed = [Rung.SIMULATION, Rung.ASSAY_TRANSFER]
  assert qualified_for(passed) == (Rung.SIMULATION,)
  gaps = missing_below(Rung.ASSAY_TRANSFER, passed)
  assert set(gaps) == {
    Rung.DEVICE_ACCEPTANCE,
    Rung.INTEGRATED_DRY_RUN,
    Rung.VOLUMETRIC_QUALIFICATION,
  }


def test_claiming_a_rung_never_passed_is_unsupported():
  unsupported = unsupported_claims([Rung.VOLUMETRIC_QUALIFICATION], [Rung.SIMULATION])
  assert len(unsupported) == 1
  claim, gaps = unsupported[0]
  assert claim is Rung.VOLUMETRIC_QUALIFICATION
  assert Rung.VOLUMETRIC_QUALIFICATION in gaps
  assert Rung.DEVICE_ACCEPTANCE in gaps


def test_an_unbroken_ladder_qualifies_the_top():
  assert qualified_for(list(Rung)) == tuple(Rung)
  assert unsupported_claims([Rung.SUSTAINED_PRODUCTION], list(Rung)) == ()


def test_nothing_passed_qualifies_nothing():
  assert qualified_for([]) == ()
  assert missing_below(Rung.DEVICE_ACCEPTANCE, []) == (Rung.SIMULATION,)


def test_every_rung_states_what_it_does_not_qualify():
  """A rung stated without its limit will be read as qualifying everything above it."""
  assert len(LADDER) == len(Rung)
  for entry in LADDER:
    assert entry.qualifies.strip()
    assert entry.does_not_qualify.strip(), f"{entry.rung.value} states no limit"
    assert len(entry.does_not_qualify) > 80


def test_a_rung_cannot_be_built_without_a_stated_limit():
  with pytest.raises(ValueError, match="no limit"):
    QualificationRung(
      rung=Rung.SIMULATION,
      qualifies="everything, obviously",
      does_not_qualify="",
    )


def test_the_ladder_is_ordered_and_complete():
  assert tuple(entry.rung for entry in LADDER) == tuple(Rung)
  assert set(LADDER_BY_RUNG) == set(Rung)
  heights = [entry.rung.height for entry in LADDER]
  assert heights == sorted(heights)


def test_ladder_evidence_keys_resolve_to_the_verified_index():
  for entry in LADDER:
    if entry.evidence_key is not None:
      assert entry.evidence_key in KNOWN_EVIDENCE_KEYS


def test_the_assay_transfer_rung_refuses_to_qualify_production():
  """The one rung whose limit is stated by the cited guidance itself."""
  entry = LADDER_BY_RUNG[Rung.ASSAY_TRANSFER]
  assert entry.evidence_key == "ncats"
  assert "post-production monitoring" in entry.does_not_qualify


# -- no self-declaration --------------------------------------------------------


def test_nothing_in_a_plan_can_declare_itself_compliant():
  """The same rule the ledger applies to automation and qc applies to readiness.

  There must be no field an author can set that suppresses a finding. If this fails,
  someone has added an override and every report in this module can be made to lie.
  """
  assignment = Assignment("batch_release", Authority.MODEL)
  plan = Plan(name="p", assignments=(assignment,))
  for attr in ("approved", "exempt", "waived", "override", "compliant"):
    assert not hasattr(assignment, attr)
    assert not hasattr(plan, attr)

  # `complies` is computed from the registry and has no setter, so a plan cannot assert it.
  with pytest.raises(AttributeError):
    plan.complies = True


# -- no row may hide behind an earlier one ---------------------------------------


def test_a_stronger_assignment_listed_first_cannot_hide_a_weaker_one():
  """The module's stated invariant is that no field an author can set suppresses a
  violation. A duplicate assignment was exactly such a field: first-match resolution meant
  listing HUMAN before MODEL on batch release reported a clean plan.
  """
  A = lambda auth: Assignment(decision_class="batch_release", authority=auth, who="x")
  for order in ((A(Authority.HUMAN), A(Authority.MODEL)), (A(Authority.MODEL), A(Authority.HUMAN))):
    found = [v for v in violations(Plan(name="p", assignments=order)) if v.decision_class == "batch_release"]
    kinds = {v.kind for v in found}
    assert ViolationKind.DUPLICATED in kinds, "the ambiguity itself is a finding"
    assert ViolationKind.WEAKENED in kinds, "the weaker row must still be judged on its merits"


def test_a_duplicated_class_is_reported_rather_than_resolved():
  """Picking a winner would answer 'who decides' on the author's behalf. A plan naming a
  class twice has not decided, and that is the thing to report."""
  A = lambda auth: Assignment(decision_class="batch_release", authority=auth, who="x")
  plan = Plan(name="p", assignments=(A(Authority.HUMAN), A(Authority.MODEL)))
  assert plan.assigned("batch_release") is None, "an ambiguous class resolves to nothing"
  assert len(plan.all_assigned("batch_release")) == 2
  dup = next(v for v in violations(plan) if v.kind is ViolationKind.DUPLICATED)
  assert "has not decided" in dup.reason


def test_a_single_correct_assignment_is_still_clean():
  """Guards the fix against overcorrecting into always-fail."""
  plan = Plan(name="p", assignments=(Assignment(decision_class="batch_release", authority=Authority.HUMAN, who="QA"),))
  assert not [v for v in violations(plan) if v.decision_class == "batch_release"]
