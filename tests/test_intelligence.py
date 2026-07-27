"""Decision gates: proposal is not permission, and missing evidence stops the run."""

from __future__ import annotations

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


def test_most_severe_gate_action_controls_the_decision():
  retry = _gate(
    gate_id="ready",
    metric="ready",
    comparator=Comparator.EQUAL,
    allowed_sources=(EvidenceKind.TELEMETRY,),
    failure_action=DecisionAction.RETRY,
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
    recovery="operator inspection",
    subject="plate-1",
    minimum=None,
    maximum=None,
    expected=True,
  )
  observations = [
    Observation(
      "ready", False, EvidenceKind.TELEMETRY, "instrument-1", "api", "1", "synthetic://1"
    ),
    Observation("seal", False, EvidenceKind.VISION, "plate-1", "cam", "1", "synthetic://2"),
  ]
  decision = DecisionEngine().evaluate("run", _policy(retry, stop), observations)
  assert decision.action is DecisionAction.STOP


def test_gate_rejects_an_inverted_range():
  with pytest.raises(ValueError, match="inverted"):
    _gate(minimum=10, maximum=2)


def test_policy_rejects_duplicate_gate_ids():
  with pytest.raises(ValueError, match="duplicate"):
    _policy(_gate(), _gate())


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
