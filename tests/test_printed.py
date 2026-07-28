"""Device-free tests for the printed-fixture fitness layer.

The tests that matter here try to get a printed part reported as fit when it is not, and the
richest source of that is the vacuous pass: a check that passes when handed nothing. A
fixture with no fields set. A fitness computation over a part with no declared dimensions,
where `all()` over an empty tuple is True and a part nobody measured reads as fully measured.
A material with no glass transition on record going into an autoclave check that has nothing
to compare and returns a cheerful default. A designed dimension, which is a number with units
in a document and is a fact about a model rather than about the part that came out.

The other half of the file guards the refusals. Five of them are load-bearing -- a porous
process in a fluid path, an uncleared photopolymer at culture contact, a cycle above the
glass transition, an unmeasured dimension a robot registers against, and an unlocated part
inside a moving envelope -- and each has to keep refusing when the obvious workaround is
applied to it. Post-processing must not clear porosity. Heat deflection must not clear an
autoclave. A benefit claim resting on somebody's opinion must not clear a measurement.
"""

from __future__ import annotations

import pytest

from autonomous_lab import printed
from autonomous_lab.printed import (
  FIXTURES,
  MATERIALS,
  NOT_ESTIMATED,
  POST_PROCESS_EVIDENCE,
  USES,
  Assessment,
  Basis,
  Benefit,
  Contact,
  CriticalDimension,
  DimensionState,
  Fitness,
  Fixture,
  Flange,
  Material,
  Objection,
  PostProcess,
  Process,
  Qualification,
  ResinQualification,
  Sterilization,
  Thermal,
  Use,
  fitness,
  materials_reaching,
  materials_surviving,
  plate_envelope,
  refusals,
  survey,
  unqualified,
)


def _measured(name="d", nominal=10.0, value=9.9, after=True):
  return CriticalDimension(
    name=name,
    nominal_mm=nominal,
    state=DimensionState.MEASURED,
    measured_mm=value,
    measured_after_processing=after,
    instrument="digital caliper",
  )


def _benefit():
  return Benefit(claim="saves a hand motion", measured="40 s over eight runs", basis=Basis.IN_HOUSE)


def _good_fixture(material=None, **kw):
  """A fixture with everything a lab controls already done, so a test can vary one thing."""
  defaults = dict(
    name="controlled",
    material=material if material is not None else MATERIALS["asa_fdm"],
    built_for=Contact.CULTURE_CONTACT,
    dimensions=(_measured(),),
    positively_located=True,
    benefit=_benefit(),
  )
  defaults.update(kw)
  return Fixture(**defaults)


def _benign_use(**kw):
  """The least demanding use this module can express."""
  defaults = dict(
    name="shelf",
    contact=Contact.NONE,
    robot_registers_to_it=False,
    inside_moving_envelope=False,
    sterilization=Sterilization.NONE,
  )
  defaults.update(kw)
  return Use(**defaults)


# -- vacuous passes --------------------------------------------------------------


def test_a_fixture_with_no_fields_set_is_never_fit():
  """The single most important test in the file.

  A dataclass of booleans and empty tuples is the easiest thing in this module to get wrong,
  because every default that reads as True or as 'nothing to check' turns a part nobody has
  built into a part cleared for a deck. Even against the least demanding use expressible
  here, a bare fixture has to come back unfit.
  """
  result = fitness(Fixture(), _benign_use())
  assert not result.fit
  assert result.verdict is not Fitness.FIT
  assert Fitness.MATERIAL_UNDECLARED in result.refusals()
  assert Fitness.BENEFIT_NOT_QUANTIFIED in result.refusals()


def test_a_bare_fixture_is_unqualified_in_every_respect():
  """`unqualified` defaults to everything, so a new print is untrusted the way a new op is."""
  standing = unqualified(Fixture())
  assert set(standing) == set(Qualification)


def test_a_fixture_that_declares_no_dimensions_does_not_read_as_all_measured():
  """`all()` over an empty tuple is True; a part nobody measured must not inherit that."""
  assert not Fixture().dimensions_measured()
  assert Qualification.DIMENSIONS_MEASURED in unqualified(Fixture())

  use = _benign_use(name="gripped", robot_registers_to_it=True)
  result = fitness(Fixture(material=MATERIALS["asa_fdm"]), use)
  assert Fitness.DIMENSION_NOT_MEASURED in result.refusals()
  assert "no critical dimension is declared" in result.all_reasons()[
    result.refusals().index(Fitness.DIMENSION_NOT_MEASURED)
  ]


