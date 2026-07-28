"""Device-free tests for multi-plate scheduling.

The failure mode this guards against is a scheduler that looks useful. Given a protocol and
a plate count, the natural implementation returns a cycle time and a Gantt chart, and both
are fabrications when no step has ever been timed -- worse than nothing, because a total
gets quoted and becomes a specification nobody measured.

So the tests hold two lines. The structural results (which instrument serializes, where the
run stops, on what constraint) must be real without any timing data. And the temporal
result must stay refused.

The other load-bearing test is `arm_relief`. "Buy a plate mover" is the default answer to a
stalling schedule, and here it is wrong: an arm clears 5 of 22 stalls and none of the 8 that
are undecoded commands. If that test ever starts reporting an arm as sufficient, someone has
reclassified a decode problem as a logistics one.
"""

from __future__ import annotations

from autonomous_lab import Workcell, build_ledger, protocols
from autonomous_lab.intelligence import untrusted_ops
from autonomous_lab.orchestrate import Constraint, contention, orchestrate
from autonomous_lab.qc import gate_report


def _sched(plates=10, plr_tested=None):
  wc = Workcell.default()
  if plr_tested:
    wc.plr_tested_root = plr_tested
  p = protocols.get("single_cell_genomics")
  ledger = build_ledger(p, wc)
  return p, ledger, orchestrate(
    p, ledger, gate_report(p.name, ledger), plates=plates, untrusted=untrusted_ops(p)
  )


# -- structure that survives having no clock ------------------------------------


def test_the_bottleneck_is_the_instrument_that_owns_the_most_steps():
  """True at any speed, so it needs no stopwatch. This is the number worth having when
  every duration is unmeasured, and it names which box to buy a second of."""
  _p, _l, s = _sched()
  assert s.bottleneck is not None
  assert s.bottleneck.instrument == "namocell"
  assert s.bottleneck.steps == 7
  # Under one-process-per-instrument those serialize across every plate in flight.
  assert s.bottleneck.serialized_slots(10) == 70


def test_contention_is_ranked_and_sums_to_the_protocol():
  p = protocols.get("single_cell_genomics")
  rows = contention(p)
  assert sum(r.steps for r in rows) == len(p.steps)
  assert rows == sorted(rows, key=lambda c: (-c.steps, c.instrument))
  assert abs(sum(r.share for r in rows) - 1.0) < 1e-9


def test_a_makespan_is_refused_however_many_plates_you_ask_for():
  """`throughput` refuses this for one plate. Adding plates makes the refusal stronger,
  not weaker: a pipelined estimate compounds every unmeasured duration in it."""
  _p, _l, s = _sched(plates=500)
  assert s.makespan() is None
  assert "guess" in s.why_no_makespan()
  # And the structural results are still there, which is the point of the design.
  assert s.bottleneck.steps == 7


# -- the purchase question ------------------------------------------------------


def test_an_arm_removes_handoff_stalls_and_nothing_else():
  """The honest form of 'should we buy a plate mover'. It is the only thing that closes a
  custody gap, and it decodes no command sets."""
  _p, _l, s = _sched()
  removed, remains = s.arm_relief()
  assert removed, "an arm should clear the physical hops"
  assert all(st.constraint is Constraint.HANDOFF for st in removed)
  assert not any(st.constraint is Constraint.HANDOFF for st in remains)
  # It is not the next purchase here: far more stalls survive it than it clears.
  assert len(remains) > len(removed)
  assert any(st.constraint is Constraint.DECODE for st in remains)


def test_handoff_stalls_agree_with_the_ledgers_physical_hops():
  """One computation, not two -- the rule the provenance and lineage suites both enforce."""
  _p, ledger, s = _sched()
  hops = [st for st in s.stalls if st.constraint is Constraint.HANDOFF]
  assert len(hops) == len(ledger.handoffs()) == 5


# -- classifying rather than collapsing -----------------------------------------


def test_stalls_are_classified_because_each_one_costs_a_different_budget():
  """Collapsing these into 'blocked' is the same mistake as collapsing loop closure into
  one autonomy percentage: it hides which budget to spend."""
  _p, _l, s = _sched()
  kinds = s.by_constraint()
  assert len(kinds) >= 3
  assert kinds["decode"] > 0 and kinds["handoff"] > 0 and kinds["attended"] > 0


def test_every_stall_names_something_concrete_that_clears_it():
  """'Improve the workflow' is not an action."""
  _p, _l, s = _sched()
  assert s.stalls
  for st in s.stalls:
    assert st.clears_it and len(st.clears_it) > 20
    assert st.detail


def test_where_the_run_stops_matches_the_ledgers_headless_prefix():
  """The scheduler must not invent a different answer to a question the ledger already
  computed. Two numbers for 'how far does an unattended run get' would eventually
  disagree and nothing would reveal which was wrong."""
  _p, ledger, s = _sched()
  assert s.unattended_steps == ledger.headless_prefix()


# -- trust, scoped to where it actually binds -----------------------------------


def test_a_read_only_probe_does_not_need_a_robot_benchmark():
  """Enumerating a USB bus moves nothing. Gating it on a volumetric-accuracy benchmark
  would stall every protocol at step one and bury the constraints that differ."""
  _p, _l, s = _sched()
  trust = [st for st in s.stalls if st.constraint is Constraint.TRUST]
  assert not any(st.step_op == "discover_usb" for st in trust)


def test_trust_fires_where_the_machine_can_act_but_has_not_earned_it():
  """With plr-tested wired, two steps really run on hardware under supervision. Neither
  has a met benchmark, and that -- not decoding -- is what stands between them and running
  unattended."""
  _p, _l, s = _sched(plr_tested="/somewhere/plr-tested")
  trust = {st.step_op for st in s.stalls if st.constraint is Constraint.TRUST}
  assert "wgs_prep_lysis" in trust
  assert all("no benchmark" in st.detail for st in s.stalls if st.constraint is Constraint.TRUST)


def test_wiring_in_real_hardware_moves_stalls_between_classes_not_away():
  """Proving run cards converts DECODE stalls into TRUST stalls. The run does not become
  unattended; the reason it is not changes, and so does the next action."""
  _p, _l, bare = _sched()
  _p2, _l2, wired = _sched(plr_tested="/somewhere/plr-tested")
  assert wired.by_constraint().get("trust", 0) > bare.by_constraint().get("trust", 0)
  assert wired.unattended_steps == bare.unattended_steps  # still stops in the same place
