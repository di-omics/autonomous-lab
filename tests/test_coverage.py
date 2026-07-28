"""Device-free tests for the composition of vision, QC gates, and the failure model.

Every test here is an attempt to make this lab look covered when nothing would catch
anything. The composition is the most dangerous layer in the package for exactly that
reason: it is the one a reader trusts, it prints a table with a covered column, and both of
its inputs offer a plausible way to fill that column with something that does not exist. A
visual check is declared for a failure -- count it. A gate is declared for a failure --
count it. Do that and a workcell with no camera and a plate reader that has never returned a
number reports full coverage while its material is being destroyed silently.

So the tests that matter are the ones that hand the module something that exists and is not
usable, and insist it says so:

  a declared visual check with no camera behind it
  a gate that cannot be evaluated because its input comes from a broken instrument
  a gate that CAN be evaluated and reads the wrong assay for the sample
  a report over no rows at all, which is the vacuous pass in its purest form
  a vision capability with every requirement met, which must STILL leave the INVISIBLE
    failures uncovered, because that boundary is physics and not budget

and the one on the other side, which is the reason the module is worth having: a
material-destroying failure with neither path must appear in the report every time, never
omitted and never softened.
"""

from __future__ import annotations

import dataclasses

import pytest

from autonomous_lab import build_ledger, protocols
from autonomous_lab.coverage import (
  Cover,
  CoverageReport,
  CoverageRow,
  Uncovered,
  coverage_report,
  mandatory_gates,
  sota_lift,
  unmet_demands,
)
from autonomous_lab.qc import (
  LIBRARY_QUANT_GATE,
  SORT_OCCUPANCY_GATE,
  GateReadiness,
  GateReport,
  Readiness,
  gate_report,
)
from autonomous_lab.recovery import FAILURES_BY_NAME, Detection, Severity, recovery_report
from autonomous_lab.vision import (
  CHECKS_BY_NAME,
  Observable,
  VisionCapability,
  VisionRequirement,
  check_catching,
)


def _fully_equipped() -> VisionCapability:
  """A workcell holding every vision requirement. No such bench exists in this repo."""
  return VisionCapability(name="hypothetical", satisfied=tuple(VisionRequirement))


def _genomics():
  protocol = protocols.get("single_cell_genomics")
  ledger = build_ledger(protocol)
  return protocol, ledger, gate_report(protocol.name, ledger)


def _report(capability=None, gates=None) -> CoverageReport:
  """The composition over the genomics loop, at a stated vision capability.

  The recovery report is rebuilt against the same capability every time. That is not
  ceremony: coverage_report refuses a recovery report built against a different one, and it
  refuses it because a mismatch produces rows that are individually well-formed and describe
  a workcell nobody has.
  """
  cap = capability or VisionCapability.none()
  protocol, ledger, real_gates = _genomics()
  gates = real_gates if gates is None else gates
  return coverage_report(
    protocol, ledger, gates, recovery_report(protocol, gates, cap), cap
  )


def _row(report: CoverageReport, name: str) -> CoverageRow:
  return next(r for r in report.rows if r.failure.name == name)


def _gates_where(*readiness_rows) -> GateReport:
  """A gate report asserting a readiness the real ledger does not support.

  Built by hand on purpose. Every gate in this repo is unsatisfiable, so the only way to
  test that an EVALUABLE gate is treated correctly -- both when it counts and when it does
  not -- is to hand the module a workcell that does not exist.
  """
  return GateReport(protocol="single_cell_genomics", rows=list(readiness_rows))


# -- the vacuous pass, in each of its costumes ---------------------------------


def test_a_declared_visual_check_that_is_not_deployable_is_not_coverage():
  """The failure this module exists to refuse: counting a detector nobody has built.

  tips_present_after_pickup is declared, names the failure it catches, and is the easiest
  check in the list. None of that puts a camera on the instrument.
  """
  report = _report()
  row = _row(report, "tip_not_picked_up")

  assert row.vision_check == "tips_present_after_pickup"
  assert not row.vision_deployable
  assert row.cover is Cover.NEITHER
  assert VisionRequirement.CAMERA.value in row.vision_reason


