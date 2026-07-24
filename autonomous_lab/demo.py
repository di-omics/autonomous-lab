"""A device-free, honest demonstration of the evidence and learning kernel."""

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
  run_id: str = "demo_process_learning",
  actor: str = "learning-demo",
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
      "protocol": "bounded_process_design_loop",
      "mode": "device_free_simulation",
      "actuation_allowed": False,
      "claim": "modeled demonstration; no physical measurement",
    },
  )
  tracker = SampleTracker(ledger, run_id, actor)
  tracker.register(
    material_id="input_001",
    sample_id="sample_001",
    material_type="process_input",
    quantity=1.0,
    unit="relative_amount",
    container_id="input_container_001",
    location="simulated_workcell",
    evidence_level=EvidenceLevel.SIMULATED,
  )

  quality_floor = 0.60
  variation_ceiling = 0.20
  gate = QualityGate(
    gate_id="process_training_eligibility_v1",
    description=(
      "Only mechanically clean outputs that meet the declared quality criteria "
      "may train the process optimizer."
    ),
    rules=(
      AcceptanceRule(
        rule_id="minimum_output_quality",
        metric="output_quality_score",
        comparator=Comparator.AT_LEAST,
        lower=quality_floor,
        unit="score",
        required_evidence=EvidenceLevel.SIMULATED,
      ),
      AcceptanceRule(
        rule_id="maximum_process_variation",
        metric="process_variation",
        comparator=Comparator.AT_MOST,
        upper=variation_ceiling,
        unit="fraction",
        required_evidence=EvidenceLevel.SIMULATED,
      ),
    ),
  )

  # The third row is intentionally a mechanical fault. Its objective remains in the
  # ledger for diagnosis, but the failed gate quarantines it from model training.
  rows = (
    ("a", 0.20, 0.30, 0.40, 0.65, 0.75, 0.10),
    ("b", 0.40, 0.50, 0.60, 0.82, 0.85, 0.15),
    ("c", 0.70, 0.20, 0.30, 0.45, 0.70, 0.35),
    ("d", 0.30, 0.60, 0.50, 0.90, 0.92, 0.12),
  )
  observations: List[Observation] = []
  outcomes: List[GateOutcome] = []
  for index, (label, factor_a, factor_b, factor_c, objective, quality, variation) in enumerate(
    rows, 1
  ):
    material_id = f"output_{label}"
    tracker.derive(
      material_id=material_id,
      parent_material_ids=("input_001",),
      parent_contributions={"input_001": 0.20},
      operation="simulated_process_step",
      material_type="process_output",
      quantity=quality,
      unit="relative_amount",
      container_id="output_plate_001",
      position=f"A{index}",
      evidence_level=EvidenceLevel.SIMULATED,
      derivation_mode=DerivationMode.TRANSFORMATION,
      transformation_reason="the simulated process transforms input into output",
      metadata={
        "factor_a": factor_a,
        "factor_b": factor_b,
        "factor_c": factor_c,
      },
    )
    tracker.record_measurement(
      material_id,
      measurement_id=f"quality_{label}",
      metric="output_quality_score",
      value=quality,
      unit="score",
      evidence_level=EvidenceLevel.SIMULATED,
    )
    tracker.record_measurement(
      material_id,
      measurement_id=f"variation_{label}",
      metric="process_variation",
      value=variation,
      unit="fraction",
      evidence_level=EvidenceLevel.SIMULATED,
    )
    quality_constraint = tracker.record_measurement(
      material_id,
      measurement_id=f"constraint_quality_{label}",
      metric="constraint_minimum_output_quality",
      value=1.0 if quality >= quality_floor else 0.0,
      unit="boolean",
      evidence_level=EvidenceLevel.SIMULATED,
      metadata={
        "constraint_id": "minimum_output_quality",
        "constraint_satisfied": quality >= quality_floor,
      },
    )
    variation_constraint = tracker.record_measurement(
      material_id,
      measurement_id=f"constraint_variation_{label}",
      metric="constraint_maximum_process_variation",
      value=1.0 if variation <= variation_ceiling else 0.0,
      unit="boolean",
      evidence_level=EvidenceLevel.SIMULATED,
      metadata={
        "constraint_id": "maximum_process_variation",
        "constraint_satisfied": variation <= variation_ceiling,
      },
    )
    objective_measurement = tracker.record_measurement(
      material_id,
      measurement_id=f"score_{label}",
      metric="process_score",
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
        "factor_a": factor_a,
        "factor_b": factor_b,
        "factor_c": factor_c,
      },
    )
    observations.append(
      record_observation(
        ledger,
        run_id=run_id,
        actor=actor,
        observation_id=f"observation_{label}",
        design=design,
        objective_name="process_score",
        objective=objective,
        feasible=decision.allowed,
        source_event_ids=(
          objective_measurement.event_id,
          quality_constraint.event_id,
          variation_constraint.event_id,
          decision.event_id,
        ),
        constraint_event_ids=(
          quality_constraint.event_id,
          variation_constraint.event_id,
        ),
        feasibility_rationale=(
          "declared quality and process-variation constraints passed"
          if decision.allowed
          else "one or more declared quality or process-variation constraints failed"
        ),
        disposition=disposition,
        exclusion_reason=(
          "" if decision.allowed else f"QC {decision.outcome.value}: {decision.reason}"
        ),
      )
    )

  optimizer = EvidenceBoundOptimizer(
    variables=(
      DesignVariable("factor_a", 0.0, 1.0, "fraction"),
      DesignVariable("factor_b", 0.0, 1.0, "fraction"),
      DesignVariable("factor_c", 0.0, 1.0, "fraction"),
    ),
    objective_name="process_score",
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
