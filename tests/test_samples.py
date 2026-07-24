"""Device-free tests for sample lineage.

The tests that matter are the ones that try to make a provenance chain claim more than it
can support: that a pooled library still names a well, that a chain with an unwitnessed
hop is machine-attested, that material consumed by a mass spec can be used again.
"""

from __future__ import annotations

import dataclasses

import pytest

from autonomous_lab.samples import (
  Attribution,
  Lineage,
  LineageError,
  Witness,
  reference_lineage,
  wells,
)


def _plate(lin, n=4):
  lin.acquire("src", witness=Witness.OPERATOR)
  lin.split("src", [(f"c{i}", "P1", w) for i, w in enumerate(wells()[:n])], "sort", "namocell")
  return [f"c{i}" for i in range(n)]


def test_wells_are_column_major():
  # A1, B1, ... H1, A2 -- the order a plate is actually pipetted in.
  assert wells()[:9] == ["A1", "B1", "C1", "D1", "E1", "F1", "G1", "H1", "A2"]
  assert len(wells()) == 96


def test_an_unpooled_well_is_addressable_and_blames_only_itself():
  lin = Lineage()
  kids = _plate(lin)
  lin.derive(kids[0], "lys0", "lysis", "star")
  assert lin.attribution("lys0") is Attribution.ADDRESSABLE
  assert lin.blame("lys0") == ["lys0"]


def test_pooling_without_an_index_confounds_every_input():
  lin = Lineage()
  kids = _plate(lin)
  lin.pool(kids, "pool", "library_pool", "star")
  assert lin.attribution("pool") is Attribution.CONFOUNDED
  assert lin.blame("pool") == sorted(kids)


def test_pooling_with_a_full_index_map_stays_recoverable():
  lin = Lineage()
  kids = _plate(lin)
  lin.pool(kids, "pool", "library_pool", "star", index_map={k: f"IDX{i}" for i, k in enumerate(kids)})
  assert lin.attribution("pool") is Attribution.INDEXED
  # Still 4 contributors: indexing does not un-mix the tube, it makes the mixing reversible.
  assert lin.blame("pool") == sorted(kids)


def test_blame_is_not_the_acquired_root():
  """The regression this method exists for.

  Every well of a single-cell plate descends from the one suspension that was loaded, so
  reporting the acquired root would always say "1 source" and would always be useless.
  """
  lin = reference_lineage()
  assert lin.sources("pool") == ["suspension"]  # true, and says nothing
  assert len(lin.blame("pool")) == 96  # what a bad result actually implicates


def test_a_partial_index_map_is_refused():
  lin = Lineage()
  kids = _plate(lin)
  with pytest.raises(LineageError, match="unrecoverable"):
    lin.pool(kids, "pool", "library_pool", "star", index_map={kids[0]: "IDX0"})


def test_a_duplicated_index_is_refused():
  lin = Lineage()
  kids = _plate(lin)
  with pytest.raises(LineageError, match="cannot be demultiplexed"):
    lin.pool(kids, "pool", "library_pool", "star", index_map={k: "SAME" for k in kids})


def test_a_pool_of_one_is_a_derive_and_is_refused():
  lin = Lineage()
  kids = _plate(lin)
  with pytest.raises(LineageError, match="at least two"):
    lin.pool(kids[:1], "pool", "library_pool", "star")


def test_consumed_material_cannot_be_used_again():
  lin = Lineage()
  kids = _plate(lin)
  lin.consume(kids[0], "inject", "agilent6530")
  with pytest.raises(LineageError, match="consumed"):
    lin.derive(kids[0], "downstream", "anything", "star")


def test_unknown_sample_raises_rather_than_inventing_one():
  lin = Lineage()
  with pytest.raises(LineageError, match="unknown sample"):
    lin.derive("nope", "child", "step", "star")


def test_sample_ids_are_permanent():
  lin = Lineage()
  lin.acquire("s")
  with pytest.raises(LineageError, match="already exists"):
    lin.acquire("s")


def test_weakest_witness_is_the_minimum_not_the_maximum():
  """A chain with one inferred hop is an inferred chain, however well instrumented the
  rest of it was. Reporting the best link would invert the meaning."""
  lin = Lineage()
  lin.acquire("src", witness=Witness.MACHINE)
  lin.derive("src", "a", "step_a", "star", witness=Witness.MACHINE)
  lin.derive("a", "b", "step_b", "star", witness=Witness.INFERRED)
  lin.derive("b", "c", "step_c", "star", witness=Witness.MACHINE)
  assert lin.weakest_witness("c") is Witness.INFERRED


def test_the_reference_lineage_admits_it_is_inferred():
  """It is reconstructed from a protocol, not read out of a run record. No step in that
  protocol has an instrument that writes provenance today, and the chain says so."""
  assert reference_lineage().weakest_witness("pool") is Witness.INFERRED


def test_indexing_is_the_only_difference_between_the_two_reference_runs():
  assert reference_lineage(indexed=False).attribution("pool") is Attribution.CONFOUNDED
  assert reference_lineage(indexed=True).attribution("pool") is Attribution.INDEXED


def test_there_is_no_way_to_edit_a_recorded_event():
  """Append-only is a property of the API, not a convention. If a caller can rewrite an
  event after a result comes back, the record is a matter of opinion."""
  lin = Lineage()
  _plate(lin)
  assert not [m for m in dir(lin) if m.startswith(("update", "delete", "remove", "edit"))]
  with pytest.raises(dataclasses.FrozenInstanceError):
    lin.events[0].step = "something else"
