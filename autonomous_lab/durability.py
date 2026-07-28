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
  the two-point absorbance calibration and record both readings" is.
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
      if value is not None and value <= 0:
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

  Structurally identical to `Campaign` and kept separate anyway, because one is a count of
  the past and the other is a claim about the future, and a function that accepts either
  where it meant one will eventually be handed the wrong one.
  """

  days: Optional[float] = None
  runs: Optional[float] = None
  hours: Optional[float] = None

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
  """

  runs: float = 0.0
  hours: float = 0.0
  days: float = 0.0

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

  def exhausted(self) -> Tuple[Charge, ...]:
    """Units whose budget is spent. A budget of exactly zero is spent, not nearly spent."""
    return tuple(c for c, v in self.left if v <= 0)

  def crossed_by(self, campaign: Campaign) -> Tuple[Charge, ...]:
    """Units where the planned work consumes more than is left.

    Excludes units already exhausted. Those are a lapse, which is a different finding with
    a different fix, and folding them in here would let a report about a plan absorb a
    fact about the present.
    """
    out: List[Charge] = []
    for c, v in self.left:
      if v > 0 and campaign.charged(c) > v:
        out.append(c)
    return tuple(out)


@dataclass(frozen=True)
class Standing:
  """One obligation on one instrument, resolved against what the caller actually counted.

  `restores` is the concrete next action and it differs by why the standing is bad: a
  lapse is restored by performing the obligation, an unrecorded one by performing it AND
  recording it, and a crossing by discharging the obligation before the campaign starts
  rather than during it.
  """

  instrument: str
  interval: Interval
  entitlement: Entitlement
  remaining: Remaining
  reason: str
  restores: str
  crossing: Tuple[Charge, ...] = ()

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
  """
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

  if remaining.uncounted:
    units = ", ".join(c.value for c in remaining.uncounted)
    return Standing(
      instrument=health.instrument,
      interval=interval,
      entitlement=Entitlement.UNKNOWN,
      remaining=remaining,
      reason=(
        f"'{interval.name}' is charged in {units}, and nobody counted {units} since it was "
        f"last discharged on {record.performed}. There is no budget to state"
      ),
      restores=(
        f"count {units} against this instrument from now on; until then the interval is a "
        "policy nobody is measuring against"
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
    return Standing(
      instrument=health.instrument,
      interval=interval,
      entitlement=Entitlement.LAPSED,
      remaining=remaining,
      reason=f"'{interval.name}' is past due on {units}.{past}",
      restores=interval.restores,
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
  bill of health is exactly the vacuous pass a gate evaluated against an empty measurement
  dict gives.
  """

  instrument: str
  obligations: Tuple[Interval, ...] = ()
  records: Tuple[ServiceRecord, ...] = ()
  note: str = ""

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

  def record_for(self, interval_name: str) -> Optional[ServiceRecord]:
    """The most recent record for an obligation, taking the last declared as most recent.

    Order is the caller's, not a sort. Sorting would need dates parsed out of `performed`,
    and this module does no date arithmetic on purpose.
    """
    found: Optional[ServiceRecord] = None
    for rec in self.records:
      if rec.interval == interval_name:
        found = rec
    return found

  def standings(self, campaign: Optional[Campaign] = None) -> Tuple[Standing, ...]:
    return tuple(standing(self, i, campaign) for i in self.obligations)

  def entitlement(self, campaign: Optional[Campaign] = None) -> Entitlement:
    """The worst standing among this instrument's obligations.

    Returns UNKNOWN for an instrument with no obligations declared. That is the direction
    that fails safe: a new instrument arrives untrusted and has to earn its way out,
    rather than arriving perfect because nobody has written its maintenance plan yet.
    """
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
    """Obligations this lab cannot say anything about, for any of the three reasons."""
    return tuple(r for r in self.standings() if r.entitlement is Entitlement.UNKNOWN)

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
    """
    return tuple(r for r in self.rows if r.entitlement is Entitlement.UNKNOWN)

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
  would be the emptiest kind of pass this package refuses.
  """
  if campaign.empty:
    raise ValueError(
      "a campaign that plans no runs, hours, or days crosses nothing; state the planned "
      "work before asking whether it fits inside the instrument's entitlement"
    )
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
  """
  supplied = health or {}
  keys: List[str] = list(workcell.present_keys())
  for key in workcell.federated:
    if key not in keys:
      keys.append(key)

  out: List[Untrusted] = []
  for key in keys:
    h = supplied.get(key) or health_for(key)
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
  """Counts for the report. Every instrument in the workcell is in exactly one bucket."""
  supplied = health or {}
  keys: List[str] = list(workcell.present_keys())
  for key in workcell.federated:
    if key not in keys:
      keys.append(key)
  counts = {e.value: 0 for e in Entitlement}
  counts["total"] = len(keys)
  for key in keys:
    h = supplied.get(key) or health_for(key)
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
      "correlation structure between instruments, which no published autonomous-lab work "
      "reports"
    ),
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
