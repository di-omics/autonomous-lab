"""Workcell orchestration refuses unsafe concurrency and unpermitted operations."""

from __future__ import annotations

import pytest

from autonomous_lab.intelligence import (
  Comparator,
  DecisionAction,
  EvidenceGate,
  EvidenceKind,
  ExpertPolicy,
  Observation,
)
from autonomous_lab.orchestration_demo import run_orchestration_demo
from autonomous_lab.orchestrator import (
  OperationResult,
  OperationStatus,
  ResourceBusy,
  ResourceManager,
  TaskFinalState,
  WorkcellOrchestrator,
  WorkcellTask,
)
from autonomous_lab.provenance import RunLedger, SampleTracker


def _policy(action=DecisionAction.RECOVER):
  return ExpertPolicy(
    "move_plate",
    "1.0",
    (
      EvidenceGate(
        "pose",
        "pose_ok",
        Comparator.EQUAL,
        (EvidenceKind.VISION,),
        action,
        "re-home and reacquire pose",
        subject="plate-1",
        expected=True,
      ),
    ),
    "workcell owner",
  )


def _observation(value=True):
  return Observation(
    "pose_ok",
    value,
    EvidenceKind.VISION,
    "plate-1",
    "synthetic camera",
    "2026-01-01T00:00:00Z",
    "synthetic://camera/1",
  )


def _fixture(max_retries=0, max_recoveries=0, policy=None):
  ledger = RunLedger("test-run")
  samples = SampleTracker(ledger)
  samples.register("plate-1", "reader", recorded_at="1")
  resources = ResourceManager()
  orchestrator = WorkcellOrchestrator(ledger, samples, resources)
  task = WorkcellTask(
    "move-1",
    "move plate to staging",
    "plate-1",
    "reader",
    "staging",
    ("camera", "robot"),
    policy or _policy(),
    max_retries=max_retries,
    max_recoveries=max_recoveries,
  )
  return ledger, samples, resources, orchestrator, task


def _success(_task, _attempt):
  return OperationResult(OperationStatus.SUCCEEDED, "synthetic move complete")


def test_resource_acquisition_is_atomic():
  resources = ResourceManager()
  lease = resources.acquire("task-a", ("robot",))
  try:
    with pytest.raises(ResourceBusy):
      resources.acquire("task-b", ("camera", "robot"))
    assert resources.owner("camera") is None
    assert resources.owner("robot") == "task-a"
  finally:
    lease.release()


def test_resource_context_releases_every_resource():
  resources = ResourceManager()
  with resources.acquire("task", ("robot", "camera")):
    assert resources.snapshot() == {"camera": "task", "robot": "task"}
  assert resources.snapshot() == {}


def test_task_refuses_duplicate_resources():
  with pytest.raises(ValueError, match="duplicate resources"):
    WorkcellTask("t", "p", "s", "a", "b", ("robot", "robot"), _policy())


def test_success_requires_permission_moves_sample_and_releases_resources():
  ledger, samples, resources, orchestrator, task = _fixture()
  report = orchestrator.run(task, lambda _task, _attempt: (_observation(),), _success)
  assert report.final_state is TaskFinalState.SUCCEEDED
  assert samples.samples["plate-1"].location == "staging"
  assert resources.snapshot() == {}
  assert ledger.verify()[0]
  assert any(event.event_type == "decision" for event in ledger.events)
  assert any(event.event_type == "resource" and event.action == "release" for event in ledger.events)
  assert any(event.event_type == "task_terminal" for event in ledger.events)


def test_success_can_leave_a_sample_at_the_same_station():
  _ledger, samples, _resources, orchestrator, task = _fixture()
  in_place = WorkcellTask(
    task.task_id,
    "read plate in place",
    task.sample_id,
    task.expected_location,
    task.expected_location,
    task.resources,
    task.policy,
  )
  report = orchestrator.run(
    in_place, lambda _task, _attempt: (_observation(),), _success
  )
  assert report.final_state is TaskFinalState.SUCCEEDED
  assert samples.samples["plate-1"].location == "reader"


def test_missing_evidence_stops_before_operation():
  _ledger, samples, _resources, orchestrator, task = _fixture()
  calls = []

  def operation(_task, _attempt):
    calls.append("called")
    return _success(_task, _attempt)

  report = orchestrator.run(task, lambda _task, _attempt: (), operation)
  assert report.final_state is TaskFinalState.STOPPED
  assert calls == []
  assert samples.samples["plate-1"].location == "reader"


def test_provenance_location_mismatch_is_refused_before_leasing():
  _ledger, _samples, resources, orchestrator, task = _fixture()
  bad = WorkcellTask(
    task.task_id,
    task.proposal,
    task.sample_id,
    "freezer",
    task.success_location,
    task.resources,
    task.policy,
  )
  with pytest.raises(ValueError, match="provenance says reader"):
    orchestrator.run(bad, lambda _task, _attempt: (_observation(),), _success)
  assert resources.snapshot() == {}


