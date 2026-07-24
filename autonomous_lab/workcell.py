"""A workcell: the instruments actually in front of you, and the maps decoded so far.

The registry says what an instrument IS. A workcell says what YOU have: which boxes are
on the bench, where each one's decoded ProtocolMap lives, and what endpoint it answers
on. Everything the ledger reports is computed against a workcell, so the report tracks
your bench rather than an idealized one.

The important behaviour is the fallback. Ask for an instrument's map and you get the
decoded one off disk if it exists, and the undecoded seed if it does not. There is no
third option and no way to assert coverage you have not earned: a missing map file is
not an error, it is simply a map with nothing decoded, and it costs out that way.
"""

from __future__ import annotations

import copy
import json
import math
import os
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from plr_re.protocolmap import DEVICE_NAMES, SEEDS, ProtocolMap, Transport, seed

from .registry import FEDERATED, registry


@dataclass(frozen=True)
class InstrumentConfig:
  """One instrument's local reality: is it here, and how far is its map."""

  key: str
  present: bool = True
  map_path: Optional[str] = None
  endpoint: Optional[str] = None
  note: str = ""


@dataclass
class Workcell:
  """A named lab. `instruments` is keyed by registry key; `federated` names the
  plr-tested instruments this bench can reach."""

  name: str = "default"
  instruments: Dict[str, InstrumentConfig] = field(default_factory=dict)
  federated: Tuple[str, ...] = ()
  # Where plr-tested is checked out, for federated run cards. None means the seam is
  # declared but not wired, and the ledger says so rather than guessing a path.
  plr_tested_root: Optional[str] = None
  # Populated only by snapshot(). Costing and execution then resolve identical map
  # content even if a map file changes while a run is being authorized.
  _resolved_maps: Dict[str, ProtocolMap] = field(
    default_factory=dict, init=False, repr=False, compare=False
  )

  # -- construction ----------------------------------------------------------

  @classmethod
  def default(cls) -> "Workcell":
    """Every registered instrument, present, with no decoded maps and no endpoints.

    This is the honest zero state and it is what `lab stock` reports on a fresh clone:
    every box declared, nothing decoded, nothing reachable.
    """
    return cls(
      name="default",
      instruments={k: InstrumentConfig(key=k) for k in registry()},
      federated=tuple(FEDERATED),
    )

  @classmethod
  def from_json(cls, path: str) -> "Workcell":
    with open(path, encoding="utf-8") as fh:
      d = json.load(fh)
    if type(d) is not dict:
      raise ValueError("workcell JSON must be an object")
    allowed_top_level = {"name", "plr_tested_root", "federated", "instruments"}
    unknown_top_level = sorted(set(d) - allowed_top_level)
    if unknown_top_level:
      raise ValueError(
        "workcell JSON has unknown fields: " + ", ".join(unknown_top_level)
      )
    known = registry()
    instruments: Dict[str, InstrumentConfig] = {}
    raw_instruments = d.get("instruments", {})
    if type(raw_instruments) is not dict:
      raise ValueError("workcell instruments must be an object")
    for key, cfg in raw_instruments.items():
      if type(key) is not str:
        raise ValueError("workcell instrument keys must be strings")
      if key not in known:
        raise KeyError(f"workcell names unknown instrument '{key}'; known: {sorted(known)}")
      if cfg is None:
        cfg = {}
      if type(cfg) is not dict:
        raise ValueError(f"workcell instrument '{key}' configuration must be an object")
      allowed_config = {"present", "map_path", "endpoint", "note"}
      unknown_config = sorted(set(cfg) - allowed_config)
      if unknown_config:
        raise ValueError(
          f"workcell instrument '{key}' has unknown fields: "
          + ", ".join(unknown_config)
        )
      present = cfg.get("present", True)
      if type(present) is not bool:
        raise ValueError(f"workcell instrument '{key}' present must be a boolean")
      map_path = _optional_config_string(cfg.get("map_path"), key, "map_path")
      endpoint = _optional_config_string(cfg.get("endpoint"), key, "endpoint")
      note = cfg.get("note", "")
      if type(note) is not str:
        raise ValueError(f"workcell instrument '{key}' note must be a string")
      instruments[key] = InstrumentConfig(
        key=key,
        present=present,
        map_path=map_path,
        endpoint=endpoint,
        note=note,
      )
    raw_federated = d.get("federated", [])
    if type(raw_federated) is not list or any(
      type(key) is not str for key in raw_federated
    ):
      raise ValueError("workcell federated must be an array of instrument keys")
    federated = tuple(raw_federated)
    if len(federated) != len(set(federated)):
      raise ValueError("workcell federated instrument keys must not contain duplicates")
    for key in federated:
      if key not in FEDERATED:
        raise KeyError(f"workcell names unknown federated instrument '{key}'; known: {sorted(FEDERATED)}")
    name = d.get("name", "workcell")
    if type(name) is not str or not name.strip():
      raise ValueError("workcell name must be a non-empty string")
    plr_tested_root = d.get("plr_tested_root")
    if plr_tested_root is not None and type(plr_tested_root) is not str:
      raise ValueError("workcell plr_tested_root must be a string or null")
    return cls(
      name=name,
      instruments=instruments,
      federated=federated,
      plr_tested_root=plr_tested_root,
    )

  def to_json(self, path: str) -> None:
    payload = {
      "name": self.name,
      "plr_tested_root": self.plr_tested_root,
      "federated": list(self.federated),
      "instruments": {
        k: {"present": c.present, "map_path": c.map_path, "endpoint": c.endpoint, "note": c.note}
        for k, c in self.instruments.items()
      },
    }
    with open(path, "w", encoding="utf-8") as fh:
      json.dump(payload, fh, indent=2)

  # -- map resolution --------------------------------------------------------

  def protocol_map(self, key: str) -> ProtocolMap:
    """The instrument's map: decoded from disk when present, the undecoded seed when not.

    A declared map_path that does not exist is a real mistake (a typo silently costing
    out as "nothing decoded" would be worse than a crash), so that raises. No map_path
    at all is not a mistake: it is the normal state of an instrument nobody has captured
    yet, and it seeds.
    """
    cfg = self.instruments.get(key)
    if cfg is not None and cfg.key != key:
      raise ValueError(
        f"workcell instrument key '{key}' contains configuration for '{cfg.key}'"
      )
    if key in self._resolved_maps:
      cached = copy.deepcopy(self._resolved_maps[key])
      _validate_protocol_map(key, cached)
      return cached
    if cfg is not None and cfg.map_path:
      if not os.path.exists(cfg.map_path):
        raise FileNotFoundError(
          f"workcell declares map_path '{cfg.map_path}' for '{key}' but it does not exist"
        )
      pm = ProtocolMap.from_json(cfg.map_path)
    else:
      pm = seed(key)
    # The workcell describes the local bench. An explicit local endpoint therefore
    # overrides a stale endpoint embedded in a portable decode artifact.
    if cfg is not None and cfg.endpoint is not None:
      pm.endpoint = cfg.endpoint
    _validate_protocol_map(key, pm)
    return pm

  def snapshot(self, keys: Iterable[str]) -> "Workcell":
    """Freeze resolved ProtocolMaps for one authorization/execution attempt."""
    known = registry()
    requested = sorted(set(keys))
    resolved = {
      key: copy.deepcopy(self.protocol_map(key))
      for key in requested
      if key in known
    }
    snapshot = Workcell(
      name=self.name,
      instruments=dict(self.instruments),
      federated=tuple(self.federated),
      plr_tested_root=self.plr_tested_root,
    )
    snapshot._resolved_maps = resolved
    return snapshot

  def coverage(self, key: str) -> dict:
    """decoded/total/missing for one instrument, against its resolved map."""
    return self.protocol_map(key).coverage()

  def present_keys(self) -> List[str]:
    return [k for k, c in self.instruments.items() if c.present]

  def is_federated(self, key: str) -> bool:
    return key in self.federated


