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
