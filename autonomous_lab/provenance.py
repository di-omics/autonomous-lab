"""Sample tracking: what happened to this material, who says so, and where the record lies.

A run ledger is the part of an autonomous lab that looks easiest and is quietly the
hardest, because the easy version records what the SOFTWARE INTENDED and presents it as
what HAPPENED. Those diverge exactly when it matters. A transfer that was commanded and
never executed appears in a naive ledger as a completed transfer, and the record is then
worse than no record, because it is trusted.

So every event here carries who attests to it:

  CONFIRMED  an instrument reported the action completed, and the report was read back.
  ASSERTED   software commanded it and nothing contradicted it. This is not evidence.
  WITNESSED  a human attests to it. Real, unverifiable, and the only thing available for
             the bench steps -- which is why they are the weak links in the chain.

The second idea is CUSTODY, and it is where a lab's provenance actually breaks. Between
two instruments a plate is carried by a human. No instrument observes the transfer. The
binding between the physical plate now sitting on the STAR deck and the record that says
what is in it rests entirely on the human having carried the right plate. Software cannot
close that gap by being careful; only a barcode read at both ends, or a plate mover that
reports the move, closes it.

The single-cell genomics protocol has five such hops. That means the chain of custody has
five holes, and they sit exactly where the ledger's `handoffs()` already counts physical
transfers -- so this module resolves them from that same computation rather than a second
list that could disagree.

The hash chain is tamper-evidence, not security. It proves the record was not edited after
the fact, which is what an audit needs. It proves nothing about whether the recorded events
are true, and pretending otherwise would be the same category of overclaim this package
exists to refuse.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple


class Attestation(str, Enum):
  """Who says this happened, and how much that is worth. Ordered weakest to strongest."""

  ASSERTED = "asserted"  # software sent the command; nothing read back
  WITNESSED = "witnessed"  # a human attests to it
  CONFIRMED = "confirmed"  # the instrument reported completion and it was read

  @property
  def is_evidence(self) -> bool:
    """ASSERTED is not evidence. It is a log line about intent.

    Drawn here rather than left to the reader because the whole failure mode is that a
    command log reads like a record of events.
    """
    return self is not Attestation.ASSERTED


class Actor(str, Enum):
  MACHINE = "machine"
  HUMAN = "human"
  AGENT = "agent"  # a model proposed it; a gate or a human permitted it


@dataclass(frozen=True)
class Event:
  """One recorded action. Immutable, hash-chained to its predecessor.

  `decision` records what the intelligence layer concluded after the action, when a gate
  ran. Recording action and decision in the same chain is deliberate: replaying a run
  requires knowing not just what the lab did but why it continued.
  """

  seq: int
  step_op: str
  instrument: str
  actor: Actor
  attestation: Attestation
  consumes: Tuple[str, ...] = ()
  produces: Tuple[str, ...] = ()
  evidence: str = ""
  decision: Optional[str] = None
  timestamp: Optional[str] = None  # ISO 8601; optional so records stay reproducible in tests
  prev_hash: str = ""
  digest: str = ""

  def payload(self) -> str:
    """The canonical bytes this event's digest covers. Sorted keys, so it is stable."""
    return json.dumps(
      {
        "seq": self.seq,
        "step_op": self.step_op,
        "instrument": self.instrument,
        "actor": self.actor.value,
        "attestation": self.attestation.value,
        "consumes": list(self.consumes),
        "produces": list(self.produces),
        "evidence": self.evidence,
        "decision": self.decision,
        "timestamp": self.timestamp,
        "prev_hash": self.prev_hash,
      },
      sort_keys=True,
      separators=(",", ":"),
    )

  def compute_digest(self) -> str:
    return hashlib.sha256(self.payload().encode("utf-8")).hexdigest()