def test_a_camera_alone_is_not_coverage():
  """The requirement labs stall on is validation, and an unvalidated detector is not one."""
  camera_only = VisionCapability(name="camera only", satisfied=(VisionRequirement.CAMERA,))
  report = _report(camera_only)
  for row in report.rows:
    assert not row.vision_deployable, f"{row.failure.name} counted a check with no validation"
  assert report.counts()["covered"] == 0


def test_an_unsatisfiable_gate_is_not_coverage():
  """A gate whose input comes from an instrument that has never returned a number.

  bead_pellet_aspirated declares the library-quant gate. The gate is real, it is on the
  protocol, and the Tecan times out deterministically, so it can never fire. Counting it
  would report the most destructive routine failure in the loop as handled.
  """
  report = _report()
  row = _row(report, "bead_pellet_aspirated")

  assert row.gate == "library_quant_before_flow_cell"
  assert not row.gate_evaluable
  assert "unsatisfiable" in row.gate_reason
  assert row.cover is Cover.NEITHER
  assert row.destroys_material


def test_an_evaluable_gate_resting_on_the_wrong_assay_is_not_coverage():
  """The quietest costume: the gate fires, the number is real, and it is about something else.

  A260 at picogram input counts carrier, primer, and free nucleotide. Repair the plate
  reader and this gate becomes evaluable and still passes an empty library, so evaluability
  alone must not be allowed to fill the covered column.
  """
  repaired = _gates_where(
    GateReadiness(LIBRARY_QUANT_GATE, Readiness.READY, "pretend the reader was fixed today")
  )
  report = _report(gates=repaired)
  row = _row(report, "enzyme_activity_lost")

  assert row.gate == "library_quant_before_flow_cell"
  assert not row.gate_evaluable
  assert "wrong assay" in row.gate_reason
  assert row.cover is Cover.NEITHER


def test_an_empty_report_is_not_complete():
  """A composition handed no rows must not report an all-clear.

  The same bug as a gate evaluated against an empty measurement dict. Every criterion is
  met, because there were none.
  """
  empty = CoverageReport(protocol="nothing", capability=VisionCapability.none(), rows=[])
  assert not empty.complete()
  assert empty.counts()["total"] == 0
  assert empty.uncovered_destructive() == []


def test_mandatory_gates_with_no_gate_report_is_a_skip_and_not_a_pass():
  """A default that reads as a PASS when it is really a SKIP would let a caller comply by
  supplying nothing at all."""
  demands = mandatory_gates()
  assert demands
  for demand in demands:
    assert not demand.met
    assert "unresolved" in demand.reason
  assert len(unmet_demands()) == len(demands)


# -- the ceiling on vision, held through the composition -----------------------


def test_full_vision_equipment_still_leaves_destructive_failures_uncovered():
  """The honest bound, restated over the composition rather than over vision alone.

  If this ever passes trivially, someone has reclassified an INVISIBLE failure or started
  counting a gate that cannot fire.
  """
  report = _report(_fully_equipped())
  uncovered = report.uncovered_destructive()
  assert uncovered, "fully equipped, and the invisible failures still destroy material unseen"
  assert not report.complete()

  names = {row.failure.name for row in uncovered}
  assert "enzyme_activity_lost" in names
  assert "cross_contamination" in names
  assert "volume_short_within_tolerance" in names


def test_no_capability_makes_an_invisible_failure_vision_covered():
  """The boundary is physics. Every capability in the test suite has to respect it."""
  for capability in (VisionCapability.none(), _fully_equipped()):
    for row in _report(capability).rows:
      if row.observable is Observable.INVISIBLE:
        assert not row.vision_deployable, (
          f"{row.failure.name} is INVISIBLE and was reported as covered by a camera"
        )
        assert row.cover is not Cover.VISION


