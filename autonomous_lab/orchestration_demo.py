"""Synthetic workcell scenarios for the policy-gated orchestrator."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Tuple

from .demo import library_commit_policy
from .intelligence import (
  Comparator,
  DecisionAction,
  EvidenceGate,
  EvidenceKind,
  ExpertPolicy,
  Observation,
)
from .orchestrator import (
  AdapterBinding,
  ContractApproval,
  ContractRegistry,
  GuardedOperation,
  GuardedRecovery,
  OperationContract,
  OperationResult,
  OperationStatus,
  OrchestrationReport,
  SampleEffect,
  RecoveryResult,
  RecoveryBinding,
  RecoveryStatus,
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
  "postcondition_failure",
  "ambiguous_driver_timeout",
)


def _captured_at() -> str:
  return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _evidence(aligned: bool, attempt: int) -> Tuple[Observation, ...]:
  captured = _captured_at()
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


def _postcondition_policy() -> ExpertPolicy:
  return ExpertPolicy(
    "library_at_sequencer_staging",
    "1.0.0-demo",
    (
      EvidenceGate(
        gate_id="destination_pose",
        metric="at_sequencer_staging",
        comparator=Comparator.EQUAL,
        allowed_sources=(EvidenceKind.VISION,),
        failure_action=DecisionAction.STOP,
        recovery_id="reconcile_sample_location",
        recovery="quarantine the sample and reconcile its location with an operator",
        subject="$sample",
        expected=True,
        rationale="a successful driver response is not evidence that the plate arrived",
        max_age_seconds=30,
        max_future_skew_seconds=2,
      ),
    ),
    "example workcell owner",
    "Synthetic postcondition; replace with a validated camera policy.",
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
  contract = OperationContract(
    operation_id="stage_library_for_sequencing",
    version="1.0.0-demo",
    expected_location="plate_reader",
    success_location="sequencer_staging",
    required_resources=("camera-01", "plate-mover-01", "sequencer-01"),
    preconditions=library_commit_policy("$sample"),
    postconditions=_postcondition_policy(),
    max_retries=1 if scenario == "transient_retry" else 0,
    max_recoveries=1 if scenario == "vision_recovery" else 0,
    allowed_adapters=(
      AdapterBinding(
        "synthetic-workcell",
        "1.0.0-demo",
        "sha256:synthetic-configuration",
      ),
    ),
    recovery_adapters=(
      RecoveryBinding(
        "repeat_quantification",
        AdapterBinding(
          "synthetic-workcell",
          "1.0.0-demo",
          "sha256:synthetic-configuration",
        ),
      ),
      RecoveryBinding(
        "rehome_plate_mover",
        AdapterBinding(
          "synthetic-workcell",
          "1.0.0-demo",
          "sha256:synthetic-configuration",
        ),
      ),
    ),
  )
  contracts = ContractRegistry(
    (
      ContractApproval(
        contract,
        "example workcell owner",
        "synthetic://approval/stage-library-for-sequencing-v1",
      ),
    )
  )
  orchestrator = WorkcellOrchestrator(
    ledger,
    samples,
    resources,
    contracts=contracts,
  )
  task = WorkcellTask(
    task_id="stage-library-001",
    proposal="move the QC-passing library into sequencer staging",
    sample_id="library-plate-001",
    contract=contract,
  )
  state: Dict[str, object] = {"aligned": scenario != "vision_recovery"}

  def evidence(_task, attempt):
    return _evidence(bool(state["aligned"]), attempt)

  def operation(_task, attempt, permit):
    if scenario == "ambiguous_driver_timeout":
      raise TimeoutError("synthetic acknowledgment was lost after motion may have started")
    if scenario == "transient_retry" and attempt == 1:
      return OperationResult(
        OperationStatus.RETRYABLE,
        "synthetic controller was busy; no motion started",
        SampleEffect.NO_CHANGE,
        permit.permit_id,
        payload={"error_code": "SIM_BUSY"},
      )
    if scenario == "fatal_driver_error":
      return OperationResult(
        OperationStatus.FAILED,
        "synthetic driver reported a non-recoverable calibration fault",
        SampleEffect.NO_CHANGE,
        permit.permit_id,
        payload={"error_code": "SIM_CALIBRATION"},
      )
    return OperationResult(
      OperationStatus.SUCCEEDED,
      "synthetic adapter completed its transfer command",
      SampleEffect.EXPECTED_CHANGE,
      permit.permit_id,
      payload={"destination": "sequencer_staging"},
    )

  def post_evidence(_task, attempt):
    return (
      Observation(
        "at_sequencer_staging",
        scenario != "postcondition_failure",
        EvidenceKind.VISION,
        "library-plate-001",
        "synthetic overhead camera",
        _captured_at(),
        f"synthetic://vision/postcondition-{attempt}",
      ),
    )

  def recover(_task, reason, count, permit):
    state["aligned"] = True
    state["last_recovery"] = {"reason": reason, "count": count}
    return RecoveryResult(
      RecoveryStatus.SUCCEEDED,
      "synthetic re-home completed without touching the sample",
      SampleEffect.NO_CHANGE,
      permit.permit_id,
    )

  guarded_operation = GuardedOperation(
    "stage_library_for_sequencing",
    "synthetic-workcell",
    "1.0.0-demo",
    "sha256:synthetic-configuration",
    operation,
  )
  guarded_recovery = GuardedRecovery(
    "rehome_plate_mover",
    "synthetic-workcell",
    "1.0.0-demo",
    "sha256:synthetic-configuration",
    recover,
  )

  blocker = None
  if scenario == "resource_busy":
    blocker = resources.acquire("synthetic-other-task", ("plate-mover-01",))
  try:
    return orchestrator.run(
      task,
      evidence,
      guarded_operation,
      post_evidence,
      guarded_recovery,
    )
  finally:
    if blocker is not None:
      blocker.release()
