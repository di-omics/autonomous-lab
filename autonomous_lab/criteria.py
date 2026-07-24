"""Reference evidence gates for the laboratory intelligence layer.

The decision machinery is reusable across methods, so this module describes *which*
measurements guard each reference step without embedding a method recipe. Numeric
thresholds come from an operator-supplied evidence profile. When a profile entry is
missing, the criterion remains visible with an unset threshold and blocks hardware use.

An evidence profile is a JSON object keyed by the names returned from ``profile_keys()``::

  {
    "liquid_handling.dispense_cv_percent": {
      "threshold": 4.5,
      "units": "%",
      "source": "qualification report Q-2026-14 section 3",
      "origin": "transcribed"
    }
  }

The example value is synthetic. A real profile must cite the protocol, specification, or
local qualification record that authorizes each threshold.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Tuple

from .acceptance import Criterion, Gate, Origin


@dataclass(frozen=True)
class ProfileValue:
  """One operator-owned threshold and its evidence provenance."""

  threshold: float
  source: str
  units: str
  origin: Origin = Origin.TRANSCRIBED

  def __post_init__(self):
    if not self.source or not self.source.strip():
      raise ValueError("an evidence-profile value must cite its source")
    if not self.units or not self.units.strip():
      raise ValueError("an evidence-profile value must declare its units")
    if not math.isfinite(self.threshold):
      raise ValueError("an evidence-profile threshold must be finite")


@dataclass(frozen=True)
class _CriterionTemplate:
  key: str
  metric: str
  comparator: str
  units: str
  note: str = ""


@dataclass(frozen=True)
class _GateTemplate:
  name: str
  guards: str
  produced_by: Tuple[str, str]
  criteria: Tuple[_CriterionTemplate, ...]
  note: str = ""


_TEMPLATES = (
  _GateTemplate(
    name="liquid_handling_qualification",
    guards="any sample material touching the deck",
    produced_by=("tecan", "read_absorbance"),
    criteria=(
      _CriterionTemplate(
        "liquid_handling.dispense_cv_percent",
        "dispense_cv_percent",
        "<=",
        "%",
        "measured across the replicates defined by the operator evidence profile",
      ),
      _CriterionTemplate(
        "liquid_handling.curve_r2",
        "curve_r2",
        ">=",
        "R2",
      ),
    ),
    note=(
      "Qualifies the measurement path before downstream evidence is used. The local "
      "profile defines both the replicate plan and its acceptance limits."
    ),
  ),
  _GateTemplate(
    name="preparation_output",
    guards="committing prepared material to the next laboratory stage",
    produced_by=("tecan", "read_absorbance"),
    criteria=(
      _CriterionTemplate(
        "preparation_output.minimum_yield",
        "preparation_yield",
        ">=",
        "profile_units",
      ),
      _CriterionTemplate(
        "preparation_output.maximum_cv_percent",
        "yield_cv_percent",
        "<=",
        "%",
      ),
    ),
    note=(
      "Evaluates prepared material using method-independent metric names. Units and "
      "limits belong to the operator evidence profile for the active method."
    ),
  ),
  _GateTemplate(
    name="loading_window",
    guards="committing prepared material to an instrument run",
    produced_by=("tecan", "read_absorbance"),
    criteria=(
      _CriterionTemplate(
        "loading_window.minimum",
        "loading_concentration",
        ">=",
        "profile_units",
      ),
      _CriterionTemplate(
        "loading_window.maximum",
        "loading_concentration",
        "<=",
        "profile_units",
      ),
    ),
    note=(
      "The active method profile supplies the measurement units and both sides of the "
      "loading window."
    ),
  ),
  _GateTemplate(
    name="thermal_performance",
    guards="running a thermal program on material",
    produced_by=("odtc", "pcr_enrichment_round1"),
    criteria=(
      _CriterionTemplate(
        "thermal_performance.maximum_setpoint_error",
        "setpoint_error",
        "<=",
        "profile_units",
      ),
      _CriterionTemplate(
        "thermal_performance.minimum_ceiling_headroom",
        "ceiling_headroom",
        ">=",
        "profile_units",
      ),
    ),
    note=(
      "Instrument observations are compared only after the active method profile supplies "
      "its authorized thermal limits."
    ),
  ),
  _GateTemplate(
    name="run_control_quality",
    guards="accepting an instrument run as usable",
    produced_by=("element_aviti", "read_control_metrics"),
    criteria=(
      _CriterionTemplate(
        "run_controls.minimum_positive_count",
        "positive_control_count",
        ">=",
        "count",
      ),
      _CriterionTemplate(
        "run_controls.maximum_background_count",
        "background_control_count",
        "<=",
        "count",
      ),
    ),
    note=(
      "Control identities and authorized limits come from the active operator profile; "
      "the intelligence layer records only generic evidence fields."
    ),
  ),
)


def profile_keys() -> Tuple[str, ...]:
  """Every evidence-profile key consumed by the reference gate catalog."""
  return tuple(c.key for gate in _TEMPLATES for c in gate.criteria)


def load_profile(path: str) -> Dict[str, ProfileValue]:
  """Load and validate an operator evidence profile from JSON."""
  with open(path, encoding="utf-8") as handle:
    raw = json.load(handle)
  if not isinstance(raw, dict):
    raise ValueError("an evidence profile must be a JSON object")

  unknown = sorted(set(raw) - set(profile_keys()))
  if unknown:
    raise ValueError(f"unknown evidence-profile key(s): {', '.join(unknown)}")

  profile: Dict[str, ProfileValue] = {}
  for key, item in raw.items():
    if not isinstance(item, dict):
      raise ValueError(f"evidence-profile entry '{key}' must be an object")
    try:
      raw_threshold = item["threshold"]
      source = item["source"]
      units = item["units"]
      raw_origin = item.get("origin", Origin.TRANSCRIBED.value)
      if isinstance(raw_threshold, bool) or not isinstance(raw_threshold, (int, float)):
        raise TypeError("threshold is not numeric")
      if not isinstance(source, str) or not isinstance(units, str):
        raise TypeError("source and units must be strings")
      if not isinstance(raw_origin, str):
        raise TypeError("origin must be a string")
      threshold = float(raw_threshold)
      origin = Origin(raw_origin)
    except (KeyError, TypeError, ValueError) as exc:
      raise ValueError(
        f"evidence-profile entry '{key}' needs numeric threshold, units, source, and valid origin"
      ) from exc
    profile[key] = ProfileValue(
      threshold=threshold,
      source=source,
      units=units,
      origin=origin,
    )
  return profile


def _criterion(template: _CriterionTemplate, profile: Mapping[str, ProfileValue]) -> Criterion:
  value = profile.get(template.key)
  if value is None:
    return Criterion(
      metric=template.metric,
      comparator=template.comparator,
      threshold=None,
      units=template.units,
      origin=Origin.TODO,
      source=(
        f"operator evidence profile field '{template.key}' is required and has not been "
        "supplied"
      ),
      note=template.note,
    )
  return Criterion(
    metric=template.metric,
    comparator=template.comparator,
    threshold=value.threshold,
    units=value.units,
    origin=value.origin,
    source=value.source,
    note=template.note,
  )


def build_reference_gates(
  profile: Optional[Mapping[str, ProfileValue]] = None,
) -> Dict[str, Gate]:
  """Build the reference catalog from operator-owned evidence thresholds."""
  supplied = profile or {}
  unknown = sorted(set(supplied) - set(profile_keys()))
  if unknown:
    raise ValueError(f"unknown evidence-profile key(s): {', '.join(unknown)}")
  return {
    template.name: Gate(
      name=template.name,
      guards=template.guards,
      produced_by=template.produced_by,
      criteria=tuple(_criterion(c, supplied) for c in template.criteria),
      note=template.note,
    )
    for template in _TEMPLATES
  }


REFERENCE_GATES: Dict[str, Gate] = build_reference_gates()
LIQUID_HANDLING = REFERENCE_GATES["liquid_handling_qualification"]
PREPARATION_OUTPUT = REFERENCE_GATES["preparation_output"]
LOADING_WINDOW = REFERENCE_GATES["loading_window"]
THERMAL_PERFORMANCE = REFERENCE_GATES["thermal_performance"]
RUN_CONTROL_QUALITY = REFERENCE_GATES["run_control_quality"]


# A gate guards the step it is listed against and is evaluated before that step starts.
GATES_FOR_STEP: Dict[str, Tuple[str, ...]] = {
  "wgs_prep_lysis": ("liquid_handling_qualification",),
  "pcr_enrichment_round1": ("thermal_performance",),
  "pcr_enrichment_round1_cleanup": ("preparation_output",),
  "start_run": ("loading_window",),
  "watch_run_folder": ("run_control_quality",),
}


def get(name: str, catalog: Optional[Mapping[str, Gate]] = None) -> Gate:
  gates = catalog or REFERENCE_GATES
  if name not in gates:
    raise KeyError(f"unknown gate '{name}'; known: {sorted(gates)}")
  return gates[name]


def gates_for(op: str, catalog: Optional[Mapping[str, Gate]] = None) -> List[Gate]:
  """Every gate that must clear before this operation may start."""
  gates = catalog or REFERENCE_GATES
  return [gates[name] for name in GATES_FOR_STEP.get(op, ())]
