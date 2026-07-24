"""Tamper-evident evidence for laboratory runs.

Clair has to remember more than a normal application log. A future decision may depend
on whether a number was modeled, produced by a simulator, measured from an instrument,
or measured through an integration that has itself been validated. It must also be
possible to prove that an old decision was not silently rewritten after the fact.

This module provides a small, stdlib-only append-only ledger. Every event:

* names its evidence level explicitly;
* carries the hash of the previous event;
* is sealed by a SHA-256 digest over a canonical JSON body; and
* can be verified and replayed without importing any hardware package.

The hash chain detects mutation, interior deletion, insertion, and reordering. Deleting
an unanchored suffix changes the head but cannot be distinguished from an earlier clean
stop, so deployments should sign and externally anchor reported head hashes. This is a
tamper-evident log, not an identity or non-repudiation system.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple

SCHEMA_VERSION = 1
GENESIS_HASH = "0" * 64
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_RFC3339_PATTERN = re.compile(
  r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


class EvidenceLevel(str, Enum):
  """Where a claim came from.

  The order is deliberate. A caller may require at least MEASURED evidence before a
  production QC gate or learning loop can use a value. Simulation remains valuable,
  but it can never be confused with contact with the physical world.
  """

  MODELED = "modeled"
  SIMULATED = "simulated_execution"
  MEASURED = "measured"
  HARDWARE_VALIDATED = "hardware_validated"

  @property
  def rank(self) -> int:
    return {
      EvidenceLevel.MODELED: 0,
      EvidenceLevel.SIMULATED: 1,
      EvidenceLevel.MEASURED: 2,
      EvidenceLevel.HARDWARE_VALIDATED: 3,
    }[self]

  def at_least(self, required: "EvidenceLevel") -> bool:
    return self.rank >= required.rank


class EventKind(str, Enum):
  """The stable vocabulary used by the evidence, sample, and learning layers."""

  RUN_STARTED = "run_started"
  PERMISSION_EVALUATED = "permission_evaluated"
  STEP_STARTED = "step_started"
  STEP_COMPLETED = "step_completed"
  STEP_FAILED = "step_failed"
  RUN_STOPPED = "run_stopped"
  RUN_COMPLETED = "run_completed"
  MATERIAL_REGISTERED = "material_registered"
  MATERIAL_DERIVED = "material_derived"
  MATERIAL_MOVED = "material_moved"
  MATERIAL_STATUS_CHANGED = "material_status_changed"
  MEASUREMENT_RECORDED = "measurement_recorded"
  GATE_EVALUATED = "gate_evaluated"
  DESIGN_PROPOSED = "design_proposed"
  OBSERVATION_RECORDED = "observation_recorded"


def canonical_json(value: object) -> str:
  """Canonical JSON used for every digest in the package."""
  return json.dumps(
    _normalise(value),
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=True,
    allow_nan=False,
  )


def digest(value: object) -> str:
  """SHA-256 of a canonical JSON value."""
  return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_digest(path: str, chunk_size: int = 1024 * 1024) -> str:
  """SHA-256 a source file so an analysis event can name the exact bytes it used."""
  h = hashlib.sha256()
  with open(path, "rb") as fh:
    while True:
      chunk = fh.read(chunk_size)
      if not chunk:
        break
      h.update(chunk)
  return h.hexdigest()


def _normalise(value: object) -> object:
  """Copy a value into the JSON subset and reject ambiguous payloads early."""
  if value is None or isinstance(value, (str, int, float, bool)):
    return value
  if isinstance(value, Enum):
    return _normalise(value.value)
  if isinstance(value, Mapping):
    out: Dict[str, object] = {}
    for key, item in value.items():
      if not isinstance(key, str):
        raise TypeError("evidence payload keys must be strings")
      out[key] = _normalise(item)
    return out
  if isinstance(value, (list, tuple)):
    return [_normalise(item) for item in value]
  raise TypeError(
    f"evidence payload contains unsupported {type(value).__name__}; "
    "use JSON scalars, mappings, and sequences"
  )


def _strict_json_copy(value: object, path: str = "payload") -> object:
  """Copy already-decoded JSON without accepting Python-only lookalikes."""
  if value is None or type(value) in (str, bool, int):
    return value
  if type(value) is float:
    if not math.isfinite(value):
      raise ValueError(f"{path} contains a non-finite number")
    return value
  if type(value) is list:
    return [
      _strict_json_copy(item, f"{path}[{index}]")
      for index, item in enumerate(value)
    ]
  if type(value) is dict:
    out: Dict[str, object] = {}
    for key, item in value.items():
      if type(key) is not str:
        raise ValueError(f"{path} object keys must be strings")
      out[key] = _strict_json_copy(item, f"{path}.{key}")
    return out
  raise ValueError(
    f"{path} contains non-JSON type {type(value).__name__}; "
    "expected null, boolean, number, string, array, or object"
  )


class _ImmutableJSONMapping(Mapping[str, object]):
  """Read-only mapping that returns defensive copies of nested JSON containers."""

  def __init__(self, values: Mapping[str, object]):
    self.__values = {
      key: _freeze_json(item)
      for key, item in values.items()
    }

  def __getitem__(self, key: str) -> object:
    return _copy_frozen_json(self.__values[key])

  def __iter__(self) -> Iterator[str]:
    return iter(self.__values)

  def __len__(self) -> int:
    return len(self.__values)

  def _copy(self) -> Dict[str, object]:
    return {
      key: _copy_frozen_json(item)
      for key, item in self.__values.items()
    }

  def __repr__(self) -> str:
    return repr(self._copy())


def _freeze_json(value: object) -> object:
  """Recursively store a normalized JSON value without mutable containers."""
  if isinstance(value, Mapping):
    return _ImmutableJSONMapping(value)
  if isinstance(value, (list, tuple)):
    return tuple(_freeze_json(item) for item in value)
  return value


def _copy_frozen_json(value: object) -> object:
  """Expose ordinary JSON containers without exposing the sealed internal state."""
  if isinstance(value, _ImmutableJSONMapping):
    return value._copy()
  if isinstance(value, tuple):
    return [_copy_frozen_json(item) for item in value]
  return value


def _require_int(value: object, field: str) -> int:
  if type(value) is not int:
    raise ValueError(f"evidence event {field} must be an integer")
  return value


def _require_string(value: object, field: str, *, nonempty: bool = False) -> str:
  if type(value) is not str:
    raise ValueError(f"evidence event {field} must be a string")
  if nonempty and not value:
    raise ValueError(f"evidence event {field} must not be empty")
  return value


def _require_hash(value: object, field: str) -> str:
  chosen = _require_string(value, field)
  if not _HASH_PATTERN.fullmatch(chosen):
    raise ValueError(f"evidence event {field} must be 64 lowercase hex characters")
  return chosen


def _require_recorded_at(value: object) -> str:
  chosen = _require_string(value, "recorded_at")
  if not _RFC3339_PATTERN.fullmatch(chosen):
    raise ValueError("evidence event recorded_at must be an RFC 3339 date-time")
  try:
    datetime.fromisoformat(chosen.replace("Z", "+00:00"))
  except ValueError as exc:
    raise ValueError("evidence event recorded_at must be an RFC 3339 date-time") from exc
  return chosen


@dataclass(frozen=True)
class EvidenceEvent:
  """One immutable event in a hash chain."""

  sequence: int
  event_id: str
  recorded_at: str
  run_id: str
  kind: EventKind
  actor: str
  evidence_level: EvidenceLevel
  payload: Mapping[str, object]
  previous_hash: str
  event_hash: str
  schema_version: int = SCHEMA_VERSION

  def __post_init__(self) -> None:
    schema_version = _require_int(self.schema_version, "schema_version")
    if schema_version != SCHEMA_VERSION:
      raise ValueError(
        f"evidence event schema_version must be {SCHEMA_VERSION}, got {schema_version}"
      )
    sequence = _require_int(self.sequence, "sequence")
    if sequence < 0:
      raise ValueError("evidence event sequence must be at least zero")
    _require_string(self.event_id, "event_id", nonempty=True)
    _require_recorded_at(self.recorded_at)
    _require_string(self.run_id, "run_id", nonempty=True)
    if type(self.kind) is not EventKind:
      raise ValueError("evidence event kind must be an EventKind")
    _require_string(self.actor, "actor", nonempty=True)
    if type(self.evidence_level) is not EvidenceLevel:
      raise ValueError("evidence event evidence_level must be an EvidenceLevel")
    _require_hash(self.previous_hash, "previous_hash")
    _require_hash(self.event_hash, "event_hash")
    if not isinstance(self.payload, Mapping):
      raise TypeError("evidence event payload must be an object")
    normal_payload = _normalise(self.payload)
    if not isinstance(normal_payload, dict):
      raise TypeError("evidence event payload must be an object")
    canonical_json(normal_payload)
    object.__setattr__(self, "payload", _freeze_json(normal_payload))

  def body(self) -> Dict[str, object]:
    payload = _normalise(self.payload)
    assert isinstance(payload, dict)
    return {
      "schema_version": self.schema_version,
      "sequence": self.sequence,
      "event_id": self.event_id,
      "recorded_at": self.recorded_at,
      "run_id": self.run_id,
      "kind": self.kind.value,
      "actor": self.actor,
      "evidence_level": self.evidence_level.value,
      "payload": payload,
      "previous_hash": self.previous_hash,
    }

  def computed_hash(self) -> str:
    return digest(self.body())

  def to_dict(self) -> Dict[str, object]:
    out = self.body()
    out["event_hash"] = self.event_hash
    return out

  @classmethod
  def from_dict(cls, value: Mapping[str, object]) -> "EvidenceEvent":
    required = {
      "schema_version",
      "sequence",
      "event_id",
      "recorded_at",
      "run_id",
      "kind",
      "actor",
      "evidence_level",
      "payload",
      "previous_hash",
      "event_hash",
    }
    if any(type(key) is not str for key in value):
      raise ValueError("evidence event field names must be strings")
    fields = set(value)
    missing = sorted(required - fields)
    if missing:
      raise ValueError(f"evidence event is missing fields: {', '.join(missing)}")
    unknown = sorted(fields - required)
    if unknown:
      raise ValueError(f"evidence event has unknown fields: {', '.join(unknown)}")
    schema_version = _require_int(value["schema_version"], "schema_version")
    if schema_version != SCHEMA_VERSION:
      raise ValueError(
        f"evidence event schema_version must be {SCHEMA_VERSION}, got {schema_version}"
      )
    sequence = _require_int(value["sequence"], "sequence")
    if sequence < 0:
      raise ValueError("evidence event sequence must be at least zero")
    payload = value["payload"]
    if type(payload) is not dict:
      raise ValueError("evidence event payload must be an object")
    strict_payload = _strict_json_copy(payload)
    assert isinstance(strict_payload, dict)
    kind = _require_string(value["kind"], "kind")
    evidence_level = _require_string(value["evidence_level"], "evidence_level")
    return cls(
      schema_version=schema_version,
      sequence=sequence,
      event_id=_require_string(value["event_id"], "event_id", nonempty=True),
      recorded_at=_require_recorded_at(value["recorded_at"]),
      run_id=_require_string(value["run_id"], "run_id", nonempty=True),
      kind=EventKind(kind),
      actor=_require_string(value["actor"], "actor", nonempty=True),
      evidence_level=EvidenceLevel(evidence_level),
      payload=strict_payload,
      previous_hash=_require_hash(value["previous_hash"], "previous_hash"),
      event_hash=_require_hash(value["event_hash"], "event_hash"),
    )


@dataclass(frozen=True)
class VerificationReport:
  """The result of replaying the chain from genesis."""

  ok: bool
  event_count: int
  head_hash: str
  errors: Tuple[str, ...] = ()

  def require_valid(self) -> None:
    if not self.ok:
      raise ValueError("invalid evidence ledger: " + "; ".join(self.errors))


def _verify(events: Iterable[EvidenceEvent]) -> VerificationReport:
  previous = GENESIS_HASH
  errors: List[str] = []
  ids = set()
  count = 0
  for expected, event in enumerate(events):
    count += 1
    where = f"event {expected} ({event.event_id})"
    if event.schema_version != SCHEMA_VERSION:
      errors.append(
        f"{where} uses schema {event.schema_version}, expected {SCHEMA_VERSION}"
      )
    if event.sequence != expected:
      errors.append(f"{where} has sequence {event.sequence}")
    if event.event_id in ids:
      errors.append(f"{where} reuses an event_id")
    ids.add(event.event_id)
    if event.previous_hash != previous:
      errors.append(f"{where} does not point to the previous event")
    computed = event.computed_hash()
    if event.event_hash != computed:
      errors.append(f"{where} has an invalid digest")
    previous = event.event_hash
  return VerificationReport(
    ok=not errors,
    event_count=count,
    head_hash=previous,
    errors=tuple(errors),
  )


@contextmanager
def _exclusive_file(fh) -> Iterator[None]:
  """Best-effort process lock on Unix; the ledger still works on other platforms."""
  try:
    import fcntl
  except ImportError:  # pragma: no cover - Windows fallback
    yield
    return
  fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
  try:
    yield
  finally:
    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


class EvidenceLedger:
  """An in-memory or JSONL-backed append-only event ledger.

  On Unix, a file-backed append re-reads and verifies the file while holding ``flock``.
  That prevents two local processes from forking the chain from the same head and
  refuses to append to a ledger that no longer matches what was previously verified.
  Platforms without ``fcntl`` retain per-instance thread locking but require an
  externally enforced single-writer policy for a shared JSONL file.
  """

  def __init__(
    self,
    path: Optional[str] = None,
    events: Optional[Iterable[EvidenceEvent]] = None,
  ):
    if path is not None and events is not None:
      raise ValueError("construct an evidence ledger from a path or events, not both")
    self.path = os.path.abspath(os.path.expanduser(path)) if path else None
    self._events: List[EvidenceEvent] = []
    self._lock = threading.RLock()
    if self.path:
      parent = os.path.dirname(self.path)
      if parent:
        os.makedirs(parent, exist_ok=True)
      if os.path.exists(self.path):
        self._events = self._read_path(self.path)
    elif events is not None:
      self._events = list(events)
    self.verify().require_valid()

  @property
  def events(self) -> Tuple[EvidenceEvent, ...]:
    with self._lock:
      return tuple(self._events)

  @property
  def head_hash(self) -> str:
    with self._lock:
      return self._events[-1].event_hash if self._events else GENESIS_HASH

  def verify(self) -> VerificationReport:
    with self._lock:
      return _verify(self._events)

  def event(self, event_id: str) -> EvidenceEvent:
    with self._lock:
      for event in self._events:
        if event.event_id == event_id:
          return event
    raise KeyError(f"no evidence event '{event_id}'")

  def by_run(self, run_id: str) -> Tuple[EvidenceEvent, ...]:
    with self._lock:
      return tuple(event for event in self._events if event.run_id == run_id)

  def append(
    self,
    *,
    run_id: str,
    kind: EventKind,
    actor: str,
    evidence_level: EvidenceLevel,
    payload: Mapping[str, object],
    event_id: Optional[str] = None,
    recorded_at: Optional[str] = None,
  ) -> EvidenceEvent:
    """Append one event and return the sealed value."""
    return self._append(
      run_id=run_id,
      kind=kind,
      actor=actor,
      evidence_level=evidence_level,
      payload=payload,
      event_id=event_id,
      recorded_at=recorded_at,
      validate=None,
    )

  def append_transactionally(
    self,
    *,
    run_id: str,
    kind: EventKind,
    actor: str,
    evidence_level: EvidenceLevel,
    payload: Mapping[str, object],
    validate: Callable[[Tuple[EvidenceEvent, ...]], None],
    event_id: Optional[str] = None,
    recorded_at: Optional[str] = None,
  ) -> EvidenceEvent:
    """Append only after ``validate`` accepts the lock-time candidate chain.

    The callback receives an immutable tuple containing the latest verified durable
    events followed by the newly sealed candidate. It runs while the in-memory lock and,
    where available, the process file lock are still held and before any bytes or
    in-memory state are appended. Raising from the callback aborts the transaction
    without writing.

    Validation callbacks must be side-effect free and must not append to this ledger.
    """
    if not callable(validate):
      raise TypeError("validate must be callable")
    return self._append(
      run_id=run_id,
      kind=kind,
      actor=actor,
      evidence_level=evidence_level,
      payload=payload,
      event_id=event_id,
      recorded_at=recorded_at,
      validate=validate,
    )

  def _append(
    self,
    *,
    run_id: str,
    kind: EventKind,
    actor: str,
    evidence_level: EvidenceLevel,
    payload: Mapping[str, object],
    event_id: Optional[str],
    recorded_at: Optional[str],
    validate: Optional[Callable[[Tuple[EvidenceEvent, ...]], None]],
  ) -> EvidenceEvent:
    if not run_id.strip():
      raise ValueError("run_id must not be empty")
    if not actor.strip():
      raise ValueError("actor must not be empty")
    normal_payload = dict(_normalise(payload))
    with self._lock:
      if self.path:
        event = self._append_path(
          run_id=run_id,
          kind=kind,
          actor=actor,
          evidence_level=evidence_level,
          payload=normal_payload,
          event_id=event_id,
          recorded_at=recorded_at,
          validate=validate,
        )
        return event
      event = self._make_event(
        self._events,
        run_id,
        kind,
        actor,
        evidence_level,
        normal_payload,
        event_id,
        recorded_at,
      )
      if validate is not None:
        validate(tuple(self._events) + (event,))
      self._events.append(event)
      return event

  @staticmethod
  def _make_event(
    events: List[EvidenceEvent],
    run_id: str,
    kind: EventKind,
    actor: str,
    evidence_level: EvidenceLevel,
    payload: Dict[str, object],
    event_id: Optional[str],
    recorded_at: Optional[str],
  ) -> EvidenceEvent:
    if kind is EventKind.RUN_STARTED and any(
      event.run_id == run_id for event in events
    ):
      raise ValueError(
        f"run_id '{run_id}' already exists; RUN_STARTED must be the first and only "
        "start event for a physical attempt"
      )
    chosen_id = event_id or f"evt_{uuid.uuid4().hex}"
    if any(event.event_id == chosen_id for event in events):
      raise ValueError(f"duplicate evidence event_id '{chosen_id}'")
    timestamp = recorded_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    body = {
      "schema_version": SCHEMA_VERSION,
      "sequence": len(events),
      "event_id": chosen_id,
      "recorded_at": timestamp,
      "run_id": run_id,
      "kind": kind.value,
      "actor": actor,
      "evidence_level": evidence_level.value,
      "payload": payload,
      "previous_hash": events[-1].event_hash if events else GENESIS_HASH,
    }
    return EvidenceEvent(
      schema_version=SCHEMA_VERSION,
      sequence=len(events),
      event_id=chosen_id,
      recorded_at=timestamp,
      run_id=run_id,
      kind=kind,
      actor=actor,
      evidence_level=evidence_level,
      payload=payload,
      previous_hash=str(body["previous_hash"]),
      event_hash=digest(body),
    )

  def _append_path(
    self,
    *,
    run_id: str,
    kind: EventKind,
    actor: str,
    evidence_level: EvidenceLevel,
    payload: Dict[str, object],
    event_id: Optional[str],
    recorded_at: Optional[str],
    validate: Optional[Callable[[Tuple[EvidenceEvent, ...]], None]],
  ) -> EvidenceEvent:
    assert self.path is not None
    mode = "r+" if self._events else "a+"
    try:
      fh = open(self.path, mode, encoding="utf-8")
    except FileNotFoundError as exc:
      raise ValueError(
        "on-disk evidence ledger disappeared after it was loaded; refusing to append"
      ) from exc
    with fh:
      with _exclusive_file(fh):
        fh.seek(0)
        contents = fh.read()
        events = self._read_lines(contents.splitlines(keepends=True))
        _verify(events).require_valid()
        self._require_compatible_snapshot(events)
        event = self._make_event(
          events,
          run_id,
          kind,
          actor,
          evidence_level,
          payload,
          event_id,
          recorded_at,
        )
        if validate is not None:
          validate(tuple(events) + (event,))
        fh.seek(0, os.SEEK_END)
        if contents and not contents.endswith(("\n", "\r")):
          fh.write("\n")
        fh.write(canonical_json(event.to_dict()) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
        self._events = events + [event]
        return event

  def _require_compatible_snapshot(self, events: List[EvidenceEvent]) -> None:
    """Refuse a valid chain that rewrites or removes this instance's history."""
    for index, (known, current) in enumerate(zip(self._events, events)):
      if known != current:
        raise ValueError(
          "on-disk evidence ledger diverged from this ledger snapshot at "
          f"event {index}; refusing to append"
        )
    if len(events) < len(self._events):
      raise ValueError(
        "on-disk evidence ledger was truncated after it was loaded; "
        "refusing to append"
      )

  @classmethod
  def _read_path(cls, path: str) -> List[EvidenceEvent]:
    with open(path, encoding="utf-8") as fh:
      return cls._read_lines(fh)

  @staticmethod
  def _read_lines(fh) -> List[EvidenceEvent]:
    out: List[EvidenceEvent] = []
    for line_number, line in enumerate(fh, 1):
      if not line.strip():
        continue
      try:
        value = json.loads(line)
        if not isinstance(value, dict):
          raise ValueError("event is not an object")
        out.append(EvidenceEvent.from_dict(value))
      except (ValueError, TypeError, KeyError) as exc:
        raise ValueError(f"invalid evidence JSONL at line {line_number}: {exc}") from exc
    return out
