"""Device-free tests for sample identity.

The tests that matter here try to make the layer claim attribution it does not have. The
natural implementation of a lineage tracker follows containers, and a container-follower
reports a clean chain straight through a pooling step -- which is the exact operation that
destroys the thing the chain is supposed to prove. So the load-bearing tests pool material
and check that the layer says the information is gone, and gone permanently, no matter how
good the lab gets.

The other half guards a subtler drift. `lineage` adds `lineage_input` to `Step`, and it
would be easy for that field to start counting as a real material transfer -- at which
point naming an input in a protocol would silently invent a plate hop nobody carries, and
the custody numbers this package already reports would inflate for free.
"""

from __future__ import annotations

import pytest

from autonomous_lab import build_ledger, protocols
from autonomous_lab.lineage import (
  MISASSIGNMENT,
  Separability,
  Traceability,
  UndeclaredTransform,
  build_lineage,
  lineage_report,
  undeclared_transforms,
)
from autonomous_lab.model import Artifact, Protocol, Step, Transform
from autonomous_lab.provenance import Attestation
from autonomous_lab.qc import Basis


def _genomics():
  p = protocols.get("single_cell_genomics")
  return p, lineage_report(p, build_ledger(p), "run_outcome", unit="cell")


# -- the physics: what pooling destroys ----------------------------------------


def test_pooling_without_a_tag_destroys_attribution_permanently():
  """The single most important test here.

  A container-following tracker reports this chain as intact: one plate in, one tube out,
  nothing dropped. It is intact as a record of material and worthless as a record of
  identity, and the difference is the whole module.
  """
  untagged = Protocol(
    name="untagged_pool",
    summary="sort, then pool with no index",
    artifacts=(
      Artifact("susp", physical=True),
      Artifact("plate", physical=True),
      Artifact("pool", physical=True),
    ),
    steps=(
      Step(
        instrument="namocell",
        op="manual_load",
        summary="load",
        produces=("susp",),
        manual_reason="bench action",
        transform=Transform.ENTER,
      ),
      Step(
        instrument="namocell",
        op="start_sort",
        summary="sort",
        consumes=("susp",),
        produces=("plate",),
        manual_reason="bench action",
        transform=Transform.SPLIT,
        fanout=96,
      ),
      Step(
        instrument="namocell",
        op="library_pool",
        summary="pool",
        consumes=("plate",),
        produces=("pool",),
        manual_reason="bench action",
        transform=Transform.MERGE,
      ),
    ),
  )
  report = lineage_report(untagged, build_ledger(untagged), "pool", unit="cell")
  assert report.verdict is Traceability.LOST
  assert "destroyed" in report.reason
  assert "library_pool" in report.reason

  # And the point that makes it worth computing: no amount of lab improvement helps.
  assert report.ceiling is Traceability.LOST
  cohort = report.graph.cohorts["pool"]
  assert cohort.separability is Separability.MERGED
  assert not cohort.separability.recoverable


def test_bulk_and_merged_are_different_states_though_they_look_identical():
  """Both are one tube of indistinguishable material; only one of them is a mistake."""
  _p, report = _genomics()
  assert report.graph.cohorts["cell_suspension"].separability is Separability.BULK
  # A suspension was never separated, so nothing was lost by it being bulk.
  assert report.graph.cohorts["cell_suspension"].merged_at is None
  # The genomics protocol tags before it pools, so nothing is ever MERGED.
  assert report.graph.destroyed_at() is None


def test_a_tag_lets_attribution_survive_the_pool():
  _p, report = _genomics()
  assert report.graph.cohorts["library_plate"].separability is Separability.TAGGED
  assert report.graph.cohorts["library_plate"].tagged_at == "pcr_enrichment_round1_cleanup"
  assert report.verdict is not Traceability.LOST


def test_more_cells_than_indices_is_caught_before_the_run_not_after():
  """A collided pool sequences normally and returns unassignable reads with no marker."""
  p = protocols.get("single_cell_genomics")
  overloaded = Protocol(
    name="overloaded",
    summary=p.summary,
    artifacts=p.artifacts,
    steps=tuple(
      # Sort 384 cells into a tag space that only holds 96.
      s if s.op != "start_sort" else Step(**{**s.__dict__, "fanout": 384})
      for s in p.steps
    ),
  )
  report = lineage_report(overloaded, build_ledger(overloaded), "run_outcome", unit="cell")
  assert report.verdict is Traceability.LOST
  assert "confounded" in report.reason
  assert report.graph.cohorts["library_plate"].tag_collision


# -- the ceiling: what decoding cannot buy -------------------------------------


def test_finishing_every_decode_still_does_not_prove_per_cell_attribution():
  """The counterpart of the vision suite's fully-equipped-workcell test.

  Grant the entire reverse-engineering queue. Attribution still stops at CLAIMED, because
  what caps it is five plate hops a human carries unobserved. If this ever starts passing
  as PROVEN, someone has quietly decided that software can vouch for a physical transfer.
  """
  _p, report = _genomics()
  assert report.ceiling is Traceability.CLAIMED
  assert not report.ceiling.ok
  assert "custody hop" in report.ceiling_reason
  assert "barcode" in report.ceiling_reason.lower()


def test_the_lineage_custody_hops_agree_with_the_ledger():
  """One computation, not two -- the same rule the provenance suite enforces."""
  p, report = _genomics()
  assert report.counts()["unobserved_custody_hops"] == len(build_ledger(p).handoffs())
  assert report.counts()["unobserved_custody_hops"] == 5


