"""Device-free tests for the feedback layer.

The tests that matter here try to get a loop reported as closed when it is not. Four ways
that happens, and they are kept apart on purpose because they cost four different things to
fix: the sensor sits downstream of the actuator so the correction never reaches the material,
nothing declares what good is so there is nothing to steer toward, the number comes from a
step that produces nothing, and the controller is weaker than the correction it would make.
Collapsing any two of those into one verdict would send a lab to spend one budget on two
problems.

The other half of the file guards the refusal. This module must not start returning a gain,
a time constant, or a settling time, because it has no plant model and no measured response
data, and a number of that shape is exactly the kind that gets quoted into a specification.
"""

from __future__ import annotations

from enum import Enum

import pytest

from autonomous_lab import Workcell, build_ledger, protocols
from autonomous_lab.model import Artifact, Protocol, Step, Verdict, ZeroDecodeOp
from autonomous_lab.qc import (
  GATES,
  MEASUREMENTS,
  PROTOCOL_GATES,
  Basis,
)
from autonomous_lab.workcell import InstrumentConfig
from autonomous_lab import feedback
from autonomous_lab.feedback import (
  LOOPS,
  NOT_MODELLED,
  Closable,
  Closure,
  Controller,
  Correction,
  Envelope,
  Loop,
  can_close,
  envelope_from_criterion,
  feedback_report,
  in_flight_exposure,
  ungated_protocols,
)


# -- fixtures ------------------------------------------------------------------


# The quantity the fixture protocols genuinely sense. qc declares it, qc says it arrives on
# the artifact 'run_outcome', and the fixture's sensor step is the step that produces that
# artifact -- so a loop built out of these has a real sensor-to-quantity relationship rather
# than an author's say-so. A fixture sensing a name qc has never heard of, off a step that
# produces nothing, is the counterexample this module exists to refuse, and a suite whose
# definition of "well formed" was that shape could not catch it.
SENSED = "run_yield_pf"


def _env(quantity=SENSED, lower=0.5, upper=None, basis=Basis.IN_HOUSE):
  """Units come from qc for any quantity qc declares, and are invented only where it cannot."""
  if quantity in MEASUREMENTS:
    return Envelope.for_quantity(quantity, lower=lower, upper=upper, basis=basis)
  return Envelope(quantity=quantity, units="u", lower=lower, upper=upper, basis=basis)


def _loop(
  measured_at,
  corrects,
  envelope=None,
  correction=Correction.HOLD,
  applied_by=Controller.CODED,
  quantity=SENSED,
  name="test_loop",
):
  return Loop(
    name=name,
    quantity=quantity,
    measured_at=measured_at,
    corrects=corrects,
    correction=correction,
    applied_by=applied_by,
    envelope=envelope,
  )


def _sensor_then_actuator():
  """Every step headless AND the sensor genuinely produces the quantity's artifact.

  Both halves matter. Headless means the ledger cannot be what refuses a loop here, and the
  sensor producing 'run_outcome' means qc's own resolution of run_yield_pf lands on this
  step, so nothing but the loop can be at fault.
  """
  return Protocol(
    name="tiny",
    summary="test",
    artifacts=(Artifact("run_outcome", note="run state and outcome, read off the folder"),),
    steps=(
      Step(
        instrument="element_aviti",
        op=ZeroDecodeOp.WATCH_RUN_FOLDER.value,
        summary="sensor",
        produces=("run_outcome",),
        params={"run_dir": "/tmp/x"},
      ),
      Step(instrument="element_aviti", op=ZeroDecodeOp.PROBE_HTTP.value, summary="actuator"),
    ),
  )


def _actuator_then_sensor():
  """The same two steps with the sensor after the actuator, so only the ORDER is wrong.

  Kept apart from the well-formed fixture rather than expressed by swapping a loop's two
  arguments, because the sensor has to stay the step that really produces the number for the
  lateness refusal to be the only thing under test.
  """
  return Protocol(
    name="tiny",
    summary="test",
    artifacts=(Artifact("run_outcome", note="run state and outcome, read off the folder"),),
    steps=(
      Step(instrument="element_aviti", op=ZeroDecodeOp.PROBE_HTTP.value, summary="actuator"),
      Step(
        instrument="element_aviti",
        op=ZeroDecodeOp.WATCH_RUN_FOLDER.value,
        summary="sensor",
        produces=("run_outcome",),
        params={"run_dir": "/tmp/x"},
      ),
    ),
  )


