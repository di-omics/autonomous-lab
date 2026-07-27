"""Evidence and permission for autonomous laboratory workflows.

di-omics/plr-reverse-engineer brings instruments under control one at a time. This package
asks the question that only makes sense across all of them at once: given the instruments
on the bench and the command sets decoded so far, how much of a real protocol runs
unattended, what exactly is blocking the rest, and does current physical evidence permit
the proposed next action?

    from autonomous_lab import Workcell, build_ledger, protocols

    ledger = build_ledger(protocols.get("single_cell_genomics"))
    ledger.autonomy()         # fraction of steps that run headless today
    ledger.headless_prefix()  # how far an unattended run actually gets
    ledger.unlocks()          # which decode would free the most steps, ranked

The answers are currently bleak, and that is the feature. Nothing here can flatter the
lab: automation is derived from the resolved ProtocolMap, missing QC stops a decision,
and the reference protocols include the cartridge seating and flow-cell loading that a
demo would quietly omit.
"""

from .executor import Executor, Handoff, RunReport, StepResult
from .intelligence import (
  Comparator,
  DecisionAction,
  DecisionEngine,
  EvidenceGate,
  EvidenceKind,
  ExpertPolicy,
  GateResult,
  GateStatus,
  Observation,
  PermissionDecision,
)
from .ledger import Ledger, StepVerdict, Unlock, build_ledger, cost_step, rank_unlocks
from .model import Artifact, Protocol, Role, Step, Tier, Verdict, ZeroDecodeOp
from .orchestrator import (
  AdapterBinding,
  AttemptRecord,
  ContractApproval,
  ContractRegistry,
  ExecutionPermit,
  GuardedOperation,
  GuardedRecovery,
  OperationContract,
  OperationResult,
  OperationStatus,
  OrchestrationReport,
  SampleEffect,
  RecoveryPermit,
  RecoveryBinding,
  RecoveryResult,
  RecoveryStatus,
  ResourceBusy,
  ResourceLease,
  ResourceManager,
  TaskFinalState,
  WorkcellOrchestrator,
  WorkcellTask,
)
from .provenance import LedgerEvent, RunLedger, SampleState, SampleTracker
from .registry import FEDERATED, FederatedSpec, InstrumentSpec, declared, registry, spec
from .throughput import CapacityStage, ThroughputPlan, ThroughputReport
from .workcell import InstrumentConfig, Workcell

__all__ = [
  "Artifact",
  "AdapterBinding",
  "AttemptRecord",
  "CapacityStage",
  "Comparator",
  "ContractApproval",
  "ContractRegistry",
  "DecisionAction",
  "DecisionEngine",
  "EvidenceGate",
  "EvidenceKind",
  "ExecutionPermit",
  "Executor",
  "ExpertPolicy",
  "FEDERATED",
  "FederatedSpec",
  "GateResult",
  "GateStatus",
  "GuardedOperation",
  "GuardedRecovery",
  "Handoff",
  "InstrumentConfig",
  "InstrumentSpec",
  "Ledger",
  "LedgerEvent",
  "Observation",
  "OperationContract",
  "OperationResult",
  "OperationStatus",
  "OrchestrationReport",
  "SampleEffect",
  "PermissionDecision",
  "Protocol",
  "RecoveryPermit",
  "RecoveryBinding",
  "RecoveryResult",
  "RecoveryStatus",
  "Role",
  "ResourceBusy",
  "ResourceLease",
  "ResourceManager",
  "RunLedger",
  "RunReport",
  "SampleState",
  "SampleTracker",
  "Step",
  "StepResult",
  "StepVerdict",
  "Tier",
  "TaskFinalState",
  "ThroughputPlan",
  "ThroughputReport",
  "Unlock",
  "Verdict",
  "Workcell",
  "WorkcellOrchestrator",
  "WorkcellTask",
  "ZeroDecodeOp",
  "build_ledger",
  "cost_step",
  "declared",
  "rank_unlocks",
  "registry",
  "spec",
]
