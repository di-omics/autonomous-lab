"""Workcell orchestration fails closed across policy, adapters, samples, and recovery."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from itertools import count
from threading import Event, Thread
from time import sleep

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
  AdapterBinding,
  ContractApproval,
  ContractRegistry,
  GuardedOperation,
  GuardedRecovery,
  OperationContract,
  OperationResult,
  OperationStatus,
  SampleEffect,
  RecoveryResult,
  RecoveryBinding,
  RecoveryStatus,
  ResourceBusy,
  ResourceManager,
  TaskFinalState,
  WorkcellOrchestrator,
  WorkcellTask,
)
from autonomous_lab.provenance import RunLedger, SampleTracker


_TEST_RUN_IDS = count()


def _now() -> str:
  return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _policy(
  action=DecisionAction.RECOVER,
  max_age_seconds=30,
  expected=True,
):
  return ExpertPolicy(
    "move_plate_preconditions",
    "1.0",
    (
      EvidenceGate(
        "pose",
        "pose_ok",
        Comparator.EQUAL,
        (EvidenceKind.VISION,),
        action,
        "rehome_pose",
        "re-home and reacquire pose",
        subject="$sample",
        expected=expected,
        max_age_seconds=max_age_seconds,
        max_future_skew_seconds=2,
      ),
    ),
    "workcell owner",
  )


def _post_policy(max_age_seconds=30):
  return ExpertPolicy(
    "move_plate_postconditions",
    "1.0",
    (
      EvidenceGate(
        "destination",
        "at_destination",
        Comparator.EQUAL,
        (EvidenceKind.VISION,),
        DecisionAction.STOP,
        "reconcile_location",
        "quarantine and reconcile sample location",
        subject="$sample",
        expected=True,
        max_age_seconds=max_age_seconds,
        max_future_skew_seconds=2,
      ),
    ),
    "workcell owner",
  )


def _contract(
  operation_id="move_plate",
  expected="reader",
  success="staging",
  resources=("camera", "robot"),
  policy=None,
  post_policy=None,
  max_retries=0,
  max_recoveries=0,
):
  return OperationContract(
    operation_id,
    "1.0",
    expected,
    success,
    tuple(resources),
    policy or _policy(),
    post_policy or _post_policy(),
    max_retries,
    max_recoveries,
    (AdapterBinding("test-adapter", "1.0", "sha256:test-configuration"),),
    (
      RecoveryBinding(
        "rehome_pose",
        AdapterBinding("test-adapter", "1.0", "sha256:test-configuration"),
      ),
    ),
  )


def _observation(value=True):
  return Observation(
    "pose_ok",
    value,
    EvidenceKind.VISION,
    "plate-1",
    "synthetic camera",
    _now(),
    "synthetic://camera/precondition",
  )


def _post_observation(value=True):
  return Observation(
    "at_destination",
    value,
    EvidenceKind.VISION,
    "plate-1",
    "synthetic camera",
    _now(),
    "synthetic://camera/postcondition",
  )


def _guard(
  execute,
  operation_id="move_plate",
  adapter_id="test-adapter",
  adapter_version="1.0",
  configuration_hash="sha256:test-configuration",
):
  return GuardedOperation(
    operation_id,
    adapter_id,
    adapter_version,
    configuration_hash,
    execute,
  )


def _registry(*contracts):
  return ContractRegistry(
    tuple(
      ContractApproval(
        contract,
        "test workcell owner",
        f"test://approval/{contract.operation_id}/{contract.version}",
      )
      for contract in contracts
    )
  )


def _recovery(
  execute,
  recovery_id="rehome_pose",
  adapter_id="test-adapter",
  adapter_version="1.0",
  configuration_hash="sha256:test-configuration",
):
  return GuardedRecovery(
    recovery_id,
    adapter_id,
    adapter_version,
    configuration_hash,
    execute,
  )


def _fixture(max_retries=0, max_recoveries=0, contract=None):
  ledger = RunLedger(f"test-run-{next(_TEST_RUN_IDS)}")
  samples = SampleTracker(ledger)
  samples.register("plate-1", "reader", recorded_at="2026-01-01T00:00:00Z")
  resources = ResourceManager()
  selected_contract = contract or _contract(
    max_retries=max_retries,
    max_recoveries=max_recoveries,
  )
  orchestrator = WorkcellOrchestrator(
    ledger,
    samples,
    resources,
    contracts=_registry(selected_contract),
  )
  task = WorkcellTask(
    "move-1",
    "move plate to staging",
    "plate-1",
    selected_contract,
  )
  return ledger, samples, resources, orchestrator, task


def _success(_task, _attempt, permit):
  return OperationResult(
    OperationStatus.SUCCEEDED,
    "synthetic move complete",
    SampleEffect.EXPECTED_CHANGE,
    permit.permit_id,
  )


def _post(_task, _attempt):
  return (_post_observation(),)


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


def test_release_audit_is_serialized_before_next_owner_acquires():
  class BlockingReleaseLedger(RunLedger):
    def append(self, event_type, subject, action, payload=None, recorded_at=None):
      if event_type == "resource" and action == "release":
        callback_entered.set()
        assert allow_release_record.wait(5)
      return super().append(event_type, subject, action, payload, recorded_at)

  callback_entered = Event()
  allow_release_record = Event()
  ledger = BlockingReleaseLedger("serialized-resource-release")
  resources = ResourceManager()
  first = resources.acquire("task-a", ("robot",), ledger)
  second_started = Event()

  def acquire_second():
    second_started.set()
    return resources.acquire("task-b", ("robot",), ledger)

  with ThreadPoolExecutor(max_workers=2) as pool:
    releasing = pool.submit(first.release)
    assert callback_entered.wait(5)
    acquiring = pool.submit(acquire_second)
    assert second_started.wait(5)
    assert not acquiring.done()
    allow_release_record.set()
    releasing.result(timeout=5)
    second = acquiring.result(timeout=5)

  transitions = [
    (event.subject, event.action)
    for event in ledger.events
    if event.event_type == "resource"
  ]
  assert transitions == [
    ("task-a", "acquire"),
    ("task-a", "release"),
    ("task-b", "acquire"),
  ]
  second.release()


def test_fresh_resource_managers_share_the_default_process_namespace():
  first_ledger = RunLedger("resource-run-a")
  second_ledger = RunLedger("resource-run-b")
  first_manager = ResourceManager()
  second_manager = ResourceManager()
  lease = first_manager.acquire("task-1", ("robot",), first_ledger)
  try:
    with pytest.raises(ResourceBusy):
      second_manager.acquire("task-1", ("robot",), second_ledger)
    conflict = next(
      event
      for event in second_ledger.events
      if event.event_type == "resource" and event.action == "blocked"
    ).payload["conflicts"]["robot"]
    assert conflict["run_id"] == "resource-run-a"
    assert conflict["task_id"] == "task-1"
    assert conflict["workcell_namespace"] == "process-default"
  finally:
    lease.release()


def test_stale_lease_cannot_release_a_new_generation_for_the_same_owner():
  resources = ResourceManager("lease-generation-regression")
  first = resources.acquire("task", ("robot",))
  first.release()
  second = resources.acquire("task", ("robot",))
  first.release()
  assert resources.owner("robot") == "task"
  second.release()


def test_workcell_and_ledger_identifiers_must_be_nonempty_strings():
  contract = _contract()
  with pytest.raises(ValueError, match="task task_id"):
    WorkcellTask(1, "move", "plate-1", contract)
  with pytest.raises(ValueError, match="task_id"):
    RunLedger("typed-ids").claim_task_id(1)
  with pytest.raises(ValueError, match="owner"):
    ResourceManager("typed-ids").acquire(1, ("robot",))


def test_contract_refuses_duplicate_or_reserved_resources():
  with pytest.raises(ValueError, match="duplicate resources"):
    _contract(resources=("robot", "robot"))
  with pytest.raises(ValueError, match="reserved"):
    _contract(resources=("sample:plate-1",))


@pytest.mark.parametrize("value", [-1, True, 1.5, float("inf"), 11])
def test_contract_binds_plain_integer_response_budgets_with_a_hard_cap(value):
  with pytest.raises(ValueError, match="integer from 0 to 10"):
    _contract(max_retries=value)


def test_contract_normalizes_collections_and_approval_pins_the_original_hash():
  resources = ["camera", "robot"]
  adapters = [AdapterBinding("test-adapter", "1.0", "sha256:test-configuration")]
  recoveries = [
    RecoveryBinding(
      "rehome_pose",
      AdapterBinding("test-adapter", "1.0", "sha256:test-configuration"),
    )
  ]
  contract = OperationContract(
    "move_plate",
    "1.0",
    "reader",
    "staging",
    resources,
    _policy(),
    _post_policy(),
    0,
    0,
    adapters,
    recoveries,
  )
  approval = ContractApproval(contract, "owner", "test://approval")
  registry = ContractRegistry((approval,))
  original_hash = contract.fingerprint()

  resources.append("unreviewed-device")
  adapters.append(AdapterBinding("other", "1.0", "sha256:other"))
  recoveries.clear()

  assert contract.required_resources == ("camera", "robot")
  assert contract.fingerprint() == original_hash
  assert registry.approval(contract) is approval


def test_policy_detaches_nested_expected_value_before_approval():
  mutable_expected = {"station": "staging"}
  postconditions = ExpertPolicy(
    "mutable_postcondition",
    "1.0",
    (
      EvidenceGate(
        "destination",
        "destination",
        Comparator.EQUAL,
        (EvidenceKind.VISION,),
        DecisionAction.STOP,
        "reconcile_location",
        "reconcile sample location",
          subject="$sample",
        expected=mutable_expected,
        max_age_seconds=30,
      ),
    ),
    "owner",
  )
  contract = OperationContract(
    "move_plate",
    "1.0",
    "reader",
    "staging",
    ("camera", "robot"),
    _policy(),
    postconditions,
    0,
    0,
    (AdapterBinding("test-adapter", "1.0", "sha256:test-configuration"),),
    (
      RecoveryBinding(
        "rehome_pose",
        AdapterBinding("test-adapter", "1.0", "sha256:test-configuration"),
      ),
    ),
  )
  registry = _registry(contract)
  mutable_expected["station"] = "trash"
  assert registry.approval(contract) is not None
  assert contract.postconditions.as_dict()["gates"][0]["expected"] == {
    "station": "staging"
  }


def test_success_requires_pre_and_postconditions_then_moves_sample():
  ledger, samples, resources, orchestrator, task = _fixture()
  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(),),
    _guard(_success),
    _post,
  )
  assert report.final_state is TaskFinalState.SUCCEEDED
  assert report.attempts[0].postcondition is not None
  assert samples.samples["plate-1"].location == "staging"
  assert resources.snapshot() == {}
  assert ledger.verify()[0]
  acquired = next(
    event for event in ledger.events if event.event_type == "resource" and event.action == "acquire"
  )
  assert "sample:plate-1" in acquired.payload["resources"]
  assert "task:move-1" in acquired.payload["resources"]
  assert any(event.event_type == "operation" and event.action == "start" for event in ledger.events)


def test_success_can_leave_a_sample_at_the_same_station():
  contract = _contract(success="reader")
  _ledger, samples, _resources, orchestrator, task = _fixture(contract=contract)

  def inspect(_task, _attempt, permit):
    return OperationResult(
      OperationStatus.SUCCEEDED,
      "inspection complete",
      SampleEffect.NO_CHANGE,
      permit.permit_id,
    )

  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(),),
    _guard(inspect),
    _post,
  )
  assert report.final_state is TaskFinalState.SUCCEEDED
  assert samples.samples["plate-1"].location == "reader"


def test_missing_evidence_stops_before_operation():
  _ledger, samples, _resources, orchestrator, task = _fixture()
  calls = []

  def operation(_task, _attempt, permit):
    calls.append(permit.permit_id)
    return _success(_task, _attempt, permit)

  report = orchestrator.run(task, lambda _task, _attempt: (), _guard(operation), _post)
  assert report.final_state is TaskFinalState.STOPPED
  assert calls == []
  assert samples.samples["plate-1"].location == "reader"


def test_provenance_location_mismatch_is_audited_before_leasing():
  bad_contract = _contract(expected="freezer")
  ledger, _samples, resources, orchestrator, task = _fixture(contract=bad_contract)
  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(),),
    _guard(_success),
    _post,
  )
  assert report.final_state is TaskFinalState.BLOCKED
  assert "provenance says reader" in report.detail
  assert resources.snapshot() == {}
  assert any(event.event_type == "task_terminal" for event in ledger.events)


def test_sample_placeholder_binds_policy_evidence_to_the_actuated_sample():
  ledger = RunLedger("sample-subject-binding")
  samples = SampleTracker(ledger)
  samples.register("plate-2", "reader", recorded_at="2026-01-01T00:00:00Z")
  contract = _contract()
  orchestrator = WorkcellOrchestrator(
    ledger,
    samples,
    contracts=_registry(contract),
  )
  task = WorkcellTask("move-plate-2", "move", "plate-2", contract)
  calls = []
  report = orchestrator.run(
    task,
    # Passing evidence for plate-1 must never authorize a move of plate-2.
    lambda _task, _attempt: (_observation(True),),
    _guard(lambda _task, _attempt, _permit: calls.append("operation")),
    _post,
  )
  assert report.final_state is TaskFinalState.STOPPED
  assert calls == []
  assert samples.samples["plate-2"].location == "reader"


def test_retryable_driver_result_is_bounded_then_succeeds():
  _ledger, _samples, _resources, orchestrator, task = _fixture(max_retries=1)

  def operation(_task, attempt, permit):
    if attempt == 1:
      return OperationResult(
        OperationStatus.RETRYABLE,
        "controller busy before motion",
        SampleEffect.NO_CHANGE,
        permit.permit_id,
      )
    return _success(_task, attempt, permit)

  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(),),
    _guard(operation),
    _post,
  )
  assert report.final_state is TaskFinalState.SUCCEEDED
  assert report.retries_used == 1
  assert len(report.attempts) == 2


def test_exhausted_retry_escalates_without_moving_sample():
  _ledger, samples, _resources, orchestrator, task = _fixture(max_retries=1)

  def busy(_task, _attempt, permit):
    return OperationResult(
      OperationStatus.RETRYABLE,
      "still busy before motion",
      SampleEffect.NO_CHANGE,
      permit.permit_id,
    )

  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(),),
    _guard(busy),
    _post,
  )
  assert report.final_state is TaskFinalState.ESCALATED
  assert report.retries_used == 1
  assert samples.samples["plate-1"].location == "reader"
  assert samples.samples["plate-1"].status == "available"


def test_cancellation_after_audited_no_change_retry_does_not_quarantine_twice():
  ledger, samples, _resources, orchestrator, task = _fixture(max_retries=1)

  def evidence(_task, attempt):
    if attempt == 2:
      raise KeyboardInterrupt("cancelled before second attempt")
    return (_observation(),)

  def retryable(_task, _attempt, permit):
    return OperationResult(
      OperationStatus.RETRYABLE,
      "known no-change transient",
      SampleEffect.NO_CHANGE,
      permit.permit_id,
    )

  with pytest.raises(KeyboardInterrupt, match="cancelled before second attempt"):
    orchestrator.run(task, evidence, _guard(retryable), _post)

  assert samples.samples["plate-1"].status == "available"
  actions = [event.action for event in ledger.events if event.event_type == "operation"]
  assert actions == ["start", "retryable"]
  terminals = [event for event in ledger.events if event.event_type == "task_terminal"]
  assert len(terminals) == 1


def test_policy_recovery_is_bound_and_reacquires_evidence():
  _ledger, _samples, _resources, orchestrator, task = _fixture(max_recoveries=1)
  state = {"aligned": False}
  operations = []

  def evidence(_task, _attempt):
    return (_observation(state["aligned"]),)

  def recover(_task, _reason, _count, permit):
    state["aligned"] = True
    return RecoveryResult(
      RecoveryStatus.SUCCEEDED,
      "re-home complete without touching sample",
      SampleEffect.NO_CHANGE,
      permit.permit_id,
    )

  def operation(_task, _attempt, permit):
    operations.append("called")
    return _success(_task, _attempt, permit)

  report = orchestrator.run(
    task,
    evidence,
    _guard(operation),
    _post,
    _recovery(recover),
  )
  assert report.final_state is TaskFinalState.SUCCEEDED
  assert report.recoveries_used == 1
  assert len(report.attempts) == 2
  assert operations == ["called"]


def test_mismatched_recovery_handler_is_rejected_without_calling_it():
  _ledger, _samples, _resources, orchestrator, task = _fixture(max_recoveries=1)
  calls = []

  def wrong(_task, _reason, _count, permit):
    calls.append(permit.permit_id)
    return RecoveryResult(
      RecoveryStatus.SUCCEEDED,
      "wrong recovery",
      SampleEffect.NO_CHANGE,
      permit.permit_id,
    )

  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(False),),
    _guard(_success),
    _post,
    _recovery(wrong, recovery_id="different_recovery"),
  )
  assert report.final_state is TaskFinalState.ESCALATED
  assert calls == []


@pytest.mark.parametrize(
  "guard",
  [
    {"adapter_version": "999-unreviewed"},
    {"configuration_hash": "sha256:unreviewed-configuration"},
  ],
)
def test_recovery_requires_exact_approved_version_and_configuration(guard):
  _ledger, _samples, _resources, orchestrator, task = _fixture(max_recoveries=1)
  calls = []

  def recover(_task, _reason, _count, permit):
    calls.append(permit.permit_id)
    return RecoveryResult(
      RecoveryStatus.SUCCEEDED,
      "re-home complete",
      SampleEffect.NO_CHANGE,
      permit.permit_id,
    )

  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(False),),
    _guard(_success),
    _post,
    _recovery(recover, **guard),
  )
  assert report.final_state is TaskFinalState.ESCALATED
  assert calls == []


def test_unavailable_recovery_escalates_and_never_calls_operation():
  _ledger, _samples, _resources, orchestrator, task = _fixture(max_recoveries=1)
  calls = []

  def operation(_task, _attempt, permit):
    calls.append(permit.permit_id)
    return _success(_task, _attempt, permit)

  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(False),),
    _guard(operation),
    _post,
  )
  assert report.final_state is TaskFinalState.ESCALATED
  assert calls == []


def test_recoverable_result_uses_named_recovery_then_succeeds():
  _ledger, _samples, _resources, orchestrator, task = _fixture(max_recoveries=1)
  state = {"recovered": False}

  def operation(_task, _attempt, permit):
    if not state["recovered"]:
      return OperationResult(
        OperationStatus.RECOVERABLE,
        "gripper needs re-home; sample was not touched",
        SampleEffect.NO_CHANGE,
        permit.permit_id,
        recovery_id="rehome_pose",
      )
    return _success(_task, _attempt, permit)

  def recover(_task, _reason, _count, permit):
    state["recovered"] = True
    return RecoveryResult(
      RecoveryStatus.SUCCEEDED,
      "gripper re-homed",
      SampleEffect.NO_CHANGE,
      permit.permit_id,
    )

  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(),),
    _guard(operation),
    _post,
    _recovery(recover),
  )
  assert report.final_state is TaskFinalState.SUCCEEDED
  assert report.recoveries_used == 1


def test_fatal_no_motion_result_fails_without_quarantining_sample():
  _ledger, samples, _resources, orchestrator, task = _fixture()

  def failed(_task, _attempt, permit):
    return OperationResult(
      OperationStatus.FAILED,
      "calibration fault before motion",
      SampleEffect.NO_CHANGE,
      permit.permit_id,
    )

  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(),),
    _guard(failed),
    _post,
  )
  assert report.final_state is TaskFinalState.FAILED
  assert samples.samples["plate-1"].status == "available"


def test_adapter_exception_after_start_quarantines_sample_and_never_retries():
  ledger, samples, resources, orchestrator, task = _fixture(max_retries=3)
  calls = []

  def operation(_task, _attempt, permit):
    calls.append(permit.permit_id)
    raise TimeoutError("ack lost after command may have actuated")

  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(),),
    _guard(operation),
    _post,
  )
  assert report.final_state is TaskFinalState.FAILED
  assert len(calls) == 1
  assert samples.samples["plate-1"].status == "uncertain"
  assert resources.snapshot() == {}
  assert ledger.verify()[0]
  actions = [event.action for event in ledger.events if event.event_type == "operation"]
  assert actions[:2] == ["start", "failed"]


def test_keyboard_interrupt_after_operation_start_is_audited_and_reraised():
  ledger, samples, resources, orchestrator, task = _fixture()

  def cancelled(_task, _attempt, _permit):
    raise KeyboardInterrupt("synthetic cancellation")

  with pytest.raises(KeyboardInterrupt, match="synthetic cancellation"):
    orchestrator.run(
      task,
      lambda _task, _attempt: (_observation(),),
      _guard(cancelled),
      _post,
    )

  assert samples.samples["plate-1"].status == "uncertain"
  assert resources.snapshot() == {}
  assert ledger.verify()[0]
  actions = [(event.event_type, event.action) for event in ledger.events]
  assert ("operation", "failed") in actions
  assert ("resource", "release") in actions
  assert ("task_terminal", "failed") in actions


def test_custody_entry_interrupt_releases_the_previously_acquired_lease():
  class InterruptingTracker(SampleTracker):
    @contextmanager
    def custody(self, _sample_id):
      raise KeyboardInterrupt("custody cancelled")
      yield

  ledger = RunLedger("custody-entry-interrupt")
  samples = InterruptingTracker(ledger)
  samples.register("plate-1", "reader", recorded_at="2026-01-01T00:00:00Z")
  resources = ResourceManager("custody-entry-interrupt")
  contract = _contract()
  orchestrator = WorkcellOrchestrator(
    ledger,
    samples,
    resources,
    contracts=_registry(contract),
  )
  task = WorkcellTask("cancelled-custody", "move", "plate-1", contract)

  with pytest.raises(KeyboardInterrupt, match="custody cancelled"):
    orchestrator.run(
      task,
      lambda _task, _attempt: (_observation(),),
      _guard(_success),
      _post,
    )

  assert resources.snapshot() == {}
  transitions = [
    event.action for event in ledger.events if event.event_type == "resource"
  ]
  assert transitions == ["acquire", "release"]
  assert any(
    event.event_type == "task" and event.action == "custody_error"
    for event in ledger.events
  )
  assert any(
    event.event_type == "task_terminal" and event.action == "failed"
    for event in ledger.events
  )


def test_direct_tracker_mutation_waits_for_orchestrator_custody():
  contract = _contract(success="reader")
  ledger, samples, resources, orchestrator, task = _fixture(contract=contract)
  operation_started = Event()
  release_operation = Event()
  mutation_started = Event()
  reports = []

  def inspect(_task, _attempt, permit):
    operation_started.set()
    assert release_operation.wait(5)
    return OperationResult(
      OperationStatus.SUCCEEDED,
      "inspection complete",
      SampleEffect.NO_CHANGE,
      permit.permit_id,
    )

  def run_task():
    reports.append(
      orchestrator.run(
        task,
        lambda _task, _attempt: (_observation(),),
        _guard(inspect),
        _post,
      )
    )

  def consume():
    mutation_started.set()
    return samples.consume("plate-1", "destructive follow-up")

  task_thread = Thread(target=run_task)
  task_thread.start()
  assert operation_started.wait(5)
  with ThreadPoolExecutor(max_workers=1) as pool:
    mutation = pool.submit(consume)
    assert mutation_started.wait(5)
    assert not mutation.done()
    release_operation.set()
    task_thread.join(5)
    assert not task_thread.is_alive()
    assert mutation.result(timeout=5).status == "consumed"

  assert reports[0].final_state is TaskFinalState.SUCCEEDED
  assert resources.snapshot() == {}
  assert ledger.verify()[0]
  terminal_index = next(
    index
    for index, event in enumerate(ledger.events)
    if event.event_type == "task_terminal" and event.payload["task_id"] == task.task_id
  )
  consume_index = next(
    index for index, event in enumerate(ledger.events) if event.action == "consume"
  )
  assert terminal_index < consume_index


def test_between_check_and_custody_mutation_is_audited_and_releases_resources():
  ledger = RunLedger("custody-race")
  samples = SampleTracker(ledger)
  samples.register("plate-1", "reader", recorded_at="2026-01-01T00:00:00Z")
  contract = _contract()

  class RacingResources(ResourceManager):
    def acquire(self, owner, resources, ledger=None):
      lease = super().acquire(owner, resources, ledger)
      samples.consume("plate-1", "synthetic race after resource acquisition")
      return lease

  resources = RacingResources()
  orchestrator = WorkcellOrchestrator(
    ledger,
    samples,
    resources,
    contracts=_registry(contract),
  )
  task = WorkcellTask("race-task", "move", "plate-1", contract)
  calls = []
  report = orchestrator.run(
    task,
    lambda _task, _attempt: calls.append("evidence"),
    _guard(lambda _task, _attempt, _permit: calls.append("operation")),
    _post,
  )
  assert report.final_state is TaskFinalState.BLOCKED
  assert "provenance changed" in report.detail
  assert calls == []
  assert resources.snapshot() == {}
  assert ledger.verify()[0]
  assert any(event.event_type == "task_terminal" for event in ledger.events)


def test_untyped_or_wrong_permit_result_fails_closed_and_quarantines():
  for suffix, execute in (
    ("untyped", lambda _task, _attempt, _permit: {"ok": True}),
    (
      "wrong-permit",
      lambda _task, _attempt, _permit: OperationResult(
        OperationStatus.SUCCEEDED,
        "stale result",
        SampleEffect.EXPECTED_CHANGE,
        "wrong-permit",
      ),
    ),
  ):
    ledger = RunLedger(f"test-{suffix}")
    samples = SampleTracker(ledger)
    samples.register("plate-1", "reader", recorded_at="2026-01-01T00:00:00Z")
    contract = _contract()
    orchestrator = WorkcellOrchestrator(
      ledger, samples, contracts=_registry(contract)
    )
    task = WorkcellTask(f"task-{suffix}", "move", "plate-1", contract)
    report = orchestrator.run(
      task,
      lambda _task, _attempt: (_observation(),),
      _guard(execute),
      _post,
    )
    assert report.final_state is TaskFinalState.FAILED
    assert samples.samples["plate-1"].status == "uncertain"


def test_postcondition_failure_quarantines_instead_of_advancing_provenance():
  _ledger, samples, _resources, orchestrator, task = _fixture()
  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(),),
    _guard(_success),
    lambda _task, _attempt: (_post_observation(False),),
  )
  assert report.final_state is TaskFinalState.STOPPED
  assert samples.samples["plate-1"].location == "reader"
  assert samples.samples["plate-1"].status == "uncertain"


def test_postcondition_evidence_must_be_captured_after_operation_completion():
  _ledger, samples, _resources, orchestrator, task = _fixture()
  early = Observation(
    "at_destination",
    True,
    EvidenceKind.VISION,
    "plate-1",
    "synthetic camera",
    "2026-01-01T00:00:00Z",
    "synthetic://camera/before-operation",
  )
  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(),),
    _guard(_success),
    lambda _task, _attempt: (early,),
  )
  assert report.final_state is TaskFinalState.FAILED
  assert "predates operation completion" in report.detail
  assert samples.samples["plate-1"].status == "uncertain"


def test_postcondition_evidence_captured_during_operation_is_rejected():
  _ledger, samples, _resources, orchestrator, task = _fixture()
  captured = []

  def capture_before_return(_task, _attempt, permit):
    captured.append(_post_observation())
    return OperationResult(
      OperationStatus.SUCCEEDED,
      "synthetic move complete",
      SampleEffect.EXPECTED_CHANGE,
      permit.permit_id,
    )

  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(),),
    _guard(capture_before_return),
    lambda _task, _attempt: tuple(captured),
  )
  assert report.final_state is TaskFinalState.FAILED
  assert "predates operation completion" in report.detail
  assert samples.samples["plate-1"].status == "uncertain"


def test_postcondition_cancellation_quarantines_before_reraising():
  ledger, samples, resources, orchestrator, task = _fixture()

  def cancelled(_task, _attempt):
    raise KeyboardInterrupt("postcondition cancelled")

  with pytest.raises(KeyboardInterrupt, match="postcondition cancelled"):
    orchestrator.run(
      task,
      lambda _task, _attempt: (_observation(),),
      _guard(_success),
      cancelled,
    )

  assert samples.samples["plate-1"].status == "uncertain"
  assert samples.samples["plate-1"].location == "reader"
  assert resources.snapshot() == {}
  assert ledger.verify()[0]
  assert any(
    event.event_type == "task_terminal" and event.action == "failed"
    for event in ledger.events
  )


def test_mutated_result_payload_is_revalidated_after_adapter_return():
  ledger, samples, _resources, orchestrator, task = _fixture()

  def malformed(_task, _attempt, permit):
    result = OperationResult(
      OperationStatus.SUCCEEDED,
      "synthetic move complete",
      SampleEffect.EXPECTED_CHANGE,
      permit.permit_id,
      payload={"ok": True},
    )
    result.payload["late_bad_value"] = object()
    return result

  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(),),
    _guard(malformed),
    _post,
  )
  assert report.final_state is TaskFinalState.FAILED
  assert samples.samples["plate-1"].status == "uncertain"
  assert samples.samples["plate-1"].location == "reader"
  assert ledger.verify()[0]
  assert any(
    event.event_type == "operation" and event.action == "failed"
    for event in ledger.events
  )


def test_location_changing_success_must_declare_expected_change():
  _ledger, samples, _resources, orchestrator, task = _fixture()

  def contradictory(_task, _attempt, permit):
    return OperationResult(
      OperationStatus.SUCCEEDED,
      "claims move without state change",
      SampleEffect.NO_CHANGE,
      permit.permit_id,
    )

  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(),),
    _guard(contradictory),
    _post,
  )
  assert report.final_state is TaskFinalState.FAILED
  assert samples.samples["plate-1"].status == "uncertain"


def test_operation_result_contract_rejects_unsafe_or_malformed_values():
  with pytest.raises(ValueError, match="portable JSON"):
    OperationResult(
      OperationStatus.SUCCEEDED,
      "bad payload",
      SampleEffect.EXPECTED_CHANGE,
      "permit",
      payload={"values": {1, 2}},
    )
  with pytest.raises(ValueError, match="JSON object"):
    OperationResult(
      OperationStatus.SUCCEEDED,
      "scalar payload",
      SampleEffect.EXPECTED_CHANGE,
      "permit",
      payload=["not", "an", "object"],
    )
  with pytest.raises(ValueError, match="portable JSON"):
    OperationResult(
      OperationStatus.SUCCEEDED,
      "non-finite payload",
      SampleEffect.EXPECTED_CHANGE,
      "permit",
      payload={"confidence": float("nan")},
    )
  with pytest.raises(ValueError, match="must be strings"):
    OperationResult(
      OperationStatus.SUCCEEDED,
      object(),
      SampleEffect.EXPECTED_CHANGE,
      "permit",
    )
  with pytest.raises(ValueError, match="OperationStatus"):
    OperationResult("succeeded", "bad status", SampleEffect.NO_CHANGE, "permit")
  with pytest.raises(ValueError, match="no tracked sample/material state change"):
    OperationResult(
      OperationStatus.RETRYABLE,
      "unsafe replay",
      SampleEffect.UNKNOWN,
      "permit",
    )
  with pytest.raises(ValueError, match="recovery_id"):
    OperationResult(
      OperationStatus.RECOVERABLE,
      "missing recovery",
      SampleEffect.NO_CHANGE,
      "permit",
    )


def test_unapproved_contract_is_blocked_before_evidence_or_operation():
  ledger = RunLedger("unapproved-contract")
  samples = SampleTracker(ledger)
  samples.register("plate-1", "reader", recorded_at="2026-01-01T00:00:00Z")
  orchestrator = WorkcellOrchestrator(ledger, samples)
  task = WorkcellTask("unapproved-task", "move", "plate-1", _contract())
  calls = []
  report = orchestrator.run(
    task,
    lambda _task, _attempt: calls.append("evidence"),
    _guard(lambda _task, _attempt, _permit: calls.append("operation")),
    _post,
  )
  assert report.final_state is TaskFinalState.BLOCKED
  assert "not approved by this deployment" in report.detail
  assert calls == []


def test_contract_binding_blocks_wrong_operation_or_adapter_before_evidence():
  for index, guarded in enumerate((
    _guard(_success, operation_id="discard_plate"),
    _guard(_success, adapter_id="unreviewed-adapter"),
    _guard(_success, adapter_version="999-unreviewed"),
    _guard(_success, configuration_hash="sha256:unreviewed-configuration"),
  )):
    ledger = RunLedger(
      f"binding-{index}-{guarded.operation_id}-{guarded.adapter_id}"
    )
    samples = SampleTracker(ledger)
    samples.register("plate-1", "reader", recorded_at="2026-01-01T00:00:00Z")
    contract = _contract()
    orchestrator = WorkcellOrchestrator(
      ledger, samples, contracts=_registry(contract)
    )
    task = WorkcellTask("binding-task", "move", "plate-1", contract)
    calls = []
    report = orchestrator.run(
      task,
      lambda _task, _attempt: calls.append("evidence"),
      guarded,
      _post,
    )
    assert report.final_state is TaskFinalState.BLOCKED
    assert calls == []


def test_contract_is_revalidated_after_resource_acquisition_before_permit():
  contract = _contract(policy=_policy(expected=False))

  class MutatingResources(ResourceManager):
    def acquire(self, owner, resources, ledger=None):
      lease = super().acquire(owner, resources, ledger)
      object.__setattr__(contract.preconditions.gates[0], "expected", True)
      return lease

  ledger = RunLedger("contract-toctou")
  samples = SampleTracker(ledger)
  samples.register("plate-1", "reader", recorded_at="2026-01-01T00:00:00Z")
  calls = []
  orchestrator = WorkcellOrchestrator(
    ledger,
    samples,
    MutatingResources("contract-toctou"),
    contracts=_registry(contract),
  )
  task = WorkcellTask("contract-race", "move", "plate-1", contract)
  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(True),),
    _guard(lambda _task, _attempt, _permit: calls.append("operation")),
    _post,
  )
  assert report.final_state is TaskFinalState.BLOCKED
  assert "permission invalidated" in report.detail
  assert calls == []


def test_precondition_evidence_must_still_be_current_at_permit_issue():
  contract = _contract(policy=_policy(max_age_seconds=0.01))
  _ledger, samples, _resources, orchestrator, task = _fixture(contract=contract)
  record = orchestrator._record_decision

  def delayed_record(*args):
    record(*args)
    if args[2] == "precondition":
      sleep(0.03)

  orchestrator._record_decision = delayed_record
  calls = []
  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(),),
    _guard(lambda _task, _attempt, _permit: calls.append("operation")),
    _post,
  )
  assert report.final_state is TaskFinalState.STOPPED
  assert "expired before adapter invocation" in report.detail
  assert calls == []
  assert samples.samples["plate-1"].status == "available"


@pytest.mark.parametrize("expiry_stage", ("ledger_verification", "permit_construction"))
def test_precondition_expiry_at_final_authorization_is_audited(expiry_stage):
  contract = _contract(policy=_policy(max_age_seconds=0.05))
  ledger, samples, resources, orchestrator, task = _fixture(contract=contract)

  if expiry_stage == "ledger_verification":
    original_assert_valid = ledger.assert_valid
    calls_to_assert = 0

    def delayed_assert_valid():
      nonlocal calls_to_assert
      calls_to_assert += 1
      original_assert_valid()
      if calls_to_assert == 2:
        sleep(0.1)

    ledger.assert_valid = delayed_assert_valid
    expected_detail = "expired before adapter invocation"
  else:
    original_permit = orchestrator._execution_permit

    def delayed_permit(*args):
      sleep(0.1)
      return original_permit(*args)

    orchestrator._execution_permit = delayed_permit
    expected_detail = "cannot issue an execution permit"

  adapter_calls = []
  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(),),
    _guard(lambda _task, _attempt, _permit: adapter_calls.append("operation")),
    _post,
  )

  assert report.final_state is TaskFinalState.STOPPED
  assert expected_detail in report.detail
  assert adapter_calls == []
  assert samples.samples["plate-1"].status == "available"
  assert resources.snapshot() == {}
  assert ledger.verify()[0]
  terminals = [event for event in ledger.events if event.event_type == "task_terminal"]
  assert len(terminals) == 1
  assert terminals[0].action == "stopped"


def test_recovery_permission_expires_before_recovery_adapter_invocation():
  contract = _contract(
    policy=_policy(max_age_seconds=0.01),
    max_recoveries=1,
  )
  _ledger, samples, _resources, orchestrator, task = _fixture(contract=contract)
  record = orchestrator._record_decision

  def delayed_record(*args):
    record(*args)
    if args[2] == "precondition":
      sleep(0.03)

  orchestrator._record_decision = delayed_record
  calls = []
  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(False),),
    _guard(_success),
    _post,
    _recovery(lambda *_args: calls.append("recovery")),
  )
  assert report.final_state is TaskFinalState.ESCALATED
  assert "expired before recovery" in report.detail
  assert calls == []
  assert samples.samples["plate-1"].status == "available"


def test_postcondition_evidence_must_be_current_at_provenance_advance():
  contract = _contract(post_policy=_post_policy(max_age_seconds=0.01))
  _ledger, samples, _resources, orchestrator, task = _fixture(contract=contract)
  record = orchestrator._record_decision

  def delayed_record(*args):
    record(*args)
    if args[2] == "postcondition":
      sleep(0.03)

  orchestrator._record_decision = delayed_record
  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(),),
    _guard(_success),
    _post,
  )
  assert report.final_state is TaskFinalState.STOPPED
  assert "expired before provenance advance" in report.detail
  assert samples.samples["plate-1"].status == "uncertain"
  assert samples.samples["plate-1"].location == "reader"


def test_raw_callable_is_not_an_execution_binding():
  _ledger, _samples, _resources, orchestrator, task = _fixture()
  report = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(),),
    _success,
    _post,
  )
  assert report.final_state is TaskFinalState.BLOCKED
  assert "GuardedOperation" in report.detail


def test_mandatory_contract_resource_cannot_be_omitted_by_task():
  _ledger, _samples, resources, orchestrator, task = _fixture()
  blocker = resources.acquire("other-task", ("robot",))
  calls = []
  try:
    report = orchestrator.run(
      task,
      lambda _task, _attempt: calls.append("evidence"),
      _guard(_success),
      _post,
    )
  finally:
    blocker.release()
  assert task.resources == ("camera", "robot")
  assert report.final_state is TaskFinalState.BLOCKED
  assert calls == []


def test_duplicate_task_id_is_audited_and_blocked():
  _ledger, _samples, _resources, orchestrator, task = _fixture()
  first = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(),),
    _guard(_success),
    _post,
  )
  second = orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(),),
    _guard(_success),
    _post,
  )
  assert first.final_state is TaskFinalState.SUCCEEDED
  assert second.final_state is TaskFinalState.BLOCKED
  assert "already been used" in second.detail


def test_task_id_is_run_wide_across_orchestrator_instances():
  ledger = RunLedger("shared-run")
  samples = SampleTracker(ledger)
  samples.register("plate-1", "reader", recorded_at="2026-01-01T00:00:00Z")
  resources = ResourceManager()
  contract = _contract(success="reader")
  registry = _registry(contract)
  first_orchestrator = WorkcellOrchestrator(
    ledger, samples, resources, contracts=registry
  )
  second_orchestrator = WorkcellOrchestrator(
    ledger, samples, resources, contracts=registry
  )
  task = WorkcellTask("shared-task", "inspect", "plate-1", contract)

  def inspect(_task, _attempt, permit):
    return OperationResult(
      OperationStatus.SUCCEEDED,
      "inspection complete",
      SampleEffect.NO_CHANGE,
      permit.permit_id,
    )

  first = first_orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(),),
    _guard(inspect),
    _post,
  )
  second = second_orchestrator.run(
    task,
    lambda _task, _attempt: (_observation(),),
    _guard(inspect),
    _post,
  )
  assert first.final_state is TaskFinalState.SUCCEEDED
  assert second.final_state is TaskFinalState.BLOCKED
  starts = [
    event for event in ledger.events if event.event_type == "operation" and event.action == "start"
  ]
  assert len(starts) == 1


def test_same_sample_tasks_with_disjoint_devices_cannot_run_together():
  ledger = RunLedger("concurrent-sample")
  samples = SampleTracker(ledger)
  samples.register("plate-1", "reader", recorded_at="2026-01-01T00:00:00Z")
  resources = ResourceManager()
  first = WorkcellTask(
    "inspect-a",
    "inspect with station a",
    "plate-1",
    _contract("inspect_a", success="reader", resources=("station-a",)),
  )
  second = WorkcellTask(
    "inspect-b",
    "inspect with station b",
    "plate-1",
    _contract("inspect_b", success="reader", resources=("station-b",)),
  )
  orchestrator = WorkcellOrchestrator(
    ledger,
    samples,
    resources,
    contracts=_registry(first.contract, second.contract),
  )
  entered = Event()
  release = Event()
  first_reports = []
  calls = []

  def slow(_task, _attempt, permit):
    calls.append("a")
    entered.set()
    assert release.wait(5)
    return OperationResult(
      OperationStatus.SUCCEEDED,
      "inspection a complete",
      SampleEffect.NO_CHANGE,
      permit.permit_id,
    )

  def run_first():
    first_reports.append(
      orchestrator.run(
        first,
        lambda _task, _attempt: (_observation(),),
        _guard(slow, operation_id="inspect_a"),
        _post,
      )
    )

  thread = Thread(target=run_first)
  thread.start()
  assert entered.wait(5)
  blocked = orchestrator.run(
    second,
    lambda _task, _attempt: (_observation(),),
    _guard(
      lambda _task, _attempt, permit: calls.append("b"),
      operation_id="inspect_b",
    ),
    _post,
  )
  release.set()
  thread.join(5)
  assert not thread.is_alive()
  assert first_reports[0].final_state is TaskFinalState.SUCCEEDED
  assert blocked.final_state is TaskFinalState.BLOCKED
  assert calls == ["a"]
  assert ledger.verify()[0]


@pytest.mark.parametrize(
  "scenario, final_state, attempts, retries, recoveries",
  [
    ("pass", TaskFinalState.SUCCEEDED, 1, 0, 0),
    ("transient_retry", TaskFinalState.SUCCEEDED, 2, 1, 0),
    ("vision_recovery", TaskFinalState.SUCCEEDED, 2, 0, 1),
    ("resource_busy", TaskFinalState.BLOCKED, 0, 0, 0),
    ("fatal_driver_error", TaskFinalState.FAILED, 1, 0, 0),
    ("postcondition_failure", TaskFinalState.STOPPED, 1, 0, 0),
    ("ambiguous_driver_timeout", TaskFinalState.FAILED, 1, 0, 0),
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
