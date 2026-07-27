"""Append-only run records and sample lineage for auditable laboratory execution.

Every event commits to the previous event with SHA-256. The chain is not a security
boundary by itself, but it makes edits, reordering, and deletion from the middle of an
available record detectable during replay. Detecting deletion from the tail requires an
externally committed head hash, which this in-memory prototype does not provide.
SampleTracker builds lineage and location transitions on top of the same record.
"""

from __future__ import annotations

import hashlib
import json
import weakref
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from types import MappingProxyType
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple


_RUN_AUTHORITY_LOCK = RLock()
_RUN_AUTHORITIES = weakref.WeakValueDictionary()


def _canonical(value: Dict[str, Any]) -> str:
  def require_string_keys(node: Any):
    if isinstance(node, dict):
      for key, child in node.items():
        if not isinstance(key, str):
          raise ValueError("ledger mapping keys must be strings")
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

  def __post_init__(self):
    if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
      raise ValueError("ledger event sequence must be a positive integer")
    for name in (
      "run_id",
      "event_type",
      "subject",
      "action",
      "recorded_at",
      "previous_hash",
      "event_hash",
    ):
      value = getattr(self, name)
      if not isinstance(value, str) or not value:
        raise ValueError(f"ledger event {name} must be a non-empty string")
    if not isinstance(self.payload, dict):
      raise ValueError("ledger event payload must be a JSON object")
    normalized = (
      f"{self.recorded_at[:-1]}+00:00"
      if self.recorded_at.endswith("Z")
      else self.recorded_at
    )
    try:
      parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
      raise ValueError("ledger event recorded_at must be valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
      raise ValueError("ledger event recorded_at must include a timezone offset")

  def committed_fields(self) -> Dict[str, Any]:
    return {
      "sequence": self.sequence,
      "run_id": self.run_id,
      "event_type": self.event_type,
      "subject": self.subject,
      "action": self.action,
      "payload": json.loads(_canonical(self.payload)),
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
  """An in-memory hash chain with serialized append, verify, snapshot, and export.

  Verification covers the available chain. It cannot detect a truncated tail unless a
  previously published head hash or event count is compared outside this process.
  ``events`` and ``snapshot()`` return detached views; only ``append()`` mutates the
  committed chain.
  """

  GENESIS = "0" * 64

  def __init__(self, run_id: str, events: Iterable[LedgerEvent] = ()):
    if not isinstance(run_id, str) or not run_id:
      raise ValueError("run_id must not be empty")
    self.run_id = run_id
    self._events: List[LedgerEvent] = [
      LedgerEvent(**event.as_dict()) for event in events
    ]
    self._lock = RLock()
    self._runtime_bindings = weakref.WeakValueDictionary()
    self._claimed_task_ids = {
      event.payload["task_id"]
      for event in self._events
      if (
        (event.event_type == "task_claim" and event.action == "claim")
        or (event.event_type == "task" and event.action == "propose")
      )
      and isinstance(event.payload, dict)
      and isinstance(event.payload.get("task_id"), str)
      and event.payload["task_id"]
    }

  def shared_runtime(self, name: str, factory):
    """Return one process-local runtime object for this run ledger."""
    if not name or not callable(factory):
      raise ValueError("runtime binding needs a name and factory")
    with self._lock:
      if name not in self._runtime_bindings:
        self._runtime_bindings[name] = factory()
      return self._runtime_bindings[name]

  def bind_runtime(self, name: str, value: Any):
    """Bind exactly one process-local runtime object of a given kind to this run."""
    if not name or value is None:
      raise ValueError("runtime binding needs a name and value")
    with self._lock:
      current = self._runtime_bindings.get(name)
      if current is not None and current is not value:
        raise ValueError(f"run {self.run_id} already has a different {name}")
      self._runtime_bindings[name] = value
      return value

  def append(
    self,
    event_type: str,
    subject: str,
    action: str,
    payload: Optional[Dict[str, Any]] = None,
    recorded_at: Optional[str] = None,
  ) -> LedgerEvent:
    with self._lock:
      for name, value in (
        ("event_type", event_type),
        ("subject", subject),
        ("action", action),
      ):
        if not isinstance(value, str) or not value:
          raise ValueError(f"{name} must not be empty")

      if payload is not None and not isinstance(payload, dict):
        raise ValueError("ledger payload must be a JSON object")

      # Round-trip through canonical JSON so a caller cannot mutate a nested payload
      # after the event hash has been computed.
      clean_payload = json.loads(_canonical(payload if payload is not None else {}))
      fields = {
        "sequence": len(self._events) + 1,
        "run_id": self.run_id,
        "event_type": event_type,
        "subject": subject,
        "action": action,
        "payload": clean_payload,
        "recorded_at": _now() if recorded_at is None else recorded_at,
        "previous_hash": self._events[-1].event_hash if self._events else self.GENESIS,
      }
      digest = hashlib.sha256(_canonical(fields).encode("ascii")).hexdigest()
      event = LedgerEvent(event_hash=digest, **fields)
      self._events.append(event)
      return LedgerEvent(**event.as_dict())

  @property
  def events(self) -> Tuple[LedgerEvent, ...]:
    """Return detached events so inspection cannot mutate the committed chain."""
    with self._lock:
      return tuple(LedgerEvent(**event.as_dict()) for event in self._events)

  def snapshot(self) -> Tuple[LedgerEvent, ...]:
    """Return a detached tuple captured between serialized appends."""
    return self.events

  def claim_task_id(self, task_id: str) -> bool:
    """Claim and record a run-wide task ID exactly once."""
    if not isinstance(task_id, str) or not task_id:
      raise ValueError("task_id must not be empty")
    with _RUN_AUTHORITY_LOCK:
      authority = _RUN_AUTHORITIES.get(self.run_id)
      if authority is not None and authority is not self:
        raise ValueError(
          f"logical run {self.run_id} is already active through another RunLedger"
        )
      _RUN_AUTHORITIES[self.run_id] = self
      with self._lock:
        if task_id in self._claimed_task_ids:
          return False
        self._claimed_task_ids.add(task_id)
        try:
          self.append(
            "task_claim",
            task_id,
            "claim",
            {"task_id": task_id},
          )
        except BaseException:
          committed = any(
            event.event_type == "task_claim"
            and event.action == "claim"
            and event.payload.get("task_id") == task_id
            for event in self._events
          )
          if not committed:
            self._claimed_task_ids.remove(task_id)
          raise
        return True

  def verify(self) -> Tuple[bool, str]:
    with self._lock:
      previous = self.GENESIS
      for expected_sequence, event in enumerate(self._events, 1):
        if event.run_id != self.run_id:
          return False, f"event {expected_sequence} belongs to run {event.run_id}"
        if event.sequence != expected_sequence:
          return False, f"event sequence jumps at {expected_sequence}"
        if event.previous_hash != previous:
          return False, f"event {expected_sequence} does not commit to its predecessor"
        if event.event_hash != event.expected_hash():
          return False, f"event {expected_sequence} hash does not match its contents"
        previous = event.event_hash
      return True, f"{len(self._events)} events form a valid chain"

  def assert_valid(self):
    ok, reason = self.verify()
    if not ok:
      raise ValueError(reason)

  def to_jsonl(self) -> str:
    with self._lock:
      return "\n".join(_canonical(event.as_dict()) for event in self._events)

  @classmethod
  def from_jsonl(cls, data: str) -> "RunLedger":
    rows = [line for line in data.splitlines() if line.strip()]
    if not rows:
      raise ValueError("ledger JSONL is empty")
    events: List[LedgerEvent] = []
    for line_number, row in enumerate(rows, 1):
      try:
        raw = json.loads(
          row,
          parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON number {value}")
          ),
        )
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
    ledger.bind_runtime("sample_tracker", self)
    self._samples: Dict[str, SampleState] = {}
    self._index_lock = RLock()
    self._sample_locks: Dict[str, RLock] = {}
    self._reserved_ids = set()

  @property
  def samples(self) -> Mapping[str, SampleState]:
    """Read-only live view of tracked immutable sample states."""
    return MappingProxyType(self._samples)

  def register(
    self,
    sample_id: str,
    location: str,
    metadata: Optional[Dict[str, Any]] = None,
    recorded_at: Optional[str] = None,
  ) -> SampleState:
    with self._index_lock:
      self._new_id(sample_id)
      if not isinstance(location, str) or not location:
        raise ValueError("sample location must not be empty")
      state = SampleState(sample_id, (), location, "available")
      self.ledger.append(
        "sample",
        sample_id,
        "register",
        {"location": location, "metadata": metadata or {}},
        recorded_at,
      )
      self._samples[sample_id] = state
      self._sample_locks[sample_id] = RLock()
      return state

  def derive(
    self,
    sample_id: str,
    parents: Iterable[str],
    location: str,
    operation: str,
    recorded_at: Optional[str] = None,
  ) -> SampleState:
    parent_ids = tuple(parents)
    if not parent_ids:
      raise ValueError("derived samples need at least one parent")
    if len(parent_ids) != len(set(parent_ids)):
      raise ValueError("derived samples cannot repeat a parent")
    if any(not isinstance(value, str) or not value for value in (operation, location)):
      raise ValueError("derive needs an operation and location")
    if any(not isinstance(parent, str) or not parent for parent in parent_ids):
      raise ValueError("derived sample parent IDs must be non-empty strings")
    with self._index_lock:
      self._new_id(sample_id)
      missing = [parent for parent in parent_ids if parent not in self._sample_locks]
      if missing:
        raise KeyError(f"unknown sample {missing[0]}")
      locks = [self._sample_locks[parent] for parent in sorted(parent_ids)]
      self._reserved_ids.add(sample_id)
    for lock in locks:
      lock.acquire()
    committed = False
    try:
      for parent in parent_ids:
        state = self._available(parent)
        if state.location != location:
          raise ValueError(
            f"parent {parent} is at {state.location}, not derivation location {location}"
          )
      state = SampleState(sample_id, parent_ids, location, "available")
      with self._index_lock:
        self.ledger.append(
          "sample",
          sample_id,
          "derive",
          {"parents": list(parent_ids), "location": location, "operation": operation},
          recorded_at,
        )
        self._samples[sample_id] = state
        self._sample_locks[sample_id] = RLock()
        self._reserved_ids.remove(sample_id)
        committed = True
      return state
    finally:
      if not committed:
        with self._index_lock:
          self._reserved_ids.discard(sample_id)
      for lock in reversed(locks):
        lock.release()

  def move(
    self, sample_id: str, destination: str, recorded_at: Optional[str] = None
  ) -> SampleState:
    with self._lock_for(sample_id):
      state = self._available(sample_id)
      if not isinstance(destination, str) or not destination:
        raise ValueError("destination must not be empty")
      if destination == state.location:
        raise ValueError(f"sample {sample_id} is already at {destination}")
      updated = SampleState(state.sample_id, state.parents, destination, state.status)
      self.ledger.append(
        "sample",
        sample_id,
        "move",
        {"from": state.location, "to": destination},
        recorded_at,
      )
      self._samples[sample_id] = updated
      return updated

  def consume(
    self, sample_id: str, reason: str, recorded_at: Optional[str] = None
  ) -> SampleState:
    with self._lock_for(sample_id):
      state = self._available(sample_id)
      if not isinstance(reason, str) or not reason:
        raise ValueError("consumption reason must not be empty")
      updated = SampleState(state.sample_id, state.parents, state.location, "consumed")
      self.ledger.append(
        "sample",
        sample_id,
        "consume",
        {"location": state.location, "reason": reason},
        recorded_at,
      )
      self._samples[sample_id] = updated
      return updated

  def mark_uncertain(
    self,
    sample_id: str,
    reason: str,
    possible_location: Optional[str] = None,
    recorded_at: Optional[str] = None,
  ) -> SampleState:
    """Quarantine a sample whose physical state can no longer be established.

    ``location`` remains the last confirmed location. The possible destination is
    recorded separately, and the non-available status prevents another task from using
    stale provenance as permission to actuate.
    """
    with self._lock_for(sample_id):
      state = self._available(sample_id)
      if not isinstance(reason, str) or not reason:
        raise ValueError("uncertainty reason must not be empty")
      if possible_location is not None and (
        not isinstance(possible_location, str) or not possible_location
      ):
        raise ValueError("possible_location must be a non-empty string when provided")
      updated = SampleState(state.sample_id, state.parents, state.location, "uncertain")
      self.ledger.append(
        "sample",
        sample_id,
        "mark_uncertain",
        {
          "last_confirmed_location": state.location,
          "possible_location": possible_location,
          "reason": reason,
        },
        recorded_at,
      )
      self._samples[sample_id] = updated
      return updated

  @contextmanager
  def custody(self, sample_id: str) -> Iterator[SampleState]:
    """Hold the same per-sample lock used by every tracker mutation."""
    lock = self._lock_for(sample_id)
    with lock:
      # Availability is deliberately re-checked by the orchestrator after entering.
      # Yielding a consumed/uncertain state lets that race become an audited BLOCKED
      # report rather than an exception during context-manager entry.
      yield self._samples[sample_id]

  def lineage(self, sample_id: str) -> Tuple[str, ...]:
    with self._index_lock:
      if sample_id not in self._samples:
        raise KeyError(f"unknown sample {sample_id}")
      parents_by_id = {
        current_id: state.parents for current_id, state in self._samples.items()
      }
    ordered: List[str] = []
    seen = set()

    def visit(current: str):
      if current in seen:
        return
      seen.add(current)
      for parent in parents_by_id[current]:
        visit(parent)
      ordered.append(current)

    visit(sample_id)
    return tuple(ordered)

  def _new_id(self, sample_id: str):
    if not isinstance(sample_id, str) or not sample_id:
      raise ValueError("sample_id must not be empty")
    if sample_id in self._samples or sample_id in self._reserved_ids:
      raise ValueError(f"sample {sample_id} already exists")

  def _lock_for(self, sample_id: str) -> RLock:
    with self._index_lock:
      if sample_id not in self._sample_locks:
        raise KeyError(f"unknown sample {sample_id}")
      return self._sample_locks[sample_id]

  def _available(self, sample_id: str) -> SampleState:
    if sample_id not in self._samples:
      raise KeyError(f"unknown sample {sample_id}")
    state = self._samples[sample_id]
    if state.status != "available":
      raise ValueError(f"sample {sample_id} is {state.status}")
    return state
