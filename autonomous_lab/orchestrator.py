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

import json
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .intelligence import (
  DecisionAction,
  DecisionEngine,
  ExpertPolicy,
  Observation,
  PermissionDecision,
)
from .provenance import RunLedger, SampleTracker


class ResourceBusy(RuntimeError):
  """Raised when a task cannot lease its complete resource set."""

  def __init__(self, conflicts: Dict[str, str]):
    self.conflicts = dict(conflicts)
    detail = ", ".join(f"{resource} owned by {owner}" for resource, owner in conflicts.items())
    super().__init__(f"workcell resources are busy: {detail}")


class OperationStatus(str, Enum):
  SUCCEEDED = "succeeded"
  RETRYABLE = "retryable"
  RECOVERABLE = "recoverable"
  FAILED = "failed"


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
  payload: Dict[str, Any] = field(default_factory=dict)

  def __post_init__(self):
    if not self.detail:
      raise ValueError("operation result detail must not be empty")
    try:
      clean = json.loads(json.dumps(self.payload, sort_keys=True, ensure_ascii=True))
    except (TypeError, ValueError) as exc:
      raise ValueError("operation result payload must be JSON serializable") from exc
    object.__setattr__(self, "payload", clean)


@dataclass(frozen=True)
class WorkcellTask:
  """One proposed unit of work across one or more exclusive resources."""

  task_id: str
  proposal: str
  sample_id: str
  expected_location: str
  success_location: str
  resources: Tuple[str, ...]
  policy: ExpertPolicy
  max_retries: int = 0
  max_recoveries: int = 0

  def __post_init__(self):
    for name in (
      "task_id",
      "proposal",
      "sample_id",
      "expected_location",
      "success_location",
    ):
      if not getattr(self, name):
        raise ValueError(f"task {name} must not be empty")
    if not self.resources or any(not resource for resource in self.resources):
      raise ValueError(f"task {self.task_id} needs named resources")
    if len(self.resources) != len(set(self.resources)):
      raise ValueError(f"task {self.task_id} contains duplicate resources")
    if self.max_retries < 0 or self.max_recoveries < 0:
      raise ValueError(f"task {self.task_id} budgets must not be negative")


@dataclass(frozen=True)
class AttemptRecord:
  number: int
  decision: PermissionDecision
  operation: Optional[OperationResult]


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
      lines.append(
        f"  attempt {attempt.number}: decision={attempt.decision.action.value}; "
        f"operation={operation}"
      )
    return "\n".join(lines)


class ResourceLease:
  def __init__(self, manager: "ResourceManager", owner: str, resources: Tuple[str, ...]):
    self._manager = manager
    self.owner = owner
    self.resources = resources
    self.released = False
    self._release_callbacks: List[Callable[[str, Tuple[str, ...]], None]] = []

  def on_release(self, callback: Callable[[str, Tuple[str, ...]], None]):
    self._release_callbacks.append(callback)

  def release(self):
    if self.released:
      return
    self._manager._release(self.owner, self.resources)
    self.released = True
    for callback in self._release_callbacks:
      callback(self.owner, self.resources)

  def __enter__(self) -> "ResourceLease":
    return self

  def __exit__(self, exc_type, exc, traceback):
    self.release()


class ResourceManager:
  """Atomically enforce one active owner per resource inside this process.

  A production workcell still needs a durable inter-process or distributed lease so a
  second controller process cannot bypass this in-memory manager.
  """

  def __init__(self):
    self._owners: Dict[str, str] = {}
    self._lock = Lock()

  def acquire(self, owner: str, resources: Iterable[str]) -> ResourceLease:
    requested = tuple(sorted(resources))
    if not owner or not requested or any(not resource for resource in requested):
      raise ValueError("resource acquisition needs an owner and named resources")
    if len(requested) != len(set(requested)):
      raise ValueError("resource acquisition contains duplicates")
    with self._lock:
      conflicts = {
        resource: self._owners[resource]
        for resource in requested
        if resource in self._owners and self._owners[resource] != owner
      }
      if conflicts:
        raise ResourceBusy(conflicts)
      if any(self._owners.get(resource) == owner for resource in requested):
        raise ValueError(f"owner {owner} already holds one of the requested resources")
      for resource in requested:
        self._owners[resource] = owner
    return ResourceLease(self, owner, requested)

  def owner(self, resource: str) -> Optional[str]:
    with self._lock:
      return self._owners.get(resource)

  def snapshot(self) -> Dict[str, str]:
    with self._lock:
      return dict(self._owners)

  def _release(self, owner: str, resources: Tuple[str, ...]):
    with self._lock:
      for resource in resources:
        if self._owners.get(resource) != owner:
          raise RuntimeError(f"{owner} cannot release {resource}; it does not own it")
      for resource in resources:
        del self._owners[resource]


