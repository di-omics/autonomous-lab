"""The run record: an append-only, hash-chained account of what was proposed and decided.

A run that cannot be reconstructed afterwards did not really happen, in the only sense
that matters to somebody reading a result six months later and asking whether to believe
it. This module is where every proposal, gate decision, measurement, and refusal lands, in
order, in a form that makes a later edit detectable.

Each entry carries the digest of the one before it, so the file is a chain. Change a
threshold in entry 3 and every digest from 3 onward stops matching; delete an entry and
the sequence breaks; reorder two and the links break. `verify()` reports the first entry
where the chain stops holding.

What that is worth, stated plainly, because a tamper-evident log invites more faith than
it has earned:

  It detects edits to a written record. Somebody who changes a stored decision after a
  result came back is caught, which is the failure this is actually aimed at.

  It does NOT make the record true. Nothing in a log can. If the writer records a
  measurement that never happened, the chain will protect that lie as carefully as it
  protects the truth. That is what the evidence tiers in `acceptance` are for: they decide
  what a value is allowed to claim about itself before it ever reaches this file.

  It does NOT stop the author from rewriting the whole file. Whoever holds the file can
  recompute every digest from scratch. A chain defends against edits, not against a
  dishonest author, and closing that gap needs an external anchor -- a countersignature or
  a timestamp published somewhere the author does not control. `seal()` returns the head
  digest precisely so it can be handed to something outside this process. Until it is,
  what you have is an internally consistent record, and calling it more than that would be
  the overclaim this package exists to refuse.

Stdlib only: hashlib and json. A run record is readable with `cat` and checkable by
anybody who has the file, which is most of the point.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Callable, Dict, Iterator, List, Optional

GENESIS = ""  # the `prev` of the first entry: there is nothing before it


def canonical(obj: object) -> str:
  """A byte-stable JSON rendering, so the same content always hashes the same.

  Sorted keys and tight separators: without both, two records with identical content but
  different dict ordering would produce different digests, and the chain would report
  tampering on a file nobody touched.
  """
  return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest_of(seq: int, kind: str, payload: object, at: float, prev: str) -> str:
  return hashlib.sha256(
    canonical({"seq": seq, "kind": kind, "payload": payload, "at": at, "prev": prev}).encode()
  ).hexdigest()


@dataclass(frozen=True)
class Entry:
  """One recorded fact. Immutable by construction; the chain assumes it."""

  seq: int
  kind: str
  payload: Dict[str, object]
  at: float
  prev: str
  digest: str

  def to_dict(self) -> Dict[str, object]:
    return {
      "seq": self.seq,
      "kind": self.kind,
      "payload": self.payload,
      "at": self.at,
      "prev": self.prev,
      "digest": self.digest,
    }

  @classmethod
  def from_dict(cls, d: Dict[str, object]) -> "Entry":
    return cls(
      seq=int(d["seq"]),
      kind=str(d["kind"]),
      payload=dict(d["payload"]),  # type: ignore[arg-type]
      at=float(d["at"]),
      prev=str(d["prev"]),
      digest=str(d["digest"]),
    )


@dataclass(frozen=True)
class ChainCheck:
  """The result of verifying a record. `ok` is the only thing most callers need; the rest
  is for saying exactly where and how it broke."""

  ok: bool
  entries: int
  broken_at: Optional[int] = None
  reason: str = ""

  def render(self) -> str:
    if self.ok:
      return f"chain intact: {self.entries} entries"
    return f"chain BROKEN at entry {self.broken_at}: {self.reason}"


class RunRecord:
  """An append-only record of one run.

  There is no update, no delete, and no method that takes an entry index. That is not an
  oversight to be fixed later: a provenance store with an edit path is a store whose
  contents are a matter of opinion. Corrections are appended as new entries that reference
  the old ones, which is also how a lab notebook has always worked.
  """

  def __init__(self, run_id: str, clock: Optional[Callable[[], float]] = None):
    self.run_id = run_id
    self._clock = clock or time.time
    self.entries: List[Entry] = []

  # -- writing ---------------------------------------------------------------

  def append(self, kind: str, **payload: object) -> Entry:
    """Record one fact. Returns the entry, whose digest is now the chain head."""
    prev = self.entries[-1].digest if self.entries else GENESIS
    seq = len(self.entries)
    at = float(self._clock())
    # Round-trip the payload through canonical JSON now rather than at write time, so a
    # value that cannot be serialized fails here -- pointing at the caller that supplied
    # it -- instead of at some later flush with no context left.
    try:
      payload = json.loads(canonical(payload))
    except (TypeError, ValueError) as e:
      raise TypeError(f"record payload for '{kind}' is not JSON-serializable: {e}") from e
    entry = Entry(
      seq=seq,
      kind=kind,
      payload=payload,
      at=at,
      prev=prev,
      digest=digest_of(seq, kind, payload, at, prev),
    )
    self.entries.append(entry)
    return entry

  def seal(self) -> str:
    """The head digest: the one value that commits to the entire record.

    Publish this, countersign it, or write it somewhere this process cannot reach. It is
    what turns "internally consistent" into evidence, and until it leaves the machine that
    wrote it, the record proves nothing to a skeptic.
    """
    return self.entries[-1].digest if self.entries else GENESIS

  # -- reading back ----------------------------------------------------------

  def verify(self) -> ChainCheck:
    """Recompute every link. Reports the first entry that does not hold."""
    prev = GENESIS
    for i, e in enumerate(self.entries):
      if e.seq != i:
        return ChainCheck(False, len(self.entries), i, f"sequence is {e.seq}, expected {i}")
      if e.prev != prev:
        return ChainCheck(
          False, len(self.entries), i, "prev does not match the previous entry's digest"
        )
      want = digest_of(e.seq, e.kind, e.payload, e.at, e.prev)
      if want != e.digest:
        return ChainCheck(
          False, len(self.entries), i, "content does not match its digest; this entry was edited"
        )
      prev = e.digest
    return ChainCheck(True, len(self.entries))

  def of_kind(self, kind: str) -> List[Entry]:
    return [e for e in self.entries if e.kind == kind]

  def __iter__(self) -> Iterator[Entry]:
    return iter(self.entries)

  def __len__(self) -> int:
    return len(self.entries)

  # -- persistence -----------------------------------------------------------

  def to_jsonl(self, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
      fh.write(canonical({"run_id": self.run_id, "kind": "__header__"}) + "\n")
      for e in self.entries:
        fh.write(canonical(e.to_dict()) + "\n")

  @classmethod
  def from_jsonl(cls, path: str) -> "RunRecord":
    """Load a record. Does not verify it -- call `verify()` and look at the answer.

    Kept separate on purpose. A loader that silently refused a broken chain would deny
    you the one thing you want when a chain is broken, which is to read it and find out
    what was changed.
    """
    with open(path, encoding="utf-8") as fh:
      lines = [ln for ln in (line.strip() for line in fh) if ln]
    if not lines:
      raise ValueError(f"{path} is empty; a run record has at least a header")
    header = json.loads(lines[0])
    rec = cls(run_id=str(header.get("run_id", "unknown")))
    rec.entries = [Entry.from_dict(json.loads(ln)) for ln in lines[1:]]
    return rec

  # -- reporting -------------------------------------------------------------

  def render(self) -> str:
    check = self.verify()
    lines = [f"run record: {self.run_id}  ({len(self.entries)} entries)", ""]
    for e in self.entries:
      detail = ", ".join(f"{k}={v}" for k, v in sorted(e.payload.items()) if k != "detail")
      lines.append(f"  {e.seq:3d}. {e.kind:<18} {detail[:96]}")
    lines.append("")
    lines.append(f"  {check.render()}")
    lines.append(f"  head {self.seal()[:16]}...  (publish this to make it evidence)")
    return "\n".join(lines)
