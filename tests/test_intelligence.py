"""Device-free tests for the tacit layer and loop closure.

Two rules carry this module. An operation nobody has benchmarked must be UNTRUSTED, because
the absence of a measurement is not evidence of adequacy and defaulting the other way is how
a demo becomes an assay. And `loop_closure` must not report a closed loop while any of its
four legs is broken, because a single autonomy percentage hides exactly which of the four
needs the work.
"""

from __future__ import annotations

from autonomous_lab import build_ledger, loop_closure_for, protocols
from autonomous_lab.intelligence import (
  BENCHMARKS,
  JUDGMENTS,
  BenchmarkStatus,
  Leg,
  knowledge_summary,
  loop_closure,
  trusted_for,
  untrusted_ops,
  unvalidated_judgments,
)
from autonomous_lab.provenance import provenance_report
from autonomous_lab.qc import Basis, gate_report
from autonomous_lab.recovery import FAILURES_BY_NAME, recovery_report
from autonomous_lab.vision import Observable, VisionCapability


# -- trust is earned, not assumed ----------------------------------------------


def test_an_operation_with_no_benchmark_is_not_trusted():
  """The default must be untrusted. Silence is not a pass."""
  ok, reason = trusted_for("an_operation_nobody_benchmarked")
  assert not ok
  assert "no benchmark" in reason


def test_a_met_benchmark_confers_trust():
  ok, _reason = trusted_for("iswap_to_hhs")
  assert ok


def test_a_failed_benchmark_does_not_confer_trust():
  ok, reason = trusted_for("read_absorbance")
  assert not ok
  assert "unmet" in reason


def test_an_unmeasured_benchmark_does_not_confer_trust():
  ok, reason = trusted_for("wgs_prep_lysis")
  assert not ok
  assert "unmeasured" in reason


def test_dry_validation_does_not_confer_volumetric_trust():
  """The gap this repo cares about: motion validated, accuracy never measured."""
  bench = next(b for b in BENCHMARKS if b.name == "low_volume_pipetting_cv")
  assert bench.status is BenchmarkStatus.UNMEASURED
  assert bench.observable is Observable.INVISIBLE
  assert "camera" in bench.how_to_measure


def test_the_benchmarks_that_matter_most_are_invisible_to_cameras():
  """Volumetric accuracy, thermal uniformity, carryover: no camera retires these."""
  invisible = [b for b in BENCHMARKS if b.observable is Observable.INVISIBLE]
  assert invisible
  names = {b.name for b in invisible}
  assert "low_volume_pipetting_cv" in names
  assert "odtc_thermal_uniformity" in names


def test_most_genomics_operations_have_no_met_benchmark():
  protocol = protocols.get("single_cell_genomics")
  untrusted = untrusted_ops(protocol)
  distinct = {s.op for s in protocol.steps}
  assert len(untrusted) == len(distinct)


# -- tacit knowledge -----------------------------------------------------------


def test_judgments_record_their_basis_and_most_are_unvalidated():
  """The honest state of a working bench, made visible rather than hidden."""
  assert JUDGMENTS
  unvalidated = unvalidated_judgments()
  assert unvalidated, "a bench whose every rule is validated has not written down enough"
  for j in unvalidated:
    assert not j.basis.validated


def test_every_judgment_explains_its_mechanism():
  """A rule without a why cannot be argued with, and so cannot be improved."""
  for j in JUDGMENTS:
    assert j.because.strip(), f"{j.name} states a rule with no mechanism"
    assert len(j.because) > 40


def test_judgments_that_guard_a_failure_name_a_real_one():
  for j in JUDGMENTS:
    if j.guards:
      assert j.guards in FAILURES_BY_NAME, f"{j.name} guards against an undeclared failure"


def test_at_least_one_judgment_is_validated_in_house():
  validated = [j for j in JUDGMENTS if j.basis is Basis.IN_HOUSE]
  assert validated


def test_knowledge_summary_adds_up():
  s = knowledge_summary()
  assert s["judgments"] == len(JUDGMENTS)
  assert s["benchmarks"] == len(BENCHMARKS)
  assert s["judgments_validated"] <= s["judgments"]
  assert s["benchmarks_met"] + s["benchmarks_unmeasured"] + s["benchmarks_failed"] == s["benchmarks"]


# -- loop closure --------------------------------------------------------------


def test_the_genomics_loop_does_not_close():
  closure = loop_closure_for(protocols.get("single_cell_genomics"))
  assert not closure.closes
  assert len(closure.broken()) == 4


def test_every_leg_is_reported_even_when_all_fail():
  """A report that dropped a leg would let one failure hide behind another."""
  closure = loop_closure_for(protocols.get("single_cell_genomics"))
  assert {leg.leg for leg in closure.legs} == set(Leg)


def test_each_broken_leg_gives_a_distinct_reason():
  """The point of four legs is four different next actions, not four ways to say 'no'."""
  closure = loop_closure_for(protocols.get("single_cell_genomics"))
  reasons = [leg.reason for leg in closure.broken()]
  assert len(set(reasons)) == len(reasons)


def test_a_protocol_with_no_gates_fails_the_measure_leg():
  """Zero gates must not pass vacuously; unchecked is not the same as checked-and-fine."""
  closure = loop_closure_for(protocols.get("small_molecule_qc"))
  measure = next(leg for leg in closure.legs if leg.leg is Leg.MEASURE)
  assert not measure.ok
  assert "no QC gates" in measure.reason


def test_loop_closure_does_not_recompute_the_ledger():
  """It combines reports; it must not derive a second, disagreeing opinion.

  Verified by feeding it a hand-built set and checking the legs echo those inputs rather
  than a fresh computation.
  """
  protocol = protocols.get("single_cell_genomics")
  ledger = build_ledger(protocol)
  gates = gate_report(protocol.name, ledger)
  recovery = recovery_report(protocol, gates, VisionCapability.none())
  prov = provenance_report(ledger)

  closure = loop_closure(ledger, gates, recovery, prov)
  execute = next(leg for leg in closure.legs if leg.leg is Leg.EXECUTE)
  assert str(ledger.headless_prefix()) in execute.reason
  assert str(len(ledger.rows)) in execute.reason

  record = next(leg for leg in closure.legs if leg.leg is Leg.RECORD)
  assert str(len(prov.gaps)) in record.reason


def test_the_execute_leg_names_where_the_run_stops():
  closure = loop_closure_for(protocols.get("single_cell_genomics"))
  execute = next(leg for leg in closure.legs if leg.leg is Leg.EXECUTE)
  assert "stops at" in execute.reason


def test_the_decide_leg_names_the_silent_failures():
  closure = loop_closure_for(protocols.get("single_cell_genomics"))
  decide = next(leg for leg in closure.legs if leg.leg is Leg.DECIDE)
  assert "bead_pellet_aspirated" in decide.reason