def test_a_designed_dimension_is_not_a_measured_one():
  designed = CriticalDimension(name="pocket", nominal_mm=128.5)
  assert designed.state is DimensionState.DESIGNED
  assert not designed.state.measured
  assert designed.deviation_mm() is None
  assert designed.deviation_percent() is None

  fixture = _good_fixture(dimensions=(designed,))
  assert not fixture.dimensions_measured()
  result = fitness(fixture, _benign_use(robot_registers_to_it=True))
  assert Fitness.DIMENSION_NOT_MEASURED in result.refusals()


def test_an_unchecked_dimension_is_not_a_measured_one_either():
  unchecked = CriticalDimension(
    name="pocket", nominal_mm=128.5, state=DimensionState.UNCHECKED
  )
  assert not unchecked.state.measured
  assert not _good_fixture(dimensions=(unchecked,)).dimensions_measured()


def test_a_dimension_cannot_claim_measured_without_a_number():
  with pytest.raises(ValueError, match="carries no measured value"):
    CriticalDimension(name="pocket", nominal_mm=10.0, state=DimensionState.MEASURED)


def test_a_dimension_cannot_claim_measured_without_naming_an_instrument():
  with pytest.raises(ValueError, match="names no instrument"):
    CriticalDimension(
      name="pocket", nominal_mm=10.0, state=DimensionState.MEASURED, measured_mm=9.9
    )


def test_a_designed_dimension_cannot_carry_a_measured_number():
  """The ambiguity from the other side: a value present under a state that did not earn it."""
  with pytest.raises(ValueError, match="carries a measured value"):
    CriticalDimension(name="pocket", nominal_mm=10.0, measured_mm=9.9)


def test_an_unmeasured_dimension_cannot_claim_it_was_measured_after_processing():
  with pytest.raises(ValueError, match="nothing was measured at all"):
    CriticalDimension(name="pocket", nominal_mm=10.0, measured_after_processing=True)


def test_a_material_with_unknown_tg_does_not_pass_an_autoclave_check():
  """The other headline vacuous pass: nothing to compare, so nothing refuses.

  Two real materials sit in this state -- a polycarbonate blend whose sheet publishes heat
  deflection at two loads and no glass transition, and a polypropylene copolymer whose sheet
  publishes only a melting point. Both would sail through a check that skipped what it could
  not evaluate.
  """
  for key in ("pc_blend_fdm", "pp_copolymer_fdm", "photopolymer_certified", "machined_stock"):
    mat = MATERIALS[key]
    assert mat.tg is None
    ok, why = mat.survives(Sterilization.AUTOCLAVE_121)
    assert ok is None, f"{key} must not return a boolean verdict on a threshold it does not have"
    assert "no glass transition is on record" in why

    result = fitness(
      _good_fixture(material=mat), _benign_use(sterilization=Sterilization.AUTOCLAVE_121)
    )
    assert Fitness.THERMAL_LIMIT_UNKNOWN in result.refusals()
    assert not result.fit


def test_a_material_with_unknown_tg_is_not_listed_as_surviving():
  surviving = {m.name for m in materials_surviving(Sterilization.AUTOCLAVE_121)}
  assert MATERIALS["pc_blend_fdm"].name not in surviving
  assert MATERIALS["pp_copolymer_fdm"].name not in surviving


def test_a_fixture_cannot_declare_itself_fit():
  """There is no field that sets fitness; it is only ever computed, per use.

  The same rule the ledger applies to automation and `qc` applies to gate readiness. If this
  ever fails, somebody has added an override and the report can be made to lie.
  """
  fixture = FIXTURES["plate_nest_as_printed"]
  assert not hasattr(fixture, "fit")
  assert not hasattr(fixture, "fitness")
  assert not hasattr(fixture, "verdict")