def test_declaring_a_lineage_input_does_not_invent_a_plate_hop():
  """`lineage_input` is for identity only. If it ever reaches `handoffs()`, the custody
  numbers inflate for free and every downstream provenance claim gets quietly worse."""
  p = protocols.get("single_cell_genomics")
  named = [s.op for s in p.steps if s.lineage_input]
  assert named, "the reference protocol should exercise this field"
  assert len(build_ledger(p).handoffs()) == 5


# -- attestation ---------------------------------------------------------------


def test_the_step_the_whole_claim_rests_on_is_attested_by_a_human():
  """Indexing is the linchpin: it is the only thing that survives pooling, and in this
  lab a person does it with nobody watching."""
  _p, report = _genomics()
  tag = report.graph.tag_edge()
  assert tag is not None
  assert tag.step_op == "pcr_enrichment_round1_cleanup"
  assert tag.attestation is Attestation.WITNESSED
  # A person's word, which this package counts as evidence. What it is not is an
  # instrument's: nothing read back that 96 different indices reached 96 different wells.
  assert tag.attestation is not Attestation.CONFIRMED


def test_a_manual_step_happens_but_a_blocked_step_does_not():
  """Conflating these would report 'a person does this' as 'this does not work'."""
  p, report = _genomics()
  by_op = {e.step_op: e for e in report.graph.edges}
  assert by_op["manual_load"].happens_today  # a human seats the cartridge; it happens
  assert by_op["manual_load"].attestation is Attestation.WITNESSED  # on their word
  assert not by_op["load_protocol"].happens_today  # undecoded command; nothing occurs


# -- measurement after pooling --------------------------------------------------


def test_the_only_quantification_cannot_see_a_single_failed_well():
  """The reader measures the pool. A well that lost its beads moves that number by about
  a ninety-sixth and fails no gate, so the failure is averaged into a passing result."""
  _p, report = _genomics()
  blind = report.graph.post_merge_measurements()
  assert [e.step_op for e in blind] == ["read_absorbance"]
  assert blind[0].before.members == 96


def test_sequencing_is_not_counted_as_a_blind_pooled_measurement():
  """The sequencer reads the index. It is the one measurement here that is per-cell, and
  treating it like the plate reader would overstate the damage."""
  _p, report = _genomics()
  seq = next(e for e in report.graph.edges if e.step_op == "start_run")
  assert seq.resolves_tags
  assert seq not in report.graph.post_merge_measurements()


def test_misassignment_is_recorded_as_unmeasured_literature():
  """A per-cell result carries an error term this lab has never bounded."""
  assert MISASSIGNMENT.basis is Basis.LITERATURE
  assert not MISASSIGNMENT.basis.validated
  assert not MISASSIGNMENT.measured_here


# -- refusing to guess ----------------------------------------------------------


def test_a_protocol_that_does_not_declare_its_transforms_is_refused():
  """Defaulting an undeclared step to MOVE would report intact attribution straight
  through a pooling step. Better to refuse than to flatter."""
  sloppy = Protocol(
    name="sloppy",
    summary="x",
    artifacts=(Artifact("plate", physical=True),),
    steps=(
      Step(instrument="namocell", op="start_sort", summary="x", produces=("plate",)),
      Step(instrument="star", op="library_pool", summary="x", consumes=("plate",)),
    ),
  )
  assert undeclared_transforms(sloppy) == ["start_sort", "library_pool"]
  with pytest.raises(UndeclaredTransform) as err:
    build_lineage(sloppy, build_ledger(sloppy))
  assert "start_sort" in str(err.value)


def test_steps_that_touch_no_material_owe_no_declaration():
  """A socket probe has nothing to say about identity and should not have to say it."""
  p = protocols.get("single_cell_genomics")
  assert undeclared_transforms(p) == []
  probes = [s for s in p.steps if s.op == "probe_http"]
  assert probes and probes[0].transform is None


# -- the contrasting protocol ---------------------------------------------------


def test_chemistry_never_risks_attribution_because_it_never_pools():
  """A compound plate arrives already individuated and stays that way, so its identity
  problem is entirely custody. Worth having as a contrast: the genomics protocol's risk
  comes from its chemistry, not from its instruments being worse."""
  p = protocols.get("small_molecule_qc")
  report = lineage_report(p, build_ledger(p), "chromatogram", unit="compound")
  for cohort in report.graph.cohorts.values():
    assert cohort.separability is Separability.ADDRESSED
  assert report.graph.destroyed_at() is None
  assert report.graph.post_merge_measurements() == []
  # Still not PROVEN: the vials are carried by hand between three instruments.
  assert report.ceiling is Traceability.CLAIMED


# -- following the sample rather than everything on the bench -------------------


def test_ancestry_follows_the_sample_and_not_the_reagents():
  """A protocol runs several material streams at once and only one carries identity.

  The flow cell is real material, is loaded by hand, and is not a cell. Sweeping it into
  the identity chain would put a cohort of 1 next to cohorts of 96 and invite reading it
  as a cell count.
  """
  _p, report = _genomics()
  line = report.graph.ancestry("run_outcome")
  assert "flow_cell" not in line
  assert line[0] == "cell_suspension"
  assert line[-1] == "run_outcome"


def test_a_step_that_produces_nothing_does_not_truncate_the_ancestry():
  """`upload_manifest` consumes the library and produces no new material, so it reports
  its input as its output. Treated as that artifact's producer it links the library to
  itself, and the walk back to the cells stops one step in."""
  _p, report = _genomics()
  line = report.graph.ancestry("run_outcome")
  for expected in ("sorted_plate", "pcr1_plate", "library_plate"):
    assert expected in line, f"{expected} missing: the ancestry walk stopped early"
