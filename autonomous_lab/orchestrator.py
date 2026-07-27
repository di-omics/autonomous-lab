"""Policy-gated workcell orchestration with resource locks and bounded recovery.

The orchestrator is the seam between laboratory intelligence and a device adapter. A
scientist or model proposes a typed task. The orchestrator verifies sample location,
atomically leases every required resource, evaluates versioned expert policy, and only
then calls the injected operation. Expected driver failures are represented as results,
not exceptions, so retry and recovery budgets remain explicit and auditable.

This module contains no hardware driver. A caller may inject a simulator or a guarded
adapter from another repository. The adapter still owns its own arming boundary.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import Lock, RLock
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .intelligence import (
  DecisionAction,
  DecisionEngine,
  ExpertPolicy,
  Observation,
  PermissionDecision,
)
from .provenance import RunLedger, SampleTracker


MAX_AUTOMATIC_RESPONSES = 10


def _utc_now() -> str:
  return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_instant(value: str) -> datetime:
  normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
  return datetime.fromisoformat(normalized)


def _json_object_copy(value: Any, label: str) -> Dict[str, Any]:
  """Return a detached, portable JSON object with no coerced mapping keys."""

  if not isinstance(value, dict):
    raise ValueError(f"{label} must be a JSON object")

  def require_string_keys(node: Any):
    if isinstance(node, dict):
      for key, child in node.items():
        if not isinstance(key, str):
          raise ValueError(f"{label} mapping keys must be strings")
        require_string_keys(child)
    elif isinstance(node, (list, tuple)):
      for child in node:
        require_string_keys(child)

  require_string_keys(value)
  try:
    encoded = json.dumps(
      value,
      sort_keys=True,
      ensure_ascii=True,
      allow_nan=False,
    )
  except (TypeError, ValueError) as exc:
    raise ValueError(f"{label} must be portable JSON") from exc
  return json.loads(encoded)


class ResourceBusy(RuntimeError):
  """Raised when a task cannot lease its complete resource set."""

  def __init__(self, conflicts: Dict[str, Dict[str, Any]]):
    self.conflicts = dict(conflicts)
    detail = ", ".join(
      f"{resource} owned by {claim['run_id']}:{claim['task_id']}"
      for resource, claim in conflicts.items()
    )
    super().__init__(f"workcell resources are busy: {detail}")


class OperationStatus(str, Enum):
  SUCCEEDED = "succeeded"
  RETRYABLE = "retryable"
  RECOVERABLE = "recoverable"
  FAILED = "failed"


class SampleEffect(str, Enum):
  """What the adapter can establish about tracked sample/material state.

  ``NO_CHANGE`` does not mean a robot or instrument made no motion. It certifies that
  sample location, custody, and material state did not change in a way that makes replay
  unsafe. A transfer declares ``EXPECTED_CHANGE`` and still needs post-operation
  evidence before provenance advances.
  """

  NO_CHANGE = "no_change"
  EXPECTED_CHANGE = "expected_change"
  UNKNOWN = "unknown"


class TaskFinalState(str, Enum):
  SUCCEEDED = "succeeded"
  BLOCKED = "blocked"
  STOPPED = "stopped"
  ESCALATED = "escalated"
  FAILED = "failed"


@dataclass(frozen=True)
class OperationResult:
  status: OperationStatus
  detail: str
  effect: SampleEffect
  permit_id: str
  payload: Dict[str, Any] = field(default_factory=dict)
  recovery_id: Optional[str] = None

  def __post_init__(self):
    if not isinstance(self.status, OperationStatus):
      raise ValueError("operation result status must be an OperationStatus")
    if not isinstance(self.effect, SampleEffect):
      raise ValueError("operation result effect must be a SampleEffect")
    if not isinstance(self.detail, str) or not isinstance(self.permit_id, str):
      raise ValueError("operation result detail and permit_id must be strings")
    if not self.detail or not self.permit_id:
      raise ValueError("operation result detail and permit_id must not be empty")
    if self.recovery_id is not None and (
      not isinstance(self.recovery_id, str) or not self.recovery_id
    ):
      raise ValueError("operation result recovery_id must be a non-empty string")
    clean = _json_object_copy(self.payload, "operation result payload")
    if self.status in (OperationStatus.RETRYABLE, OperationStatus.RECOVERABLE):
      if self.effect is not SampleEffect.NO_CHANGE:
        raise ValueError(
          f"{self.status.value} results must certify no tracked sample/material "
          "state change before replay"
        )
    if self.status is OperationStatus.RECOVERABLE and not self.recovery_id:
      raise ValueError("recoverable results must name a reviewed recovery_id")
    if self.status is OperationStatus.SUCCEEDED and self.effect is SampleEffect.UNKNOWN:
      raise ValueError("successful operations must declare their tracked sample effect")
    object.__setattr__(self, "payload", clean)


@dataclass(frozen=True)
class AdapterBinding:
  adapter_id: str
  adapter_version: str
  configuration_hash: str

  def __post_init__(self):
    if any(
      not isinstance(value, str) or not value
      for value in (self.adapter_id, self.adapter_version, self.configuration_hash)
    ):
      raise ValueError("adapter binding requires id, version, and configuration hash")

  def as_dict(self) -> Dict[str, str]:
    return {
      "adapter_id": self.adapter_id,
      "adapter_version": self.adapter_version,
      "configuration_hash": self.configuration_hash,
    }

  def matches(self, adapter_id: str, adapter_version: str, configuration_hash: str) -> bool:
    return (
      self.adapter_id == adapter_id
      and self.adapter_version == adapter_version
      and self.configuration_hash == configuration_hash
    )


@dataclass(frozen=True)
class RecoveryBinding:
  recovery_id: str
  adapter: AdapterBinding

  def __post_init__(self):
    if (
      not isinstance(self.recovery_id, str)
      or not self.recovery_id
      or not isinstance(self.adapter, AdapterBinding)
    ):
      raise ValueError("recovery binding requires an id and AdapterBinding")

  def as_dict(self) -> Dict[str, Any]:
    return {"recovery_id": self.recovery_id, "adapter": self.adapter.as_dict()}


@dataclass(frozen=True)
class OperationContract:
  """Expert-reviewed action scope from which a task derives its permissions.

  Locations, resources, policies, and approved adapters live together so a caller cannot
  attach a passing policy to an unrelated transition or omit a resource from the lease.
  The fingerprint commits this exact scope into every execution record.
  """

  operation_id: str
  version: str
  expected_location: str
  success_location: str
  required_resources: Tuple[str, ...]
  preconditions: ExpertPolicy
  postconditions: ExpertPolicy
  max_retries: int
  max_recoveries: int
  allowed_adapters: Tuple[AdapterBinding, ...]
  recovery_adapters: Tuple[RecoveryBinding, ...] = ()

  def __post_init__(self):
    object.__setattr__(self, "required_resources", tuple(self.required_resources))
    object.__setattr__(self, "allowed_adapters", tuple(self.allowed_adapters))
    object.__setattr__(self, "recovery_adapters", tuple(self.recovery_adapters))
    for name in ("operation_id", "version", "expected_location", "success_location"):
      if not isinstance(getattr(self, name), str) or not getattr(self, name):
        raise ValueError(f"operation contract {name} must not be empty")
    if not isinstance(self.preconditions, ExpertPolicy) or not isinstance(
      self.postconditions, ExpertPolicy
    ):
      raise ValueError("operation contract preconditions and postconditions must be policies")
    if not self.required_resources or any(
      not isinstance(item, str) or not item for item in self.required_resources
    ):
      raise ValueError(f"operation {self.operation_id} needs mandatory resources")
    if len(self.required_resources) != len(set(self.required_resources)):
      raise ValueError(f"operation {self.operation_id} contains duplicate resources")
    if any(
      resource.startswith(("sample:", "task:")) for resource in self.required_resources
    ):
      raise ValueError("sample: and task: are reserved for implicit orchestrator leases")
    allowed_subjects = {"$sample", *self.required_resources}
    for phase, policy in (
      ("preconditions", self.preconditions),
      ("postconditions", self.postconditions),
    ):
      invalid_subjects = {
        gate.subject for gate in policy.gates if gate.subject not in allowed_subjects
      }
      if invalid_subjects:
        raise ValueError(
          f"operation {self.operation_id} {phase} gates must bind to $sample or a "
          f"leased resource; got {sorted(str(item) for item in invalid_subjects)}"
        )
      if not any(gate.subject == "$sample" for gate in policy.gates):
        raise ValueError(
          f"operation {self.operation_id} {phase} must include a $sample-bound gate"
        )
    for name in ("max_retries", "max_recoveries"):
      value = getattr(self, name)
      if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > MAX_AUTOMATIC_RESPONSES
      ):
        raise ValueError(
          f"operation {self.operation_id} {name} must be an integer from 0 to "
          f"{MAX_AUTOMATIC_RESPONSES}"
        )
    if not self.allowed_adapters or any(
      not isinstance(item, AdapterBinding) for item in self.allowed_adapters
    ):
      raise ValueError(f"operation {self.operation_id} needs an approved adapter")
    if len(self.allowed_adapters) != len(set(self.allowed_adapters)):
      raise ValueError(f"operation {self.operation_id} contains duplicate adapters")
    stale_unbounded = [
      gate.gate_id
      for policy in (self.preconditions, self.postconditions)
      for gate in policy.gates
      if gate.max_age_seconds is None
    ]
    if stale_unbounded:
      raise ValueError(
        f"operation {self.operation_id} requires finite evidence freshness for gates "
        f"{sorted(stale_unbounded)}"
      )
    if any(not isinstance(item, RecoveryBinding) for item in self.recovery_adapters):
      raise ValueError("recovery adapters must be RecoveryBinding objects")
    recovery_ids = [item.recovery_id for item in self.recovery_adapters]
    if len(recovery_ids) != len(set(recovery_ids)):
      raise ValueError(f"operation {self.operation_id} contains duplicate recovery bindings")
    required_recoveries = {
      gate.recovery_id
      for gate in self.preconditions.gates
      if gate.failure_action is DecisionAction.RECOVER
    }
    missing_recoveries = required_recoveries - set(recovery_ids)
    if missing_recoveries:
      raise ValueError(
        f"operation {self.operation_id} lacks adapter bindings for recoveries "
        f"{sorted(missing_recoveries)}"
      )

  def as_dict(self) -> Dict[str, Any]:
    return {
      "operation_id": self.operation_id,
      "version": self.version,
      "expected_location": self.expected_location,
      "success_location": self.success_location,
      "required_resources": list(self.required_resources),
      "preconditions": self.preconditions.as_dict(),
      "postconditions": self.postconditions.as_dict(),
      "max_retries": self.max_retries,
      "max_recoveries": self.max_recoveries,
      "allowed_adapters": [item.as_dict() for item in self.allowed_adapters],
      "recovery_adapters": [item.as_dict() for item in self.recovery_adapters],
    }

  def fingerprint(self) -> str:
    canonical = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()

  def allows_adapter(
    self, adapter_id: str, adapter_version: str, configuration_hash: str
  ) -> bool:
    return any(
      item.matches(adapter_id, adapter_version, configuration_hash)
      for item in self.allowed_adapters
    )

  def recovery_adapter(self, recovery_id: str) -> Optional[AdapterBinding]:
    for binding in self.recovery_adapters:
      if binding.recovery_id == recovery_id:
        return binding.adapter
    return None


@dataclass(frozen=True)
class ContractApproval:
  """Deployment-owned approval for one exact operation-contract fingerprint."""

  contract: OperationContract
  approved_by: str
  approval_ref: str
  contract_hash: str = field(init=False)

  def __post_init__(self):
    if not isinstance(self.contract, OperationContract):
      raise ValueError("approval contract must be an OperationContract")
    if any(
      not isinstance(value, str) or not value
      for value in (self.approved_by, self.approval_ref)
    ):
      raise ValueError("contract approval needs approved_by and approval_ref")
    object.__setattr__(self, "contract_hash", self.contract.fingerprint())

  def as_dict(self) -> Dict[str, str]:
    return {
      "operation_id": self.contract.operation_id,
      "version": self.contract.version,
      "contract_hash": self.contract_hash,
      "approved_by": self.approved_by,
      "approval_ref": self.approval_ref,
    }


class ContractRegistry:
  """Immutable set of exact contracts trusted by one orchestrator deployment."""

  def __init__(self, approvals: Iterable[ContractApproval] = ()):
    self._approvals: Dict[Tuple[str, str], ContractApproval] = {}
    for approval in approvals:
      if not isinstance(approval, ContractApproval):
        raise ValueError("contract registry entries must be ContractApproval objects")
      key = (approval.contract.operation_id, approval.contract.version)
      if key in self._approvals:
        raise ValueError(f"duplicate contract approval for {key[0]}@{key[1]}")
      self._approvals[key] = approval

  def approval(self, contract: OperationContract) -> Optional[ContractApproval]:
    candidate = self._approvals.get((contract.operation_id, contract.version))
    if candidate is None or candidate.contract_hash != contract.fingerprint():
      return None
    return candidate

  def snapshot(self) -> Tuple[ContractApproval, ...]:
    return tuple(self._approvals[key] for key in sorted(self._approvals))


@dataclass(frozen=True)
class WorkcellTask:
  """One proposal instantiated from a reviewed operation contract."""

  task_id: str
  proposal: str
  sample_id: str
  contract: OperationContract

  def __post_init__(self):
    for name in (
      "task_id",
      "proposal",
      "sample_id",
    ):
      if not isinstance(getattr(self, name), str) or not getattr(self, name):
        raise ValueError(f"task {name} must not be empty")
    if not isinstance(self.contract, OperationContract):
      raise ValueError("task contract must be an OperationContract")

  @property
  def operation_id(self) -> str:
    return self.contract.operation_id

  @property
  def expected_location(self) -> str:
    return self.contract.expected_location

  @property
  def success_location(self) -> str:
    return self.contract.success_location

  @property
  def resources(self) -> Tuple[str, ...]:
    return self.contract.required_resources

  @property
  def policy(self) -> ExpertPolicy:
    return self.contract.preconditions

  @property
  def postcondition_policy(self) -> ExpertPolicy:
    return self.contract.postconditions

  @property
  def max_retries(self) -> int:
    return self.contract.max_retries

  @property
  def max_recoveries(self) -> int:
    return self.contract.max_recoveries


@dataclass(frozen=True)
class AttemptRecord:
  number: int
  decision: PermissionDecision
  operation: Optional[OperationResult]
  postcondition: Optional[PermissionDecision] = None


@dataclass
class _ActuationEnvelope:
  started: bool = False
  attempt: int = 0
  permit_id: str = ""
  handled: bool = False


class _ExecutionPermitRejected(ValueError):
  """Raised when evidence is no longer valid at permit construction."""


@dataclass(frozen=True)
class ExecutionPermit:
  """Single-attempt capability passed to an approved adapter after permission."""

  permit_id: str
  idempotency_key: str
  run_id: str
  task_id: str
  operation_id: str
  contract_hash: str
  issued_at: str
  expires_at: str
  attempt: int
  leased_resources: Tuple[str, ...]

  def is_current(self, checked_at: Optional[str] = None) -> bool:
    current = _parse_instant(checked_at) if checked_at is not None else datetime.now(timezone.utc)
    return current <= _parse_instant(self.expires_at)


@dataclass(frozen=True)
class GuardedOperation:
  """Versioned adapter binding; the contract decides whether it is approved."""

  operation_id: str
  adapter_id: str
  adapter_version: str
  configuration_hash: str
  execute: Callable[[WorkcellTask, int, ExecutionPermit], OperationResult]

  def __post_init__(self):
    for name in ("operation_id", "adapter_id", "adapter_version", "configuration_hash"):
      if not isinstance(getattr(self, name), str) or not getattr(self, name):
        raise ValueError(f"guarded operation {name} must not be empty")
    if not callable(self.execute):
      raise ValueError("guarded operation execute must be callable")


class RecoveryStatus(str, Enum):
  SUCCEEDED = "succeeded"
  FAILED = "failed"


@dataclass(frozen=True)
class RecoveryPermit:
  permit_id: str
  idempotency_key: str
  run_id: str
  task_id: str
  recovery_id: str
  contract_hash: str
  issued_at: str
  expires_at: str
  count: int

  def is_current(self, checked_at: Optional[str] = None) -> bool:
    current = _parse_instant(checked_at) if checked_at is not None else datetime.now(timezone.utc)
    return current <= _parse_instant(self.expires_at)


@dataclass(frozen=True)
class RecoveryResult:
  status: RecoveryStatus
  detail: str
  effect: SampleEffect
  permit_id: str

  def __post_init__(self):
    if not isinstance(self.status, RecoveryStatus):
      raise ValueError("recovery result status must be a RecoveryStatus")
    if not isinstance(self.effect, SampleEffect):
      raise ValueError("recovery result effect must be a SampleEffect")
    if not isinstance(self.detail, str) or not isinstance(self.permit_id, str):
      raise ValueError("recovery result detail and permit_id must be strings")
    if not self.detail or not self.permit_id:
      raise ValueError("recovery result detail and permit_id must not be empty")


@dataclass(frozen=True)
class GuardedRecovery:
  recovery_id: str
  adapter_id: str
  adapter_version: str
  configuration_hash: str
  execute: Callable[[WorkcellTask, str, int, RecoveryPermit], RecoveryResult]

  def __post_init__(self):
    for name in ("recovery_id", "adapter_id", "adapter_version", "configuration_hash"):
      if not isinstance(getattr(self, name), str) or not getattr(self, name):
        raise ValueError(f"guarded recovery {name} must not be empty")
    if not callable(self.execute):
      raise ValueError("guarded recovery execute must be callable")


@dataclass(frozen=True)
class OrchestrationReport:
  task: WorkcellTask
  final_state: TaskFinalState
  attempts: Tuple[AttemptRecord, ...]
  retries_used: int
  recoveries_used: int
  detail: str
  final_location: str
  ledger: RunLedger

  @property
  def succeeded(self) -> bool:
    return self.final_state is TaskFinalState.SUCCEEDED

  def render(self) -> str:
    ok, chain = self.ledger.verify()
    lines = [
      f"task:       {self.task.task_id}",
      f"proposal:   {self.task.proposal}",
      f"resources:  {', '.join(self.task.resources)}",
      f"final:      {self.final_state.value.upper()}",
      f"sample:     {self.task.sample_id} at {self.final_location}",
      f"budgets:    {self.retries_used}/{self.task.max_retries} retries, "
      f"{self.recoveries_used}/{self.task.max_recoveries} recoveries",
      f"detail:     {self.detail}",
      f"audit:      {'VALID' if ok else 'INVALID'} - {chain}",
      "",
    ]
    for attempt in self.attempts:
      operation = "not called"
      if attempt.operation is not None:
        operation = f"{attempt.operation.status.value}: {attempt.operation.detail}"
      postcondition = ""
      if attempt.postcondition is not None:
        postcondition = f"; postcondition={attempt.postcondition.action.value}"
      lines.append(
        f"  attempt {attempt.number}: decision={attempt.decision.action.value}; "
        f"operation={operation}{postcondition}"
      )
    return "\n".join(lines)


class ResourceLease:
  def __init__(
    self,
    manager: "ResourceManager",
    owner: str,
    resources: Tuple[str, ...],
    token: int,
    ledger: Optional[RunLedger],
  ):
    self._manager = manager
    self._token = token
    self._ledger = ledger
    self._release_lock = Lock()
    self.owner = owner
    self.resources = resources
    self.released = False

  def release(self):
    with self._release_lock:
      if self.released:
        return
      self._manager._release(
        self.owner,
        self.resources,
        self._token,
        self._ledger,
      )
      self.released = True

  def __enter__(self) -> "ResourceLease":
    return self

  def __exit__(self, exc_type, exc, traceback):
    self.release()


@dataclass
class _ResourceNamespaceState:
  owners: Dict[str, Tuple[str, str, int]] = field(default_factory=dict)
  lock: RLock = field(default_factory=RLock)
  generation: int = 0
  after_release: Dict[Tuple[str, str, int], List[Callable[[], None]]] = field(
    default_factory=dict
  )


_RESOURCE_NAMESPACE_LOCK = Lock()
_RESOURCE_NAMESPACES: Dict[str, _ResourceNamespaceState] = {}


class ResourceManager:
  """Atomically enforce one active owner per resource inside this process.

  A production workcell still needs a durable inter-process or distributed lease so a
  second controller process cannot bypass this in-memory manager.
  """

  def __init__(self, workcell_namespace: str = "process-default"):
    if not isinstance(workcell_namespace, str) or not workcell_namespace:
      raise ValueError("resource manager workcell_namespace must be a non-empty string")
    self.workcell_namespace = workcell_namespace
    with _RESOURCE_NAMESPACE_LOCK:
      self._state = _RESOURCE_NAMESPACES.setdefault(
        workcell_namespace,
        _ResourceNamespaceState(),
      )

  def acquire(
    self,
    owner: str,
    resources: Iterable[str],
    ledger: Optional[RunLedger] = None,
  ) -> ResourceLease:
    if not isinstance(owner, str) or not owner:
      raise ValueError("resource acquisition needs an owner and named resources")
    supplied = tuple(resources)
    if not supplied or any(not isinstance(resource, str) or not resource for resource in supplied):
      raise ValueError("resource acquisition needs an owner and named resources")
    requested = tuple(sorted(supplied))
    if len(requested) != len(set(requested)):
      raise ValueError("resource acquisition contains duplicates")
    run_id = ledger.run_id if ledger is not None else f"unscoped:{self.workcell_namespace}"
    with self._state.lock:
      conflicts = {
        resource: {
          "run_id": self._state.owners[resource][0],
          "task_id": self._state.owners[resource][1],
          "lease_generation": self._state.owners[resource][2],
          "workcell_namespace": self.workcell_namespace,
        }
        for resource in requested
        if resource in self._state.owners
      }
      if conflicts:
        if ledger is not None:
          ledger.append(
            "resource",
            owner,
            "blocked",
            {"conflicts": conflicts},
          )
        raise ResourceBusy(conflicts)
      self._state.generation += 1
      token = self._state.generation
      for resource in requested:
        self._state.owners[resource] = (run_id, owner, token)
      try:
        if ledger is not None:
          ledger.append(
            "resource",
            owner,
            "acquire",
            {
              "resources": list(requested),
              "lease_generation": token,
              "owner_run_id": run_id,
              "workcell_namespace": self.workcell_namespace,
            },
          )
      except BaseException:
        for resource in requested:
          del self._state.owners[resource]
        raise
      return ResourceLease(self, owner, requested, token, ledger)

  def owner(self, resource: str) -> Optional[str]:
    with self._state.lock:
      current = self._state.owners.get(resource)
      return current[1] if current is not None else None

  def snapshot(self) -> Dict[str, str]:
    with self._state.lock:
      return {
        resource: owner
        for resource, (_run_id, owner, _token) in self._state.owners.items()
      }

  def defer_until_release(
    self,
    run_id: str,
    owner: str,
    callback: Callable[[], None],
  ) -> bool:
    """Schedule an audit callback after this owner's exact lease is released."""
    with self._state.lock:
      claims = {
        claim
        for claim in self._state.owners.values()
        if claim[0] == run_id and claim[1] == owner
      }
      if not claims:
        return False
      if len(claims) != 1:
        raise RuntimeError(f"{run_id}:{owner} owns multiple lease generations")
      self._state.after_release.setdefault(claims.pop(), []).append(callback)
      return True

  def _release(
    self,
    owner: str,
    resources: Tuple[str, ...],
    token: int,
    ledger: Optional[RunLedger],
  ):
    run_id = ledger.run_id if ledger is not None else f"unscoped:{self.workcell_namespace}"
    with self._state.lock:
      for resource in resources:
        if self._state.owners.get(resource) != (run_id, owner, token):
          raise RuntimeError(
            f"lease {token} for {owner} cannot release {resource}; "
            "it does not own that exact lease generation"
          )
      if ledger is not None:
        ledger.append(
          "resource",
          owner,
          "release",
          {
            "resources": list(resources),
            "lease_generation": token,
            "owner_run_id": run_id,
            "workcell_namespace": self.workcell_namespace,
          },
        )
      for resource in resources:
        del self._state.owners[resource]
      callbacks = self._state.after_release.pop((run_id, owner, token), [])
      for callback in callbacks:
        callback()


