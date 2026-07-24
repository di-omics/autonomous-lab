"""Adversarial replay tests for material identity, custody, and quantity accounting."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier

import pytest

from autonomous_lab.evidence import EventKind, EvidenceLedger, EvidenceLevel
from autonomous_lab.samples import DerivationMode, MaterialStatus, SampleTracker


def _append(ledger, kind, payload):
  return ledger.append(
    run_id="run",
    kind=kind,
    actor="adversary",
    evidence_level=EvidenceLevel.MEASURED,
    payload=payload,
  )


def _registered(material_id="root", sample_id="sample", quantity=10.0):
  return {
    "material_id": material_id,
    "sample_id": sample_id,
    "material_type": "input",
    "quantity": quantity,
    "unit": "uL",
    "container_id": f"tube_{material_id}",
    "position": None,
    "location": "bench",
    "metadata": {},
  }


def _derived(
  *,
  material_id="child",
  parent_ids=("root",),
  contributions=None,
  quantity=1.0,
  sample_id="sample",
  mode="transfer",
  reason="",
):
  if contributions is None:
    contributions = {
      parent: {"quantity": 1.0, "unit": "uL"} for parent in parent_ids
    }
  return {
    "material_id": material_id,
    "sample_id": sample_id,
    "material_type": "derived",
    "quantity": quantity,
    "unit": "uL",
    "container_id": f"tube_{material_id}",
    "position": None,
    "location": "bench",
    "parent_material_ids": list(parent_ids),
    "parent_contributions": contributions,
    "operation": "aliquot",
    "derivation_mode": mode,
    "transformation_reason": reason,
    "metadata": {},
  }


def _ledger_with_root(quantity=10.0):
  ledger = EvidenceLedger()
  _append(ledger, EventKind.MATERIAL_REGISTERED, _registered(quantity=quantity))
  return ledger


@pytest.mark.parametrize(
  ("mutate", "message"),
  (
    (lambda row: row.pop("sample_id"), "payload is missing: sample_id"),
    (lambda row: row.update({"unknown_claim": True}), "unknown fields"),
    (lambda row: row.update({"sample_id": 7}), "sample_id must be"),
    (lambda row: row.update({"quantity": "many"}), "quantity must be a number"),
    (lambda row: row.update({"quantity": -0.1}), "quantity must be >= 0"),
    (lambda row: row.update({"container_id": ""}), "container_id must be"),
    (lambda row: row.update({"position": ""}), "position must be"),
  ),
)
def test_registration_projection_rejects_invalid_domain_payloads(mutate, message):
  ledger = EvidenceLedger()
  payload = _registered()
  mutate(payload)
  _append(ledger, EventKind.MATERIAL_REGISTERED, payload)

  with pytest.raises(ValueError, match=message):
    SampleTracker(ledger, "run").materials()


@pytest.mark.parametrize(
  ("mutate", "message"),
  (
    (
      lambda row: row.update({"parent_material_ids": []}),
      "derived material has no parents",
    ),
    (
      lambda row: row.update({"parent_material_ids": ["root", "root"]}),
      "repeats a parent",
    ),
    (
      lambda row: row.update({"parent_material_ids": ["future"]}),
      "missing or future parent",
    ),
    (
      lambda row: row.update({"parent_contributions": {}}),
      "do not match parents",
    ),
    (
      lambda row: row["parent_contributions"]["root"].update({"quantity": 0}),
      "must be > 0",
    ),
    (
      lambda row: row["parent_contributions"]["root"].update({"unit": "ng"}),
      "contribution unit",
    ),
  ),
)
def test_derived_projection_rejects_invalid_parents_and_contributions(
  mutate, message
):
  ledger = _ledger_with_root()
  payload = _derived()
  mutate(payload)
  _append(ledger, EventKind.MATERIAL_DERIVED, payload)

  with pytest.raises(ValueError, match=message):
    SampleTracker(ledger, "run").lineage("child")


def test_transfer_cannot_create_a_huge_aliquot_or_overallocate_parent():
  ledger = _ledger_with_root(quantity=1.0)
  huge = _derived(
    quantity=1_000_000.0,
    contributions={"root": {"quantity": 1.0, "unit": "uL"}},
  )
  _append(ledger, EventKind.MATERIAL_DERIVED, huge)
  with pytest.raises(ValueError, match="exceeds explicit parent contributions"):
    SampleTracker(ledger, "run").materials()

  ledger = _ledger_with_root(quantity=1.0)
  first = _derived(
    material_id="first",
    quantity=0.75,
    contributions={"root": {"quantity": 0.75, "unit": "uL"}},
  )
  second = _derived(
    material_id="second",
    quantity=0.5,
    contributions={"root": {"quantity": 0.5, "unit": "uL"}},
  )
  _append(ledger, EventKind.MATERIAL_DERIVED, first)
  _append(ledger, EventKind.MATERIAL_DERIVED, second)
  with pytest.raises(ValueError, match="over-allocates parent 'root'"):
    SampleTracker(ledger, "run").materials()


def test_explicit_transformation_supports_audited_yield_gain():
  tracker = SampleTracker(EvidenceLedger(), "run")
  tracker.register(
    material_id="root",
    sample_id="sample",
    material_type="template",
    quantity=1.0,
    unit="ng",
    container_id="tube",
  )
  amplified = tracker.derive(
    material_id="amp",
    parent_material_ids=("root",),
    parent_contributions={"root": 0.25},
    operation="PCR",
    material_type="amplicon",
    quantity=100.0,
    unit="ng",
    container_id="plate",
    derivation_mode=DerivationMode.TRANSFORMATION,
    transformation_reason="PCR amplification creates additional copies",
  )

  assert amplified.quantity == 100.0
  assert tracker.material("root").allocated_quantity == 0.25
  assert tracker.material("root").available_quantity == 0.75


def test_direct_derivation_cannot_use_quarantined_or_terminal_parent():
  for status in (
    MaterialStatus.QUARANTINED,
    MaterialStatus.CONSUMED,
    MaterialStatus.DISPOSED,
  ):
    tracker = SampleTracker(EvidenceLedger(), "run")
    tracker.register(
      material_id="root",
      sample_id="sample",
      material_type="input",
      quantity=1,
      unit="uL",
      container_id="tube",
    )
    tracker.set_status("root", status, reason="test state")
    _append(tracker.ledger, EventKind.MATERIAL_DERIVED, _derived())

    with pytest.raises(ValueError, match="derives from unavailable"):
      tracker.materials()


def test_multi_sample_pool_requires_a_new_sample_identity_on_write_and_replay():
  tracker = SampleTracker(EvidenceLedger(), "run")
  for label in ("a", "b"):
    tracker.register(
      material_id=label,
      sample_id=f"sample_{label}",
      material_type="input",
      quantity=2,
      unit="uL",
      container_id=f"tube_{label}",
    )
  with pytest.raises(ValueError, match="new sample_id"):
    tracker.derive(
      material_id="pool",
      parent_material_ids=("a", "b"),
      parent_contributions={"a": 1, "b": 1},
      operation="pool",
      material_type="pool",
      quantity=2,
      unit="uL",
      container_id="pool",
      sample_id="sample_a",
    )

  payload = _derived(
    material_id="pool",
    parent_ids=("a", "b"),
    contributions={
      "a": {"quantity": 1, "unit": "uL"},
      "b": {"quantity": 1, "unit": "uL"},
    },
    quantity=2,
    sample_id="sample_a",
  )
  _append(tracker.ledger, EventKind.MATERIAL_DERIVED, payload)
  with pytest.raises(ValueError, match="new sample_id"):
    tracker.materials()


@pytest.mark.parametrize(
  ("mutate", "message"),
  (
    (
      lambda row: row["from"].update({"container_id": "invented"}),
      "source does not match replayed location",
    ),
    (
      lambda row: row["to"].update({"container_id": ""}),
      "container_id must be",
    ),
    (lambda row: row.update({"reason": ""}), "move reason must be"),
    (
      lambda row: row.update({"to": deepcopy(row["from"])}),
      "no-op material move",
    ),
  ),
)
def test_move_projection_rejects_false_custody_and_invalid_destination(
  mutate, message
):
  ledger = _ledger_with_root()
  payload = {
    "material_id": "root",
    "from": {
      "container_id": "tube_root",
      "position": None,
      "location": "bench",
    },
    "to": {
      "container_id": "freezer_rack",
      "position": "A1",
      "location": "freezer",
    },
    "reason": "cold storage",
  }
  mutate(payload)
  _append(ledger, EventKind.MATERIAL_MOVED, payload)

  with pytest.raises(ValueError, match=message):
    SampleTracker(ledger, "run").material("root")


@pytest.mark.parametrize(
  ("from_status", "to_status", "message"),
  (
    ("released", "quarantined", "but replay says active"),
    ("active", "active", "no-op status"),
    ("active", "not-a-status", "unknown material status"),
  ),
)
def test_status_projection_validates_declared_and_target_states(
  from_status, to_status, message
):
  ledger = _ledger_with_root()
  _append(
    ledger,
    EventKind.MATERIAL_STATUS_CHANGED,
    {
      "material_id": "root",
      "from_status": from_status,
      "to_status": to_status,
      "reason": "review",
    },
  )
  with pytest.raises(ValueError, match=message):
    SampleTracker(ledger, "run").materials()


def test_status_projection_refuses_illegal_and_terminal_transitions():
  ledger = _ledger_with_root()
  _append(
    ledger,
    EventKind.MATERIAL_STATUS_CHANGED,
    {
      "material_id": "root",
      "from_status": "active",
      "to_status": "quarantined",
      "reason": "identity concern",
    },
  )
  _append(
    ledger,
    EventKind.MATERIAL_STATUS_CHANGED,
    {
      "material_id": "root",
      "from_status": "quarantined",
      "to_status": "consumed",
      "reason": "invalid shortcut",
    },
  )
  with pytest.raises(ValueError, match="illegal status transition"):
    SampleTracker(ledger, "run").materials()

  tracker = SampleTracker(_ledger_with_root(), "run")
  tracker.set_status("root", MaterialStatus.CONSUMED, reason="assay used all material")
  _append(
    tracker.ledger,
    EventKind.MATERIAL_STATUS_CHANGED,
    {
      "material_id": "root",
      "from_status": "consumed",
      "to_status": "released",
      "reason": "impossible resurrection",
    },
  )
  with pytest.raises(ValueError, match="changes terminal consumed material"):
    tracker.materials()


@pytest.mark.parametrize(
  ("mutate", "message"),
  (
    (lambda row: row.update({"measurement_id": 4}), "measurement_id must be"),
    (lambda row: row.update({"metric": ""}), "metric must be"),
    (lambda row: row.update({"value": True}), "value must be a number"),
    (lambda row: row.update({"value": "NaN"}), "value must be a number"),
    (lambda row: row.update({"unit": []}), "unit must be"),
    (
      lambda row: row.update({"source_digest": "A" * 64}),
      "64 lowercase hex",
    ),
  ),
)
def test_measurement_projection_rejects_invalid_identity_types_and_values(
  mutate, message
):
  ledger = _ledger_with_root()
  payload = {
    "measurement_id": "m1",
    "material_id": "root",
    "metric": "concentration",
    "value": 1.0,
    "unit": "ng/uL",
    "source_digest": "a" * 64,
    "metadata": {},
  }
  mutate(payload)
  _append(ledger, EventKind.MEASUREMENT_RECORDED, payload)
  with pytest.raises(ValueError, match=message):
    SampleTracker(ledger, "run").measurements("root")


def test_measurement_write_rejects_nonfinite_value_and_non_sha256_digest():
  tracker = SampleTracker(_ledger_with_root(), "run")
  with pytest.raises(ValueError, match="must be finite"):
    tracker.record_measurement(
      "root",
      measurement_id="m1",
      metric="concentration",
      value=float("inf"),
      unit="ng/uL",
    )
  with pytest.raises(ValueError, match="64 lowercase hex"):
    tracker.record_measurement(
      "root",
      measurement_id="m2",
      metric="concentration",
      value=1.0,
      unit="ng/uL",
      source_digest="not-a-sha256",
    )


def test_transactional_append_validates_latest_candidate_before_durable_write(
  tmp_path,
):
  path = tmp_path / "evidence.jsonl"
  current = EvidenceLedger(str(path))
  stale = EvidenceLedger(str(path))
  first = current.append(
    run_id="run",
    kind=EventKind.RUN_STARTED,
    actor="first",
    evidence_level=EvidenceLevel.MODELED,
    payload={},
  )
  before = path.read_bytes()
  observed = []

  def reject(events):
    observed.extend(events)
    raise ValueError("candidate rejected")

  with pytest.raises(ValueError, match="candidate rejected"):
    stale.append_transactionally(
      run_id="run",
      kind=EventKind.RUN_COMPLETED,
      actor="stale",
      evidence_level=EvidenceLevel.MODELED,
      payload={},
      validate=reject,
    )

  assert path.read_bytes() == before
  assert len(observed) == 2
  assert observed[0] == first
  assert observed[1].kind is EventKind.RUN_COMPLETED
  assert observed[1].previous_hash == first.event_hash
  assert EvidenceLedger(str(path)).events == (first,)


def test_file_append_separates_a_valid_final_record_without_newline(tmp_path):
  path = tmp_path / "evidence.jsonl"
  ledger = EvidenceLedger(str(path))
  first = ledger.append(
    run_id="run",
    kind=EventKind.RUN_STARTED,
    actor="operator",
    evidence_level=EvidenceLevel.MODELED,
    payload={},
  )
  path.write_text(
    path.read_text(encoding="utf-8").removesuffix("\n"),
    encoding="utf-8",
  )

  second = ledger.append(
    run_id="run",
    kind=EventKind.RUN_COMPLETED,
    actor="operator",
    evidence_level=EvidenceLevel.MODELED,
    payload={},
  )

  assert path.read_text(encoding="utf-8").count("\n") == 2
  reopened = EvidenceLedger(str(path))
  assert reopened.events == (first, second)
  assert reopened.verify().ok


def test_stale_writers_cannot_reuse_material_or_measurement_identity(tmp_path):
  path = tmp_path / "samples.jsonl"
  first = SampleTracker(EvidenceLedger(str(path)), "run", actor="first")
  stale = SampleTracker(EvidenceLedger(str(path)), "run", actor="stale")
  first.register(
    material_id="root",
    sample_id="sample",
    material_type="input",
    quantity=1,
    unit="uL",
    container_id="tube",
  )
  with pytest.raises(ValueError, match="reuses material_id 'root'"):
    stale.register(
      material_id="root",
      sample_id="other",
      material_type="input",
      quantity=1,
      unit="uL",
      container_id="other_tube",
    )

  first_measurement = SampleTracker(
    EvidenceLedger(str(path)), "run", actor="first"
  )
  stale_measurement = SampleTracker(
    EvidenceLedger(str(path)), "run", actor="stale"
  )
  first_measurement.record_measurement(
    "root",
    measurement_id="concentration_1",
    metric="concentration",
    value=1,
    unit="ng/uL",
  )
  with pytest.raises(ValueError, match="reuses measurement_id 'concentration_1'"):
    stale_measurement.record_measurement(
      "root",
      measurement_id="concentration_1",
      metric="concentration",
      value=999,
      unit="ng/uL",
    )

  replay = SampleTracker(EvidenceLedger(str(path)), "run")
  assert tuple(replay.materials()) == ("root",)
  assert len(replay.measurements("root")) == 1


def test_stale_move_and_status_candidates_cannot_overwrite_current_state(tmp_path):
  path = tmp_path / "samples.jsonl"
  setup = SampleTracker(EvidenceLedger(str(path)), "run")
  setup.register(
    material_id="root",
    sample_id="sample",
    material_type="input",
    quantity=1,
    unit="uL",
    container_id="tube",
    location="bench",
  )

  mover = SampleTracker(EvidenceLedger(str(path)), "run", actor="mover")
  stale_mover = SampleTracker(EvidenceLedger(str(path)), "run", actor="stale")
  mover.move(
    "root",
    container_id="freezer_rack",
    position="A1",
    location="freezer",
    reason="cold storage",
  )
  with pytest.raises(ValueError, match="source does not match replayed location"):
    stale_mover.move(
      "root",
      container_id="incubator",
      location="incubator",
      reason="stale plan",
    )

  reviewer = SampleTracker(EvidenceLedger(str(path)), "run", actor="reviewer")
  stale_reviewer = SampleTracker(
    EvidenceLedger(str(path)), "run", actor="stale-reviewer"
  )
  reviewer.set_status(
    "root", MaterialStatus.QUARANTINED, reason="identity investigation"
  )
  with pytest.raises(ValueError, match="but replay says quarantined"):
    stale_reviewer.set_status(
      "root", MaterialStatus.RELEASED, reason="stale approval"
    )

  material = SampleTracker(EvidenceLedger(str(path)), "run").material("root")
  assert material.container_id == "freezer_rack"
  assert material.status is MaterialStatus.QUARANTINED


def test_concurrent_stale_derivations_cannot_overallocate_a_parent(tmp_path):
  path = tmp_path / "samples.jsonl"
  setup = SampleTracker(EvidenceLedger(str(path)), "run")
  setup.register(
    material_id="root",
    sample_id="sample",
    material_type="input",
    quantity=1,
    unit="uL",
    container_id="tube",
  )
  trackers = (
    SampleTracker(EvidenceLedger(str(path)), "run", actor="writer-a"),
    SampleTracker(EvidenceLedger(str(path)), "run", actor="writer-b"),
  )
  barrier = Barrier(2)

  def derive(index):
    barrier.wait()
    material_id = f"child_{index}"
    try:
      trackers[index].derive(
        material_id=material_id,
        parent_material_ids=("root",),
        parent_contributions={"root": 0.75},
        operation="aliquot",
        material_type="aliquot",
        quantity=0.75,
        unit="uL",
        container_id=f"tube_{index}",
      )
    except ValueError as exc:
      return "rejected", str(exc)
    return "written", material_id

  with ThreadPoolExecutor(max_workers=2) as pool:
    outcomes = tuple(pool.map(derive, (0, 1)))

  assert [outcome[0] for outcome in outcomes].count("written") == 1
  assert [outcome[0] for outcome in outcomes].count("rejected") == 1
  rejection = next(outcome[1] for outcome in outcomes if outcome[0] == "rejected")
  assert "over-allocates parent 'root'" in rejection
  replay = SampleTracker(EvidenceLedger(str(path)), "run")
  assert len(replay.materials()) == 2
  assert replay.material("root").allocated_quantity == pytest.approx(0.75)
  assert replay.ledger.verify().ok
