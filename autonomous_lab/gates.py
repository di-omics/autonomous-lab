"""Deterministic, evidence-aware quality gates.

Models and agents may propose what to do next. They do not decide whether a material is
safe or scientifically useful to advance. A ``QualityGate`` evaluates explicit numeric
criteria against measurements in the evidence ledger and records the complete decision.

Missing data, weak evidence, and unit mismatches never pass by default.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple

from .evidence import EventKind, EvidenceEvent, EvidenceLedger, EvidenceLevel, digest
from .samples import MaterialStatus, Measurement, SampleTracker


class Comparator(str, Enum):
  AT_LEAST = "at_least"
  AT_MOST = "at_most"
  BETWEEN = "between"


class RuleOutcome(str, Enum):
  PASS = "pass"
  FAIL = "fail"
  HOLD = "hold"
  ERROR = "error"


class GateOutcome(str, Enum):
  PASS = "pass"
  FAIL = "fail"
  HOLD = "hold"
  ERROR = "error"


_UNAVAILABLE_GATE_STATUSES = frozenset(
  (
    MaterialStatus.QUARANTINED,
    MaterialStatus.CONSUMED,
    MaterialStatus.DISPOSED,
  )
)


def _material_state_events(
  tracker: SampleTracker, material_id: str
) -> Tuple[EvidenceEvent, ...]:
  """Return creation plus the event that establishes the current lifecycle status."""
  material = tracker.material(material_id)
  run_events = tracker.ledger.by_run(tracker.run_id)
  creation = [
    event
    for event in run_events
    if event.event_id == material.created_by_event
    and event.kind in (EventKind.MATERIAL_REGISTERED, EventKind.MATERIAL_DERIVED)
  ]
  if len(creation) != 1:
    raise ValueError(
      f"material '{material_id}' needs exactly one replayable creation event"
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


@dataclass(frozen=True)
class AcceptanceRule:
  """One comparator over one named metric."""

  rule_id: str
  metric: str
  comparator: Comparator
  unit: str
  lower: Optional[float] = None
  upper: Optional[float] = None
  required_evidence: EvidenceLevel = EvidenceLevel.MEASURED
  rationale: str = ""

  def __post_init__(self) -> None:
    if any(
      not isinstance(value, str) or not value.strip()
      for value in (self.rule_id, self.metric, self.unit)
    ):
      raise ValueError("rule_id, metric, and unit must not be empty")
    if not isinstance(self.comparator, Comparator):
      raise TypeError("comparator must be a Comparator")
    if not isinstance(self.required_evidence, EvidenceLevel):
      raise TypeError("required_evidence must be an EvidenceLevel")
    if not isinstance(self.rationale, str):
      raise TypeError("rationale must be a string")
    for name, value in (("lower", self.lower), ("upper", self.upper)):
      if value is not None and (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
      ):
        raise ValueError(f"rule '{self.rule_id}' {name} must be a finite number or null")
    if self.comparator is Comparator.AT_LEAST:
      if self.lower is None:
        raise ValueError(f"rule '{self.rule_id}' needs a lower threshold")
      if self.upper is not None:
        raise ValueError(f"rule '{self.rule_id}' at_least must not set upper")
    if self.comparator is Comparator.AT_MOST:
      if self.upper is None:
        raise ValueError(f"rule '{self.rule_id}' needs an upper threshold")
      if self.lower is not None:
        raise ValueError(f"rule '{self.rule_id}' at_most must not set lower")
    if self.comparator is Comparator.BETWEEN:
      if self.lower is None or self.upper is None:
        raise ValueError(f"rule '{self.rule_id}' needs lower and upper thresholds")
      if self.lower > self.upper:
        raise ValueError(f"rule '{self.rule_id}' lower threshold exceeds upper")

  def as_policy(self) -> Dict[str, object]:
    return {
      "rule_id": self.rule_id,
      "metric": self.metric,
      "comparator": self.comparator.value,
      "unit": self.unit,
      "lower": self.lower,
      "upper": self.upper,
      "required_evidence": self.required_evidence.value,
      "rationale": self.rationale,
    }


@dataclass(frozen=True)
class RuleResult:
  rule: AcceptanceRule
  outcome: RuleOutcome
  reason: str
  measurement: Optional[Measurement] = None

  def as_payload(self) -> Dict[str, object]:
    return {
      "rule_id": self.rule.rule_id,
      "metric": self.rule.metric,
      "outcome": self.outcome.value,
      "reason": self.reason,
      "measurement_id": (
        self.measurement.measurement_id if self.measurement is not None else None
      ),
      "measurement_event_id": (
        self.measurement.event_id if self.measurement is not None else None
      ),
      "value": self.measurement.value if self.measurement is not None else None,
      "unit": self.measurement.unit if self.measurement is not None else None,
      "evidence_level": (
        self.measurement.evidence_level.value
        if self.measurement is not None
        else None
      ),
    }


@dataclass(frozen=True)
class GateDecision:
  gate_id: str
  material_id: str
  outcome: GateOutcome
  rule_results: Tuple[RuleResult, ...]
  policy_digest: str
  event_id: str
  reason: str

  @property
  def allowed(self) -> bool:
    """Only a complete PASS authorizes downstream scientific use."""
    return self.outcome is GateOutcome.PASS


@dataclass(frozen=True)
class QualityGate:
  gate_id: str
  rules: Tuple[AcceptanceRule, ...]
  description: str = ""

  def __post_init__(self) -> None:
    if not isinstance(self.gate_id, str) or not self.gate_id.strip():
      raise ValueError("gate_id must not be empty")
    if not isinstance(self.description, str):
      raise TypeError("quality gate description must be a string")
    if not isinstance(self.rules, tuple):
      raise TypeError("quality gate rules must be a tuple")
    if not self.rules:
      raise ValueError(f"quality gate '{self.gate_id}' needs at least one rule")
    if any(not isinstance(rule, AcceptanceRule) for rule in self.rules):
      raise TypeError("quality gate rules must contain only AcceptanceRule values")
    ids = [rule.rule_id for rule in self.rules]
    if len(ids) != len(set(ids)):
      raise ValueError(f"quality gate '{self.gate_id}' has duplicate rule IDs")

  @property
  def policy(self) -> Dict[str, object]:
    """Canonical, replayable policy sealed into every gate decision."""
    return {
      "gate_id": self.gate_id,
      "description": self.description,
      "rules": [rule.as_policy() for rule in self.rules],
    }

  @property
  def policy_digest(self) -> str:
    return digest(self.policy)

  def evaluate(self, tracker: SampleTracker, material_id: str) -> GateDecision:
    """Evaluate the latest measurement for each rule and append the decision."""
    results, outcome, reason, level, payload = self._evaluate_snapshot(
      tracker, material_id
    )

    def validate(events) -> None:
      candidate = events[-1]
      current_ledger = EvidenceLedger(events=events[:-1])
      current_tracker = SampleTracker(
        current_ledger,
        tracker.run_id,
        actor=tracker.actor,
      )
      (
        _current_results,
        _current_outcome,
        _current_reason,
        current_level,
        current_payload,
      ) = self._evaluate_snapshot(current_tracker, material_id)
      if (
        candidate.evidence_level is not current_level
        or digest(candidate.payload) != digest(current_payload)
      ):
        raise ValueError(
          "quality-gate inputs changed before the decision could be sealed; "
          "re-evaluate against the current ledger"
        )

    event = tracker.ledger.append_transactionally(
      run_id=tracker.run_id,
      kind=EventKind.GATE_EVALUATED,
      actor=tracker.actor,
      evidence_level=level,
      payload=payload,
      validate=validate,
    )
    return GateDecision(
      gate_id=self.gate_id,
      material_id=material_id,
      outcome=outcome,
      rule_results=results,
      policy_digest=self.policy_digest,
      event_id=event.event_id,
      reason=reason,
    )

  def _evaluate_snapshot(
    self, tracker: SampleTracker, material_id: str
  ) -> Tuple[
    Tuple[RuleResult, ...],
    GateOutcome,
    str,
    EvidenceLevel,
    Dict[str, object],
  ]:
    """Build a gate decision from one coherent ledger snapshot."""
    material = tracker.material(material_id)
    state_events = _material_state_events(tracker, material_id)
    state_level = min(
      (event.evidence_level for event in state_events),
      key=lambda item: item.rank,
    )
    results = tuple(self._evaluate_rule(tracker, material_id, rule) for rule in self.rules)
    outcome = self._overall(results)
    reason = self._reason(outcome, results)
    if material.status in _UNAVAILABLE_GATE_STATUSES:
      outcome = GateOutcome.HOLD
      reason = (
        f"hold: material '{material_id}' is {material.status.value} and unavailable "
        "for scientific advancement"
      )
    strictest_required = max(
      (rule.required_evidence for rule in self.rules),
      key=lambda item: item.rank,
    )
    if (
      outcome is GateOutcome.PASS
      and not state_level.at_least(strictest_required)
    ):
      outcome = GateOutcome.HOLD
      reason = (
        f"hold: material state evidence is {state_level.value}, policy requires "
        f"at least {strictest_required.value}"
      )
    used_levels = [
      result.measurement.evidence_level
      for result in results
      if result.measurement is not None
    ]
    decision_levels = used_levels or [EvidenceLevel.MODELED]
    decision_levels.extend(event.evidence_level for event in state_events)
    level = min(decision_levels, key=lambda item: item.rank)
    payload = {
      "gate_id": self.gate_id,
      "material_id": material_id,
      "material_state_event_ids": [event.event_id for event in state_events],
      "outcome": outcome.value,
      "allowed": outcome is GateOutcome.PASS,
      "reason": reason,
      "policy_digest": self.policy_digest,
      "policy": self.policy,
      "rules": [result.as_payload() for result in results],
    }
    return results, outcome, reason, level, payload

  @staticmethod
  def _evaluate_rule(
    tracker: SampleTracker, material_id: str, rule: AcceptanceRule
  ) -> RuleResult:
    measurements = tracker.measurements(material_id, metric=rule.metric)
    if not measurements:
      return RuleResult(
        rule=rule,
        outcome=RuleOutcome.HOLD,
        reason=f"required metric '{rule.metric}' is missing",
      )
    measurement = measurements[-1]
    if measurement.unit != rule.unit:
      return RuleResult(
        rule=rule,
        outcome=RuleOutcome.ERROR,
        reason=(
          f"unit mismatch: measured {measurement.unit}, policy requires {rule.unit}; "
          "no conversion was declared"
        ),
        measurement=measurement,
      )
    if not measurement.evidence_level.at_least(rule.required_evidence):
      return RuleResult(
        rule=rule,
        outcome=RuleOutcome.HOLD,
        reason=(
          f"evidence is {measurement.evidence_level.value}, policy requires at least "
          f"{rule.required_evidence.value}"
        ),
        measurement=measurement,
      )
    passed = False
    if rule.comparator is Comparator.AT_LEAST:
      assert rule.lower is not None
      passed = measurement.value >= rule.lower
      criterion = f">= {rule.lower:g} {rule.unit}"
    elif rule.comparator is Comparator.AT_MOST:
      assert rule.upper is not None
      passed = measurement.value <= rule.upper
      criterion = f"<= {rule.upper:g} {rule.unit}"
    else:
      assert rule.lower is not None and rule.upper is not None
      passed = rule.lower <= measurement.value <= rule.upper
      criterion = f"between {rule.lower:g} and {rule.upper:g} {rule.unit}"
    return RuleResult(
      rule=rule,
      outcome=RuleOutcome.PASS if passed else RuleOutcome.FAIL,
      reason=(
        f"{measurement.value:g} {measurement.unit} "
        f"{'meets' if passed else 'does not meet'} {criterion}"
      ),
      measurement=measurement,
    )

  @staticmethod
  def _overall(results: Tuple[RuleResult, ...]) -> GateOutcome:
    outcomes = {result.outcome for result in results}
    if RuleOutcome.ERROR in outcomes:
      return GateOutcome.ERROR
    if RuleOutcome.FAIL in outcomes:
      return GateOutcome.FAIL
    if RuleOutcome.HOLD in outcomes:
      return GateOutcome.HOLD
    return GateOutcome.PASS

  @staticmethod
  def _reason(
    outcome: GateOutcome, results: Tuple[RuleResult, ...]
  ) -> str:
    if outcome is GateOutcome.PASS:
      return f"all {len(results)} acceptance rules passed"
    names = [
      result.rule.rule_id
      for result in results
      if result.outcome.value == outcome.value
      or (
        outcome is GateOutcome.FAIL
        and result.outcome in (RuleOutcome.FAIL, RuleOutcome.HOLD)
      )
    ]
    return f"{outcome.value}: " + ", ".join(names)
