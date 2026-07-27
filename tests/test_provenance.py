"""The run record catches tampering and sample state cannot diverge from it."""

from __future__ import annotations

from dataclasses import replace

import pytest

from autonomous_lab.provenance import RunLedger, SampleTracker


def test_hash_chain_round_trips_through_jsonl():
  ledger = RunLedger("run-1")
  ledger.append("action", "plate-1", "aspirate", {"volume_ul": 10}, "2026-01-01T00:00:00Z")
  ledger.append("qc", "plate-1", "pass", {"metric": "od"}, "2026-01-01T00:00:01Z")
  restored = RunLedger.from_jsonl(ledger.to_jsonl())
  assert restored.verify() == (True, "2 events form a valid chain")
  assert restored.events == ledger.events


def test_tampered_payload_is_detected():
  ledger = RunLedger("run-1")
  event = ledger.append("action", "plate-1", "move", {"to": "reader"}, "1")
  ledger.events[0] = replace(event, payload={"to": "trash"})
  ok, reason = ledger.verify()
  assert not ok
  assert "hash does not match" in reason


def test_reordered_events_are_detected():
  ledger = RunLedger("run-1")
  ledger.append("action", "a", "one", recorded_at="1")
  ledger.append("action", "b", "two", recorded_at="2")
  ledger.events.reverse()
  assert not ledger.verify()[0]


def test_payload_is_copied_before_hashing():
  payload = {"nested": {"value": 1}}
  ledger = RunLedger("run-1")
  ledger.append("action", "a", "record", payload, "1")
  payload["nested"]["value"] = 999
  assert ledger.events[0].payload["nested"]["value"] == 1
  assert ledger.verify()[0]


def test_sample_lineage_and_location_are_recorded():
  ledger = RunLedger("run-1")
  tracker = SampleTracker(ledger)
  tracker.register("source", "star", recorded_at="1")
  tracker.derive("library", ["source"], "star", "library prep", "2")
  tracker.move("library", "reader", "3")
  tracker.consume("source", "fully converted", "4")
  assert tracker.lineage("library") == ("source", "library")
  assert tracker.samples["library"].location == "reader"
  assert tracker.samples["source"].status == "consumed"
  assert ledger.verify()[0]


def test_duplicate_sample_id_is_refused():
  tracker = SampleTracker(RunLedger("run-1"))
  tracker.register("sample", "bench")
  with pytest.raises(ValueError, match="already exists"):
    tracker.register("sample", "bench")


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


def test_invalid_jsonl_is_refused():
  with pytest.raises(ValueError, match="invalid ledger event"):
    RunLedger.from_jsonl("not json")