def _two_automated_steps():
  return _sensor_then_actuator()


def _three_automated_steps():
  return Protocol(
    name="tiny3",
    summary="test",
    artifacts=(Artifact("run_outcome", note="run state and outcome, read off the folder"),),
    steps=(
      Step(
        instrument="element_aviti",
        op=ZeroDecodeOp.WATCH_RUN_FOLDER.value,
        summary="sensor",
        produces=("run_outcome",),
        params={"run_dir": "/tmp/x"},
      ),
      Step(instrument="namocell", op=ZeroDecodeOp.DISCOVER_USB.value, summary="in between"),
      Step(instrument="element_aviti", op=ZeroDecodeOp.PROBE_HTTP.value, summary="actuator"),
    ),
  )


def _blocked_sensor_protocol():
  """A sensor step the workcell cannot drive, sitting after the step it would correct.

  The sort produces 'sorted_plate', which is where qc says well_occupancy comes from, so
  this loop's sensor is real and every one of its four refusals is earned somewhere else.
  """
  return Protocol(
    name="blocked",
    summary="test",
    artifacts=(Artifact("sorted_plate", physical=True, note="96-well, one cell per well"),),
    steps=(
      Step(instrument="namocell", op=ZeroDecodeOp.DISCOVER_USB.value, summary="actuator"),
      Step(
        instrument="namocell",
        op="start_sort",
        summary="sensor",
        produces=("sorted_plate",),
      ),
    ),
  )


def _costed(protocol, wc=None):
  wc = wc or Workcell.default()
  return protocol, build_ledger(protocol, wc)


# -- the positive control ------------------------------------------------------
# Without this the whole file could pass by refusing everything, which is the failure mode
# of every checker that has never been shown a case it should accept.


def test_a_well_formed_loop_closes():
  """The positive control, and it has to be a REAL loop or it controls nothing.

  Every leg is checkable against something other than the declaration: the quantity is one
  qc declares, the sensor step is the step that produces the artifact qc says the number
  arrives on, both steps run headless, and a coded controller may stop a line. A positive
  control built on a quantity nothing measures would pass here whether or not the module
  checked the sensor at all, which is exactly how a loop over an unproduced number reports
  itself closed while the suite stays green.
  """
  protocol, ledger = _costed(_two_automated_steps())
  loop = _loop("watch_run_folder", "probe_http", envelope=_env())
  closure = can_close(loop, protocol, ledger)
  assert closure.verdict is Closable.CLOSES
  assert closure.closes
  assert closure.blockers == ()

  # The control is only a control while these hold: qc knows the quantity, and the step the
  # loop names is the one the protocol produces its artifact at.
  assert loop.quantity in MEASUREMENTS
  produced_by = MEASUREMENTS[loop.quantity].produced_by
  sensor = next(s for s in protocol.steps if s.op == loop.measured_at)
  assert produced_by in sensor.produces


# -- refusal one: the sensor is downstream of the actuator ---------------------


def test_a_sensor_downstream_of_its_actuator_is_refused_with_that_reason():
  """The load-bearing check. A measurement taken after the correction point steers nothing.

  Everything else about this loop is right: it has an envelope, both steps run headless, a
  coded controller may make the correction, and the sensor really is the step that produces
  the number. The only thing wrong is the order, and the order alone must refuse it.
  """
  protocol, ledger = _costed(_actuator_then_sensor())
  loop = _loop("watch_run_folder", "probe_http", envelope=_env())
  closure = can_close(loop, protocol, ledger)
  assert closure.verdict is Closable.OPEN_LOOP_SENSOR_TOO_LATE
  assert not closure.closes
  assert closure.blockers == closure.blockers[:1], "no other leg of this loop is broken"