def test_retryable_driver_result_is_bounded_then_succeeds():
  _ledger, _samples, _resources, orchestrator, task = _fixture(max_retries=1)

  def operation(_task, attempt):
    if attempt == 1:
      return OperationResult(OperationStatus.RETRYABLE, "controller busy")
    return _success(_task, attempt)

  report = orchestrator.run(task, lambda _task, _attempt: (_observation(),), operation)
  assert report.final_state is TaskFinalState.SUCCEEDED
  assert report.retries_used == 1
  assert len(report.attempts) == 2


def test_exhausted_retry_escalates_without_moving_sample():
  _ledger, samples, _resources, orchestrator, task = _fixture(max_retries=1)
  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(),),
    lambda _task, _attempt: OperationResult(OperationStatus.RETRYABLE, "still busy"),
  )
  assert report.final_state is TaskFinalState.ESCALATED
  assert report.retries_used == 1
  assert samples.samples["plate-1"].location == "reader"


def test_policy_recovery_reacquires_evidence_before_operation():
  _ledger, _samples, _resources, orchestrator, task = _fixture(max_recoveries=1)
  state = {"aligned": False}
  operations = []

  def evidence(_task, _attempt):
    return (_observation(state["aligned"]),)

  def recover(_task, _reason, _count):
    state["aligned"] = True

  def operation(_task, _attempt):
    operations.append("called")
    return _success(_task, _attempt)

  report = orchestrator.run(task, evidence, operation, recover)
  assert report.final_state is TaskFinalState.SUCCEEDED
  assert report.recoveries_used == 1
  assert len(report.attempts) == 2
  assert operations == ["called"]


def test_unavailable_recovery_escalates_and_never_calls_operation():
  _ledger, _samples, _resources, orchestrator, task = _fixture(max_recoveries=1)
  calls = []
  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(False),),
    lambda _task, _attempt: calls.append("called"),
  )
  assert report.final_state is TaskFinalState.ESCALATED
  assert calls == []


def test_recoverable_driver_result_runs_handler_then_succeeds():
  _ledger, _samples, _resources, orchestrator, task = _fixture(max_recoveries=1)
  state = {"recovered": False}

  def operation(_task, _attempt):
    if not state["recovered"]:
      return OperationResult(OperationStatus.RECOVERABLE, "gripper pose drift")
    return _success(_task, _attempt)

  def recover(_task, _reason, _count):
    state["recovered"] = True

  report = orchestrator.run(
    task, lambda _task, _attempt: (_observation(),), operation, recover
  )
  assert report.final_state is TaskFinalState.SUCCEEDED
  assert report.recoveries_used == 1


def test_fatal_driver_result_fails_without_moving_sample():
  _ledger, samples, _resources, orchestrator, task = _fixture()
  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(),),
    lambda _task, _attempt: OperationResult(OperationStatus.FAILED, "calibration fault"),
  )
  assert report.final_state is TaskFinalState.FAILED
  assert samples.samples["plate-1"].location == "reader"


def test_unexpected_adapter_exception_is_audited_and_releases_resources():
  ledger, _samples, resources, orchestrator, task = _fixture()

  def operation(_task, _attempt):
    raise RuntimeError("synthetic adapter crash")

  report = orchestrator.run(task, lambda _task, _attempt: (_observation(),), operation)
  assert report.final_state is TaskFinalState.FAILED
  assert "adapter raised RuntimeError" in report.detail
  assert resources.snapshot() == {}
  assert ledger.verify()[0]


def test_untyped_adapter_result_fails_closed():
  _ledger, _samples, _resources, orchestrator, task = _fixture()
  report = orchestrator.run(
    task, lambda _task, _attempt: (_observation(),), lambda _task, _attempt: {"ok": True}
  )
  assert report.final_state is TaskFinalState.FAILED
  assert "untyped result" in report.detail


def test_operation_result_refuses_an_unserializable_payload():
  with pytest.raises(ValueError, match="JSON serializable"):
    OperationResult(OperationStatus.SUCCEEDED, "bad payload", {"values": {1, 2}})


def test_busy_resource_blocks_before_evidence_or_operation():
  _ledger, samples, resources, orchestrator, task = _fixture()
  blocker = resources.acquire("other-task", ("robot",))
  calls = []
  try:
    report = orchestrator.run(
      task,
      lambda _task, _attempt: calls.append("evidence"),
      lambda _task, _attempt: calls.append("operation"),
    )
  finally:
    blocker.release()
  assert report.final_state is TaskFinalState.BLOCKED
  assert calls == []
  assert samples.samples["plate-1"].location == "reader"


@pytest.mark.parametrize(
  "scenario, final_state, attempts, retries, recoveries",
  [
    ("pass", TaskFinalState.SUCCEEDED, 1, 0, 0),
    ("transient_retry", TaskFinalState.SUCCEEDED, 2, 1, 0),
    ("vision_recovery", TaskFinalState.SUCCEEDED, 2, 0, 1),
    ("resource_busy", TaskFinalState.BLOCKED, 0, 0, 0),
    ("fatal_driver_error", TaskFinalState.FAILED, 1, 0, 0),
  ],
)
def test_orchestration_demo_scenarios(
  scenario, final_state, attempts, retries, recoveries
):
  report = run_orchestration_demo(scenario)
  assert report.final_state is final_state
  assert len(report.attempts) == attempts
  assert report.retries_used == retries
  assert report.recoveries_used == recoveries
  assert report.ledger.verify()[0]