def test_structural_and_fixable_gaps_are_not_confused():
  """Two empty coverage cells that print alike and imply different budgets."""
  report = _report()

  assert _row(report, "tip_not_picked_up").uncovered is Uncovered.FIXABLE
  assert _row(report, "volume_short_within_tolerance").uncovered is Uncovered.STRUCTURAL
  assert Uncovered.STRUCTURAL.needs_a_new_instrument
  assert not Uncovered.FIXABLE.needs_a_new_instrument

  # A gate that exists and is merely dead is an instrument repair, not a re-instrumentation.
  assert _row(report, "enzyme_activity_lost").uncovered is Uncovered.FIXABLE
  for row in report.structural():
    assert row.observable is Observable.INVISIBLE
    assert row.gate is None


# -- coverage the sibling layers cannot report ---------------------------------


def test_the_composition_finds_coverage_recovery_alone_would_miss():
  """The reason the module exists rather than being a view over recovery.

  bead_pellet_aspirated declares a gate, so recovery consults vision for it never. A
  declared visual check watches exactly that condition, and with a camera in place it holds
  the failure whether or not the plate reader is ever repaired.
  """
  protocol, ledger, gates = _genomics()
  equipped = _fully_equipped()
  silent = {
    row.failure.name for row in recovery_report(protocol, gates, equipped).destructive_and_silent()
  }
  assert "bead_pellet_aspirated" in silent

  row = _row(_report(equipped), "bead_pellet_aspirated")
  assert row.cover is Cover.VISION
  assert not row.gate_evaluable


def test_an_evaluable_gate_on_an_appropriate_assay_is_coverage():
  """The positive control. Without it, every refusal above could be passing for free."""
  sorted_ok = _gates_where(
    GateReadiness(SORT_OCCUPANCY_GATE, Readiness.READY, "pretend the sorter were decoded")
  )
  row = _row(_report(gates=sorted_ok), "empty_well_after_sort")
  assert row.gate_evaluable
  assert row.cover is Cover.GATE
  assert row.uncovered is None
  assert "already held" in row.closes_it()


def test_both_instruments_are_reported_as_both():
  """Not redundancy for its own sake: it is the only state that survives one going down."""
  sorted_ok = _gates_where(
    GateReadiness(SORT_OCCUPANCY_GATE, Readiness.READY, "pretend the sorter were decoded")
  )
  row = _row(_report(_fully_equipped(), gates=sorted_ok), "empty_well_after_sort")
  assert row.vision_deployable and row.gate_evaluable
  assert row.cover is Cover.BOTH
  assert Cover.BOTH.covered


# -- a destructive failure with neither path is never omitted ------------------


def test_every_destructive_failure_with_neither_path_is_reported():
  """The one omission that would make the whole report worse than useless."""
  report = _report()
  reported = {row.failure.name for row in report.uncovered_destructive()}
  for row in report.rows:
    if not row.cover.covered and row.destroys_material:
      assert row.failure.name in reported, f"{row.failure.name} was computed and then dropped"

  assert {
    "bead_pellet_aspirated",
    "cross_contamination",
    "index_misassignment",
    "odtc_callback_theft",
    "enzyme_activity_lost",
    "volume_short_within_tolerance",
    "wrong_reagent_right_position",
  } <= reported


def test_the_genomics_loop_covers_nothing_today():
  """Pinned, because it is the finding. Zero of fourteen failures have a machine check."""
  report = _report()
  counts = report.counts()
  assert counts["covered"] == 0
  assert counts["uncovered"] == counts["total"]
  assert counts["uncovered_destructive"] > 0
  assert not report.complete()


