"""Evidence-bound, advisory process optimization.

This is intentionally not a hardware controller. It turns QC-qualified observations
into bounded experiment proposals with explicit uncertainty and feasibility estimates.
Every proposal is recorded with ``execution_allowed=False``. A separate deterministic
plan, physical readiness check, and human/permission boundary must decide whether it
ever becomes a run.

The built-in surrogate is deliberately small and inspectable: a deterministic Halton
candidate set plus distance-weighted local estimates. It is useful for device-free
pilots and as a stable interface for a future pinned GP/BO implementation. It does not
claim calibrated uncertainty.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .evidence import (
  EventKind,
  EvidenceEvent,
  EvidenceLedger,
  EvidenceLevel,
  digest,
  file_digest,
)
from .samples import MaterialStatus, SampleTracker
from .version import __version__


class ObservationDisposition(str, Enum):
  QUALIFIED = "qualified"
  QUARANTINED = "quarantined"


_UNAVAILABLE_QUALIFICATION_STATUSES = frozenset(
  (
    MaterialStatus.QUARANTINED,
    MaterialStatus.CONSUMED,
    MaterialStatus.DISPOSED,
  )
)


def _finite_real(value: object, field: str) -> float:
  if (
    isinstance(value, bool)
    or not isinstance(value, (int, float))
    or not math.isfinite(float(value))
  ):
    raise ValueError(f"{field} must be a finite number")
  return float(value)


@dataclass(frozen=True)
class DesignVariable:
  name: str
  lower: float
  upper: float
  unit: str = ""

  def __post_init__(self) -> None:
    if not isinstance(self.name, str) or not self.name.strip():
      raise ValueError("design variable name must not be empty")
    if not isinstance(self.unit, str):
      raise TypeError(f"design variable '{self.name}' unit must be a string")
    lower = _finite_real(self.lower, f"design variable '{self.name}' lower bound")
    upper = _finite_real(self.upper, f"design variable '{self.name}' upper bound")
    if lower >= upper:
      raise ValueError(f"design variable '{self.name}' lower bound must be < upper")

  def normalise(self, value: float) -> float:
    return (value - self.lower) / (self.upper - self.lower)

  def denormalise(self, value: float) -> float:
    return self.lower + value * (self.upper - self.lower)

  def as_policy(self) -> Dict[str, object]:
    return {
      "name": self.name,
      "lower": self.lower,
      "upper": self.upper,
      "unit": self.unit,
    }


@dataclass(frozen=True)
class Design:
  design_id: str
  values: Mapping[str, float]

  def __post_init__(self) -> None:
    if not isinstance(self.design_id, str) or not self.design_id.strip():
      raise ValueError("design_id must not be empty")
    if not isinstance(self.values, Mapping):
      raise TypeError("design values must be a mapping")
    normalized: Dict[str, float] = {}
    for name, value in self.values.items():
      if not isinstance(name, str) or not name.strip():
        raise ValueError("design variable names must be non-empty strings")
      normalized[name] = _finite_real(
        value, f"design '{self.design_id}' variable '{name}'"
      )
    object.__setattr__(self, "values", MappingProxyType(normalized))


@dataclass(frozen=True)
class Observation:
  observation_id: str
  design: Design
  objective: float
  feasible: bool
  evidence_event_id: str
  evidence_level: EvidenceLevel
  disposition: ObservationDisposition = ObservationDisposition.QUALIFIED
  exclusion_reason: str = ""

  @property
  def training_eligible(self) -> bool:
    return self.disposition is ObservationDisposition.QUALIFIED


@dataclass(frozen=True)
class Proposal:
  proposal_id: str
  design: Design
  predicted_objective: float
  uncertainty: float
  feasibility_probability: float
  acquisition_score: float
  policy_digest: str
  dataset_digest: str
  observation_event_ids: Tuple[str, ...]
  event_id: str
  requires_review: bool = True
  execution_allowed: bool = False


@dataclass(frozen=True)
class _GateRulePolicy:
  rule_id: str
  metric: str
  comparator: str
  unit: str
  lower: Optional[float]
  upper: Optional[float]
  required_evidence: EvidenceLevel


def _required_text(
  payload: Mapping[str, object], field: str, context: str
) -> str:
  value = payload.get(field)
  if not isinstance(value, str) or not value.strip():
    raise ValueError(f"{context} needs a non-empty '{field}'")
  return value


def _required_sequence(
  payload: Mapping[str, object], field: str, context: str
) -> Sequence[object]:
  value = payload.get(field)
  if not isinstance(value, (list, tuple)) or not value:
    raise ValueError(f"{context} needs a non-empty '{field}' sequence")
  return value


def _string_id_sequence(value: object, context: str) -> Tuple[str, ...]:
  if not isinstance(value, (list, tuple)) or not value:
    raise ValueError(f"{context} must be a non-empty sequence")
  if any(not isinstance(item, str) or not item.strip() for item in value):
    raise ValueError(f"{context} must contain only non-empty strings")
  out = tuple(value)
  if len(set(out)) != len(out):
    raise ValueError(f"{context} must not contain duplicates")
  return out


def _optional_finite_number(
  value: object, field: str, context: str
) -> Optional[float]:
  if value is None:
    return None
  if (
    isinstance(value, bool)
    or not isinstance(value, (int, float))
    or not math.isfinite(float(value))
  ):
    raise ValueError(f"{context} field '{field}' must be a finite number or null")
  return float(value)


def _parse_rule_policy(value: object, context: str) -> _GateRulePolicy:
  if not isinstance(value, Mapping):
    raise ValueError(f"{context} must be an object")
  expected_fields = {
    "rule_id",
    "metric",
    "comparator",
    "unit",
    "lower",
    "upper",
    "required_evidence",
    "rationale",
  }
  if set(value) != expected_fields:
    missing = sorted(expected_fields - set(value))
    extra = sorted(set(value) - expected_fields)
    raise ValueError(
      f"{context} fields differ from the canonical policy; "
      f"missing={missing}, extra={extra}"
    )
  rule_id = _required_text(value, "rule_id", context)
  metric = _required_text(value, "metric", context)
  unit = _required_text(value, "unit", context)
  comparator = value.get("comparator")
  if comparator not in {"at_least", "at_most", "between"}:
    raise ValueError(f"{context} has invalid comparator {comparator!r}")
  lower = _optional_finite_number(value.get("lower"), "lower", context)
  upper = _optional_finite_number(value.get("upper"), "upper", context)
  if comparator == "at_least" and lower is None:
    raise ValueError(f"{context} at_least comparator needs a lower threshold")
  if comparator == "at_least" and upper is not None:
    raise ValueError(f"{context} at_least comparator must not set upper")
  if comparator == "at_most" and upper is None:
    raise ValueError(f"{context} at_most comparator needs an upper threshold")
  if comparator == "at_most" and lower is not None:
    raise ValueError(f"{context} at_most comparator must not set lower")
  if comparator == "between":
    if lower is None or upper is None:
      raise ValueError(f"{context} between comparator needs both thresholds")
    if lower > upper:
      raise ValueError(f"{context} lower threshold exceeds upper")
  try:
    required_evidence = EvidenceLevel(str(value.get("required_evidence")))
  except ValueError as exc:
    raise ValueError(f"{context} has an invalid required_evidence") from exc
  if not isinstance(value.get("rationale"), str):
    raise ValueError(f"{context} field 'rationale' must be a string")
  return _GateRulePolicy(
    rule_id=rule_id,
    metric=metric,
    comparator=str(comparator),
    unit=unit,
    lower=lower,
    upper=upper,
    required_evidence=required_evidence,
  )


def _recompute_rule_outcome(
  policy: _GateRulePolicy, measurement: Optional[EvidenceEvent]
) -> str:
  if measurement is None:
    return "hold"
  if measurement.payload["unit"] != policy.unit:
    return "error"
  if not measurement.evidence_level.at_least(policy.required_evidence):
    return "hold"
  value = float(measurement.payload["value"])
  if policy.comparator == "at_least":
    assert policy.lower is not None
    passed = value >= policy.lower
  elif policy.comparator == "at_most":
    assert policy.upper is not None
    passed = value <= policy.upper
  else:
    assert policy.lower is not None and policy.upper is not None
    passed = policy.lower <= value <= policy.upper
  return "pass" if passed else "fail"


def _validate_measurement_event(event: EvidenceEvent, context: str) -> str:
  if event.kind is not EventKind.MEASUREMENT_RECORDED:
    raise ValueError(f"{context} is not a measurement_recorded event")
  _required_text(event.payload, "measurement_id", context)
  material_id = _required_text(event.payload, "material_id", context)
  _required_text(event.payload, "metric", context)
  _required_text(event.payload, "unit", context)
  value = event.payload.get("value")
  if (
    isinstance(value, bool)
    or not isinstance(value, (int, float))
    or not math.isfinite(float(value))
  ):
    raise ValueError(f"{context} needs a finite numeric 'value'")
  return material_id


def _material_status_before(
  ledger: EvidenceLedger,
  *,
  run_id: str,
  material_id: str,
  before_sequence: int,
) -> MaterialStatus:
  """Replay material state at an event boundary, never from the latest projection."""
  if before_sequence < 0 or before_sequence > len(ledger.events):
    raise ValueError(f"invalid material-state boundary {before_sequence}")
  prefix = ledger.events[:before_sequence]
  prefix_ledger = EvidenceLedger(events=prefix)
  return SampleTracker(prefix_ledger, run_id).material(material_id).status


def _material_state_events_before(
  ledger: EvidenceLedger,
  *,
  run_id: str,
  material_id: str,
  before_sequence: int,
) -> Tuple[EvidenceEvent, ...]:
  """Resolve creation plus the event establishing status at one event boundary."""
  run_events = [
    event
    for event in ledger.by_run(run_id)
    if event.sequence < before_sequence
  ]
  creation = [
    event
    for event in run_events
    if event.kind in (EventKind.MATERIAL_REGISTERED, EventKind.MATERIAL_DERIVED)
    and event.payload.get("material_id") == material_id
  ]
  if len(creation) != 1:
    raise ValueError(
      f"material '{material_id}' needs exactly one pre-decision creation event"
    )
  status_events = [
    event
    for event in run_events
    if event.kind is EventKind.MATERIAL_STATUS_CHANGED
    and event.payload.get("material_id") == material_id
  ]
  if status_events:
    return creation[0], status_events[-1]
  return (creation[0],)


def _validate_gate_event(
  ledger: EvidenceLedger, event: EvidenceEvent, run_id: str
) -> Tuple[str, bool, Tuple[str, ...]]:
  """Validate the sealed gate shape and all measurement links it claims."""
  context = f"gate event '{event.event_id}'"
  if event.kind is not EventKind.GATE_EVALUATED:
    raise ValueError(f"{context} is not a gate_evaluated event")
  if event.run_id != run_id:
    raise ValueError(
      f"{context} belongs to run '{event.run_id}', not observation run '{run_id}'"
    )
  gate_id = _required_text(event.payload, "gate_id", context)
  material_id = _required_text(event.payload, "material_id", context)
  material_state_event_ids = _string_id_sequence(
    event.payload.get("material_state_event_ids"),
    f"{context} material_state_event_ids",
  )
  material_state_events = _material_state_events_before(
    ledger,
    run_id=run_id,
    material_id=material_id,
    before_sequence=event.sequence,
  )
  expected_state_ids = tuple(
    state_event.event_id for state_event in material_state_events
  )
  if material_state_event_ids != expected_state_ids:
    raise ValueError(
      f"{context} material_state_event_ids do not match replayed lifecycle state"
    )
  policy_digest = _required_text(event.payload, "policy_digest", context)
  policy = event.payload.get("policy")
  if not isinstance(policy, Mapping):
    raise ValueError(f"{context} needs a canonical policy object")
  if set(policy) != {"gate_id", "description", "rules"}:
    raise ValueError(f"{context} policy fields are not canonical")
  if _required_text(policy, "gate_id", f"{context} policy") != gate_id:
    raise ValueError(f"{context} policy gate_id does not match the decision")
  if not isinstance(policy.get("description"), str):
    raise ValueError(f"{context} policy description must be a string")
  if digest(policy) != policy_digest:
    raise ValueError(f"{context} policy digest does not match its canonical policy")
  policy_rules_raw = _required_sequence(policy, "rules", f"{context} policy")
  policy_rules = [
    _parse_rule_policy(value, f"{context} policy rule {index}")
    for index, value in enumerate(policy_rules_raw)
  ]
  policy_rule_ids = [rule.rule_id for rule in policy_rules]
  if len(policy_rule_ids) != len(set(policy_rule_ids)):
    raise ValueError(f"{context} policy has duplicate rule IDs")
  outcome = event.payload.get("outcome")
  valid_outcomes = {"pass", "fail", "hold", "error"}
  if outcome not in valid_outcomes:
    raise ValueError(f"{context} has invalid outcome {outcome!r}")
  allowed = event.payload.get("allowed")
  if not isinstance(allowed, bool):
    raise ValueError(f"{context} needs a boolean 'allowed'")
  if allowed is not (outcome == "pass"):
    raise ValueError(
      f"{context} is inconsistent: allowed must be true exactly when outcome is pass"
    )

  rules = _required_sequence(event.payload, "rules", context)
  if len(rules) != len(policy_rules):
    raise ValueError(f"{context} rule results do not match the policy rule count")
  rule_outcomes: List[str] = []
  used_measurements: List[EvidenceEvent] = []
  for index, (result, rule_policy) in enumerate(zip(rules, policy_rules)):
    rule_context = f"{context} rule {index}"
    if not isinstance(result, Mapping):
      raise ValueError(f"{rule_context} must be an object")
    if _required_text(result, "rule_id", rule_context) != rule_policy.rule_id:
      raise ValueError(f"{rule_context} rule_id does not match the gate policy")
    metric = _required_text(result, "metric", rule_context)
    if metric != rule_policy.metric:
      raise ValueError(f"{rule_context} metric does not match the gate policy")
    rule_outcome = result.get("outcome")
    if rule_outcome not in valid_outcomes:
      raise ValueError(f"{rule_context} has invalid outcome {rule_outcome!r}")
    if not isinstance(result.get("reason"), str):
      raise ValueError(f"{rule_context} reason must be a string")
    measurement_event_id = result.get("measurement_event_id")
    matching_measurements = [
      candidate
      for candidate in ledger.by_run(run_id)
      if candidate.kind is EventKind.MEASUREMENT_RECORDED
      and candidate.sequence < event.sequence
      and candidate.payload.get("material_id") == material_id
      and candidate.payload.get("metric") == rule_policy.metric
    ]
    measurement = matching_measurements[-1] if matching_measurements else None
    if measurement is None:
      duplicated_fields = (
        "measurement_id",
        "measurement_event_id",
        "value",
        "unit",
        "evidence_level",
      )
      if any(result.get(field) is not None for field in duplicated_fields):
        raise ValueError(f"{rule_context} claims measurement data that does not exist")
    else:
      measured_material = _validate_measurement_event(
        measurement, f"measurement event '{measurement.event_id}'"
      )
      if measured_material != material_id:
        raise ValueError(
          f"{rule_context} references material '{measured_material}', "
          f"not '{material_id}'"
        )
      if measurement_event_id != measurement.event_id:
        raise ValueError(
          f"{rule_context} does not reference the latest pre-gate measurement"
        )
      expected = {
        "measurement_id": measurement.payload["measurement_id"],
        "metric": measurement.payload["metric"],
        "value": measurement.payload["value"],
        "unit": measurement.payload["unit"],
        "evidence_level": measurement.evidence_level.value,
      }
      drifted = [
        field
        for field, value in expected.items()
        if digest(result.get(field)) != digest(value)
      ]
      if drifted:
        raise ValueError(
          f"{rule_context} drifted from its measurement: " + ", ".join(drifted)
        )
      used_measurements.append(measurement)
    recomputed_outcome = _recompute_rule_outcome(rule_policy, measurement)
    if rule_outcome != recomputed_outcome:
      raise ValueError(
        f"{rule_context} outcome '{rule_outcome}' disagrees with the sealed "
        f"policy and measurement ('{recomputed_outcome}')"
      )
    rule_outcomes.append(recomputed_outcome)

  if "error" in rule_outcomes:
    derived_outcome = "error"
  elif "fail" in rule_outcomes:
    derived_outcome = "fail"
  elif "hold" in rule_outcomes:
    derived_outcome = "hold"
  else:
    derived_outcome = "pass"
  material_status = _material_status_before(
    ledger,
    run_id=run_id,
    material_id=material_id,
    before_sequence=event.sequence,
  )
  if material_status in _UNAVAILABLE_QUALIFICATION_STATUSES:
    derived_outcome = "hold"
  material_state_level = min(
    (state_event.evidence_level for state_event in material_state_events),
    key=lambda item: item.rank,
  )
  strictest_required = max(
    (rule.required_evidence for rule in policy_rules),
    key=lambda item: item.rank,
  )
  if (
    derived_outcome == "pass"
    and not material_state_level.at_least(strictest_required)
  ):
    derived_outcome = "hold"
  if outcome != derived_outcome:
    raise ValueError(
      f"{context} outcome '{outcome}' disagrees with rule results "
      f"('{derived_outcome}')"
    )
  decision_levels = (
    [measurement.evidence_level for measurement in used_measurements]
    if used_measurements
    else [EvidenceLevel.MODELED]
  )
  decision_levels.extend(
    state_event.evidence_level for state_event in material_state_events
  )
  expected_level = min(decision_levels, key=lambda item: item.rank)
  if event.evidence_level is not expected_level:
    raise ValueError(
      f"{context} evidence level is {event.evidence_level.value}, "
      f"expected {expected_level.value}"
    )
  return material_id, allowed, tuple(rule.metric for rule in policy_rules)


def _validate_observation_sources(
  ledger: EvidenceLedger,
  *,
  run_id: str,
  objective_name: str,
  objective: float,
  feasible: bool,
  disposition: ObservationDisposition,
  source_events: Sequence[EvidenceEvent],
  constraint_event_ids: Sequence[str],
  feasibility_rationale: str,
  before_sequence: int,
) -> str:
  """Return the material after proving measurement, gate, and run linkage."""
  wrong_run = [event.event_id for event in source_events if event.run_id != run_id]
  if wrong_run:
    raise ValueError(
      "observation source events belong to a different run: " + ", ".join(wrong_run)
    )
  unsupported = [
    event.event_id
    for event in source_events
    if event.kind
    not in (EventKind.MEASUREMENT_RECORDED, EventKind.GATE_EVALUATED)
  ]
  if unsupported:
    raise ValueError(
      "observation sources must be measurement_recorded or gate_evaluated events: "
      + ", ".join(unsupported)
    )
  measurements = [
    event
    for event in source_events
    if event.kind is EventKind.MEASUREMENT_RECORDED
  ]
  gates = [
    event for event in source_events if event.kind is EventKind.GATE_EVALUATED
  ]
  if not measurements:
    raise ValueError("an observation needs at least one measurement source")
  if len(gates) != 1:
    raise ValueError("an observation needs exactly one quality-gate source")
  if any(event.sequence >= before_sequence for event in source_events):
    raise ValueError("observation references evidence not recorded before it")
  if not feasibility_rationale.strip():
    raise ValueError("an observation needs a scientific feasibility rationale")
  if not constraint_event_ids:
    raise ValueError("an observation needs explicit scientific constraint evidence")
  if len(set(constraint_event_ids)) != len(constraint_event_ids):
    raise ValueError("constraint_event_ids must not contain duplicates")
  source_by_id = {event.event_id: event for event in source_events}
  missing_constraints = [
    event_id for event_id in constraint_event_ids if event_id not in source_by_id
  ]
  if missing_constraints:
    raise ValueError(
      "scientific constraint evidence is not in source_event_ids: "
      + ", ".join(missing_constraints)
    )
  invalid_constraints = [
    event_id
    for event_id in constraint_event_ids
    if source_by_id[event_id].kind is not EventKind.MEASUREMENT_RECORDED
  ]
  if invalid_constraints:
    raise ValueError(
      "scientific constraint evidence must be measurement_recorded events: "
      + ", ".join(invalid_constraints)
    )
  constraint_ids = set()
  constraint_results: List[bool] = []
  constraint_sources: Dict[str, EvidenceEvent] = {}
  for event_id in constraint_event_ids:
    constraint_event = source_by_id[event_id]
    metadata = constraint_event.payload.get("metadata")
    context = f"scientific constraint event '{event_id}'"
    if not isinstance(metadata, Mapping):
      raise ValueError(f"{context} needs a metadata object")
    constraint_id = _required_text(metadata, "constraint_id", context)
    if constraint_id in constraint_ids:
      raise ValueError(f"duplicate scientific constraint_id '{constraint_id}'")
    constraint_ids.add(constraint_id)
    if constraint_event.payload.get("unit") != "boolean":
      raise ValueError(f"{context} must use unit 'boolean'")
    constraint_value = float(constraint_event.payload["value"])
    if constraint_value not in (0.0, 1.0):
      raise ValueError(f"{context} boolean value must be exactly 0 or 1")
    constraint_satisfied = metadata.get("constraint_satisfied")
    if not isinstance(constraint_satisfied, bool):
      raise ValueError(f"{context} needs boolean 'constraint_satisfied' metadata")
    if constraint_satisfied is not (constraint_value == 1.0):
      raise ValueError(
        f"{context} constraint_satisfied does not match its boolean value"
      )
    constraint_results.append(constraint_satisfied)
    constraint_sources[constraint_id] = constraint_event
  derived_feasible = all(constraint_results)
  if feasible is not derived_feasible:
    raise ValueError(
      f"observation feasible={feasible} disagrees with sealed scientific "
      f"constraint evidence ({derived_feasible})"
    )

  material_ids = {
    _validate_measurement_event(
      event, f"measurement source event '{event.event_id}'"
    )
    for event in measurements
  }
  if len(material_ids) != 1:
    raise ValueError("observation measurement sources refer to different materials")
  material_id = next(iter(material_ids))
  gate_material_id, gate_allowed, gate_metrics = _validate_gate_event(
    ledger, gates[0], run_id
  )
  if gate_material_id != material_id:
    raise ValueError(
      f"observation measurement material '{material_id}' and gate material "
      f"'{gate_material_id}' differ"
    )

  creation_events = [
    event
    for event in ledger.by_run(run_id)
    if event.kind in (EventKind.MATERIAL_REGISTERED, EventKind.MATERIAL_DERIVED)
    and event.payload.get("material_id") == material_id
  ]
  if len(creation_events) != 1:
    raise ValueError(
      f"observation material '{material_id}' needs exactly one creation event "
      f"in run '{run_id}'"
    )
  if any(creation_events[0].sequence >= event.sequence for event in source_events):
    raise ValueError(
      f"observation material '{material_id}' was not created before its evidence"
    )

  objective_sources = [
    event
    for event in measurements
    if event.payload.get("metric") == objective_name
  ]
  if len(objective_sources) != 1:
    raise ValueError(
      f"observation needs exactly one measurement for objective '{objective_name}'"
    )
  measured_objective = float(objective_sources[0].payload["value"])
  if measured_objective != float(objective):
    raise ValueError(
      f"observation objective {objective} does not match sealed measurement "
      f"{measured_objective}"
    )
  pre_observation_measurements = [
    event
    for event in ledger.by_run(run_id)
    if event.kind is EventKind.MEASUREMENT_RECORDED
    and event.sequence < before_sequence
    and event.payload.get("material_id") == material_id
  ]
  latest_objective = [
    event
    for event in pre_observation_measurements
    if event.payload.get("metric") == objective_name
  ][-1]
  if objective_sources[0].event_id != latest_objective.event_id:
    raise ValueError(
      f"objective measurement '{objective_sources[0].event_id}' is stale; "
      f"latest is '{latest_objective.event_id}'"
    )
  stale_gate_metrics = sorted(
    {
      str(event.payload.get("metric"))
      for event in pre_observation_measurements
      if gates[0].sequence < event.sequence
      and event.payload.get("metric") in set(gate_metrics)
    }
  )
  if stale_gate_metrics:
    raise ValueError(
      "quality-gate evidence is stale; re-gate after newer measurements for: "
      + ", ".join(stale_gate_metrics)
    )
  later_status_events = [
    event
    for event in ledger.by_run(run_id)
    if event.kind is EventKind.MATERIAL_STATUS_CHANGED
    and gates[0].sequence < event.sequence < before_sequence
    and event.payload.get("material_id") == material_id
  ]
  if later_status_events:
    raise ValueError(
      "material status changed after the cited quality gate; re-gate before "
      "recording an observation"
    )
  for constraint_id, cited_event in constraint_sources.items():
    matching_attestations = [
      event
      for event in pre_observation_measurements
      if isinstance(event.payload.get("metadata"), Mapping)
      and event.payload["metadata"].get("constraint_id") == constraint_id
    ]
    if not matching_attestations:
      raise ValueError(
        f"scientific constraint '{constraint_id}' has no pre-observation attestation"
      )
    latest_attestation = matching_attestations[-1]
    if latest_attestation.event_id != cited_event.event_id:
      raise ValueError(
        f"scientific constraint event '{cited_event.event_id}' is stale; "
        f"latest for '{constraint_id}' is '{latest_attestation.event_id}'"
      )
  if disposition is ObservationDisposition.QUALIFIED and not gate_allowed:
    raise ValueError("a QUALIFIED observation requires a passing quality gate")
  material_status = _material_status_before(
    ledger,
    run_id=run_id,
    material_id=material_id,
    before_sequence=before_sequence,
  )
  if (
    disposition is ObservationDisposition.QUALIFIED
    and material_status in _UNAVAILABLE_QUALIFICATION_STATUSES
  ):
    raise ValueError(
      f"a QUALIFIED observation requires an available material; "
      f"'{material_id}' was {material_status.value}"
    )
  return material_id


def record_observation(
  ledger: EvidenceLedger,
  *,
  run_id: str,
  actor: str,
  observation_id: str,
  design: Design,
  objective_name: str,
  objective: float,
  feasible: bool,
  source_event_ids: Tuple[str, ...],
  constraint_event_ids: Tuple[str, ...],
  feasibility_rationale: str,
  disposition: ObservationDisposition = ObservationDisposition.QUALIFIED,
  exclusion_reason: str = "",
) -> Observation:
  """Seal one training-row candidate and its source-event lineage."""
  if not observation_id.strip() or not objective_name.strip():
    raise ValueError("observation_id and objective_name must not be empty")
  if not isinstance(feasible, bool):
    raise TypeError("observation feasible must be a boolean")
  if not isinstance(disposition, ObservationDisposition):
    raise TypeError("observation disposition must be an ObservationDisposition")
  if not isinstance(feasibility_rationale, str):
    raise TypeError("feasibility_rationale must be a string")
  source_event_ids = _string_id_sequence(
    source_event_ids, "source_event_ids"
  )
  constraint_event_ids = _string_id_sequence(
    constraint_event_ids, "constraint_event_ids"
  )
  if not math.isfinite(objective):
    raise ValueError("observation objective must be finite")
  if any(
    event.kind is EventKind.OBSERVATION_RECORDED
    and event.payload.get("observation_id") == observation_id
    for event in ledger.events
  ):
    raise ValueError(f"observation_id '{observation_id}' already exists")
  source_events = [ledger.event(event_id) for event_id in source_event_ids]
  material_id = _validate_observation_sources(
    ledger,
    run_id=run_id,
    objective_name=objective_name,
    objective=objective,
    feasible=feasible,
    disposition=disposition,
    source_events=source_events,
    constraint_event_ids=constraint_event_ids,
    feasibility_rationale=feasibility_rationale,
    before_sequence=len(ledger.events),
  )
  level = min((event.evidence_level for event in source_events), key=lambda item: item.rank)
  if disposition is ObservationDisposition.QUARANTINED and not exclusion_reason.strip():
    raise ValueError("a quarantined observation needs an exclusion_reason")
  gate_event_id = next(
    event.event_id
    for event in source_events
    if event.kind is EventKind.GATE_EVALUATED
  )
  payload = {
    "observation_id": observation_id,
    "design_id": design.design_id,
    "values": design.values,
    "objective_name": objective_name,
    "objective": float(objective),
    "feasible": bool(feasible),
    "feasibility_rationale": feasibility_rationale,
    "constraint_event_ids": list(constraint_event_ids),
    "disposition": disposition.value,
    "training_eligible": disposition is ObservationDisposition.QUALIFIED,
    "exclusion_reason": exclusion_reason,
    "source_event_ids": list(source_event_ids),
    "material_id": material_id,
    "gate_event_id": gate_event_id,
  }

  def validate(events) -> None:
    candidate = events[-1]
    current = EvidenceLedger(events=events[:-1])
    if any(
      existing.kind is EventKind.OBSERVATION_RECORDED
      and existing.payload.get("observation_id") == observation_id
      for existing in current.events
    ):
      raise ValueError(f"observation_id '{observation_id}' already exists")
    current_sources = [
      current.event(source_event_id) for source_event_id in source_event_ids
    ]
    current_material_id = _validate_observation_sources(
      current,
      run_id=run_id,
      objective_name=objective_name,
      objective=objective,
      feasible=feasible,
      disposition=disposition,
      source_events=current_sources,
      constraint_event_ids=constraint_event_ids,
      feasibility_rationale=feasibility_rationale,
      before_sequence=candidate.sequence,
    )
    current_level = min(
      (source.evidence_level for source in current_sources),
      key=lambda item: item.rank,
    )
    current_payload = dict(payload)
    current_payload["material_id"] = current_material_id
    if (
      candidate.evidence_level is not current_level
      or digest(candidate.payload) != digest(current_payload)
    ):
      raise ValueError(
        "observation inputs changed before the row could be sealed; "
        "re-evaluate against the current ledger"
      )

  event = ledger.append_transactionally(
    run_id=run_id,
    kind=EventKind.OBSERVATION_RECORDED,
    actor=actor,
    evidence_level=level,
    payload=payload,
    validate=validate,
  )
  return Observation(
    observation_id=observation_id,
    design=design,
    objective=float(objective),
    feasible=bool(feasible),
    evidence_event_id=event.event_id,
    evidence_level=level,
    disposition=disposition,
    exclusion_reason=exclusion_reason,
  )


class EvidenceBoundOptimizer:
  """A deterministic local surrogate that emits inert, replayable proposals."""

  def __init__(
    self,
    *,
    variables: Tuple[DesignVariable, ...],
    objective_name: str,
    maximize: bool = True,
    minimum_evidence: EvidenceLevel = EvidenceLevel.MEASURED,
    minimum_feasibility: float = 0.65,
    exploration: float = 0.35,
    risk_penalty: float = 1.0,
    candidate_count: int = 128,
  ):
    if not isinstance(variables, tuple):
      raise TypeError("optimizer variables must be a tuple")
    if not variables:
      raise ValueError("an optimizer needs at least one design variable")
    if any(not isinstance(variable, DesignVariable) for variable in variables):
      raise TypeError("optimizer variables must contain only DesignVariable values")
    names = [variable.name for variable in variables]
    if len(names) != len(set(names)):
      raise ValueError("design variable names must be unique")
    if not isinstance(objective_name, str) or not objective_name.strip():
      raise ValueError("objective_name must not be empty")
    if not isinstance(maximize, bool):
      raise TypeError("maximize must be a boolean")
    if not isinstance(minimum_evidence, EvidenceLevel):
      raise TypeError("minimum_evidence must be an EvidenceLevel")
    minimum_feasibility = _finite_real(
      minimum_feasibility, "minimum_feasibility"
    )
    exploration = _finite_real(exploration, "exploration")
    risk_penalty = _finite_real(risk_penalty, "risk_penalty")
    if not 0.0 <= minimum_feasibility <= 1.0:
      raise ValueError("minimum_feasibility must be between 0 and 1")
    if exploration < 0 or risk_penalty < 0:
      raise ValueError("exploration and risk_penalty must be >= 0")
    if isinstance(candidate_count, bool) or not isinstance(candidate_count, int):
      raise TypeError("candidate_count must be an integer")
    if candidate_count < 8:
      raise ValueError("candidate_count must be at least 8")
    self.variables = variables
    self.objective_name = objective_name
    self.maximize = maximize
    self.minimum_evidence = minimum_evidence
    self.minimum_feasibility = minimum_feasibility
    self.exploration = exploration
    self.risk_penalty = risk_penalty
    self.candidate_count = candidate_count

  @property
  def policy(self) -> Dict[str, object]:
    """Canonical implementation and settings sealed into each proposal."""
    return {
      "algorithm": {
        "id": "deterministic_distance_weighted",
        "version": 1,
      },
      "implementation": {
        "package": "autonomous-lab",
        "package_version": __version__,
        "source_sha256": file_digest(__file__),
      },
      "variables": [variable.as_policy() for variable in self.variables],
      "objective": {
        "name": self.objective_name,
        "direction": "maximize" if self.maximize else "minimize",
      },
      "evidence": {
        "minimum_level": self.minimum_evidence.value,
      },
      "acquisition": {
        "minimum_feasibility": self.minimum_feasibility,
        "exploration": self.exploration,
        "risk_penalty": self.risk_penalty,
      },
      "candidate_generation": {
        "id": "halton",
        "version": 1,
        "candidate_count": self.candidate_count,
      },
    }

  @property
  def policy_digest(self) -> str:
    return digest(self.policy)

  def propose(
    self,
    ledger: EvidenceLedger,
    observations: Sequence[Observation],
    *,
    run_id: str,
    actor: str,
    count: int = 1,
  ) -> Tuple[Proposal, ...]:
    """Return the best bounded candidates and record why they were proposed."""
    if isinstance(count, bool) or not isinstance(count, int):
      raise TypeError("proposal count must be an integer")
    if count < 1:
      raise ValueError("proposal count must be >= 1")
    policy = self.policy
    policy_digest = digest(policy)
    eligible = self._eligible(ledger, observations)
    dataset_value = [
      {
        "observation_id": observation.observation_id,
        "event_id": observation.evidence_event_id,
        "design_id": observation.design.design_id,
        "values": observation.design.values,
        "objective": observation.objective,
        "feasible": observation.feasible,
      }
      for observation in eligible
    ]
    dataset_digest = digest(dataset_value)
    candidates = self._candidates(eligible)
    if count > len(candidates):
      raise ValueError(
        f"requested {count} proposals, but only {len(candidates)} candidates remain"
      )
    scored = [
      self._score(values, eligible)
      for values in candidates
    ]
    scored.sort(key=lambda item: (-item[4], digest(item[0])))
    prior_design_ids = {
      str(event.payload.get("design_id"))
      for event in ledger.events
      if event.kind is EventKind.DESIGN_PROPOSED
    }
    prior_proposal_ids = {
      str(event.payload.get("proposal_id"))
      for event in ledger.events
      if event.kind is EventKind.DESIGN_PROPOSED
    }
    proposals: List[Proposal] = []
    emitted_design_ids = set()
    emitted_proposal_ids = set()
    source_ids = tuple(observation.evidence_event_id for observation in eligible)
    evaluated_head = ledger.head_hash
    for values, predicted, uncertainty, feasibility, score in scored[:count]:
      design_id = "design_" + digest(values)[:16]
      proposal_id = "proposal_" + digest(
        {
          "design": values,
          "policy_digest": policy_digest,
          "dataset_digest": dataset_digest,
        }
      )[:16]
      if design_id in emitted_design_ids or proposal_id in emitted_proposal_ids:
        raise RuntimeError("candidate deduplication produced a duplicate proposal")
      if design_id in prior_design_ids:
        raise ValueError(f"design_id '{design_id}' already exists")
      if proposal_id in prior_proposal_ids:
        raise ValueError(f"proposal_id '{proposal_id}' already exists")
      emitted_design_ids.add(design_id)
      emitted_proposal_ids.add(proposal_id)
      review = feasibility < self.minimum_feasibility or len(eligible) < 3
      payload = {
        "proposal_id": proposal_id,
        "design_id": design_id,
        "values": values,
        "objective_name": self.objective_name,
        "predicted_objective": predicted,
        "uncertainty": uncertainty,
        "uncertainty_calibrated": False,
        "feasibility_probability": feasibility,
        "feasibility_calibrated": False,
        "acquisition_score": score,
        "requires_review": review,
        "execution_allowed": False,
        "policy": policy,
        "policy_digest": policy_digest,
        "dataset_digest": dataset_digest,
        "observation_event_ids": list(source_ids),
      }

      def validate(events) -> None:
        candidate = events[-1]
        current = EvidenceLedger(events=events[:-1])
        if current.head_hash != evaluated_head:
          raise ValueError(
            "evidence ledger changed while the proposal was being computed; "
            "recompute from a fresh snapshot"
          )
        for existing in current.events:
          if existing.kind is not EventKind.DESIGN_PROPOSED:
            continue
          if existing.payload.get("design_id") == design_id:
            raise ValueError(f"design_id '{design_id}' already exists")
          if existing.payload.get("proposal_id") == proposal_id:
            raise ValueError(f"proposal_id '{proposal_id}' already exists")
        if (
          candidate.evidence_level is not EvidenceLevel.MODELED
          or digest(candidate.payload) != digest(payload)
          or digest(candidate.payload.get("policy"))
          != candidate.payload.get("policy_digest")
        ):
          raise ValueError("sealed proposal differs from its evaluated candidate")

      event = ledger.append_transactionally(
        run_id=run_id,
        kind=EventKind.DESIGN_PROPOSED,
        actor=actor,
        evidence_level=EvidenceLevel.MODELED,
        payload=payload,
        validate=validate,
      )
      evaluated_head = event.event_hash
      proposals.append(
        Proposal(
          proposal_id=proposal_id,
          design=Design(design_id=design_id, values=values),
          predicted_objective=predicted,
          uncertainty=uncertainty,
          feasibility_probability=feasibility,
          acquisition_score=score,
          policy_digest=policy_digest,
          dataset_digest=dataset_digest,
          observation_event_ids=source_ids,
          event_id=event.event_id,
          requires_review=review,
          execution_allowed=False,
        )
      )
    return tuple(proposals)

  def _eligible(
    self, ledger: EvidenceLedger, observations: Sequence[Observation]
  ) -> List[Observation]:
    eligible: List[Observation] = []
    ids = set()
    for observation in observations:
      if observation.observation_id in ids:
        raise ValueError(f"duplicate observation_id '{observation.observation_id}'")
      ids.add(observation.observation_id)
      self._validate_design(observation.design)
      if not math.isfinite(observation.objective):
        raise ValueError(
          f"observation '{observation.observation_id}' has a non-finite objective"
        )
      event = ledger.event(observation.evidence_event_id)
      if event.kind is not EventKind.OBSERVATION_RECORDED:
        raise ValueError(
          f"observation '{observation.observation_id}' does not point to an "
          "observation_recorded event"
        )
      if str(event.payload.get("observation_id")) != observation.observation_id:
        raise ValueError(
          f"observation '{observation.observation_id}' does not match its evidence event"
        )
      if event.evidence_level is not observation.evidence_level:
        raise ValueError(
          f"observation '{observation.observation_id}' evidence level drifted"
        )
      expected = {
        "design_id": observation.design.design_id,
        "values": observation.design.values,
        "objective_name": self.objective_name,
        "objective": observation.objective,
        "feasible": observation.feasible,
        "disposition": observation.disposition.value,
        "training_eligible": observation.training_eligible,
        "exclusion_reason": observation.exclusion_reason,
      }
      drifted = [
        name
        for name, value in expected.items()
        if digest(event.payload.get(name)) != digest(value)
      ]
      if drifted:
        raise ValueError(
          f"observation '{observation.observation_id}' drifted from sealed fields: "
          + ", ".join(drifted)
        )
      context = f"observation '{observation.observation_id}'"
      source_event_ids = _string_id_sequence(
        event.payload.get("source_event_ids"),
        f"{context} source_event_ids",
      )
      constraint_event_ids = _string_id_sequence(
        event.payload.get("constraint_event_ids"),
        f"{context} constraint_event_ids",
      )
      gate_event_id = _required_text(event.payload, "gate_event_id", context)
      sealed_material_id = _required_text(event.payload, "material_id", context)
      feasibility_rationale = _required_text(
        event.payload, "feasibility_rationale", context
      )
      source_events = [
        ledger.event(source_event_id) for source_event_id in source_event_ids
      ]
      if any(source_event.sequence >= event.sequence for source_event in source_events):
        raise ValueError(f"{context} references evidence not recorded before it")
      gate_source_ids = [
        source_event.event_id
        for source_event in source_events
        if source_event.kind is EventKind.GATE_EVALUATED
      ]
      if gate_source_ids != [gate_event_id]:
        raise ValueError(
          f"{context} gate_event_id does not match its sealed source_event_ids"
        )
      replayed_material_id = _validate_observation_sources(
        ledger,
        run_id=event.run_id,
        objective_name=self.objective_name,
        objective=observation.objective,
        feasible=observation.feasible,
        disposition=observation.disposition,
        source_events=source_events,
        constraint_event_ids=constraint_event_ids,
        feasibility_rationale=feasibility_rationale,
        before_sequence=event.sequence,
      )
      if replayed_material_id != sealed_material_id:
        raise ValueError(
          f"{context} material_id does not match its replayed source lineage"
        )
      source_level = min(
        (source_event.evidence_level for source_event in source_events),
        key=lambda item: item.rank,
      )
      if event.evidence_level is not source_level:
        raise ValueError(
          f"{context} evidence level does not match its sealed sources"
        )
      if not observation.training_eligible:
        continue
      if not observation.evidence_level.at_least(self.minimum_evidence):
        continue
      eligible.append(observation)
    eligible.sort(
      key=lambda observation: (
        ledger.event(observation.evidence_event_id).sequence,
        observation.evidence_event_id,
      )
    )
    return eligible

  def _validate_design(self, design: Design) -> None:
    expected = {variable.name for variable in self.variables}
    actual = set(design.values)
    if actual != expected:
      missing = sorted(expected - actual)
      extra = sorted(actual - expected)
      raise ValueError(
        f"design '{design.design_id}' variables differ; missing={missing}, extra={extra}"
      )
    for variable in self.variables:
      value = design.values[variable.name]
      if not math.isfinite(value):
        raise ValueError(
          f"design '{design.design_id}' variable '{variable.name}' is not finite"
        )
      if not variable.lower <= value <= variable.upper:
        raise ValueError(
          f"design '{design.design_id}' variable '{variable.name}'={value} is outside "
          f"[{variable.lower}, {variable.upper}]"
        )

  def _candidates(self, observations: Sequence[Observation]) -> List[Dict[str, float]]:
    bases = _first_primes(len(self.variables))
    normalised_observed = [
      tuple(
        variable.normalise(observation.design.values[variable.name])
        for variable in self.variables
      )
      for observation in observations
    ]
    points: List[Tuple[float, ...]] = [tuple(0.5 for _ in self.variables)]
    points.extend(
      tuple(_halton(index, base) for base in bases)
      for index in range(1, self.candidate_count + 1)
    )
    out: List[Dict[str, float]] = []
    seen_design_digests = set()
    for point in points:
      if any(_distance(point, observed) < 1e-6 for observed in normalised_observed):
        continue
      values = {
        variable.name: round(variable.denormalise(value), 10)
        for variable, value in zip(self.variables, point)
      }
      design_digest = digest(values)
      if design_digest in seen_design_digests:
        continue
      seen_design_digests.add(design_digest)
      out.append(values)
    return out

  def _score(
    self,
    values: Dict[str, float],
    observations: Sequence[Observation],
  ) -> Tuple[Dict[str, float], float, float, float, float]:
    point = tuple(
      variable.normalise(values[variable.name]) for variable in self.variables
    )
    if not observations:
      return values, 0.0, 1.0, 0.5, self.exploration - 0.5 * self.risk_penalty
    observed_points = [
      tuple(
        variable.normalise(observation.design.values[variable.name])
        for variable in self.variables
      )
      for observation in observations
    ]
    distances = [_distance(point, observed) for observed in observed_points]
    bandwidth = 0.35
    weights = [
      math.exp(-(distance * distance) / (2.0 * bandwidth * bandwidth))
      for distance in distances
    ]
    total_weight = sum(weights)
    objectives = [observation.objective for observation in observations]
    if total_weight <= 1e-12:
      predicted = sum(objectives) / len(objectives)
    else:
      predicted = sum(
        weight * observation.objective
        for weight, observation in zip(weights, observations)
      ) / total_weight
    objective_span = max(objectives) - min(objectives)
    objective_scale = max(objective_span, abs(predicted) * 0.1, 1e-9)
    if total_weight <= 1e-12:
      local_variance = objective_scale * objective_scale
    else:
      local_variance = sum(
        weight * (observation.objective - predicted) ** 2
        for weight, observation in zip(weights, observations)
      ) / total_weight
    nearest = min(distances)
    uncertainty = math.sqrt(
      max(0.0, local_variance) + (nearest * objective_scale) ** 2
    )
    feasible_weight = sum(
      weight
      for weight, observation in zip(weights, observations)
      if observation.feasible
    )
    feasibility = (1.0 + feasible_weight) / (2.0 + total_weight)
    direction = 1.0 if self.maximize else -1.0
    score = (
      direction * predicted
      + self.exploration * uncertainty
      - self.risk_penalty * (1.0 - feasibility) * objective_scale
    )
    return values, predicted, uncertainty, feasibility, score


def _distance(left: Sequence[float], right: Sequence[float]) -> float:
  return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def _halton(index: int, base: int) -> float:
  result = 0.0
  factor = 1.0
  while index > 0:
    factor /= base
    result += factor * (index % base)
    index //= base
  return result


def _first_primes(count: int) -> Tuple[int, ...]:
  primes: List[int] = []
  candidate = 2
  while len(primes) < count:
    if all(candidate % prime for prime in primes if prime * prime <= candidate):
      primes.append(candidate)
    candidate += 1
  return tuple(primes)
