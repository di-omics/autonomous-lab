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

Executing a protocol is only the first of four things a lab must do to close a loop, so
five further layers ask whether the rest hold:

    from autonomous_lab import loop_closure_for, protocols

    closure = loop_closure_for(protocols.get("single_cell_genomics"))
    closure.closes    # False
    closure.broken()  # and which of execute/measure/decide/record failed, and why

  qc            can a QC gate be evaluated at all, or does its input come from a broken
                instrument? A gate that cannot fire makes a run look supervised and is not.
  vision        what a camera could verify, and the failures no camera ever resolves.
  recovery      what goes wrong, whether anything here would notice, and how late.
  throughput    plates per day -- or an honest refusal, when nothing has been timed.
  provenance    a tamper-evident run record, and where the custody chain breaks.
  lineage       which cell a read came from -- and whether pooling already destroyed the
                answer, which is a different question from whether the plate was tracked.
  intelligence  the tacit expert judgment and the benchmarks a robot must meet first.
"""

from .executor import Executor, Handoff, RunReport, StepResult
from .intelligence import (
  Benchmark,
  BenchmarkStatus,
  Comparator,
  DecisionAction,
  DecisionEngine,
  EvidenceGate,
  EvidenceKind,
  ExpertPolicy,
  GateResult,
  GateStatus,
  Judgment,
  Leg,
  LoopClosure,
  Observation,
  PermissionDecision,
  knowledge_summary,
  loop_closure,
  trusted_for,
)
from .ledger import Ledger, StepVerdict, Unlock, build_ledger, cost_step, rank_unlocks
from .lineage import (
  MISASSIGNMENT,
  Cohort,
  LineageEdge,
  LineageGraph,
  LineageReport,
  Misassignment,
  Separability,
  Traceability,
  UndeclaredTransform,
  build_lineage,
  lineage_report,
  undeclared_transforms,
)
from .model import Artifact, Protocol, Role, Step, Tier, Transform, Verdict, ZeroDecodeOp
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
from .provenance import (
  Attestation,
  CustodyGap,
  Event,
  LedgerEvent,
  RunLedger,
  RunRecord,
  SampleState,
  SampleTracker,
  provenance_report,
)
from .qc import Basis, Criterion, Decision, Gate, Readiness, evaluate, gate_report
from .recovery import Detection, FailureMode, Latency, Severity, recovery_report
from .registry import FEDERATED, FederatedSpec, InstrumentSpec, declared, registry, spec
from .throughput import (
  CapacityStage,
  Duration,
  ThroughputPlan,
  ThroughputReport,
  TimeBasis,
  estimate,
)
from .vision import Observable, VisionCapability, VisionRequirement, VisualCheck
from .workcell import InstrumentConfig, Workcell


def loop_closure_for(protocol, workcell=None):
  """Every layer at once: can this lab close a loop on this protocol?

  A convenience over the five reports, wired in the only order that is correct -- the
  ledger first, because every other layer is costed against its verdicts rather than
  recomputing them.
  """
  ledger = build_ledger(protocol, workcell)
  gates = gate_report(protocol.name, ledger)
  return loop_closure(
    ledger,
    gates,
    recovery_report(protocol, gates, VisionCapability.none()),
    provenance_report(ledger),
  )


__all__ = [
  "AdapterBinding",
  "Artifact",
  "Attestation",
  "AttemptRecord",
  "Basis",
  "Benchmark",
  "BenchmarkStatus",
  "CapacityStage",
  "Cohort",
  "Comparator",
  "ContractApproval",
  "ContractRegistry",
  "Criterion",
  "CustodyGap",
  "Decision",
  "DecisionAction",
  "DecisionEngine",
  "Detection",
  "Duration",
  "EvidenceGate",
  "EvidenceKind",
  "Event",
  "ExecutionPermit",
  "Executor",
  "ExpertPolicy",
  "FEDERATED",
  "FailureMode",
  "FederatedSpec",
  "Gate",
  "GateResult",
  "GateStatus",
  "GuardedOperation",
  "GuardedRecovery",
  "Handoff",
  "InstrumentConfig",
  "InstrumentSpec",
  "Judgment",
  "Latency",
  "Ledger",
  "LedgerEvent",
  "Leg",
  "LineageEdge",
  "LineageGraph",
  "LineageReport",
  "LoopClosure",
  "MISASSIGNMENT",
  "Misassignment",
  "Observation",
  "Observable",
  "OperationContract",
  "OperationResult",
  "OperationStatus",
  "OrchestrationReport",
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
  "RunRecord",
  "RunReport",
  "SampleEffect",
  "SampleState",
  "SampleTracker",
  "Readiness",
  "Separability",
  "Severity",
  "Step",
  "StepResult",
  "StepVerdict",
  "Tier",
  "TaskFinalState",
  "ThroughputPlan",
  "ThroughputReport",
  "TimeBasis",
  "Traceability",
  "Transform",
  "UndeclaredTransform",
  "Unlock",
  "Verdict",
  "VisionCapability",
  "VisionRequirement",
  "VisualCheck",
  "Workcell",
  "WorkcellOrchestrator",
  "WorkcellTask",
  "ZeroDecodeOp",
  "build_ledger",
  "build_lineage",
  "cost_step",
  "declared",
  "estimate",
  "evaluate",
  "gate_report",
  "knowledge_summary",
  "lineage_report",
  "loop_closure",
  "loop_closure_for",
  "provenance_report",
  "rank_unlocks",
  "recovery_report",
  "registry",
  "spec",
  "trusted_for",
  "undeclared_transforms",
]
