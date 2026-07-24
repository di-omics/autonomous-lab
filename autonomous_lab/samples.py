"""Sample identity and lineage: what this material is, where it came from, and who says so.

The ledger reasons about artifact *types* -- "a library plate" -- because that is all a
protocol knows before it runs. This module reasons about the individual material actually
on the bench, which is what you need the moment a result comes back wrong and somebody
asks which well it came from.

Three ideas carry the module, and all three exist to stop a provenance chain from
claiming more than it can support.

  Attribution. Pooling is not a transfer, it is a loss of resolution. Ninety-six wells go
  into one tube and a downstream measurement no longer refers to any one of them. If each
  input carried a recorded index the resolution is recoverable by demultiplexing; if it
  did not, it is gone permanently and no amount of record-keeping brings it back. The
  lineage tracks which of those two happened, because the difference decides whether a bad
  sequencing result can be blamed on a well or only on the whole plate.

  Witness. Every event is attested by something: a run card that executed and logged it, a
  human who says they did it, or nothing at all. A chain reconstructed from a protocol is
  INFERRED, and inferred is not evidence -- it is a statement that the plan said this
  should have happened. Given how little of this lab runs headless today, honest chains
  here are mostly operator-attested, and the module reports the weakest link rather than
  the best one.

  Consumption. An aliquot the mass spec drew does not come back. Material that has been
  consumed cannot be an input to a later step, and saying so catches a class of protocol
  bug that otherwise surfaces as a confusing empty vial at the bench.

Nothing here talks to an instrument. It is a record of physical facts, and its only job is
to refuse to overstate them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence, Set, Tuple


class Witness(str, Enum):
  """Who attests that an event happened. Ordered weakest to strongest.

  The ordering is load-bearing: a chain is only as good as its weakest link, so
  `Lineage.weakest_witness` takes a minimum over the chain rather than reporting whether
  any step was machine-recorded.
  """

  INFERRED = "inferred"  # nobody recorded it; the protocol says it must have happened
  OPERATOR = "operator"  # a human performed it and attested to it afterwards
  MACHINE = "machine"  # a run card performed it and wrote the record itself

  @property
  def rank(self) -> int:
    return {"inferred": 0, "operator": 1, "machine": 2}[self.value]


class Attribution(str, Enum):
  """Whether a measurement on this material can be traced back to one source sample."""

  ADDRESSABLE = "addressable"  # exactly one source; a result attributes cleanly
  INDEXED = "indexed"  # pooled, but every input carries a recorded index; demux recovers it
  CONFOUNDED = "confounded"  # pooled with no index map; per-source attribution is gone


class EventKind(str, Enum):
  ACQUIRE = "acquire"  # material enters the lab
  DERIVE = "derive"  # one in, one out: lyse, amplify, clean up
  SPLIT = "split"  # one in, many out: a sort, an aliquot series
  POOL = "pool"  # many in, one out: the resolution-losing operation
  MOVE = "move"  # custody: the same material, somewhere else
  CONSUME = "consume"  # material destroyed by measuring it


@dataclass(frozen=True)
class Sample:
  """One identifiable piece of material.

  `plate` and `well` are optional because not everything is in a plate, but when they are
  set they are what makes a confounded pool concrete: "all 96 wells of plate P1" is a
  useful thing to be able to say when a run fails.
  """

  id: str
  label: str = ""
  plate: Optional[str] = None
  well: Optional[str] = None
  note: str = ""

  @property
  def address(self) -> str:
    if self.plate and self.well:
      return f"{self.plate}:{self.well}"
    return self.id


@dataclass(frozen=True)
class Event:
  """One thing that happened to some material.

  `index_map` is only meaningful on a POOL and is the whole reason pooling is survivable:
  it maps each input sample id to the barcode that will let a demultiplexer separate it
  again. A POOL without one is a permanent loss and the lineage says so.
  """

  kind: EventKind
  parents: Tuple[str, ...]
  children: Tuple[str, ...]
  step: str
  instrument: str
  witness: Witness
  note: str = ""
  index_map: Dict[str, str] = field(default_factory=dict)


class LineageError(ValueError):
  """A record that contradicts physical reality: unknown material, or material reused
  after it was consumed. Raised rather than recorded, because a provenance store that
  accepts an impossible history is worse than no store at all."""


class Lineage:
  """An append-only record of what happened to real material.

  Append-only is not a storage detail. Provenance that can be edited after a result comes
  back is not provenance, so there is no method here that rewrites or deletes an event.
  """

  def __init__(self, name: str = "lineage"):
    self.name = name
    self.samples: Dict[str, Sample] = {}
    self.events: List[Event] = []
    self._consumed: Set[str] = set()

  # -- recording -------------------------------------------------------------

  def _require(self, sid: str) -> Sample:
    if sid not in self.samples:
      raise LineageError(f"unknown sample '{sid}'")
    if sid in self._consumed:
      raise LineageError(
        f"sample '{sid}' was consumed by an earlier step and cannot be used again"
      )
    return self.samples[sid]

  def _mint(self, sample: Sample) -> Sample:
    if sample.id in self.samples:
      raise LineageError(f"sample '{sample.id}' already exists; ids are permanent")
    self.samples[sample.id] = sample
    return sample

  def acquire(
    self,
    sid: str,
    label: str = "",
    witness: Witness = Witness.OPERATOR,
    plate: Optional[str] = None,
    well: Optional[str] = None,
    note: str = "",
  ) -> Sample:
    """Material entering the lab. The root of every chain.

    Defaults to OPERATOR because somebody physically carried it in; nothing machine-
    witnessed happens before an instrument has touched it.
    """
    s = self._mint(Sample(id=sid, label=label, plate=plate, well=well, note=note))
    self.events.append(
      Event(EventKind.ACQUIRE, (), (sid,), "acquire", "", witness, note)
    )
    return s

  def derive(
    self,
    parent: str,
    child: str,
    step: str,
    instrument: str,
    witness: Witness = Witness.INFERRED,
    label: str = "",
    note: str = "",
  ) -> Sample:
    """One in, one out. Attribution survives untouched."""
    p = self._require(parent)
    s = self._mint(
      Sample(id=child, label=label or p.label, plate=p.plate, well=p.well, note=note)
    )
    self.events.append(
      Event(EventKind.DERIVE, (parent,), (child,), step, instrument, witness, note)
    )
    return s

  def split(
    self,
    parent: str,
    children: Sequence[Tuple[str, Optional[str], Optional[str]]],
    step: str,
    instrument: str,
    witness: Witness = Witness.INFERRED,
    note: str = "",
  ) -> List[Sample]:
    """One in, many out: a sort into wells, an aliquot series.

    `children` is (id, plate, well) so a sort can address its outputs. Splitting does not
    cost attribution -- each child has exactly one parent -- which is precisely why a
    sorter is easy to trace and a pooling step is not.
    """
    self._require(parent)
    out: List[Sample] = []
    ids: List[str] = []
    for cid, plate, well in children:
      out.append(self._mint(Sample(id=cid, plate=plate, well=well)))
      ids.append(cid)
    self.events.append(
      Event(EventKind.SPLIT, (parent,), tuple(ids), step, instrument, witness, note)
    )
    return out

  def pool(
    self,
    parents: Sequence[str],
    child: str,
    step: str,
    instrument: str,
    witness: Witness = Witness.INFERRED,
    index_map: Optional[Dict[str, str]] = None,
    label: str = "",
    note: str = "",
  ) -> Sample:
    """Many in, one out. The operation that costs resolution.

    Pass `index_map` only if an index really was added per input and recorded. It is
    checked against the parent list rather than trusted: a partial map is worse than none,
    because it would let a demultiplexer silently drop the inputs it cannot name.
    """
    if len(parents) < 2:
      raise LineageError("a pool needs at least two inputs; use derive() for one")
    for pid in parents:
      self._require(pid)
    if index_map is not None:
      missing = [p for p in parents if p not in index_map]
      if missing:
        raise LineageError(
          f"index_map covers {len(index_map)} of {len(parents)} inputs; "
          f"{len(missing)} would be unrecoverable after pooling (first: {missing[0]}). "
          "Record every index or record none."
        )
      seen: Dict[str, str] = {}
      for pid in parents:
        idx = index_map[pid]
        if idx in seen:
          raise LineageError(
            f"index '{idx}' is assigned to both '{seen[idx]}' and '{pid}'; "
            "a duplicated index cannot be demultiplexed"
          )
        seen[idx] = pid
    s = self._mint(Sample(id=child, label=label, note=note))
    self.events.append(
      Event(
        EventKind.POOL,
        tuple(parents),
        (child,),
        step,
        instrument,
        witness,
        note,
        dict(index_map) if index_map else {},
      )
    )
    return s

  def move(
    self,
    sid: str,
    frm: str,
    to: str,
    witness: Witness = Witness.OPERATOR,
    note: str = "",
  ) -> None:
    """A custody hop: the same material, carried somewhere else.

    Recorded as its own event kind because a hop is where a chain most often breaks. The
    ledger counts these from the protocol; here they carry a witness, and a hop nobody
    witnessed is a hole in the provenance even though nothing about the material changed.
    """
    self._require(sid)
    self.events.append(
      Event(EventKind.MOVE, (sid,), (sid,), f"{frm} -> {to}", to, witness, note)
    )

  def consume(
    self,
    sid: str,
    step: str,
    instrument: str,
    witness: Witness = Witness.INFERRED,
    note: str = "",
  ) -> None:
    """Material destroyed by measuring it. It cannot be an input again."""
    self._require(sid)
    self.events.append(
      Event(EventKind.CONSUME, (sid,), (), step, instrument, witness, note)
    )
    self._consumed.add(sid)

  # -- reading back ----------------------------------------------------------

  def chain(self, sid: str) -> List[Event]:
    """Every event that contributed to this material, oldest first."""
    if sid not in self.samples:
      raise LineageError(f"unknown sample '{sid}'")
    wanted = self.ancestors(sid) | {sid}
    return [e for e in self.events if set(e.children) & wanted or set(e.parents) & wanted]

  def ancestors(self, sid: str) -> Set[str]:
    """Every sample this one descends from."""
    if sid not in self.samples:
      raise LineageError(f"unknown sample '{sid}'")
    parent_of: Dict[str, Tuple[str, ...]] = {}
    for e in self.events:
      if e.kind in (EventKind.MOVE, EventKind.CONSUME):
        continue
      for c in e.children:
        parent_of[c] = e.parents
    out: Set[str] = set()
    stack = list(parent_of.get(sid, ()))
    while stack:
      cur = stack.pop()
      if cur in out:
        continue
      out.add(cur)
      stack.extend(parent_of.get(cur, ()))
    return out

  def sources(self, sid: str) -> List[str]:
    """The acquired roots this material descends from, sorted."""
    acquired = {e.children[0] for e in self.events if e.kind is EventKind.ACQUIRE}
    roots = (self.ancestors(sid) | {sid}) & acquired
    return sorted(roots)

  def attribution(self, sid: str) -> Attribution:
    """Whether a result on this material points at one source, or at a crowd.

    A pool is INDEXED only if every pooling event in its history recorded a full index
    map. One unindexed pool anywhere upstream confounds everything downstream of it, and
    a later indexed pool does not repair that.
    """
    pools = [
      e
      for e in self.chain(sid)
      if e.kind is EventKind.POOL and (set(e.children) & (self.ancestors(sid) | {sid}))
    ]
    if not pools:
      return Attribution.ADDRESSABLE
    if all(e.index_map for e in pools):
      return Attribution.INDEXED
    return Attribution.CONFOUNDED

  def blame(self, sid: str) -> List[str]:
    """The samples a bad result here cannot be told apart from.

    Deliberately not `sources()`. Every well of a single-cell plate descends from the one
    suspension that was loaded, so the acquired root is always a set of size one and
    blaming it says nothing. What a failed result actually implicates is the set of
    contributors a pool made indistinguishable: the inputs to every pool upstream that are
    not themselves pool outputs.

    One id means the result is actionable -- go look at that well. Ninety-six means the
    plate is the finest resolution available and the run taught you less than it appeared
    to. `attribution` says whether the list can still be narrowed by demultiplexing.
    """
    lineage_of = self.ancestors(sid) | {sid}
    pools = [
      e for e in self.events if e.kind is EventKind.POOL and set(e.children) & lineage_of
    ]
    if not pools:
      return [sid]
    pooled_outputs = {c for e in pools for c in e.children}
    merged = {p for e in pools for p in e.parents}
    return sorted(merged - pooled_outputs)

  def weakest_witness(self, sid: str) -> Witness:
    """The weakest attestation anywhere in this material's history.

    Reported instead of the strongest on purpose. A chain with one inferred hop in the
    middle is an inferred chain, however well instrumented the rest of it was.
    """
    chain = self.chain(sid)
    if not chain:
      return Witness.INFERRED
    return min((e.witness for e in chain), key=lambda w: w.rank)

  def unwitnessed_moves(self) -> List[Event]:
    """Custody hops nobody attested to. Holes in the chain, listed."""
    return [
      e for e in self.events if e.kind is EventKind.MOVE and e.witness is Witness.INFERRED
    ]

  def summary(self, sid: str) -> Dict[str, object]:
    """Everything worth knowing about one sample's provenance, in one dict."""
    attr = self.attribution(sid)
    blame = self.blame(sid)
    return {
      "sample": sid,
      "address": self.samples[sid].address if sid in self.samples else sid,
      "attribution": attr.value,
      # How many distinct contributors a bad result here cannot be told apart from. 1 is
      # an actionable result; anything larger is the resolution the run actually has.
      "indistinguishable": len(blame),
      "blame": blame,
      "roots": self.sources(sid),
      "weakest_witness": self.weakest_witness(sid).value,
      "events": len(self.chain(sid)),
      "consumed": sid in self._consumed,
    }


