"""Device-free tests for the run record.

A tamper-evident log that does not actually detect tampering is worse than a plain one,
because it is trusted more. These tests edit, delete, and reorder entries and require the
chain to notice each time.
"""

from __future__ import annotations

import itertools

import pytest

from autonomous_lab.record import Entry, RunRecord


def _record(n=4):
  clock = itertools.count(1000.0, 1.0)
  rec = RunRecord("test", clock=lambda: next(clock))
  for i in range(n):
    rec.append("step", i=i, note=f"entry {i}")
  return rec


def test_a_fresh_chain_holds():
  check = _record().verify()
  assert check.ok and check.entries == 4


def test_an_edited_entry_is_caught_at_that_entry():
  rec = _record()
  old = rec.entries[2]
  rec.entries[2] = Entry(old.seq, old.kind, {"i": 99}, old.at, old.prev, old.digest)
  check = rec.verify()
  assert not check.ok
  assert check.broken_at == 2
  assert "edited" in check.reason


def test_a_deleted_entry_breaks_the_sequence():
  rec = _record()
  del rec.entries[1]
  check = rec.verify()
  assert not check.ok and check.broken_at == 1


def test_reordering_two_entries_breaks_the_links():
  rec = _record()
  rec.entries[1], rec.entries[2] = rec.entries[2], rec.entries[1]
  assert not rec.verify().ok


def test_appending_moves_the_seal():
  rec = _record()
  before = rec.seal()
  rec.append("another", x=1)
  assert rec.seal() != before
  assert rec.verify().ok


def test_an_empty_record_seals_to_genesis():
  assert RunRecord("empty").seal() == ""


def test_round_trip_through_jsonl_preserves_the_chain(tmp_path):
  rec = _record()
  path = str(tmp_path / "run.jsonl")
  rec.to_jsonl(path)
  back = RunRecord.from_jsonl(path)
  assert back.run_id == "test"
  assert back.verify().ok
  assert back.seal() == rec.seal()
  assert [e.payload for e in back] == [e.payload for e in rec]


def test_a_tampered_file_survives_loading_so_it_can_be_inspected(tmp_path):
  """Loading deliberately does not verify. When a chain is broken, the one thing you want
  is to read it and find out what changed, and a loader that refused would deny you that."""
  rec = _record()
  path = tmp_path / "run.jsonl"
  rec.to_jsonl(str(path))
  lines = path.read_text().splitlines()
  lines[2] = lines[2].replace('"entry 1"', '"tampered"')
  path.write_text("\n".join(lines) + "\n")
  back = RunRecord.from_jsonl(str(path))  # loads fine
  assert not back.verify().ok  # and tells the truth when asked


def test_an_unserializable_payload_fails_at_the_call_that_supplied_it():
  rec = RunRecord("t")
  with pytest.raises(TypeError, match="not JSON-serializable"):
    rec.append("bad", value=object())


def test_an_empty_file_is_refused(tmp_path):
  path = tmp_path / "empty.jsonl"
  path.write_text("")
  with pytest.raises(ValueError, match="empty"):
    RunRecord.from_jsonl(str(path))


def test_identical_content_hashes_identically():
  """Canonical JSON, so key ordering cannot make an untouched file look tampered with."""
  a = RunRecord("x", clock=lambda: 1.0)
  b = RunRecord("x", clock=lambda: 1.0)
  a.append("k", one=1, two=2)
  b.append("k", two=2, one=1)
  assert a.seal() == b.seal()


def test_the_record_has_no_edit_path():
  rec = _record()
  assert not [m for m in dir(rec) if m.startswith(("update", "delete", "remove", "edit"))]