def test_the_structural_refusal_is_the_one_no_purchase_moves():
  assert Closable.OPEN_LOOP_SENSOR_TOO_LATE.structural
  assert not Closable.NO_ENVELOPE.structural
  assert not Closable.UNAVAILABLE_MEASUREMENT.structural
  assert not Closable.UNPERMITTED_CORRECTION.structural


def test_measuring_at_the_step_being_corrected_is_open_too():
  """A step is atomic here, so a correction applied inside one is not visible to this layer.

  Reported as open rather than closed, because claiming a loop closes on a mechanism the
  package does not model is the same overclaim as calling an unbenchmarked robot trusted.
  """
  protocol, ledger = _costed(_two_automated_steps())
  loop = _loop("watch_run_folder", "watch_run_folder", envelope=_env())
  closure = can_close(loop, protocol, ledger)
  assert closure.verdict is Closable.OPEN_LOOP_SENSOR_TOO_LATE
  assert "atomic" in closure.reason


# -- refusal two: nothing to steer toward --------------------------------------


def test_a_loop_steering_toward_nothing_is_refused_separately():
  """Distinct from lateness, and fixed by an experiment rather than by a reordering."""
  protocol, ledger = _costed(_two_automated_steps())
  loop = _loop("watch_run_folder", "probe_http", envelope=None)
  closure = can_close(loop, protocol, ledger)
  assert closure.verdict is Closable.NO_ENVELOPE
  assert closure.verdict is not Closable.OPEN_LOOP_SENSOR_TOO_LATE
  assert not closure.closes


def test_absence_of_an_envelope_never_reads_as_a_pass():
  """The skip-that-looks-like-a-pass case, in the shape this module can produce it.

  A loop declaring no target is not a loop with a permissive target. The natural
  implementation checks the envelope only when one is present, and that implementation
  reports every envelope-less loop as closed.
  """
  protocol, ledger = _costed(_two_automated_steps())
  closure = can_close(_loop("watch_run_folder", "probe_http"), protocol, ledger)
  assert not closure.closes
  assert Closable.NO_ENVELOPE in closure.refusals()


def test_an_envelope_bounding_nothing_is_refused_at_construction():
  """An unbounded band contains every value, so a loop over it is in specification forever."""
  with pytest.raises(ValueError, match="bounds nothing"):
    Envelope(quantity="q", units="u")


def test_an_inverted_envelope_is_refused():
  with pytest.raises(ValueError, match="below lower"):
    Envelope(quantity="q", units="u", lower=2.0, upper=1.0)


def test_an_envelope_on_a_neighbouring_quantity_is_not_an_envelope_for_this_one():
  """A declaration that a summary would count and that bounds the wrong thing."""
  protocol, ledger = _costed(_two_automated_steps())
  loop = _loop("watch_run_folder", "probe_http", envelope=_env(quantity="something_else"))
  closure = can_close(loop, protocol, ledger)
  assert closure.verdict is Closable.NO_ENVELOPE
  assert "something_else" in closure.reason


# -- refusal three: the number never arrives -----------------------------------


def test_a_loop_reading_a_step_this_lab_cannot_run_is_refused_with_a_third_reason():
  protocol = protocols.get("single_cell_genomics")
  ledger = build_ledger(protocol)
  closure = can_close(LOOPS["quant_steers_flow_cell_loading"], protocol, ledger)
  assert closure.verdict is Closable.UNAVAILABLE_MEASUREMENT
  assert "read_absorbance" in closure.reason


def test_measurement_availability_is_resolved_from_the_ledger_not_asserted():
  """The same loop, two workcells, two answers -- so nothing here is hard-coded.

  A second implementation of cost_step living in this module would eventually disagree with
  the ledger about whether a step produces a number, and a control layer that disagreed with
  the ledger would be worse than no control layer.
  """
  protocol = _two_automated_steps()
  loop = _loop("watch_run_folder", "probe_http", envelope=_env())

  full = build_ledger(protocol, Workcell.default())
  assert can_close(loop, protocol, full).closes

  bare = Workcell(
    name="bare",
    instruments={"element_aviti": InstrumentConfig(key="element_aviti", present=False)},
  )
  stripped = build_ledger(protocol, bare)
  assert stripped.rows[0].verdict is Verdict.MANUAL
  closure = can_close(loop, protocol, stripped)
  assert closure.verdict is Closable.UNAVAILABLE_MEASUREMENT


