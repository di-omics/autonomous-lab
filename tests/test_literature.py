"""Device-free tests for the citation layer. Every one of them tries to make it lie.

The failure this module exists to prevent is an accurate citation carrying an inaccurate
inference, so the tests are written from the attacker's side: hand it a cell-assay production
claim and see whether a materials campaign comes back as support, hand it a claim no work
addresses and see whether an empty list reports as satisfied, and check that an entry whose
numbers were only partly confirmed cannot present itself as fully verified.

Two invariants carry the rest. Every entry must state what it does NOT establish -- a citation
with no boundary is an unread one, and the table is worth nothing if it can hold one. And every
number that failed verification must still be written down somewhere in the entry, because a
verification pass whose misses are invisible only launders the numbers it could not check.

One test deliberately proves the layer can say yes. A checker that refuses everything is as
useless as one that accepts everything, and the refusals only mean something if a scope that
genuinely sits inside a demonstration comes back supported.
"""

from __future__ import annotations

import pytest

from autonomous_lab.literature import (
  EVIDENCE,
  EVIDENCE_BY_KEY,
  UNSUPPORTED,
  Confidence,
  Domain,
  Evidence,
  EvidenceKind,
  Scope,
  Support,
  by_domain,
  partially_verified,
  summary,
  support_for,
  unsupported_claims,
)


# A claim of the kind this module was built to refuse: sustained, unattended, cell-assay
# production. Every field is what gets asserted in the room, not what anyone has shown.
SUSTAINED_CELL_PRODUCTION = Scope(
  summary="continuous unattended plate-based cell assay production",
  material="mammalian cell culture in plates",
  continuous_hours=720.0,
  replicated=True,
  sustained=True,
  unattended=True,
)


def _gap(support, key: str):
  """The in-domain finding for one citation.

  Raises rather than returning None if the citation was cut on domain instead, so a test that
  meant to check a scope shortfall cannot quietly pass because the entry never reached the
  comparison at all.
  """
  return next(g for g in support.speaks_to if g.evidence.key == key)


def _refused(support, key: str):
  """The domain-cut finding for one citation. Kept separate from `_gap` because the two
  lists mean different things: one is a citation that fell short, the other is a citation
  about something else."""
  return next(g for g in support.out_of_domain if g.evidence.key == key)


# -- the domain cut ------------------------------------------------------------


def test_a_materials_campaign_is_not_support_for_a_cell_assay_production_claim():
  """The single most common miscitation in this field, and the reason for the module."""
  support = support_for(Domain.CELL_ASSAY, SUSTAINED_CELL_PRODUCTION)
  assert "a_lab" not in {g.evidence.key for g in support.speaks_to}
  assert "a_lab" in {g.evidence.key for g in support.out_of_domain}


def test_the_materials_campaign_is_refused_in_the_words_that_matter():
  """'Not supported' is an opinion. Naming the scope is a statement someone can check."""
  support = support_for(Domain.CELL_ASSAY, SUSTAINED_CELL_PRODUCTION)
  gap = _refused(support, "a_lab")
  assert "17-day materials campaign" in gap.reason
  assert "does not speak to a cell assay claim" in gap.reason


def test_a_fifteen_hour_yeast_run_does_not_reach_sustained_production():
  """In-domain and still short. This is the citation that survives the domain cut."""
  support = support_for(Domain.CELL_ASSAY, SUSTAINED_CELL_PRODUCTION)
  gap = _gap(support, "roboculture")
  assert not gap.covers
  assert "15-hour single-plate yeast run" in gap.reason
  assert "does not reach sustained production" in gap.reason


def test_crossing_into_living_material_is_named_rather_than_left_to_the_reader():
  support = support_for(Domain.CELL_ASSAY, SUSTAINED_CELL_PRODUCTION)
  gap = _refused(support, "dai")
  assert "loses viability" in gap.reason


def test_the_living_line_falls_where_the_failure_modes_do():
  assert Domain.CELL_ASSAY.living and Domain.IN_VIVO.living
  assert not Domain.MATERIALS.living
  assert not Domain.CHEMISTRY.living
  assert not Domain.ORCHESTRATION.living