def test_a_benefit_nobody_measured_is_not_quantified():
  assert not Benefit(claim="feels faster").quantified
  claimed = Benefit(claim="faster", measured="a forum post says 30 percent", basis=Basis.LITERATURE)
  assert not claimed.quantified, "somebody else's measurement is not a measurement of this part"
  assert Benefit(claim="faster", measured="40 s over eight runs", basis=Basis.IN_HOUSE).quantified


def test_an_unquantified_benefit_refuses_even_a_perfect_part():
  result = fitness(_good_fixture(benefit=None), _benign_use())
  assert Fitness.BENEFIT_NOT_QUANTIFIED in result.refusals()
  assert not result.fit


def test_no_threshold_in_the_catalog_is_validated_here():
  """Every figure is a datasheet figure, and a datasheet is not evidence about your part."""
  assert survey()["validated_thresholds"] == 0
  for mat in MATERIALS.values():
    for thermal in (mat.tg, mat.hdt, mat.melt):
      if thermal is not None:
        assert not thermal.basis.validated
        assert thermal.method, "a temperature with no test method behind it is not a threshold"


# -- refusal 1: a porous process in the fluid path --------------------------------


def test_fdm_at_sample_contact_is_refused():
  result = fitness(_good_fixture(), Use(name="trough", contact=Contact.SAMPLE_CONTACT))
  assert Fitness.POROUS_PROCESS_IN_FLUID_PATH in result.refusals()
  assert result.needs_a_different_part


def test_fdm_at_culture_contact_is_refused():
  result = fitness(_good_fixture(), Use(name="insert", contact=Contact.CULTURE_CONTACT))
  assert Fitness.POROUS_PROCESS_IN_FLUID_PATH in result.refusals()


def test_fdm_below_the_fluid_path_is_not_refused_for_porosity():
  """The gate is drawn at intended contact, not at proximity, so a bracket is not refused."""
  for contact in (Contact.NONE, Contact.INCIDENTAL):
    result = fitness(_good_fixture(), _benign_use(contact=contact))
    assert Fitness.POROUS_PROCESS_IN_FLUID_PATH not in result.refusals()


def test_no_post_processing_clears_the_porosity_refusal():
  """The workaround every lab reaches for, refused per treatment with what it actually showed."""
  for treatment in PostProcess:
    assert not treatment.closes_the_fluid_path
    fixture = _good_fixture(post_processing=(treatment,))
    result = fitness(fixture, Use(name="trough", contact=Contact.SAMPLE_CONTACT))
    assert Fitness.POROUS_PROCESS_IN_FLUID_PATH in result.refusals()
    detail = result.all_reasons()[result.refusals().index(Fitness.POROUS_PROCESS_IN_FLUID_PATH)]
    assert treatment.value in detail, "the refusal must name the claimed fix it is rejecting"


def test_every_post_process_carries_what_it_was_actually_shown_to_do():
  for treatment in PostProcess:
    assert treatment in POST_PROCESS_EVIDENCE
    assert POST_PROCESS_EVIDENCE[treatment].strip()


def test_the_porosity_refusal_is_structural():
  """No measurement, procedure or purchase clears it for the part as built."""
  assert Fitness.POROUS_PROCESS_IN_FLUID_PATH.structural
  result = fitness(_good_fixture(), Use(name="trough", contact=Contact.SAMPLE_CONTACT))
  assert result.needs_a_different_part


def test_an_uncharacterized_process_is_refused_on_a_different_ground():
  """Measured-porous and never-measured cost different things to clear and must not collapse."""
  assert not Process.SLS.cleanable_in_principle
  assert not Process.SLS.porosity_characterized
  assert Process.FDM.porosity_characterized

  powder = Material(
    name="a powder-bed part", process=Process.SLS, ceiling=Contact.CULTURE_CONTACT
  )
  result = fitness(_good_fixture(material=powder), Use(name="trough", contact=Contact.SAMPLE_CONTACT))
  assert Fitness.UNCHARACTERIZED_PROCESS in result.refusals()
  assert Fitness.POROUS_PROCESS_IN_FLUID_PATH not in result.refusals()
  assert not Fitness.UNCHARACTERIZED_PROCESS.structural