def test_a_broken_instrument_and_an_unwired_one_refuse_alike_and_report_differently():
  """Wiring plr-tested in changes the reason and not the verdict.

  Both are UNAVAILABLE_MEASUREMENT because in both cases no number arrives. The reason is
  carried through from the ledger because the next action differs completely: one is a
  checkout path, the other is a deterministic timeout somebody has to debug.
  """
  protocol = protocols.get("single_cell_genomics")
  loop = LOOPS["quant_steers_flow_cell_loading"]

  unwired = build_ledger(protocol)
  wired_wc = Workcell.default()
  wired_wc.plr_tested_root = "/nonexistent/plr-tested"
  wired = build_ledger(protocol, wired_wc)

  reader = next(i for i, s in enumerate(protocol.steps) if s.op == "read_absorbance")
  assert unwired.rows[reader].verdict is Verdict.MANUAL
  assert wired.rows[reader].verdict is Verdict.BROKEN

  assert can_close(loop, protocol, unwired).verdict is Closable.UNAVAILABLE_MEASUREMENT
  wired_closure = can_close(loop, protocol, wired)
  assert wired_closure.verdict is Closable.UNAVAILABLE_MEASUREMENT
  assert "FAILED on the instrument" in wired_closure.reason


# -- refusal four: the controller may not make that correction -----------------


def test_an_unpermitted_correction_is_a_fourth_and_separate_reason():
  protocol, ledger = _costed(_two_automated_steps())
  loop = _loop(
    "watch_run_folder",
    "probe_http",
    envelope=_env(),
    correction=Correction.DISCARD,
    applied_by=Controller.MODEL,
  )
  closure = can_close(loop, protocol, ledger)
  assert closure.verdict is Closable.UNPERMITTED_CORRECTION
  assert "human" in closure.reason


def test_stopping_is_the_only_correction_a_model_may_make_alone():
  """Stopping commits nothing, so the model may do it; everything else spends material."""
  assert Controller.MODEL.may_apply(Correction.HOLD)
  for correction in (Correction.RETUNE, Correction.REPEAT, Correction.DIVERT, Correction.DISCARD):
    assert not Controller.MODEL.may_apply(correction)


def test_only_stopping_is_reversible():
  assert Correction.HOLD.reversible
  for correction in (Correction.RETUNE, Correction.REPEAT, Correction.DIVERT, Correction.DISCARD):
    assert not correction.reversible


def test_authority_may_be_strengthened_and_never_weakened():
  assert Controller.HUMAN.may_apply(Correction.RETUNE)
  assert Controller.CODED.may_apply(Correction.REPEAT)
  assert not Controller.MODEL_PROPOSES.may_apply(Correction.DIVERT)
  assert not Controller.CODED.may_apply(Correction.DISCARD)


def test_a_drafting_model_still_counts_as_a_model_in_the_path():
  assert Controller.MODEL.model_in_path
  assert Controller.MODEL_PROPOSES.model_in_path
  assert not Controller.CODED.model_in_path
  assert not Controller.HUMAN.model_in_path


# -- the four are never collapsed ----------------------------------------------


def test_the_four_refusals_stay_four_distinct_verdicts():
  """Three of these are the ones the module exists to keep apart, and each has its own fix."""
  protocol, ledger = _costed(_two_automated_steps())
  late_protocol, late_ledger = _costed(_actuator_then_sensor())
  late = can_close(
    _loop("watch_run_folder", "probe_http", envelope=_env()), late_protocol, late_ledger
  )
  targetless = can_close(_loop("watch_run_folder", "probe_http"), protocol, ledger)
  unpermitted = can_close(
    _loop(
      "watch_run_folder",
      "probe_http",
      envelope=_env(),
      correction=Correction.DISCARD,
      applied_by=Controller.MODEL,
    ),
    protocol,
    ledger,
  )
  genomics = protocols.get("single_cell_genomics")
  absent = can_close(
    LOOPS["quant_steers_flow_cell_loading"], genomics, build_ledger(genomics)
  )

  verdicts = {late.verdict, targetless.verdict, unpermitted.verdict, absent.verdict}
  assert len(verdicts) == 4
  assert Closable.CLOSES not in verdicts


