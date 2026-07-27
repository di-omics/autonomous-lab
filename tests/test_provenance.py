"""Run records catch tampering and sample state cannot diverge from custody."""

from __future__ import annotations

import dataclasses
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event, RLock

import pytest

from autonomous_lab import Executor, Workcell, build_ledger, protocols
from autonomous_lab.provenance import (
  Actor,
  Attestation,
  RunLedger,
  RunRecord,
  SampleTracker,
  custody_gaps,
  provenance_report,
  record_from_run,
)


def test_hash_chain_round_trips_through_jsonl():
  ledger = RunLedger("run-1")
  ledger.append("action", "plate-1", "aspirate", {"volume_ul": 10}, "2026-01-01T00:00:00Z")
  ledger.append("qc", "plate-1", "pass", {"metric": "od"}, "2026-01-01T00:00:01Z")
  restored = RunLedger.from_jsonl(ledger.to_jsonl())
  assert restored.verify() == (True, "2 events form a valid chain")
  assert restored.events == ledger.events


def test_tampered_payload_is_detected():
  ledger = RunLedger("run-1")
  event = ledger.append(
    "action", "plate-1", "move", {"to": "reader"}, "2026-01-01T00:00:01Z"
  )
  tampered = RunLedger("run-1", (replace(event, payload={"to": "trash"}),))
  ok, reason = tampered.verify()
  assert not ok
  assert "hash does not match" in reason


def test_reordered_events_are_detected():
  ledger = RunLedger("run-1")
  ledger.append("action", "a", "one", recorded_at="2026-01-01T00:00:01Z")
  ledger.append("action", "b", "two", recorded_at="2026-01-01T00:00:02Z")
  reordered = RunLedger("run-1", reversed(ledger.events))
  assert not reordered.verify()[0]


def test_payload_is_copied_before_hashing():
  payload = {"nested": {"value": 1}}
  ledger = RunLedger("run-1")
  ledger.append("action", "a", "record", payload, "2026-01-01T00:00:01Z")
  payload["nested"]["value"] = 999
  assert ledger.events[0].payload["nested"]["value"] == 1
  assert ledger.verify()[0]

  detached = ledger.events[0]
  detached.payload["nested"]["value"] = 777
  assert ledger.events[0].payload["nested"]["value"] == 1
  assert ledger.verify()[0]


def test_ledger_rejects_nonportable_json_and_malformed_timestamps():
  ledger = RunLedger("portable-json")
  with pytest.raises(ValueError, match="JSON serializable"):
    ledger.append("event", "sample", "nan", {"value": float("nan")})
  with pytest.raises(ValueError, match="mapping keys"):
    ledger.append("event", "sample", "bad-key", {1: "coerced"})
  with pytest.raises(ValueError, match="JSON object"):
    ledger.append("event", "sample", "scalar", ["not", "an", "object"])
  with pytest.raises(ValueError, match="recorded_at"):
    ledger.append("event", "sample", "bad-time", {}, recorded_at="")
  with pytest.raises(ValueError, match="invalid ledger event"):
    RunLedger.from_jsonl('{"value": NaN}')


def test_concurrent_appends_form_one_gapless_valid_chain():
  ledger = RunLedger("concurrent-run")

  def append(index):
    return ledger.append("action", f"sample-{index}", "record", {"index": index})

  with ThreadPoolExecutor(max_workers=8) as pool:
    events = list(pool.map(append, range(200)))

  snapshot = ledger.snapshot()
  assert len(events) == len(snapshot) == 200
  assert [event.sequence for event in snapshot] == list(range(1, 201))
  assert len({event.event_hash for event in snapshot}) == 200
  assert ledger.verify() == (True, "200 events form a valid chain")


def test_snapshot_verify_and_export_are_consistent_during_appends():
  ledger = RunLedger("concurrent-export")
  ledger.append("action", "seed", "record")

  def write_events():
    for index in range(100):
      ledger.append("action", f"sample-{index}", "record", {"index": index})

  def read_events():
    observations = []
    for _ in range(100):
      snapshot = ledger.snapshot()
      exported = ledger.to_jsonl()
      observations.append((snapshot, exported, ledger.verify()))
    return observations

  with ThreadPoolExecutor(max_workers=2) as pool:
    writer = pool.submit(write_events)
    reader = pool.submit(read_events)
    writer.result()
    observations = reader.result()

  for snapshot, exported, verification in observations:
    assert [event.sequence for event in snapshot] == list(range(1, len(snapshot) + 1))
    assert RunLedger.from_jsonl(exported).verify()[0]
    assert verification[0]
  assert len(ledger.snapshot()) == 101