def test_no_sls_material_is_declared_here():
  """The enum member exists and no material claims it, because nothing here measured one."""
  assert not any(m.process is Process.SLS for m in MATERIALS.values())


# -- refusal 2: photopolymer at culture contact -----------------------------------


def test_photopolymer_at_culture_contact_without_a_certified_resin_is_refused():
  fixture = _good_fixture(
    material=MATERIALS["photopolymer_certified"],
    resin=ResinQualification(
      certified_biocompatible=False, workflow_as_certified=True, post_cure_validated=True
    ),
  )
  result = fitness(fixture, Use(name="insert", contact=Contact.CULTURE_CONTACT))
  assert Fitness.CYTOTOXICITY_UNCLEARED in result.refusals()
  detail = result.all_reasons()[result.refusals().index(Fitness.CYTOTOXICITY_UNCLEARED)]
  assert "no certified biocompatible resin" in detail


def test_photopolymer_at_culture_contact_without_a_validated_post_cure_is_refused():
  fixture = _good_fixture(
    material=MATERIALS["photopolymer_certified"],
    resin=ResinQualification(
      certified_biocompatible=True, workflow_as_certified=True, post_cure_validated=False
    ),
  )
  result = fitness(fixture, Use(name="insert", contact=Contact.CULTURE_CONTACT))
  assert Fitness.CYTOTOXICITY_UNCLEARED in result.refusals()
  assert "no validated post-cure" in result.reason


def test_a_certified_resin_made_outside_the_certified_workflow_is_refused():
  """The certification is measured on one printer, one wash and one cure. That is the article."""
  fixture = _good_fixture(
    material=MATERIALS["photopolymer_certified"],
    resin=ResinQualification(
      certified_biocompatible=True, workflow_as_certified=False, post_cure_validated=True
    ),
  )
  result = fitness(fixture, Use(name="insert", contact=Contact.CULTURE_CONTACT))
  assert Fitness.CYTOTOXICITY_UNCLEARED in result.refusals()
  assert "not made by the workflow" in result.reason


def test_a_default_resin_qualification_clears_nothing():
  assert not ResinQualification().cleared_for_culture
  assert len(ResinQualification().missing()) == 3


def test_a_fully_cleared_photopolymer_passes_the_cytotoxicity_ground():
  """The module is not a machine that always says no; the path exists and it is narrow."""
  fixture = _good_fixture(
    material=MATERIALS["photopolymer_certified"],
    resin=ResinQualification(
      certified_biocompatible=True, workflow_as_certified=True, post_cure_validated=True
    ),
  )
  result = fitness(fixture, Use(name="insert", contact=Contact.CULTURE_CONTACT))
  assert Fitness.CYTOTOXICITY_UNCLEARED not in result.refusals()
  assert Fitness.POROUS_PROCESS_IN_FLUID_PATH not in result.refusals()
  assert result.fit


def test_an_uncertified_photopolymer_is_refused_by_its_ceiling_as_well():
  fixture = _good_fixture(
    material=MATERIALS["photopolymer_uncertified"],
    resin=ResinQualification(True, True, True),
  )
  result = fitness(fixture, Use(name="insert", contact=Contact.CULTURE_CONTACT))
  assert Fitness.ABOVE_MATERIAL_CEILING in result.refusals()


# -- refusal 3: an autoclave above the glass transition ---------------------------


def test_autoclaving_a_material_whose_tg_is_below_the_cycle_is_refused():
  for key in ("pla_fdm", "petg_fdm", "abs_fdm", "asa_fdm"):
    mat = MATERIALS[key]
    for cycle in (Sterilization.AUTOCLAVE_121, Sterilization.AUTOCLAVE_134):
      ok, _why = mat.survives(cycle)
      assert ok is False, f"{key} must not clear {cycle.value}"
      result = fitness(_good_fixture(material=mat), _benign_use(sterilization=cycle))
      assert Fitness.SOFTENS_IN_THE_CYCLE in result.refusals()


