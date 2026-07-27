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

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, Optional, Tuple


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
      if not getattr(self, name):
        raise ValueError(f"observation {name} must not be empty")


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
  recovery: str
  subject: Optional[str] = None
  minimum: Optional[float] = None
  maximum: Optional[float] = None
  expected: Any = None
  rationale: str = ""

  def __post_init__(self):
    if not self.gate_id or not self.metric:
      raise ValueError("gate_id and metric must not be empty")
    if not self.allowed_sources:
      raise ValueError(f"gate {self.gate_id} must name at least one evidence source")
    if self.failure_action is DecisionAction.CONTINUE:
      raise ValueError(f"gate {self.gate_id} failure_action cannot be continue")
    if not self.recovery:
      raise ValueError(f"gate {self.gate_id} must encode a recovery or escalation")
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
    if not self.name or not self.version or not self.owner:
      raise ValueError("policy name, version, and owner must not be empty")
    if not self.gates:
      raise ValueError(f"policy {self.name} must contain at least one gate")
    ids = [gate.gate_id for gate in self.gates]
    if len(ids) != len(set(ids)):
      raise ValueError(f"policy {self.name} contains duplicate gate ids")


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

  @property
  def permitted(self) -> bool:
    return self.action is DecisionAction.CONTINUE

  @property
  def recoveries(self) -> Tuple[str, ...]:
    return tuple(
      result.gate.recovery for result in self.results if result.status is not GateStatus.PASS
    )


class DecisionEngine:
  """Evaluate proposals against evidence without calling a model or instrument."""

  def evaluate(
    self,
    proposal: str,
    policy: ExpertPolicy,
    observations: Iterable[Observation],
  ) -> PermissionDecision:
    if not proposal:
      raise ValueError("proposal must not be empty")
    by_metric: Dict[str, list] = {}
    for observation in observations:
      by_metric.setdefault(observation.metric, []).append(observation)

    results = tuple(self._evaluate_gate(gate, by_metric) for gate in policy.gates)
    action = max((result.action for result in results), key=_ACTION_PRIORITY.get)
    return PermissionDecision(
      proposal=proposal,
      policy_name=policy.name,
      policy_version=policy.version,
      action=action,
      results=results,
    )

  def _evaluate_gate(
    self, gate: EvidenceGate, by_metric: Dict[str, list]
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

    # ISO-8601 timestamps sort chronologically when integrations use the same normalized
    # timezone. evidence_ref breaks ties, keeping replay deterministic.
    observation = max(trusted, key=lambda item: (item.captured_at, item.evidence_ref))
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