def test_support_for_accounts_for_every_entry_exactly_once():
  """A citation the report drops is a citation nobody has to answer for."""
  support = support_for(Domain.CELL_ASSAY, SUSTAINED_CELL_PRODUCTION)
  seen = [g.evidence.key for g in support.speaks_to] + [g.evidence.key for g in support.out_of_domain]
  assert sorted(seen) == sorted(e.key for e in EVIDENCE)


def test_the_genomics_style_claim_is_unsupported_and_says_why():
  support = support_for(Domain.CELL_ASSAY, SUSTAINED_CELL_PRODUCTION)
  assert not support.supported
  assert support.gaps()
  assert "sustained production" in support.reason()


# -- the layer must be able to say yes, or its refusals mean nothing -----------


def test_a_scope_that_sits_inside_a_demonstration_reports_as_supported():
  """Guards against the cheapest possible bug: a checker that always answers no."""
  modest = Scope(
    summary="a single ten-hour attended run on one plate of yeast",
    material="yeast culture in a 96-well plate",
    continuous_hours=10.0,
  )
  support = support_for(Domain.CELL_ASSAY, modest)
  assert support.supported
  covering = {g.evidence.key for g in support.speaks_to if g.covers}
  assert "roboculture" in covering


def test_the_same_demonstration_fails_the_same_claim_once_unattended_is_asserted():
  """One field changes, and the citation that covered the claim stops covering it."""
  attended = Scope(summary="ten attended hours", continuous_hours=10.0)
  unattended = Scope(summary="ten unattended hours", continuous_hours=10.0, unattended=True)
  before = _gap(support_for(Domain.CELL_ASSAY, attended), "roboculture")
  after = _gap(support_for(Domain.CELL_ASSAY, unattended), "roboculture")
  assert before.covers
  assert not after.covers
  assert "manually initiated" in after.reason


def test_an_empty_support_list_is_not_vacuously_satisfied():
  """all() over an empty sequence is True, and that bug would rank the worst claims best."""
  empty = Support(
    claim_domain=Domain.CELL_ASSAY,
    scope=SUSTAINED_CELL_PRODUCTION,
    speaks_to=(),
    out_of_domain=(),
  )
  assert not empty.supported


# -- kind: what can evidence an operating claim at all ------------------------


def test_only_a_demonstration_evidences_an_operating_claim():
  assert EvidenceKind.EMPIRICAL_DEMONSTRATION.demonstrates_operation
  for kind in (
    EvidenceKind.BENCHMARK,
    EvidenceKind.GUIDANCE,
    EvidenceKind.STANDARD,
    EvidenceKind.RESOURCE,
  ):
    assert not kind.demonstrates_operation


def test_in_domain_guidance_does_not_cover_an_operating_claim():
  """A standard's existence is easy to mistake for its satisfaction."""
  support = support_for(Domain.CELL_ASSAY, SUSTAINED_CELL_PRODUCTION)
  gap = _gap(support, "ncats")
  assert not gap.covers
  assert "not a demonstration" in gap.reason


def test_a_benchmark_is_not_a_lab_run():
  bench_claim = Scope(summary="hazard judgment at a bench", unattended=True)
  gap = _gap(support_for(Domain.SAFETY, bench_claim), "labsafety")
  assert not gap.covers
  assert "does not show a lab operating" in gap.reason


def test_a_non_demonstration_is_refused_once_rather_than_four_times():
  """Duration, replication and human-in-the-loop gaps against a checklist are category errors.

  A report that stacked them would read as four objections, three of them fabricated, and the
  real one -- nobody ran anything -- would be the easiest of the four to skim past.
  """
  support = support_for(Domain.CELL_ASSAY, SUSTAINED_CELL_PRODUCTION)
  for key in ("ncats", "jump"):
    gap = _gap(support, key)
    assert len(gap.shortfalls) == 1, f"{key} is refused on {len(gap.shortfalls)} grounds"
    assert "sustained production" not in gap.reason
    assert "was not replicated" not in gap.reason


# -- confidence ----------------------------------------------------------------


def test_a_work_whose_numbers_were_only_partially_verified_is_not_confirmed():
  partial = partially_verified()
  assert partial, "a verification pass that confirmed everything did not check hard enough"
  for e in partial:
    assert e.confidence is Confidence.PARTIAL
    assert not e.confidence.fully_verified
    assert not e.verified


def test_every_partial_entry_names_which_numbers_could_not_be_confirmed():
  """A confidence downgrade with no reason attached cannot be acted on or retired."""
  for e in partially_verified():
    assert e.unverified
    for item in e.unverified:
      assert len(item.strip()) > 20, f"{e.key} carries an unverified item too vague to chase"