def test_a_loop_broken_four_ways_reports_all_four_and_headlines_the_structural_one():
  """Reporting only the first refusal is how a lab fixes one and rediscovers the next."""
  protocol, ledger = _costed(_blocked_sensor_protocol())
  loop = _loop(
    "start_sort",
    "discover_usb",
    envelope=None,
    correction=Correction.DISCARD,
    applied_by=Controller.MODEL,
    quantity="well_occupancy",
  )
  closure = can_close(loop, protocol, ledger)
  assert closure.refusals() == (
    Closable.OPEN_LOOP_SENSOR_TOO_LATE,
    Closable.NO_ENVELOPE,
    Closable.UNAVAILABLE_MEASUREMENT,
    Closable.UNPERMITTED_CORRECTION,
  )
  assert closure.verdict is Closable.OPEN_LOOP_SENSOR_TOO_LATE
  assert len(closure.all_reasons()) == 4


# -- nothing here may declare itself closed ------------------------------------


def test_no_field_on_a_loop_declares_it_closed():
  """Closability is computed against a protocol and a ledger, never set by an author.

  The same rule the ledger applies to automation and qc applies to readiness. If this ever
  fails, somebody has added an override and every report in this module can be silenced.
  """
  loop = LOOPS["pooled_quant_steers_pooling"]
  for field in ("closes", "closed", "closable", "verdict", "reason", "blockers"):
    assert field not in Loop.__dataclass_fields__
    assert not hasattr(loop, field)


def test_a_closure_is_derived_from_its_blockers_rather_than_stored_beside_them():
  """A stored verdict sitting next to the blockers it came from eventually disagrees."""
  assert "verdict" not in Closure.__dataclass_fields__
  assert "closes" not in Closure.__dataclass_fields__
  assert isinstance(getattr(Closure, "verdict"), property)


# -- the refusal to invent dynamics --------------------------------------------


def test_nothing_public_offers_a_gain_a_time_constant_or_a_settling_time():
  """No plant model and no measured response data, so no dynamic quantity may be emitted.

  Checked by name across the module surface rather than argued in prose, because the way
  this refusal breaks is somebody adding one convenient helper.
  """
  forbidden = (
    "gain",
    "overshoot",
    "damping",
    "settling",
    "stability",
    "time_constant",
    "timeconstant",
    "tau",
    "rise_time",
    "response_time",
  )
  names = []
  for name, obj in vars(feedback).items():
    if name.startswith("_"):
      continue
    names.append(name)
    if isinstance(obj, type) and getattr(obj, "__module__", "") == feedback.__name__:
      names.extend(k for k in vars(obj) if not k.startswith("_"))
      names.extend(getattr(obj, "__dataclass_fields__", {}))
      if issubclass(obj, Enum):
        names.extend(str(m.value) for m in obj)
  offenders = [n for n in names if any(f in n.lower() for f in forbidden)]
  assert offenders == []


def test_the_quantities_this_module_will_not_emit_are_named():
  """An unstated omission is indistinguishable from an oversight."""
  for quantity in ("gain", "overshoot", "time constant", "settling time"):
    assert quantity in NOT_MODELLED


def test_in_flight_exposure_is_a_plate_count_and_not_a_duration():
  """The honest form of 'how fast can this loop react', in the unit the protocol knows."""
  protocol = _three_automated_steps()
  flight = in_flight_exposure(_loop("watch_run_folder", "probe_http", envelope=_env()), protocol)
  assert flight.steps_between == 1
  assert flight.intervening == ("discover_usb",)
  assert not flight.immediate
  assert "plate" in flight.meaning
  assert "seconds" in flight.meaning and "ever been timed" in flight.meaning
  assert "steps_between" in type(flight).__dataclass_fields__
  assert not any(
    f.endswith("_s") or "seconds" in f for f in type(flight).__dataclass_fields__
  )


