"""A device-free, honest closed-loop demonstration of the Clair kernel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from .evidence import EventKind, EvidenceLedger, EvidenceLevel
from .gates import AcceptanceRule, Comparator, GateOutcome, QualityGate
from .learning import (
  Design,
  DesignVariable,
  EvidenceBoundOptimizer,
  Observation,
  ObservationDisposition,
  Proposal,
  record_observation,
)
from .samples import DerivationMode, SampleTracker


@dataclass(frozen=True)
class DemoSummary:
  run_id: str
  event_count: int
  material_count: int
  qualified_observations: int
  quarantined_observations: int
  gate_outcomes: Tuple[GateOutcome, ...]
  proposal: Proposal
  evidence_head: str


def run_demo(
  ledger: EvidenceLedger,
  *,
  run_id: str = "demo_low_input_genomics",
  actor: str = "clair-demo",
) -> DemoSummary:
  """Run a deterministic simulated DBTL loop.

  All values are explicitly tagged ``simulated_execution``. The demo exercises sample
  lineage, QC quarantine, training-data qualification, and a bounded next-design
  proposal. It sends no command to any instrument and requires a fresh ledger so a
  repeated showcase cannot leave a partial run after deterministic ID collisions.
  """
  if ledger.events:
    raise ValueError(
      "the deterministic demo requires an empty evidence ledger; "
      "choose a new --evidence path"
    )
  ledger.append(
    run_id=run_id,
    kind=EventKind.RUN_STARTED,
    actor=actor,
    evidence_level=EvidenceLevel.SIMULATED,
    payload={
      "protocol": "low_input_genomics_design_loop",
      "mode": "device_free_simulation",
      "actuation_allowed": False,
      "claim": "modeled demonstration; no physical measurement",
    },
  )
  tracker = SampleTracker(ledger, run_id, actor)
  tracker.register(
    material_id="source_001",
    sample_id="donor_001",
    material_type="input_dna",
    quantity=60.0,
    unit="ng",
    container_id="source_tube_001",
    location="simulated_bench",
    evidence_level=EvidenceLevel.SIMULATED,
  )

  gate = QualityGate(
    gate_id="library_training_eligibility_v1",
    description=(
      "Only mechanically clean, sufficiently yielding libraries may train the "
      "process optimizer."
    ),
    rules=(
      AcceptanceRule(
        rule_id="minimum_yield",
        metric="library_yield_ng",
        comparator=Comparator.AT_LEAST,
        lower=8.0,
        unit="ng",
        required_evidence=EvidenceLevel.SIMULATED,
      ),
      AcceptanceRule(
        rule_id="maximum_transfer_cv",
        metric="transfer_cv_pct",
        comparator=Comparator.AT_MOST,
        upper=15.0,
        unit="pct",
        required_evidence=EvidenceLevel.SIMULATED,
      ),
    ),
  )

  # The third row is intentionally a mechanical fault. Its objective remains in the
  # ledger for diagnosis, but the failed gate quarantines it from model training.
  rows = (
    ("a", 6.0, 10.0, 0.50, 1.10, 12.0, 8.0),
    ("b", 8.0, 15.0, 0.70, 0.92, 14.0, 10.0),
    ("c", 10.0, 6.0, 0.30, 0.58, 9.0, 24.0),
    ("d", 7.0, 12.0, 0.55, 1.21, 13.0, 7.5),
  )
  observations: List[Observation] = []
  outcomes: List[GateOutcome] = []
  for index, (label, cycles, input_ng, reagent, objective, yield_ng, cv) in enumerate(
    rows, 1
  ):
    material_id = f"library_{label}"
    tracker.derive(
      material_id=material_id,
      parent_material_ids=("source_001",),
      parent_contributions={"source_001": input_ng},
      operation="simulated_library_prep",
      material_type="sequencing_library",
      quantity=yield_ng,
      unit="ng",
      container_id="library_plate_001",
      position=f"A{index}",
      evidence_level=EvidenceLevel.SIMULATED,
      derivation_mode=DerivationMode.TRANSFORMATION,
      transformation_reason="simulated PCR amplification changes recovered mass",
      metadata={
        "pcr_cycles": cycles,
        "input_ng": input_ng,
        "reagent_fraction": reagent,
      },
    )
    tracker.record_measurement(
      material_id,
      measurement_id=f"yield_{label}",
      metric="library_yield_ng",
      value=yield_ng,
      unit="ng",
      evidence_level=EvidenceLevel.SIMULATED,
    )
    tracker.record_measurement(
      material_id,
      measurement_id=f"cv_{label}",
      metric="transfer_cv_pct",
      value=cv,
      unit="pct",
      evidence_level=EvidenceLevel.SIMULATED,
    )
    yield_constraint = tracker.record_measurement(
      material_id,
      measurement_id=f"constraint_yield_{label}",
      metric="constraint_minimum_yield",
      value=1.0 if yield_ng >= 8.0 else 0.0,
      unit="boolean",
      evidence_level=EvidenceLevel.SIMULATED,
      metadata={
        "constraint_id": "minimum_yield",
        "constraint_satisfied": yield_ng >= 8.0,
      },
    )
    cv_constraint = tracker.record_measurement(
      material_id,
      measurement_id=f"constraint_cv_{label}",
      metric="constraint_maximum_transfer_cv",
      value=1.0 if cv <= 15.0 else 0.0,
      unit="boolean",
      evidence_level=EvidenceLevel.SIMULATED,
      metadata={
        "constraint_id": "maximum_transfer_cv",
        "constraint_satisfied": cv <= 15.0,
      },
    )
    objective_measurement = tracker.record_measurement(
      material_id,
      measurement_id=f"urpd_{label}",
      metric="unique_reads_per_dollar",
      value=objective,
      unit="relative",
      evidence_level=EvidenceLevel.SIMULATED,
    )
    decision = gate.evaluate(tracker, material_id)
    outcomes.append(decision.outcome)
    disposition = (
      ObservationDisposition.QUALIFIED
      if decision.allowed
      else ObservationDisposition.QUARANTINED
    )
    design = Design(
      design_id=f"observed_{label}",
      values={
        "pcr_cycles": cycles,
        "input_ng": input_ng,
        "reagent_fraction": reagent,
      },
    )
    observations.append(
      record_observation(
        ledger,
        run_id=run_id,
        actor=actor,
        observation_id=f"observation_{label}",
        design=design,
        objective_name="unique_reads_per_dollar",
        objective=objective,
        feasible=decision.allowed,
        source_event_ids=(
          objective_measurement.event_id,
          yield_constraint.event_id,
          cv_constraint.event_id,
          decision.event_id,
        ),
        constraint_event_ids=(
          yield_constraint.event_id,
          cv_constraint.event_id,
        ),
        feasibility_rationale=(
          "declared yield and transfer-variation constraints passed"
          if decision.allowed
          else "one or more declared yield or transfer-variation constraints failed"
        ),
        disposition=disposition,
        exclusion_reason=(
          "" if decision.allowed else f"QC {decision.outcome.value}: {decision.reason}"
        ),
      )
    )

  optimizer = EvidenceBoundOptimizer(
    variables=(
      DesignVariable("pcr_cycles", 4.0, 12.0, "cycles"),
      DesignVariable("input_ng", 5.0, 20.0, "ng"),
      DesignVariable("reagent_fraction", 0.25, 1.0, "fraction"),
    ),
    objective_name="unique_reads_per_dollar",
    minimum_evidence=EvidenceLevel.SIMULATED,
    minimum_feasibility=0.65,
  )
  proposal = optimizer.propose(
    ledger,
    observations,
    run_id=run_id,
    actor=actor,
  )[0]
  ledger.append(
    run_id=run_id,
    kind=EventKind.RUN_COMPLETED,
    actor=actor,
    evidence_level=EvidenceLevel.SIMULATED,
    payload={
      "mode": "device_free_simulation",
      "qualified_observations": sum(
        observation.training_eligible for observation in observations
      ),
      "quarantined_observations": sum(
        not observation.training_eligible for observation in observations
      ),
      "proposal_id": proposal.proposal_id,
      "proposal_execution_allowed": proposal.execution_allowed,
    },
  )
  run_events = ledger.by_run(run_id)
  return DemoSummary(
    run_id=run_id,
    event_count=len(run_events),
    material_count=len(tracker.materials()),
    qualified_observations=sum(
      observation.training_eligible for observation in observations
    ),
    quarantined_observations=sum(
      not observation.training_eligible for observation in observations
    ),
    gate_outcomes=tuple(outcomes),
    proposal=proposal,
    evidence_head=ledger.head_hash,
  )