def test_sample_lineage_and_location_are_recorded():
  ledger = RunLedger("run-1")
  tracker = SampleTracker(ledger)
  tracker.register("source", "star", recorded_at="2026-01-01T00:00:01Z")
  tracker.derive(
    "library",
    ["source"],
    "star",
    "library prep",
    "2026-01-01T00:00:02Z",
  )
  tracker.move("library", "reader", "2026-01-01T00:00:03Z")
  tracker.consume("source", "fully converted", "2026-01-01T00:00:04Z")
  assert tracker.lineage("library") == ("source", "library")
  assert tracker.samples["library"].location == "reader"
  assert tracker.samples["source"].status == "consumed"
  assert ledger.verify()[0]


def test_duplicate_sample_id_is_refused():
  tracker = SampleTracker(RunLedger("run-1"))
  tracker.register("sample", "bench")
  with pytest.raises(ValueError, match="already exists"):
    tracker.register("sample", "bench")


def test_one_sample_tracker_is_bound_to_each_run_ledger():
  ledger = RunLedger("one-tracker-per-run")
  first = SampleTracker(ledger)
  with pytest.raises(ValueError, match="different sample_tracker"):
    SampleTracker(ledger)
  first.register("sample-1", "reader")
  with pytest.raises(TypeError):
    first.samples["sample-2"] = first.samples["sample-1"]


def test_one_live_ledger_holds_execution_authority_for_a_logical_run_id():
  first = RunLedger("logical-run-authority")
  second = RunLedger("logical-run-authority")
  assert first.claim_task_id("task-a")
  with pytest.raises(ValueError, match="already active through another RunLedger"):
    second.claim_task_id("task-b")


def test_concurrent_registration_allows_one_owner_for_a_sample_id():
  ledger = RunLedger("concurrent-register")
  tracker = SampleTracker(ledger)

  def register(_index):
    try:
      tracker.register("sample", "bench")
      return True
    except ValueError:
      return False

  with ThreadPoolExecutor(max_workers=16) as pool:
    results = list(pool.map(register, range(64)))

  assert results.count(True) == 1
  assert len([event for event in ledger.events if event.action == "register"]) == 1
  assert ledger.verify()[0]


def test_concurrent_move_and_consume_cannot_both_commit():
  ledger = RunLedger("concurrent-transition")
  tracker = SampleTracker(ledger)
  tracker.register("sample", "bench")
  started = Event()

  def move():
    started.wait(5)
    try:
      tracker.move("sample", "reader")
      return "move"
    except ValueError:
      return "blocked"

  def consume():
    started.set()
    try:
      tracker.consume("sample", "destructive read")
      return "consume"
    except ValueError:
      return "blocked"

  with ThreadPoolExecutor(max_workers=2) as pool:
    move_future = pool.submit(move)
    consume_future = pool.submit(consume)
    outcomes = {move_future.result(timeout=5), consume_future.result(timeout=5)}

  assert "blocked" in outcomes
  transitions = [
    event.action for event in ledger.events if event.action in ("move", "consume")
  ]
  assert len(transitions) == 1
  assert ledger.verify()[0]


def test_custody_blocks_direct_sample_mutation_until_release():
  tracker = SampleTracker(RunLedger("custody"))
  tracker.register("sample", "bench")
  mutation_started = Event()

  def consume():
    mutation_started.set()
    return tracker.consume("sample", "destructive read")

  with ThreadPoolExecutor(max_workers=1) as pool:
    with tracker.custody("sample"):
      future = pool.submit(consume)
      assert mutation_started.wait(5)
      assert not future.done()
    assert future.result(timeout=5).status == "consumed"


