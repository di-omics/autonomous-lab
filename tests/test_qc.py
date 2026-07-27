"""Device-free tests for the QC layer.

The tests that matter here try to make a gate pass something it should not. Two failure
modes are worth more than all the others: a gate that returns CONTINUE when the instrument
returned nothing at all, and a gate that reports itself ready when the step feeding it is
blocked, manual, or broken. Both look like a clean run, which is what makes them dangerous.
"""

from __future__ import annotations

import pytest

from autonomous_lab import Workcell, build_ledger, protocols
from autonomous_lab.model import Artifact, Protocol, Step, Verdict, ZeroDecodeOp
from autonomous_lab.qc import (
  GATES,
  MEASUREMENTS,
  Basis,
  Comparison,
  Criterion,
  Decision,
  Gate,
  Measurement,
  Readiness,
  evaluate,
  gate_report,
  readiness,
)


def _crit(name="c", measurement="m", bound=1.0, on_fail=Decision.ESCALATE, comparison=Comparison.AT_LEAST):
  return Criterion(
    name=name,
    measurement=measurement,
    comparison=comparison,
    bound=bound,
    rationale="test",
    basis=Basis.IN_HOUSE,
    on_fail=on_fail,
  )


# -- the silent-pass bug -------------------------------------------------------


def test_missing_measurement_is_never_a_pass():
  """A gate over an absent measurement must not return CONTINUE.

  This is the single most important test in the file. The natural implementation iterates
  the values it was handed, so a gate evaluated against an empty dict passes every
  criterion vacuously. That is how a lab commits a flow cell to an empty library.
  """
  gate = Gate(name="g", after_step="s", criteria=(_crit(),), blocks="a flow cell")
  result = evaluate(gate, {})
  assert result.decision is not Decision.CONTINUE
  assert not result.ok
  assert "m" in result.missing


def test_partially_missing_measurement_does_not_pass_on_the_half_that_arrived():
  gate = Gate(
    name="g",
    after_step="s",
    criteria=(_crit(name="a", measurement="present"), _crit(name="b", measurement="absent")),
    blocks="a flow cell",
  )
  result = evaluate(gate, {"present": 99.0})
  assert result.passed == ("a",)
  assert result.missing == ("absent",)
  assert not result.ok


def test_on_missing_is_configurable_but_still_not_continue():
  """Even the most permissive configuration cannot make absence a pass."""
  for policy in (Decision.RETRY, Decision.RECOVER, Decision.ESCALATE, Decision.ABORT):
    gate = Gate(name="g", after_step="s", criteria=(_crit(),), blocks="x", on_missing=policy)
    assert evaluate(gate, {}).decision is policy


# -- severity ------------------------------------------------------------------


def test_the_most_severe_failed_criterion_wins():
  """A gate takes the worst response among its failures, not the first or the last."""
  gate = Gate(
    name="g",
    after_step="s",
    criteria=(
      _crit(name="mild", measurement="a", on_fail=Decision.RETRY),
      _crit(name="fatal", measurement="b", on_fail=Decision.ABORT),
      _crit(name="middle", measurement="c", on_fail=Decision.RECOVER),
    ),
    blocks="x",
  )
  result = evaluate(gate, {"a": 0.0, "b": 0.0, "c": 0.0})
  assert result.decision is Decision.ABORT
  assert set(result.failed) == {"mild", "fatal", "middle"}


def test_all_criteria_met_continues():
  gate = Gate(name="g", after_step="s", criteria=(_crit(bound=1.0),), blocks="x")
  assert evaluate(gate, {"m": 5.0}).decision is Decision.CONTINUE


def test_between_is_bounded_on_both_sides():
  c = Criterion(
    name="window",
    measurement="ratio",
    comparison=Comparison.BETWEEN,
    bound=1.7,
    upper=2.1,
    rationale="test",
    basis=Basis.VENDOR,
  )
  assert c.passes(1.85)
  assert not c.passes(1.5)
  assert not c.passes(2.5)


def test_between_without_an_upper_bound_is_refused():
  with pytest.raises(ValueError, match="no upper bound"):
    Criterion(
      name="bad",
      measurement="m",
      comparison=Comparison.BETWEEN,
      bound=1.0,
      rationale="test",
      basis=Basis.VENDOR,
    )


def test_inverted_bounds_are_refused():
  with pytest.raises(ValueError, match="below lower"):
    Criterion(
      name="bad",
      measurement="m",
      comparison=Comparison.BETWEEN,
      bound=2.0,
      upper=1.0,
      rationale="test",
      basis=Basis.VENDOR,
    )


# -- readiness: the gate that cannot fire --------------------------------------


