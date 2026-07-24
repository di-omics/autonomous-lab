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
lab: only built-in zero-decode reads can be automated. A decoded ProtocolMap remains
supervised because it cannot independently approve its own request bytes, and the
reference protocols include the cartridge seating and flow-cell loading that a demo
would quietly omit.
"""

from .evidence import (
  GENESIS_HASH,
  EventKind,
  EvidenceEvent,
  EvidenceLedger,
  EvidenceLevel,
  VerificationReport,
  canonical_json,
  digest,
  file_digest,
)
from .executor import Executor, Handoff, RunReport, StepResult
from .gates import (
  AcceptanceRule,
  Comparator,
  GateDecision,
  GateOutcome,
  QualityGate,
  RuleOutcome,
  RuleResult,
)
from .learning import (
  Design,
  DesignVariable,
  EvidenceBoundOptimizer,
  Observation,
  ObservationDisposition,
  Proposal,
  record_observation,
)
from .ledger import Ledger, StepVerdict, Unlock, build_ledger, cost_step, rank_unlocks
from .model import Artifact, Protocol, Role, Step, Tier, Verdict, ZeroDecodeOp
from .registry import FEDERATED, FederatedSpec, InstrumentSpec, declared, registry, spec
from .samples import (
  DerivationMode,
  Lineage,
  LineageEdge,
  Material,
  MaterialStatus,
  Measurement,
  SampleTracker,
)
from .version import __version__
from .workcell import InstrumentConfig, Workcell

__all__ = [
  "AcceptanceRule",
  "Artifact",
  "Comparator",
  "Design",
  "DesignVariable",
  "DerivationMode",
  "EvidenceBoundOptimizer",
  "EvidenceEvent",
  "EvidenceLedger",
  "EvidenceLevel",
  "Executor",
  "FEDERATED",
  "FederatedSpec",
  "GENESIS_HASH",
  "GateDecision",
  "GateOutcome",
  "Handoff",
  "InstrumentConfig",
  "InstrumentSpec",
  "Ledger",
  "Lineage",
  "LineageEdge",
  "Material",
  "MaterialStatus",
  "Measurement",
  "Observation",
  "ObservationDisposition",
  "Proposal",
  "Protocol",
  "QualityGate",
  "Role",
  "RuleOutcome",
  "RuleResult",
  "RunReport",
  "SampleTracker",
  "Step",
  "StepResult",
  "StepVerdict",
  "Tier",
  "Unlock",
  "Verdict",
  "Workcell",
  "ZeroDecodeOp",
  "build_ledger",
  "canonical_json",
  "cost_step",
  "declared",
  "digest",
  "file_digest",
  "rank_unlocks",
  "record_observation",
  "registry",
  "spec",
  "EventKind",
  "VerificationReport",
  "__version__",
]
