"""Per-run material identity, location, measurements, and lineage.

``Artifact`` in :mod:`autonomous_lab.model` describes a protocol-level type such as a
library plate. This module describes the physical instances that exist during one run:
which sample is in which container and well, what it was derived from, and which
measurements are attached to it.

State is never edited in place. ``SampleTracker`` projects it from the append-only
evidence ledger, so a split, pool, move, quarantine, or release remains replayable.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from enum import Enum
from typing import Dict, List, Mapping, Optional, Tuple

from .evidence import EventKind, EvidenceEvent, EvidenceLedger, EvidenceLevel


class MaterialStatus(str, Enum):
  ACTIVE = "active"
  QUARANTINED = "quarantined"
  RELEASED = "released"
  CONSUMED = "consumed"
  DISPOSED = "disposed"


class DerivationMode(str, Enum):
  """How output quantity relates to explicitly allocated parent material."""

  TRANSFER = "transfer"
  TRANSFORMATION = "transformation"


@dataclass(frozen=True)
class Material:
  """The current projection of one material instance."""

  material_id: str
  sample_id: str
  material_type: str
  quantity: float
  unit: str
  container_id: str
  position: Optional[str]
  parent_material_ids: Tuple[str, ...]
  created_by_event: str
  status: MaterialStatus = MaterialStatus.ACTIVE
  location: str = ""
  metadata: Optional[Dict[str, object]] = None
  allocated_quantity: float = 0.0

  @property
  def available_quantity(self) -> float:
    """Quantity not yet allocated to a derived child, in ``unit``."""
    return max(0.0, self.quantity - self.allocated_quantity)


@dataclass(frozen=True)
class Measurement:
  """One observed metric tied to exact material and evidence."""

  measurement_id: str
  material_id: str
  metric: str
  value: float
  unit: str
  event_id: str
  evidence_level: EvidenceLevel
  source_digest: Optional[str] = None
  metadata: Optional[Dict[str, object]] = None


@dataclass(frozen=True)
class LineageEdge:
  parent_material_id: str
  child_material_id: str
  operation: str
  event_id: str


@dataclass(frozen=True)
class Lineage:
  """Ancestors are ordered root-first and contain the requested material last."""

  material: Material
  ancestors: Tuple[Material, ...]
  edges: Tuple[LineageEdge, ...]


class SampleTracker:
  """Project and append sample events for one run."""

  def __init__(self, ledger: EvidenceLedger, run_id: str, actor: str = "clair"):
    if not run_id.strip():
      raise ValueError("run_id must not be empty")
    if not actor.strip():
      raise ValueError("actor must not be empty")
    self.ledger = ledger
    self.run_id = run_id
    self.actor = actor

  def materials(self) -> Dict[str, Material]:
    materials, _measurements, _edges = self._project()
    return materials

  def material(self, material_id: str) -> Material:
    materials = self.materials()
    if material_id not in materials:
      raise KeyError(f"no material '{material_id}' in run '{self.run_id}'")
    return materials[material_id]

  def measurements(
    self, material_id: str, metric: Optional[str] = None
  ) -> Tuple[Measurement, ...]:
    materials, measurements, _edges = self._project()
    if material_id not in materials:
      raise KeyError(f"no material '{material_id}' in run '{self.run_id}'")
    out = [
      measurement
      for measurement in measurements
      if measurement.material_id == material_id
      and (metric is None or measurement.metric == metric)
    ]
    return tuple(out)

  def register(
    self,
    *,
    material_id: str,
    sample_id: str,
    material_type: str,
    quantity: float,
    unit: str,
    container_id: str,
    position: Optional[str] = None,
    location: str = "",
    metadata: Optional[Mapping[str, object]] = None,
    evidence_level: EvidenceLevel = EvidenceLevel.MEASURED,
  ) -> Material:
    """Register a root material such as an accessioned tube or source well."""
    self._validate_identity(material_id, sample_id, material_type, container_id)
    self._validate_quantity(quantity, unit)
    _validate_optional_position(position, "position")
    _validate_location(location, "location")
    _validate_metadata_for_write(metadata)
    if material_id in self.materials():
      raise ValueError(f"material_id '{material_id}' already exists")
    event = self._append_replay_validated(
      kind=EventKind.MATERIAL_REGISTERED,
      evidence_level=evidence_level,
      payload={
        "material_id": material_id,
        "sample_id": sample_id,
        "material_type": material_type,
        "quantity": float(quantity),
        "unit": unit,
        "container_id": container_id,
        "position": position,
        "location": location,
        "metadata": dict(metadata or {}),
      },
    )
    return self.material(str(event.payload["material_id"]))

  def derive(
    self,
    *,
    material_id: str,
    parent_material_ids: Tuple[str, ...],
    parent_contributions: Mapping[str, float],
    operation: str,
    material_type: str,
    quantity: float,
    unit: str,
    container_id: str,
    position: Optional[str] = None,
    sample_id: Optional[str] = None,
    location: str = "",
    metadata: Optional[Mapping[str, object]] = None,
    evidence_level: EvidenceLevel = EvidenceLevel.MEASURED,
    derivation_mode: DerivationMode = DerivationMode.TRANSFER,
    transformation_reason: str = "",
  ) -> Material:
    """Create a material while allocating an explicit quantity from every parent.

    ``TRANSFER`` is conservative: the child unit must match every parent unit and its
    quantity cannot exceed the sum of its contributions. ``TRANSFORMATION`` permits a
    unit conversion or yield gain (for example PCR amplification), but requires a
    recorded scientific reason. In both cases, contributions consume each parent's
    finite allocation budget.
    """
    if not parent_material_ids:
      raise ValueError("derived material needs at least one parent")
    if any(
      not isinstance(parent, str) or not parent.strip()
      for parent in parent_material_ids
    ):
      raise ValueError("parent_material_ids must contain non-empty strings")
    if len(set(parent_material_ids)) != len(parent_material_ids):
      raise ValueError("parent_material_ids must not contain duplicates")
    _nonempty_string(operation, "operation")
    if not isinstance(derivation_mode, DerivationMode):
      raise TypeError("derivation_mode must be a DerivationMode")
    _validate_optional_position(position, "position")
    _validate_location(location, "location")
    _validate_metadata_for_write(metadata)
    existing = self.materials()
    if material_id in existing:
      raise ValueError(f"material_id '{material_id}' already exists")
    missing = [parent for parent in parent_material_ids if parent not in existing]
    if missing:
      raise KeyError(f"unknown parent material(s): {', '.join(missing)}")
    unusable = [
      parent
      for parent in parent_material_ids
      if existing[parent].status
      in (MaterialStatus.CONSUMED, MaterialStatus.DISPOSED, MaterialStatus.QUARANTINED)
    ]
    if unusable:
      raise ValueError(
        "cannot derive from unavailable material(s): " + ", ".join(unusable)
      )
    if not isinstance(parent_contributions, Mapping):
      raise TypeError("parent_contributions must be a mapping")
    if any(
      not isinstance(parent, str) or not parent.strip()
      for parent in parent_contributions
    ):
      raise ValueError("parent_contributions keys must be non-empty strings")
    contribution_ids = set(parent_contributions)
    parent_ids = set(parent_material_ids)
    if contribution_ids != parent_ids:
      missing_contributions = sorted(parent_ids - contribution_ids)
      extra_contributions = sorted(contribution_ids - parent_ids)
      details = []
      if missing_contributions:
        details.append("missing " + ", ".join(missing_contributions))
      if extra_contributions:
        details.append("extra " + ", ".join(extra_contributions))
      raise ValueError(
        "parent_contributions must exactly match parent_material_ids ("
        + "; ".join(details)
        + ")"
      )
    normalized_contributions: Dict[str, Dict[str, object]] = {}
    for parent in parent_material_ids:
      contribution = _finite_number(
        parent_contributions[parent], f"contribution from '{parent}'"
      )
      if contribution <= 0:
        raise ValueError(f"contribution from '{parent}' must be > 0")
      if _exceeds(contribution, existing[parent].available_quantity):
        raise ValueError(
          f"contribution from '{parent}' is {contribution:g} "
          f"{existing[parent].unit}, but only "
          f"{existing[parent].available_quantity:g} {existing[parent].unit} remains"
        )
      normalized_contributions[parent] = {
        "quantity": contribution,
        "unit": existing[parent].unit,
      }
    parent_samples = {existing[parent].sample_id for parent in parent_material_ids}
    if sample_id is None:
      if len(parent_samples) != 1:
        raise ValueError("a pool of multiple sample_ids must declare its new sample_id")
      sample_id = next(iter(parent_samples))
    elif len(parent_samples) == 1 and sample_id not in parent_samples:
      raise ValueError("derived material must preserve its parent's sample_id")
    elif len(parent_samples) > 1 and sample_id in parent_samples:
      raise ValueError("a multi-sample pool must declare a new sample_id")
    self._validate_identity(material_id, sample_id, material_type, container_id)
    self._validate_quantity(quantity, unit)
    total_contribution = sum(
      float(item["quantity"]) for item in normalized_contributions.values()
    )
    if derivation_mode is DerivationMode.TRANSFER:
      mismatched_units = [
        parent
        for parent in parent_material_ids
        if existing[parent].unit != unit
      ]
      if mismatched_units:
        raise ValueError(
          "transfer output unit must match every parent unit; mismatched: "
          + ", ".join(mismatched_units)
        )
      if _exceeds(float(quantity), total_contribution):
        raise ValueError(
          f"transfer output {float(quantity):g} {unit} exceeds explicit parent "
          f"contributions of {total_contribution:g} {unit}"
        )
      if transformation_reason:
        raise ValueError("transfer derivation must not declare a transformation_reason")
    else:
      if (
        not isinstance(transformation_reason, str)
        or not transformation_reason.strip()
      ):
        raise ValueError("transformation derivation requires a transformation_reason")
    event = self._append_replay_validated(
      kind=EventKind.MATERIAL_DERIVED,
      evidence_level=evidence_level,
      payload={
        "material_id": material_id,
        "sample_id": sample_id,
        "material_type": material_type,
        "quantity": float(quantity),
        "unit": unit,
        "container_id": container_id,
        "position": position,
        "location": location,
        "parent_material_ids": list(parent_material_ids),
        "parent_contributions": normalized_contributions,
        "operation": operation,
        "derivation_mode": derivation_mode.value,
        "transformation_reason": transformation_reason,
        "metadata": dict(metadata or {}),
      },
    )
    return self.material(str(event.payload["material_id"]))

  def move(
    self,
    material_id: str,
    *,
    container_id: str,
    position: Optional[str] = None,
    location: str = "",
    reason: str,
    evidence_level: EvidenceLevel = EvidenceLevel.MEASURED,
  ) -> Material:
    """Record custody/location change without rewriting the material."""
    _nonempty_string(material_id, "material_id")
    current = self.material(material_id)
    if current.status in (MaterialStatus.CONSUMED, MaterialStatus.DISPOSED):
      raise ValueError(f"cannot move {current.status.value} material '{material_id}'")
    _nonempty_string(container_id, "container_id")
    _nonempty_string(reason, "material move reason")
    _validate_optional_position(position, "position")
    _validate_location(location, "location")
    destination = {
      "container_id": container_id,
      "position": position,
      "location": location,
    }
    source = {
      "container_id": current.container_id,
      "position": current.position,
      "location": current.location,
    }
    if destination == source:
      raise ValueError("material move destination must differ from its source")
    self._append_replay_validated(
      kind=EventKind.MATERIAL_MOVED,
      evidence_level=evidence_level,
      payload={
        "material_id": material_id,
        "from": source,
        "to": destination,
        "reason": reason,
      },
    )
    return self.material(material_id)

  def set_status(
    self,
    material_id: str,
    status: MaterialStatus,
    *,
    reason: str,
    evidence_level: EvidenceLevel = EvidenceLevel.MEASURED,
  ) -> Material:
    _nonempty_string(material_id, "material_id")
    current = self.material(material_id)
    if not isinstance(status, MaterialStatus):
      raise TypeError("status must be a MaterialStatus")
    _nonempty_string(reason, "status change reason")
    if current.status in (MaterialStatus.CONSUMED, MaterialStatus.DISPOSED):
      raise ValueError(
        f"terminal material '{material_id}' is already {current.status.value}"
      )
    if status is current.status:
      raise ValueError(f"material '{material_id}' is already {status.value}")
    if status not in _LEGAL_STATUS_TRANSITIONS[current.status]:
      raise ValueError(
        f"illegal material status transition "
        f"{current.status.value} -> {status.value}"
      )
    self._append_replay_validated(
      kind=EventKind.MATERIAL_STATUS_CHANGED,
      evidence_level=evidence_level,
      payload={
        "material_id": material_id,
        "from_status": current.status.value,
        "to_status": status.value,
        "reason": reason,
      },
    )
    return self.material(material_id)

  def record_measurement(
    self,
    material_id: str,
    *,
    measurement_id: str,
    metric: str,
    value: float,
    unit: str,
    source_digest: Optional[str] = None,
    metadata: Optional[Mapping[str, object]] = None,
    evidence_level: EvidenceLevel = EvidenceLevel.MEASURED,
  ) -> Measurement:
    """Attach a typed scalar measurement to a material.

    Raw images, reader exports, and omics matrices stay outside the JSONL ledger. Their
    SHA-256 digest belongs in ``source_digest`` so this scalar can be traced back to the
    exact source bytes.
    """
    _nonempty_string(material_id, "material_id")
    self.material(material_id)
    _nonempty_string(measurement_id, "measurement_id")
    _nonempty_string(metric, "metric")
    _nonempty_string(unit, "unit")
    numeric_value = _finite_number(value, "measurement value")
    _validate_source_digest(source_digest)
    _validate_metadata_for_write(metadata)
    _materials, existing_measurements, _edges = self._project()
    if any(
      measurement.measurement_id == measurement_id
      for measurement in existing_measurements
    ):
      raise ValueError(f"measurement_id '{measurement_id}' already exists")
    event = self._append_replay_validated(
      kind=EventKind.MEASUREMENT_RECORDED,
      evidence_level=evidence_level,
      payload={
        "measurement_id": measurement_id,
        "material_id": material_id,
        "metric": metric,
        "value": numeric_value,
        "unit": unit,
        "source_digest": source_digest,
        "metadata": dict(metadata or {}),
      },
    )
    return self._measurement_from_event(event)

  def _append_replay_validated(
    self,
    *,
    kind: EventKind,
    evidence_level: EvidenceLevel,
    payload: Mapping[str, object],
  ) -> EvidenceEvent:
    """Append a sample event only if the lock-time projection remains valid."""

    def validate(candidate_events: Tuple[EvidenceEvent, ...]) -> None:
      replay = EvidenceLedger(events=candidate_events)
      SampleTracker(replay, self.run_id, actor=self.actor)._project()

    return self.ledger.append_transactionally(
      run_id=self.run_id,
      kind=kind,
      actor=self.actor,
      evidence_level=evidence_level,
      payload=payload,
      validate=validate,
    )

  def lineage(self, material_id: str) -> Lineage:
    materials, _measurements, edges = self._project()
    if material_id not in materials:
      raise KeyError(f"no material '{material_id}' in run '{self.run_id}'")
    parent_edges: Dict[str, List[LineageEdge]] = {}
    for edge in edges:
      parent_edges.setdefault(edge.child_material_id, []).append(edge)
    ordered: List[str] = []
    chosen_edges: List[LineageEdge] = []
    visiting = set()

    def visit(current: str) -> None:
      if current in visiting:
        raise ValueError(f"material lineage contains a cycle at '{current}'")
      if current in ordered:
        return
      visiting.add(current)
      for edge in parent_edges.get(current, []):
        visit(edge.parent_material_id)
        chosen_edges.append(edge)
      visiting.remove(current)
      ordered.append(current)

    visit(material_id)
    return Lineage(
      material=materials[material_id],
      ancestors=tuple(materials[item] for item in ordered),
      edges=tuple(chosen_edges),
    )

  def _project(
    self,
  ) -> Tuple[Dict[str, Material], List[Measurement], List[LineageEdge]]:
    materials: Dict[str, Material] = {}
    measurements: List[Measurement] = []
    edges: List[LineageEdge] = []
    measurement_ids = set()
    for event in self.ledger.by_run(self.run_id):
      payload = event.payload
      if event.kind in (EventKind.MATERIAL_REGISTERED, EventKind.MATERIAL_DERIVED):
        material = self._material_from_creation(event)
        if material.material_id in materials:
          raise ValueError(
            f"ledger reuses material_id '{material.material_id}' at {event.event_id}"
          )
        if event.kind is EventKind.MATERIAL_DERIVED:
          parent_ids = material.parent_material_ids
          if not parent_ids:
            raise ValueError(f"{event.event_id} derived material has no parents")
          if len(set(parent_ids)) != len(parent_ids):
            raise ValueError(f"{event.event_id} repeats a parent_material_id")
          if material.material_id in parent_ids:
            raise ValueError(f"{event.event_id} makes a material its own parent")
          for parent in parent_ids:
            if parent not in materials:
              raise ValueError(
                f"material '{material.material_id}' references missing or future "
                f"parent '{parent}'"
              )
            if materials[parent].status in _UNAVAILABLE_PARENT_STATUSES:
              raise ValueError(
                f"{event.event_id} derives from unavailable "
                f"{materials[parent].status.value} material '{parent}'"
              )
          parent_samples = {materials[parent].sample_id for parent in parent_ids}
          if len(parent_samples) == 1 and material.sample_id not in parent_samples:
            raise ValueError(
              f"{event.event_id} changes sample_id for a single-sample lineage"
            )
          if len(parent_samples) > 1 and material.sample_id in parent_samples:
            raise ValueError(
              f"{event.event_id} does not assign a new sample_id to a multi-sample pool"
            )
          contributions = _parent_contributions(event, parent_ids, materials)
          mode = _derivation_mode(payload["derivation_mode"], event)
          total_contribution = sum(contributions.values())
          if mode is DerivationMode.TRANSFER:
            mismatched_units = [
              parent for parent in parent_ids if materials[parent].unit != material.unit
            ]
            if mismatched_units:
              raise ValueError(
                f"{event.event_id} transfer unit differs from parent(s): "
                + ", ".join(mismatched_units)
              )
            if _exceeds(material.quantity, total_contribution):
              raise ValueError(
                f"{event.event_id} transfer output {material.quantity:g} "
                f"{material.unit} exceeds explicit parent contributions "
                f"{total_contribution:g} {material.unit}"
              )
            if payload["transformation_reason"] != "":
              raise ValueError(
                f"{event.event_id} transfer must not declare a transformation_reason"
              )
          else:
            _nonempty_string(
              payload["transformation_reason"],
              f"{event.event_id} transformation_reason",
            )
          for parent in parent_ids:
            current_parent = materials[parent]
            contribution = contributions[parent]
            materials[parent] = replace(
              current_parent,
              allocated_quantity=current_parent.allocated_quantity + contribution,
            )
            edges.append(
              LineageEdge(
                parent_material_id=parent,
                child_material_id=material.material_id,
                operation=_nonempty_string(
                  payload["operation"], f"{event.event_id} operation"
                ),
                event_id=event.event_id,
              )
            )
        materials[material.material_id] = material
      elif event.kind is EventKind.MATERIAL_MOVED:
        _validate_event_payload(
          event,
          required=("material_id", "from", "to", "reason"),
        )
        material_id = _nonempty_string(
          payload["material_id"], f"{event.event_id} material_id"
        )
        current = self._require_projected(materials, material_id, event)
        if current.status in _TERMINAL_STATUSES:
          raise ValueError(
            f"{event.event_id} moves terminal {current.status.value} material "
            f"'{material_id}'"
          )
        source = _location_payload(payload["from"], event, "from")
        destination = payload.get("to")
        destination = _location_payload(destination, event, "to")
        expected_source = {
          "container_id": current.container_id,
          "position": current.position,
          "location": current.location,
        }
        if source != expected_source:
          raise ValueError(
            f"{event.event_id} move source does not match replayed location for "
            f"'{material_id}'"
          )
        if destination == source:
          raise ValueError(f"{event.event_id} records a no-op material move")
        _nonempty_string(payload["reason"], f"{event.event_id} move reason")
        materials[material_id] = replace(
          current,
          container_id=destination["container_id"],
          position=destination["position"],
          location=destination["location"],
        )
      elif event.kind is EventKind.MATERIAL_STATUS_CHANGED:
        _validate_event_payload(
          event,
          required=("material_id", "from_status", "to_status", "reason"),
        )
        material_id = _nonempty_string(
          payload["material_id"], f"{event.event_id} material_id"
        )
        current = self._require_projected(materials, material_id, event)
        declared_from = _material_status(payload["from_status"], event, "from_status")
        target = _material_status(payload["to_status"], event, "to_status")
        if declared_from is not current.status:
          raise ValueError(
            f"{event.event_id} changes material '{material_id}' from "
            f"{declared_from.value}, but replay says {current.status.value}"
          )
        if target is current.status:
          raise ValueError(f"{event.event_id} records a no-op status transition")
        if current.status in _TERMINAL_STATUSES:
          raise ValueError(
            f"{event.event_id} changes terminal {current.status.value} material "
            f"'{material_id}'"
          )
        if target not in _LEGAL_STATUS_TRANSITIONS[current.status]:
          raise ValueError(
            f"{event.event_id} records illegal status transition "
            f"{current.status.value} -> {target.value}"
          )
        _nonempty_string(payload["reason"], f"{event.event_id} status reason")
        materials[material_id] = replace(current, status=target)
      elif event.kind is EventKind.MEASUREMENT_RECORDED:
        measurement = self._measurement_from_event(event)
        self._require_projected(materials, measurement.material_id, event)
        if measurement.measurement_id in measurement_ids:
          raise ValueError(
            f"ledger reuses measurement_id '{measurement.measurement_id}'"
          )
        measurement_ids.add(measurement.measurement_id)
        measurements.append(measurement)
    return materials, measurements, edges

  @staticmethod
  def _require_projected(
    materials: Dict[str, Material], material_id: str, event: EvidenceEvent
  ) -> Material:
    if material_id not in materials:
      raise ValueError(
        f"{event.event_id} references material '{material_id}' before registration"
      )
    return materials[material_id]

  @staticmethod
  def _material_from_creation(event: EvidenceEvent) -> Material:
    payload = event.payload
    common_required = (
      "material_id",
      "sample_id",
      "material_type",
      "quantity",
      "unit",
      "container_id",
    )
    common_optional = ("position", "location", "metadata")
    if event.kind is EventKind.MATERIAL_REGISTERED:
      _validate_event_payload(
        event,
        required=common_required,
        optional=common_optional,
      )
      parents: Tuple[str, ...] = ()
    elif event.kind is EventKind.MATERIAL_DERIVED:
      _validate_event_payload(
        event,
        required=common_required
        + (
          "parent_material_ids",
          "parent_contributions",
          "operation",
          "derivation_mode",
          "transformation_reason",
        ),
        optional=common_optional,
      )
      raw_parents = payload["parent_material_ids"]
      if not isinstance(raw_parents, list):
        raise ValueError(f"{event.event_id} parent_material_ids must be an array")
      parents = tuple(
        _nonempty_string(item, f"{event.event_id} parent_material_ids item")
        for item in raw_parents
      )
      _nonempty_string(payload["operation"], f"{event.event_id} operation")
      _derivation_mode(payload["derivation_mode"], event)
      if not isinstance(payload["transformation_reason"], str):
        raise ValueError(
          f"{event.event_id} transformation_reason must be a string"
        )
    else:
      raise ValueError(f"{event.event_id} is not a material creation event")
    material_id = _nonempty_string(
      payload["material_id"], f"{event.event_id} material_id"
    )
    sample_id = _nonempty_string(
      payload["sample_id"], f"{event.event_id} sample_id"
    )
    material_type = _nonempty_string(
      payload["material_type"], f"{event.event_id} material_type"
    )
    quantity = _finite_number(payload["quantity"], f"{event.event_id} quantity")
    if quantity < 0:
      raise ValueError(f"{event.event_id} material quantity must be >= 0")
    unit = _nonempty_string(payload["unit"], f"{event.event_id} unit")
    container_id = _nonempty_string(
      payload["container_id"], f"{event.event_id} container_id"
    )
    position = _validate_optional_position(
      payload.get("position"), f"{event.event_id} position"
    )
    location = _validate_location(
      payload.get("location", ""), f"{event.event_id} location"
    )
    metadata = _validate_metadata(
      payload.get("metadata", {}), f"{event.event_id} metadata"
    )
    return Material(
      material_id=material_id,
      sample_id=sample_id,
      material_type=material_type,
      quantity=quantity,
      unit=unit,
      container_id=container_id,
      position=position,
      location=location,
      parent_material_ids=parents,
      created_by_event=event.event_id,
      metadata=metadata,
    )

  @staticmethod
  def _measurement_from_event(event: EvidenceEvent) -> Measurement:
    payload = event.payload
    _validate_event_payload(
      event,
      required=("measurement_id", "material_id", "metric", "value", "unit"),
      optional=("source_digest", "metadata"),
    )
    source_digest = payload.get("source_digest")
    _validate_source_digest(source_digest, f"{event.event_id} source_digest")
    return Measurement(
      measurement_id=_nonempty_string(
        payload["measurement_id"], f"{event.event_id} measurement_id"
      ),
      material_id=_nonempty_string(
        payload["material_id"], f"{event.event_id} material_id"
      ),
      metric=_nonempty_string(payload["metric"], f"{event.event_id} metric"),
      value=_finite_number(payload["value"], f"{event.event_id} measurement value"),
      unit=_nonempty_string(payload["unit"], f"{event.event_id} unit"),
      event_id=event.event_id,
      evidence_level=event.evidence_level,
      source_digest=source_digest,
      metadata=_validate_metadata(
        payload.get("metadata", {}), f"{event.event_id} metadata"
      ),
    )

  @staticmethod
  def _validate_identity(
    material_id: str, sample_id: str, material_type: str, container_id: str
  ) -> None:
    named = {
      "material_id": material_id,
      "sample_id": sample_id,
      "material_type": material_type,
      "container_id": container_id,
    }
    for name, value in named.items():
      _nonempty_string(value, name)

  @staticmethod
  def _validate_quantity(quantity: float, unit: str) -> None:
    numeric_quantity = _finite_number(quantity, "material quantity")
    if numeric_quantity < 0:
      raise ValueError("material quantity must be >= 0")
    _nonempty_string(unit, "material quantity unit")


_TERMINAL_STATUSES = frozenset(
  (MaterialStatus.CONSUMED, MaterialStatus.DISPOSED)
)
_UNAVAILABLE_PARENT_STATUSES = frozenset(
  (
    MaterialStatus.QUARANTINED,
    MaterialStatus.CONSUMED,
    MaterialStatus.DISPOSED,
  )
)
_LEGAL_STATUS_TRANSITIONS = {
  MaterialStatus.ACTIVE: frozenset(
    (
      MaterialStatus.QUARANTINED,
      MaterialStatus.RELEASED,
      MaterialStatus.CONSUMED,
      MaterialStatus.DISPOSED,
    )
  ),
  MaterialStatus.QUARANTINED: frozenset(
    (MaterialStatus.RELEASED, MaterialStatus.DISPOSED)
  ),
  MaterialStatus.RELEASED: frozenset(
    (
      MaterialStatus.QUARANTINED,
      MaterialStatus.CONSUMED,
      MaterialStatus.DISPOSED,
    )
  ),
  MaterialStatus.CONSUMED: frozenset(),
  MaterialStatus.DISPOSED: frozenset(),
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _validate_event_payload(
  event: EvidenceEvent,
  *,
  required: Tuple[str, ...],
  optional: Tuple[str, ...] = (),
) -> None:
  payload_keys = set(event.payload)
  required_keys = set(required)
  allowed_keys = required_keys | set(optional)
  missing = sorted(required_keys - payload_keys)
  unknown = sorted(payload_keys - allowed_keys)
  if missing:
    raise ValueError(
      f"{event.event_id} {event.kind.value} payload is missing: "
      + ", ".join(missing)
    )
  if unknown:
    raise ValueError(
      f"{event.event_id} {event.kind.value} payload has unknown fields: "
      + ", ".join(unknown)
    )


def _nonempty_string(value: object, field: str) -> str:
  if not isinstance(value, str) or not value.strip():
    raise ValueError(f"{field} must be a non-empty string")
  return value


def _finite_number(value: object, field: str) -> float:
  if isinstance(value, bool) or not isinstance(value, (int, float)):
    raise ValueError(f"{field} must be a number")
  numeric = float(value)
  if not math.isfinite(numeric):
    raise ValueError(f"{field} must be finite")
  return numeric


def _validate_optional_position(value: object, field: str) -> Optional[str]:
  if value is None:
    return None
  return _nonempty_string(value, field)


def _validate_location(value: object, field: str) -> str:
  if not isinstance(value, str):
    raise ValueError(f"{field} must be a string")
  return value


def _validate_metadata(
  value: object,
  field: str = "metadata",
) -> Dict[str, object]:
  if not isinstance(value, dict):
    raise ValueError(f"{field} must be an object")
  return dict(value)


def _validate_metadata_for_write(
  value: Optional[Mapping[str, object]],
) -> None:
  if value is not None and not isinstance(value, Mapping):
    raise ValueError("metadata must be a mapping or null")


def _validate_source_digest(
  value: object,
  field: str = "source_digest",
) -> None:
  if value is not None and (
    not isinstance(value, str) or _SHA256.fullmatch(value) is None
  ):
    raise ValueError(f"{field} must be 64 lowercase hex characters or null")


def _location_payload(
  value: object, event: EvidenceEvent, label: str
) -> Dict[str, object]:
  if not isinstance(value, dict):
    raise ValueError(f"{event.event_id} move {label} must be an object")
  expected = {"container_id", "position", "location"}
  keys = set(value)
  missing = sorted(expected - keys)
  unknown = sorted(keys - expected)
  if missing or unknown:
    details = []
    if missing:
      details.append("missing " + ", ".join(missing))
    if unknown:
      details.append("unknown " + ", ".join(unknown))
    raise ValueError(
      f"{event.event_id} move {label} has invalid fields: " + "; ".join(details)
    )
  return {
    "container_id": _nonempty_string(
      value["container_id"], f"{event.event_id} move {label} container_id"
    ),
    "position": _validate_optional_position(
      value["position"], f"{event.event_id} move {label} position"
    ),
    "location": _validate_location(
      value["location"], f"{event.event_id} move {label} location"
    ),
  }


def _material_status(
  value: object, event: EvidenceEvent, field: str
) -> MaterialStatus:
  if not isinstance(value, str):
    raise ValueError(f"{event.event_id} {field} must be a string")
  try:
    return MaterialStatus(value)
  except ValueError as exc:
    raise ValueError(
      f"{event.event_id} {field} has unknown material status '{value}'"
    ) from exc


def _derivation_mode(value: object, event: EvidenceEvent) -> DerivationMode:
  if not isinstance(value, str):
    raise ValueError(f"{event.event_id} derivation_mode must be a string")
  try:
    return DerivationMode(value)
  except ValueError as exc:
    raise ValueError(
      f"{event.event_id} has unknown derivation_mode '{value}'"
    ) from exc


def _parent_contributions(
  event: EvidenceEvent,
  parent_ids: Tuple[str, ...],
  materials: Dict[str, Material],
) -> Dict[str, float]:
  value = event.payload["parent_contributions"]
  if not isinstance(value, dict):
    raise ValueError(f"{event.event_id} parent_contributions must be an object")
  contribution_ids = set(value)
  expected_ids = set(parent_ids)
  if contribution_ids != expected_ids:
    missing = sorted(expected_ids - contribution_ids)
    extra = sorted(contribution_ids - expected_ids)
    details = []
    if missing:
      details.append("missing " + ", ".join(missing))
    if extra:
      details.append("extra " + ", ".join(extra))
    raise ValueError(
      f"{event.event_id} parent_contributions do not match parents: "
      + "; ".join(details)
    )
  contributions: Dict[str, float] = {}
  for parent in parent_ids:
    contribution = value[parent]
    if not isinstance(contribution, dict):
      raise ValueError(
        f"{event.event_id} contribution from '{parent}' must be an object"
      )
    if set(contribution) != {"quantity", "unit"}:
      raise ValueError(
        f"{event.event_id} contribution from '{parent}' must contain only "
        "quantity and unit"
      )
    quantity = _finite_number(
      contribution["quantity"],
      f"{event.event_id} contribution from '{parent}'",
    )
    if quantity <= 0:
      raise ValueError(
        f"{event.event_id} contribution from '{parent}' must be > 0"
      )
    unit = _nonempty_string(
      contribution["unit"], f"{event.event_id} contribution unit for '{parent}'"
    )
    if unit != materials[parent].unit:
      raise ValueError(
        f"{event.event_id} contribution unit for '{parent}' is {unit}, "
        f"but replay says {materials[parent].unit}"
      )
    if _exceeds(quantity, materials[parent].available_quantity):
      raise ValueError(
        f"{event.event_id} over-allocates parent '{parent}': requests "
        f"{quantity:g} {unit}, only "
        f"{materials[parent].available_quantity:g} {unit} remains"
      )
    contributions[parent] = quantity
  return contributions


def _exceeds(value: float, limit: float) -> bool:
  tolerance = max(1e-12, abs(limit) * 1e-12)
  return value > limit + tolerance