def test_derive_waiting_for_custody_does_not_deadlock_nested_move():
  tracker = SampleTracker(RunLedger("derive-lock-order"))
  tracker.register("source", "bench")
  attempted = Event()

  class ProbeLock:
    def __init__(self):
      self.lock = RLock()

    def acquire(self):
      attempted.set()
      return self.lock.acquire()

    def release(self):
      return self.lock.release()

    def __enter__(self):
      self.acquire()
      return self

    def __exit__(self, exc_type, exc, traceback):
      self.release()

  tracker._sample_locks["source"] = ProbeLock()
  with ThreadPoolExecutor(max_workers=1) as pool:
    with tracker.custody("source"):
      future = pool.submit(
        tracker.derive,
        "derived",
        ("source",),
        "bench",
        "split",
      )
      assert attempted.wait(5)
      tracker.move("source", "reader")
    with pytest.raises(ValueError, match="not derivation location"):
      future.result(timeout=5)


def test_derivation_requires_all_parents_at_the_operation():
  tracker = SampleTracker(RunLedger("run-1"))
  tracker.register("a", "star")
  tracker.register("b", "reader")
  with pytest.raises(ValueError, match="not derivation location"):
    tracker.derive("pool", ["a", "b"], "star", "pool")


def test_consumed_sample_cannot_move_again():
  tracker = SampleTracker(RunLedger("run-1"))
  tracker.register("sample", "bench")
  tracker.consume("sample", "destructive read")
  with pytest.raises(ValueError, match="consumed"):
    tracker.move("sample", "freezer")


def test_uncertain_sample_keeps_last_confirmed_location_and_is_quarantined():
  ledger = RunLedger("run-1")
  tracker = SampleTracker(ledger)
  tracker.register("sample", "bench")

  state = tracker.mark_uncertain("sample", "pickup outcome unknown", "reader")

  assert state.location == "bench"
  assert state.status == "uncertain"
  event = ledger.snapshot()[-1]
  assert event.action == "mark_uncertain"
  assert event.payload == {
    "last_confirmed_location": "bench",
    "possible_location": "reader",
    "reason": "pickup outcome unknown",
  }
  with pytest.raises(ValueError, match="uncertain"):
    tracker.move("sample", "reader")


def test_sample_mutations_are_atomic_when_ledger_serialization_fails():
  ledger = RunLedger("run-1")
  tracker = SampleTracker(ledger)
  tracker.register("source", "bench")
  original = tracker.samples["source"]
  original_events = ledger.snapshot()

  with pytest.raises(ValueError, match="JSON serializable"):
    tracker.register("new", "bench", {"not_json": object()})
  assert "new" not in tracker.samples
  assert ledger.snapshot() == original_events

  with pytest.raises(ValueError, match="JSON serializable"):
    tracker.derive("derived", ["source"], "bench", "split", recorded_at=object())
  assert "derived" not in tracker.samples
  assert ledger.snapshot() == original_events

  with pytest.raises(ValueError, match="JSON serializable"):
    tracker.move("source", "reader", recorded_at=object())
  assert tracker.samples["source"] == original
  assert ledger.snapshot() == original_events

  with pytest.raises(ValueError, match="JSON serializable"):
    tracker.consume("source", "destructive read", recorded_at=object())
  assert tracker.samples["source"] == original
  assert ledger.snapshot() == original_events

  with pytest.raises(ValueError, match="JSON serializable"):
    tracker.mark_uncertain("source", "lost observation", recorded_at=object())
  assert tracker.samples["source"] == original
  assert ledger.snapshot() == original_events


def test_tail_truncation_needs_an_external_head_commitment_to_detect():
  ledger = RunLedger("run-1")
  ledger.append("action", "a", "one", recorded_at="2026-01-01T00:00:01Z")
  committed_head = ledger.append(
    "action", "b", "two", recorded_at="2026-01-01T00:00:02Z"
  ).event_hash

  truncated = RunLedger("run-1", ledger.events[:-1])

  assert truncated.verify() == (True, "1 events form a valid chain")
  assert truncated.snapshot()[-1].event_hash != committed_head
  assert "cannot detect a truncated tail" in RunLedger.__doc__


def test_invalid_jsonl_is_refused():
  with pytest.raises(ValueError, match="invalid ledger event"):
    RunLedger.from_jsonl("not json")


def _record(n=3) -> RunRecord:
  rec = RunRecord(run_id="test")
  for i in range(n):
    rec.append(
      step_op=f"op{i}",
      instrument="star",
      actor=Actor.MACHINE,
      attestation=Attestation.CONFIRMED,
      evidence=f"evidence {i}",
    )
  return rec


