"""Decision gates: proposal is not permission, and missing evidence stops the run."""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields

import pytest

from autonomous_lab.demo import run_closed_loop_demo
from autonomous_lab.intelligence import (
  Comparator,
  DecisionAction,
  DecisionEngine,
  EvidenceGate,
  EvidenceKind,
  ExpertPolicy,
  GateStatus,
  Observation,
)


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
