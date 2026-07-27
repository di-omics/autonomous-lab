"""Executable evidence gates and explicit expert knowledge for laboratory intelligence.

Models and robots may propose the next action. This module decides whether the
available physical evidence permits it. The distinction is deliberate: an agent can
suggest almost anything, but a run advances only when versioned, assay-specific rules
accept observations from the right sources.

The implementation is hardware-free. Observations arrive from integrations elsewhere
(a plate reader, a camera, instrument telemetry, or an operator), and this layer returns
CONTINUE, RETRY, RECOVER, ESCALATE, or STOP. It never actuates an instrument.

The same module records the judgments and benchmarks that precede safe automation.
``trusted_for()`` refuses trust without a met benchmark, while ``loop_closure()``
reports the independent execute, measure, decide, and record legs of a protocol.
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
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .qc import MEASUREMENTS, Basis, GateReport
from .recovery import RecoveryReport
from .vision import Observable


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
class BenchmarkStatus(str, Enum):
  """Whether a robot has earned the right to do a task unattended."""

  MET = "met"  # measured, and it passed
  UNMET = "unmet"  # measured, and it did not pass
  UNMEASURED = "unmeasured"  # nobody has run the measurement

  @property
  def trusted(self) -> bool:
    return self is BenchmarkStatus.MET


@dataclass(frozen=True)
class Benchmark:
  """A measurable target standing between a script that runs and a task that is trusted.

  `observable` records whether the property can be seen at all, which is what connects
  benchmarks to the vision taxonomy. The benchmarks that matter most for low-input work --
  volumetric accuracy, thermal uniformity, carryover -- are all INVISIBLE, so no camera
  retires them. They need a dedicated calibration experiment, and saying so is the point.
  """

  name: str
  op: str  # the operation this benchmark qualifies
  target: str  # what has to be true, in measurable terms
  status: BenchmarkStatus
  observable: Observable
  evidence: str = ""
  how_to_measure: str = ""


@dataclass(frozen=True)
class Judgment:
  """One piece of tacit expert reasoning, written down.

  `when` and `then` are prose on purpose. This module's job is to make tacit knowledge
  explicit and attributable, not to pretend it is executable: a judgment that could be
  safely compiled into a rule would already be in the protocol. The value is that it is
  recorded, sourced, and marked validated or not, so it can be argued with and tested.
  """

  name: str
  when: str  # the observation
  then: str  # what the scientist does
  because: str  # the mechanism; why the rule is not arbitrary
  basis: Basis
  # The failure mode this judgment guards against, where it maps to one. Links tacit
  # knowledge to the failure model rather than leaving it as unattached wisdom.
  guards: Optional[str] = None

  @property
  def validated(self) -> bool:
    return self.basis.validated


# -- the tacit knowledge of a low-input genomics bench -------------------------
# Every one of these is a real decision made routinely and written in no protocol.

JUDGMENTS: Tuple[Judgment, ...] = (
  Judgment(
    name="diffuse_pellet_means_rebind",
    when="the bead pellet looks diffuse or smeared rather than tight after the magnet step",
    then="do not proceed to elution; add binding buffer and re-collect on the magnet",
    because=(
      "a diffuse pellet means the beads have not fully collected, so aspirating the "
      "supernatant now removes library along with it. Eluting a partial pellet gives a low "
      "yield that looks like a failed reaction rather than a failed cleanup, and the two "
      "have opposite fixes"
    ),
    basis=Basis.INTUITION,
    guards="bead_pellet_aspirated",
  ),
  Judgment(
    name="sort_duration_bounds_comparability",
    when="a sort runs materially longer than usual for the same cell count",
    then="treat the last-sorted wells as a different condition from the first, or re-sort",
    because=(
      "cells sitting in the sheath and in the source tube are changing the whole time. A "
      "long sort turns one experiment into a time course nobody designed, and the effect "
      "loads onto plate position, which is exactly where a batch effect hides"
    ),
    basis=Basis.LITERATURE,
  ),
  Judgment(
    name="column_wise_failure_is_hardware",
    when="wells fail in a column-wise or channel-wise pattern rather than at random",
    then="stop and inspect the instrument before repeating any biology",
    because=(
      "biology fails randomly across a plate; hardware fails geometrically. A whole column "
      "failing is a channel, a tip, or a deck position, and repeating the prep will "
      "reproduce it exactly. This single pattern distinction saves more material than any "
      "other rule here"
    ),
    basis=Basis.IN_HOUSE,
  ),
  Judgment(
    name="signal_in_negative_invalidates_plate",
    when="the no-template control shows any product",
    then="discard the whole plate, not just the control well",
    because=(
      "contamination is not local. A control showing product means the contaminating "
      "material was present during setup, so every well saw it; the other wells simply had "
      "real template to compete with it. Keeping the wells that 'look fine' is how a "
      "contaminated dataset gets published"
    ),
    basis=Basis.IN_HOUSE,
  ),
  Judgment(
    name="quant_without_size_is_not_a_library",
    when="a library quantifies at an acceptable concentration",
    then="do not pool it until the size distribution has been checked",
    because=(
      "adapter dimer quantifies beautifully and sequences to nothing useful. Concentration "
      "alone cannot distinguish a good library from a tube of dimer, and dimer "
      "preferentially clusters, so it takes over the flow cell"
    ),
    basis=Basis.VENDOR,
    guards="bead_pellet_aspirated",
  ),
  Judgment(
    name="never_refreeze_the_enzyme_mix",
    when="an enzyme master mix has been thawed once already",
    then="discard it rather than returning it to the freezer",
    because=(
      "activity loss across freeze-thaw is real, gradual, and invisible. The failure it "
      "causes appears as a modest yield drop that gets attributed to the sample, which "
      "means the actual cause is never found"
    ),
    basis=Basis.VENDOR,
    guards="enzyme_activity_lost",
  ),
  Judgment(
    name="low_input_needs_fluorometric_quant",
    when="quantifying a library built from single-cell or otherwise picogram input",
    then="use a fluorometric or qPCR method; do not trust A260",
    because=(
      "A260 counts every nucleic acid in the well, including carrier, primer, and free "
      "nucleotide. At this input those dominate, so the reading is precise, reproducible, "
      "and not about the library. This is the judgment that makes the plate reader the "
      "wrong instrument for this assay even when it works"
    ),
    basis=Basis.IN_HOUSE,
  ),
  Judgment(
    name="one_driver_process_per_instrument",
    when="scheduling any two operations against the same instrument",
    then="serialize them; never open a second driver process",
    because=(
      "the STAR raises USBError [Errno 16] and stops, which is survivable. The ODTC does "
      "not: a second process re-registers the event receiver and silently steals the "
      "first's callbacks, so the first waits forever on a plate whose real state nobody is "
      "tracking. The quiet failure is the dangerous one"
    ),
    basis=Basis.IN_HOUSE,
    guards="odtc_callback_theft",
  ),
)


JUDGMENTS_BY_NAME: Dict[str, Judgment] = {j.name: j for j in JUDGMENTS}


# -- what a robot must prove before it is trusted -------------------------------

BENCHMARKS: Tuple[Benchmark, ...] = (
  Benchmark(
    name="low_volume_pipetting_cv",
    op="wgs_prep_lysis",
    target="coefficient of variation below 5 percent across a full plate at the working volume",
    status=BenchmarkStatus.UNMEASURED,
    observable=Observable.INVISIBLE,
    how_to_measure=(
      "gravimetric or dye-based measurement across all 96 positions, at the volume actually "
      "used, with the tips actually used. No camera substitutes for this"
    ),
    evidence="dry motion is validated; volumetric accuracy has never been measured",
  ),
  Benchmark(
    name="iswap_plate_transfer_repeatability",
    op="iswap_to_hhs",
    target="repeatable pickup and placement across consecutive transfers",
    status=BenchmarkStatus.MET,
    observable=Observable.VISIBLE,
    evidence="6 of 6 transfers clean, pickup landed at z 0.950 every time",
  ),
  Benchmark(
    name="tecan_tray_cycle_timing",
    op="tray_cycle",
    target="a bounded, known worst case for the drawer, for handoff scheduling",
    status=BenchmarkStatus.MET,
    observable=Observable.VISIBLE,
    evidence=(
      "five clean cycles on starpi2 2026-07-16; close stable at 3.6 s, open bimodal 3.2 s "
      "vs 5.3 s. Bounded, so schedulable, provided the worst case is budgeted"
    ),
  ),
  Benchmark(
    name="tecan_absorbance_read",
    op="read_absorbance",
    target="returns a complete OD matrix for a 96-well plate",
    status=BenchmarkStatus.UNMET,
    observable=Observable.INVISIBLE,
    evidence=(
      "FAILED on the instrument from starpi2 2026-07-16: TimeoutError on 'ABSOLUTE MTP,Y=', "
      "deterministic 2 of 2. The reader has never returned an OD matrix"
    ),
    how_to_measure="read a plate; the benchmark is currently blocked by the defect, not unmeasured",
  ),
  Benchmark(
    name="odtc_thermal_uniformity",
    op="pcr_enrichment_round1",
    target="well-to-well temperature spread within the block's specification, door closed",
    status=BenchmarkStatus.UNMEASURED,
    observable=Observable.INVISIBLE,
    how_to_measure="a calibrated thermal plate, or an amplification uniformity experiment across the block",
    evidence=(
      "cycling was observed on hardware, but the choreography does not close the door "
      "around the thermal leg, so any uniformity number measured today would not describe "
      "the intended configuration"
    ),
  ),
  Benchmark(
    name="bead_retention_through_wash",
    op="pcr_enrichment_round1_cleanup",
    target="measured recovery through the full bead protocol, with a known loss distribution",
    status=BenchmarkStatus.UNMEASURED,
    observable=Observable.VISIBLE_INDIRECT,
    how_to_measure="a spike-in of known quantity through the full cleanup, quantified at both ends",
    evidence="the state machine is written and dry-validated; it has never run wet",
  ),
  Benchmark(
    name="sort_well_occupancy",
    op="start_sort",
    target="measured single-cell occupancy across a plate, with the empty-well rate known",
    status=BenchmarkStatus.UNMEASURED,
    observable=Observable.VISIBLE_INDIRECT,
    how_to_measure="imaging or an amplification-based readout on a full plate of a known cell line",
    evidence="the command set is undecoded; the instrument cannot be driven at all yet",
  ),
)


BENCHMARKS_BY_OP: Dict[str, List[Benchmark]] = {}
for _b in BENCHMARKS:
  BENCHMARKS_BY_OP.setdefault(_b.op, []).append(_b)


def trusted_for(op: str) -> Tuple[bool, str]:
  """Has this operation earned unattended execution?

  A missing benchmark is not a pass. An operation nobody has benchmarked is untrusted by
  default, which is the opposite of the usual convention and the correct one: the absence
  of a measurement is not evidence of adequacy.
  """
  bench = BENCHMARKS_BY_OP.get(op)
  if not bench:
    return False, f"no benchmark is declared for '{op}'; an unmeasured operation is not a trusted one"
  unmet = [b for b in bench if not b.status.trusted]
  if unmet:
    names = ", ".join(f"{b.name} ({b.status.value})" for b in unmet)
    return False, f"benchmark not met: {names}"
  return True, f"all {len(bench)} benchmark(s) met"


# -- loop closure ---------------------------------------------------------------


class Leg(str, Enum):
  """The four things a lab must do to close one hypothesis-to-evidence loop."""

  EXECUTE = "execute"  # perform the experiment
  MEASURE = "measure"  # obtain a result that means something
  DECIDE = "decide"  # conclude what follows, defensibly
  RECORD = "record"  # capture it well enough to replay and audit


@dataclass(frozen=True)
class LegStatus:
  leg: Leg
  ok: bool
  reason: str


@dataclass
class LoopClosure:
  """Whether this lab can close a loop on a protocol, and which leg breaks.

  The value over a single autonomy percentage is that each broken leg implies a different
  next action: EXECUTE means reverse-engineering, MEASURE means an instrument that works,
  DECIDE means a gate whose input exists, RECORD means barcodes or an arm. A lab that only
  tracks autonomy will spend all four budgets on the first one.
  """

  protocol: str
  legs: List[LegStatus]

  @property
  def closes(self) -> bool:
    return all(leg.ok for leg in self.legs)

  def broken(self) -> List[LegStatus]:
    return [leg for leg in self.legs if not leg.ok]


def loop_closure(
  ledger,
  gates: GateReport,
  recovery: RecoveryReport,
  provenance,
) -> LoopClosure:
  """Check all four legs against real computed state.

  Every input is a report computed elsewhere. Nothing is re-derived here, so this cannot
  disagree with the ledger, the gate readiness, or the custody chain -- it only combines
  them.
  """
  legs: List[LegStatus] = []

  # EXECUTE: an unattended run has to reach the end.
  prefix = ledger.headless_prefix()
  total = len(ledger.rows)
  legs.append(
    LegStatus(
      Leg.EXECUTE,
      prefix == total,
      f"an unattended run reaches step {prefix} of {total}"
      + ("" if prefix == total else f"; it stops at '{ledger.first_stop().step.op}'"),
    )
  )

  # MEASURE: the gates need inputs that actually arrive, from an appropriate assay.
  unsat = gates.unsatisfiable()
  wrong_assay = gates.inappropriate(MEASUREMENTS)
  if not gates.rows:
    measure_ok, measure_why = False, "this protocol declares no QC gates, so no result is checked at all"
  elif unsat:
    measure_ok = False
    measure_why = (
      f"{len(unsat)} of {len(gates.rows)} gate(s) cannot be evaluated: "
      + "; ".join(g.gate.name for g in unsat)
    )
  elif wrong_assay:
    measure_ok = False
    measure_why = (
      f"{len(wrong_assay)} gate(s) rest on a measurement that is the wrong assay for the sample"
    )
  else:
    measure_ok, measure_why = True, f"all {len(gates.rows)} gate(s) can be evaluated"
  legs.append(LegStatus(Leg.MEASURE, measure_ok, measure_why))

  # DECIDE: a decision is only defensible if the failures it must react to are detectable.
  silent = recovery.destructive_and_silent()
  legs.append(
    LegStatus(
      Leg.DECIDE,
      not silent,
      f"all {len(recovery.rows)} failure mode(s) have a detection path"
      if not silent
      else (
        f"{len(silent)} failure mode(s) destroy material with nothing in this lab to notice: "
        + ", ".join(r.failure.name for r in silent)
      ),
    )
  )

  # RECORD: the chain has to survive the physical hops.
  legs.append(
    LegStatus(
      Leg.RECORD,
      provenance.unbroken,
      "the custody chain is unbroken"
      if provenance.unbroken
      else f"{len(provenance.gaps)} unobserved custody transfer(s); the record's identity claim is an assertion",
    )
  )

  return LoopClosure(protocol=ledger.protocol.name, legs=legs)


def knowledge_summary() -> Dict[str, int]:
  """How much of the encoded expert knowledge this lab has actually validated."""
  return {
    "judgments": len(JUDGMENTS),
    "judgments_validated": sum(1 for j in JUDGMENTS if j.validated),
    "benchmarks": len(BENCHMARKS),
    "benchmarks_met": sum(1 for b in BENCHMARKS if b.status.trusted),
    "benchmarks_unmeasured": sum(1 for b in BENCHMARKS if b.status is BenchmarkStatus.UNMEASURED),
    "benchmarks_failed": sum(1 for b in BENCHMARKS if b.status is BenchmarkStatus.UNMET),
  }


def unvalidated_judgments() -> List[Judgment]:
  """Expert rules this lab acts on and has never tested.

  Not a criticism. This is the normal state of a working bench and the reason the tacit
  layer is worth writing down at all: an unwritten rule cannot be validated, and a written
  one can be put in a queue.
  """
  return [j for j in JUDGMENTS if not j.validated]


def untrusted_ops(protocol) -> List[Tuple[str, str]]:
  """(op, reason) for every step in a protocol whose benchmark is not met.

  Deliberately includes steps the ledger already calls blocked. The two questions are
  independent: 'can the machine perform this' and 'has it earned the right to' fail for
  different reasons and are fixed by different work.
  """
  out: List[Tuple[str, str]] = []
  seen = set()
  for step in protocol.steps:
    if step.op in seen:
      continue
    seen.add(step.op)
    ok, why = trusted_for(step.op)
    if not ok:
      out.append((step.op, why))
  return out


__all__ = [
  "Comparator",
  "DecisionAction",
  "DecisionEngine",
  "EvidenceGate",
  "EvidenceKind",
  "ExpertPolicy",
  "GateResult",
  "GateStatus",
  "Observation",
  "PermissionDecision",
  "render_decision",
  "BENCHMARKS",
  "BENCHMARKS_BY_OP",
  "Benchmark",
  "BenchmarkStatus",
  "JUDGMENTS",
  "JUDGMENTS_BY_NAME",
  "Judgment",
  "Leg",
  "LegStatus",
  "LoopClosure",
  "knowledge_summary",
  "loop_closure",
  "trusted_for",
  "untrusted_ops",
  "unvalidated_judgments",
]
