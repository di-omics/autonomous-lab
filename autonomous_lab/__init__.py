"""An autonomous lab layer: what can run, whether it should, what happened, and what next.

di-omics/plr-reverse-engineer brings instruments under control one at a time. This package
asks the questions that only make sense across all of them at once, and it is built in
four layers that each refuse to overstate what the one below them supports.

  Capability -- can this step run at all? The autonomy ledger costs every step of a real
  protocol against the resolved ProtocolMap and the validated run cards, so a step is
  automated only when its command is genuinely decoded.

      from autonomous_lab import Workcell, build_ledger, protocols
      ledger = build_ledger(protocols.get("single_cell_genomics"))
      ledger.headless_prefix()  # how far an unattended run actually gets

  Acceptance -- should it run, given the numbers that came back? Criteria that cannot be
  written without a source, evidence tiers that are earned rather than declared, and an
  UNMEASURABLE verdict for the case a gate in front of a broken instrument must not answer.

      from autonomous_lab import criteria
      criteria.get("loading_window").evaluate(measurements, workcell)

  Provenance -- what is this material, and what does a bad result implicate? Sample lineage
  that tracks where per-sample attribution is lost, and an append-only hash-chained record
  of every proposal and decision.

  Control -- what should we try next? Bayesian reliability from the runs that happened, and
  a supervisory controller that proposes setpoints and cannot move an acceptance threshold.

`permission.Session` wires all four together: propose an action, get a deterministic
decision, and get an auditable record and a list of work orders out the other side.

The answers are currently bleak, and that is the feature. Nothing here can flatter the
lab: the reference protocols include the cartridge seating and flow-cell loading a demo
would quietly omit. Reference gates remain unmeasurable when their producing path has not
returned data, and an unset operator-profile threshold cannot authorize hardware.
"""

from .acceptance import (
  ConformalBand,
  Criterion,
  EvidenceTier,
  Gate,
  GateResult,
  Judgement,
  Measurement,
  Origin,
  UnsourcedCriterion,
  earned_tier,
  promote,
  triage,
)
from .control import (
  Bound,
  Controller,
  KernelSurrogate,
  Observation,
  Proposal,
  Refusal,
  Reliability,
  ReliabilityModel,
  WasteRank,
)
from .criteria import ProfileValue, build_reference_gates, load_profile, profile_keys
from .executor import Executor, Handoff, RunReport, StepResult, gap_closer
from .ledger import Ledger, StepVerdict, Unlock, build_ledger, cost_step, rank_unlocks
from .model import Artifact, Protocol, Role, Step, Tier, Verdict, ZeroDecodeOp
from .permission import Decision, Grant, Request, Session, decide
from .record import ChainCheck, Entry, RunRecord
from .registry import FEDERATED, FederatedSpec, InstrumentSpec, declared, registry, spec
from .samples import Attribution, Event, EventKind, Lineage, Sample, Witness, wells
from .workcell import InstrumentConfig, Workcell

__all__ = [
  "Artifact",
  "Attribution",
  "Bound",
  "ChainCheck",
  "ConformalBand",
  "Controller",
  "Criterion",
  "Decision",
  "Entry",
  "Event",
  "EventKind",
  "EvidenceTier",
  "Executor",
  "FEDERATED",
  "FederatedSpec",
  "Gate",
  "GateResult",
  "Grant",
  "Handoff",
  "InstrumentConfig",
  "InstrumentSpec",
  "Judgement",
  "KernelSurrogate",
  "Ledger",
  "Lineage",
  "Measurement",
  "Observation",
  "Origin",
  "Proposal",
  "ProfileValue",
  "Protocol",
  "Refusal",
  "Reliability",
  "ReliabilityModel",
  "Request",
  "Role",
  "RunRecord",
  "RunReport",
  "Sample",
  "Session",
  "Step",
  "StepResult",
  "StepVerdict",
  "Tier",
  "Unlock",
  "UnsourcedCriterion",
  "Verdict",
  "WasteRank",
  "Witness",
  "Workcell",
  "ZeroDecodeOp",
  "build_ledger",
  "build_reference_gates",
  "cost_step",
  "decide",
  "declared",
  "earned_tier",
  "gap_closer",
  "load_profile",
  "profile_keys",
  "promote",
  "rank_unlocks",
  "registry",
  "spec",
  "triage",
  "wells",
]