def test_the_autoclave_check_reads_tg_and_not_hdt():
  """The material that makes the rule concrete: HDT clears 121 C by 49 C and Tg fails it by 51.

  A carbon-fiber nylon carries a published heat deflection temperature of 170 to 194 C on top
  of a glass transition of 70 C, because the filler carries the load the matrix no longer can.
  A check that read the HDT column would wave this part into a cycle it cannot survive.
  """
  mat = MATERIALS["pa_cf_fdm"]
  assert mat.hdt is not None and mat.hdt.conservative() > 121.0
  assert mat.tg is not None and mat.tg.conservative() < 121.0
  ok, why = mat.survives(Sterilization.AUTOCLAVE_121)
  assert ok is False
  assert "glass transition" in why


def test_the_high_temperature_polymers_clear_the_cycle_thermally():
  for key in ("pei_9085_fdm", "pei_1010_fdm", "peek_fdm"):
    assert MATERIALS[key].survives(Sterilization.AUTOCLAVE_134)[0] is True


def test_a_non_thermal_method_does_not_invoke_the_thermal_gate():
  for method in (Sterilization.NONE, Sterilization.SINGLE_USE, Sterilization.IPA_WIPE):
    assert not method.thermal
    assert method.cycle_c is None
    result = fitness(_good_fixture(material=MATERIALS["pla_fdm"]), _benign_use(sterilization=method))
    assert Fitness.SOFTENS_IN_THE_CYCLE not in result.refusals()
    assert Fitness.THERMAL_LIMIT_UNKNOWN not in result.refusals()


def test_a_thermal_range_uses_its_low_end_for_the_gate():
  """Half the possible parts are past the line if the gate reads the middle of the spread."""
  band = Thermal(54.0, 61.0, "DSC 10 C/min", Basis.VENDOR)
  assert band.conservative() == 54.0
  assert band.spread_c == 7.0


def test_an_inverted_thermal_range_is_refused():
  with pytest.raises(ValueError, match="below low"):
    Thermal(120.0, 90.0, "DSC", Basis.VENDOR)


# -- refusal 4: an unmeasured dimension where a robot registers -------------------


def test_an_unmeasured_dimension_is_refused_where_a_robot_registers_to_it():
  fixture = _good_fixture(dimensions=(CriticalDimension(name="pocket", nominal_mm=128.5),))
  result = fitness(fixture, _benign_use(robot_registers_to_it=True))
  assert Fitness.DIMENSION_NOT_MEASURED in result.refusals()
  assert "pocket" in result.reason


def test_a_partially_measured_set_of_dimensions_does_not_pass_on_the_half_that_was_measured():
  fixture = _good_fixture(
    dimensions=(_measured(name="pitch"), CriticalDimension(name="offset", nominal_mm=22.0))
  )
  assert not fixture.dimensions_measured()
  result = fitness(fixture, _benign_use(robot_registers_to_it=True))
  detail = result.all_reasons()[result.refusals().index(Fitness.DIMENSION_NOT_MEASURED)]
  assert "offset" in detail
  assert "pitch" not in detail


def test_a_measured_dimension_clears_the_gate():
  result = fitness(_good_fixture(), _benign_use(robot_registers_to_it=True))
  assert Fitness.DIMENSION_NOT_MEASURED not in result.refusals()
  assert result.fit


def test_a_dimension_measured_before_a_thermal_cycle_is_stale():
  """Thermal and coating steps move printed parts by percent, and the sign depends on the axis."""
  fixture = _good_fixture(
    material=MATERIALS["pei_1010_fdm"], dimensions=(_measured(name="pitch", after=False),)
  )
  result = fitness(
    fixture, _benign_use(robot_registers_to_it=True, sterilization=Sterilization.AUTOCLAVE_134)
  )
  assert Fitness.DIMENSION_STALE_AFTER_CYCLE in result.refusals()


def test_a_dimension_measured_before_a_dimension_changing_post_process_is_stale():
  fixture = _good_fixture(
    dimensions=(_measured(name="pitch", after=False),), post_processing=(PostProcess.ANNEALING,)
  )
  result = fitness(fixture, _benign_use(robot_registers_to_it=True))
  assert Fitness.DIMENSION_STALE_AFTER_CYCLE in result.refusals()