def test_a_correction_landing_at_the_next_step_commits_nothing_in_between():
  protocol = _two_automated_steps()
  flight = in_flight_exposure(_loop("watch_run_folder", "probe_http", envelope=_env()), protocol)
  assert flight.steps_between == 0
  assert flight.immediate


def test_in_flight_exposure_refuses_a_loop_that_never_reaches_its_material():
  """Zero would read as the best possible case rather than as the absence of a loop."""
  protocol = _actuator_then_sensor()
  with pytest.raises(ValueError, match="measures at or after"):
    in_flight_exposure(_loop("watch_run_folder", "probe_http", envelope=_env()), protocol)


def test_in_flight_exposure_on_the_real_protocol_counts_protocol_structure():
  protocol = protocols.get("single_cell_genomics")
  flight = in_flight_exposure(LOOPS["occupancy_steers_amplification"], protocol)
  assert flight.steps_between == 1
  assert flight.intervening == ("wait_complete",)


# -- refusing to resolve what it cannot resolve --------------------------------


def test_an_op_used_twice_in_a_flow_is_not_a_position():
  """Picking the first occurrence reports a loop as closed whenever the wrong one is upstream."""
  protocol = protocols.get("single_cell_genomics")
  ledger = build_ledger(protocol)
  loop = _loop("manual_load", "start_run", envelope=_env())
  with pytest.raises(ValueError, match="appears 2 times"):
    can_close(loop, protocol, ledger)


def test_a_loop_naming_a_step_the_protocol_does_not_have_is_refused():
  protocol, ledger = _costed(_two_automated_steps())
  with pytest.raises(KeyError, match="not a step"):
    can_close(_loop("no_such_step", "watch_run_folder", envelope=_env()), protocol, ledger)


def test_a_ledger_built_for_another_protocol_is_refused():
  """A verdict mixed from two protocols describes neither, and would silently use the
  wrong step's verdict for the measurement."""
  protocol = _two_automated_steps()
  other = build_ledger(protocols.get("single_cell_genomics"))
  with pytest.raises(ValueError, match="built for protocol"):
    can_close(_loop("watch_run_folder", "probe_http", envelope=_env()), protocol, other)


# -- envelopes come from qc, never from here -----------------------------------


def test_an_envelope_is_resolved_from_the_qc_criterion_rather_than_restated():
  """Two copies of one cutoff eventually disagree and nothing reveals which is live."""
  gate = GATES["sort_occupancy_before_amplification"]
  criterion = gate.criteria[0]
  envelope = envelope_from_criterion(gate, criterion.name)
  assert envelope.lower == criterion.bound
  assert envelope.quantity == criterion.measurement
  assert envelope.basis is criterion.basis
  assert envelope.units == "fraction"

  declared = LOOPS["occupancy_steers_amplification"].envelope
  assert declared is not None
  assert declared.lower == criterion.bound


def test_a_two_sided_criterion_becomes_a_two_sided_envelope():
  gate = GATES["library_quant_before_flow_cell"]
  envelope = envelope_from_criterion(gate, "not_protein_contaminated")
  assert envelope.lower == 1.7
  assert envelope.upper == 2.1
  assert envelope.contains(1.85)
  assert not envelope.contains(2.5)


def test_an_envelope_over_a_criterion_qc_does_not_declare_is_refused():
  with pytest.raises(KeyError, match="declares no criterion"):
    envelope_from_criterion(GATES["library_quant_before_flow_cell"], "invented")