def test_a_partial_entry_that_names_nothing_unverified_is_refused():
  with pytest.raises(ValueError, match="names nothing unverified"):
    Evidence(
      key="hollow",
      citation="A work.",
      url="https://example.org/1",
      domain=Domain.CELL_ASSAY,
      kind=EvidenceKind.EMPIRICAL_DEMONSTRATION,
      year=2020,
      confidence=Confidence.PARTIAL,
      shorthand="a work",
      demonstrates="something",
      does_not_establish="it does not establish anything else",
      scope=Scope(summary="a scope"),
    )


def test_confirmed_entries_still_carry_the_numbers_that_failed_checking():
  """Confirmed means the stated numbers held, not that nothing went unchecked."""
  confirmed_with_misses = [e for e in EVIDENCE if e.verified and e.unverified]
  assert confirmed_with_misses
  assert "a_lab" in {e.key for e in confirmed_with_misses}


def test_the_figures_that_failed_verification_are_stated_nowhere_as_fact():
  """Dropping them would be safe. Restating them would not. The table does neither."""
  a_lab = EVIDENCE_BY_KEY["a_lab"]
  assert "43 new materials" not in a_lab.demonstrates
  assert "41 of 58" not in a_lab.demonstrates
  assert "43 new materials" in " ".join(a_lab.unverified)

  coley = EVIDENCE_BY_KEY["coley"]
  assert "68 hours" not in coley.demonstrates
  assert "68 hours" in " ".join(coley.unverified)


def test_coley_does_not_attribute_safety_to_the_expert_step():
  """The one attribution that could not be confirmed, and the reason this entry is PARTIAL."""
  coley = EVIDENCE_BY_KEY["coley"]
  assert coley.confidence is Confidence.PARTIAL
  assert "safety" not in coley.demonstrates.lower()
  assert "safety" in " ".join(coley.unverified).lower()


def test_pylabrobot_does_not_claim_simulation_across_families():
  """The paper asserts it architecturally and never reports running it. So does this entry."""
  plr = EVIDENCE_BY_KEY["pylabrobot"]
  assert plr.confidence is Confidence.PARTIAL
  assert "designed to work with any robot" in " ".join(plr.unverified)


# -- the boundary field --------------------------------------------------------


def test_every_entry_states_what_it_does_not_establish():
  """A citation with no stated scope limit is the failure mode this module prevents."""
  for e in EVIDENCE:
    assert e.does_not_establish.strip(), f"{e.key} states no scope limit"
    assert len(e.does_not_establish) > 200, f"{e.key} states a boundary too thin to be real"


def test_no_two_entries_share_a_boundary():
  """Boilerplate pasted across entries would satisfy the length check and say nothing."""
  boundaries = [e.does_not_establish for e in EVIDENCE]
  assert len(set(boundaries)) == len(boundaries)


def test_an_entry_with_no_boundary_is_refused_at_construction():
  with pytest.raises(ValueError, match="states no scope limit"):
    Evidence(
      key="unbounded",
      citation="A famous paper.",
      url="https://doi.org/10.0000/fake",
      domain=Domain.MATERIALS,
      kind=EvidenceKind.EMPIRICAL_DEMONSTRATION,
      year=2024,
      confidence=Confidence.CONFIRMED,
      shorthand="a famous paper",
      demonstrates="a great deal",
      does_not_establish="   ",
      scope=Scope(summary="a scope"),
    )


# -- citation hygiene ----------------------------------------------------------


def test_every_entry_carries_a_url_or_doi():
  for e in EVIDENCE:
    assert e.url.startswith("http"), f"{e.key} carries no resolvable identifier"
    assert e.citation.strip(), f"{e.key} carries no citation"


def test_an_entry_with_no_url_is_refused_at_construction():
  with pytest.raises(ValueError, match="no URL or DOI"):
    Evidence(
      key="uncheckable",
      citation="Someone, somewhere.",
      url="",
      domain=Domain.CHEMISTRY,
      kind=EvidenceKind.EMPIRICAL_DEMONSTRATION,
      year=2021,
      confidence=Confidence.CONFIRMED,
      shorthand="a work nobody can look up",
      demonstrates="something",
      does_not_establish="it does not establish that it can be found",
      scope=Scope(summary="a scope"),
    )


