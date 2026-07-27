"""Synthetic closed-loop demo joining QC, vision, telemetry, and provenance.

The fixture makes the decision path executable in CI without laundering it into a
hardware claim. It demonstrates how a proposal is accepted, recovered, or stopped; all
observations are explicitly marked synthetic in their evidence references.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from .intelligence import (
  Comparator,
  DecisionAction,
  DecisionEngine,
  EvidenceGate,
  EvidenceKind,
  ExpertPolicy,
  Observation,
  PermissionDecision,
  render_decision,
)
from .provenance import RunLedger, SampleTracker


SCENARIOS = ("pass", "qc_fail", "vision_error", "missing_evidence")


def library_commit_policy() -> ExpertPolicy:
  """Example expert policy for committing a quantified library to sequencing."""
  return ExpertPolicy(
    name="library_commit",
    version="1.0.0-demo",
    owner="example assay owner",
    note="Synthetic acceptance ranges; replace with a lab-approved policy before use.",
    gates=(
      EvidenceGate(
        "library_concentration",
        "library_concentration_ng_ul",
        Comparator.RANGE,
        (EvidenceKind.ASSAY_QC,),
        DecisionAction.RECOVER,
        "re-read blank and standards; if still out of range, return to cleanup and do not pool",
        subject="library-plate-001",
        minimum=2.0,
        maximum=10.0,
        rationale="concentration is non-visible assay state; only quantitative QC establishes it",
      ),
      EvidenceGate(
        "deck_pose",
        "labware_offset_mm",
        Comparator.MAXIMUM,
        (EvidenceKind.VISION,),
        DecisionAction.RECOVER,
        "re-home the mover, reacquire the fiducial image, and re-estimate plate pose",
        subject="library-plate-001",
        maximum=1.5,
        rationale="pose error is visible state used to prevent a bad robotic pickup",
      ),
      EvidenceGate(
        "seal_present",
        "seal_present",
        Comparator.EQUAL,
        (EvidenceKind.VISION,),
        DecisionAction.STOP,
        "stop and ask an operator to inspect or reseal the plate before any thermal step",
        subject="library-plate-001",
        expected=True,
      ),
      EvidenceGate(
        "sequencer_ready",
        "instrument_ready",
        Comparator.EQUAL,
        (EvidenceKind.TELEMETRY,),
        DecisionAction.RETRY,
        "wait for the control plane to become ready; escalate after the bounded retry budget",
        subject="sequencer-01",
        expected=True,
        rationale="a camera cannot establish control-plane readiness or interlock state",
      ),
    ),
  )


def _observations(scenario: str) -> Tuple[Observation, ...]:
  if scenario not in SCENARIOS:
    raise KeyError(f"unknown demo scenario {scenario!r}; known: {list(SCENARIOS)}")
  values: Dict[str, object] = {
    "library_concentration_ng_ul": 5.4,
    "labware_offset_mm": 0.6,
    "seal_present": True,
    "instrument_ready": True,
  }
  if scenario == "qc_fail":
    values["library_concentration_ng_ul"] = 0.7
  if scenario == "vision_error":
    values["labware_offset_mm"] = 3.2

  rows = (
    Observation(
      "library_concentration_ng_ul",
      values["library_concentration_ng_ul"],
      EvidenceKind.ASSAY_QC,
      "library-plate-001",
      "synthetic plate reader",
      "2026-01-01T00:00:01Z",
      "synthetic://plate-reader/run-001",
    ),
    Observation(
      "labware_offset_mm",
      values["labware_offset_mm"],
      EvidenceKind.VISION,
      "library-plate-001",
      "synthetic overhead camera",
      "2026-01-01T00:00:02Z",
      "synthetic://vision/frame-042",
    ),
    Observation(
      "seal_present",
      values["seal_present"],
      EvidenceKind.VISION,
      "library-plate-001",
      "synthetic overhead camera",
      "2026-01-01T00:00:02Z",
      "synthetic://vision/frame-042",
    ),
    Observation(
      "instrument_ready",
      values["instrument_ready"],
      EvidenceKind.TELEMETRY,
      "sequencer-01",
      "synthetic sequencer API",
      "2026-01-01T00:00:03Z",
      "synthetic://telemetry/status-004",
    ),
  )
  if scenario == "missing_evidence":
    return rows[:-1]
  return rows


@dataclass(frozen=True)
class ClosedLoopDemo:
  scenario: str
  decision: PermissionDecision
  ledger: RunLedger
  final_location: str

  def render(self) -> str:
    ok, chain = self.ledger.verify()
    lines = [
      "SYNTHETIC CLOSED-LOOP DEMO - NO HARDWARE CLAIM",
      f"scenario: {self.scenario}",
      "",
      render_decision(self.decision),
      "",
      f"sample location: {self.final_location}",
      f"audit chain: {'VALID' if ok else 'INVALID'} - {chain}",
      f"chain head: {self.ledger.events[-1].event_hash}",
    ]
    return "\n".join(lines)


def run_closed_loop_demo(scenario: str = "pass") -> ClosedLoopDemo:
  ledger = RunLedger(f"synthetic-{scenario}")
  tracker = SampleTracker(ledger)
  tracker.register(
    "library-plate-001",
    "plate_reader",
    {"evidence": "synthetic fixture, not a physical sample"},
    "2026-01-01T00:00:00Z",
  )
  observations = _observations(scenario)
  for observation in observations:
    ledger.append(
      "observation",
      observation.subject,
      "record",
      {
        "metric": observation.metric,
        "value": observation.value,
        "kind": observation.kind.value,
        "source": observation.source,
        "evidence_ref": observation.evidence_ref,
      },
      observation.captured_at,
    )

  decision = DecisionEngine().evaluate(
    "commit library plate to sequencing",
    library_commit_policy(),
    observations,
  )
  ledger.append(
    "decision",
    "library-plate-001",
    decision.action.value,
    {
      "proposal": decision.proposal,
      "policy": f"{decision.policy_name}@{decision.policy_version}",
      "permitted": decision.permitted,
      "gates": [
        {
          "gate_id": result.gate.gate_id,
          "status": result.status.value,
          "action": result.action.value,
          "reason": result.reason,
        }
        for result in decision.results
      ],
      "recoveries": list(decision.recoveries),
    },
    "2026-01-01T00:00:04Z",
  )
  if decision.permitted:
    tracker.move("library-plate-001", "sequencer_staging", "2026-01-01T00:00:05Z")
  ledger.assert_valid()
  return ClosedLoopDemo(
    scenario,
    decision,
    ledger,
    tracker.samples["library-plate-001"].location,
  )