def _validate_protocol_map(key: str, protocol_map: ProtocolMap) -> None:
  """Refuse a map whose safety-critical shape drifted from its immutable seed.

  Decoding may fill transport templates, endpoints, and evidence. It may not rename or
  remove required commands, assign a different device, or relabel an actuating command
  as read-only. Those seed facts are the independent safety boundary used by the
  autonomy ledger and executor.
  """
  if key not in SEEDS:
    raise KeyError(f"unknown instrument '{key}'; known: {sorted(SEEDS)}")
  expected_device = DEVICE_NAMES[key]
  if protocol_map.device != expected_device:
    raise ValueError(
      f"ProtocolMap integrity violation for '{key}': device is "
      f"'{protocol_map.device}', expected '{expected_device}'"
    )

  expected = {name: actuating for name, actuating, _note in SEEDS[key]}
  if (
    type(protocol_map.created) not in (int, float)
    or isinstance(protocol_map.created, bool)
    or not math.isfinite(float(protocol_map.created))
  ):
    raise ValueError(
      f"ProtocolMap integrity violation for '{key}': created must be finite numeric"
    )
  if protocol_map.endpoint is not None and type(protocol_map.endpoint) is not str:
    raise ValueError(
      f"ProtocolMap integrity violation for '{key}': endpoint must be a string or null"
    )
  actual_names = set(protocol_map.commands)
  expected_names = set(expected)
  if actual_names != expected_names:
    missing = sorted(expected_names - actual_names)
    extra = sorted(actual_names - expected_names)
    raise ValueError(
      f"ProtocolMap integrity violation for '{key}': command set drifted; "
      f"missing={missing}, extra={extra}"
    )

  for name, command in protocol_map.commands.items():
    if command.name != name:
      raise ValueError(
        f"ProtocolMap integrity violation for '{key}': command key '{name}' "
        f"contains name '{command.name}'"
      )
    if type(command.actuating) is not bool:
      raise ValueError(
        f"ProtocolMap integrity violation for '{key}': command '{name}' "
        "actuating must be boolean"
      )
    if command.actuating != expected[name]:
      raise ValueError(
        f"ProtocolMap integrity violation for '{key}': command '{name}' has "
        f"actuating={command.actuating}, expected {expected[name]}"
      )
    if type(command.decoded) is not bool:
      raise ValueError(
        f"ProtocolMap integrity violation for '{key}': command '{name}' "
        "decoded must be boolean"
      )
    if not command.decoded:
      continue
    if protocol_map.transport is Transport.HTTP:
      if not command.http_path:
        raise ValueError(
          f"ProtocolMap integrity violation for '{key}': decoded HTTP command "
          f"'{name}' has no request path"
        )
    elif not command.frame_template:
      raise ValueError(
        f"ProtocolMap integrity violation for '{key}': decoded byte command "
        f"'{name}' has no frame template"
      )


def _optional_config_string(
  value: object, instrument: str, field_name: str
) -> Optional[str]:
  if value is not None and type(value) is not str:
    raise ValueError(
      f"workcell instrument '{instrument}' {field_name} must be a string or null"
    )
  return value
