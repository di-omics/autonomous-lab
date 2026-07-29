"""Device-free tests for the durability layer.

The tests that matter here try to make an untracked instrument look healthy. Four ways in:
an instrument with no service history, an obligation charged in a unit nobody counted, a
maintenance record that software wrote to itself, and an obligation list that is empty
because nobody has written the maintenance plan yet. Every one of them is a SKIP that reads
as a PASS, and every one of them ends the same way -- a campaign starts on a machine nobody
could vouch for, and the run record is impeccable about everything except that.

The fifth test hunts the number. This module must not return a predicted failure rate under
any name, because a reliability figure invented here would become a specification nobody
measured.

The later tests hunt the same four ways in through the doors an audit found open. A NaN in
a maintenance cell is the fifth way to arrive at "nobody counted it", and it used to be
read as a measurement. An obligation that recurs every inf days is the obligation that
recurs on nothing, spelled as a number. A campaign that lands exactly on a boundary was
cleared by a report whose own arithmetic calls the state it ends in lapsed. An uncounted
second unit erased a lapse the module had already proved. One service record filed under
nine keys entitled a workcell. And a guard installed at one of four entry points is a
guard at none, which is why the empty campaign is now checked at every door in one test.
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest

from autonomous_lab import Workcell
from autonomous_lab import durability
from autonomous_lab.durability import (
  NOT_COMPUTED,
  OBLIGATIONS,
  SERVICE_HISTORY,
  Accrued,
  Campaign,
  Charge,
  Entitlement,
  InstrumentHealth,
  Interval,
  IntervalKind,
  ServiceRecord,
  crosses_boundary,
  entitlement_summary,
  health_for,
  refusals,
  standing,
  untrusted_instruments,
)
from autonomous_lab.provenance import Attestation
from autonomous_lab.qc import Basis


def _calibration(**kwargs) -> Interval:
  """A calibration obligation. Every number here is the test's, not the repo's."""
  fields = dict(
    name="absorbance_two_point",
    instrument="tecan",
    kind=IntervalKind.CALIBRATION,
    restores="run the two-point calibration and record both readings",
    basis=Basis.VENDOR,
    every_runs=100.0,
  )
  fields.update(kwargs)
  return Interval(**fields)


def _serviced(interval: Interval, since: Accrued, attestation=Attestation.WITNESSED) -> ServiceRecord:
  return ServiceRecord(
    interval=interval.name,
    performed="day 0",
    by="technician",
    attestation=attestation,
    since=since,
  )


def _health(interval: Interval, since=None, attestation=Attestation.WITNESSED) -> InstrumentHealth:
  records = () if since is None else (_serviced(interval, since, attestation),)
  return InstrumentHealth(instrument=interval.instrument, obligations=(interval,), records=records)


# -- an instrument nobody tracked is not a healthy instrument ------------------


def test_an_instrument_with_no_service_history_is_not_healthy():
  """The single most important test in the file.

  The natural implementation asks "is anything past due", finds no record of anything
  being due, and returns entitled. That is how a lab discovers in month three that the
  pump it has been running for two years has never been opened.
  """
  interval = _calibration()
  health = _health(interval)
  assert health.entitlement() is Entitlement.UNKNOWN
  assert not health.entitlement().trustworthy
  row = standing(health, interval)
  assert row.entitlement is Entitlement.UNKNOWN
  assert "no service record" in row.reason


def test_unknown_is_not_optimistic_and_ranks_below_lapsed():
  """Unmeasured is untrusted by default, and worse than known-overdue.

  A lapse names its own fix. An unrecorded obligation does not even establish what state
  the instrument is in, so it needs the service AND the record-keeping.
  """
  assert not Entitlement.UNKNOWN.trustworthy
  assert not Entitlement.UNKNOWN.entitled_now
  assert not Entitlement.LAPSED.trustworthy
  assert Entitlement.ENTITLED.trustworthy
  assert durability._ENTITLEMENT_ORDER.index(Entitlement.UNKNOWN) > durability._ENTITLEMENT_ORDER.index(
    Entitlement.LAPSED
  )


def test_no_declared_obligations_is_not_a_clean_bill_of_health():
  """The vacuous pass, arriving through an empty list instead of an empty dict.

  `all()` over no obligations is True, so an instrument nobody wrote a maintenance plan
  for would clear every check it was ever put through.
  """
  health = InstrumentHealth(instrument="star")
  assert health.entitlement() is Entitlement.UNKNOWN
  report = crosses_boundary(health, Campaign(runs=500))
  assert report.rows == ()
  assert not report.clear
  assert "has not been shown to need none" in report.why_not()


def test_an_asserted_service_record_does_not_discharge_the_obligation():
  """Software marking its own scheduled job complete is intent, not evidence.

  The same line `provenance.Attestation` draws between a command log and a record of
  events, pointed at a maintenance system.
  """
  interval = _calibration()
  health = _health(interval, since=Accrued(runs=5), attestation=Attestation.ASSERTED)
  assert health.entitlement() is Entitlement.UNKNOWN
  assert "asserted" in standing(health, interval).reason

  witnessed = _health(interval, since=Accrued(runs=5), attestation=Attestation.WITNESSED)
  assert witnessed.entitlement() is Entitlement.ENTITLED


def test_a_record_that_counts_nothing_does_not_restore_entitlement():
  """An obligation charged in runs, against a lab that never counted runs.

  There is no remaining budget here -- not a large one, none that can be stated. A number
  returned over this input would be a number over an input nobody measured.
  """
  interval = _calibration(every_runs=100.0)
  health = _health(interval, since=Accrued(days=3.0))  # days counted, runs not
  assert health.entitlement() is Entitlement.UNKNOWN
  row = standing(health, interval)
  assert Charge.RUNS in row.remaining.uncounted
  assert row.remaining.value(Charge.RUNS) is None
  assert not row.remaining.computable


def test_an_uncounted_unit_is_not_read_as_zero():
  """The default that would silently restore entitlement to every untracked instrument."""
  assert Accrued().charged(Charge.RUNS) is None
  assert Accrued(runs=0).charged(Charge.RUNS) == 0
  interval = _calibration()
  fresh = _health(interval, since=Accrued(runs=0))
  assert fresh.entitlement() is Entitlement.ENTITLED
  untracked = _health(interval, since=Accrued())
  assert untracked.entitlement() is Entitlement.UNKNOWN


def test_a_nan_accrual_is_refused_rather_than_read_as_a_measurement():
  """The other missing-number sentinel, and the one a real loader produces.

  None is the module's uncounted marker and a blank maintenance cell round-tripped through
  a spreadsheet or a JSON reader comes back as NaN, which is the same fact wearing a
  different type. NaN compares False against every threshold in this module, so reading it
  as a count reported a full budget, an ENTITLED instrument, and a clear campaign over a
  cell nobody filled in -- absent data yielding a pass, in one call.
  """
  for kwargs in ({"runs": float("nan")}, {"days": float("nan")}, {"hours": float("nan")}):
    with pytest.raises(ValueError, match="means UNCOUNTED"):
      Accrued(**kwargs)
  with pytest.raises(ValueError, match="means UNCOUNTED"):
    Accrued(runs=float("inf"))
  assert Accrued(runs=None).charged(Charge.RUNS) is None, "None remains the way to say uncounted"


def test_a_negative_accrual_cannot_mint_budget_that_was_never_earned():
  """An instrument cannot have run minus nine hundred plates since it was serviced.

  Accepted, it added to the remaining budget: a hundred-run calibration reported a
  thousand runs left and cleared a five-hundred-run campaign.
  """
  with pytest.raises(ValueError, match="negative work"):
    Accrued(runs=-900.0)
  with pytest.raises(ValueError, match="negative work"):
    Accrued(days=-1.0)


# -- lapse ----------------------------------------------------------------------


def test_an_exhausted_budget_is_lapsed():
  interval = _calibration(every_runs=100.0)
  health = _health(interval, since=Accrued(runs=100.0))
  assert health.entitlement() is Entitlement.LAPSED
  assert standing(health, interval).remaining.exhausted() == (Charge.RUNS,)


def test_the_first_unit_to_run_out_governs():
  """An interval that recurs on days and runs is two obligations sharing a name."""
  interval = _calibration(every_runs=100.0, every_days=365.0)
  health = _health(interval, since=Accrued(runs=2.0, days=400.0))
  assert health.entitlement() is Entitlement.LAPSED
  row = standing(health, interval)
  assert row.remaining.exhausted() == (Charge.DAYS,)
  assert row.remaining.value(Charge.RUNS) == 98.0


def test_calendar_time_lapses_an_instrument_that_did_no_work():
  """The wear model that only counts usage believes a mothballed instrument stays fresh."""
  assert Charge.DAYS.accrues_when_idle
  assert not Charge.RUNS.accrues_when_idle
  assert not Charge.HOURS.accrues_when_idle

  interval = _calibration(every_days=365.0, every_runs=None)
  idle = _health(interval, since=Accrued(days=400.0, runs=0.0))
  assert idle.entitlement() is Entitlement.LAPSED


def test_a_proved_lapse_survives_an_uncounted_second_unit():
  """An uncounted unit must not erase a lapse the module has already proved.

  Checking `uncounted` before `exhausted` turned a definitively past-due calibration into
  UNKNOWN the moment a second charge unit was added to the same interval, and the row left
  `lapsed()`, `invalidating()`, and the boundary report with it. The lab was told to start
  a counter; it was not told that five hundred days of results are unattributable.
  """
  interval = _calibration(name="cal_days", every_days=365.0, every_runs=500.0)
  health = _health(interval, since=Accrued(days=900.0))  # days counted, runs never

  assert health.entitlement() is Entitlement.LAPSED
  assert len(health.lapsed()) == 1
  assert len(health.invalidating()) == 1, "the retrospective alarm must not go quiet"
  row = health.lapsed()[0]
  assert row.remaining.exhausted() == (Charge.DAYS,)
  assert row.partial == (Charge.RUNS,), "the uncounted unit qualifies the finding, not the verdict"
  assert "unattributable" in row.reason
  assert "There is no budget to state" not in row.reason
  assert interval.restores in row.restores and "count runs" in row.restores

  report = crosses_boundary(health, Campaign(days=90))
  assert report.lapsed(), "the lapse reaches the campaign report too"
  assert report.uncertain(), "and the unit nobody counted is still an unavailable answer"
  assert not report.clear
  assert health.partially_counted() == (row,)


def test_a_reason_never_denies_a_budget_the_same_object_states():
  """Prose the module's own data contradicts is a claim, not a finding.

  An interval charged in two units with one of them counted has a stated remaining budget
  on that unit, and the report said "There is no budget to state" beside it.
  """
  interval = _calibration(every_runs=100.0, every_days=365.0)
  health = _health(interval, since=Accrued(days=65.0))  # days counted, runs not
  row = standing(health, interval)
  assert row.entitlement is Entitlement.UNKNOWN, "an uncounted unit still blocks a clearance"
  assert row.remaining.value(Charge.DAYS) == 300.0
  assert "300.0 days" in row.reason
  assert "There is no budget to state" not in row.reason
  assert row.partial == (Charge.RUNS,)


def test_a_calibration_lapse_reaches_backwards_and_a_tip_box_does_not():
  """The distinction that decides what a lapse costs.

  A depleted consumable stops the next run. An expired calibration means every number
  since is unattributable, and no downstream analysis recovers that.
  """
  assert IntervalKind.CALIBRATION.invalidates_past_results
  assert IntervalKind.QUALIFICATION.invalidates_past_results
  assert not IntervalKind.CONSUMABLE.invalidates_past_results
  assert not IntervalKind.PREVENTIVE_SERVICE.invalidates_past_results

  interval = _calibration(every_runs=10.0)
  health = _health(interval, since=Accrued(runs=50.0))
  assert health.invalidating()
  assert "unattributable" in health.lapsed()[0].reason


# -- the boundary crossing ------------------------------------------------------


def test_a_campaign_spanning_a_calibration_expiry_is_flagged_though_every_instrument_is_entitled():
  """The load-bearing case, and the reason a current-state check is not enough.

  Nothing is overdue. Every instrument passes a health check taken this morning. The
  campaign still cannot run, because a plate started before the boundary and finished
  after it has a provenance nothing downstream repairs.
  """
  interval = _calibration(every_runs=100.0)
  health = _health(interval, since=Accrued(runs=60.0))
  assert health.entitlement() is Entitlement.ENTITLED, "entitled today, by every current check"

  report = crosses_boundary(health, Campaign(runs=120))
  assert not report.clear
  crossings = report.crossings()
  assert len(crossings) == 1
  assert crossings[0].entitlement is Entitlement.EXPIRING
  assert crossings[0].crossing == (Charge.RUNS,)
  assert "before the campaign starts" in crossings[0].restores
  assert health.entitlement(Campaign(runs=120)) is Entitlement.EXPIRING


def test_a_campaign_inside_the_remaining_budget_is_clear():
  interval = _calibration(every_runs=100.0)
  health = _health(interval, since=Accrued(runs=60.0))
  report = crosses_boundary(health, Campaign(runs=39))
  assert report.clear
  assert report.crossings() == ()


def test_a_campaign_that_lands_exactly_on_the_boundary_crosses_it():
  """The two boundary rules on `Remaining` have to be one rule, and the module says which.

  `exhausted()` calls a budget of exactly zero spent, not nearly spent. `crossed_by` used
  a strict comparison, so a campaign consuming exactly the remaining budget was reported
  clear -- and the state that campaign produces is one this same module calls LAPSED. The
  last plate of the "clear" campaign is run by an instrument the report will not vouch
  for. The existing tests straddle this case at 39 and 120 against 40 remaining.
  """
  interval = _calibration(every_runs=100.0)
  health = _health(interval, since=Accrued(runs=60.0))  # 40 left

  assert crosses_boundary(health, Campaign(runs=39)).clear, "one short of the boundary fits"
  report = crosses_boundary(health, Campaign(runs=40))
  assert not report.clear
  assert len(report.crossings()) == 1
  assert report.crossings()[0].entitlement is Entitlement.EXPIRING
  assert report.crossings()[0].crossing == (Charge.RUNS,)

  ends_at = _health(interval, since=Accrued(runs=100.0))
  assert ends_at.entitlement() is Entitlement.LAPSED, "the state the cleared campaign ends in"


def test_an_empty_campaign_is_refused_at_every_door_that_accepts_one():
  """A guard on one of four entry points is a guard on none.

  The refusal lived on `crosses_boundary`, and the same empty Campaign passed through
  `standing`, `entitlement`, `entitlement_summary` and `untrusted_instruments`, clearing
  every crossing check because zero planned work crosses nothing. A planner who forgot to
  fill the campaign in got a workcell-wide clean bill from three of the four doors.
  """
  interval = _calibration()
  health = _health(interval, since=Accrued(runs=1.0))
  wc = Workcell.default()
  key = wc.present_keys()[0]
  supplied = {key: _health(_calibration(instrument=key), since=Accrued(runs=1.0))}

  doors = (
    lambda: standing(health, interval, Campaign()),
    lambda: health.standings(Campaign()),
    lambda: health.entitlement(Campaign()),
    lambda: crosses_boundary(health, Campaign()),
    lambda: entitlement_summary(wc, supplied, Campaign()),
    lambda: untrusted_instruments(wc, supplied, Campaign()),
    # The instrument with no obligations short-circuits before its standings are built,
    # so it is the one door an empty campaign could still walk through.
    lambda: InstrumentHealth(instrument="star").entitlement(Campaign()),
  )
  for door in doors:
    with pytest.raises(ValueError, match="crosses nothing"):
      door()

  assert health.entitlement() is Entitlement.ENTITLED, "no plan at all is a different question"


def test_a_campaign_of_negative_or_undefined_work_is_refused():
  """A campaign of minus five runs is not empty, so it survived the empty-campaign refusal.

  It also crosses nothing, ever, because it gives budget back -- and NaN clears every
  boundary in the module for the same reason a NaN interval never comes due.
  """
  for kwargs in ({"runs": -5.0}, {"days": -1.0}, {"hours": -0.5}):
    with pytest.raises(ValueError, match="is not a plan"):
      Campaign(**kwargs)
  with pytest.raises(ValueError, match="is not a plan"):
    Campaign(runs=float("nan"))
  with pytest.raises(ValueError, match="is not a plan"):
    Campaign(days=float("inf"))


def test_expiring_is_a_deadline_rather_than_a_defect():
  """EXPIRING must not read as unfit; the fix is to the plan, not to the machine."""
  assert Entitlement.EXPIRING.entitled_now
  assert not Entitlement.EXPIRING.trustworthy


def test_calendar_days_are_charged_against_an_instrument_the_campaign_never_touches():
  """A ninety-day campaign charges ninety days to every instrument in the lab.

  A plan that counts only its own plates misses the boundary that catches it.
  """
  interval = _calibration(every_days=365.0, every_runs=None)
  health = _health(interval, since=Accrued(days=300.0))
  report = crosses_boundary(health, Campaign(runs=0, days=90))
  assert report.crossings(), "an idle instrument still crosses a calendar boundary"
  assert report.crossings()[0].crossing == (Charge.DAYS,)


def test_an_uncounted_budget_cannot_be_shown_not_to_cross():
  """An unavailable answer is reported as one, not folded in with the real crossings."""
  interval = _calibration(every_runs=100.0)
  health = _health(interval, since=Accrued(days=3.0))
  report = crosses_boundary(health, Campaign(runs=10))
  assert report.crossings() == ()
  assert report.uncertain()
  assert not report.clear


def test_an_already_lapsed_instrument_does_not_report_a_clear_campaign():
  """Nothing crosses, because the boundary is already behind it. That is not clear."""
  interval = _calibration(every_runs=100.0)
  health = _health(interval, since=Accrued(runs=140.0))
  report = crosses_boundary(health, Campaign(runs=5))
  assert report.crossings() == ()
  assert report.lapsed()
  assert not report.clear


def test_a_campaign_that_plans_no_work_is_refused():
  """The emptiest pass available: asking whether zero plates cross a boundary."""
  interval = _calibration()
  health = _health(interval, since=Accrued(runs=1.0))
  with pytest.raises(ValueError, match="crosses nothing"):
    crosses_boundary(health, Campaign())


def test_the_crossing_docstring_names_the_provenance_vocabulary():
  """The tie is load-bearing prose, so a rewrite that drops it should be loud."""
  doc = crosses_boundary.__doc__ or ""
  assert "CONFIRMED" in doc
  assert "provenance" in doc


# -- basis: a borrowed interval is not a validated one -------------------------


def test_a_vendor_interval_is_not_validated_for_this_duty_cycle():
  """Real evidence, and not evidence about this workload on this input."""
  assert not _calibration(basis=Basis.VENDOR).validated
  assert not _calibration(basis=Basis.LITERATURE).validated
  assert not _calibration(basis=Basis.INTUITION).validated
  assert _calibration(basis=Basis.IN_HOUSE).validated


def test_an_unvalidated_interval_still_governs_entitlement():
  """Basis records what the number is worth; it does not excuse the obligation.

  Ignoring a vendor interval because it came from a manual would be worse than honoring
  it. The finding is that the number is borrowed, not that it can be skipped.
  """
  interval = _calibration(basis=Basis.VENDOR, every_runs=100.0)
  health = _health(interval, since=Accrued(runs=150.0))
  assert health.entitlement() is Entitlement.LAPSED
  assert health.unvalidated() == (interval,)


def test_an_interval_that_recurs_on_nothing_is_refused():
  """An obligation that never comes due would make every instrument entitled forever."""
  with pytest.raises(ValueError, match="recurs on no unit"):
    _calibration(every_runs=None, every_days=None, every_hours=None)


def test_a_nonpositive_interval_is_refused():
  with pytest.raises(ValueError, match="already past due"):
    _calibration(every_runs=0.0)


def test_an_interval_that_recurs_on_a_number_that_never_arrives_is_refused():
  """The same never-comes-due obligation, written as a number instead of a missing field.

  The guard above refuses an interval that recurs on no unit and names the reason: an
  obligation that never comes due is the vacuous pass this package hunts, arriving through
  a data table. `every_days=inf` is that obligation, and `<= 0` is False for both inf and
  NaN, so both walked past a guard written for exactly them.
  """
  for kwargs in (
    {"every_runs": float("inf")},
    {"every_runs": float("nan")},
    {"every_days": float("inf"), "every_runs": None},
    {"every_hours": float("nan"), "every_runs": None},
  ):
    with pytest.raises(ValueError, match="never comes due"):
      _calibration(**kwargs)


def test_an_obligation_that_names_no_remedy_is_refused():
  """An author-settable field that silences half the report.

  `untrusted_instruments` collects remedies by filtering out empty strings, so a blank
  `restores` produces an instrument named untrusted with nothing named that would fix it.
  The repo's own guard cannot catch it today: with OBLIGATIONS empty, every row takes the
  no-obligations branch whose remedy is a hardcoded literal, so the assertion is satisfied
  over a path nothing exercises.
  """
  with pytest.raises(ValueError, match="does not say what discharging it restores"):
    _calibration(restores="")
  with pytest.raises(ValueError, match="does not say what discharging it restores"):
    _calibration(restores="   ")

  wc = Workcell.default()
  key = wc.present_keys()[0]
  interval = _calibration(instrument=key, every_runs=10.0)
  rows = untrusted_instruments(wc, {key: _health(interval, since=Accrued(runs=999.0))})
  row = [r for r in rows if r.instrument == key][0]
  assert row.entitlement is Entitlement.LAPSED
  assert row.restores == (interval.restores,), "a lapse from a declared obligation names its fix"


# -- which record discharges which obligation, on which box --------------------


def test_two_records_of_one_discharge_do_not_resolve_by_tuple_order():
  """The same facts must not return opposite verdicts depending on declaration order.

  `record_for` takes the last match as most recent, which is right for a service history
  and wrong for two rows claiming the SAME discharge with incompatible counts. Resolved by
  position, appending a flattering row was enough to bury a lapse.
  """
  interval = _calibration(every_runs=100.0)
  overdue = _serviced(interval, Accrued(runs=400.0))
  fresh = _serviced(interval, Accrued(runs=1.0))
  kwargs = dict(instrument=interval.instrument, obligations=(interval,))

  first = InstrumentHealth(records=(overdue, fresh), **kwargs)
  second = InstrumentHealth(records=(fresh, overdue), **kwargs)
  assert first.entitlement() is second.entitlement(), "tuple order must not decide the verdict"
  assert first.entitlement() is Entitlement.UNKNOWN, "two incompatible histories are unmeasured"
  assert first.conflicting() and second.conflicting()
  assert "disagree" in first.standings()[0].reason
  assert len(first.records_for(interval.name)) == 2

  later = ServiceRecord(
    interval=interval.name,
    performed="day 300",
    by="technician",
    attestation=Attestation.WITNESSED,
    since=Accrued(runs=1.0),
  )
  history = InstrumentHealth(records=(overdue, later), **kwargs)
  assert history.entitlement() is Entitlement.ENTITLED, "separate discharges are a history"
  assert history.conflicting() == ()
  assert history.record_for(interval.name) is later


def test_one_record_cannot_discharge_two_obligations_sharing_a_name():
  """A service record names the interval it discharged and nothing else.

  Two obligations sharing a name are therefore discharged by one signature, and a
  calibration and a qualification that were never both performed both read as done.
  'annual_calibration', 'pm' and 'tip_change' are the names a real lab reuses.
  """
  calibration = _calibration(name="annual", every_days=365.0, every_runs=None)
  qualification = Interval(
    name="annual",
    instrument=calibration.instrument,
    kind=IntervalKind.QUALIFICATION,
    restores="requalify the pump head against the reference plate",
    basis=Basis.VENDOR,
    every_days=365.0,
  )
  with pytest.raises(ValueError, match="declared twice"):
    InstrumentHealth(
      instrument=calibration.instrument,
      obligations=(calibration, qualification),
      records=(_serviced(calibration, Accrued(days=10.0)),),
    )


def test_a_health_record_filed_under_another_instrument_entitles_nothing():
  """One calibration, performed once, on one box, reported nine boxes entitled.

  `Interval.instrument` and `InstrumentHealth.instrument` are two stored copies of one
  fact and nothing compared them, so the workcell view honored whatever key a record was
  filed under. The docstring defends against omitting an instrument; the failure here is
  misattribution, which produces a PASS rather than a gap.
  """
  wc = Workcell.default()
  keys = list(wc.present_keys()) + list(wc.federated)
  one = _health(_calibration(every_runs=100.0), since=Accrued(runs=1.0))
  assert one.entitlement() is Entitlement.ENTITLED, "the record is real; only its filing is wrong"

  with pytest.raises(ValueError, match="filed under"):
    entitlement_summary(wc, {k: one for k in keys})
  with pytest.raises(ValueError, match="filed under"):
    untrusted_instruments(wc, {k: one for k in keys})


def test_an_obligation_is_resolved_only_against_its_own_instruments_history():
  """One box's paperwork does not entitle another, at either level.

  Loaded through the module tables this reported tecan ENTITLED on star's pump service,
  carrying a Standing whose `.instrument` and whose `.interval.instrument` disagreed.
  """
  with pytest.raises(ValueError, match="does not entitle another"):
    InstrumentHealth(instrument="star", obligations=(_calibration(instrument="tecan"),))

  liquid_handler = _health(_calibration(instrument="liquid_handler", every_runs=100.0), since=Accrued(runs=1.0))
  with pytest.raises(ValueError, match="does not entitle another"):
    standing(liquid_handler, _calibration(instrument="tecan"))


# -- no field may silence the report -------------------------------------------


def test_health_cannot_declare_itself_entitled():
  """There is no author-settable field that makes an instrument healthy.

  The same rule `qc` applies to gate readiness and the ledger applies to automation. If
  this fails, someone added an override and the report can be made to lie.
  """
  names = {f.name for f in dataclasses.fields(InstrumentHealth)}
  for forbidden in ("entitled", "healthy", "ok", "waived", "override", "exempt", "status"):
    assert forbidden not in names, f"InstrumentHealth carries a settable '{forbidden}'"


def test_entitlement_is_derived_on_demand_rather_than_stored():
  """A derived value kept beside its inputs eventually disagrees with them."""
  assert inspect.isfunction(InstrumentHealth.entitlement)
  assert inspect.isfunction(InstrumentHealth.standings)
  interval = _calibration(every_runs=100.0)
  health = _health(interval, since=Accrued(runs=10.0))
  assert health.entitlement() is Entitlement.ENTITLED
  assert health.entitlement(Campaign(runs=200)) is Entitlement.EXPIRING


# -- the refusal ----------------------------------------------------------------


_FORBIDDEN = ("mtbf", "failure_rate", "remaining_life", "predict", "reliability", "hazard", "lifetime")


def test_no_public_callable_returns_a_failure_prediction():
  """Reliability prediction needs population data this package does not have.

  A name scan rather than a spot check, because the failure this guards against is
  somebody adding a helpful `estimate_remaining_life` in six months.
  """
  for name, obj in vars(durability).items():
    if name.startswith("_") or not callable(obj):
      continue
    if getattr(obj, "__module__", None) != durability.__name__:
      continue
    low = name.lower()
    for token in _FORBIDDEN:
      assert token not in low, f"durability exposes '{name}', which promises a prediction"


def test_no_dataclass_field_stores_a_failure_rate():
  """The same refusal applied to data, where an invented number would actually live."""
  for name, obj in vars(durability).items():
    if not (isinstance(obj, type) and dataclasses.is_dataclass(obj)):
      continue
    for field in dataclasses.fields(obj):
      low = field.name.lower()
      for token in _FORBIDDEN:
        assert token not in low, f"{name}.{field.name} would hold a number nobody measured"


def test_the_module_names_what_it_refuses_and_what_each_would_take():
  """A refusal recorded as data is checkable; one left in prose is a claim."""
  assert refusals() is NOT_COMPUTED
  assert len(NOT_COMPUTED) >= 3
  quantities = " ".join(r.quantity.lower() for r in NOT_COMPUTED)
  assert "mean time between failures" in quantities
  assert "failure rate" in quantities
  assert "remaining useful life" in quantities
  for r in NOT_COMPUTED:
    assert r.why and r.what_it_would_take, f"'{r.quantity}' is refused without saying why"


# -- the workcell view ----------------------------------------------------------


def test_this_repo_records_no_service_history_for_any_instrument():
  """Empty as a finding, not as an omission.

  A plausible service interval written into these tables would be quoted as this lab's
  service interval within two releases, which is how an estimate becomes a specification.
  """
  assert OBLIGATIONS == {}
  assert SERVICE_HISTORY == {}
  h = health_for("star")
  assert h.obligations == ()
  assert h.entitlement() is Entitlement.UNKNOWN


def test_no_instrument_in_this_workcell_is_entitled_today():
  """The finding this module exists to produce, pinned so a regression is loud."""
  wc = Workcell.default()
  rows = untrusted_instruments(wc)
  expected = len(wc.present_keys()) + len(wc.federated)
  assert len(rows) == expected
  assert all(r.entitlement is Entitlement.UNKNOWN for r in rows)
  assert all(r.restores for r in rows), "an untrusted instrument must name what would fix it"


def test_the_instrument_list_comes_from_the_workcell_not_the_health_records():
  """Iterating the health dict would report on the instruments somebody wrote down.

  Those are precisely the instruments this module is not about.
  """
  wc = Workcell.default()
  key = wc.present_keys()[0]
  interval = _calibration(instrument=key, every_runs=100.0)
  supplied = {key: _health(interval, since=Accrued(runs=1.0))}
  rows = untrusted_instruments(wc, supplied)
  names = {r.instrument for r in rows}
  assert key not in names, "the one tracked instrument is entitled"
  assert len(rows) == len(wc.present_keys()) + len(wc.federated) - 1
  for federated in wc.federated:
    assert federated in names, "a federated instrument's service history is still this lab's problem"


def test_a_campaign_moves_instruments_out_of_entitled_without_changing_the_lab():
  """The same workcell, the same records, a longer plan, a different answer."""
  wc = Workcell.default()
  key = wc.present_keys()[0]
  interval = _calibration(instrument=key, every_runs=100.0)
  supplied = {key: _health(interval, since=Accrued(runs=90.0))}

  short = entitlement_summary(wc, supplied, Campaign(runs=5))
  long = entitlement_summary(wc, supplied, Campaign(runs=50))
  assert short[Entitlement.ENTITLED.value] == 1
  assert long[Entitlement.ENTITLED.value] == 0
  assert long[Entitlement.EXPIRING.value] == 1
  assert short["total"] == long["total"] == len(wc.present_keys()) + len(wc.federated)


def test_every_instrument_lands_in_exactly_one_bucket():
  wc = Workcell.default()
  counts = entitlement_summary(wc)
  buckets = sum(counts[e.value] for e in Entitlement)
  assert buckets == counts["total"]
  assert counts[Entitlement.UNKNOWN.value] == counts["total"]


def test_a_workcell_that_declares_no_instrument_is_not_a_clean_lab():
  """The `all()`-over-nothing shape, one level up from the obligation list.

  The natural call is `if not untrusted_instruments(wc): print("every instrument
  entitled")`, and an empty list read exactly that way for a workcell that declares no
  instruments at all. `BoundaryReport.clear` guards its own version of this with
  `bool(self.rows)` and nothing here did. Emptiness is the finding, not the absence of one.
  """
  empty = Workcell(name="empty")
  assert empty.present_keys() == [] and empty.federated == ()

  rows = untrusted_instruments(empty)
  assert rows, "an empty list reads as a fully entitled lab"
  assert rows[0].entitlement is Entitlement.UNKNOWN
  assert rows[0].restores, "even this row names what would fix it"

  with pytest.raises(ValueError, match="declares no present or federated instrument"):
    entitlement_summary(empty)


# -- the prose this module rests on ---------------------------------------------


def test_the_vacuous_pass_this_module_cites_is_one_qc_actually_has():
  """A precedent has to be a case the sibling really has, checked rather than asserted.

  `qc.evaluate` refuses an empty measurement dict by name, so citing that as the vacuous
  pass would be a claim this repo's own code contradicts. The real analogue for an empty
  obligation list is a gate that declares no criteria: `qc.readiness` refuses it and
  `qc.evaluate` does not.
  """
  from autonomous_lab.ledger import build_ledger
  from autonomous_lab.protocols import SINGLE_CELL_GENOMICS
  from autonomous_lab.qc import LIBRARY_QUANT_GATE, Decision, Gate, Readiness, evaluate, readiness

  absent = evaluate(LIBRARY_QUANT_GATE, {})
  assert not absent.ok and absent.decision is not Decision.CONTINUE
  assert "not a pass" in absent.reason, "the empty measurement dict is refused by name"

  declares_nothing = Gate(name="declares_nothing", after_step="x", criteria=(), blocks="y")
  assert evaluate(declares_nothing, {}).ok, "the case durability cites: no criteria, and it passes"
  refused = readiness(declares_nothing, build_ledger(SINGLE_CELL_GENOMICS), {})
  assert refused.readiness is Readiness.UNSATISFIABLE, "and the sibling that refuses it"

  doc = InstrumentHealth.__doc__ or ""
  assert "declares no" in doc and "criteria" in doc
  assert "qc.readiness" in doc


def test_no_refusal_rests_on_a_claim_about_a_literature():
  """A refusal states what a number would require. It does not survey a field.

  "which no published autonomous-lab work reports" is a universal negative with no
  citation, carried in a string, inside a module whose argument is that an unsourced
  number becomes a specification. Nothing in this package can check it.
  """
  for r in NOT_COMPUTED:
    text = f"{r.why} {r.what_it_would_take}".lower()
    for claim in ("no published", "nobody has published", "has never been reported", "no one has shown"):
      assert claim not in text, f"'{r.quantity}' rests on a claim nothing here can check"
