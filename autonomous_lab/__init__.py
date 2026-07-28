"""How much of an end-to-end lab run happens without a human, and what is in the way.

di-omics/plr-reverse-engineer brings instruments under control one at a time. This package
asks the question that only makes sense across all of them at once: given the instruments
on the bench and the command sets decoded so far, how much of a real protocol runs
unattended, and what exactly is blocking the rest?

    from autonomous_lab import Workcell, build_ledger, protocols

    ledger = build_ledger(protocols.get("single_cell_genomics"))
    ledger.autonomy()         # fraction of steps that run headless today
    ledger.headless_prefix()  # how far an unattended run actually gets
    ledger.unlocks()          # which decode would free the most steps, ranked

The answers are currently bleak, and that is the feature. Nothing here can flatter the
lab: verdicts are computed from the resolved ProtocolMap, so a step is automated only if
its command is genuinely decoded, and the reference protocols include the cartridge
seating and flow-cell loading that a demo would quietly omit.

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

Four further layers cover what a workcell needs once more than one instrument is involved
and the lab has to keep running:

  coverage      vision and QC gates composed. For every failure that destroys material, is
                there ANYTHING that would catch it? Where a camera is physically incapable,
                an assay is the only option left, so an invisible failure with no gate is
                uncovered and no CV budget ever changes that.
  durability    what an instrument is currently entitled to be trusted with, and whether a
                planned campaign crosses a service boundary mid-run. Not a failure
                predictor -- that needs reliability data this package does not have.
  teaching      an expert demonstrating an operation, and a machine measured against that
                demonstration. A demonstration is data, not authority: one performance is a
                value with no tolerance, and saying so is the point.
  feedback      whether a control loop can actually close. A sensor downstream of its own
                actuator is a post-mortem wearing the costume of a control loop.

`Envelope` is defined in both `teaching` (what an expert demonstrated) and `feedback` (what
a loop steers toward). They are related and not the same, so neither is re-exported here --
import from the module that means the one you want.
"""

from .coverage import (
  Ceiling,
  Cover,
  CoverageReport,
  CoverageRow,
  Demand,
  SotaLift,
  coverage_report,
  mandatory_gates,
  sota_lift,
  unmet_demands,
)
from .durability import (
  Accrued,
  BoundaryReport,
  Campaign,
  Entitlement,
  InstrumentHealth,
  Interval,
  IntervalKind,
  ServiceRecord,
  crosses_boundary,
  entitlement_summary,
  untrusted_instruments,
)
from .executor import Executor, Handoff, RunReport, StepResult
from .feedback import (
  Closable,
  Closure,
  Controller,
  Correction,
  FeedbackReport,
  Loop,
  can_close,
  feedback_report,
  in_flight_exposure,
)
from .intelligence import (
  Benchmark,
  BenchmarkStatus,
  Judgment,
  Leg,
  LoopClosure,
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
from .provenance import Attestation, CustodyGap, Event, RunRecord, provenance_report
from .qc import Basis, Criterion, Decision, Gate, Readiness, evaluate, gate_report
from .teaching import (
  Attainment,
  Demonstration,
  MachineObservation,
  NextDemonstration,
  TransferReport,
  TransferRow,
  attainment,
  demonstration_queue,
  envelope_for,
  taught,
  transfer_report,
  untaught_operations,
)
from .recovery import Detection, FailureMode, Latency, Severity, recovery_report
from .registry import FEDERATED, FederatedSpec, InstrumentSpec, declared, registry, spec
from .throughput import Duration, TimeBasis, estimate
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
  "Accrued",
  "Artifact",
  "Attainment",
  "Attestation",
  "Basis",
  "Benchmark",
  "BenchmarkStatus",
  "BoundaryReport",
  "Campaign",
  "Ceiling",
  "Closable",
  "Closure",
  "Cohort",
  "Controller",
  "Correction",
  "Cover",
  "CoverageReport",
  "CoverageRow",
  "Criterion",
  "CustodyGap",
  "Decision",
  "Demand",
  "Demonstration",
  "Detection",
  "Duration",
  "Entitlement",
  "Event",
  "Executor",
  "FEDERATED",
  "FailureMode",
  "FederatedSpec",
  "FeedbackReport",
  "Gate",
  "Handoff",
  "InstrumentConfig",
  "InstrumentHealth",
  "InstrumentSpec",
  "Interval",
  "IntervalKind",
  "Judgment",
  "Latency",
  "Ledger",
  "Leg",
  "LineageEdge",
  "LineageGraph",
  "LineageReport",
  "Loop",
  "LoopClosure",
  "MISASSIGNMENT",
  "MachineObservation",
  "Misassignment",
  "NextDemonstration",
  "Observable",
  "Protocol",
  "Readiness",
  "Role",
  "RunRecord",
  "RunReport",
  "Separability",
  "ServiceRecord",
  "Severity",
  "SotaLift",
  "Step",
  "StepResult",
  "StepVerdict",
  "Tier",
  "TimeBasis",
  "Traceability",
  "TransferReport",
  "TransferRow",
  "Transform",
  "UndeclaredTransform",
  "Unlock",
  "Verdict",
  "VisionCapability",
  "VisionRequirement",
  "VisualCheck",
  "Workcell",
  "ZeroDecodeOp",
  "attainment",
  "build_ledger",
  "build_lineage",
  "can_close",
  "cost_step",
  "coverage_report",
  "crosses_boundary",
  "declared",
  "demonstration_queue",
  "entitlement_summary",
  "envelope_for",
  "estimate",
  "evaluate",
  "feedback_report",
  "gate_report",
  "in_flight_exposure",
  "knowledge_summary",
  "lineage_report",
  "loop_closure",
  "loop_closure_for",
  "mandatory_gates",
  "provenance_report",
  "rank_unlocks",
  "recovery_report",
  "registry",
  "sota_lift",
  "spec",
  "taught",
  "transfer_report",
  "trusted_for",
  "undeclared_transforms",
  "unmet_demands",
  "untaught_operations",
  "untrusted_instruments",
]