def test_an_uncovered_row_never_denies_a_path_recovery_already_found():
  """Uncovered means no camera and no gate. It must not be read as nothing anywhere.

  The STAR raises USBError before anything moves, and demanding a camera for that would be
  noise dressed as rigor.
  """
  report = _report()
  loud = _row(report, "star_resource_busy")
  assert loud.cover is Cover.NEITHER
  assert loud.residual is Detection.INSTRUMENT
  assert not loud.unwatched
  assert "instrument" in loud.closes_it()

  late = _row(report, "cross_contamination")
  assert late.residual is Detection.DATA_ANALYSIS
  assert "after the flow cell is spent" in late.closes_it()

  gone = _row(report, "odtc_callback_theft")
  assert gone.residual is None
  assert gone.unwatched


def test_every_uncovered_row_names_what_would_close_it():
  """A remedy column that reads 'improve coverage' has handed the problem back."""
  for capability in (VisionCapability.none(), _fully_equipped()):
    for row in _report(capability).uncovered():
      remedy = row.closes_it()
      assert len(remedy) > 40
      assert "this module cannot name" not in remedy


# -- sota_lift: what a better model buys, and what it cannot ------------------


def test_sota_lift_never_reports_a_lift_for_an_invisible_failure():
  """The overclaim the function exists to prevent, asserted directly."""
  protocol, ledger, gates = _genomics()
  lift = sota_lift(VisionCapability.none(), _fully_equipped(), protocol, ledger, gates)

  assert lift.lifted
  for moved in lift.lifted:
    assert moved.failure.observable.reachable_by_vision
    assert moved.failure.observable is not Observable.INVISIBLE
    assert moved.before is Cover.NEITHER
    assert moved.after.covered
    assert CHECKS_BY_NAME[moved.check].catches == moved.failure.name


def test_sota_lift_reports_the_failures_no_capability_moves():
  """The second list is the product. A lift shown without it is a purchase justification."""
  protocol, ledger, gates = _genomics()
  lift = sota_lift(VisionCapability.none(), _fully_equipped(), protocol, ledger, gates)

  ceiling = {c.failure.name for c in lift.ceiling}
  for name in ("enzyme_activity_lost", "cross_contamination", "index_misassignment"):
    assert name in ceiling
    assert FAILURES_BY_NAME[name].observable is Observable.INVISIBLE
  assert lift.destructive_ceiling(), "the ceiling holds failures that destroy material"
  assert set(ceiling).isdisjoint({m.failure.name for m in lift.lifted})


def test_sota_lift_at_the_top_of_the_ladder_still_has_a_ceiling():
  """Proposing the best possible capability does not empty the ceiling, at any price."""
  protocol, ledger, gates = _genomics()
  lift = sota_lift(_fully_equipped(), _fully_equipped(), protocol, ledger, gates)
  assert lift.buys_nothing, "a capability proposed against itself cannot buy anything"
  assert lift.destructive_ceiling()


def test_a_lift_names_the_requirement_the_upgrade_actually_supplied():
  """A lift that cannot say what changed is a coincidence, not a purchase argument."""
  protocol, ledger, gates = _genomics()
  lift = sota_lift(VisionCapability.none(), _fully_equipped(), protocol, ledger, gates)
  for moved in lift.lifted:
    assert moved.gained
    assert VisionRequirement.VALIDATION in moved.gained


# -- gates that are not optional ------------------------------------------------


def test_every_invisible_destructive_failure_demands_a_gate():
  """Where no camera can substitute, an assay is not one option among several."""
  _, _, gates = _genomics()
  demands = mandatory_gates(gates)
  demanded = {d.failure.name for d in demands}

  for failure in FAILURES_BY_NAME.values():
    if failure.observable is Observable.INVISIBLE and failure.severity in (
      Severity.SAMPLE,
      Severity.RUN,
    ):
      assert failure.name in demanded, f"{failure.name} destroys material unseen and demands nothing"

  for demand in demands:
    assert demand.failure.observable is Observable.INVISIBLE
    assert "no camera substitutes" in demand.statement()