def test_nothing_that_moves_dimensions_means_nothing_is_stale():
  """Staleness must be computed from something that actually happened, not asserted."""
  fixture = _good_fixture(
    dimensions=(_measured(name="pitch", after=False),),
    post_processing=(PostProcess.SOLVENT_EXTRACTION,),
  )
  assert fixture.stale_dimensions(thermally_cycled=False) == ()
  result = fitness(fixture, _benign_use(robot_registers_to_it=True))
  assert Fitness.DIMENSION_STALE_AFTER_CYCLE not in result.refusals()


def test_a_dimension_gate_is_not_invoked_where_nothing_registers_to_the_part():
  fixture = _good_fixture(dimensions=())
  result = fitness(fixture, _benign_use(robot_registers_to_it=False))
  assert Fitness.DIMENSION_NOT_MEASURED not in result.refusals()


# -- refusal 5: an unlocated part inside a moving envelope ------------------------


def test_an_unlocated_fixture_inside_a_moving_envelope_is_refused():
  fixture = _good_fixture(positively_located=False)
  result = fitness(fixture, _benign_use(inside_moving_envelope=True))
  assert Fitness.NOT_POSITIVELY_LOCATED in result.refusals()
  assert "crash" in result.reason


def test_an_unlocated_fixture_outside_any_envelope_is_not_refused_for_location():
  fixture = _good_fixture(positively_located=False)
  result = fitness(fixture, _benign_use(inside_moving_envelope=False))
  assert Fitness.NOT_POSITIVELY_LOCATED not in result.refusals()


def test_a_use_defaults_to_the_demanding_geometry():
  """An under-specified use must not clear checks it never faced."""
  use = Use(name="unspecified", contact=Contact.NONE)
  assert use.inside_moving_envelope
  assert use.robot_registers_to_it


# -- the contact ladder ----------------------------------------------------------


def test_contact_levels_are_ordered_and_the_fluid_path_line_is_where_it_says():
  order = [Contact.NONE, Contact.INCIDENTAL, Contact.SAMPLE_CONTACT, Contact.CULTURE_CONTACT]
  assert [c.rank for c in order] == [0, 1, 2, 3]
  assert not Contact.NONE.in_the_fluid_path
  assert not Contact.INCIDENTAL.in_the_fluid_path
  assert Contact.SAMPLE_CONTACT.in_the_fluid_path
  assert Contact.CULTURE_CONTACT.in_the_fluid_path


def test_a_part_used_above_what_it_was_built_for_is_refused():
  fixture = _good_fixture(built_for=Contact.INCIDENTAL, material=MATERIALS["machined_stock"])
  result = fitness(fixture, Use(name="trough", contact=Contact.SAMPLE_CONTACT))
  assert Fitness.ABOVE_DECLARED_CONTACT in result.refusals()


def test_a_part_used_at_or_below_what_it_was_built_for_is_not_refused_for_that():
  fixture = _good_fixture(built_for=Contact.SAMPLE_CONTACT, material=MATERIALS["machined_stock"])
  result = fitness(fixture, Use(name="trough", contact=Contact.SAMPLE_CONTACT))
  assert Fitness.ABOVE_DECLARED_CONTACT not in result.refusals()


def test_the_material_ceiling_and_the_declared_contact_are_separate_refusals():
  """One is a fact about the polymer and the process; the other is about what was designed."""
  fixture = _good_fixture(built_for=Contact.NONE, material=MATERIALS["pla_fdm"])
  result = fitness(fixture, Use(name="insert", contact=Contact.CULTURE_CONTACT))
  assert Fitness.ABOVE_MATERIAL_CEILING in result.refusals()
  assert Fitness.ABOVE_DECLARED_CONTACT in result.refusals()


# -- how refusals are reported ----------------------------------------------------


def test_every_refusal_is_carried_not_just_the_first():
  """A printed part is usually wrong in several ways, and fixing the headline reveals the next."""
  result = fitness(Fixture(), Use(name="insert", contact=Contact.CULTURE_CONTACT))
  assert len(result.objections) >= 4
  assert result.verdict is result.objections[0].reason
  assert len(result.all_reasons()) == len(result.objections)


