"""Append-only run records and sample lineage for auditable laboratory execution.

Every event commits to the previous event with SHA-256. The chain is not a security
boundary by itself, but it makes accidental edits, missing events, and reordered events
detectable during replay. SampleTracker builds lineage and location transitions on top
of the same record, so the audit trail and the sample state cannot quietly diverge.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _canonical(value: Dict[str, Any]) -> str:
  try:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
  except (TypeError, ValueError) as exc:
    raise ValueError("ledger payloads must be JSON serializable") from exc


def _now() -> str:
  return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class LedgerEvent:
  sequence: int
  run_id: str
  event_type: str
  subject: str
  action: str
  payload: Dict[str, Any]
  recorded_at: str
  previous_hash: str
  event_hash: str

  def committed_fields(self) -> Dict[str, Any]:
    return {
      "sequence": self.sequence,
      "run_id": self.run_id,
      "event_type": self.event_type,
      "subject": self.subject,
      "action": self.action,
      "payload": self.payload,
      "recorded_at": self.recorded_at,
      "previous_hash": self.previous_hash,
    }

  def expected_hash(self) -> str:
    return hashlib.sha256(_canonical(self.committed_fields()).encode("ascii")).hexdigest()

  def as_dict(self) -> Dict[str, Any]:
    out = self.committed_fields()
    out["event_hash"] = self.event_hash
    return out


class RunLedger:
  """An in-memory hash-chained ledger with JSONL import/export."""

  GENESIS = "0" * 64

  def __init__(self, run_id: str, events: Iterable[LedgerEvent] = ()):
    if not run_id:
      raise ValueError("run_id must not be empty")
    self.run_id = run_id
    self.events: List[LedgerEvent] = list(events)

  def append(
    self,
    event_type: str,
    subject: str,
    action: str,
    payload: Optional[Dict[str, Any]] = None,
    recorded_at: Optional[str] = None,
  ) -> LedgerEvent:
    for name, value in (("event_type", event_type), ("subject", subject), ("action", action)):
      if not value:
        raise ValueError(f"{name} must not be empty")

    # Round-trip through canonical JSON so a caller cannot mutate a nested payload after
    # the event hash has been computed.
    clean_payload = json.loads(_canonical(payload or {}))
    fields = {
      "sequence": len(self.events) + 1,
      "run_id": self.run_id,
      "event_type": event_type,
      "subject": subject,
      "action": action,
      "payload": clean_payload,
      "recorded_at": recorded_at or _now(),
      "previous_hash": self.events[-1].event_hash if self.events else self.GENESIS,
    }
    digest = hashlib.sha256(_canonical(fields).encode("ascii")).hexdigest()
    event = LedgerEvent(event_hash=digest, **fields)
    self.events.append(event)
    return event

  def verify(self) -> Tuple[bool, str]:
    previous = self.GENESIS
    for expected_sequence, event in enumerate(self.events, 1):
      if event.run_id != self.run_id:
        return False, f"event {expected_sequence} belongs to run {event.run_id}"
      if event.sequence != expected_sequence:
        return False, f"event sequence jumps at {expected_sequence}"
      if event.previous_hash != previous:
        return False, f"event {expected_sequence} does not commit to its predecessor"
      if event.event_hash != event.expected_hash():
        return False, f"event {expected_sequence} hash does not match its contents"
      previous = event.event_hash
    return True, f"{len(self.events)} events form a valid chain"

  def assert_valid(self):
    ok, reason = self.verify()
    if not ok:
      raise ValueError(reason)

  def to_jsonl(self) -> str:
    return "\n".join(_canonical(event.as_dict()) for event in self.events)

  @classmethod
  def from_jsonl(cls, data: str) -> "RunLedger":
    rows = [line for line in data.splitlines() if line.strip()]
    if not rows:
      raise ValueError("ledger JSONL is empty")
    events: List[LedgerEvent] = []
    for line_number, row in enumerate(rows, 1):
      try:
        raw = json.loads(row)
        events.append(LedgerEvent(**raw))
      except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid ledger event on line {line_number}") from exc
    ledger = cls(events[0].run_id, events)
    ledger.assert_valid()
    return ledger


@dataclass(frozen=True)
class SampleState:
  sample_id: str
  parents: Tuple[str, ...]
  location: str
  status: str


class SampleTracker:
  """Track sample identity, lineage, location, and consumption in one run ledger."""

  def __init__(self, ledger: RunLedger):
    self.ledger = ledger
    self.samples: Dict[str, SampleState] = {}

  def register(
    self,
    sample_id: str,
    location: str,
    metadata: Optional[Dict[str, Any]] = None,
    recorded_at: Optional[str] = None,
  ) -> SampleState:
    self._new_id(sample_id)
    if not location:
      raise ValueError("sample location must not be empty")
    state = SampleState(sample_id, (), location, "available")
    self.samples[sample_id] = state
    self.ledger.append(
      "sample",
      sample_id,
      "register",
      {"location": location, "metadata": metadata or {}},
      recorded_at,
    )
    return state

  def derive(
    self,
    sample_id: str,
    parents: Iterable[str],
    location: str,
    operation: str,
    recorded_at: Optional[str] = None,
  ) -> SampleState:
    self._new_id(sample_id)
    parent_ids = tuple(parents)
    if not parent_ids:
      raise ValueError("derived samples need at least one parent")
    if not operation or not location:
      raise ValueError("derive needs an operation and location")
    for parent in parent_ids:
      state = self._available(parent)
      if state.location != location:
        raise ValueError(
          f"parent {parent} is at {state.location}, not derivation location {location}"
        )
    state = SampleState(sample_id, parent_ids, location, "available")
    self.samples[sample_id] = state
    self.ledger.append(
      "sample",
      sample_id,
      "derive",
      {"parents": list(parent_ids), "location": location, "operation": operation},
      recorded_at,
    )
    return state

  def move(
    self, sample_id: str, destination: str, recorded_at: Optional[str] = None
  ) -> SampleState:
    state = self._available(sample_id)
    if not destination:
      raise ValueError("destination must not be empty")
    if destination == state.location:
      raise ValueError(f"sample {sample_id} is already at {destination}")
    updated = SampleState(state.sample_id, state.parents, destination, state.status)
    self.samples[sample_id] = updated
    self.ledger.append(
      "sample",
      sample_id,
      "move",
      {"from": state.location, "to": destination},
      recorded_at,
    )
    return updated

  def consume(
    self, sample_id: str, reason: str, recorded_at: Optional[str] = None
  ) -> SampleState:
    state = self._available(sample_id)
    if not reason:
      raise ValueError("consumption reason must not be empty")
    updated = SampleState(state.sample_id, state.parents, state.location, "consumed")
    self.samples[sample_id] = updated
    self.ledger.append(
      "sample",
      sample_id,
      "consume",
      {"location": state.location, "reason": reason},
      recorded_at,
    )
    return updated

  def lineage(self, sample_id: str) -> Tuple[str, ...]:
    if sample_id not in self.samples:
      raise KeyError(f"unknown sample {sample_id}")
    ordered: List[str] = []
    seen = set()

    def visit(current: str):
      if current in seen:
        return
      seen.add(current)
      for parent in self.samples[current].parents:
        visit(parent)
      ordered.append(current)

    visit(sample_id)
    return tuple(ordered)

  def _new_id(self, sample_id: str):
    if not sample_id:
      raise ValueError("sample_id must not be empty")
    if sample_id in self.samples:
      raise ValueError(f"sample {sample_id} already exists")

  def _available(self, sample_id: str) -> SampleState:
    if sample_id not in self.samples:
      raise KeyError(f"unknown sample {sample_id}")
    state = self.samples[sample_id]
    if state.status != "available":
      raise ValueError(f"sample {sample_id} is {state.status}")
    return state
