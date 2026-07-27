"""Device-free tests for the failure model and the vision taxonomy.

The tests that matter here try to make a failure look caught when nothing would catch it.
The declared detection path is a plan, and a plan that names a camera this lab does not
own, or a gate this lab cannot evaluate, is not a detection path. If `effective()` ever
believes one of those, every downstream safety claim inherits the lie.
"""

from __future__ import annotations

from autonomous_lab import build_ledger, protocols
from autonomous_lab.qc import gate_report
from autonomous_lab.recovery import (
  FAILURES_BY_NAME,
  Detection,
  FailureMode,
  Latency,
  Severity,
  effective,
  recovery_report,
  visual_checks_that_would_help,
)
from autonomous_lab.qc import Decision
from autonomous_lab.vision import (
  CHECKS,
  Observable,
  VisionCapability,
  VisionRequirement,
  check_catching,
  gaps,
  summarize,
)


def _fully_equipped() -> VisionCapability:
  """A workcell that has every vision requirement. No such bench exists in this repo."""
  return VisionCapability(name="hypothetical", satisfied=tuple(VisionRequirement))


# -- vision: what a camera can and cannot ever do ------------------------------


def test_no_visual_check_is_available_without_a_camera():
  counts = summarize(VisionCapability.none())
  assert counts["available"] == 0
  assert counts["blocked"] == counts["total"]


def test_every_check_names_the_requirement_it_is_missing():
  """A blocked check must say what would unblock it, not merely that it is blocked."""
  for gap in gaps(VisionCapability.none()):
    assert not gap.available
    assert gap.missing, f"{gap.check.name} is blocked but names nothing missing"
    assert VisionRequirement.CAMERA in gap.missing


def test_a_camera_alone_does_not_make_a_check_available():
  """The requirement labs actually stall on is labels and validation, not hardware."""
  cap = VisionCapability(name="camera only", satisfied=(VisionRequirement.CAMERA,))
  for gap in gaps(cap):
    assert not gap.available
    assert VisionRequirement.VALIDATION in gap.missing


def test_full_equipment_makes_the_possible_checks_available():
  counts = summarize(_fully_equipped())
  assert counts["blocked"] == 0
  assert counts["available"] == counts["total"] - counts["impossible"]


def test_an_invisible_condition_is_never_reachable_by_vision():
  """The hard boundary: no capability, however complete, resolves an INVISIBLE failure."""
  assert not Observable.INVISIBLE.reachable_by_vision
  assert Observable.VISIBLE.reachable_by_vision
  assert Observable.VISIBLE_INDIRECT.reachable_by_vision


def test_every_declared_check_catches_a_real_failure_mode():
  """A visual check that catches nothing in the failure model is a feature nobody needs."""
  for check in CHECKS:
    assert check.catches in FAILURES_BY_NAME, (
      f"{check.name} claims to catch '{check.catches}', which is not a declared failure mode"
    )


# -- effective detection: the plan versus reality ------------------------------


def test_vision_detection_degrades_to_never_without_a_camera():
  failure = FAILURES_BY_NAME["tip_not_picked_up"]
  assert failure.declared_detection is Detection.VISION
  assert failure.declared_latency is Latency.IMMEDIATE

  eff = effective(failure, None, VisionCapability.none())
  assert eff.detection is Detection.NONE
  assert eff.latency is Latency.NEVER
  assert eff.silent
  assert eff.degraded


def test_vision_detection_holds_when_the_camera_is_real():
  failure = FAILURES_BY_NAME["tip_not_picked_up"]
  eff = effective(failure, None, _fully_equipped())
  assert eff.detection is Detection.VISION
  assert eff.latency is Latency.IMMEDIATE
  assert not eff.silent


def test_qc_gate_detection_degrades_when_the_gate_is_unsatisfiable():
  """The chain that matters: a broken plate reader makes a bead loss undetectable.

  bead_pellet_aspirated declares that the library-quant gate catches it. That gate reads
  the Tecan, the Tecan cannot read a plate, so the failure is silent -- and it destroys
  the sample.
  """
  protocol = protocols.get("single_cell_genomics")
  gates = gate_report(protocol.name, build_ledger(protocol))
  eff = effective(FAILURES_BY_NAME["bead_pellet_aspirated"], gates, VisionCapability.none())
  assert eff.detection is Detection.NONE
  assert eff.latency is Latency.NEVER
  assert eff.destructive_and_silent


