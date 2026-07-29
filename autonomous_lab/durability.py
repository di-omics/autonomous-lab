"""What an instrument is entitled to be trusted with, given what it has done since it was serviced.

Every other layer in this package reasons about a lab in perfect health. The ledger costs a
step against a decoded command set, `qc` costs a gate against the step that feeds it, and
both quietly assume the instrument on the far end is the instrument the vendor shipped.
Instruments wear. Calibrations expire. Seals, tips, pumps, and lamps have service lives, and
consumables deplete. A schedule built on the perfect-health assumption is a schedule for the
first week.

The gap this fills is the one a real automation programme hits in month three. The run did
not fail because the code was wrong. It failed because a pump was four hundred hours past
service and nobody was tracking hours, or because the reader was recalibrated in the middle
of a plate and the numbers on either side of that moment are not the same measurement.

This is the insurance layer, and it is deliberately narrow about what insurance means. It
does NOT predict failures. Predicting them needs reliability data this package does not have
-- population lifetimes, censored failure histories, a duty cycle somebody characterized --
and inventing an MTBF would be exactly the fabricated number `throughput` already refuses
when it declines to return plates per day over eighteen untimed steps. See `NOT_COMPUTED` at
the bottom of this module, which names each prediction this layer will not make and what it
would take to make it honestly.

What it tracks instead is ENTITLEMENT: what an instrument is currently entitled to be
trusted with, given when its obligations were last discharged and what it has accumulated
since. Entitlement is a bookkeeping question, not a physics question, so it can be answered
from records a lab already keeps -- and the answer is checkable, which a predicted failure
rate is not.

Three things make this different from a maintenance calendar.

UNKNOWN IS NOT OPTIMISTIC. An instrument whose service history nobody kept is not a healthy
instrument; it is an unmeasured one. It reports UNKNOWN, UNKNOWN is not a pass, and the
whole enum is ordered so that the instrument nobody recorded ranks below the one everybody
knows is overdue -- because a lapsed obligation names its own fix and an unrecorded one does
not even establish which state the instrument is in. This is the same convention
`intelligence.trusted_for` applies to an unbenchmarked operation and `qc.evaluate` applies
to an absent measurement.

That ordering ranks verdicts and does not decide them, and one asymmetry falls out of it.
LAPSED is a proof and UNKNOWN is the absence of one, so an unmeasured unit cannot cancel a
lapse already proved on a unit that WAS counted -- it is reported alongside as an
additional finding on the same obligation. The reverse does not hold at all: ENTITLED and
EXPIRING are clearances, and nothing unmeasured supports a clearance. An interval charged
in days and runs, five hundred days past due, against a lab that never counted runs, is
lapsed on the evidence in hand, and reporting it merely UNKNOWN dropped the retrospective
alarm this module calls the harder problem.

AN INTERVAL CARRIES ITS BASIS. A vendor-stated service interval is real evidence and it is
not evidence about THIS duty cycle, which is the identical distinction `qc.Basis` already
draws about thresholds -- so this module reuses that enum rather than mirroring it. A
service interval established on a reference workload does not describe an instrument run
sixteen hours a day on picogram input, and a lab that stores the two indistinguishably has
thrown away the only information that would let it revise one. Note carefully what this does
NOT do: an unvalidated interval still governs entitlement. Basis records how much the
recurrence is worth, and refusing to honor a vendor interval because it is only a vendor
interval would be worse than honoring it.

THE LOAD-BEARING COMPUTATION IS THE BOUNDARY CROSSING, not the current state. Every
instrument in a workcell can be entitled today and the campaign can still be unrunnable,
because a plate that starts on one side of a calibration boundary and finishes on the other
has an ambiguous provenance that nothing downstream repairs. `crosses_boundary` is the
question a planner has to ask before a campaign rather than after it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .provenance import Attestation
from .qc import Basis


class Charge(str, Enum):
  """The unit an obligation accrues in.

  The line drawn here is whether the clock runs while the instrument sits idle, and it
  splits the three unevenly on purpose. RUNS and HOURS are charged by work: an instrument
  doing nothing accumulates neither, so a quiet month genuinely buys budget back. DAYS are
  charged by the calendar and nothing stops them. A planner that models only usage-based
  wear will believe a mothballed instrument stays fresh, and will discover in the same
  week that its calibration expired six months ago and that every result since the last
  one it trusted has to be reviewed.
  """

  DAYS = "days"  # calendar time since the obligation was last discharged
  RUNS = "runs"  # plates, cycles, or injections put through it
  HOURS = "hours"  # powered or actuating hours, as the lab counts them

  @property
  def accrues_when_idle(self) -> bool:
    return self is Charge.DAYS


class IntervalKind(str, Enum):
  """What kind of obligation recurs, and whether lapsing it reaches backwards.

  This is the distinction that decides how expensive a lapse is, and it is not the one
  people expect. A depleted tip box or an overdue pump service is a forward-looking
  problem: it stops the next run and costs nothing already recorded. An expired
  CALIBRATION or QUALIFICATION is retrospective. Every number the instrument produced
  between the expiry and the discovery was produced by a machine nobody could say was
  reading true, and no downstream analysis recovers that -- the data is not wrong, it is
  unattributable, which is worse because it looks fine.
  """

  CALIBRATION = "calibration"  # the instrument reads true against a reference
  QUALIFICATION = "qualification"  # it has been shown to perform the task, on this configuration
  PREVENTIVE_SERVICE = "preventive_service"  # wear parts replaced before they fail
  CONSUMABLE = "consumable"  # tips, seals, filters, reagent on board

  @property
  def invalidates_past_results(self) -> bool:
    """True when a lapse casts doubt on data the instrument already produced."""
    return self in (IntervalKind.CALIBRATION, IntervalKind.QUALIFICATION)


class Entitlement(str, Enum):
  """What an instrument may currently be trusted with. Ordered best to worst.

  UNKNOWN sits at the far end rather than in the middle, and that placement is the whole
  argument of this module. An instrument everybody knows is overdue is in a bad state that
  names its own fix: perform the service. An instrument whose history nobody kept is in no
  known state at all, and restoring it needs both the service AND the record-keeping that
  should have been running for the last two years. Ranking UNKNOWN above LAPSED would
  reward the lab that stopped writing things down.

  EXPIRING is not a defect and does not mean the instrument is unfit. It means the
  instrument is entitled today and the CAMPAIGN AS PLANNED collides with a boundary. The
  fix is to the plan or to the schedule, not to the machine.
  """

  ENTITLED = "entitled"  # every obligation discharged, with a budget the plan fits inside
  EXPIRING = "expiring"  # entitled now; the planned work crosses a boundary mid-campaign
  LAPSED = "lapsed"  # an obligation is past due
  UNKNOWN = "unknown"  # nobody recorded it, or nobody counted what it has done since

  @property
  def trustworthy(self) -> bool:
    """True only for ENTITLED.

    UNKNOWN is excluded deliberately and is the reason this property exists rather than a
    truthiness check at the call site. The absence of a service record is not evidence of
    service, in exactly the way `qc` refuses to read an absent measurement as a pass.
    """
    return self is Entitlement.ENTITLED

  @property
  def entitled_now(self) -> bool:
    """True for work that starts and finishes before any boundary in question.

    Separate from `trustworthy` because EXPIRING must not read as unfit. An instrument two
    runs from a calibration boundary is entitled to do one run and is not entitled to do a
    campaign of forty, and collapsing those into one answer forces a lab to either idle a
    healthy instrument or run the campaign anyway.
    """
    return self in (Entitlement.ENTITLED, Entitlement.EXPIRING)


# Worse is later. Combining obligations takes the worst, so one unrecorded calibration
# makes the instrument UNKNOWN however complete the rest of its history is.
_ENTITLEMENT_ORDER: Tuple[Entitlement, ...] = (
  Entitlement.ENTITLED,
  Entitlement.EXPIRING,
  Entitlement.LAPSED,
  Entitlement.UNKNOWN,
)


@dataclass(frozen=True)
class Interval:
  """A recurring obligation on one instrument, and where its recurrence came from.

  An interval may recur on more than one unit at once, and real ones usually do -- a
  calibration valid for a year or five hundred plates, whichever arrives first. Every
  declared unit is checked independently and the first to run out governs, because an
  interval that recurs on days and runs is two obligations sharing a name.

  `basis` is `qc.Basis`, reused rather than restated. A vendor service interval is VENDOR:
  real evidence, and not evidence about this duty cycle. `validated` is therefore False for
  every interval a lab has not confirmed against its own workload, which is nearly all of
  them, and that is a thing to know before treating one as a specification.

  `restores` is prose and deliberately concrete, in the same discipline
  `provenance.CustodyGap.closes_it` applies: "improve maintenance" is not an action, "run
  the two-point absorbance calibration and record both readings" is. It is required to say
  something, because `untrusted_instruments` reports an instrument's remedies by
  collecting this field, and a blank one produces a row that names an instrument untrusted
  and names nothing that would fix it.

  `instrument` is checked against the health record it is resolved through, not decoration.
  See `InstrumentHealth.__post_init__`: the same fact stored in two places disagrees
  eventually, and the disagreement here reports the wrong box entitled.
  """

  name: str
  instrument: str  # registry key or federated key
  kind: IntervalKind
  restores: str  # what discharging it restores, in bench terms
  basis: Basis
  every_days: Optional[float] = None
  every_runs: Optional[float] = None
  every_hours: Optional[float] = None
  rationale: str = ""

  def __post_init__(self) -> None:
    if not self.restores.strip():
      # An obligation that does not say what discharging it restores is an author-settable
      # field that silences half the report: the instrument is still named untrusted and
      # the work that would restore it is gone, which is the one thing the row was for.
      raise ValueError(
        f"interval '{self.name}' does not say what discharging it restores; an obligation "
        "with no stated remedy is a note, not an obligation"
      )
    declared = {
      Charge.DAYS: self.every_days,
      Charge.RUNS: self.every_runs,
      Charge.HOURS: self.every_hours,
    }
    if all(v is None for v in declared.values()):
      # An obligation that recurs on nothing can never come due, so every instrument
      # carrying one would report entitled forever. That is the vacuous pass this package
      # hunts, arriving through a data table instead of through a function.
      raise ValueError(
        f"interval '{self.name}' recurs on no unit; an obligation that never comes due is "
        "not an obligation, it is a note"
      )
    for charge, value in declared.items():
      if value is None:
        continue
      if not math.isfinite(value):
        # The same never-comes-due obligation written as a number. An infinite recurrence
        # is never exhausted and never crossed, and a NaN one compares False against every
        # test in this module, so both report entitled forever through the arithmetic
        # instead of through the missing field the guard above catches. Checked before the
        # sign test, which NaN passes.
        raise ValueError(
          f"interval '{self.name}' recurs every {value} {charge.value}, which is not a "
          "quantity that ever arrives; an obligation that never comes due is not an "
          "obligation, however it is spelled"
        )
      if value <= 0:
        raise ValueError(
          f"interval '{self.name}' recurs every {value} {charge.value}, which is already past due "
          "the moment it is discharged"
        )

  @property
  def validated(self) -> bool:
    """True only for a recurrence this lab established against its own duty cycle."""
    return self.basis.validated

  def charges(self) -> Tuple[Charge, ...]:
    """The units this obligation accrues in. Never empty; __post_init__ refuses that."""
    out: List[Charge] = []
    for charge, value in (
      (Charge.DAYS, self.every_days),
      (Charge.RUNS, self.every_runs),
      (Charge.HOURS, self.every_hours),
    ):
      if value is not None:
        out.append(charge)
    return tuple(out)

  def every(self, charge: Charge) -> Optional[float]:
    if charge is Charge.DAYS:
      return self.every_days
    if charge is Charge.RUNS:
      return self.every_runs
    return self.every_hours

  def describe(self) -> str:
    parts = [f"every {self.every(c)} {c.value}" for c in self.charges()]
    return f"{self.name}: {' or '.join(parts)}, whichever arrives first"


@dataclass(frozen=True)
class Accrued:
  """What an instrument has done since an obligation was last discharged.

  Every field is Optional and None means UNCOUNTED, never zero. The difference is the
  whole point: zero runs since the last calibration is a measurement, and a lab that never
  counted runs has not made it. Defaulting an uncounted dimension to zero would restore
  entitlement to an instrument nobody has been watching, which is the failure this module
  exists to prevent.

  None is the only sentinel for uncounted, and NaN is refused rather than accepted as a
  second one. That refusal is the whole promise above, held against the way the number
  actually arrives: a blank maintenance cell round-tripped through a spreadsheet, a CSV,
  or a JSON reader comes back as NaN, which is precisely the "nobody counted it" case this
  module exists for. NaN compares False against every threshold here, so accepting it
  reports a full budget and an entitled instrument over a cell nobody filled in. Refusing
  at the door tells the loader what to do -- an unfilled cell has to arrive as None --
  rather than guessing which of the two it meant.

  Structurally identical to `Campaign` and kept separate anyway, because one is a count of
  the past and the other is a claim about the future, and a function that accepts either
  where it meant one will eventually be handed the wrong one.
  """

  days: Optional[float] = None
  runs: Optional[float] = None
  hours: Optional[float] = None

  def __post_init__(self) -> None:
    for charge in Charge:
      value = self.charged(charge)
      if value is None:
        continue
      if not math.isfinite(value):
        raise ValueError(
          f"{value} {charge.value} accrued is not a count. A blank maintenance cell "
          "round-tripped through a spreadsheet arrives as NaN and means UNCOUNTED, so it "
          "has to arrive as None; read as a measurement it restores entitlement to an "
          "instrument nobody was watching"
        )
      if value < 0:
        raise ValueError(
          f"{value} {charge.value} accrued since this obligation was discharged; an "
          "instrument cannot have done negative work since it was serviced, and a "
          "negative accrual mints budget that was never earned"
        )

  def charged(self, charge: Charge) -> Optional[float]:
    if charge is Charge.DAYS:
      return self.days
    if charge is Charge.RUNS:
      return self.runs
    return self.hours


@dataclass(frozen=True)
class ServiceRecord:
  """One obligation, discharged: what was done, when, and on whose word.

  `attestation` is `provenance.Attestation`, reused for the same reason it exists there. A
  maintenance system that marks a service complete because it was scheduled has recorded
  intent, not evidence, and an ASSERTED record does not discharge an obligation here --
  the instrument reports UNKNOWN rather than entitled. WITNESSED is the common and
  legitimate case: a technician signed for it, which is unverifiable and real.

  `performed` is prose, read back and never parsed. Nothing in this module does date
  arithmetic, because a lab that keeps its own calendar keeps it in a format this package
  should not be guessing at. The elapsed quantities arrive in `since`, counted by the
  caller, so this layer computes over numbers somebody actually measured.
  """

  interval: str  # Interval.name
  performed: str  # when, as the lab recorded it
  by: str  # who or what discharged it
  attestation: Attestation
  since: Accrued  # what has accumulated on this instrument since, as counted by the caller
  evidence: str = ""


@dataclass(frozen=True)
class Campaign:
  """Planned work, in the units obligations are charged in.

  Days are declared separately from runs on purpose. A campaign that occupies the lab for
  ninety days charges ninety days against the calibration of every instrument in it,
  including the ones it never touches, and a plan that counts only its own plates will
  miss the boundary that catches it.

  Zero is the default and it means no work declared in that unit, which is why the
  all-zero campaign is refused where it is used rather than where it is built -- see
  `_refuse_empty_campaign`. Negative and non-finite quantities are refused here, at the
  door: a plan of minus five runs is not empty, so it survives that refusal, and it can
  never cross a boundary because it consumes budget instead of spending it.
  """

  runs: float = 0.0
  hours: float = 0.0
  days: float = 0.0

  def __post_init__(self) -> None:
    for charge in Charge:
      value = self.charged(charge)
      if not math.isfinite(value):
        raise ValueError(
          f"a campaign of {value} {charge.value} is not a plan; a quantity that compares "
          "False against every boundary in this module clears every one of them"
        )
      if value < 0:
        raise ValueError(
          f"a campaign of {value} {charge.value} is not a plan; planned work is what will "
          "be charged against an instrument's budget, and nothing gives budget back"
        )

  def charged(self, charge: Charge) -> float:
    if charge is Charge.DAYS:
      return self.days
    if charge is Charge.RUNS:
      return self.runs
    return self.hours

  @property
  def empty(self) -> bool:
    return not (self.runs or self.hours or self.days)


@dataclass(frozen=True)
class Remaining:
  """How much of one obligation's budget is left, per unit it is charged in.

  `uncounted` is the field that keeps this honest, and it is why the class exists rather
  than a float. An interval charged in runs against a lab that never counted runs has no
  remaining budget -- not a large one, none that can be stated -- and a report that
  returned a number there would be a number over an input nobody measured.

  Everything derivable is a method. A stored `exhausted` flag beside the budget it derives
  from eventually disagrees with it, and nothing reveals which one is wrong.
  """

  interval: str
  left: Tuple[Tuple[Charge, float], ...] = ()
  uncounted: Tuple[Charge, ...] = ()
  recorded: bool = False

  @property
  def computable(self) -> bool:
    return self.recorded and not self.uncounted

  def value(self, charge: Charge) -> Optional[float]:
    for c, v in self.left:
      if c is charge:
        return v
    return None

  @staticmethod
  def _spent(left: float) -> bool:
    """The boundary convention, written once because two copies of it drift apart.

    A budget of exactly zero is spent, not nearly spent. `exhausted` asks this of the
    present and `crossed_by` asks it of the state the plan ends in, and while the two were
    written separately they disagreed: a campaign consuming exactly the remaining budget
    was reported clear, and the state that same campaign produces is one this module calls
    lapsed. The last plate of a "clear" campaign was run by an instrument this module
    would not vouch for.
    """
    return left <= 0

  def exhausted(self) -> Tuple[Charge, ...]:
    """Units whose budget is spent. A budget of exactly zero is spent, not nearly spent."""
    return tuple(c for c, v in self.left if self._spent(v))

  def crossed_by(self, campaign: Campaign) -> Tuple[Charge, ...]:
    """Units where the planned work ends on or past the boundary.

    Excludes units already exhausted. Those are a lapse, which is a different finding with
    a different fix, and folding them in here would let a report about a plan absorb a
    fact about the present.
    """
    out: List[Charge] = []
    for c, v in self.left:
      if not self._spent(v) and self._spent(v - campaign.charged(c)):
        out.append(c)
    return tuple(out)


@dataclass(frozen=True)
class Standing:
  """One obligation on one instrument, resolved against what the caller actually counted.

  `restores` is the concrete next action and it differs by why the standing is bad: a
  lapse is restored by performing the obligation, an unrecorded one by performing it AND
  recording it, and a crossing by discharging the obligation before the campaign starts
  rather than during it.

  `partial` names the units nobody counted on an obligation where other units WERE
  counted, which is a different state from an obligation nobody counted at all and used to
  be reported as the same one. It qualifies a finding and never suppresses it: an interval
  charged in days and runs, past due on days, against a lab that never counted runs, is
  lapsed on the evidence it has -- and reporting that UNKNOWN because of the second unit
  dropped the row out of `lapsed()` and `invalidating()` and took the retrospective alarm
  with it.
  """

  instrument: str
  interval: Interval
  entitlement: Entitlement
  remaining: Remaining
  reason: str
  restores: str
  crossing: Tuple[Charge, ...] = ()
  partial: Tuple[Charge, ...] = ()

  @property
  def trustworthy(self) -> bool:
    return self.entitlement.trustworthy


def _remaining(interval: Interval, record: Optional[ServiceRecord]) -> Remaining:
  """Budget left on one obligation. Uncounted units are reported, never defaulted."""
  if record is None:
    return Remaining(interval=interval.name, uncounted=interval.charges(), recorded=False)
  left: List[Tuple[Charge, float]] = []
  uncounted: List[Charge] = []
  for charge in interval.charges():
    counted = record.since.charged(charge)
    if counted is None:
      uncounted.append(charge)
      continue
    every = interval.every(charge)
    left.append((charge, float(every) - float(counted)))
  return Remaining(
    interval=interval.name,
    left=tuple(left),
    uncounted=tuple(uncounted),
    recorded=True,
  )


def _refuse_empty_campaign(campaign: Optional[Campaign]) -> None:
  """The empty-campaign refusal, called from every door that accepts a plan.

  It lived on `crosses_boundary` alone, which is a guard on one of four entry points and
  therefore a guard on none: the same empty Campaign passed through `standing`,
  `InstrumentHealth.entitlement`, `entitlement_summary` and `untrusted_instruments` and
  cleared every crossing check in all four, because zero planned work crosses nothing. A
  planner who forgot to fill the campaign in got a workcell-wide clean bill.

  `campaign=None` is the no-plan case and stays legal. It is a different claim from a
  campaign of zero: one asks what the instrument is entitled to today, the other asks
  whether a plan fits, and the plan is missing.
  """
  if campaign is not None and campaign.empty:
    raise ValueError(
      "a campaign that plans no runs, hours, or days crosses nothing; state the planned "
      "work before asking whether it fits inside the instrument's entitlement"
    )


def standing(
  health: "InstrumentHealth",
  interval: Interval,
  campaign: Optional[Campaign] = None,
) -> Standing:
  """Resolve one obligation against the records this lab kept and the work it plans.

  The order of the checks is the order of severity and it matters. An obligation with no
  record is UNKNOWN before anything else is considered, because there is no baseline to
  subtract from; an obligation whose record is only ASSERTED is UNKNOWN for the same
  reason `provenance` refuses to call a command log a record of events.

  A proved lapse is checked BEFORE an uncounted unit, and the asymmetry is deliberate.
  LAPSED is a proof and UNKNOWN is the absence of one, so an unmeasured second unit cannot
  make a past-due first unit less past due -- it is reported alongside, in `partial`. The
  reverse does not hold: ENTITLED and EXPIRING are clearances, and an uncounted unit
  cannot support a clearance, so those two stay behind the uncounted check.
  """
  _refuse_empty_campaign(campaign)
  if interval.instrument != health.instrument:
    # The obligation and the health record each name an instrument, and nothing used to
    # compare them. Resolving one box's paperwork against another's service history
    # returns a verdict about neither, and it returns it as a PASS rather than as a gap.
    raise ValueError(
      f"obligation '{interval.name}' belongs to '{interval.instrument}' and is being "
      f"resolved against the service history of '{health.instrument}'; one box's "
      "paperwork does not entitle another"
    )
  record = health.record_for(interval.name)
  remaining = _remaining(interval, record)

  if record is None:
    return Standing(
      instrument=health.instrument,
      interval=interval,
      entitlement=Entitlement.UNKNOWN,
      remaining=remaining,
      reason=(
        f"no service record exists for '{interval.name}'; an instrument whose history "
        "nobody kept is unmeasured, not healthy"
      ),
      restores=(
        f"{interval.restores}, and record what was done, by whom, and the reading that "
        "confirms it. An obligation with no record cannot be discharged retroactively"
      ),
    )

  clash = health.contradictions(interval.name)
  if clash:
    moments = ", ".join(sorted({r.performed for r in clash}))
    return Standing(
      instrument=health.instrument,
      interval=interval,
      entitlement=Entitlement.UNKNOWN,
      remaining=remaining,
      reason=(
        f"{len(clash)} records claim '{interval.name}' was discharged on {moments} and "
        "disagree about what has accrued since. Which one governs is decided by which row "
        "was appended last, so the same facts return entitled or lapsed by declaration "
        "order; an instrument with two incompatible histories is unmeasured"
      ),
      restores=(
        f"withdraw or correct the duplicate records of '{interval.name}' on {moments} so "
        "one discharge is claimed once, with the accrual somebody actually counted"
      ),
    )

  if not record.attestation.is_evidence:
    return Standing(
      instrument=health.instrument,
      interval=interval,
      entitlement=Entitlement.UNKNOWN,
      remaining=remaining,
      reason=(
        f"'{interval.name}' is recorded as {record.attestation.value}: software marked it "
        "done and nothing read back. That is intent, not evidence that it happened"
      ),
      restores=(
        "have the person or instrument that performed it attest to it, so the record is "
        f"witnessed or confirmed rather than asserted; otherwise {interval.restores}"
      ),
    )

  spent = remaining.exhausted()
  if spent:
    units = ", ".join(f"{c.value} ({remaining.value(c)} left)" for c in spent)
    past = (
      " Every result it produced since is unattributable rather than wrong, which is the "
      "harder problem."
      if interval.kind.invalidates_past_results
      else ""
    )
    # The uncounted units qualify this finding and do not replace it. Reporting UNKNOWN
    # here because a second unit went uncounted erased a lapse the arithmetic had already
    # proved: the row left `lapsed()` and `invalidating()`, the retrospective alarm went
    # quiet, and the lab was told to start a counter instead of being told that months of
    # results are unattributable.
    unmeasured = ""
    also = ""
    if remaining.uncounted:
      names = ", ".join(c.value for c in remaining.uncounted)
      unmeasured = (
        f" Nobody counted {names} since, so this obligation is past due on what was "
        "counted and unmeasured on the rest, which can only make it worse."
      )
      also = f", and count {names} against this instrument from now on"
    return Standing(
      instrument=health.instrument,
      interval=interval,
      entitlement=Entitlement.LAPSED,
      remaining=remaining,
      reason=f"'{interval.name}' is past due on {units}.{past}{unmeasured}",
      restores=f"{interval.restores}{also}",
      partial=remaining.uncounted,
    )

  if remaining.uncounted:
    units = ", ".join(c.value for c in remaining.uncounted)
    # Never claim there is no budget while `remaining.left` holds one. What cannot be
    # stated is the budget for the interval, because it comes due on whichever unit
    # arrives first and one of those units is unmeasured.
    stated = ", ".join(f"{v} {c.value}" for c, v in remaining.left)
    budget = (
      f" {stated} remain on the units that were counted, and the obligation comes due on "
      "whichever unit arrives first, so that is not this interval's budget"
      if remaining.left
      else " There is no budget to state"
    )
    return Standing(
      instrument=health.instrument,
      interval=interval,
      entitlement=Entitlement.UNKNOWN,
      remaining=remaining,
      reason=(
        f"'{interval.name}' is charged in {units}, and nobody counted {units} since it was "
        f"last discharged on {record.performed}.{budget}"
      ),
      restores=(
        f"count {units} against this instrument from now on; until then the interval is a "
        "policy nobody is measuring against"
      ),
      partial=remaining.uncounted if remaining.left else (),
    )

  if campaign is not None:
    crossed = remaining.crossed_by(campaign)
    if crossed:
      units = ", ".join(
        f"{campaign.charged(c)} {c.value} planned against {remaining.value(c)} remaining"
        for c in crossed
      )
      return Standing(
        instrument=health.instrument,
        interval=interval,
        entitlement=Entitlement.EXPIRING,
        remaining=remaining,
        reason=(
          f"the campaign crosses '{interval.name}' mid-run: {units}. The instrument is "
          "entitled today and will not be by the end"
        ),
        restores=(
          f"discharge '{interval.name}' before the campaign starts, or split the campaign "
          "at the boundary so no plate spans it"
        ),
        crossing=crossed,
      )

  budget = ", ".join(f"{remaining.value(c)} {c.value}" for c in interval.charges())
  return Standing(
    instrument=health.instrument,
    interval=interval,
    entitlement=Entitlement.ENTITLED,
    remaining=remaining,
    reason=f"'{interval.name}' discharged on {record.performed}; {budget} remaining",
    restores="",
  )


@dataclass(frozen=True)
class InstrumentHealth:
  """One instrument's obligations and the records that discharge them.

  Carries no entitlement field, and that absence is enforced by a test. Entitlement is
  computed from the records and the plan every time it is asked for, in the same way the
  ledger computes verdicts rather than storing them: a stored standing beside the records
  it derives from eventually disagrees with them, and an author-settable "healthy" flag is
  the single easiest way to silence this whole report.

  An instrument with no declared obligations is UNKNOWN rather than entitled. Declaring
  none is not the same as having none, and treating an empty obligation list as a clean
  bill of health is exactly the vacuous pass `qc.evaluate` gives a gate that declares no
  criteria -- which `qc.readiness` refuses and `qc.evaluate` does not. The analogue is the
  empty CRITERIA tuple and deliberately not the empty measurement dict: `qc.evaluate`
  handles that one correctly, and citing the case a sibling gets right as the precedent
  for a case it gets wrong is the kind of claim this package's own data contradicts.

  `instrument` is the owning key, and every obligation filed here has to agree with it.
  The name is stored in two places -- here and on `Interval` -- and two stored copies of
  one fact eventually disagree, so the disagreement is refused at construction rather than
  discovered later as an instrument reporting entitled on another box's paperwork.
  """

  instrument: str
  obligations: Tuple[Interval, ...] = ()
  records: Tuple[ServiceRecord, ...] = ()
  note: str = ""

  def __post_init__(self) -> None:
    seen: List[str] = []
    for iv in self.obligations:
      if iv.instrument != self.instrument:
        raise ValueError(
          f"obligation '{iv.name}' declares instrument '{iv.instrument}' and is filed "
          f"under '{self.instrument}'; a maintenance plan for one box does not entitle "
          "another, and the misfiling reports a pass rather than a gap"
        )
      if iv.name in seen:
        # A service record names the interval it discharged and nothing else. Two
        # obligations sharing a name are therefore discharged by one signature, so a
        # calibration and a qualification that were never both performed both read as
        # done. 'annual_calibration', 'pm' and 'tip_change' are exactly the names a real
        # lab reuses.
        raise ValueError(
          f"'{iv.name}' is declared twice on {self.instrument}; two obligations sharing a "
          "name are discharged by one record, for work that was performed once"
        )
      seen.append(iv.name)

  @classmethod
  def unrecorded(cls, instrument: str) -> "InstrumentHealth":
    """The honest zero state: an instrument nobody has written anything down about."""
    return cls(
      instrument=instrument,
      note=(
        "no service interval is declared and no service record exists for this instrument "
        "in this repo"
      ),
    )

  def records_for(self, interval_name: str) -> Tuple[ServiceRecord, ...]:
    """Every record filed against one obligation, in the order the caller declared them."""
    return tuple(r for r in self.records if r.interval == interval_name)

  def record_for(self, interval_name: str) -> Optional[ServiceRecord]:
    """The most recent record for an obligation, taking the last declared as most recent.

    Order is the caller's, not a sort. Sorting would need dates parsed out of `performed`,
    and this module does no date arithmetic on purpose. Records of separate discharges are
    a service history and the later supersedes; records of the SAME discharge that
    disagree are not a history, and `contradictions` catches those before this is read.
    """
    found: Optional[ServiceRecord] = None
    for rec in self.records:
      if rec.interval == interval_name:
        found = rec
    return found

  def contradictions(self, interval_name: str) -> Tuple[ServiceRecord, ...]:
    """Records that claim the SAME discharge of an obligation and disagree about it.

    Two records performed at different moments are a history, and taking the last is what
    `record_for` is for. Two records claiming one discharge with different accruals or
    different attestations are a contradiction, and resolving it by tuple position decides
    the verdict by declaration order: the same instrument reads entitled or lapsed
    depending on which row was appended last, so appending a flattering one buries a
    lapse. Reported rather than resolved -- an instrument with two incompatible histories
    is unmeasured, which this module already ranks below overdue.
    """
    by_moment: Dict[str, List[ServiceRecord]] = {}
    for rec in self.records_for(interval_name):
      by_moment.setdefault(rec.performed, []).append(rec)
    out: List[ServiceRecord] = []
    for group in by_moment.values():
      # `since` and `attestation` are the two fields a verdict is computed from. Two
      # technicians signing one job is not a contradiction about the budget.
      if len({(r.since, r.attestation) for r in group}) > 1:
        out.extend(group)
    return tuple(out)

  def standings(self, campaign: Optional[Campaign] = None) -> Tuple[Standing, ...]:
    _refuse_empty_campaign(campaign)
    return tuple(standing(self, i, campaign) for i in self.obligations)

  def entitlement(self, campaign: Optional[Campaign] = None) -> Entitlement:
    """The worst standing among this instrument's obligations.

    Returns UNKNOWN for an instrument with no obligations declared. That is the direction
    that fails safe: a new instrument arrives untrusted and has to earn its way out,
    rather than arriving perfect because nobody has written its maintenance plan yet.
    """
    # Before the short circuit below, so an instrument with no obligations does not become
    # the one door where an empty campaign still gets an answer.
    _refuse_empty_campaign(campaign)
    if not self.obligations:
      return Entitlement.UNKNOWN
    worst = Entitlement.ENTITLED
    for row in self.standings(campaign):
      if _ENTITLEMENT_ORDER.index(row.entitlement) > _ENTITLEMENT_ORDER.index(worst):
        worst = row.entitlement
    return worst

  def lapsed(self) -> Tuple[Standing, ...]:
    return tuple(r for r in self.standings() if r.entitlement is Entitlement.LAPSED)

  def unrecorded_obligations(self) -> Tuple[Standing, ...]:
    """Obligations this lab cannot say anything about, for any of the reasons."""
    return tuple(r for r in self.standings() if r.entitlement is Entitlement.UNKNOWN)

  def partially_counted(self) -> Tuple[Standing, ...]:
    """Obligations resolved on some units while others went uncounted.

    Reported separately because the verdict on such a row rests on part of the evidence.
    A lapse proved on the counted unit stands, and the uncounted unit is still an
    unmeasured dimension on the same instrument -- two findings on one obligation, and
    collapsing them to either one loses work.
    """
    return tuple(r for r in self.standings() if r.partial)

  def conflicting(self) -> Tuple[Standing, ...]:
    """Obligations whose records contradict each other rather than accumulate."""
    return tuple(r for r in self.standings() if self.contradictions(r.interval.name))

  def unvalidated(self) -> Tuple[Interval, ...]:
    """Obligations whose recurrence this lab has not confirmed against its own duty cycle.

    Reported, and deliberately not acted on. A vendor interval still governs entitlement --
    ignoring it because it came from a manual would be worse than honoring it. This lists
    the ones whose NUMBER is borrowed, so a lab can put them in a queue to be established
    on its own workload, exactly as `qc.Gate.unvalidated` does for thresholds.
    """
    return tuple(i for i in self.obligations if not i.validated)

  def invalidating(self) -> Tuple[Standing, ...]:
    """Lapses that reach backwards into data the instrument already produced."""
    return tuple(r for r in self.lapsed() if r.interval.kind.invalidates_past_results)


# -- the boundary crossing ------------------------------------------------------


@dataclass(frozen=True)
class BoundaryReport:
  """Whether a planned campaign can run start to finish on one instrument's entitlement.

  `clear` is the field to read, and it is False for an instrument with no declared
  obligations. That case is the one worth stating explicitly: the natural implementation
  of "does anything cross" is an `all()` over the obligation list, and an `all()` over an
  empty list is True. An instrument nobody wrote a maintenance plan for would then clear
  every campaign it was ever checked against.
  """

  instrument: str
  campaign: Campaign
  rows: Tuple[Standing, ...]

  def crossings(self) -> Tuple[Standing, ...]:
    """Obligations the campaign crosses mid-run. The finding this report exists for."""
    return tuple(r for r in self.rows if r.entitlement is Entitlement.EXPIRING)

  def lapsed(self) -> Tuple[Standing, ...]:
    return tuple(r for r in self.rows if r.entitlement is Entitlement.LAPSED)

  def uncertain(self) -> Tuple[Standing, ...]:
    """Obligations that cannot be shown to be crossed or not crossed.

    Reported alongside real crossings rather than under them. An uncounted budget is not a
    small risk, it is an unavailable answer, and a campaign planned over one is planned
    over nothing.

    Includes rows whose verdict came from the units that WERE counted. A lapse proved on
    one unit belongs in `lapsed()`, and the unit nobody counted on that same obligation is
    still an unavailable answer -- one row appears in both lists because it is two
    findings.
    """
    return tuple(
      r for r in self.rows if r.entitlement is Entitlement.UNKNOWN or r.partial
    )

  @property
  def clear(self) -> bool:
    return bool(self.rows) and all(r.trustworthy for r in self.rows)

  def why_not(self) -> str:
    """One line naming what stands between this campaign and a clean start."""
    if self.clear:
      return f"every obligation on {self.instrument} outlasts the campaign as planned"
    if not self.rows:
      return (
        f"no service interval is declared for {self.instrument}; an instrument with no "
        "maintenance plan has not been shown to need none"
      )
    parts: List[str] = []
    for row in self.rows:
      if not row.trustworthy:
        parts.append(f"{row.interval.name} ({row.entitlement.value})")
    return "; ".join(parts)


def crosses_boundary(
  health: InstrumentHealth,
  campaign: Campaign,
) -> BoundaryReport:
  """Does the planned campaign cross a service or calibration boundary mid-run?

  This is the insurance question, and it is not answered by checking that every instrument
  is entitled today. A plate that starts before a calibration expires and finishes after it
  has an ambiguous provenance, and NOTHING downstream can repair that afterwards.

  Tie this to the attestation vocabulary in `provenance`, because the two are easy to
  confuse and only one of them is being solved here. A run record can be CONFIRMED at every
  step in that module's strongest sense -- the instrument reported completion and the
  report was read back -- and still not say which side of the boundary the plate was on,
  because the boundary is not an event any instrument reports. Attestation answers WHO SAYS
  THE STEP HAPPENED. Entitlement answers WHETHER THE INSTRUMENT WAS ALLOWED TO DO IT. A
  record that is unimpeachable about the first and silent about the second leaves the run
  exactly as defensible as no record at all, and the hash chain will verify perfectly while
  it does.

  A campaign that plans no work is refused rather than reported clear. Asking whether zero
  plates cross a boundary is a question about nothing, and returning a clean report to it
  would be the emptiest kind of pass this package refuses. The refusal itself lives in
  `_refuse_empty_campaign` and every entry point that accepts a plan calls it, because
  while it lived here the other three answered the same empty campaign with a clean bill.
  """
  _refuse_empty_campaign(campaign)
  return BoundaryReport(
    instrument=health.instrument,
    campaign=campaign,
    rows=health.standings(campaign),
  )


# -- the workcell view ----------------------------------------------------------


@dataclass(frozen=True)
class Untrusted:
  """One instrument that is not currently entitled, and what would restore it.

  `restores` is a tuple because an instrument is usually untrusted for more than one
  reason at once, and collapsing them to the worst one hides work. An instrument needing a
  calibration AND a pump service is two jobs, and a report that names one of them gets the
  second discovered on the morning of the campaign.
  """

  instrument: str
  entitlement: Entitlement
  reason: str
  restores: Tuple[str, ...]


def _instrument_keys(workcell) -> List[str]:
  """Every box this report is answerable for: present, plus federated, in that order."""
  keys: List[str] = list(workcell.present_keys())
  for key in workcell.federated:
    if key not in keys:
      keys.append(key)
  return keys


def _health_at(key: str, supplied: Dict[str, InstrumentHealth]) -> InstrumentHealth:
  """The health record for one instrument, refusing one filed under another's key.

  A missing record resolves to `unrecorded`: an instrument nobody wrote down is the case
  this module exists for, and it reports UNKNOWN. A record filed under the wrong key is a
  different thing entirely -- it is a record of some other box, and honoring it reports
  this one entitled on service it never had. One record filed under nine keys reported a
  whole workcell entitled and left nothing untrusted, off one calibration performed once
  on one instrument.
  """
  h = supplied.get(key)
  if h is None:
    return health_for(key)
  if h.instrument != key:
    raise ValueError(
      f"health record for '{h.instrument}' is filed under '{key}'; a service history "
      "belongs to the box the work was performed on, and crediting it to another reports "
      "an instrument entitled on paperwork that is not its own"
    )
  return h


def untrusted_instruments(
  workcell,
  health: Optional[Dict[str, InstrumentHealth]] = None,
  campaign: Optional[Campaign] = None,
) -> List[Untrusted]:
  """Which instruments in a workcell are not currently entitled, and what would fix each.

  The instrument list is resolved from the workcell rather than from the health dictionary,
  which is the whole reason the workcell is a parameter. Iterating the health records would
  report on the instruments somebody bothered to write down and silently omit the ones
  nobody did -- and those are precisely the instruments this module is about. Federated
  instruments are included: running on hardware in another repo says nothing about when the
  box was last serviced.

  A missing health record is not a missing row. It resolves to `InstrumentHealth.unrecorded`
  and reports UNKNOWN, in the same way `throughput.duration_for` resolves an untimed op to
  UNKNOWN rather than to zero.

  A workcell that declares no instrument returns a row rather than an empty list. The
  natural call shape is `if not untrusted_instruments(wc)`, which reads an empty list as a
  lab where every instrument is entitled -- the same `all()`-over-nothing that
  `BoundaryReport.clear` refuses. Emptiness is the finding here, not the absence of one.
  """
  supplied = health or {}
  _refuse_empty_campaign(campaign)
  keys = _instrument_keys(workcell)
  if not keys:
    return [
      Untrusted(
        instrument=workcell.name,
        entitlement=Entitlement.UNKNOWN,
        reason=(
          f"workcell '{workcell.name}' declares no present or federated instrument, so "
          "this report covers nothing; a lab with no boxes in it has not been shown to "
          "have no boxes out of service"
        ),
        restores=(
          "declare the instruments this workcell actually contains, then this report can "
          "say something about them",
        ),
      )
    ]

  out: List[Untrusted] = []
  for key in keys:
    h = _health_at(key, supplied)
    verdict = h.entitlement(campaign)
    if verdict.trustworthy:
      continue
    if not h.obligations:
      out.append(
        Untrusted(
          instrument=key,
          entitlement=verdict,
          reason=(
            f"no service interval is declared for '{key}' and no service record exists; "
            "an instrument nobody tracked is unmeasured, not healthy"
          ),
          restores=(
            "write down what this instrument is obliged to have done to it and how often, "
            "then record the next time each one is discharged",
          ),
        )
      )
      continue
    bad = [r for r in h.standings(campaign) if not r.trustworthy]
    out.append(
      Untrusted(
        instrument=key,
        entitlement=verdict,
        reason="; ".join(r.reason for r in bad),
        restores=tuple(r.restores for r in bad if r.restores),
      )
    )
  return out


def entitlement_summary(
  workcell,
  health: Optional[Dict[str, InstrumentHealth]] = None,
  campaign: Optional[Campaign] = None,
) -> Dict[str, int]:
  """Counts for the report. Every instrument in the workcell is in exactly one bucket.

  Refuses a workcell with nothing in it. Zero in every bucket and a total of zero is
  arithmetic over no instruments, and it reads exactly like a lab with nothing wrong --
  which is the shape of vacuous pass this package hunts, arriving as a summary instead of
  as a check.
  """
  supplied = health or {}
  _refuse_empty_campaign(campaign)
  keys = _instrument_keys(workcell)
  if not keys:
    raise ValueError(
      f"workcell '{workcell.name}' declares no present or federated instrument; counts of "
      "zero over zero instruments read as a lab with nothing out of service, so declare "
      "the instruments before summarizing them"
    )
  counts = {e.value: 0 for e in Entitlement}
  counts["total"] = len(keys)
  for key in keys:
    h = _health_at(key, supplied)
    counts[h.entitlement(campaign).value] += 1
  return counts


# -- what this lab has recorded -------------------------------------------------
# Nothing, and the empty tables below are the finding rather than an omission. They are
# empty in exactly the way `throughput.DURATIONS` is almost entirely UNKNOWN and
# `vision.VisionCapability.none` satisfies no requirement.
#
# The alternative was to fill them in, and it is worth being explicit about why that would
# be worse than leaving them bare. A plausible-looking "preventive service every 2000
# hours" written here would be a number nobody in this lab measured, sitting in a table
# other modules read, and within two releases it would be quoted as this lab's service
# interval. That is the precise mechanism by which an estimate becomes a specification, and
# it is the one `throughput` refuses when it declines to publish plates per day. A lab
# filling these in should fill them in from its own instrument manuals and its own
# maintenance history, and should record which of the two each number came from -- that is
# what `Interval.basis` is for.

OBLIGATIONS: Dict[str, Tuple[Interval, ...]] = {}

SERVICE_HISTORY: Dict[str, Tuple[ServiceRecord, ...]] = {}


def health_for(instrument: str) -> InstrumentHealth:
  """This lab's recorded health for an instrument, defaulting to nothing recorded.

  Defaulting rather than raising is the safe direction, and it is the same choice
  `throughput.duration_for` makes: a new instrument should make this report less confident,
  not crash it.
  """
  obligations = OBLIGATIONS.get(instrument, ())
  records = SERVICE_HISTORY.get(instrument, ())
  if not obligations and not records:
    return InstrumentHealth.unrecorded(instrument)
  return InstrumentHealth(instrument=instrument, obligations=obligations, records=records)


# -- what this module will not compute ------------------------------------------


@dataclass(frozen=True)
class Refusal:
  """One number this layer declines to return, and what it would take to return it.

  Recorded as data rather than left in prose so the refusal is checkable. A module that
  says in its docstring that it does not predict failures and then exposes a
  remaining-life helper has documented a discipline it does not have.
  """

  quantity: str
  why: str
  what_it_would_take: str


NOT_COMPUTED: Tuple[Refusal, ...] = (
  Refusal(
    quantity="mean time between failures",
    why=(
      "an MTBF is a population statistic. It is estimated from many units of the same "
      "model failing over time, and this lab has one of each instrument and no failure "
      "history at all. A figure computed from one box that has not broken yet is not a "
      "small-sample estimate, it is arithmetic on nothing"
    ),
    what_it_would_take=(
      "failure and censoring times across a population of the same model under a "
      "comparable duty cycle, which is a vendor's or a fleet operator's data and not this "
      "lab's"
    ),
  ),
  Refusal(
    quantity="failure rate",
    why=(
      "a rate implies a hazard function, which implies a wear model somebody fitted. "
      "Nothing here fits one. Publishing a rate would put a curve nobody measured under "
      "every schedule downstream of it, and the schedule would look quantitative"
    ),
    what_it_would_take=(
      "observed failures per unit of exposure on this duty cycle, with the exposure "
      "actually counted -- which requires the run and hour counting this module already "
      "reports is missing"
    ),
  ),
  Refusal(
    quantity="remaining useful life",
    why=(
      "the honest version of this question is a distribution, not a number, and the "
      "number is what gets used. An instrument reported as having 300 hours left will be "
      "scheduled for 290 of them by somebody who never saw the interval around it"
    ),
    what_it_would_take=(
      "a degradation signal measured on this instrument over time, plus a threshold "
      "somebody validated against real end-of-life events on the same model"
    ),
  ),
  Refusal(
    quantity="probability a campaign completes without a stoppage",
    why=(
      "this is the number a planner most wants and the one least supportable here. It "
      "multiplies per-instrument reliabilities nobody has measured and assumes they are "
      "independent, which shared power, shared operators, and a shared environment make "
      "false in a direction that flatters the answer"
    ),
    what_it_would_take=(
      "measured per-instrument reliability on this duty cycle AND a characterized "
      "correlation structure between the instruments, established on this bench or taken "
      "from work that states the bench and duty cycle it was established on"
    ),
    # The earlier wording claimed no published autonomous-lab work reports such a
    # structure. That is a universal negative over a literature, carried in a string with
    # no citation, inside a module whose argument is that an unsourced number becomes a
    # specification. It is also unnecessary: naming what the figure would require is the
    # refusal, and a claim about what a field has not shown is checkable nowhere here.
  ),
)


def refusals() -> Tuple[Refusal, ...]:
  """The predictions this layer declines to make, with what each would require.

  Worth returning rather than only documenting: a lab asking this module for a failure
  rate gets an answer that names what it would have to go and measure, instead of silence
  that invites somebody to write the estimate themselves.
  """
  return NOT_COMPUTED


__all__ = [
  "Accrued",
  "BoundaryReport",
  "Campaign",
  "Charge",
  "Entitlement",
  "InstrumentHealth",
  "Interval",
  "IntervalKind",
  "NOT_COMPUTED",
  "OBLIGATIONS",
  "Refusal",
  "Remaining",
  "SERVICE_HISTORY",
  "ServiceRecord",
  "Standing",
  "Untrusted",
  "crosses_boundary",
  "entitlement_summary",
  "health_for",
  "refusals",
  "standing",
  "untrusted_instruments",
]
