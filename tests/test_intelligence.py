"""Adversarial tests for provenance, sample lineage, QC, and learning.

The important assertions are negative: tampering is detected, unknown evidence does not
pass, a mechanical fault never trains the optimizer, and a proposal never becomes
hardware permission.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from plr_re.protocolmap import Transport, seed

from autonomous_lab import (
  AcceptanceRule,
  Comparator,
  Design,
  DesignVariable,
  EventKind,
  EvidenceBoundOptimizer,
  EvidenceEvent,
  EvidenceLedger,
  EvidenceLevel,
  Executor,
  GateOutcome,
  MaterialStatus,
  Observation,
  ObservationDisposition,
  QualityGate,
  SampleTracker,
  Step,
  Verdict,
  Workcell,
  cost_step,
  digest,
  record_observation,
)
from autonomous_lab.demo import run_demo
from autonomous_lab.model import ZeroDecodeOp


def _training_sources(
  ledger: EvidenceLedger,
  *,
  run_id: str,
  label: str,
  objective: float,
  gate_allowed: bool = True,
  scientifically_feasible: bool = True,
  level: EvidenceLevel = EvidenceLevel.MEASURED,
):
  tracker = SampleTracker(ledger, run_id, actor="test")
  material_id = f"material_{label}"
  tracker.register(
    material_id=material_id,
    sample_id=f"sample_{label}",
    material_type="library",
    quantity=1,
    unit="uL",
    container_id="plate",
    evidence_level=level,
  )
  objective_measurement = tracker.record_measurement(
    material_id,
    measurement_id=f"objective_{label}",
    metric="yield",
    value=objective,
    unit="relative",
    evidence_level=level,
  )
  constraint_measurement = tracker.record_measurement(
    material_id,
    measurement_id=f"constraint_{label}",
    metric="scientific_feasibility",
    value=1.0 if scientifically_feasible else 0.0,
    unit="boolean",
    evidence_level=level,
    metadata={
      "constraint_id": "scientific_feasibility",
      "constraint_satisfied": scientifically_feasible,
    },
  )
  tracker.record_measurement(
    material_id,
    measurement_id=f"qc_{label}",
    metric="qc_score",
    value=1.0 if gate_allowed else 0.0,
    unit="relative",
    evidence_level=level,
  )
  decision = QualityGate(
    gate_id=f"release_{label}",
    rules=(
      AcceptanceRule(
        rule_id="qc",
        metric="qc_score",
        comparator=Comparator.AT_LEAST,
        unit="relative",
        lower=0.5,
        required_evidence=level,
      ),
    ),
  ).evaluate(tracker, material_id)
  assert decision.allowed is gate_allowed
  return (
    objective_measurement.event_id,
    constraint_measurement.event_id,
    decision.event_id,
  ), decision


def _record_design(
  ledger: EvidenceLedger,
  *,
  run_id: str,
  label: str,
  x: float,
  objective: float,
  feasible: bool = True,
  disposition: ObservationDisposition = ObservationDisposition.QUALIFIED,
  level: EvidenceLevel = EvidenceLevel.MEASURED,
) -> Observation:
  source_event_ids, _decision = _training_sources(
    ledger,
    run_id=run_id,
    label=label,
    objective=objective,
    scientifically_feasible=feasible,
    level=level,
  )
  return record_observation(
    ledger,
    run_id=run_id,
    actor="test",
    observation_id=f"obs_{label}",
    design=Design(f"design_{label}", {"x": x}),
    objective_name="yield",
    objective=objective,
    feasible=feasible,
    source_event_ids=source_event_ids,
    constraint_event_ids=(source_event_ids[1],),
    feasibility_rationale=(
      "declared scientific constraints passed"
      if feasible
      else "declared scientific constraints failed"
    ),
    disposition=disposition,
    exclusion_reason="mechanical fault" if disposition is ObservationDisposition.QUARANTINED else "",
  )


# -- evidence -----------------------------------------------------------------


def test_evidence_round_trip_is_hash_chained(tmp_path):
  path = tmp_path / "run.jsonl"
  ledger = EvidenceLedger(str(path))
  first = ledger.append(
    run_id="run_1",
    kind=EventKind.RUN_STARTED,
    actor="operator",
    evidence_level=EvidenceLevel.MEASURED,
    payload={"protocol": "x"},
    event_id="evt_1",
    recorded_at="2026-07-24T00:00:00Z",
  )
  second = ledger.append(
    run_id="run_1",
    kind=EventKind.RUN_COMPLETED,
    actor="operator",
    evidence_level=EvidenceLevel.MEASURED,
    payload={"ok": True},
    event_id="evt_2",
    recorded_at="2026-07-24T00:01:00Z",
  )
  assert second.previous_hash == first.event_hash
  assert second.sequence == 1
  reopened = EvidenceLedger(str(path))
  assert reopened.verify().ok
  assert reopened.head_hash == second.event_hash
  assert len(reopened.by_run("run_1")) == 2


def test_evidence_tampering_is_detected(tmp_path):
  path = tmp_path / "run.jsonl"
  ledger = EvidenceLedger(str(path))
  ledger.append(
    run_id="run_1",
    kind=EventKind.RUN_STARTED,
    actor="operator",
    evidence_level=EvidenceLevel.MEASURED,
    payload={"protocol": "x"},
  )
  row = json.loads(path.read_text(encoding="utf-8"))
  row["payload"]["protocol"] = "silently_rewritten"
  path.write_text(json.dumps(row) + "\n", encoding="utf-8")
  with pytest.raises(ValueError, match="invalid digest"):
    EvidenceLedger(str(path))


def test_evidence_rejects_non_json_and_nan_payloads():
  ledger = EvidenceLedger()
  with pytest.raises(TypeError):
    ledger.append(
      run_id="run",
      kind=EventKind.RUN_STARTED,
      actor="x",
      evidence_level=EvidenceLevel.MODELED,
      payload={"bad": {1, 2}},
    )
  with pytest.raises(ValueError):
    ledger.append(
      run_id="run",
      kind=EventKind.RUN_STARTED,
      actor="x",
      evidence_level=EvidenceLevel.MODELED,
      payload={"bad": float("nan")},
    )


def test_verify_command_refuses_a_missing_or_empty_ledger(tmp_path):
  from autonomous_lab.cli import main

  assert main(["verify", str(tmp_path / "missing.jsonl")]) == 1
  empty = tmp_path / "empty.jsonl"
  empty.write_text("", encoding="utf-8")
  assert main(["verify", str(empty)]) == 1


def test_evidence_schema_enums_match_the_code():
  schema = json.loads(
    (Path(__file__).parents[1] / "schemas" / "evidence-event.schema.json").read_text(
      encoding="utf-8"
    )
  )
  assert set(schema["properties"]["kind"]["enum"]) == {kind.value for kind in EventKind}
  assert set(schema["properties"]["evidence_level"]["enum"]) == {
    level.value for level in EvidenceLevel
  }


@pytest.mark.parametrize(
  ("field", "replacement", "message"),
  (
    ("schema_version", True, "schema_version must be an integer"),
    ("sequence", 0.9, "sequence must be an integer"),
    ("sequence", False, "sequence must be an integer"),
    ("event_id", 7, "event_id must be a string"),
    ("recorded_at", "not-a-date", "recorded_at must be an RFC 3339"),
    ("previous_hash", "A" * 64, "previous_hash must be 64 lowercase hex"),
  ),
)
def test_evidence_from_dict_refuses_type_coercion_and_schema_drift(
  field, replacement, message
):
  event = EvidenceLedger().append(
    run_id="run",
    kind=EventKind.RUN_STARTED,
    actor="operator",
    evidence_level=EvidenceLevel.MEASURED,
    payload={"ok": True},
  )
  row = event.to_dict()
  row[field] = replacement
  with pytest.raises(ValueError, match=message):
    EvidenceEvent.from_dict(row)


def test_evidence_from_dict_refuses_unknown_fields_and_python_only_payloads():
  event = EvidenceLedger().append(
    run_id="run",
    kind=EventKind.RUN_STARTED,
    actor="operator",
    evidence_level=EvidenceLevel.MEASURED,
    payload={"ok": True},
  )
  unknown = event.to_dict()
  unknown["silently_dropped"] = "no"
  with pytest.raises(ValueError, match="unknown fields: silently_dropped"):
    EvidenceEvent.from_dict(unknown)

  python_only = event.to_dict()
  python_only["payload"] = {"tuple": (1, 2)}
  with pytest.raises(ValueError, match="non-JSON type tuple"):
    EvidenceEvent.from_dict(python_only)


def test_append_refuses_invalid_envelope_before_writing(tmp_path):
  memory = EvidenceLedger()
  with pytest.raises(ValueError, match="recorded_at must be an RFC 3339"):
    memory.append(
      run_id="run",
      kind=EventKind.RUN_STARTED,
      actor="operator",
      evidence_level=EvidenceLevel.MEASURED,
      payload={},
      recorded_at="yesterday-ish",
    )
  assert memory.events == ()

  path = tmp_path / "run.jsonl"
  backed = EvidenceLedger(str(path))
  with pytest.raises(ValueError, match="recorded_at must be an RFC 3339"):
    backed.append(
      run_id="run",
      kind=EventKind.RUN_STARTED,
      actor="operator",
      evidence_level=EvidenceLevel.MEASURED,
      payload={},
      recorded_at="yesterday-ish",
    )
  assert path.read_text(encoding="utf-8") == ""
  assert backed.events == ()


def test_file_backed_append_refuses_truncated_snapshot(tmp_path):
  path = tmp_path / "run.jsonl"
  ledger = EvidenceLedger(str(path))
  ledger.append(
    run_id="run",
    kind=EventKind.RUN_STARTED,
    actor="operator",
    evidence_level=EvidenceLevel.MEASURED,
    payload={},
  )
  ledger.append(
    run_id="run",
    kind=EventKind.RUN_COMPLETED,
    actor="operator",
    evidence_level=EvidenceLevel.MEASURED,
    payload={},
  )
  first_line = path.read_text(encoding="utf-8").splitlines()[0]
  path.write_text(first_line + "\n", encoding="utf-8")

  with pytest.raises(ValueError, match="was truncated"):
    ledger.append(
      run_id="run",
      kind=EventKind.RUN_STOPPED,
      actor="operator",
      evidence_level=EvidenceLevel.MEASURED,
      payload={},
    )
  assert len(path.read_text(encoding="utf-8").splitlines()) == 1
  assert len(ledger.events) == 2


def test_file_backed_append_refuses_diverged_snapshot(tmp_path):
  path = tmp_path / "run.jsonl"
  ledger = EvidenceLedger(str(path))
  ledger.append(
    run_id="run",
    kind=EventKind.RUN_STARTED,
    actor="operator",
    evidence_level=EvidenceLevel.MEASURED,
    payload={"branch": "original"},
  )
  alternate_path = tmp_path / "alternate.jsonl"
  alternate = EvidenceLedger(str(alternate_path))
  alternate.append(
    run_id="run",
    kind=EventKind.RUN_STARTED,
    actor="operator",
    evidence_level=EvidenceLevel.MEASURED,
    payload={"branch": "alternate"},
  )
  path.write_text(alternate_path.read_text(encoding="utf-8"), encoding="utf-8")

  with pytest.raises(ValueError, match="diverged from this ledger snapshot"):
    ledger.append(
      run_id="run",
      kind=EventKind.RUN_COMPLETED,
      actor="operator",
      evidence_level=EvidenceLevel.MEASURED,
      payload={},
    )
  assert path.read_text(encoding="utf-8") == alternate_path.read_text(encoding="utf-8")


def test_run_start_is_reserved_atomically_across_stale_ledger_instances(tmp_path):
  path = tmp_path / "runs.jsonl"
  first = EvidenceLedger(str(path))
  stale = EvidenceLedger(str(path))
  first.append(
    run_id="same_attempt",
    kind=EventKind.RUN_STARTED,
    actor="first",
    evidence_level=EvidenceLevel.MODELED,
    payload={"protocol": "x"},
  )
  with pytest.raises(ValueError, match="run_id 'same_attempt' already exists"):
    stale.append(
      run_id="same_attempt",
      kind=EventKind.RUN_STARTED,
      actor="second",
      evidence_level=EvidenceLevel.MODELED,
      payload={"protocol": "x"},
    )
  reopened = EvidenceLedger(str(path))
  assert [
    event.kind for event in reopened.by_run("same_attempt")
  ] == [EventKind.RUN_STARTED]


# -- sample/material lineage --------------------------------------------------


def test_sample_split_pool_move_and_lineage_are_replayable():
  ledger = EvidenceLedger()
  tracker = SampleTracker(ledger, "run_1", actor="operator")
  tracker.register(
    material_id="root",
    sample_id="sample_1",
    material_type="input",
    quantity=20,
    unit="uL",
    container_id="tube_1",
  )
  tracker.derive(
    material_id="a",
    parent_material_ids=("root",),
    parent_contributions={"root": 5},
    operation="aliquot",
    material_type="aliquot",
    quantity=5,
    unit="uL",
    container_id="plate_1",
    position="A1",
  )
  tracker.derive(
    material_id="b",
    parent_material_ids=("root",),
    parent_contributions={"root": 5},
    operation="aliquot",
    material_type="aliquot",
    quantity=5,
    unit="uL",
    container_id="plate_1",
    position="A2",
  )
  tracker.derive(
    material_id="pool",
    parent_material_ids=("a", "b"),
    parent_contributions={"a": 4, "b": 4},
    operation="pool",
    material_type="pool",
    quantity=8,
    unit="uL",
    container_id="tube_2",
  )
  moved = tracker.move(
    "pool",
    container_id="rack_1",
    position="B3",
    location="freezer_1",
    reason="store after pooling",
  )
  assert moved.container_id == "rack_1"
  assert moved.position == "B3"
  trace = tracker.lineage("pool")
  assert [material.material_id for material in trace.ancestors] == [
    "root",
    "a",
    "b",
    "pool",
  ]
  assert {(edge.parent_material_id, edge.child_material_id) for edge in trace.edges} == {
    ("root", "a"),
    ("root", "b"),
    ("a", "pool"),
    ("b", "pool"),
  }


def test_sample_tracker_refuses_duplicate_missing_and_unavailable_material():
  tracker = SampleTracker(EvidenceLedger(), "run")
  tracker.register(
    material_id="root",
    sample_id="s",
    material_type="input",
    quantity=1,
    unit="uL",
    container_id="tube",
  )
  with pytest.raises(ValueError, match="already exists"):
    tracker.register(
      material_id="root",
      sample_id="s",
      material_type="input",
      quantity=1,
      unit="uL",
      container_id="tube",
    )
  with pytest.raises(KeyError, match="unknown parent"):
    tracker.derive(
      material_id="child",
      parent_material_ids=("ghost",),
      parent_contributions={"ghost": 1},
      operation="aliquot",
      material_type="x",
      quantity=1,
      unit="uL",
      container_id="tube",
    )
  tracker.set_status("root", MaterialStatus.QUARANTINED, reason="identity mismatch")
  with pytest.raises(ValueError, match="unavailable"):
    tracker.derive(
      material_id="child",
      parent_material_ids=("root",),
      parent_contributions={"root": 1},
      operation="aliquot",
      material_type="x",
      quantity=1,
      unit="uL",
      container_id="tube",
    )


def test_measurements_keep_source_evidence_and_reject_duplicate_ids():
  tracker = SampleTracker(EvidenceLedger(), "run")
  tracker.register(
    material_id="root",
    sample_id="s",
    material_type="input",
    quantity=1,
    unit="uL",
    container_id="tube",
  )
  measurement = tracker.record_measurement(
    "root",
    measurement_id="m1",
    metric="concentration",
    value=4.2,
    unit="ng/uL",
    source_digest="a" * 64,
  )
  assert measurement.source_digest == "a" * 64
  assert tracker.measurements("root", "concentration") == (measurement,)
  with pytest.raises(ValueError, match="already exists"):
    tracker.record_measurement(
      "root",
      measurement_id="m1",
      metric="concentration",
      value=5.0,
      unit="ng/uL",
    )


# -- quality gates ------------------------------------------------------------


def _gate(required=EvidenceLevel.MEASURED):
  return QualityGate(
    gate_id="release",
    rules=(
      AcceptanceRule(
        "yield",
        "yield_ng",
        Comparator.AT_LEAST,
        "ng",
        lower=10.0,
        required_evidence=required,
      ),
      AcceptanceRule(
        "cv",
        "cv_pct",
        Comparator.AT_MOST,
        "pct",
        upper=15.0,
        required_evidence=required,
      ),
    ),
  )


def _tracker_with_material():
  tracker = SampleTracker(EvidenceLedger(), "run")
  tracker.register(
    material_id="lib",
    sample_id="s",
    material_type="library",
    quantity=15,
    unit="ng",
    container_id="plate",
  )
  return tracker


@pytest.mark.parametrize(
  ("updates", "error", "message"),
  (
    ({"comparator": "at_least"}, TypeError, "Comparator"),
    ({"required_evidence": "measured"}, TypeError, "EvidenceLevel"),
    ({"lower": True}, ValueError, "finite number"),
    ({"lower": float("nan")}, ValueError, "finite number"),
    ({"upper": 20.0}, ValueError, "must not set upper"),
    ({"rationale": 7}, TypeError, "rationale must be a string"),
  ),
)
def test_acceptance_rule_rejects_ambiguous_policy_values(updates, error, message):
  values = {
    "rule_id": "yield",
    "metric": "yield_ng",
    "comparator": Comparator.AT_LEAST,
    "unit": "ng",
    "lower": 10.0,
  }
  values.update(updates)
  with pytest.raises(error, match=message):
    AcceptanceRule(**values)


def test_quality_gate_rejects_wrong_rule_and_description_types():
  rule = AcceptanceRule(
    "yield", "yield_ng", Comparator.AT_LEAST, "ng", lower=10.0
  )
  with pytest.raises(TypeError, match="rules must be a tuple"):
    QualityGate("release", [rule])
  with pytest.raises(TypeError, match="description must be a string"):
    QualityGate("release", (rule,), description=7)


def test_gate_passes_only_when_every_rule_has_sufficient_evidence():
  tracker = _tracker_with_material()
  tracker.record_measurement(
    "lib", measurement_id="yield", metric="yield_ng", value=12, unit="ng"
  )
  tracker.record_measurement(
    "lib", measurement_id="cv", metric="cv_pct", value=8, unit="pct"
  )
  decision = _gate().evaluate(tracker, "lib")
  assert decision.outcome is GateOutcome.PASS
  assert decision.allowed
  event = tracker.ledger.event(decision.event_id)
  assert event.payload["allowed"] is True
  assert event.payload["policy_digest"] == decision.policy_digest
  assert event.payload["policy"]["gate_id"] == "release"
  assert event.payload["policy"]["rules"][0]["comparator"] == "at_least"
  assert event.payload["policy"]["rules"][0]["lower"] == 10.0


def test_event_payload_cannot_be_mutated_to_flip_a_gate():
  tracker = _tracker_with_material()
  tracker.record_measurement(
    "lib", measurement_id="yield", metric="yield_ng", value=2, unit="ng"
  )
  tracker.record_measurement(
    "lib", measurement_id="cv", metric="cv_pct", value=8, unit="pct"
  )
  measurement_event = next(
    event
    for event in tracker.ledger.events
    if event.kind is EventKind.MEASUREMENT_RECORDED
    and event.payload["measurement_id"] == "yield"
  )
  with pytest.raises(TypeError):
    measurement_event.payload["value"] = 20

  decision = _gate().evaluate(tracker, "lib")
  assert decision.outcome is GateOutcome.FAIL
  gate_event = tracker.ledger.event(decision.event_id)
  exposed_rules = gate_event.payload["rules"]
  exposed_rules[0]["outcome"] = "pass"
  assert gate_event.payload["rules"][0]["outcome"] == "fail"
  assert tracker.ledger.event(decision.event_id).payload["allowed"] is False


def test_gate_missing_or_weak_evidence_holds_and_unit_drift_errors():
  missing = _tracker_with_material()
  assert _gate().evaluate(missing, "lib").outcome is GateOutcome.HOLD

  weak = _tracker_with_material()
  weak.record_measurement(
    "lib",
    measurement_id="yield",
    metric="yield_ng",
    value=12,
    unit="ng",
    evidence_level=EvidenceLevel.SIMULATED,
  )
  weak.record_measurement(
    "lib",
    measurement_id="cv",
    metric="cv_pct",
    value=8,
    unit="pct",
    evidence_level=EvidenceLevel.SIMULATED,
  )
  assert _gate().evaluate(weak, "lib").outcome is GateOutcome.HOLD

  wrong_unit = _tracker_with_material()
  wrong_unit.record_measurement(
    "lib", measurement_id="yield", metric="yield_ng", value=12, unit="ug"
  )
  wrong_unit.record_measurement(
    "lib", measurement_id="cv", metric="cv_pct", value=8, unit="pct"
  )
  assert _gate().evaluate(wrong_unit, "lib").outcome is GateOutcome.ERROR


def test_gate_failure_never_authorizes_downstream_use():
  tracker = _tracker_with_material()
  tracker.record_measurement(
    "lib", measurement_id="yield", metric="yield_ng", value=3, unit="ng"
  )
  tracker.record_measurement(
    "lib", measurement_id="cv", metric="cv_pct", value=8, unit="pct"
  )
  decision = _gate().evaluate(tracker, "lib")
  assert decision.outcome is GateOutcome.FAIL
  assert not decision.allowed


@pytest.mark.parametrize(
  "status",
  (
    MaterialStatus.QUARANTINED,
    MaterialStatus.CONSUMED,
    MaterialStatus.DISPOSED,
  ),
)
def test_unavailable_material_status_never_produces_an_allowed_gate(status):
  tracker = _tracker_with_material()
  tracker.record_measurement(
    "lib", measurement_id="yield", metric="yield_ng", value=12, unit="ng"
  )
  tracker.record_measurement(
    "lib", measurement_id="cv", metric="cv_pct", value=8, unit="pct"
  )
  tracker.set_status("lib", status=status, reason="not available for advancement")

  decision = _gate().evaluate(tracker, "lib")

  assert decision.outcome is GateOutcome.HOLD
  assert not decision.allowed
  assert status.value in decision.reason
  assert tracker.ledger.event(decision.event_id).payload["allowed"] is False


def test_weak_material_release_evidence_cannot_launder_a_measured_gate():
  tracker = _tracker_with_material()
  tracker.record_measurement(
    "lib", measurement_id="yield", metric="yield_ng", value=12, unit="ng"
  )
  tracker.record_measurement(
    "lib", measurement_id="cv", metric="cv_pct", value=8, unit="pct"
  )
  tracker.set_status(
    "lib",
    status=MaterialStatus.QUARANTINED,
    reason="measured contamination signal",
  )
  tracker.set_status(
    "lib",
    status=MaterialStatus.RELEASED,
    reason="unverified release claim",
    evidence_level=EvidenceLevel.MODELED,
  )
  release_event = tracker.ledger.events[-1]

  decision = _gate().evaluate(tracker, "lib")

  assert decision.outcome is GateOutcome.HOLD
  assert not decision.allowed
  event = tracker.ledger.event(decision.event_id)
  assert event.evidence_level is EvidenceLevel.MODELED
  assert event.payload["material_state_event_ids"][-1] == release_event.event_id


def test_stale_gate_snapshot_cannot_pass_a_newly_quarantined_material(tmp_path):
  path = tmp_path / "gate-race.jsonl"
  initial = SampleTracker(EvidenceLedger(str(path)), "run")
  initial.register(
    material_id="lib",
    sample_id="s",
    material_type="library",
    quantity=15,
    unit="ng",
    container_id="plate",
  )
  initial.record_measurement(
    "lib", measurement_id="yield", metric="yield_ng", value=12, unit="ng"
  )
  initial.record_measurement(
    "lib", measurement_id="cv", metric="cv_pct", value=8, unit="pct"
  )
  stale = SampleTracker(EvidenceLedger(str(path)), "run")
  current = SampleTracker(EvidenceLedger(str(path)), "run")
  current.set_status(
    "lib",
    status=MaterialStatus.QUARANTINED,
    reason="late contamination signal",
  )

  with pytest.raises(ValueError, match="quality-gate inputs changed"):
    _gate().evaluate(stale, "lib")

  reopened = EvidenceLedger(str(path))
  assert not any(event.kind is EventKind.GATE_EVALUATED for event in reopened.events)


# -- advisory learning --------------------------------------------------------


def _optimizer(minimum=EvidenceLevel.MEASURED):
  return EvidenceBoundOptimizer(
    variables=(DesignVariable("x", 0.0, 1.0),),
    objective_name="yield",
    minimum_evidence=minimum,
    candidate_count=32,
  )


@pytest.mark.parametrize(
  ("factory", "error", "message"),
  (
    (
      lambda: DesignVariable("x", True, 1.0),
      ValueError,
      "finite number",
    ),
    (
      lambda: DesignVariable("x", 0.0, float("inf")),
      ValueError,
      "finite number",
    ),
    (
      lambda: Design("design", {"x": False}),
      ValueError,
      "finite number",
    ),
    (
      lambda: EvidenceBoundOptimizer(
        variables=(DesignVariable("x", 0.0, 1.0),),
        objective_name="yield",
        maximize=1,
      ),
      TypeError,
      "maximize must be a boolean",
    ),
    (
      lambda: EvidenceBoundOptimizer(
        variables=(DesignVariable("x", 0.0, 1.0),),
        objective_name="yield",
        minimum_evidence="measured",
      ),
      TypeError,
      "minimum_evidence must be an EvidenceLevel",
    ),
    (
      lambda: EvidenceBoundOptimizer(
        variables=(DesignVariable("x", 0.0, 1.0),),
        objective_name="yield",
        exploration=float("nan"),
      ),
      ValueError,
      "finite number",
    ),
    (
      lambda: EvidenceBoundOptimizer(
        variables=(DesignVariable("x", 0.0, 1.0),),
        objective_name="yield",
        candidate_count=True,
      ),
      TypeError,
      "candidate_count must be an integer",
    ),
    (
      lambda: EvidenceBoundOptimizer(
        variables=[DesignVariable("x", 0.0, 1.0)],
        objective_name="yield",
      ),
      TypeError,
      "variables must be a tuple",
    ),
  ),
)
def test_learning_constructors_reject_ambiguous_values(factory, error, message):
  with pytest.raises(error, match=message):
    factory()


def test_optimizer_rejects_non_integer_proposal_count():
  with pytest.raises(TypeError, match="proposal count must be an integer"):
    _optimizer().propose(
      EvidenceLedger(), [], run_id="run", actor="agent", count=True
    )


def test_design_values_are_frozen_after_validation():
  source = {"x": 0.25}
  design = Design("immutable_design", source)
  source["x"] = 0.75
  assert design.values["x"] == 0.25
  with pytest.raises(TypeError):
    design.values["x"] = 0.5


def test_failed_gate_cannot_be_laundered_into_training_data():
  ledger = EvidenceLedger()
  source_event_ids, decision = _training_sources(
    ledger,
    run_id="run",
    label="failed",
    objective=0.2,
    gate_allowed=False,
    scientifically_feasible=False,
  )
  assert not decision.allowed

  feasible_source_event_ids, _feasible_decision = _training_sources(
    ledger,
    run_id="run",
    label="failed_but_scientifically_feasible",
    objective=0.2,
    gate_allowed=False,
    scientifically_feasible=True,
  )
  for feasible, chosen_sources in (
    (True, feasible_source_event_ids),
    (False, source_event_ids),
  ):
    with pytest.raises(ValueError, match="QUALIFIED.*passing quality gate"):
      record_observation(
        ledger,
        run_id="run",
        actor="test",
        observation_id=f"laundered_{feasible}",
        design=Design("failed", {"x": 0.2}),
        objective_name="yield",
        objective=0.2,
        feasible=feasible,
        source_event_ids=chosen_sources,
        constraint_event_ids=(chosen_sources[1],),
        feasibility_rationale="declared scientific constraints evaluated",
        disposition=ObservationDisposition.QUALIFIED,
      )

  quarantined = record_observation(
    ledger,
    run_id="run",
    actor="test",
    observation_id="honest_failure",
    design=Design("failed", {"x": 0.2}),
    objective_name="yield",
    objective=0.2,
    feasible=False,
    source_event_ids=source_event_ids,
    constraint_event_ids=(source_event_ids[1],),
    feasibility_rationale="scientific constraint failed",
    disposition=ObservationDisposition.QUARANTINED,
    exclusion_reason="release gate failed",
  )
  proposal = _optimizer().propose(
    ledger, [quarantined], run_id="run", actor="agent"
  )[0]
  assert quarantined.evidence_event_id not in proposal.observation_event_ids


def test_observation_refuses_an_unrelated_material_or_run_gate():
  ledger = EvidenceLedger()
  sources_a, _decision_a = _training_sources(
    ledger,
    run_id="run",
    label="a",
    objective=0.4,
  )
  sources_b, _decision_b = _training_sources(
    ledger,
    run_id="run",
    label="b",
    objective=0.4,
  )
  with pytest.raises(ValueError, match="measurement material.*gate material.*differ"):
    record_observation(
      ledger,
      run_id="run",
      actor="test",
      observation_id="mixed_material",
      design=Design("mixed", {"x": 0.4}),
      objective_name="yield",
      objective=0.4,
      feasible=True,
      source_event_ids=(sources_a[0], sources_a[1], sources_b[-1]),
      constraint_event_ids=(sources_a[1],),
      feasibility_rationale="scientific constraint passed",
    )

  other_run_sources, _other_decision = _training_sources(
    ledger,
    run_id="other_run",
    label="other",
    objective=0.4,
  )
  with pytest.raises(ValueError, match="different run"):
    record_observation(
      ledger,
      run_id="run",
      actor="test",
      observation_id="mixed_run",
      design=Design("mixed", {"x": 0.4}),
      objective_name="yield",
      objective=0.4,
      feasible=True,
      source_event_ids=other_run_sources,
      constraint_event_ids=(other_run_sources[1],),
      feasibility_rationale="scientific constraint passed",
    )


def test_observation_refuses_inconsistent_gate_and_measurement_payloads():
  ledger = EvidenceLedger()
  source_event_ids, decision = _training_sources(
    ledger,
    run_id="run",
    label="semantics",
    objective=0.6,
    gate_allowed=False,
    scientifically_feasible=False,
  )
  gate_event = ledger.event(decision.event_id)
  forged_payload = dict(gate_event.payload)
  forged_payload["allowed"] = True
  inconsistent_gate = ledger.append(
    run_id="run",
    kind=EventKind.GATE_EVALUATED,
    actor="test",
    evidence_level=gate_event.evidence_level,
    payload=forged_payload,
  )
  with pytest.raises(ValueError, match="allowed must be true exactly"):
    record_observation(
      ledger,
      run_id="run",
      actor="test",
      observation_id="inconsistent_gate",
      design=Design("semantics", {"x": 0.6}),
      objective_name="yield",
      objective=0.6,
      feasible=False,
      source_event_ids=(
        source_event_ids[0],
        source_event_ids[1],
        inconsistent_gate.event_id,
      ),
      constraint_event_ids=(source_event_ids[1],),
      feasibility_rationale="scientific constraint failed",
    )

  fabricated_pass_payload = dict(gate_event.payload)
  fabricated_rule_results = [
    dict(result) for result in gate_event.payload["rules"]
  ]
  fabricated_rule_results[0]["outcome"] = "pass"
  fabricated_pass_payload.update(
    {
      "outcome": "pass",
      "allowed": True,
      "rules": fabricated_rule_results,
    }
  )
  fabricated_pass = ledger.append(
    run_id="run",
    kind=EventKind.GATE_EVALUATED,
    actor="test",
    evidence_level=gate_event.evidence_level,
    payload=fabricated_pass_payload,
  )
  with pytest.raises(
    ValueError, match="disagrees with the sealed policy and measurement"
  ):
    record_observation(
      ledger,
      run_id="run",
      actor="test",
      observation_id="fabricated_pass",
      design=Design("semantics", {"x": 0.6}),
      objective_name="yield",
      objective=0.6,
      feasible=False,
      source_event_ids=(
        source_event_ids[0],
        source_event_ids[1],
        fabricated_pass.event_id,
      ),
      constraint_event_ids=(source_event_ids[1],),
      feasibility_rationale="scientific constraint failed",
    )

  malformed_measurement = ledger.append(
    run_id="run",
    kind=EventKind.MEASUREMENT_RECORDED,
    actor="test",
    evidence_level=EvidenceLevel.MEASURED,
    payload={
      "metric": "yield",
      "value": 0.6,
      "unit": "relative",
      "material_id": "material_semantics",
    },
  )
  with pytest.raises(ValueError, match="non-empty 'measurement_id'"):
    record_observation(
      ledger,
      run_id="run",
      actor="test",
      observation_id="malformed_measurement",
      design=Design("semantics", {"x": 0.6}),
      objective_name="yield",
      objective=0.6,
      feasible=False,
      source_event_ids=(
        malformed_measurement.event_id,
        source_event_ids[1],
        decision.event_id,
      ),
      constraint_event_ids=(source_event_ids[1],),
      feasibility_rationale="scientific constraint failed",
      disposition=ObservationDisposition.QUARANTINED,
      exclusion_reason="release gate failed",
    )


def test_optimizer_excludes_quarantined_and_weak_evidence():
  ledger = EvidenceLedger()
  good = _record_design(
    ledger, run_id="run", label="good", x=0.2, objective=0.5
  )
  bad = _record_design(
    ledger,
    run_id="run",
    label="fault",
    x=0.8,
    objective=100.0,
    disposition=ObservationDisposition.QUARANTINED,
  )
  weak = _record_design(
    ledger,
    run_id="run",
    label="sim",
    x=0.5,
    objective=99.0,
    level=EvidenceLevel.SIMULATED,
  )
  proposal = _optimizer().propose(
    ledger, [good, bad, weak], run_id="run", actor="agent"
  )[0]
  assert proposal.observation_event_ids == (good.evidence_event_id,)
  assert bad.evidence_event_id not in proposal.observation_event_ids
  assert weak.evidence_event_id not in proposal.observation_event_ids


@pytest.mark.parametrize(
  "status",
  (
    MaterialStatus.QUARANTINED,
    MaterialStatus.CONSUMED,
    MaterialStatus.DISPOSED,
  ),
)
def test_unavailable_material_cannot_produce_a_qualified_observation(status):
  ledger = EvidenceLedger()
  source_event_ids, decision = _training_sources(
    ledger,
    run_id="run",
    label=status.value,
    objective=0.5,
  )
  assert decision.allowed
  SampleTracker(ledger, "run").set_status(
    f"material_{status.value}",
    status=status,
    reason="material became unavailable",
  )

  with pytest.raises(ValueError, match="material status changed after"):
    record_observation(
      ledger,
      run_id="run",
      actor="test",
      observation_id=f"obs_{status.value}",
      design=Design(f"design_{status.value}", {"x": 0.5}),
      objective_name="yield",
      objective=0.5,
      feasible=True,
      source_event_ids=source_event_ids,
      constraint_event_ids=(source_event_ids[1],),
      feasibility_rationale="scientific constraint passed",
    )


def test_observation_replay_uses_status_at_the_observation_sequence():
  ledger = EvidenceLedger()
  observation = _record_design(
    ledger,
    run_id="run",
    label="historical",
    x=0.3,
    objective=0.6,
  )
  SampleTracker(ledger, "run").set_status(
    "material_historical",
    status=MaterialStatus.CONSUMED,
    reason="used after the qualified row was sealed",
  )

  proposal = _optimizer().propose(
    ledger, [observation], run_id="run", actor="agent"
  )[0]

  assert proposal.observation_event_ids == (observation.evidence_event_id,)


def test_stale_observation_snapshot_cannot_qualify_newly_quarantined_material(
  tmp_path,
):
  path = tmp_path / "observation-race.jsonl"
  source = EvidenceLedger(str(path))
  source_event_ids, decision = _training_sources(
    source,
    run_id="run",
    label="stale_observation",
    objective=0.5,
  )
  assert decision.allowed
  stale = EvidenceLedger(str(path))
  current = SampleTracker(EvidenceLedger(str(path)), "run")
  current.set_status(
    "material_stale_observation",
    status=MaterialStatus.QUARANTINED,
    reason="late contamination signal",
  )

  with pytest.raises(ValueError, match="material status changed after"):
    record_observation(
      stale,
      run_id="run",
      actor="test",
      observation_id="obs_stale",
      design=Design("design_stale", {"x": 0.5}),
      objective_name="yield",
      objective=0.5,
      feasible=True,
      source_event_ids=source_event_ids,
      constraint_event_ids=(source_event_ids[1],),
      feasibility_rationale="scientific constraint passed",
    )

  reopened = EvidenceLedger(str(path))
  assert not any(
    event.kind is EventKind.OBSERVATION_RECORDED for event in reopened.events
  )


def test_status_change_and_release_after_gate_requires_a_fresh_gate():
  ledger = EvidenceLedger()
  source_event_ids, decision = _training_sources(
    ledger,
    run_id="run",
    label="regate_status",
    objective=0.5,
  )
  assert decision.allowed
  tracker = SampleTracker(ledger, "run")
  tracker.set_status(
    "material_regate_status",
    status=MaterialStatus.QUARANTINED,
    reason="temporary investigation",
  )
  tracker.set_status(
    "material_regate_status",
    status=MaterialStatus.RELEASED,
    reason="investigation closed",
  )

  with pytest.raises(ValueError, match="status changed after.*re-gate"):
    record_observation(
      ledger,
      run_id="run",
      actor="test",
      observation_id="obs_regate_status",
      design=Design("design_regate_status", {"x": 0.5}),
      objective_name="yield",
      objective=0.5,
      feasible=True,
      source_event_ids=source_event_ids,
      constraint_event_ids=(source_event_ids[1],),
      feasibility_rationale="scientific constraint passed",
    )


def test_stale_gate_measurement_is_rejected_at_transaction_time(tmp_path):
  path = tmp_path / "observation-qc-race.jsonl"
  source = EvidenceLedger(str(path))
  source_event_ids, decision = _training_sources(
    source,
    run_id="run",
    label="qc_race",
    objective=0.5,
  )
  assert decision.allowed
  stale = EvidenceLedger(str(path))
  SampleTracker(EvidenceLedger(str(path)), "run").record_measurement(
    "material_qc_race",
    measurement_id="qc_race_failed_late",
    metric="qc_score",
    value=0.0,
    unit="relative",
  )

  with pytest.raises(ValueError, match="quality-gate evidence is stale"):
    record_observation(
      stale,
      run_id="run",
      actor="test",
      observation_id="obs_qc_race",
      design=Design("design_qc_race", {"x": 0.5}),
      objective_name="yield",
      objective=0.5,
      feasible=True,
      source_event_ids=source_event_ids,
      constraint_event_ids=(source_event_ids[1],),
      feasibility_rationale="scientific constraint passed",
    )

  assert not any(
    event.kind is EventKind.OBSERVATION_RECORDED
    for event in EvidenceLedger(str(path)).events
  )


def test_stale_objective_measurement_cannot_be_cited():
  ledger = EvidenceLedger()
  source_event_ids, decision = _training_sources(
    ledger,
    run_id="run",
    label="objective_freshness",
    objective=0.5,
  )
  assert decision.allowed
  SampleTracker(ledger, "run").record_measurement(
    "material_objective_freshness",
    measurement_id="objective_new",
    metric="yield",
    value=0.1,
    unit="relative",
  )

  with pytest.raises(ValueError, match="objective measurement .* is stale"):
    record_observation(
      ledger,
      run_id="run",
      actor="test",
      observation_id="obs_stale_objective",
      design=Design("design_stale_objective", {"x": 0.5}),
      objective_name="yield",
      objective=0.5,
      feasible=True,
      source_event_ids=source_event_ids,
      constraint_event_ids=(source_event_ids[1],),
      feasibility_rationale="scientific constraint passed",
    )


def test_stale_constraint_attestation_cannot_be_cited():
  ledger = EvidenceLedger()
  source_event_ids, decision = _training_sources(
    ledger,
    run_id="run",
    label="constraint_freshness",
    objective=0.5,
  )
  assert decision.allowed
  SampleTracker(ledger, "run").record_measurement(
    "material_constraint_freshness",
    measurement_id="constraint_failed_late",
    metric="scientific_feasibility",
    value=0.0,
    unit="boolean",
    metadata={
      "constraint_id": "scientific_feasibility",
      "constraint_satisfied": False,
    },
  )

  with pytest.raises(ValueError, match="constraint event .* is stale"):
    record_observation(
      ledger,
      run_id="run",
      actor="test",
      observation_id="obs_stale_constraint",
      design=Design("design_stale_constraint", {"x": 0.5}),
      objective_name="yield",
      objective=0.5,
      feasible=True,
      source_event_ids=source_event_ids,
      constraint_event_ids=(source_event_ids[1],),
      feasibility_rationale="scientific constraint passed",
    )


@pytest.mark.parametrize(
  ("unit", "value", "satisfied", "feasible", "message"),
  (
    ("relative", 1.0, True, True, "must use unit 'boolean'"),
    ("boolean", 0.5, True, True, "value must be exactly 0 or 1"),
    ("boolean", 1.0, False, False, "does not match its boolean value"),
  ),
)
def test_constraint_attestations_require_coherent_boolean_evidence(
  unit, value, satisfied, feasible, message
):
  ledger = EvidenceLedger()
  source_event_ids, decision = _training_sources(
    ledger,
    run_id="run",
    label="constraint_contract",
    objective=0.5,
  )
  assert decision.allowed
  invalid = SampleTracker(ledger, "run").record_measurement(
    "material_constraint_contract",
    measurement_id=f"constraint_invalid_{unit}_{value}_{satisfied}",
    metric="scientific_feasibility",
    value=value,
    unit=unit,
    metadata={
      "constraint_id": "scientific_feasibility",
      "constraint_satisfied": satisfied,
    },
  )

  with pytest.raises(ValueError, match=message):
    record_observation(
      ledger,
      run_id="run",
      actor="test",
      observation_id=f"obs_invalid_constraint_{unit}_{value}_{satisfied}",
      design=Design("design_invalid_constraint", {"x": 0.5}),
      objective_name="yield",
      objective=0.5,
      feasible=feasible,
      source_event_ids=(
        source_event_ids[0],
        invalid.event_id,
        source_event_ids[2],
      ),
      constraint_event_ids=(invalid.event_id,),
      feasibility_rationale="constraint attestation supplied",
    )


def test_qc_pass_can_train_a_scientifically_infeasible_observation():
  ledger = EvidenceLedger()
  observation = _record_design(
    ledger,
    run_id="run",
    label="infeasible",
    x=0.3,
    objective=0.4,
    feasible=False,
  )
  assert observation.training_eligible
  assert not observation.feasible
  sealed = ledger.event(observation.evidence_event_id)
  assert isinstance(sealed.payload["source_event_ids"], (list, tuple))
  assert isinstance(sealed.payload["constraint_event_ids"], (list, tuple))
  proposal = _optimizer().propose(
    ledger, [observation], run_id="run", actor="agent"
  )[0]
  assert proposal.observation_event_ids == (observation.evidence_event_id,)


def test_scientific_feasibility_label_must_match_constraint_evidence():
  ledger = EvidenceLedger()
  source_event_ids, decision = _training_sources(
    ledger,
    run_id="run",
    label="constraint_mismatch",
    objective=0.4,
    gate_allowed=True,
    scientifically_feasible=False,
  )
  assert decision.allowed
  with pytest.raises(ValueError, match="disagrees with sealed scientific constraint"):
    record_observation(
      ledger,
      run_id="run",
      actor="test",
      observation_id="constraint_mismatch",
      design=Design("constraint_mismatch", {"x": 0.4}),
      objective_name="yield",
      objective=0.4,
      feasible=True,
      source_event_ids=source_event_ids,
      constraint_event_ids=(source_event_ids[1],),
      feasibility_rationale="claimed feasible despite failed constraint",
    )


def test_optimizer_replays_sources_instead_of_trusting_a_raw_observation_event():
  ledger = EvidenceLedger()
  source_event_ids, decision = _training_sources(
    ledger,
    run_id="run",
    label="replay_failure",
    objective=0.5,
    gate_allowed=False,
    scientifically_feasible=True,
  )
  raw_event = ledger.append(
    run_id="run",
    kind=EventKind.OBSERVATION_RECORDED,
    actor="attacker",
    evidence_level=EvidenceLevel.MEASURED,
    payload={
      "observation_id": "raw_qualified",
      "design_id": "raw_design",
      "values": {"x": 0.5},
      "objective_name": "yield",
      "objective": 0.5,
      "feasible": True,
      "feasibility_rationale": "scientific constraint passed",
      "constraint_event_ids": [source_event_ids[1]],
      "disposition": "qualified",
      "training_eligible": True,
      "exclusion_reason": "",
      "source_event_ids": list(source_event_ids),
      "material_id": "material_replay_failure",
      "gate_event_id": decision.event_id,
    },
  )
  raw_observation = Observation(
    observation_id="raw_qualified",
    design=Design("raw_design", {"x": 0.5}),
    objective=0.5,
    feasible=True,
    evidence_event_id=raw_event.event_id,
    evidence_level=EvidenceLevel.MEASURED,
  )
  with pytest.raises(ValueError, match="QUALIFIED.*passing quality gate"):
    _optimizer().propose(
      ledger, [raw_observation], run_id="run", actor="agent"
    )


@pytest.mark.parametrize(
  ("field", "forged_value", "message"),
  (
    ("gate_event_id", "evt_not_a_source", "gate_event_id"),
    ("material_id", "material_someone_else", "material_id"),
  ),
)
def test_optimizer_rejects_forged_sealed_observation_link_fields(
  field, forged_value, message
):
  ledger = EvidenceLedger()
  source_event_ids, decision = _training_sources(
    ledger,
    run_id="run",
    label=field,
    objective=0.5,
  )
  payload = {
    "observation_id": f"raw_{field}",
    "design_id": f"design_{field}",
    "values": {"x": 0.5},
    "objective_name": "yield",
    "objective": 0.5,
    "feasible": True,
    "feasibility_rationale": "scientific constraint passed",
    "constraint_event_ids": [source_event_ids[1]],
    "disposition": "qualified",
    "training_eligible": True,
    "exclusion_reason": "",
    "source_event_ids": list(source_event_ids),
    "material_id": f"material_{field}",
    "gate_event_id": decision.event_id,
  }
  payload[field] = forged_value
  raw_event = ledger.append(
    run_id="run",
    kind=EventKind.OBSERVATION_RECORDED,
    actor="attacker",
    evidence_level=EvidenceLevel.MEASURED,
    payload=payload,
  )
  raw_observation = Observation(
    observation_id=f"raw_{field}",
    design=Design(f"design_{field}", {"x": 0.5}),
    objective=0.5,
    feasible=True,
    evidence_event_id=raw_event.event_id,
    evidence_level=EvidenceLevel.MEASURED,
  )
  with pytest.raises(ValueError, match=message):
    _optimizer().propose(
      ledger, [raw_observation], run_id="run", actor="agent"
    )


def test_optimizer_proposal_is_bounded_recorded_and_never_permission():
  ledger = EvidenceLedger()
  observations = [
    _record_design(
      ledger,
      run_id="run",
      label=str(index),
      x=x,
      objective=1.0 - abs(0.7 - x),
    )
    for index, x in enumerate((0.1, 0.5, 0.9), 1)
  ]
  proposal = _optimizer().propose(
    ledger, observations, run_id="run", actor="agent"
  )[0]
  assert 0.0 <= proposal.design.values["x"] <= 1.0
  assert proposal.uncertainty >= 0
  assert not proposal.execution_allowed
  event = ledger.event(proposal.event_id)
  assert event.kind is EventKind.DESIGN_PROPOSED
  assert event.evidence_level is EvidenceLevel.MODELED
  assert event.payload["execution_allowed"] is False
  assert event.payload["uncertainty_calibrated"] is False
  replayed = EvidenceLedger(events=ledger.events).event(proposal.event_id)
  policy = replayed.payload["policy"]
  assert digest(policy) == replayed.payload["policy_digest"] == proposal.policy_digest
  assert policy["algorithm"] == {
    "id": "deterministic_distance_weighted",
    "version": 1,
  }
  assert policy["objective"] == {"name": "yield", "direction": "maximize"}
  assert policy["variables"] == [
    {"name": "x", "lower": 0.0, "upper": 1.0, "unit": ""}
  ]
  assert len(policy["implementation"]["source_sha256"]) == 64


def test_optimizer_never_emits_duplicate_candidate_or_proposal_ids():
  proposals = _optimizer().propose(
    EvidenceLedger(),
    [],
    run_id="run",
    actor="agent",
    count=9,
  )
  assert len({proposal.design.design_id for proposal in proposals}) == 9
  assert len({proposal.proposal_id for proposal in proposals}) == 9
  assert len(
    {
      tuple(sorted(proposal.design.values.items()))
      for proposal in proposals
    }
  ) == 9


def test_optimizer_rejects_a_ledger_wide_duplicate_proposal():
  ledger = EvidenceLedger()
  observation = _record_design(
    ledger,
    run_id="run",
    label="repeat",
    x=0.2,
    objective=0.5,
  )
  optimizer = _optimizer()
  first = optimizer.propose(
    ledger, [observation], run_id="run", actor="agent"
  )[0]

  with pytest.raises(ValueError, match="design_id .* already exists"):
    optimizer.propose(ledger, [observation], run_id="run", actor="agent")

  proposed = [
    event for event in ledger.events if event.kind is EventKind.DESIGN_PROPOSED
  ]
  assert [event.event_id for event in proposed] == [first.event_id]


def test_optimizer_is_invariant_to_caller_observation_order():
  source = EvidenceLedger()
  observations = [
    _record_design(
      source,
      run_id="run",
      label=f"order_{index}",
      x=x,
      objective=objective,
    )
    for index, (x, objective) in enumerate(
      ((0.15, 0.4), (0.45, 0.8), (0.85, 0.6)),
      1,
    )
  ]
  forward_ledger = EvidenceLedger(events=source.events)
  reverse_ledger = EvidenceLedger(events=source.events)

  forward = _optimizer().propose(
    forward_ledger,
    observations,
    run_id="run",
    actor="agent",
  )[0]
  reverse = _optimizer().propose(
    reverse_ledger,
    list(reversed(observations)),
    run_id="run",
    actor="agent",
  )[0]

  assert forward.dataset_digest == reverse.dataset_digest
  assert forward.proposal_id == reverse.proposal_id
  assert forward.design == reverse.design
  assert forward.predicted_objective == reverse.predicted_objective
  assert forward.acquisition_score == reverse.acquisition_score


def test_stale_optimizer_cannot_race_a_duplicate_proposal(tmp_path):
  path = tmp_path / "proposal-race.jsonl"
  source = EvidenceLedger(str(path))
  observation = _record_design(
    source,
    run_id="run",
    label="proposal_race",
    x=0.2,
    objective=0.5,
  )
  first_writer = EvidenceLedger(str(path))
  stale_writer = EvidenceLedger(str(path))
  optimizer = _optimizer()
  first = optimizer.propose(
    first_writer, [observation], run_id="run", actor="agent"
  )[0]

  with pytest.raises(ValueError, match="ledger changed"):
    optimizer.propose(
      stale_writer, [observation], run_id="run", actor="agent"
    )

  reopened = EvidenceLedger(str(path))
  proposed = [
    event for event in reopened.events if event.kind is EventKind.DESIGN_PROPOSED
  ]
  assert [event.event_id for event in proposed] == [first.event_id]


def test_optimizer_refuses_out_of_bounds_observation():
  ledger = EvidenceLedger()
  source_event_ids, _decision = _training_sources(
    ledger,
    run_id="run",
    label="bounds",
    objective=1.0,
  )
  observation = record_observation(
    ledger,
    run_id="run",
    actor="test",
    observation_id="bad",
    design=Design("bad", {"x": 2.0}),
    objective_name="yield",
    objective=1.0,
    feasible=True,
    source_event_ids=source_event_ids,
    constraint_event_ids=(source_event_ids[1],),
    feasibility_rationale="scientific constraint passed",
  )
  with pytest.raises(ValueError, match="outside"):
    _optimizer().propose(ledger, [observation], run_id="run", actor="agent")


def test_optimizer_refuses_observation_fields_that_drift_from_evidence():
  ledger = EvidenceLedger()
  observation = _record_design(
    ledger, run_id="run", label="sealed", x=0.4, objective=0.7
  )
  forged = replace(observation, objective=700.0, feasible=False)
  with pytest.raises(ValueError, match="drifted from sealed fields"):
    _optimizer().propose(ledger, [forged], run_id="run", actor="agent")


# -- integrated demo ----------------------------------------------------------


def test_demo_closes_the_loop_without_laundering_simulation():
  ledger = EvidenceLedger()
  summary = run_demo(ledger)
  assert summary.material_count == 5
  assert summary.qualified_observations == 3
  assert summary.quarantined_observations == 1
  assert GateOutcome.FAIL in summary.gate_outcomes
  assert not summary.proposal.execution_allowed
  assert ledger.verify().ok
  levels = {event.evidence_level for event in ledger.events}
  assert EvidenceLevel.MEASURED not in levels
  assert EvidenceLevel.HARDWARE_VALIDATED not in levels
  trace = SampleTracker(ledger, summary.run_id).lineage("output_a")
  assert [material.material_id for material in trace.ancestors] == [
    "input_001",
    "output_a",
  ]


def test_demo_refuses_a_nonempty_ledger_before_appending():
  ledger = EvidenceLedger()
  ledger.append(
    run_id="other",
    kind=EventKind.RUN_STARTED,
    actor="test",
    evidence_level=EvidenceLevel.MODELED,
    payload={},
  )
  before = ledger.events
  with pytest.raises(ValueError, match="requires an empty evidence ledger"):
    run_demo(ledger, run_id="different")
  assert ledger.events == before


# -- corrected execution truth ------------------------------------------------


def test_network_probe_without_endpoint_is_not_automated_or_an_re_gap():
  step = Step(
    instrument="element_aviti",
    op=ZeroDecodeOp.PROBE_HTTP.value,
    summary="probe",
  )
  verdict = cost_step(step, Workcell.default())
  assert verdict.verdict is Verdict.BLOCKED
  assert "endpoint" in verdict.reason
  from autonomous_lab.model import Protocol

  protocol = Protocol(name="probe", summary="x", steps=(step,))
  assert Executor(Workcell.default()).run(protocol).ledger.unlocks() == []


def test_placeholder_run_folder_is_not_automated():
  step = Step(
    instrument="element_aviti",
    op=ZeroDecodeOp.WATCH_RUN_FOLDER.value,
    summary="watch",
    params={"run_dir": "/runs/<run>"},
  )
  verdict = cost_step(step, Workcell.default())
  assert verdict.verdict is Verdict.BLOCKED
  assert "concrete run" in verdict.reason


def _write_finished_map(tmp_path):
  protocol_map = seed("namocell")
  for command in protocol_map.commands.values():
    command.decoded = True
    command.frame_template = "aa"
  protocol_map.transport = Transport.SERIAL
  protocol_map.endpoint = "/dev/map-endpoint"
  path = tmp_path / "map.json"
  protocol_map.to_json(str(path))
  return protocol_map, path


def test_protocol_map_cannot_relabel_an_actuating_command_read_only(tmp_path):
  protocol_map, path = _write_finished_map(tmp_path)
  protocol_map.commands["start_sort"].actuating = False
  protocol_map.to_json(str(path))
  workcell = Workcell.default()
  workcell.instruments["namocell"] = type(workcell.instruments["namocell"])(
    key="namocell", map_path=str(path)
  )
  with pytest.raises(ValueError, match="start_sort.*actuating=False"):
    workcell.protocol_map("namocell")


def test_protocol_map_cannot_drop_required_commands_or_templates(tmp_path):
  protocol_map, path = _write_finished_map(tmp_path)
  protocol_map.commands.pop("start_sort")
  protocol_map.to_json(str(path))
  workcell = Workcell.default()
  workcell.instruments["namocell"] = type(workcell.instruments["namocell"])(
    key="namocell", map_path=str(path)
  )
  with pytest.raises(ValueError, match="command set drifted"):
    workcell.protocol_map("namocell")

  protocol_map, path = _write_finished_map(tmp_path)
  protocol_map.commands["get_status"].frame_template = None
  protocol_map.to_json(str(path))
  with pytest.raises(ValueError, match="get_status.*no frame template"):
    workcell.protocol_map("namocell")


def test_workcell_endpoint_overrides_stale_map_endpoint_and_snapshot_is_frozen(
  tmp_path,
):
  protocol_map, path = _write_finished_map(tmp_path)
  workcell = Workcell.default()
  workcell.instruments["namocell"] = type(workcell.instruments["namocell"])(
    key="namocell",
    map_path=str(path),
    endpoint="/dev/current-bench",
  )
  snapshot = workcell.snapshot(("namocell",))
  assert snapshot.protocol_map("namocell").endpoint == "/dev/current-bench"

  protocol_map.commands["get_status"].frame_template = "bb"
  protocol_map.to_json(str(path))
  assert workcell.protocol_map("namocell").commands["get_status"].frame_template == "bb"
  assert snapshot.protocol_map("namocell").commands["get_status"].frame_template == "aa"

  snapshot._resolved_maps["namocell"].commands["start_sort"].actuating = False
  with pytest.raises(ValueError, match="start_sort.*actuating=False"):
    snapshot.protocol_map("namocell")


def test_missing_run_folder_is_blocked_even_when_path_looks_concrete(tmp_path):
  missing = tmp_path / "not-created"
  step = Step(
    instrument="element_aviti",
    op=ZeroDecodeOp.WATCH_RUN_FOLDER.value,
    summary="watch",
    params={"run_dir": str(missing)},
  )
  verdict = cost_step(step, Workcell.default())
  assert verdict.verdict is Verdict.BLOCKED
  assert "not an existing directory" in verdict.reason


def test_decoded_map_cannot_authorize_its_own_request_bytes(tmp_path):
  pm = seed("namocell")
  for command in pm.commands.values():
    command.decoded = True
    command.frame_template = "aa"
  pm.transport = Transport.SERIAL
  pm.endpoint = "/dev/fake"
  path = tmp_path / "map.json"
  pm.to_json(str(path))
  wc = Workcell.default()
  wc.instruments["namocell"] = type(wc.instruments["namocell"])(
    key="namocell", map_path=str(path)
  )
  step = Step(instrument="namocell", op="get_status", summary="status")
  assert cost_step(step, wc).verdict is Verdict.SUPERVISED
  with pytest.raises(RuntimeError, match="cannot independently prove"):
    Executor(wc, armed=True)._perform(step)


def test_executor_run_ids_are_unique_and_dry_run_is_not_permission():
  from autonomous_lab.model import Protocol

  protocol = Protocol(
    name="discovery",
    summary="read-only discovery",
    steps=(
      Step(
        instrument="namocell",
        op=ZeroDecodeOp.DISCOVER_USB.value,
        summary="discover",
      ),
    ),
  )
  evidence = EvidenceLedger()
  executor = Executor(
    Workcell.default(),
    armed=False,
    evidence=evidence,
    run_id="attempt_1",
  )
  executor.run(protocol)
  permission = next(
    event
    for event in evidence.by_run("attempt_1")
    if event.kind is EventKind.PERMISSION_EVALUATED
  )
  assert permission.payload["capability_ready"] is True
  assert permission.payload["execution_allowed"] is False
  assert permission.payload["actuation_allowed"] is False
  started = evidence.by_run("attempt_1")[0]
  assert started.payload["protocol_map_digests"] == {}
  assert len(started.payload["control_dependency"]["source_digest"]) == 64
  assert len(started.payload["kernel_identity"]["source_digest"]) == 64
  assert started.payload["kernel_identity"]["version"] == "0.2.0"
  assert started.payload["federated_dependency"]["configured"] is False
  with pytest.raises(ValueError, match="already exists"):
    executor.run(protocol)


def test_executor_records_permission_and_stop_evidence():
  from autonomous_lab import protocols

  evidence = EvidenceLedger()
  report = Executor(
    Workcell.default(),
    armed=False,
    evidence=evidence,
    run_id="run_evidence",
    actor="scheduler",
  ).run(protocols.get("single_cell_genomics"))
  assert report.evidence_head == evidence.head_hash
  kinds = [event.kind for event in evidence.by_run("run_evidence")]
  assert kinds[0] is EventKind.RUN_STARTED
  assert EventKind.PERMISSION_EVALUATED in kinds
  assert kinds[-1] is EventKind.RUN_STOPPED
  assert evidence.verify().ok
