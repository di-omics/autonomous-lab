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

Three further layers ask the question the others cannot, because it is not about this lab
at all: is the ambition supported by anything published, who is allowed to decide, and what
does a stated throughput target actually cost?

  literature    what the published record demonstrates -- and, entry by entry, what it
                explicitly does NOT establish. Scope, not fame, decides whether a paper
                supports a claim.
  authority     which decisions a model may make, which need a deterministic interlock, and
                which need a named accountable human. Authority may be strengthened, never
                weakened.
  cadence       a plates-per-day target converted into the admission interval it implies,
                and refused until it says whether it counts plates started, completed,
                QC-passed, or released.
"""

from .executor import Executor, Handoff, RunReport, StepResult
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
from .authority import (
  Authority,
  DecisionClass,
  Plan,
  QualificationRung,
  Rung,
  Violation,
  qualified_for,
  violations,
)
from .cadence import (
  Cadence,
  Demonstration,
  Endpoint,
  Target,
  cadence_for,
  demonstrated_support,
  headroom,
  launch_interval,
  sustained_rate_demonstrations,
)
from .ledger import Ledger, StepVerdict, Unlock, build_ledger, cost_step, rank_unlocks
from .literature import (
  EVIDENCE,
  Confidence,
  Domain,
  Evidence,
  EvidenceKind,
  Scope,
  Support,
  support_for,
  unsupported_claims,
)
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
  "Artifact",
  "Authority",
  "Cadence",
  "Cohort",
  "Confidence",
  "MISASSIGNMENT",
  "Attestation",
  "Basis",
  "Benchmark",
  "BenchmarkStatus",
  "Criterion",
  "DecisionClass",
  "Demonstration",
  "Domain",
  "EVIDENCE",
  "Endpoint",
  "Evidence",
  "EvidenceKind",
  "CustodyGap",
  "Decision",
  "Detection",
  "Duration",
  "Event",
  "Executor",
  "FEDERATED",
  "FailureMode",
  "FederatedSpec",
  "Gate",
  "Handoff",
  "InstrumentConfig",
  "InstrumentSpec",
  "Judgment",
  "Latency",
  "Ledger",
  "Leg",
  "LineageEdge",
  "LineageGraph",
  "LineageReport",
  "Misassignment",
  "LoopClosure",
  "Observable",
  "Plan",
  "Protocol",
  "QualificationRung",
  "Readiness",
  "Role",
  "RunRecord",
  "Rung",
  "Scope",
  "Separability",
  "RunReport",
  "Severity",
  "Step",
  "StepResult",
  "Support",
  "StepVerdict",
  "Tier",
  "Target",
  "TimeBasis",
  "Traceability",
  "Transform",
  "UndeclaredTransform",
  "Unlock",
  "Verdict",
  "Violation",
  "VisionCapability",
  "VisionRequirement",
  "VisualCheck",
  "Workcell",
  "ZeroDecodeOp",
  "build_ledger",
  "build_lineage",
  "cadence_for",
  "cost_step",
  "declared",
  "demonstrated_support",
  "estimate",
  "evaluate",
  "gate_report",
  "headroom",
  "knowledge_summary",
  "launch_interval",
  "lineage_report",
  "loop_closure",
  "loop_closure_for",
  "provenance_report",
  "qualified_for",
  "rank_unlocks",
  "recovery_report",
  "registry",
  "spec",
  "support_for",
  "sustained_rate_demonstrations",
  "trusted_for",
  "undeclared_transforms",
  "unsupported_claims",
  "violations",
]
