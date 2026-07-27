"""Sample identity: which cell a read came from, and whether that can be proven.

Every other layer in this package reasons about CONTAINERS. The ledger costs a plate hop,
provenance records that `library_plate` moved from the STAR to the reader, and both are
correct. But no experiment's conclusion is about a plate. The claim a single-cell run
exists to make is *this variant was in this cell*, and that claim runs through a different
graph: not plate to plate, but cell to well to index to read.

Those two graphs come apart, and the place they come apart is pooling. A protocol can be
perfectly executed, perfectly recorded, and every plate accounted for, and still be unable
to say which of 96 cells produced a read -- because 96 wells went into one tube and the
only thing that survives that is a label attached beforehand. The container graph shows a
clean handoff. The identity graph shows total loss. This module computes the second one.

Three ideas carry it.

SEPARABILITY is the physics axis, and it works the way `Observable` does in `vision`: it
records what is still recoverable in principle, before anyone asks what this lab happens
to own. Material is ADDRESSED when each unit sits in its own position, TAGGED when units
share a vessel but carry distinguishing labels, and BULK or MERGED when neither holds. The
last two look identical in a tube and are completely different facts. BULK means identity
never existed -- cells in a suspension were never individually known, and the sort is what
creates their identity. MERGED means identity existed and was thrown away. Upstream of a
split, BULK is correct and expected. MERGED is permanent: no barcode reader, no camera,
and no amount of decoding recovers which cell contributed which molecule once they are in
one tube untagged.

TRACEABILITY is the verdict, and it separates the physics from the paperwork. PROVEN needs
the material to still be separable AND every link in the chain to be attested by an
instrument. CLAIMED is what you get when the material is fine but some link rests on a
human's word or on software intent -- the identity is recoverable, but this lab cannot
demonstrate it. LOST is the physics failing, and it is the only one of the three that no
purchase fixes.

The CEILING is the question worth asking of a lab this early. Today almost every step here
is blocked, so a report about what runs today says little. `ceiling()` instead assumes
every undecoded command gets decoded -- the entire reverse-engineering queue finished --
and asks what attribution would be possible then. For the genomics protocol the answer is
that it stops at CLAIMED and does not reach PROVEN, because the limit is not decoding at
all: it is five plate hops that a human carries unobserved. That is worth computing
precisely, because it says the EXECUTE budget cannot buy the RECORD leg. Barcodes can.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .model import Protocol, Step, Transform, Verdict
from .provenance import Attestation
from .qc import Basis


class Separability(str, Enum):
  """Whether the units of interest are still physically distinguishable.

  A claim about the material, not about the lab. The boundary that matters is between the
  first two and the last two: ADDRESSED and TAGGED keep attribution recoverable, BULK and
  MERGED do not, and nothing downstream of MERGED gets it back.
  """

  ADDRESSED = "addressed"  # each unit in its own position; separable by geometry alone
  TAGGED = "tagged"  # units share a vessel but carry labels that survive merging
  BULK = "bulk"  # units share a vessel unlabeled; identity never existed yet
  MERGED = "merged"  # units were separable and were pooled untagged; identity destroyed

  @property
  def attributable(self) -> bool:
    return self in (Separability.ADDRESSED, Separability.TAGGED)

  @property
  def recoverable(self) -> bool:
    """Whether any future instrument could restore attribution.

    False for both unattributable states, and for different reasons. MERGED lost
    information that existed. BULK never had it. Neither is fixable after the fact, which
    is why this is one property and not two.
    """
    return self.attributable


class Traceability(str, Enum):
  """Whether a datum can be tied back to the unit that produced it."""

  PROVEN = "proven"  # separable, and every link attested by an instrument
  CLAIMED = "claimed"  # separable, but a link rests on a human or on software intent
  LOST = "lost"  # not separable; no instrument recovers it

  @property
  def ok(self) -> bool:
    return self is Traceability.PROVEN


@dataclass(frozen=True)
class Cohort:
  """The material sitting in one artifact, described by identity rather than chemistry.

  `members` counts the units the science wants to distinguish -- cells, compounds, donors
  -- not wells and not molecules. It is the denominator of every attribution question
  asked below.
  """

  artifact: str
  members: int
  separability: Separability
  tag_space: Optional[int] = None  # distinct labels carried, if any
  tagged_at: Optional[str] = None  # the step that applied them
  merged_at: Optional[str] = None  # the step that destroyed attribution, if one did
  unit: str = "unit"

  @property
  def tag_collision(self) -> bool:
    """More units than distinct labels, so at least two are permanently confounded.

    Computable before the run and invisible after it, which is the entire reason to
    compute it: a collided pool sequences normally and produces reads that cannot be
    assigned, with nothing in the data marking which ones.
    """
    return self.tag_space is not None and self.members > self.tag_space


@dataclass(frozen=True)
class LineageEdge:
  """One step, seen as a transformation of identity rather than of material.

  `attestation` is resolved from the ledger's verdict for the step rather than declared,
  so it cannot claim an instrument confirmed something the instrument cannot do. It is
  None exactly when the step does not happen at all, which is a different state from
  happening with nobody watching -- see `happens_today`.
  """

  step_op: str
  instrument: str
  transform: Transform
  attestation: Optional[Attestation]  # None when the step cannot happen at all today
  custody_hop: bool  # the material was carried between instruments to reach this step
  resolves_tags: bool  # a MEASURE that can read the labels, and so report per unit
  before: Optional[Cohort]
  after: Optional[Cohort]
  note: str = ""

  @property
  def happens_today(self) -> bool:
    """Whether this step occurs at all, by any means, in the lab as it stands.

    Deliberately not the same question as whether it runs headlessly. A manual step
    happens -- a human does it -- and produces material with a real, if weak, attestation.
    A blocked step does not happen, so there is no material and nobody to ask. Collapsing
    those two would let 'a person does this' read as 'this does not work', and the
    resulting chain would be wrong about where the lineage actually stops.
    """
    return self.attestation is not None

  @property
  def evidenced(self) -> bool:
    return self.attestation is not None and self.attestation.is_evidence


@dataclass(frozen=True)
class Misassignment:
  """The error term that survives doing everything right.

  A correctly tagged pool still misassigns some fraction of reads between its members,
  because free index-bearing adapter can prime the wrong template during the steps between
  pooling and sequencing. It is a property of pooled sequencing rather than of any
  instrument here, so no decoding removes it and no run card validates it away.

  It is recorded with its basis for the same reason QC thresholds are: this is real
  published evidence and it is not evidence about THIS pool at THIS input. A lab reporting
  per-cell results without having measured its own rate is reporting an error term it has
  never bounded.
  """

  mechanism: str
  basis: Basis
  mitigated_by: str
  measured_here: bool = False


MISASSIGNMENT = Misassignment(
  mechanism=(
    "free index-bearing adapter left in a pooled library can prime a neighbouring template "
    "during amplification and exchange the index, so a read carries a label that did not "
    "come from the molecule it sequenced"
  ),
  basis=Basis.LITERATURE,
  mitigated_by=(
    "unique dual indices, so a swap on one end is detectable as a combination that was "
    "never assigned rather than read as a different member; plus a cleanup that removes "
    "free adapter before pooling"
  ),
  measured_here=False,
)


# -- walking the identity graph ------------------------------------------------


def _attestation_for(verdict: Verdict) -> Optional[Attestation]:
  """What a step's verdict implies about who can attest to it.

  Deliberately the same mapping `provenance` uses, and deliberately narrow: only the two
  verdicts that mean real hardware ran and reported back count as an instrument's word. A
  step with no code path is a human's word. A step that cannot run has nobody's.
  """
  if verdict in (Verdict.AUTOMATED, Verdict.SUPERVISED):
    return Attestation.CONFIRMED
  if verdict is Verdict.MANUAL:
    return Attestation.WITNESSED
  return None


class UndeclaredTransform(ValueError):
  """A step moves material and does not say what it does to identity.

  Refused rather than defaulted. Defaulting to MOVE would be the dangerous choice: a
  pooling step silently treated as a transfer would report intact attribution through the
  exact operation that destroys it, and the report would look fine.
  """


def _material_steps(protocol: Protocol) -> List[Step]:
  """Steps that touch physical material, and therefore owe a transform declaration."""
  physical = {a.name for a in protocol.artifacts if a.physical}
  out: List[Step] = []
  for step in protocol.steps:
    touched = set(step.consumes) | set(step.produces)
    if touched & physical:
      out.append(step)
  return out


def undeclared_transforms(protocol: Protocol) -> List[str]:
  """Every material-moving step that has not declared what it does to identity."""
  return [s.op for s in _material_steps(protocol) if s.transform is None]


@dataclass
class LineageGraph:
  """The identity graph for one protocol, walked against one ledger."""

  protocol: str
  unit: str
  edges: List[LineageEdge] = field(default_factory=list)
  cohorts: Dict[str, Cohort] = field(default_factory=dict)

  def terminal_data(self) -> List[str]:
    """Data artifacts nothing further consumes: what the run is actually for."""
    consumed = {a for e in self.edges for a in (e.before.artifact,) if e.before}
    return [name for name, c in self.cohorts.items() if name not in consumed]

  def chain_to(self, artifact: str) -> List[LineageEdge]:
    """Every edge on the path from material entering to this artifact.

    The protocol is ordered rather than a free DAG, so the chain is the prefix of edges up
    to and including the one that produced this artifact. Nothing to reconstruct.
    """
    out: List[LineageEdge] = []
    for e in self.edges:
      out.append(e)
      if e.after is not None and e.after.artifact == artifact:
        break
    return out

  def ancestry(self, artifact: str) -> List[str]:
    """The artifacts the datum's material actually passed through, oldest first.

    Not the same as `chain_to`, and the difference is the flow cell. A protocol runs
    several material streams at once -- sample, reagents, consumables -- and only one of
    them carries the identity being traced. Walking the edges in order sweeps up all of
    them; walking `before` links backwards from the datum follows the sample alone. Listing
    a flow cell alongside the cells would invite reading its member count as a cell count.
    """
    # The edge that genuinely CREATED each artifact. A step that produces nothing --
    # staging a manifest, selecting a program -- reports its input as its output, so it
    # looks like a producer and links the artifact to itself. Taking the first real
    # creator skips those; taking the last would walk into the self-loop and stop there.
    producer: Dict[str, LineageEdge] = {}
    for e in self.edges:
      if e.after is None:
        continue
      name = e.after.artifact
      if e.before is not None and e.before.artifact == name:
        continue  # a passthrough, not a creation
      producer.setdefault(name, e)
    out: List[str] = []
    seen = set()
    cur: Optional[str] = artifact
    while cur and cur not in seen:
      seen.add(cur)
      out.append(cur)
      edge = producer.get(cur)
      cur = edge.before.artifact if edge and edge.before is not None else None
    return list(reversed(out))

  def weakest_link(self, artifact: str) -> Optional[LineageEdge]:
    """The edge that caps how strong the attribution claim can be.

    An unrunnable step outranks an unwitnessed one: if the step does not happen, arguing
    about who would have attested to it is beside the point.
    """
    chain = self.chain_to(artifact)
    blocked = [e for e in chain if not e.happens_today]
    if blocked:
      return blocked[0]
    unevidenced = [e for e in chain if not e.evidenced]
    return unevidenced[0] if unevidenced else None

  def destroyed_at(self) -> Optional[LineageEdge]:
    """The edge where attribution was permanently lost, if one exists."""
    for e in self.edges:
      if e.after is not None and e.after.separability is Separability.MERGED:
        return e
    return None

  def post_merge_measurements(self) -> List[LineageEdge]:
    """Measurements taken after the material stopped being physically separated.

    The test is ADDRESSED, not `attributable`, and the difference is the subtle part. A
    tag makes attribution recoverable only by an instrument that can READ the tag, so a
    pooled library is attributable in principle and still yields exactly one absorbance
    number for 96 cells. The sequencer that does resolve the index says so with
    `reads_tags` and is excluded here; the plate reader looking at the same tube is not.

    These are the quiet ones. The number is real and it describes the pool. A failure
    confined to one member is averaged into it, moves the pooled value by about a
    ninety-sixth, and does not come close to failing a gate -- so the gate passes and the
    member is gone.
    """
    return [
      e
      for e in self.edges
      if e.transform is Transform.MEASURE
      and not e.resolves_tags
      and e.before is not None
      and e.before.separability is not Separability.ADDRESSED
      and e.before.members > 1
    ]

  def tag_edge(self) -> Optional[LineageEdge]:
    """The step that attached the labels everything downstream depends on, if any."""
    return next((e for e in self.edges if e.transform is Transform.TAG), None)


def build_lineage(protocol: Protocol, ledger, unit: str = "unit") -> LineageGraph:
  """Walk a protocol as a graph of identity, costed against a real ledger.

  Refuses a protocol whose material-moving steps have not declared their transform, for
  the same reason the ledger refuses one with undeclared artifacts: the failure mode of
  guessing is a confident report that is wrong in the direction of flattery.
  """
  missing = undeclared_transforms(protocol)
  if missing:
    raise UndeclaredTransform(
      f"{protocol.name}: {len(missing)} step(s) move material without declaring a "
      f"transform: {', '.join(missing)}. Identity semantics cannot be inferred from an "
      "op name; declare Transform.MOVE explicitly if that is really what it does."
    )

  verdicts = {r.step.op: r.verdict for r in ledger.rows}
  hops = {(art, dst) for art, _src, dst in ledger.handoffs()}
  graph = LineageGraph(protocol=protocol.name, unit=unit)
  live: Dict[str, Cohort] = {}

  for step in protocol.steps:
    if step.transform is None:
      continue
    verdict = verdicts.get(step.op, Verdict.MANUAL)
    attestation = _attestation_for(verdict)
    custody = any((art, step.instrument) in hops for art in step.consumes)

    if step.lineage_input is not None:
      before = live.get(step.lineage_input)
    else:
      before = next((live[a] for a in step.consumes if a in live), None)
    after, note = _apply(step, before, unit)

    if after is not None:
      live[after.artifact] = after
      graph.cohorts[after.artifact] = after
    if step.transform is Transform.CONSUME:
      for art in step.consumes:
        live.pop(art, None)

    graph.edges.append(
      LineageEdge(
        step_op=step.op,
        instrument=step.instrument,
        transform=step.transform,
        attestation=attestation,
        custody_hop=custody,
        resolves_tags=step.reads_tags,
        before=before,
        after=after,
        note=note,
      )
    )
  return graph


def _apply(step: Step, before: Optional[Cohort], unit: str) -> Tuple[Optional[Cohort], str]:
  """One step's effect on a cohort. The whole identity model lives in this function."""
  t = step.transform
  if step.produces:
    produced = step.produces[0]
  elif step.lineage_input:
    produced = step.lineage_input
  elif step.consumes:
    produced = step.consumes[0]
  else:
    produced = ""

  if t is Transform.ENTER:
    # Material arrives either already individuated -- a compound plate has 96 distinct
    # compounds in 96 known positions before anyone touches it -- or as a bulk population
    # in which no unit is yet distinguishable. Which one it is changes what the rest of
    # the protocol has to do: bulk material needs a SPLIT to acquire identity at all.
    if step.fanout:
      return (
        Cohort(
          artifact=produced,
          members=step.fanout,
          separability=Separability.ADDRESSED,
          unit=unit,
        ),
        f"material enters already addressed: {step.fanout} {unit}(s) in known positions",
      )
    return (
      Cohort(artifact=produced, members=1, separability=Separability.BULK, unit=unit),
      f"material enters as one bulk population; no {unit} is individually identified yet",
    )

  if before is None:
    return None, "no material in hand at this step"

  if t is Transform.SPLIT:
    n = step.fanout or 1
    return (
      Cohort(artifact=produced, members=n, separability=Separability.ADDRESSED, unit=unit),
      f"identity is created here: {n} {unit}(s) become separable by position",
    )

  if t is Transform.MOVE:
    return (
      Cohort(
        artifact=produced,
        members=before.members,
        separability=before.separability,
        tag_space=before.tag_space,
        tagged_at=before.tagged_at,
        merged_at=before.merged_at,
        unit=unit,
      ),
      "addressing preserved",
    )

  if t is Transform.TAG:
    return (
      Cohort(
        artifact=produced,
        members=before.members,
        separability=before.separability,
        tag_space=step.fanout,
        tagged_at=step.op,
        unit=unit,
      ),
      f"{step.fanout} distinct label(s) applied; attribution can now survive a merge",
    )

  if t is Transform.MERGE:
    if before.tagged_at is not None:
      return (
        Cohort(
          artifact=produced,
          members=before.members,
          separability=Separability.TAGGED,
          tag_space=before.tag_space,
          tagged_at=before.tagged_at,
          unit=unit,
        ),
        f"pooled, but each {unit} carries a label applied at '{before.tagged_at}'",
      )
    sep = Separability.BULK if before.separability is Separability.BULK else Separability.MERGED
    return (
      Cohort(
        artifact=produced,
        members=before.members,
        separability=sep,
        merged_at=step.op if sep is Separability.MERGED else None,
        unit=unit,
      ),
      (
        f"pooled untagged: {before.members} {unit}(s) are now one indistinguishable "
        "population, permanently"
        if sep is Separability.MERGED
        else "pooled; the population was already unlabelled"
      ),
    )

  if t is Transform.MEASURE:
    return (
      Cohort(
        artifact=produced,
        members=before.members,
        separability=before.separability,
        tag_space=before.tag_space,
        tagged_at=before.tagged_at,
        merged_at=before.merged_at,
        unit=unit,
      ),
      f"data describing {before.members} {unit}(s) at {before.separability.value}",
    )

  return None, "material consumed"