def wells(rows: str = "ABCDEFGH", cols: int = 12) -> List[str]:
  """A1..H12 in column-major order, which is how a plate is actually pipetted."""
  return [f"{r}{c}" for c in range(1, cols + 1) for r in rows]


def reference_lineage(n_cells: int = 96, indexed: bool = False) -> Lineage:
  """The single-cell genomics run, as material rather than as a plan.

  Mirrors `protocols.SINGLE_CELL_GENOMICS`: a suspension is sorted into wells, each well
  is carried through lysis, amplification, and cleanup, and the plate is pooled into one
  library that gets sequenced.

  Every event is INFERRED, and that is the honest setting. This is reconstructed from the
  protocol, not read out of a run record -- no step in that protocol has a machine that
  writes provenance today. Flip `indexed` to see the only thing that decides whether a bad
  library can be traced back to a well.
  """
  lin = Lineage(name="single_cell_genomics")
  lin.acquire("suspension", label="cell suspension", witness=Witness.OPERATOR)
  addrs = wells()[:n_cells]
  lin.split(
    "suspension",
    [(f"cell_{w}", "P1", w) for w in addrs],
    step="start_sort",
    instrument="namocell",
  )
  for w in addrs:
    lin.derive(f"cell_{w}", f"lysate_{w}", "pta_wga_lysis", "star")
    lin.derive(f"lysate_{w}", f"amp_{w}", "targeted_pcr_round1", "odtc")
    lin.derive(f"amp_{w}", f"lib_{w}", "targeted_pcr_round1_cleanup", "star")
  index_map = {f"lib_{w}": f"IDX{i:03d}" for i, w in enumerate(addrs)} if indexed else None
  lin.pool(
    [f"lib_{w}" for w in addrs],
    "pool",
    step="library_pool",
    instrument="star",
    index_map=index_map,
    label="pooled library",
  )
  return lin