_PROCESS_RESOURCE_MANAGER = ResourceManager()


EvidenceProvider = Callable[[WorkcellTask, int], Iterable[Observation]]


class WorkcellOrchestrator:
  """Run one task only as far as evidence, budgets, and resource state permit."""

  def __init__(
    self,
    ledger: RunLedger,
    samples: SampleTracker,
    resources: Optional[ResourceManager] = None,
    contracts: Optional[ContractRegistry] = None,
  ):
    if samples.ledger is not ledger:
      raise ValueError("sample tracker and orchestrator must share the same run ledger")
    self.ledger = ledger
    self.samples = samples
    self.resources = resources if resources is not None else _PROCESS_RESOURCE_MANAGER
    # Permission is intentionally not injectable: policy evaluation is part of the
    # orchestrator's trusted deterministic core, not an adapter extension point.
    self._decisions = DecisionEngine()
    self.contracts = contracts or ContractRegistry()

  def run(
    self,
    task: WorkcellTask,
    evidence: EvidenceProvider,
    operation: GuardedOperation,
    post_evidence: EvidenceProvider,
    recover: Optional[GuardedRecovery] = None,
  ) -> OrchestrationReport:
    self.ledger.assert_valid()
    if not self.ledger.claim_task_id(task.task_id):
      detail = f"task_id {task.task_id} has already been used in run {self.ledger.run_id}"
      self.ledger.append(
        "task_collision",
        task.sample_id,
        "blocked",
        {"colliding_task_id": task.task_id, "detail": detail},
      )
      self.ledger.assert_valid()
      current = self.samples.samples.get(task.sample_id)
      return OrchestrationReport(
        task,
        TaskFinalState.BLOCKED,
        (),
        0,
        0,
        detail,
        current.location if current is not None else "unknown",
        self.ledger,
      )
    try:
      state = self._sample_state(task)
    except (KeyError, ValueError) as exc:
      detail = f"initial sample provenance rejected task: {exc}"
      self.ledger.append(
        "task", task.sample_id, "blocked", {"task_id": task.task_id, "detail": detail}
      )
      current = self.samples.samples.get(task.sample_id)
      return self._report(
        task,
        TaskFinalState.BLOCKED,
        [],
        0,
        0,
        detail,
        current.location if current is not None else "unknown",
      )
    contract_hash = task.contract.fingerprint()
    approval = self.contracts.approval(task.contract)
    binding_error = self._binding_error(task, operation)
    adapter_id = operation.adapter_id if isinstance(operation, GuardedOperation) else "unbound"
    adapter_version = (
      operation.adapter_version if isinstance(operation, GuardedOperation) else "unbound"
    )
    adapter_configuration_hash = (
      operation.configuration_hash if isinstance(operation, GuardedOperation) else "unbound"
    )
    self.ledger.append(
      "task",
      task.sample_id,
      "propose",
      {
        "task_id": task.task_id,
        "proposal": task.proposal,
        "expected_location": task.expected_location,
        "success_location": task.success_location,
        "resources": list(task.resources),
        "operation_id": task.operation_id,
        "contract": f"{task.operation_id}@{task.contract.version}",
        "contract_hash": contract_hash,
        "contract_document": task.contract.as_dict(),
        "contract_approval": approval.as_dict() if approval is not None else None,
        "policy": f"{task.policy.name}@{task.policy.version}",
        "policy_hash": task.policy.fingerprint(),
        "postcondition_policy": f"{task.postcondition_policy.name}@{task.postcondition_policy.version}",
        "postcondition_policy_hash": task.postcondition_policy.fingerprint(),
        "sample_subject_binding": {"$sample": task.sample_id},
        "adapter_id": adapter_id,
        "adapter_version": adapter_version,
        "adapter_configuration_hash": adapter_configuration_hash,
        "max_retries": task.max_retries,
        "max_recoveries": task.max_recoveries,
      },
    )
    if binding_error is not None:
      self.ledger.append(
        "operation", task.sample_id, "blocked", {"task_id": task.task_id, "detail": binding_error}
      )
      return self._report(
        task,
        TaskFinalState.BLOCKED,
        [],
        0,
        0,
        binding_error,
        state.location,
      )
    leased_resources = (
      *task.resources,
      f"sample:{task.sample_id}",
      f"task:{task.task_id}",
    )
    try:
      lease = self.resources.acquire(task.task_id, leased_resources, self.ledger)
    except ResourceBusy as exc:
      return self._report(
        task,
        TaskFinalState.BLOCKED,
        [],
        0,
        0,
        str(exc),
        state.location,
      )

    attempts: List[AttemptRecord] = []
    retries = 0
    recoveries = 0
    actuation = _ActuationEnvelope()
    with self._leased_custody(
      lease,
      task,
      attempts,
      lambda: (retries, recoveries),
    ), self._fail_closed_after_start(
      task,
      actuation,
      attempts,
      lambda: (retries, recoveries),
    ):
      # The first check gives callers an immediate provenance error. This second check is
      # under both the resource-manager sample lease and tracker custody lock. Direct
      # tracker mutations therefore cannot cross the task's execution window.
      try:
        state = self._sample_state(task)
      except (KeyError, ValueError) as exc:
        detail = f"sample provenance changed before lease acquisition: {exc}"
        self.ledger.append(
          "task", task.sample_id, "blocked", {"task_id": task.task_id, "detail": detail}
        )
        current = self.samples.samples.get(task.sample_id)
        final_location = current.location if current is not None else "unknown"
        return self._report(
          task,
          TaskFinalState.BLOCKED,
          attempts,
          retries,
          recoveries,
          detail,
          final_location,
        )
      attempt_number = 0
      precondition_policy = task.policy.bind_sample(task.sample_id)
      postcondition_policy = task.postcondition_policy.bind_sample(task.sample_id)
      while True:
        attempt_number += 1
        try:
          observations = tuple(
            observation.detached() for observation in evidence(task, attempt_number)
          )
          self._record_observations(task, attempt_number, "precondition", observations)
          decision = self._decisions.evaluate(
            task.proposal,
            precondition_policy,
            observations,
          )
          self._record_decision(
            task,
            attempt_number,
            "precondition",
            decision,
            precondition_policy,
          )
        except BaseException as exc:
          detail = f"evidence or decision adapter raised {type(exc).__name__}: {exc}"
          self.ledger.append(
            "task", task.sample_id, "adapter_error", {"task_id": task.task_id, "detail": detail}
          )
          report = self._report(
            task,
            TaskFinalState.FAILED,
            attempts,
            retries,
            recoveries,
            detail,
            self.samples.samples[task.sample_id].location,
          )
          if not isinstance(exc, Exception):
            raise
          return report

        if not decision.permitted:
          attempts.append(AttemptRecord(attempt_number, decision, None))
          if decision.action is DecisionAction.RETRY and retries < task.max_retries:
            retries += 1
            self._record_control(task, "retry", retries, decision.recoveries)
            continue
          if (
            decision.action is DecisionAction.RECOVER
            and recover is not None
            and recoveries < task.max_recoveries
          ):
            recoveries += 1
            try:
              recovered, detail = self._run_recovery(
                task,
                decision,
                recover,
                "; ".join(decision.recoveries),
                recoveries,
              )
            except BaseException as exc:
              if not isinstance(exc, Exception):
                detail = f"recovery control cancelled by {type(exc).__name__}: {exc}"
                self._report(
                  task,
                  TaskFinalState.ESCALATED,
                  attempts,
                  retries,
                  recoveries,
                  detail,
                  self.samples.samples[task.sample_id].location,
                )
                raise
              recovered = False
              detail = f"recovery control failed closed: {type(exc).__name__}: {exc}"
            if not recovered:
              return self._report(
                task,
                TaskFinalState.ESCALATED,
                attempts,
                retries,
                recoveries,
                detail,
                self.samples.samples[task.sample_id].location,
              )
            self._record_control(task, "recover", recoveries, decision.recoveries)
            continue
          final = (
            TaskFinalState.STOPPED
            if decision.action is DecisionAction.STOP
            else TaskFinalState.ESCALATED
          )
          detail = self._decision_detail(decision, task)
          self.ledger.append(
            "task",
            task.sample_id,
            final.value,
            {"task_id": task.task_id, "detail": detail},
          )
          return self._report(
            task,
            final,
            attempts,
            retries,
            recoveries,
            detail,
            self.samples.samples[task.sample_id].location,
          )

        binding_error = self._binding_error(task, operation)
        if binding_error is not None:
          detail = f"permission invalidated before adapter invocation: {binding_error}"
          attempts.append(AttemptRecord(attempt_number, decision, None))
          self.ledger.append(
            "operation",
            task.sample_id,
            "blocked",
            {"task_id": task.task_id, "detail": detail},
          )
          return self._report(
            task,
            TaskFinalState.BLOCKED,
            attempts,
            retries,
            recoveries,
            detail,
            self.samples.samples[task.sample_id].location,
          )
        # Verification can be O(n), so it must finish before the final freshness check.
        # Evidence that expires during verification never reaches permit construction.
        self.ledger.assert_valid()
        if not decision.is_current():
          detail = "precondition evidence expired before adapter invocation"
          attempts.append(AttemptRecord(attempt_number, decision, None))
          self.ledger.append(
            "operation",
            task.sample_id,
            "expired",
            {"task_id": task.task_id, "detail": detail},
          )
          return self._report(
            task,
            TaskFinalState.STOPPED,
            attempts,
            retries,
            recoveries,
            detail,
            self.samples.samples[task.sample_id].location,
          )
        try:
          permit = self._execution_permit(
            task,
            attempt_number,
            lease.resources,
            decision,
          )
        except _ExecutionPermitRejected as exc:
          detail = str(exc)
          attempts.append(AttemptRecord(attempt_number, decision, None))
          self.ledger.append(
            "operation",
            task.sample_id,
            "expired",
            {"task_id": task.task_id, "detail": detail},
          )
          return self._report(
            task,
            TaskFinalState.STOPPED,
            attempts,
            retries,
            recoveries,
            detail,
            self.samples.samples[task.sample_id].location,
          )
        actuation.started = True
        actuation.attempt = attempt_number
        actuation.permit_id = permit.permit_id
        actuation.handled = False
        self.ledger.append(
          "operation",
          task.sample_id,
          "start",
          {
            "task_id": task.task_id,
            "attempt": attempt_number,
            "operation_id": operation.operation_id,
            "adapter_id": operation.adapter_id,
            "adapter_version": operation.adapter_version,
            "adapter_configuration_hash": operation.configuration_hash,
            "contract_hash": permit.contract_hash,
            "permit_id": permit.permit_id,
            "idempotency_key": permit.idempotency_key,
            "permit_issued_at": permit.issued_at,
            "permit_expires_at": permit.expires_at,
          },
        )
        if not permit.is_current():
          detail = "execution permit expired before the adapter call"
          attempts.append(AttemptRecord(attempt_number, decision, None))
          self.ledger.append(
            "operation",
            task.sample_id,
            "expired",
            {"task_id": task.task_id, "detail": detail, "permit_id": permit.permit_id},
          )
          return self._report(
            task,
            TaskFinalState.STOPPED,
            attempts,
            retries,
            recoveries,
            detail,
            self.samples.samples[task.sample_id].location,
          )
        try:
          result = operation.execute(task, attempt_number, permit)
        except BaseException as exc:
          detail = f"operation adapter raised {type(exc).__name__}: {exc}"
          self._mark_uncertain(task, detail)
          self.ledger.append(
            "operation",
            task.sample_id,
            "failed",
            {"task_id": task.task_id, "detail": detail},
          )
          attempts.append(
            AttemptRecord(
              attempt_number,
              decision,
              OperationResult(
                OperationStatus.FAILED,
                detail,
                SampleEffect.UNKNOWN,
                permit.permit_id,
              ),
            )
          )
          report = self._report(
            task,
            TaskFinalState.FAILED,
            attempts,
            retries,
            recoveries,
            detail,
            self.samples.samples[task.sample_id].location,
          )
          if not isinstance(exc, Exception):
            actuation.handled = True
            raise
          return report
        if not isinstance(result, OperationResult):
          detail = "operation adapter returned an untyped result instead of OperationResult"
          self._mark_uncertain(task, detail)
          failed = OperationResult(
            OperationStatus.FAILED,
            detail,
            SampleEffect.UNKNOWN,
            permit.permit_id,
          )
          attempts.append(AttemptRecord(attempt_number, decision, failed))
          self.ledger.append(
            "operation",
            task.sample_id,
            "failed",
            {"task_id": task.task_id, "detail": detail},
          )
          return self._report(
            task,
            TaskFinalState.FAILED,
            attempts,
            retries,
            recoveries,
            detail,
            self.samples.samples[task.sample_id].location,
          )
        try:
          # Rebuild a detached result after the adapter returns. This closes the gap
          # where adapter code mutates the otherwise-frozen result's nested payload
          # after construction but before the ledger commits it.
          result = OperationResult(
            result.status,
            result.detail,
            result.effect,
            result.permit_id,
            result.payload,
            result.recovery_id,
          )
        except (TypeError, ValueError) as exc:
          detail = f"operation returned an invalid result: {type(exc).__name__}: {exc}"
          self._mark_uncertain(task, detail)
          failed = OperationResult(
            OperationStatus.FAILED,
            detail,
            SampleEffect.UNKNOWN,
            permit.permit_id,
          )
          attempts.append(AttemptRecord(attempt_number, decision, failed))
          self.ledger.append(
            "operation",
            task.sample_id,
            "failed",
            {"task_id": task.task_id, "detail": detail},
          )
          return self._report(
            task,
            TaskFinalState.FAILED,
            attempts,
            retries,
            recoveries,
            detail,
            self.samples.samples[task.sample_id].location,
          )
        if result.permit_id != permit.permit_id:
          detail = "operation result did not echo the active execution permit"
          self._mark_uncertain(task, detail)
          failed = OperationResult(
            OperationStatus.FAILED,
            detail,
            SampleEffect.UNKNOWN,
            permit.permit_id,
          )
          attempts.append(AttemptRecord(attempt_number, decision, failed))
          self.ledger.append(
            "operation",
            task.sample_id,
            "failed",
            {
              "task_id": task.task_id,
              "detail": detail,
              "expected_permit_id": permit.permit_id,
              "received_permit_id": result.permit_id,
            },
          )
          return self._report(
            task,
            TaskFinalState.FAILED,
            attempts,
            retries,
            recoveries,
            detail,
            self.samples.samples[task.sample_id].location,
          )
        operation_completed = self.ledger.append(
          "operation",
          task.sample_id,
          result.status.value,
          {
            "task_id": task.task_id,
            "attempt": attempt_number,
            "detail": result.detail,
            "effect": result.effect.value,
            "permit_id": result.permit_id,
            "payload": result.payload,
          },
        )
        if result.effect is SampleEffect.NO_CHANGE:
          # The audited adapter result establishes that this attempt did not alter
          # tracked sample/material state. A later retry-loop cancellation must not
          # be misclassified as an ambiguous actuation from this completed attempt.
          actuation.started = False

        if result.status is OperationStatus.SUCCEEDED:
          if (
            task.success_location != task.expected_location
            and result.effect is not SampleEffect.EXPECTED_CHANGE
          ):
            detail = (
              "adapter contract conflict: a location-changing success did not declare "
              "expected_change"
            )
            self._mark_uncertain(task, detail)
            attempts.append(AttemptRecord(attempt_number, decision, result))
            self.ledger.append(
              "task", task.sample_id, "failed", {"task_id": task.task_id, "detail": detail}
            )
            return self._report(
              task,
              TaskFinalState.FAILED,
              attempts,
              retries,
              recoveries,
              detail,
              self.samples.samples[task.sample_id].location,
            )
          try:
            after = tuple(
              observation.detached()
              for observation in post_evidence(task, attempt_number)
            )
            self._record_observations(task, attempt_number, "postcondition", after)
            self._validate_postcondition_chronology(after, operation_completed.recorded_at)
            postcondition = self._decisions.evaluate(
              f"verify outcome for {task.proposal}",
              postcondition_policy,
              after,
            )
            self._record_decision(
              task,
              attempt_number,
              "postcondition",
              postcondition,
              postcondition_policy,
            )
          except BaseException as exc:
            detail = f"postcondition adapter raised {type(exc).__name__}: {exc}"
            if result.effect is not SampleEffect.NO_CHANGE:
              self._mark_uncertain(task, detail)
            attempts.append(AttemptRecord(attempt_number, decision, result))
            self.ledger.append(
              "task", task.sample_id, "postcondition_error", {"task_id": task.task_id, "detail": detail}
            )
            report = self._report(
              task,
              TaskFinalState.FAILED,
              attempts,
              retries,
              recoveries,
              detail,
              self.samples.samples[task.sample_id].location,
            )
            if not isinstance(exc, Exception):
              actuation.handled = True
              raise
            return report
          attempts.append(AttemptRecord(attempt_number, decision, result, postcondition))
          if not postcondition.permitted:
            detail = (
              "operation returned success but independent postconditions did not establish "
              f"the outcome: {self._decision_detail(postcondition, task)}"
            )
            if result.effect is not SampleEffect.NO_CHANGE:
              self._mark_uncertain(task, detail)
            final = (
              TaskFinalState.STOPPED
              if postcondition.action is DecisionAction.STOP
              else TaskFinalState.ESCALATED
            )
            self.ledger.append(
              "task", task.sample_id, final.value, {"task_id": task.task_id, "detail": detail}
            )
            return self._report(
              task,
              final,
              attempts,
              retries,
              recoveries,
              detail,
              self.samples.samples[task.sample_id].location,
            )
          try:
            self.ledger.assert_valid()
          except ValueError as exc:
            detail = f"run ledger became invalid before provenance advance: {exc}"
            if result.effect is not SampleEffect.NO_CHANGE:
              self._mark_uncertain(task, detail)
            raise
          if not postcondition.is_current():
            detail = "postcondition evidence expired before provenance advance"
            if result.effect is not SampleEffect.NO_CHANGE:
              self._mark_uncertain(task, detail)
            self.ledger.append(
              "task",
              task.sample_id,
              "stopped",
              {"task_id": task.task_id, "detail": detail},
            )
            return self._report(
              task,
              TaskFinalState.STOPPED,
              attempts,
              retries,
              recoveries,
              detail,
              self.samples.samples[task.sample_id].location,
            )
          if self.samples.samples[task.sample_id].location != task.success_location:
            self.samples.move(task.sample_id, task.success_location)
          return self._report(
            task,
            TaskFinalState.SUCCEEDED,
            attempts,
            retries,
            recoveries,
            result.detail,
            task.success_location,
          )
        attempts.append(AttemptRecord(attempt_number, decision, result))
        if result.status is OperationStatus.RETRYABLE and retries < task.max_retries:
          retries += 1
          self._record_control(task, "retry", retries, (result.detail,))
          continue
        if (
          result.status is OperationStatus.RECOVERABLE
          and recover is not None
          and recoveries < task.max_recoveries
        ):
          recoveries += 1
          try:
            recovered, detail = self._run_recovery_for_result(
              task,
              result,
              recover,
              recoveries,
              decision,
            )
          except BaseException as exc:
            if not isinstance(exc, Exception):
              detail = f"recovery control cancelled by {type(exc).__name__}: {exc}"
              self._report(
                task,
                TaskFinalState.ESCALATED,
                attempts,
                retries,
                recoveries,
                detail,
                self.samples.samples[task.sample_id].location,
              )
              actuation.handled = True
              raise
            recovered = False
            detail = f"recovery control failed closed: {type(exc).__name__}: {exc}"
          if not recovered:
            return self._report(
              task,
              TaskFinalState.ESCALATED,
              attempts,
              retries,
              recoveries,
              detail,
              self.samples.samples[task.sample_id].location,
            )
          self._record_control(task, "recover", recoveries, (result.detail,))
          continue

        final = (
          TaskFinalState.FAILED
          if result.status is OperationStatus.FAILED
          else TaskFinalState.ESCALATED
        )
        detail = (
          result.detail
          if final is TaskFinalState.FAILED
          else f"{result.status.value} outcome exhausted its bounded response budget"
        )
        if result.effect is not SampleEffect.NO_CHANGE:
          self._mark_uncertain(task, detail)
        self.ledger.append(
          "task",
          task.sample_id,
          final.value,
          {"task_id": task.task_id, "detail": detail},
        )
        return self._report(
          task,
          final,
          attempts,
          retries,
          recoveries,
          detail,
          self.samples.samples[task.sample_id].location,
        )

  def _binding_error(
    self, task: WorkcellTask, operation: GuardedOperation
  ) -> Optional[str]:
    if self.contracts.approval(task.contract) is None:
      return (
        f"contract {task.operation_id}@{task.contract.version} with hash "
        f"{task.contract.fingerprint()} is not approved by this deployment"
      )
    if not isinstance(operation, GuardedOperation):
      return "operation must be a GuardedOperation binding, not a raw callable"
    if operation.operation_id != task.operation_id:
      return (
        f"adapter operation {operation.operation_id} does not match reviewed "
        f"operation {task.operation_id}"
      )
    if not task.contract.allows_adapter(
      operation.adapter_id,
      operation.adapter_version,
      operation.configuration_hash,
    ):
      return (
        f"adapter {operation.adapter_id}@{operation.adapter_version} with configuration "
        f"{operation.configuration_hash} is not approved by contract "
        f"{task.operation_id}@{task.contract.version}"
      )
    return None

  @contextmanager
  def _leased_custody(
    self,
    lease: ResourceLease,
    task: WorkcellTask,
    attempts: List[AttemptRecord],
    counts: Callable[[], Tuple[int, int]],
  ):
    """Release and finalize the lease while sample custody is still exclusive."""
    entered = False
    try:
      with self.samples.custody(task.sample_id):
        entered = True
        try:
          yield
        finally:
          lease.release()
    except BaseException as exc:
      if not entered:
        detail = f"sample custody acquisition failed: {type(exc).__name__}: {exc}"
        self.ledger.append(
          "task",
          task.sample_id,
          "custody_error",
          {"task_id": task.task_id, "detail": detail},
        )
        retries, recoveries = counts()
        self._report(
          task,
          TaskFinalState.FAILED,
          attempts,
          retries,
          recoveries,
          detail,
          self.samples.samples[task.sample_id].location,
        )
      raise
    finally:
      # Covers cancellation or failure while entering the custody context.
      lease.release()

  @contextmanager
  def _fail_closed_after_start(
    self,
    task: WorkcellTask,
    actuation: _ActuationEnvelope,
    attempts: List[AttemptRecord],
    counts: Callable[[], Tuple[int, int]],
  ):
    """Quarantine any uncaught failure after an adapter may have been invoked."""
    try:
      yield
    except BaseException as exc:
      if actuation.started and not actuation.handled:
        detail = (
          "post-start control failure left physical outcome unconfirmed: "
          f"{type(exc).__name__}: {exc}"
        )
        self._mark_uncertain(task, detail)
        self.ledger.append(
          "operation",
          task.sample_id,
          "failed",
          {
            "task_id": task.task_id,
            "attempt": actuation.attempt,
            "permit_id": actuation.permit_id,
            "detail": detail,
          },
        )
        retries, recoveries = counts()
        self._report(
          task,
          TaskFinalState.FAILED,
          attempts,
          retries,
          recoveries,
          detail,
          self.samples.samples[task.sample_id].location,
        )
        actuation.handled = True
      raise

  def _execution_permit(
    self,
    task: WorkcellTask,
    attempt: int,
    leased_resources: Tuple[str, ...],
    decision: PermissionDecision,
  ) -> ExecutionPermit:
    if decision.expires_at is None or not decision.is_current():
      raise _ExecutionPermitRejected(
        "cannot issue an execution permit from expired or unbounded evidence"
      )
    contract_hash = task.contract.fingerprint()
    basis = (
      f"{self.ledger.run_id}:{task.task_id}:{task.operation_id}:"
      f"{contract_hash}:{attempt}"
    )
    idempotency_key = hashlib.sha256(f"execute:{basis}".encode("utf-8")).hexdigest()
    permit_id = hashlib.sha256(f"permit:{basis}".encode("utf-8")).hexdigest()
    return ExecutionPermit(
      permit_id=permit_id,
      idempotency_key=idempotency_key,
      run_id=self.ledger.run_id,
      task_id=task.task_id,
      operation_id=task.operation_id,
      contract_hash=contract_hash,
      issued_at=_utc_now(),
      expires_at=decision.expires_at,
      attempt=attempt,
      leased_resources=leased_resources,
    )

  def _run_recovery(
    self,
    task: WorkcellTask,
    decision: PermissionDecision,
    recovery: GuardedRecovery,
    reason: str,
    count: int,
  ) -> Tuple[bool, str]:
    if not decision.is_current():
      detail = "precondition evidence expired before recovery adapter invocation"
      self.ledger.append(
        "recovery", task.sample_id, "expired", {"task_id": task.task_id, "detail": detail}
      )
      return False, detail
    ids = {
      result.gate.recovery_id
      for result in decision.results
      if result.action is DecisionAction.RECOVER
    }
    if len(ids) != 1:
      detail = "recovery requires exactly one reviewed recovery_id"
      self.ledger.append(
        "recovery", task.sample_id, "blocked", {"task_id": task.task_id, "detail": detail}
      )
      return False, detail
    return self._execute_recovery(
      task,
      ids.pop(),
      recovery,
      reason,
      count,
      decision,
    )

  def _run_recovery_for_result(
    self,
    task: WorkcellTask,
    result: OperationResult,
    recovery: GuardedRecovery,
    count: int,
    decision: PermissionDecision,
  ) -> Tuple[bool, str]:
    if result.recovery_id is None:
      detail = "recoverable operation result omitted recovery_id"
      self.ledger.append(
        "recovery", task.sample_id, "blocked", {"task_id": task.task_id, "detail": detail}
      )
      return False, detail
    return self._execute_recovery(
      task,
      result.recovery_id,
      recovery,
      result.detail,
      count,
      decision,
    )

  def _execute_recovery(
    self,
    task: WorkcellTask,
    recovery_id: str,
    recovery: GuardedRecovery,
    reason: str,
    count: int,
    decision: PermissionDecision,
  ) -> Tuple[bool, str]:
    self.ledger.assert_valid()
    approved_adapter = task.contract.recovery_adapter(recovery_id)
    if approved_adapter is None:
      detail = f"recovery {recovery_id} is not bound in the reviewed operation contract"
      self.ledger.append(
        "recovery", task.sample_id, "blocked", {"task_id": task.task_id, "detail": detail}
      )
      return False, detail
    if recovery.recovery_id != recovery_id or not approved_adapter.matches(
      recovery.adapter_id,
      recovery.adapter_version,
      recovery.configuration_hash,
    ):
      detail = (
        f"recovery binding mismatch: contract requires {recovery_id} via "
        f"{approved_adapter.adapter_id}@{approved_adapter.adapter_version} "
        f"({approved_adapter.configuration_hash}), got {recovery.recovery_id} via "
        f"{recovery.adapter_id}@{recovery.adapter_version} "
        f"({recovery.configuration_hash})"
      )
      self.ledger.append(
        "recovery", task.sample_id, "blocked", {"task_id": task.task_id, "detail": detail}
      )
      return False, detail

    contract_hash = task.contract.fingerprint()
    if self.contracts.approval(task.contract) is None:
      detail = "operation contract approval changed before recovery invocation"
      self.ledger.append(
        "recovery", task.sample_id, "blocked", {"task_id": task.task_id, "detail": detail}
      )
      return False, detail
    if decision.expires_at is None or not decision.is_current():
      detail = "permission evidence expired before recovery invocation"
      self.ledger.append(
        "recovery", task.sample_id, "expired", {"task_id": task.task_id, "detail": detail}
      )
      return False, detail
    basis = f"{self.ledger.run_id}:{task.task_id}:{recovery_id}:{contract_hash}:{count}"
    permit = RecoveryPermit(
      permit_id=hashlib.sha256(f"permit:{basis}".encode("utf-8")).hexdigest(),
      idempotency_key=hashlib.sha256(f"recover:{basis}".encode("utf-8")).hexdigest(),
      run_id=self.ledger.run_id,
      task_id=task.task_id,
      recovery_id=recovery_id,
      contract_hash=contract_hash,
      issued_at=_utc_now(),
      expires_at=decision.expires_at,
      count=count,
    )
    self.ledger.append(
      "recovery",
      task.sample_id,
      "start",
      {
        "task_id": task.task_id,
        "recovery_id": recovery_id,
        "adapter_id": recovery.adapter_id,
        "adapter_version": recovery.adapter_version,
        "adapter_configuration_hash": recovery.configuration_hash,
        "permit_id": permit.permit_id,
        "idempotency_key": permit.idempotency_key,
        "permit_issued_at": permit.issued_at,
        "permit_expires_at": permit.expires_at,
        "reason": reason,
        "count": count,
      },
    )
    if not permit.is_current():
      detail = "recovery permit expired before the adapter call"
      self.ledger.append(
        "recovery",
        task.sample_id,
        "expired",
        {"task_id": task.task_id, "detail": detail, "permit_id": permit.permit_id},
      )
      return False, detail
    try:
      result = recovery.execute(task, reason, count, permit)
    except BaseException as exc:
      detail = f"recovery adapter raised {type(exc).__name__}: {exc}"
      self._mark_uncertain(task, detail)
      self.ledger.append(
        "recovery", task.sample_id, "failed", {"task_id": task.task_id, "detail": detail}
      )
      if not isinstance(exc, Exception):
        raise
      return False, detail
    if not isinstance(result, RecoveryResult) or result.permit_id != permit.permit_id:
      detail = "recovery returned an untyped result or wrong permit"
      self._mark_uncertain(task, detail)
      self.ledger.append(
        "recovery", task.sample_id, "failed", {"task_id": task.task_id, "detail": detail}
      )
      return False, detail
    try:
      result = RecoveryResult(
        result.status,
        result.detail,
        result.effect,
        result.permit_id,
      )
    except (TypeError, ValueError) as exc:
      detail = f"recovery returned an invalid result: {type(exc).__name__}: {exc}"
      self._mark_uncertain(task, detail)
      self.ledger.append(
        "recovery", task.sample_id, "failed", {"task_id": task.task_id, "detail": detail}
      )
      return False, detail
    self.ledger.append(
      "recovery",
      task.sample_id,
      result.status.value,
      {
        "task_id": task.task_id,
        "recovery_id": recovery_id,
        "permit_id": result.permit_id,
        "detail": result.detail,
        "effect": result.effect.value,
      },
    )
    if result.status is RecoveryStatus.SUCCEEDED and result.effect is SampleEffect.NO_CHANGE:
      return True, result.detail
    if result.effect is not SampleEffect.NO_CHANGE:
      self._mark_uncertain(task, result.detail)
    return False, result.detail

  def _sample_state(self, task: WorkcellTask):
    if task.sample_id not in self.samples.samples:
      raise KeyError(f"task {task.task_id} names unknown sample {task.sample_id}")
    state = self.samples.samples[task.sample_id]
    if state.status != "available":
      raise ValueError(f"task {task.task_id} sample {task.sample_id} is {state.status}")
    if state.location != task.expected_location:
      raise ValueError(
        f"task {task.task_id} expects {task.sample_id} at {task.expected_location}, "
        f"but provenance says {state.location}"
      )
    return state

  def _record_observations(
    self,
    task: WorkcellTask,
    attempt: int,
    phase: str,
    observations: Tuple[Observation, ...],
  ):
    for observation in observations:
      self.ledger.append(
        "observation",
        observation.subject,
        "record",
        {
          "task_id": task.task_id,
          "attempt": attempt,
          "phase": phase,
          "metric": observation.metric,
          "value": observation.json_value(),
          "kind": observation.kind.value,
          "source": observation.source,
          "captured_at": observation.captured_at,
          "evidence_ref": observation.evidence_ref,
        },
      )

  def _validate_postcondition_chronology(
    self, observations: Tuple[Observation, ...], operation_completed_at: str
  ):
    normalized = (
      f"{operation_completed_at[:-1]}+00:00"
      if operation_completed_at.endswith("Z")
      else operation_completed_at
    )
    completed = datetime.fromisoformat(normalized)
    early = [
      observation.evidence_ref
      for observation in observations
      if observation.captured_datetime < completed
    ]
    if early:
      raise ValueError(
        "postcondition evidence predates operation completion: "
        + ", ".join(sorted(early))
      )

  def _record_decision(
    self,
    task: WorkcellTask,
    attempt: int,
    phase: str,
    decision: PermissionDecision,
    bound_policy: ExpertPolicy,
  ):
    contract_policy = task.policy if phase == "precondition" else task.postcondition_policy
    self.ledger.append(
      "decision",
      task.sample_id,
      decision.action.value,
      {
        "task_id": task.task_id,
        "attempt": attempt,
        "phase": phase,
        "proposal": decision.proposal,
        "policy": f"{decision.policy_name}@{decision.policy_version}",
        "contract_policy_hash": contract_policy.fingerprint(),
        "bound_policy_hash": bound_policy.fingerprint(),
        "sample_subject_binding": {"$sample": task.sample_id},
        "evaluated_at": decision.evaluated_at,
        "expires_at": decision.expires_at,
        "permitted": decision.permitted,
        "gates": [
          {
            "gate_id": result.gate.gate_id,
            "status": result.status.value,
            "action": result.action.value,
            "reason": result.reason,
            "recovery_id": result.gate.recovery_id,
          }
          for result in decision.results
        ],
      },
    )

  def _mark_uncertain(self, task: WorkcellTask, detail: str):
    state = self.samples.samples[task.sample_id]
    if state.status == "available":
      self.samples.mark_uncertain(
        task.sample_id,
        detail,
        possible_location=task.success_location,
      )

  def _record_control(
    self, task: WorkcellTask, action: str, count: int, reasons: Tuple[str, ...]
  ):
    self.ledger.append(
      "control",
      task.sample_id,
      action,
      {"task_id": task.task_id, "count": count, "reasons": list(reasons)},
    )

  def _decision_detail(self, decision: PermissionDecision, task: WorkcellTask) -> str:
    reasons = "; ".join(
      result.reason for result in decision.results if result.action is not DecisionAction.CONTINUE
    )
    if decision.action is DecisionAction.RETRY:
      return f"retry budget exhausted for {task.task_id}: {reasons}"
    if decision.action is DecisionAction.RECOVER:
      return f"recovery unavailable or exhausted for {task.task_id}: {reasons}"
    return reasons or f"policy returned {decision.action.value}"

  def _report(
    self,
    task: WorkcellTask,
    final_state: TaskFinalState,
    attempts: List[AttemptRecord],
    retries: int,
    recoveries: int,
    detail: str,
    final_location: str,
  ) -> OrchestrationReport:
    def append_terminal():
      self.ledger.append(
        "task_terminal",
        task.sample_id,
        final_state.value,
        {
          "task_id": task.task_id,
          "detail": detail,
          "final_location": final_location,
          "retries_used": retries,
          "recoveries_used": recoveries,
        },
      )

    if not self.resources.defer_until_release(
      self.ledger.run_id,
      task.task_id,
      append_terminal,
    ):
      append_terminal()
    self.ledger.assert_valid()
    return OrchestrationReport(
      task,
      final_state,
      tuple(attempts),
      retries,
      recoveries,
      detail,
      final_location,
      self.ledger,
    )