# -- the report ----------------------------------------------------------------


@dataclass
class LineageReport:
  """Whether this lab could say which unit a result came from."""

  protocol: str
  unit: str
  graph: LineageGraph
  datum: str
  verdict: Traceability
  reason: str
  ceiling: Traceability
  ceiling_reason: str

  def counts(self) -> Dict[str, int]:
    cohort = self.graph.cohorts.get(self.datum)
    chain = self.graph.chain_to(self.datum)
    return {
      "units": cohort.members if cohort else 0,
      "steps_in_chain": len(chain),
      "steps_that_happen_today": sum(1 for e in chain if e.happens_today),
      "steps_on_a_human_s_word": sum(
        1 for e in chain if e.attestation is Attestation.WITNESSED
      ),
      "unobserved_custody_hops": sum(1 for e in chain if e.custody_hop),
      "post_merge_measurements": len(self.graph.post_merge_measurements()),
    }


def _verdict_for(graph: LineageGraph, datum: str, assume_decoded: bool) -> Tuple[Traceability, str]:
  """The attribution verdict, optionally assuming the whole RE queue is finished.

  `assume_decoded` is what makes this a planning tool rather than a status line. It grants
  every blocked step a working command set and asks what is left. What is left is the part
  no decoding reaches, and naming that is the point of the function.
  """
  cohort = graph.cohorts.get(datum)
  if cohort is None:
    return Traceability.LOST, f"nothing in this protocol produces '{datum}'"

  if not cohort.separability.attributable:
    where = cohort.merged_at
    if where:
      return (
        Traceability.LOST,
        f"attribution was destroyed at '{where}': {cohort.members} {cohort.unit}(s) were "
        "pooled with no label applied first. No instrument recovers this, now or ever",
      )
    return (
      Traceability.LOST,
      f"the material was never separated into individual {cohort.unit}s, so there is no "
      "per-unit identity to trace",
    )

  if cohort.tag_collision:
    return (
      Traceability.LOST,
      f"{cohort.members} {cohort.unit}(s) share {cohort.tag_space} label(s); at least two "
      "are permanently confounded and nothing in the data marks which",
    )

  chain = graph.chain_to(datum)
  if not assume_decoded:
    blocked = [e for e in chain if not e.happens_today]
    if blocked:
      return (
        Traceability.CLAIMED,
        f"{len(blocked)} step(s) in the chain do not happen in this lab at all, starting "
        f"at '{blocked[0].step_op}', so there is no material to attribute yet",
      )

  # Under the ceiling, a blocked step becomes a working instrument command and can be
  # confirmed. A manual step does not: no decoding turns hand-pipetting into a machine
  # report, and no decoding puts an eye on a plate a human carries.
  weak = [
    e
    for e in chain
    if e.attestation is Attestation.WITNESSED or (e.custody_hop and not e.evidenced)
  ]
  hops = [e for e in chain if e.custody_hop]
  if hops:
    return (
      Traceability.CLAIMED,
      f"the material crosses {len(hops)} unobserved custody hop(s); the binding between "
      f"the vessel that arrives and the record describing it is a human's word. Barcodes "
      "read at both ends close this, decoding does not",
    )
  if weak:
    return (
      Traceability.CLAIMED,
      f"{len(weak)} step(s) rest on a human's attestation, starting at '{weak[0].step_op}'",
    )
  return (
    Traceability.PROVEN,
    f"every link is confirmed by an instrument and each {cohort.unit} stays separable",
  )


def lineage_report(
  protocol: Protocol, ledger, datum: str, unit: str = "unit"
) -> LineageReport:
  """Can this lab say which unit produced this datum -- today, and at best?"""
  graph = build_lineage(protocol, ledger, unit=unit)
  verdict, reason = _verdict_for(graph, datum, assume_decoded=False)
  ceiling, ceiling_reason = _verdict_for(graph, datum, assume_decoded=True)
  return LineageReport(
    protocol=protocol.name,
    unit=unit,
    graph=graph,
    datum=datum,
    verdict=verdict,
    reason=reason,
    ceiling=ceiling,
    ceiling_reason=ceiling_reason,
  )