def test_structural_refusals_are_reported_ahead_of_the_ones_money_can_move():
  fixture = _good_fixture(built_for=Contact.NONE, positively_located=False, benefit=None)
  result = fitness(
    fixture,
    Use(name="trough", contact=Contact.SAMPLE_CONTACT, sterilization=Sterilization.AUTOCLAVE_121),
  )
  reasons = result.refusals()
  assert Fitness.POROUS_PROCESS_IN_FLUID_PATH in reasons
  assert Fitness.NOT_POSITIVELY_LOCATED in reasons
  assert reasons.index(Fitness.POROUS_PROCESS_IN_FLUID_PATH) < reasons.index(
    Fitness.NOT_POSITIVELY_LOCATED
  )
  assert result.verdict.structural


def test_only_the_two_refusals_a_different_part_fixes_are_structural():
  structural = {f for f in Fitness if f.structural}
  assert structural == {Fitness.POROUS_PROCESS_IN_FLUID_PATH, Fitness.SOFTENS_IN_THE_CYCLE}
  assert not Fitness.FIT.structural


def test_fit_is_the_absence_of_refusals_and_nothing_sets_it():
  empty = Assessment(fixture=Fixture(), use=_benign_use(), objections=())
  assert empty.verdict is Fitness.FIT
  assert empty.fit
  assert Fitness.FIT.usable
  assert not empty.needs_a_different_part

  one = Assessment(
    fixture=Fixture(), use=_benign_use(), objections=(Objection(Fitness.BENEFIT_NOT_QUANTIFIED, "x"),)
  )
  assert not one.fit
  assert not one.verdict.usable


def test_fitness_is_computed_per_use_and_does_not_transfer():
  """The same part is fit as a bracket and unfit as a reservoir."""
  bracket = FIXTURES["sensor_bracket_asa"]
  assert fitness(bracket, USES["deck_bracket"]).fit
  assert not fitness(bracket, USES["shared_reagent_trough"]).fit


# -- the catalog's findings --------------------------------------------------------


def test_no_fdm_material_reaches_sample_contact():
  """Thermal capability does not buy a fluid path, and the two are easy to conflate."""
  for mat in MATERIALS.values():
    if mat.process is Process.FDM:
      assert mat.ceiling.rank < Contact.SAMPLE_CONTACT.rank, mat.name


def test_the_polymers_that_survive_steam_still_do_not_reach_sample_contact():
  for mat in materials_surviving(Sterilization.AUTOCLAVE_134):
    assert mat.process is Process.FDM
    assert not mat.ceiling.in_the_fluid_path


def test_nothing_here_is_both_autoclavable_and_sample_contact_capable():
  """The finding this catalog exists to produce, pinned so a regression is loud."""
  assert survey()["autoclavable_and_sample_contact"] == 0
  autoclavable = {m.name for m in materials_surviving(Sterilization.AUTOCLAVE_121)}
  sample = {m.name for m in materials_reaching(Contact.SAMPLE_CONTACT)}
  assert autoclavable and sample
  assert not (autoclavable & sample)


def test_a_new_print_is_untrusted():
  result = fitness(FIXTURES["plate_nest_as_printed"], USES["plate_nest"])
  assert not result.fit
  assert set(result.refusals()) == {
    Fitness.ABOVE_DECLARED_CONTACT,
    Fitness.NOT_POSITIVELY_LOCATED,
    Fitness.DIMENSION_NOT_MEASURED,
    Fitness.BENEFIT_NOT_QUANTIFIED,
  }
  assert not result.needs_a_different_part, "every one of those is work, not a different part"


def test_a_well_built_part_can_still_be_refused_structurally():
  """Everything a lab controls, done, and the process is still the refusal."""
  fixture = FIXTURES["reagent_trough_petg"]
  assert fixture.positively_located
  assert fixture.dimensions_measured()
  assert fixture.benefit is not None and fixture.benefit.quantified
  result = fitness(fixture, USES["shared_reagent_trough"])
  assert result.verdict is Fitness.POROUS_PROCESS_IN_FLUID_PATH
  assert result.needs_a_different_part


def test_a_structural_bracket_reaches_fit():
  result = fitness(FIXTURES["sensor_bracket_asa"], USES["deck_bracket"])
  assert result.fit
  assert result.verdict is Fitness.FIT
  assert "for no other use" in result.reason