# -- tamper evidence -----------------------------------------------------------


def test_a_clean_chain_verifies():
  ok, reason = _record().verify()
  assert ok
  assert "3 event(s)" in reason


def test_editing_an_event_breaks_the_chain():
  rec = _record()
  rec.events[1] = dataclasses.replace(rec.events[1], evidence="I definitely did this")
  ok, reason = rec.verify()
  assert not ok
  assert "edited" in reason


def test_removing_an_event_breaks_the_chain():
  """A splice must be caught, not just an edit. The seq check is what catches it."""
  rec = _record()
  del rec.events[1]
  ok, reason = rec.verify()
  assert not ok


def test_reordering_events_breaks_the_chain():
  rec = _record()
  rec.events[0], rec.events[1] = rec.events[1], rec.events[0]
  ok, _reason = rec.verify()
  assert not ok


def test_each_event_links_to_its_predecessor():
  rec = _record()
  assert rec.events[0].prev_hash == ""
  for prev, nxt in zip(rec.events, rec.events[1:]):
    assert nxt.prev_hash == prev.digest


def test_the_record_serializes_and_carries_its_digests():
  payload = json.loads(_record().to_json())
  assert payload["run_id"] == "test"
  assert len(payload["events"]) == 3
  assert all(e["digest"] for e in payload["events"])


# -- attestation ---------------------------------------------------------------


def test_asserted_is_not_evidence():
  """Software intent is a log line. Only an instrument or a human is evidence."""
  assert not Attestation.ASSERTED.is_evidence
  assert Attestation.CONFIRMED.is_evidence
  assert Attestation.WITNESSED.is_evidence


def test_a_dry_run_produces_a_record_with_no_evidence_in_it():
  """The correct and uncomfortable result: previewing a protocol proves nothing."""
  report = Executor(Workcell.default(), armed=False).run(protocols.get("single_cell_genomics"))
  rec = record_from_run(report, "dry")
  machine_events = [e for e in rec.events if e.actor is Actor.MACHINE]
  assert machine_events
  assert all(e.attestation is Attestation.ASSERTED for e in machine_events)
  assert len(rec.unevidenced()) == len(machine_events)


def test_a_stopped_run_records_the_handoff_as_witnessed():
  report = Executor(Workcell.default(), armed=False).run(protocols.get("single_cell_genomics"))
  assert report.handoff is not None
  rec = record_from_run(report, "stopped")
  last = rec.events[-1]
  assert last.actor is Actor.HUMAN
  assert last.attestation is Attestation.WITNESSED
  assert last.decision == "escalate"


# -- custody -------------------------------------------------------------------


def test_custody_gaps_match_the_ledgers_physical_hops_exactly():
  """One computation, not two. If these ever diverge, one of them is lying."""
  ledger = build_ledger(protocols.get("single_cell_genomics"))
  hops = ledger.handoffs()
  gaps = custody_gaps(ledger)
  assert len(gaps) == len(hops)
  assert [(g.artifact, g.from_instrument, g.to_instrument) for g in gaps] == hops


def test_genomics_has_five_unobserved_transfers():
  report = provenance_report(build_ledger(protocols.get("single_cell_genomics")))
  assert report.counts()["custody_gaps"] == 5
  assert not report.unbroken


def test_every_gap_names_something_concrete_that_would_close_it():
  """'Improve tracking' is not an action. A barcode read at both ends is."""
  for gap in custody_gaps(build_ledger(protocols.get("single_cell_genomics"))):
    assert gap.closes_it
    assert "barcode" in gap.closes_it or "arm" in gap.closes_it


def test_most_steps_cannot_be_confirmed_by_an_instrument_today():
  report = provenance_report(build_ledger(protocols.get("single_cell_genomics")))
  counts = report.counts()
  assert counts["steps_confirmable"] < counts["steps_total"]
  assert counts["steps_asserted_only"] > 0
  assert counts["steps_confirmable"] + counts["steps_asserted_only"] == counts["steps_total"]


def test_there_is_no_api_to_edit_or_delete_an_event():
  """Append-only enforced by the type, not by convention."""
  rec = RunRecord(run_id="x")
  for forbidden in ("edit", "update", "remove", "delete", "pop", "insert"):
    assert not hasattr(rec, forbidden)
