"""Device-free tests for sample tracking and the chain of custody.

Two things must hold. The hash chain must catch a record that was edited or spliced after
the fact, because a record that cannot detect tampering is a diary. And the custody gaps
must come from the ledger's own physical-hop computation rather than a second list, because
two independent lists eventually disagree and nobody notices which one is wrong.
"""

from __future__ import annotations

import dataclasses
import json

from autonomous_lab import Executor, Workcell, build_ledger, protocols
from autonomous_lab.provenance import (
  Actor,
  Attestation,
  RunRecord,
  custody_gaps,
  provenance_report,
  record_from_run,
)


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