def test_a_fit_part_is_still_unqualified_in_the_wet_bench_respects():
  """FIT is fitness for a use, not a clean bill. Four qualifications this module cannot see."""
  standing = unqualified(FIXTURES["sensor_bracket_asa"])
  assert set(standing) == {
    Qualification.CLEANABILITY,
    Qualification.LEACHABLES,
    Qualification.STERILITY,
    Qualification.THERMAL_ON_THIS_PART,
  }


# -- the microplate envelope -------------------------------------------------------


def test_a_nest_must_clear_the_loose_mid_side_tolerance_not_the_famous_one():
  """The commonly quoted tolerance holds only within 12.7 mm of the four outside corners."""
  env = plate_envelope(Flange.MEDIUM)
  assert env.max_length_mm == pytest.approx(128.26)
  assert env.max_width_mm == pytest.approx(85.98)
  assert env.max_length_mm > 127.76 + 0.25


def test_the_corner_relief_uses_the_maximum_radius_not_the_nominal():
  """The permitted range spans 1.58 to 4.78 mm; a nest cut to 3.18 binds on the upper end."""
  assert plate_envelope(Flange.SHORT).max_corner_radius_mm == pytest.approx(4.78)


def test_an_undeclared_flange_variant_refuses_to_emit_a_number():
  env = plate_envelope()
  assert not env.flange_known
  assert env.flange_low_mm is None and env.flange_high_mm is None
  assert "no flange variant is declared" in env.note
  assert not Flange.UNDECLARED.declared


def test_a_declared_flange_variant_emits_its_band():
  env = plate_envelope(Flange.TALL)
  assert env.flange_known
  assert env.flange_low_mm == pytest.approx(7.24)
  assert env.flange_high_mm == pytest.approx(8.00)


def test_the_dual_variant_reports_two_sides_rather_than_a_tolerance_band():
  env = plate_envelope(Flange.DUAL)
  assert env.flange_low_mm == pytest.approx(2.03)
  assert env.flange_high_mm == pytest.approx(8.00)
  assert "different SIDES" in env.note


def test_no_height_is_emitted_for_a_plate_that_is_not_a_standard_height_microplate():
  """Deep-well, PCR and reservoir plates keep the footprint and abandon the height."""
  assert plate_envelope(Flange.MEDIUM).max_height_mm is None
  assert plate_envelope(Flange.MEDIUM, typical_height=True).max_height_mm == pytest.approx(15.11)


def test_the_envelope_says_dimensional_conformity_is_not_contact_fitness():
  for flange in (Flange.UNDECLARED, Flange.SHORT, Flange.DUAL):
    assert "not evidence of fitness for contact" in plate_envelope(flange).note


# -- the refusal to estimate --------------------------------------------------------


def test_the_module_returns_no_lifetime_leachable_rate_or_probability():
  """Guards the discipline the docstring claims, in the only way that stays true under edits."""
  forbidden = (
    "predict",
    "estimate",
    "lifetime",
    "remaining_life",
    "expected",
    "probability",
    "likely",
    "cycles_survived",
    "leachable_rate",
  )
  # The refusal ledger is allowed to name the quantities it declines to return; nothing else is.
  for name in printed.__all__:
    if name in ("NOT_ESTIMATED", "refusals"):
      continue
    lowered = name.lower()
    for token in forbidden:
      assert token not in lowered, f"'{name}' looks like a predicted quantity"


def test_every_refusal_names_what_it_would_take_to_lift_it():
  assert refusals() is NOT_ESTIMATED
  assert len(NOT_ESTIMATED) >= 5
  quantities = {r.quantity for r in NOT_ESTIMATED}
  assert "autoclave cycles survived" in quantities
  assert "leachable release rate or concentration" in quantities
  assert "part service life" in quantities
  for r in NOT_ESTIMATED:
    assert r.why.strip()
    assert r.what_it_would_take.strip()


def test_no_cycle_count_is_published_anywhere_in_the_catalog():
  """Every specific count located for these polymers traced to commercial aggregator pages."""
  for mat in MATERIALS.values():
    text = " ".join(filter(None, (mat.note, mat.chemistry))).lower()
    for claim in ("cycles at", "autoclave cycles", "1,000", "2,000", "3000"):
      assert claim not in text, f"{mat.name} carries an unsourced cycle count"