EvidenceProvider = Callable[[WorkcellTask, int], Iterable[Observation]]
Operation = Callable[[WorkcellTask, int], OperationResult]
RecoveryHandler = Callable[[WorkcellTask, str, int], None]


class WorkcellOrchestrator:
  """Run one task only as far as evidence, budgets, and resource state permit."""

  def __init__(
    self,
    ledger: RunLedger,
    samples: SampleTracker,
    resources: Optional[ResourceManager] = None,
    decisions: Optional[DecisionEngine] = None,
  ):
    if samples.ledger is not ledger:
      raise ValueError("sample tracker and orchestrator must share the same run ledger")
    self.ledger = ledger
    self.samples = samples
    self.resources = resources or ResourceManager()
    self.decisions = decisions or DecisionEngine()

  def run(
    self,
    task: WorkcellTask,
    evidence: EvidenceProvider,
    operation: Operation,
    recover: Optional[RecoveryHandler] = None,
  ) -> OrchestrationReport:
    state = self._sample_state(task)
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
        "policy": f"{task.policy.name}@{task.policy.version}",
        "max_retries": task.max_retries,
        "max_recoveries": task.max_recoveries,
      },
    )
    try:
      lease = self.resources.acquire(task.task_id, task.resources)
    except ResourceBusy as exc:
      self.ledger.append(
        "resource",
        task.task_id,
        "blocked",
        {"conflicts": exc.conflicts},
      )
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
    lease.on_release(
      lambda owner, leased: self.ledger.append(
        "resource", owner, "release", {"resources": list(leased)}
      )
    )
    with lease:
      self.ledger.append(
        "resource", task.task_id, "acquire", {"resources": list(lease.resources)}
      )
      attempt_number = 0
      while True:
        attempt_number += 1
        try:
          observations = tuple(evidence(task, attempt_number))
          self._record_observations(task, attempt_number, observations)
          decision = self.decisions.evaluate(task.proposal, task.policy, observations)
          self._record_decision(task, attempt_number, decision)
        except Exception as exc:
          detail = f"evidence or decision adapter raised {type(exc).__name__}: {exc}"
          self.ledger.append(
            "task", task.sample_id, "adapter_error", {"task_id": task.task_id, "detail": detail}
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
              recover(task, "; ".join(decision.recoveries), recoveries)
            except Exception as exc:
              detail = f"recovery adapter raised {type(exc).__name__}: {exc}"
              self.ledger.append(
                "recovery",
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

        try:
          result = operation(task, attempt_number)
        except Exception as exc:
          detail = f"operation adapter raised {type(exc).__name__}: {exc}"
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
              OperationResult(OperationStatus.FAILED, detail),
            )
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
        if not isinstance(result, OperationResult):
          detail = "operation adapter returned an untyped result instead of OperationResult"
          failed = OperationResult(OperationStatus.FAILED, detail)
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
        attempts.append(AttemptRecord(attempt_number, decision, result))
        self.ledger.append(
          "operation",
          task.sample_id,
          result.status.value,
          {
            "task_id": task.task_id,
            "attempt": attempt_number,
            "detail": result.detail,
            "payload": result.payload,
          },
        )

        if result.status is OperationStatus.SUCCEEDED:
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
            recover(task, result.detail, recoveries)
          except Exception as exc:
            detail = f"recovery adapter raised {type(exc).__name__}: {exc}"
            self.ledger.append(
              "recovery",
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
    self, task: WorkcellTask, attempt: int, observations: Tuple[Observation, ...]
  ):
    for observation in observations:
      self.ledger.append(
        "observation",
        observation.subject,
        "record",
        {
          "task_id": task.task_id,
          "attempt": attempt,
          "metric": observation.metric,
          "value": observation.value,
          "kind": observation.kind.value,
          "source": observation.source,
          "captured_at": observation.captured_at,
          "evidence_ref": observation.evidence_ref,
        },
      )

  def _record_decision(
    self, task: WorkcellTask, attempt: int, decision: PermissionDecision
  ):
    self.ledger.append(
      "decision",
      task.sample_id,
      decision.action.value,
      {
        "task_id": task.task_id,
        "attempt": attempt,
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
      },
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