def test_an_unvalidated_envelope_is_reported_and_does_not_refuse_the_loop():
  """A loop around a vendor cutoff genuinely closes -- it just closes on somebody else's band.

  Making this a fifth refusal would say the fix is the same as for a loop with no target at
  all. It is not: this one needs a titration, and the loop works meanwhile.
  """
  protocol, ledger = _costed(_two_automated_steps())
  loop = _loop("watch_run_folder", "probe_http", envelope=_env(basis=Basis.VENDOR))
  closure = can_close(loop, protocol, ledger)
  assert closure.closes
  assert not loop.envelope.validated


# -- the real protocols --------------------------------------------------------


def test_the_library_quant_cannot_steer_the_pool_it_is_taken_after():
  """The flagship finding, pinned so a regression is loud.

  Normalizing a pool is exactly what a concentration measurement is for, and this protocol
  measures after the pool. Repairing the plate reader does not close this; measuring per
  well before pooling does, and that is a protocol change rather than a purchase.
  """
  protocol = protocols.get("single_cell_genomics")
  ledger = build_ledger(protocol)
  closure = can_close(LOOPS["pooled_quant_steers_pooling"], protocol, ledger)
  assert closure.verdict is Closable.OPEN_LOOP_SENSOR_TOO_LATE
  assert closure.measured_index > closure.corrects_index
  assert "next-run adjustment" in closure.reason


def test_yield_read_off_a_finished_run_is_not_a_control_loop():
  """What a lab means by 'the system learns from its runs'. Real, useful, and not control."""
  protocol = protocols.get("single_cell_genomics")
  ledger = build_ledger(protocol)
  closure = can_close(LOOPS["yield_steers_resequencing"], protocol, ledger)
  assert closure.verdict is Closable.OPEN_LOOP_SENSOR_TOO_LATE


def test_no_declared_loop_closes_in_this_lab_today():
  """The finding this module exists to produce. Every proposed loop fails, for three reasons."""
  protocol = protocols.get("single_cell_genomics")
  report = feedback_report(protocol, build_ledger(protocol))
  assert len(report.rows) == 5
  assert report.closable() == []
  assert not report.closes_any()
  assert len(report.structurally_open()) == 2


def test_the_chemistry_loop_has_no_target_because_qc_declares_no_gate():
  """Resolved from the qc layer rather than asserted here, so it flips when a gate lands."""
  assert PROTOCOL_GATES["small_molecule_qc"] == ()
  assert "small_molecule_qc" in ungated_protocols()
  protocol = protocols.get("small_molecule_qc")
  report = feedback_report(protocol, build_ledger(protocol))
  assert [r.verdict for r in report.rows] == [Closable.NO_ENVELOPE]


def test_a_correction_nobody_can_apply_is_reported_beside_the_verdict_not_inside_it():
  """Whether the corrected step runs is the ledger's question and stays there.

  Folding it into the closure verdict would put an execution problem and a control problem
  behind one word, and the lab would spend one budget on two things.
  """
  protocol = protocols.get("single_cell_genomics")
  report = feedback_report(protocol, build_ledger(protocol))
  stranded = report.corrections_nobody_can_apply()
  assert stranded, "every correction in this protocol lands on a step no code path reaches"
  for closure in stranded:
    assert closure.corrects_verdict not in (Verdict.AUTOMATED, Verdict.SUPERVISED)
    # The reported verdict is about the loop. None of these rows was refused for the
    # reachability of the step it corrects, which is the separation being pinned.
    assert closure.verdict is not Closable.UNPERMITTED_CORRECTION or not closure.loop.permitted()


def test_every_declared_envelope_here_rests_on_something_this_lab_has_not_validated():
  """Uncomfortable and correct, and the same answer qc gives about the same thresholds."""
  protocol = protocols.get("single_cell_genomics")
  report = feedback_report(protocol, build_ledger(protocol))
  assert len(report.unvalidated_envelopes()) == len(report.rows)


def test_report_counts_account_for_every_row():
  protocol = protocols.get("single_cell_genomics")
  report = feedback_report(protocol, build_ledger(protocol))
  counts = report.counts()
  assert counts["total"] == len(report.rows)
  assert sum(counts[reason.value] for reason in Closable) == counts["total"]
  assert set(report.by_reason()) <= {reason.value for reason in Closable}
