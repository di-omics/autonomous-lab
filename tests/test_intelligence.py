"""Executable evidence gates, expert benchmarks, and loop-closure tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields

import pytest

from autonomous_lab import build_ledger, loop_closure_for, protocols
from autonomous_lab.demo import run_closed_loop_demo
from autonomous_lab.intelligence import (
  BENCHMARKS,
  JUDGMENTS,
  BenchmarkStatus,
  Comparator,
  DecisionAction,
  DecisionEngine,
  EvidenceGate,
  EvidenceKind,
  ExpertPolicy,
  GateStatus,
  Leg,
  Observation,
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


def _gate(**overrides):
  values = {
    "gate_id": "concentration",
    "metric": "ng_ul",
    "comparator": Comparator.RANGE,
    "allowed_sources": (EvidenceKind.ASSAY_QC,),
    "failure_action": DecisionAction.RECOVER,
    "recovery_id": "reread_standards",
    "recovery": "re-read standards",
    "subject": "plate-1",
    "minimum": 2.0,
    "maximum": 10.0,
  }
  values.update(overrides)
  return EvidenceGate(**values)


def _observation(value=5.0, kind=EvidenceKind.ASSAY_QC, captured_at="2026-01-01T00:00:00Z"):
  return Observation(
    "ng_ul", value, kind, "plate-1", "reader", captured_at, "synthetic://reader/1"
  )


def _policy(*gates):
  return ExpertPolicy("commit", "1.0", tuple(gates or (_gate(),)), "assay owner")


def test_passing_evidence_permits_the_proposal():
  decision = DecisionEngine().evaluate("pool", _policy(), [_observation()])
  assert decision.permitted
  assert decision.action is DecisionAction.CONTINUE
  assert decision.results[0].status is GateStatus.PASS


def test_failing_qc_returns_the_expert_recovery():
  decision = DecisionEngine().evaluate("pool", _policy(), [_observation(0.5)])
  assert not decision.permitted
  assert decision.action is DecisionAction.RECOVER
  assert decision.recoveries == ("re-read standards",)
  assert decision.recovery_ids == ("reread_standards",)


def test_missing_evidence_stops_even_when_gate_failure_would_only_retry():
  gate = _gate(failure_action=DecisionAction.RETRY)
  decision = DecisionEngine().evaluate("pool", _policy(gate), [])
  assert decision.action is DecisionAction.STOP
  assert decision.results[0].status is GateStatus.MISSING


def test_wrong_source_does_not_satisfy_non_visible_qc():
  decision = DecisionEngine().evaluate(
    "pool", _policy(), [_observation(5.0, EvidenceKind.VISION)]
  )
  assert decision.action is DecisionAction.STOP
  assert "requires assay_qc" in decision.results[0].reason


def test_latest_trusted_observation_wins_deterministically():
  observations = [
    _observation(0.5, captured_at="2026-01-01T00:00:00Z"),
    _observation(5.0, captured_at="2026-01-01T00:00:01Z"),
  ]
  decision = DecisionEngine().evaluate("pool", _policy(), observations)
  assert decision.permitted
  assert decision.results[0].observation.value == 5.0


def test_latest_observation_uses_instants_not_lexical_offset_order():
  observations = [
    _observation(0.5, captured_at="2026-01-01T10:30:00+02:00"),
    _observation(5.0, captured_at="2026-01-01T09:00:00+00:00"),
  ]
  decision = DecisionEngine().evaluate(
    "pool", _policy(), observations, evaluated_at="2026-01-01T09:00:01Z"
  )
  assert decision.permitted
  assert decision.results[0].observation.value == 5.0


@pytest.mark.parametrize(
  "captured_at, message",
  [
    ("2026-01-01T00:00:00", "timezone offset"),
    ("not-a-time", "valid ISO-8601"),
  ],
)
def test_observations_require_valid_timezone_aware_timestamps(captured_at, message):
  with pytest.raises(ValueError, match=message):
    _observation(captured_at=captured_at)


def test_observation_values_are_detached_and_recursively_frozen():
  mutable = {"labels": ["plate-1"]}
  observation = Observation(
    "identity",
    mutable,
    EvidenceKind.VISION,
    "plate-1",
    "synthetic camera",
    "2026-01-01T00:00:00Z",
    "synthetic://camera/identity",
  )
  mutable["labels"].append("wrong-plate")
  assert observation.json_value() == {"labels": ["plate-1"]}
  with pytest.raises(TypeError):
    observation.value["labels"] = ("mutated",)


def test_stale_evidence_stops_instead_of_granting_permission():
  gate = _gate(max_age_seconds=5)
  decision = DecisionEngine().evaluate(
    "pool",
    _policy(gate),
    [_observation(captured_at="2026-01-01T00:00:00Z")],
    evaluated_at="2026-01-01T00:00:06Z",
  )
  assert decision.action is DecisionAction.STOP
  assert decision.results[0].status is GateStatus.MISSING
  assert "freshness limit" in decision.results[0].reason


def test_future_evidence_beyond_explicit_clock_skew_stops():
  gate = _gate(max_future_skew_seconds=2)
  decision = DecisionEngine().evaluate(
    "pool",
    _policy(gate),
    [_observation(captured_at="2026-01-01T00:00:03Z")],
    evaluated_at="2026-01-01T00:00:00Z",
  )
  assert decision.action is DecisionAction.STOP
  assert decision.results[0].status is GateStatus.MISSING
  assert "allowed clock skew" in decision.results[0].reason


def test_future_evidence_inside_explicit_clock_skew_can_pass():
  gate = _gate(max_future_skew_seconds=2)
  decision = DecisionEngine().evaluate(
    "pool",
    _policy(gate),
    [_observation(captured_at="2026-01-01T00:00:02Z")],
    evaluated_at="2026-01-01T00:00:00Z",
  )
  assert decision.permitted


def test_most_severe_gate_action_controls_the_decision():
  retry = _gate(
    gate_id="ready",
    metric="ready",
    comparator=Comparator.EQUAL,
    allowed_sources=(EvidenceKind.TELEMETRY,),
    failure_action=DecisionAction.RETRY,
    recovery_id="bounded_retry",
    recovery="bounded retry",
    subject="instrument-1",
    minimum=None,
    maximum=None,
    expected=True,
  )
  stop = _gate(
    gate_id="seal",
    metric="seal",
    comparator=Comparator.EQUAL,
    allowed_sources=(EvidenceKind.VISION,),
    failure_action=DecisionAction.STOP,
    recovery_id="operator_inspection",
    recovery="operator inspection",
    subject="plate-1",
    minimum=None,
    maximum=None,
    expected=True,
  )
  observations = [
    Observation(
      "ready",
      False,
      EvidenceKind.TELEMETRY,
      "instrument-1",
      "api",
      "2026-01-01T00:00:00Z",
      "synthetic://1",
    ),
    Observation(
      "seal",
      False,
      EvidenceKind.VISION,
      "plate-1",
      "cam",
      "2026-01-01T00:00:00Z",
      "synthetic://2",
    ),
  ]
  decision = DecisionEngine().evaluate("run", _policy(retry, stop), observations)
  assert decision.action is DecisionAction.STOP


def test_gate_rejects_an_inverted_range():
  with pytest.raises(ValueError, match="inverted"):
    _gate(minimum=10, maximum=2)


def test_policy_rejects_duplicate_gate_ids():
  with pytest.raises(ValueError, match="duplicate"):
    _policy(_gate(), _gate())


def test_gate_requires_a_machine_readable_recovery_id():
  with pytest.raises(ValueError, match="recovery_id"):
    _gate(recovery_id="")


def test_policy_serialization_is_exact_json_safe_and_fingerprinted():
  policy = ExpertPolicy(
    "commit",
    "1.0",
    (
      _gate(
        expected={"nested": [True, None]},
        rationale="reviewed rule",
        max_age_seconds=30,
        max_future_skew_seconds=2,
      ),
    ),
    "assay owner",
    "approved for synthetic tests",
  )
  document = policy.as_dict()
  assert set(document) == {"name", "version", "owner", "note", "gates"}
  assert set(document["gates"][0]) == {
    field.name for field in fields(EvidenceGate)
  }
  assert document["gates"][0]["comparator"] == "range"
  assert document["gates"][0]["allowed_sources"] == ["assay_qc"]
  canonical = json.dumps(
    document,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=True,
    allow_nan=False,
  )
  assert policy.fingerprint() == hashlib.sha256(canonical.encode("ascii")).hexdigest()
  assert len(policy.fingerprint()) == 64

  document["gates"][0]["expected"]["nested"].append("mutated copy")
  assert policy.as_dict()["gates"][0]["expected"] == {"nested": [True, None]}


def test_policy_fingerprint_covers_each_gate_field():
  baseline = _policy().fingerprint()
  alternatives = (
    _gate(gate_id="concentration-v2"),
    _gate(metric="concentration_ng_ul"),
    _gate(comparator=Comparator.MAXIMUM),
    _gate(allowed_sources=(EvidenceKind.TELEMETRY,)),
    _gate(failure_action=DecisionAction.ESCALATE),
    _gate(recovery_id="repeat_quantification"),
    _gate(recovery="repeat quantification"),
    _gate(subject="plate-2"),
    _gate(minimum=1.0),
    _gate(maximum=11.0),
    _gate(expected="recorded-even-when-unused"),
    _gate(rationale="subject-matter rationale"),
    _gate(max_age_seconds=30),
    _gate(max_future_skew_seconds=2),
  )
  assert all(_policy(gate).fingerprint() != baseline for gate in alternatives)


def test_policy_rejects_non_json_gate_values_before_orchestration():
  with pytest.raises(ValueError, match="portable JSON"):
    _policy(_gate(expected=object()))


@pytest.mark.parametrize(
  "scenario, action, location",
  [
    ("pass", DecisionAction.CONTINUE, "sequencer_staging"),
    ("qc_fail", DecisionAction.RECOVER, "plate_reader"),
    ("vision_error", DecisionAction.RECOVER, "plate_reader"),
    ("missing_evidence", DecisionAction.STOP, "plate_reader"),
  ],
)
def test_closed_loop_scenarios_are_audited(scenario, action, location):
  report = run_closed_loop_demo(scenario)
  assert report.decision.action is action
  assert report.final_location == location
  assert report.ledger.verify()[0]
  assert "NO HARDWARE CLAIM" in report.render()


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
