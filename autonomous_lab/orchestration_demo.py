"""Synthetic workcell scenarios for the policy-gated orchestrator."""

from __future__ import annotations

from typing import Dict, Tuple

from .demo import library_commit_policy
from .intelligence import EvidenceKind, Observation
from .orchestrator import (
  OperationResult,
  OperationStatus,
  OrchestrationReport,
  ResourceManager,
  WorkcellOrchestrator,
  WorkcellTask,
)
from .provenance import RunLedger, SampleTracker


ORCHESTRATION_SCENARIOS = (
  "pass",
  "transient_retry",
  "vision_recovery",
  "resource_busy",
  "fatal_driver_error",
)


def _evidence(aligned: bool, attempt: int) -> Tuple[Observation, ...]:
  captured = f"2026-01-01T00:00:{attempt:02d}Z"
  return (
    Observation(
      "library_concentration_ng_ul",
      5.4,
      EvidenceKind.ASSAY_QC,
      "library-plate-001",
      "synthetic plate reader",
      captured,
      f"synthetic://plate-reader/attempt-{attempt}",
    ),
    Observation(
      "labware_offset_mm",
      0.6 if aligned else 3.2,
      EvidenceKind.VISION,
      "library-plate-001",
      "synthetic overhead camera",
      captured,
      f"synthetic://vision/attempt-{attempt}",
    ),
    Observation(
      "seal_present",
      True,
      EvidenceKind.VISION,
      "library-plate-001",
      "synthetic overhead camera",
      captured,
      f"synthetic://vision/attempt-{attempt}",
    ),
    Observation(
      "instrument_ready",
      True,
      EvidenceKind.TELEMETRY,
      "sequencer-01",
      "synthetic sequencer API",
      captured,
      f"synthetic://telemetry/attempt-{attempt}",
    ),
  )


def run_orchestration_demo(scenario: str = "pass") -> OrchestrationReport:
  if scenario not in ORCHESTRATION_SCENARIOS:
    raise KeyError(
      f"unknown orchestration scenario {scenario!r}; known: {list(ORCHESTRATION_SCENARIOS)}"
    )
  ledger = RunLedger(f"synthetic-workcell-{scenario}")
  samples = SampleTracker(ledger)
  samples.register(
    "library-plate-001",
    "plate_reader",
    {"evidence": "synthetic fixture, not a physical sample"},
    "2026-01-01T00:00:00Z",
  )
  resources = ResourceManager()
  orchestrator = WorkcellOrchestrator(ledger, samples, resources)
  task = WorkcellTask(
    task_id="stage-library-001",
    proposal="move the QC-passing library into sequencer staging",
    sample_id="library-plate-001",
    expected_location="plate_reader",
    success_location="sequencer_staging",
    resources=("camera-01", "plate-mover-01", "sequencer-01"),
    policy=library_commit_policy(),
    max_retries=1 if scenario == "transient_retry" else 0,
    max_recoveries=1 if scenario == "vision_recovery" else 0,
  )
  state: Dict[str, object] = {"aligned": scenario != "vision_recovery"}

  def evidence(_task, attempt):
    return _evidence(bool(state["aligned"]), attempt)

  def operation(_task, attempt):
    if scenario == "transient_retry" and attempt == 1:
      return OperationResult(
        OperationStatus.RETRYABLE,
        "synthetic controller was busy; no motion started",
        {"error_code": "SIM_BUSY"},
      )
    if scenario == "fatal_driver_error":
      return OperationResult(
        OperationStatus.FAILED,
        "synthetic driver reported a non-recoverable calibration fault",
        {"error_code": "SIM_CALIBRATION"},
      )
    return OperationResult(
      OperationStatus.SUCCEEDED,
      "synthetic transfer completed and postcondition was acknowledged",
      {"destination": "sequencer_staging"},
    )

  def recover(_task, reason, count):
    state["aligned"] = True
    state["last_recovery"] = {"reason": reason, "count": count}

  blocker = None
  if scenario == "resource_busy":
    blocker = resources.acquire("synthetic-other-task", ("plate-mover-01",))
  try:
    return orchestrator.run(task, evidence, operation, recover)
  finally:
    if blocker is not None:
      blocker.release()
