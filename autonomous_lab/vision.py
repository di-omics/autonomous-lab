"""What a camera could verify at the bench, what it fundamentally cannot, and the gap.

Computer vision is where lab autonomy is usually oversold. A demo shows a model finding a
plate in a frame and the conclusion drawn is that the lab can now see. That conclusion
skips two questions this module refuses to skip.

The first is whether the condition is visible AT ALL. A camera can see that a tip is
missing. No camera can see that the enzyme in the tube lost activity in a freeze-thaw, or
that a correct-looking transfer delivered 8 uL instead of 10, or that two wells
cross-contaminated. Those are invisible in the strict sense: the failed run and the clean
run produce identical images. Sorting bench failures into VISIBLE, VISIBLE_INDIRECT, and
INVISIBLE is the first thing this module does, and it is the honest bound on what vision
can ever contribute to QC -- not what a better model would contribute, what ANY model
could.

The second is whether a check that could exist actually does. A visual check needs a
mounted camera, a known pose, controlled lighting, labeled examples of the failure, a model,
and -- the one everybody skips -- a measured sensitivity on held-out real failures. A
detector whose miss rate nobody has measured is not a safety device. It is a source of
false confidence, and installing one makes a lab less safe than having none, because the
operator stops looking.

The requirement that actually blocks this lab is LABELS, and the reason is structural
rather than budgetary: a detector needs examples of the failure, failures are rare by
design, and nobody photographs the run that went wrong at the moment it went wrong. A lab
that wants vision QC has to start collecting failure images long before it has a model,
which is a thing worth knowing early.

Nothing in this workcell has a camera. Every check here is therefore BLOCKED, and the
module reports which requirement is missing rather than implying the work is nearly done.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple


class Observable(str, Enum):
  """Whether a physical condition can be seen by a camera at all.

  The hard boundary in this enum is INVISIBLE, and it is a claim about physics rather than
  about model quality. No amount of training data separates a well containing active
  enzyme from one containing denatured enzyme, because the photons are the same. A lab
  planning vision QC needs that boundary drawn before it buys cameras, because the
  failures on the far side of it need a different instrument, not a better model.
  """

  VISIBLE = "visible"  # directly imageable: presence, position, level, color
  VISIBLE_INDIRECT = "visible_indirect"  # only a proxy or consequence is imageable
  INVISIBLE = "invisible"  # identical images either way; no camera resolves it

  @property
  def reachable_by_vision(self) -> bool:
    return self is not Observable.INVISIBLE


class VisionRequirement(str, Enum):
  """What a visual check needs before it is a check rather than an aspiration.

  Ordered roughly by how easily a lab acquires it. The ordering matters: labs buy the
  camera first because it is the purchasable one, and stall on LABELS and VALIDATION,
  which are the two that cannot be bought.
  """

  CAMERA = "camera"  # a camera exists and sees the workspace
  POSE = "pose"  # fixed mount or hand-eye calibration; pixels map to deck coordinates
  LIGHTING = "lighting"  # controlled enough that appearance is not time-of-day dependent
  LABELS = "labels"  # labeled examples of the FAILURE, not just the nominal state
  MODEL = "model"  # something that actually classifies or segments it
  VALIDATION = "validation"  # measured sensitivity on held-out real failures


@dataclass(frozen=True)
class VisualCheck:
  """One condition a camera could verify, and what it would buy.

  `catches` names the failure mode this check exists to catch, linking vision to the
  recovery taxonomy rather than leaving it as a standalone capability. A visual check that
  catches nothing in the failure model is a feature nobody asked for.

  `requires` lists everything still missing in this workcell. It is never empty in this
  repo, because there is no camera.
  """

  name: str
  step_op: str  # the step it would run before, during, or after
  observes: str  # the physical condition, in plain words
  observable: Observable
  catches: str  # failure mode name from recovery.FAILURE_MODES
  requires: Tuple[VisionRequirement, ...]
  note: str = ""

  @property
  def possible(self) -> bool:
    """True if a camera could ever do this, ignoring whether one exists."""
    return self.observable.reachable_by_vision


@dataclass(frozen=True)
class VisionCapability:
  """What vision hardware and software a workcell actually has.

  Defaults to nothing, which is the truth for every bench in this repo. `satisfied` is the
  set of requirements met; a check is available only when its requirements are a subset.
  """

  name: str = "none"
  satisfied: Tuple[VisionRequirement, ...] = ()
  note: str = ""

  @classmethod
  def none(cls) -> "VisionCapability":
    return cls(
      name="none",
      satisfied=(),
      note="no camera is mounted on any instrument in this repo; every visual check is blocked",
    )

  def missing_for(self, check: VisualCheck) -> Tuple[VisionRequirement, ...]:
    return tuple(r for r in check.requires if r not in self.satisfied)

  def available(self, check: VisualCheck) -> bool:
    return check.possible and not self.missing_for(check)


# -- the checks worth having, for the single-cell genomics loop -----------------
# Written against the real failure modes of low-input library prep. Each names what it
# would catch, so `recovery` can report which failures have a detection path and which
# have none at all.

CHECKS: Tuple[VisualCheck, ...] = (
  VisualCheck(
    name="tips_present_after_pickup",
    step_op="wgs_prep_lysis",
    observes="a tip on every channel that should have one, after the pickup move",
    observable=Observable.VISIBLE,
    catches="tip_not_picked_up",
    requires=(
      VisionRequirement.CAMERA,
      VisionRequirement.POSE,
      VisionRequirement.LABELS,
      VisionRequirement.MODEL,
      VisionRequirement.VALIDATION,
    ),
    note=(
      "the highest-value check in the list and the easiest: the failure is unambiguous in "
      "an image, the nominal state is trivially collectable, and the STAR reports nothing "
      "when a tip fails to seat"
    ),
  ),
  VisualCheck(
    name="plate_seated_and_delidded",
    step_op="wgs_prep_lysis",
    observes="the plate is flat in its nest and its lid is off before the head descends",
    observable=Observable.VISIBLE,
    catches="plate_misseated",
    requires=(
      VisionRequirement.CAMERA,
      VisionRequirement.POSE,
      VisionRequirement.LABELS,
      VisionRequirement.MODEL,
      VisionRequirement.VALIDATION,
    ),
    note="a crash check; the consequence of missing it is mechanical, not just scientific",
  ),
  VisualCheck(
    name="bead_pellet_retained_through_wash",
    step_op="pcr_enrichment_round1_cleanup",
    observes="a pellet is still on the magnet wall after the supernatant is drawn off",
    observable=Observable.VISIBLE,
    catches="bead_pellet_aspirated",
    requires=(
      VisionRequirement.CAMERA,
      VisionRequirement.POSE,
      VisionRequirement.LIGHTING,
      VisionRequirement.LABELS,
      VisionRequirement.MODEL,
      VisionRequirement.VALIDATION,
    ),
    note=(
      "the failure that most often silently destroys a low-input library: the beads carry "
      "the entire sample, aspirating them loses it completely, and every downstream step "
      "runs normally on nothing. Needs LIGHTING because a wet pellet against a dark well "
      "wall is a contrast problem before it is a detection problem"
    ),
  ),
  VisualCheck(
    name="wells_not_dry_after_incubation",
    step_op="pcr_enrichment_round1",
    observes="meniscus present in every well after the thermal hold",
    observable=Observable.VISIBLE_INDIRECT,
    catches="evaporation_during_incubation",
    requires=(
      VisionRequirement.CAMERA,
      VisionRequirement.POSE,
      VisionRequirement.LIGHTING,
      VisionRequirement.LABELS,
      VisionRequirement.MODEL,
      VisionRequirement.VALIDATION,
    ),
    note=(
      "indirect because the camera sees a meniscus, not a volume. It distinguishes dry "
      "from wet and cannot distinguish 8 uL from 10 uL, which is the loss that actually "
      "matters at this scale. Relevant here because the ODTC choreography does not close "
      "the door around the thermal leg"
    ),
  ),
  VisualCheck(
    name="single_cell_droplet_dispensed",
    step_op="start_sort",
    observes="a droplet leaves the nozzle and lands in the addressed well",
    observable=Observable.VISIBLE_INDIRECT,
    catches="empty_well_after_sort",
    requires=(
      VisionRequirement.CAMERA,
      VisionRequirement.POSE,
      VisionRequirement.LIGHTING,
      VisionRequirement.LABELS,
      VisionRequirement.MODEL,
      VisionRequirement.VALIDATION,
    ),
    note=(
      "indirect and weak: a droplet is visible, a CELL inside it is not at any practical "
      "working distance. This check confirms the dispenser fired, which is not the same "
      "claim as the well containing one cell, and reporting it as occupancy would be an "
      "overclaim"
    ),
  ),
  VisualCheck(
    name="flow_cell_seated",
    step_op="manual_load",
    observes="the flow cell is latched and the reagent bottles are in their positions",
    observable=Observable.VISIBLE,
    catches="flow_cell_misloaded",
    requires=(
      VisionRequirement.CAMERA,
      VisionRequirement.POSE,
      VisionRequirement.LABELS,
      VisionRequirement.MODEL,
      VisionRequirement.VALIDATION,
    ),
    note="a check on a human's work rather than a robot's, which is where it earns its keep",
  ),
)


CHECKS_BY_NAME: Dict[str, VisualCheck] = {c.name: c for c in CHECKS}


def checks_for(step_op: str) -> Tuple[VisualCheck, ...]:
  return tuple(c for c in CHECKS if c.step_op == step_op)


def check_catching(failure_name: str) -> Optional[VisualCheck]:
  """The visual check that would catch a named failure mode, if one is declared."""
  for c in CHECKS:
    if c.catches == failure_name:
      return c
  return None


@dataclass(frozen=True)
class VisionGap:
  """One check, and exactly what stands between here and having it."""

  check: VisualCheck
  available: bool
  missing: Tuple[VisionRequirement, ...]
  reason: str


def gaps(capability: Optional[VisionCapability] = None) -> List[VisionGap]:
  """Every declared check, costed against what this workcell actually has."""
  cap = capability or VisionCapability.none()
  out: List[VisionGap] = []
  for check in CHECKS:
    if not check.possible:
      out.append(
        VisionGap(check, False, (), "no camera resolves this condition; it needs a different sensor")
      )
      continue
    missing = cap.missing_for(check)
    if missing:
      out.append(
        VisionGap(
          check,
          False,
          missing,
          f"missing {', '.join(m.value for m in missing)}",
        )
      )
    else:
      out.append(VisionGap(check, True, (), "available in this workcell"))
  return out


def summarize(capability: Optional[VisionCapability] = None) -> Dict[str, int]:
  """Counts for the report: how many checks are available, blocked, or impossible."""
  rows = gaps(capability)
  return {
    "available": sum(1 for r in rows if r.available),
    "blocked": sum(1 for r in rows if not r.available and r.check.possible),
    "impossible": sum(1 for r in rows if not r.check.possible),
    "total": len(rows),
  }