def _protocol_with(verdict_step):
  """A one-hop protocol whose measurement comes from a step we control the verdict of."""
  return Protocol(
    name="tiny",
    summary="test",
    artifacts=(Artifact("thing"),),
    steps=(verdict_step,),
  )


def test_gate_fed_by_a_blocked_step_is_unsatisfiable():
  """The load-bearing case: a perfectly specified gate whose input never arrives."""
  protocol = _protocol_with(
    Step(instrument="namocell", op="start_sort", summary="s", produces=("thing",))
  )
  ledger = build_ledger(protocol, Workcell.default())
  assert ledger.rows[0].verdict is Verdict.BLOCKED

  gate = Gate(name="g", after_step="start_sort", criteria=(_crit(measurement="q"),), blocks="x")
  meas = {"q": Measurement(key="q", units="u", produced_by="thing")}
  r = readiness(gate, ledger, meas)
  assert r.readiness is Readiness.UNSATISFIABLE
  assert not r.evaluable
  assert "start_sort" in r.blocking_steps


def test_gate_fed_by_an_automated_step_is_ready():
  protocol = _protocol_with(
    Step(
      instrument="element_aviti",
      op=ZeroDecodeOp.WATCH_RUN_FOLDER.value,
      summary="s",
      produces=("thing",),
      params={"run_dir": "/tmp/x"},
    )
  )
  ledger = build_ledger(protocol, Workcell.default())
  assert ledger.rows[0].verdict is Verdict.AUTOMATED

  gate = Gate(name="g", after_step="watch_run_folder", criteria=(_crit(measurement="q"),), blocks="x")
  meas = {"q": Measurement(key="q", units="u", produced_by="thing")}
  assert readiness(gate, ledger, meas).readiness is Readiness.READY


def test_a_gate_cannot_declare_itself_ready():
  """There is no field on Gate that asserts readiness; it is only ever computed.

  The same rule the ledger applies to automation, applied to evaluability. If this ever
  fails, someone has added an override and the report can be made to lie.
  """
  assert not hasattr(GATES["library_quant_before_flow_cell"], "ready")
  assert not hasattr(GATES["library_quant_before_flow_cell"], "readiness")


def test_gate_reading_an_undeclared_measurement_is_unsatisfiable_not_crashing():
  protocol = _protocol_with(
    Step(instrument="namocell", op="start_sort", summary="s", produces=("thing",))
  )
  ledger = build_ledger(protocol, Workcell.default())
  gate = Gate(name="g", after_step="start_sort", criteria=(_crit(measurement="nope"),), blocks="x")
  r = readiness(gate, ledger, {})
  assert r.readiness is Readiness.UNSATISFIABLE
  assert "not a declared measurement" in r.reason


# -- the real protocols --------------------------------------------------------


def test_genomics_gates_are_all_unsatisfiable_today():
  """The finding this module exists to produce, pinned so a regression is loud."""
  ledger = build_ledger(protocols.get("single_cell_genomics"))
  report = gate_report("single_cell_genomics", ledger)
  assert len(report.rows) == 2
  assert len(report.unsatisfiable()) == 2
  assert not report.closes_the_loop()


def test_library_gate_is_flagged_as_the_wrong_assay():
  """A260 on a single-cell library is precise and about the wrong thing.

  Distinct from unsatisfiability on purpose: this one fails quietly even when the
  instrument works, so it must be reported separately rather than folded in.
  """
  ledger = build_ledger(protocols.get("single_cell_genomics"))
  report = gate_report("single_cell_genomics", ledger)
  wrong = report.inappropriate(MEASUREMENTS)
  assert wrong, "the OD-based library quant should be flagged as the wrong assay"
  names = {m.key for _gate, m in wrong}
  assert "library_conc_od" in names


def test_a_protocol_with_no_gates_does_not_close_the_loop():
  """Zero gates is not the same as zero failures, and must not report as passing."""
  ledger = build_ledger(protocols.get("small_molecule_qc"))
  report = gate_report("small_molecule_qc", ledger)
  assert report.rows == []
  assert not report.closes_the_loop()


def test_unvalidated_thresholds_are_visible():
  gate = GATES["library_quant_before_flow_cell"]
  unvalidated = gate.unvalidated()
  assert unvalidated, "this gate rests on at least one threshold nobody has validated here"
  assert all(not c.basis.validated for c in unvalidated)


def test_vendor_and_literature_do_not_count_as_validated():
  """Real evidence, and not evidence about this assay at this input."""
  assert not Basis.VENDOR.validated
  assert not Basis.LITERATURE.validated
  assert not Basis.INTUITION.validated
  assert Basis.IN_HOUSE.validated