def test_operator_detection_of_an_invisible_condition_is_not_a_detection_path():
  """Asking a human to notice something nobody can see is a wish, not a plan."""
  failure = FAILURES_BY_NAME["wrong_reagent_right_position"]
  assert failure.declared_detection is Detection.OPERATOR
  assert failure.observable is Observable.INVISIBLE

  eff = effective(failure, None, _fully_equipped())
  assert eff.detection is Detection.NONE
  assert eff.latency is Latency.NEVER


def test_instrument_detection_is_believed():
  """A loud failure stays loud; it does not need anything else wired to work."""
  eff = effective(FAILURES_BY_NAME["star_resource_busy"], None, VisionCapability.none())
  assert eff.detection is Detection.INSTRUMENT
  assert eff.latency is Latency.IMMEDIATE
  assert not eff.silent


def test_a_failure_claiming_vision_with_no_declared_check_is_silent():
  """A plan cannot invoke a camera for a condition nobody wrote a check for."""
  invented = FailureMode(
    name="not_a_real_failure_with_no_check",
    step_op="wgs_prep_lysis",
    description="test",
    observable=Observable.VISIBLE,
    declared_detection=Detection.VISION,
    declared_latency=Latency.IMMEDIATE,
    severity=Severity.SAMPLE,
    response=Decision.ABORT,
  )
  assert check_catching(invented.name) is None
  eff = effective(invented, None, _fully_equipped())
  assert eff.latency is Latency.NEVER


def test_a_failure_naming_a_gate_not_on_the_protocol_is_silent():
  invented = FailureMode(
    name="bogus",
    step_op="wgs_prep_lysis",
    description="test",
    observable=Observable.INVISIBLE,
    declared_detection=Detection.QC_GATE,
    declared_latency=Latency.AT_NEXT_GATE,
    severity=Severity.SAMPLE,
    response=Decision.ABORT,
    via_gate="a_gate_that_does_not_exist",
  )
  protocol = protocols.get("single_cell_genomics")
  gates = gate_report(protocol.name, build_ledger(protocol))
  eff = effective(invented, gates, VisionCapability.none())
  assert eff.latency is Latency.NEVER


# -- the report ----------------------------------------------------------------


def test_genomics_has_destructive_silent_failures():
  """Pinned, because this is the finding the module exists to surface."""
  protocol = protocols.get("single_cell_genomics")
  gates = gate_report(protocol.name, build_ledger(protocol))
  report = recovery_report(protocol, gates, VisionCapability.none())

  silent = report.destructive_and_silent()
  assert silent, "the genomics loop has failures that destroy material and go unnoticed"
  names = {r.failure.name for r in silent}
  assert "bead_pellet_aspirated" in names
  assert "odtc_callback_theft" in names


def test_cameras_would_not_fix_the_invisible_failures():
  """The shopping list must not promise that hardware solves a sensing-modality problem."""
  protocol = protocols.get("single_cell_genomics")
  gates = gate_report(protocol.name, build_ledger(protocol))
  report = recovery_report(protocol, gates, VisionCapability.none())

  helpful = visual_checks_that_would_help(report)
  for name in helpful:
    check = next(c for c in CHECKS if c.name == name)
    assert check.possible, "the shopping list offered a camera for an invisible condition"

  unreachable = report.unreachable_by_vision()
  assert unreachable
  for row in unreachable:
    assert row.failure.observable is Observable.INVISIBLE


def test_report_is_scoped_to_the_protocols_own_steps():
  """A failure belonging to another flow must not inflate this one's count."""
  chem = protocols.get("small_molecule_qc")
  report = recovery_report(chem, None, VisionCapability.none())
  ops = {s.op for s in chem.steps}
  for row in report.rows:
    assert row.failure.step_op in ops


def test_buying_every_camera_still_leaves_silent_failures():
  """The honest ceiling on vision: full equipment does not close the loop.

  If this ever passes trivially, someone has quietly reclassified an INVISIBLE failure.
  """
  protocol = protocols.get("single_cell_genomics")
  gates = gate_report(protocol.name, build_ledger(protocol))
  report = recovery_report(protocol, gates, _fully_equipped())
  assert report.destructive_and_silent(), (
    "even fully equipped, the invisible failures remain undetected"
  )