def test_no_mandatory_gate_is_met_in_this_lab():
  """Pinned. Six gates must exist and none of them can fire today."""
  _, _, gates = _genomics()
  demands = mandatory_gates(gates)
  assert demands
  assert all(not d.met for d in demands)
  assert len(unmet_demands(gates)) == len(demands)

  named_nothing = [d for d in demands if d.gate is None]
  assert named_nothing, "most of these failures have no assay named for them at all"


# -- the module refuses inputs it cannot compose --------------------------------


def test_composing_reports_about_different_protocols_is_refused():
  """A blend of two labs is a number about no lab."""
  genomics, ledger, gates = _genomics()
  chemistry = protocols.get("small_molecule_qc")
  wrong = recovery_report(chemistry, None, VisionCapability.none())
  with pytest.raises(ValueError, match="one protocol"):
    coverage_report(genomics, ledger, gates, wrong, VisionCapability.none())


def test_a_recovery_report_built_against_another_capability_is_refused():
  """The quieter mismatch: every row is well-formed and describes a workcell nobody has."""
  protocol, ledger, gates = _genomics()
  stale = recovery_report(protocol, gates, VisionCapability.none())
  with pytest.raises(ValueError, match="disagree"):
    coverage_report(protocol, ledger, gates, stale, _fully_equipped())


# -- the house rules the report itself has to obey ------------------------------


def test_coverage_is_derived_and_never_a_stored_field():
  """An author-settable `cover` would be a claim of coverage, which is what this refuses.

  It is also the general rule: a derived value kept beside the values it derives from
  eventually disagrees with them, and nothing reveals which one is wrong.
  """
  stored = {f.name for f in dataclasses.fields(CoverageRow)}
  for derived in ("cover", "uncovered", "severity", "observable", "destroys_material"):
    assert derived not in stored, f"'{derived}' is derivable and must not be storable"


def test_a_reported_cover_is_backed_by_the_data_that_produced_it():
  """A claim of coverage the module's own row contradicts."""
  sorted_ok = _gates_where(
    GateReadiness(SORT_OCCUPANCY_GATE, Readiness.READY, "pretend the sorter were decoded")
  )
  equipped = _fully_equipped()
  for row in _report(equipped, gates=sorted_ok).rows:
    if row.cover in (Cover.VISION, Cover.BOTH):
      check = check_catching(row.failure.name)
      assert check is not None and equipped.available(check)
      assert check.name == row.vision_check
    if row.cover in (Cover.GATE, Cover.BOTH):
      readiness = next(r for r in sorted_ok.rows if r.gate.name == row.gate)
      assert readiness.evaluable
    assert row.cover.covered == (row.uncovered is None)
    assert row.cover.closed_by


def test_coverage_agrees_with_recovery_about_what_destroys_material():
  """Two definitions of one line eventually disagree, so there must only be one."""
  protocol, ledger, gates = _genomics()
  capability = VisionCapability.none()
  recovery = recovery_report(protocol, gates, capability)
  report = coverage_report(protocol, ledger, gates, recovery, capability)

  destructive_here = {row.failure.name for row in report.rows if row.destroys_material}
  destructive_there = {row.failure.name for row in recovery.destructive_and_silent()}
  assert destructive_there <= destructive_here


def test_the_counts_add_up():
  """A report whose own arithmetic disagrees cannot be trusted about anything else."""
  for capability in (VisionCapability.none(), _fully_equipped()):
    counts = _report(capability).counts()
    assert counts["covered"] + counts["uncovered"] == counts["total"]
    assert counts["vision"] + counts["gate"] + counts["both"] == counts["covered"]
    assert counts["fixable"] + counts["structural"] == counts["uncovered"]
    assert counts["unwatched"] <= counts["uncovered"]
    assert counts["uncovered_destructive"] <= counts["uncovered"]