def test_evidence_keys_are_unique_and_the_index_is_complete():
  keys = [e.key for e in EVIDENCE]
  assert len(set(keys)) == len(keys)
  assert set(EVIDENCE_BY_KEY) == set(keys)


def test_every_declared_domain_has_at_least_one_entry():
  """An empty domain would silently return no support instead of refusing a claim."""
  for domain in Domain:
    assert by_domain(domain), f"no cited work for domain '{domain.value}'"


# -- scope honesty -------------------------------------------------------------


def test_a_hedged_duration_is_not_converted_into_a_figure():
  """'Almost four consecutive days' is not 96 hours, and the table refuses to make it one."""
  dai = EVIDENCE_BY_KEY["dai"]
  assert dai.scope.continuous_hours is None
  assert "almost four consecutive days" in dai.scope.duration_verbatim


def test_a_hedged_duration_reports_as_a_gap_rather_than_passing_quietly():
  claim = Scope(summary="a week of continuous chemistry", continuous_hours=168.0)
  gap = _gap(support_for(Domain.CHEMISTRY, claim), "dai")
  assert not gap.covers
  assert "states no duration that converts to a figure" in gap.reason


def test_no_demonstration_in_this_table_ran_without_a_human():
  """The finding, stated as an invariant: every one of them kept somebody in the loop."""
  demos = [e for e in EVIDENCE if e.kind.demonstrates_operation]
  assert demos
  for e in demos:
    assert e.scope.human_in_loop.strip(), f"{e.key} claims fully unattended operation"


def test_no_work_in_this_table_demonstrates_sustained_production():
  for e in EVIDENCE:
    assert not e.scope.sustained, f"{e.key} claims sustained production"


def test_a_shorter_run_cannot_cover_a_longer_claim():
  claim = Scope(summary="a hundred continuous hours of cell work", continuous_hours=100.0)
  gap = _gap(support_for(Domain.CELL_ASSAY, claim), "roboculture")
  assert not gap.covers
  assert "ran 15 h against the 100 h" in gap.reason


# -- the standing list ---------------------------------------------------------


def test_the_unsupported_list_is_not_empty_and_names_the_production_rate_claim():
  claims = unsupported_claims()
  assert claims
  names = {c.name for c in claims}
  assert "integrated_autonomy_at_production_rates" in names


def test_the_unsupported_list_covers_the_five_recurring_inferences():
  names = {c.name for c in UNSUPPORTED}
  assert names == {
    "integrated_autonomy_at_production_rates",
    "nominal_speed_as_biological_throughput",
    "simulation_as_qualification",
    "ai_fluency_as_hazard_competence",
    "capital_as_capacity",
  }


def test_every_unsupported_claim_names_the_citations_usually_offered_for_it():
  """The argument is never 'you have no evidence'; it is where the evidence stops."""
  for c in UNSUPPORTED:
    assert c.nearest, f"{c.name} refuses a claim without naming what it refuses"
    for key in c.nearest:
      assert key in EVIDENCE_BY_KEY, f"{c.name} cites '{key}', which is not in the table"


def test_every_unsupported_claim_says_what_would_retire_it():
  """An objection with no stated remedy is a position, not a finding."""
  for c in UNSUPPORTED:
    assert len(c.would_establish_it.strip()) > 40, f"{c.name} states no way to retire itself"
    assert len(c.why_unsupported.strip()) > 200, f"{c.name} asserts rather than argues"


def test_the_production_rate_claim_argues_from_the_specific_shortfalls():
  c = next(c for c in UNSUPPORTED if c.name == "integrated_autonomy_at_production_rates")
  assert "17-day" in c.why_unsupported
  assert "15 hours" in c.why_unsupported
  assert set(c.nearest) >= {"a_lab", "roboculture"}


# -- the report ----------------------------------------------------------------


def test_summary_adds_up():
  s = summary()
  assert s["evidence"] == len(EVIDENCE)
  assert s["confirmed"] + s["partial"] == s["evidence"]
  assert s["demonstrations"] < s["evidence"], "not every citation is a lab that ran"
  assert s["domains_covered"] == len(Domain)
  assert s["unsupported_claims"] == len(UNSUPPORTED)
  assert s["entries_with_unverified_numbers"] >= s["partial"]