@dataclass
class RunRecord:
  """An append-only, tamper-evident record of one run.

  Append-only is enforced by the API rather than by convention: there is no method that
  edits or removes an event, and `verify()` detects any edit made behind the API's back.
  """

  run_id: str
  events: List[Event] = field(default_factory=list)

  def append(
    self,
    step_op: str,
    instrument: str,
    actor: Actor,
    attestation: Attestation,
    consumes: Sequence[str] = (),
    produces: Sequence[str] = (),
    evidence: str = "",
    decision: Optional[str] = None,
    timestamp: Optional[str] = None,
  ) -> Event:
    prev = self.events[-1].digest if self.events else ""
    ev = Event(
      seq=len(self.events),
      step_op=step_op,
      instrument=instrument,
      actor=actor,
      attestation=attestation,
      consumes=tuple(consumes),
      produces=tuple(produces),
      evidence=evidence,
      decision=decision,
      timestamp=timestamp,
      prev_hash=prev,
    )
    ev = Event(**{**ev.__dict__, "digest": ev.compute_digest()})
    self.events.append(ev)
    return ev

  def verify(self) -> Tuple[bool, str]:
    """Recompute the chain. Returns (ok, reason).

    Catches both an edited event and a removed one: an edit changes a digest, and a
    removal breaks the prev_hash link of whatever followed it.
    """
    prev = ""
    for i, ev in enumerate(self.events):
      if ev.seq != i:
        return False, f"event {i} carries seq {ev.seq}; the chain has been reordered or spliced"
      if ev.prev_hash != prev:
        return False, f"event {i} does not link to its predecessor; an event was removed or edited"
      if ev.digest != ev.compute_digest():
        return False, f"event {i} ('{ev.step_op}') was edited after it was recorded"
      prev = ev.digest
    return True, f"{len(self.events)} event(s) verified"

  def unevidenced(self) -> List[Event]:
    """Events recorded on nothing but software intent."""
    return [e for e in self.events if not e.attestation.is_evidence]

  def to_json(self) -> str:
    return json.dumps(
      {
        "run_id": self.run_id,
        "events": [json.loads(e.payload()) | {"digest": e.digest} for e in self.events],
      },
      indent=2,
    )


# -- custody -------------------------------------------------------------------


@dataclass(frozen=True)
class CustodyGap:
  """A point where the physical chain of custody is unobserved.

  `closes_it` is deliberately concrete. "Improve tracking" is not an action; "read a
  barcode at both ends of this hop" is.
  """

  artifact: str
  from_instrument: str
  to_instrument: str
  reason: str
  closes_it: str


def custody_gaps(ledger) -> List[CustodyGap]:
  """Every physical hop in a costed protocol, as an unobserved custody transfer.

  Resolved from the ledger's own `handoffs()` rather than a parallel list. That matters:
  the physical-hop count is already the number this repo reports as irreducible without a
  plate mover, and provenance breaking at exactly those points is the same fact seen from
  the data side. Two independent lists would eventually disagree, and the disagreement
  would be invisible.
  """
  out: List[CustodyGap] = []
  for artifact, src, dst in ledger.handoffs():
    out.append(
      CustodyGap(
        artifact=artifact,
        from_instrument=src,
        to_instrument=dst,
        reason=(
          f"'{artifact}' is carried from {src} to {dst} by a human. No instrument observes "
          "the transfer, so the record's claim about which plate arrived is an assertion"
        ),
        closes_it=(
          "read a machine-readable label on the plate at both ends, or move it with an arm "
          "that reports the move; nothing in software closes this"
        ),
      )
    )
  return out


@dataclass
class ProvenanceReport:
  """What this lab could actually prove about a run afterwards."""

  protocol: str
  gaps: List[CustodyGap]
  steps_total: int
  steps_confirmable: int

  @property
  def unbroken(self) -> bool:
    return not self.gaps

  def counts(self) -> Dict[str, int]:
    return {
      "custody_gaps": len(self.gaps),
      "steps_total": self.steps_total,
      "steps_confirmable": self.steps_confirmable,
      "steps_asserted_only": self.steps_total - self.steps_confirmable,
    }


def provenance_report(ledger) -> ProvenanceReport:
  """How much of a run this lab could evidence, and where the chain breaks.

  A step is confirmable when the instrument reports completion in a way the layer reads
  back -- which today means the steps the ledger already calls AUTOMATED or SUPERVISED.
  Everything else would enter the record as ASSERTED or WITNESSED, and neither is an
  instrument's word.
  """
  from .model import Verdict

  confirmable = sum(
    1 for r in ledger.rows if r.verdict in (Verdict.AUTOMATED, Verdict.SUPERVISED)
  )
  return ProvenanceReport(
    protocol=ledger.protocol.name,
    gaps=custody_gaps(ledger),
    steps_total=len(ledger.rows),
    steps_confirmable=confirmable,
  )


def record_from_run(report, run_id: str = "run") -> RunRecord:
  """Build a run record from an executor RunReport.

  Attestation follows what actually happened rather than what was planned: a step the
  executor really performed and read data back from is CONFIRMED, and a step that was only
  previewed is ASSERTED. A dry run therefore produces a record with no evidence in it at
  all, which is the correct and slightly uncomfortable result.
  """
  rec = RunRecord(run_id=run_id)
  for res in report.results:
    rec.append(
      step_op=res.step.op,
      instrument=res.step.instrument,
      actor=Actor.MACHINE,
      attestation=Attestation.CONFIRMED if res.executed else Attestation.ASSERTED,
      consumes=res.step.consumes,
      produces=res.step.produces,
      evidence=res.note,
    )
  if report.handoff is not None:
    rec.append(
      step_op=report.handoff.step.op,
      instrument=report.handoff.step.instrument,
      actor=Actor.HUMAN,
      attestation=Attestation.WITNESSED,
      evidence=f"run stopped: {report.handoff.reason}",
      decision="escalate",
    )
  return rec
