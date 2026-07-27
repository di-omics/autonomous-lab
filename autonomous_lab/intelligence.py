"""Deterministic evidence gates for the laboratory intelligence layer.

Models and robots may propose the next action. This module decides whether the
available physical evidence permits it. The distinction is deliberate: an agent can
suggest almost anything, but a run advances only when versioned, assay-specific rules
accept observations from the right sources.

The implementation is hardware-free. Observations arrive from integrations elsewhere
(a plate reader, a camera, instrument telemetry, or an operator), and this layer returns
CONTINUE, RETRY, RECOVER, ESCALATE, or STOP. It never actuates an instrument.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, Iterable, Optional, Tuple


def _parse_timestamp(value: str, field_name: str) -> datetime:
  """Parse an ISO-8601 timestamp and normalize it for chronological comparison."""
  if not isinstance(value, str) or not value:
    raise ValueError(f"{field_name} must be a non-empty ISO-8601 timestamp")
  normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
  try:
    parsed = datetime.fromisoformat(normalized)
  except ValueError as exc:
    raise ValueError(f"{field_name} must be a valid ISO-8601 timestamp") from exc
  if parsed.tzinfo is None or parsed.utcoffset() is None:
    raise ValueError(f"{field_name} must include a timezone offset")
  return parsed.astimezone(timezone.utc)


def _canonical_json(value: Any) -> str:
  """Return the exact JSON representation used for policy fingerprints."""

  def require_string_keys(node: Any):
    if isinstance(node, dict):
      for key, child in node.items():
        if not isinstance(key, str):
          raise ValueError("JSON mapping keys must be strings")
        require_string_keys(child)
    elif isinstance(node, (list, tuple)):
      for child in node:
        require_string_keys(child)

  require_string_keys(value)
  try:
    return json.dumps(
      value,
      sort_keys=True,
      separators=(",", ":"),
      ensure_ascii=True,
      allow_nan=False,
    )
  except (TypeError, ValueError) as exc:
    raise ValueError("expert policies must be exactly JSON serializable") from exc


def _freeze_json(value: Any, field_name: str) -> Any:
  """Detach and recursively freeze one portable JSON value."""
  try:
    clean = json.loads(_canonical_json(_thaw_json(value)))
  except ValueError as exc:
    raise ValueError(f"{field_name} must be portable JSON") from exc

  def freeze(node: Any) -> Any:
    if isinstance(node, dict):
      return MappingProxyType({key: freeze(child) for key, child in node.items()})
    if isinstance(node, list):
      return tuple(freeze(child) for child in node)
    return node

  return freeze(clean)


def _thaw_json(value: Any) -> Any:
  """Return a detached JSON-compatible copy of a frozen value."""
  if isinstance(value, Mapping):
    return {key: _thaw_json(child) for key, child in value.items()}
  if isinstance(value, tuple):
    return [_thaw_json(child) for child in value]
  return value


def _format_timestamp(value: datetime) -> str:
  return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class EvidenceKind(str, Enum):
  """Where an observation came from.

  VISION covers visible state such as labware pose or liquid presence. ASSAY_QC and
  TELEMETRY cover state a camera cannot establish, such as concentration or an
  instrument interlock. OPERATOR is explicit human evidence, never silently treated as
  machine evidence.
  """

  ASSAY_QC = "assay_qc"
  VISION = "vision"
  TELEMETRY = "telemetry"
  OPERATOR = "operator"


class Comparator(str, Enum):
  MINIMUM = "minimum"
  MAXIMUM = "maximum"
  RANGE = "range"
  EQUAL = "equal"


class GateStatus(str, Enum):
  PASS = "pass"
  FAIL = "fail"
  MISSING = "missing"


class DecisionAction(str, Enum):
  """What the orchestrator may do after evaluation."""

  CONTINUE = "continue"
  RETRY = "retry"
  RECOVER = "recover"
  ESCALATE = "escalate"
  STOP = "stop"


_ACTION_PRIORITY = {
  DecisionAction.CONTINUE: 0,
  DecisionAction.RETRY: 1,
  DecisionAction.RECOVER: 2,
  DecisionAction.ESCALATE: 3,
  DecisionAction.STOP: 4,
}


@dataclass(frozen=True)
class Observation:
  """One measured fact about one physical or digital subject."""

  metric: str
  value: Any
  kind: EvidenceKind
  subject: str
  source: str
  captured_at: str
  evidence_ref: str

  def __post_init__(self):
    for name in ("metric", "subject", "source", "captured_at", "evidence_ref"):
      if not isinstance(getattr(self, name), str) or not getattr(self, name):
        raise ValueError(f"observation {name} must not be empty")
    if not isinstance(self.kind, EvidenceKind):
      raise ValueError("observation kind must be an EvidenceKind")
    _parse_timestamp(self.captured_at, "observation captured_at")
    object.__setattr__(self, "value", _freeze_json(self.value, "observation value"))

  @property
  def captured_datetime(self) -> datetime:
    """Timezone-normalized capture time used by deterministic gate selection."""
    return _parse_timestamp(self.captured_at, "observation captured_at")

  def json_value(self) -> Any:
    return _thaw_json(self.value)

  def detached(self) -> "Observation":
    """Snapshot this observation so provider-owned mutable state cannot race audit."""
    return Observation(
      self.metric,
      self.json_value(),
      self.kind,
      self.subject,
      self.source,
      self.captured_at,
      self.evidence_ref,
    )


@dataclass(frozen=True)
class EvidenceGate:
  """A versioned piece of expert judgment expressed as an executable rule.

  `failure_action` and `recovery` capture what a senior scientist does when the rule
  fails. Missing or wrong-source evidence always stops the proposal; it cannot inherit
  the less severe failure action because the physical state is unknown.
  """

  gate_id: str
  metric: str
  comparator: Comparator
  allowed_sources: Tuple[EvidenceKind, ...]
  failure_action: DecisionAction
  recovery_id: str
  recovery: str
  subject: Optional[str] = None
  minimum: Optional[float] = None
  maximum: Optional[float] = None
  expected: Any = None
  rationale: str = ""
  max_age_seconds: Optional[float] = None
  max_future_skew_seconds: float = 0.0

  def __post_init__(self):
    object.__setattr__(self, "allowed_sources", tuple(self.allowed_sources))
    if self.expected is not None:
      object.__setattr__(self, "expected", _freeze_json(self.expected, "gate expected"))
    if not self.gate_id or not self.metric:
      raise ValueError("gate_id and metric must not be empty")
    if not self.allowed_sources:
      raise ValueError(f"gate {self.gate_id} must name at least one evidence source")
    if self.failure_action is DecisionAction.CONTINUE:
      raise ValueError(f"gate {self.gate_id} failure_action cannot be continue")
    if not self.recovery_id or not self.recovery:
      raise ValueError(
        f"gate {self.gate_id} must encode a recovery_id and recovery or escalation"
      )
    for name, value in (
      ("max_age_seconds", self.max_age_seconds),
      ("max_future_skew_seconds", self.max_future_skew_seconds),
    ):
      if value is None:
        continue
      if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"gate {self.gate_id} {name} must be a finite non-negative number")
      if not math.isfinite(value) or value < 0:
        raise ValueError(f"gate {self.gate_id} {name} must be a finite non-negative number")
    if self.comparator is Comparator.MINIMUM and self.minimum is None:
      raise ValueError(f"gate {self.gate_id} needs minimum")
    if self.comparator is Comparator.MAXIMUM and self.maximum is None:
      raise ValueError(f"gate {self.gate_id} needs maximum")
    if self.comparator is Comparator.RANGE:
      if self.minimum is None or self.maximum is None:
        raise ValueError(f"gate {self.gate_id} needs minimum and maximum")
      if self.minimum > self.maximum:
        raise ValueError(f"gate {self.gate_id} has an inverted range")
    if self.comparator is Comparator.EQUAL and self.expected is None:
      raise ValueError(f"gate {self.gate_id} needs expected")

  def accepts(self, value: Any) -> bool:
    """Evaluate a value without coercion that could hide a bad integration."""
    try:
      if self.comparator is Comparator.MINIMUM:
        return bool(value >= self.minimum)
      if self.comparator is Comparator.MAXIMUM:
        return bool(value <= self.maximum)
      if self.comparator is Comparator.RANGE:
        return bool(self.minimum <= value <= self.maximum)
      return bool(value == self.expected)
    except TypeError as exc:
      raise ValueError(
        f"gate {self.gate_id} cannot compare {value!r} with {self.comparator.value}"
      ) from exc

  def expectation(self) -> str:
    if self.comparator is Comparator.MINIMUM:
      return f">= {self.minimum}"
    if self.comparator is Comparator.MAXIMUM:
      return f"<= {self.maximum}"
    if self.comparator is Comparator.RANGE:
      return f"between {self.minimum} and {self.maximum}"
    return f"== {self.expected!r}"


@dataclass(frozen=True)
class ExpertPolicy:
  """A reviewable set of assay and physical-state acceptance criteria."""

  name: str
  version: str
  gates: Tuple[EvidenceGate, ...]
  owner: str
  note: str = ""

  def __post_init__(self):
    object.__setattr__(self, "gates", tuple(self.gates))
    if not self.name or not self.version or not self.owner:
      raise ValueError("policy name, version, and owner must not be empty")
    if not self.gates:
      raise ValueError(f"policy {self.name} must contain at least one gate")
    ids = [gate.gate_id for gate in self.gates]
    if len(ids) != len(set(ids)):
      raise ValueError(f"policy {self.name} contains duplicate gate ids")
    # Fail at policy construction rather than later when an orchestrator tries to bind
    # the policy to an audit record.
    self._canonical()

  def _document(self) -> Dict[str, Any]:
    return {
      "name": self.name,
      "version": self.version,
      "owner": self.owner,
      "note": self.note,
      "gates": [
        {
          "gate_id": gate.gate_id,
          "metric": gate.metric,
          "comparator": gate.comparator.value,
          "allowed_sources": [source.value for source in gate.allowed_sources],
          "failure_action": gate.failure_action.value,
          "recovery_id": gate.recovery_id,
          "recovery": gate.recovery,
          "subject": gate.subject,
          "minimum": gate.minimum,
          "maximum": gate.maximum,
          "expected": _thaw_json(gate.expected),
          "rationale": gate.rationale,
          "max_age_seconds": gate.max_age_seconds,
          "max_future_skew_seconds": gate.max_future_skew_seconds,
        }
        for gate in self.gates
      ],
    }

  def _canonical(self) -> str:
    return _canonical_json(self._document())

  def as_dict(self) -> Dict[str, Any]:
    """Return a detached, JSON-safe representation containing every policy field."""
    return json.loads(self._canonical())

  def fingerprint(self) -> str:
    """SHA-256 of the exact canonical policy document used for run binding."""
    return hashlib.sha256(self._canonical().encode("ascii")).hexdigest()

  def bind_sample(self, sample_id: str) -> "ExpertPolicy":
    """Bind reviewed ``$sample`` gate subjects to one task sample."""
    if not isinstance(sample_id, str) or not sample_id:
      raise ValueError("sample policy binding needs a non-empty sample_id")
    return ExpertPolicy(
      self.name,
      self.version,
      tuple(
        replace(gate, subject=sample_id) if gate.subject == "$sample" else gate
        for gate in self.gates
      ),
      self.owner,
      self.note,
    )


@dataclass(frozen=True)
class GateResult:
  gate: EvidenceGate
  status: GateStatus
  action: DecisionAction
  reason: str
  observation: Optional[Observation] = None


@dataclass(frozen=True)
class PermissionDecision:
  """The deterministic answer to a proposed action."""

  proposal: str
  policy_name: str
  policy_version: str
  action: DecisionAction
  results: Tuple[GateResult, ...]
  evaluated_at: str
  expires_at: Optional[str]

  @property
  def permitted(self) -> bool:
    return self.action is DecisionAction.CONTINUE

  @property
  def recoveries(self) -> Tuple[str, ...]:
    return tuple(
      result.gate.recovery for result in self.results if result.status is not GateStatus.PASS
    )

  @property
  def recovery_ids(self) -> Tuple[str, ...]:
    return tuple(
      result.gate.recovery_id
      for result in self.results
      if result.status is not GateStatus.PASS
    )

  def is_current(self, checked_at: Optional[str] = None) -> bool:
    if self.expires_at is None:
      return True
    current = (
      _parse_timestamp(checked_at, "checked_at")
      if checked_at is not None
      else datetime.now(timezone.utc)
    )
    return current <= _parse_timestamp(self.expires_at, "decision expires_at")


class DecisionEngine:
  """Evaluate proposals against evidence without calling a model or instrument."""

  def evaluate(
    self,
    proposal: str,
    policy: ExpertPolicy,
    observations: Iterable[Observation],
    evaluated_at: Optional[str] = None,
  ) -> PermissionDecision:
    if not proposal:
      raise ValueError("proposal must not be empty")
    evaluation_time = (
      _parse_timestamp(evaluated_at, "evaluated_at")
      if evaluated_at is not None
      else datetime.now(timezone.utc)
    )
    by_metric: Dict[str, list] = {}
    for observation in observations:
      if not isinstance(observation, Observation):
        raise ValueError("decision evidence must contain Observation objects")
      snapshot = observation.detached()
      by_metric.setdefault(snapshot.metric, []).append(snapshot)

    results = tuple(
      self._evaluate_gate(gate, by_metric, evaluation_time) for gate in policy.gates
    )
    action = max((result.action for result in results), key=_ACTION_PRIORITY.get)
    expirations = [
      result.observation.captured_datetime + timedelta(seconds=result.gate.max_age_seconds)
      for result in results
      if result.observation is not None and result.gate.max_age_seconds is not None
    ]
    return PermissionDecision(
      proposal=proposal,
      policy_name=policy.name,
      policy_version=policy.version,
      action=action,
      results=results,
      evaluated_at=_format_timestamp(evaluation_time),
      expires_at=_format_timestamp(min(expirations)) if expirations else None,
    )

  def _evaluate_gate(
    self,
    gate: EvidenceGate,
    by_metric: Dict[str, list],
    evaluation_time: datetime,
  ) -> GateResult:
    candidates = by_metric.get(gate.metric, [])
    if gate.subject is not None:
      candidates = [item for item in candidates if item.subject == gate.subject]
    if not candidates:
      return GateResult(
        gate,
        GateStatus.MISSING,
        DecisionAction.STOP,
        f"no observation for {gate.metric}; unknown physical state stops the run",
      )

    trusted = [item for item in candidates if item.kind in gate.allowed_sources]
    if not trusted:
      got = ", ".join(sorted({item.kind.value for item in candidates}))
      need = ", ".join(source.value for source in gate.allowed_sources)
      return GateResult(
        gate,
        GateStatus.MISSING,
        DecisionAction.STOP,
        f"{gate.metric} came from {got}, but this gate requires {need}",
      )

    # Compare normalized instants rather than timestamp strings: different UTC offsets
    # do not have lexical chronological order. evidence_ref breaks exact-time ties.
    observation = max(
      trusted, key=lambda item: (item.captured_datetime, item.evidence_ref)
    )
    age_seconds = (evaluation_time - observation.captured_datetime).total_seconds()
    if age_seconds < -gate.max_future_skew_seconds:
      ahead = -age_seconds
      return GateResult(
        gate,
        GateStatus.MISSING,
        DecisionAction.STOP,
        (
          f"{gate.metric} capture time is {ahead:.3f}s in the future, beyond the "
          f"{gate.max_future_skew_seconds:.3f}s allowed clock skew"
        ),
        observation,
      )
    if gate.max_age_seconds is not None and age_seconds > gate.max_age_seconds:
      return GateResult(
        gate,
        GateStatus.MISSING,
        DecisionAction.STOP,
        (
          f"{gate.metric} evidence is {age_seconds:.3f}s old, beyond the "
          f"{gate.max_age_seconds:.3f}s freshness limit"
        ),
        observation,
      )
    if gate.accepts(observation.value):
      return GateResult(
        gate,
        GateStatus.PASS,
        DecisionAction.CONTINUE,
        f"{gate.metric}={observation.value!r} satisfies {gate.expectation()}",
        observation,
      )
    return GateResult(
      gate,
      GateStatus.FAIL,
      gate.failure_action,
      f"{gate.metric}={observation.value!r} violates {gate.expectation()}",
      observation,
    )


def render_decision(decision: PermissionDecision) -> str:
  """Human-readable decision report used by the CLI and run records."""
  lines = [
    f"proposal: {decision.proposal}",
    f"policy:   {decision.policy_name}@{decision.policy_version}",
    f"decision: {decision.action.value.upper()}",
    "",
  ]
  for result in decision.results:
    source = ""
    if result.observation is not None:
      source = f" [{result.observation.kind.value}:{result.observation.source}]"
    lines.append(
      f"  {result.status.value.upper():<7} {result.gate.gate_id:<24} {result.reason}{source}"
    )
    if result.status is not GateStatus.PASS:
      lines.append(f"          recovery: {result.gate.recovery}")
  return "\n".join(lines)
