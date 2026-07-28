"""Turning "N plates a day" into the interval a plate must actually enter, and what that forces.

A throughput target arrives as a round number. Five hundred plates a day. It is stated in
plates and days because those are the units a budget is written in, and it is almost never
converted into the unit a workcell is actually built against, which is SECONDS BETWEEN
ADMISSIONS. The conversion is one division. It needs no measured durations, nothing about
it can be argued with, and it is consistently sobering: 500 a day is a plate entering every
172.8 seconds, sustained, including nights, weekends, and the morning after a jam.

That interval is the specification. Deck layout, buffer positions, arm reach, how many
people are on shift, how long a tip refill may take -- all of it is downstream of it, and a
lab that never computed it is designing against a number nobody wrote down.

Two figures are reported rather than one. The same 500 plates inside a staffed 16-hour day
is a plate every 115.2 seconds, which is 1.5 times tighter for no change in the target. That
ratio IS the argument for walk-away capability, stated in the only terms that make it an
argument rather than a preference: every hour the lab is not admitting plates, the hours it
is must go proportionally faster, and the penalty is multiplicative rather than additive.

THE TARGET HAS TO SAY WHAT IT COUNTS, and this module refuses one that does not. "Five
hundred plates a day" is four different specifications:

  STARTED     plates admitted to the workcell.
  COMPLETED   plates that reached the last step.
  QC_PASSED   plates that reached the last step and passed their gates.
  RELEASED    plates whose result was released for use.

Only the first is a rate a scheduler controls. The other three are outputs, and converting
an output target back into an admission interval needs the failure-and-rerun rate between
them, which is a measured quantity and not a rounding. At a 20 percent loss, 500 RELEASED
is an admission rate of 625 and an interval under 139 seconds rather than 172.8. Answering
the wrong one of the four is not a refinement; it is the difference between a workcell that
meets its target and one that misses by a quarter and cannot say which step ate it. So
`cadence_for` and `demonstrated_support` both refuse a target with no stated endpoint
instead of quietly picking the flattering reading.

WHAT THE INTERVAL FORCES is the second half. `implied_constraints` computes four things,
and the split between them is the load-bearing one: two are purchases and two are charges
against the same clock. Parallel LINES and BUFFER capacity are relieved by hardware -- a
second line, more nests. RECOVERY and UPKEEP are not. A stoppage at a sustained cadence
costs admissions at exactly the launch rate and there is no idle time in the day to make
them back, so recovering an hour means running above target afterward, which is a higher
cadence than the one anybody costed. Tips, reagents, waste, calibration, and record review
are charged against the identical window, and no published source sizes that charge.

`headroom` is where "just buy a faster robot" dies. If a human is needed on some fraction
of plates for some number of minutes, that consumes a fixed share of every admission
interval, and instrument speed appears nowhere in the arithmetic. Above 100 percent the
queue grows without bound and the target is unreachable at any hardware budget.

The last section is the honest check, and it mirrors what `throughput` does with a
makespan. `throughput` refuses to return plates per day because 18 of 18 steps have never
been timed, and that refusal stands. This module can compute an interval from arithmetic
alone, so it has nothing to refuse there -- but it must not let arithmetic be mistaken for
evidence that the rate is achievable. `demonstrated_support` answers the question that
actually matters after the division: has anybody published a system that sustains this?

Across every work cited here the answer is no, and none of them is close. The longest
continuously-operating integrated system in the list ran 17 days, in one domain, on
inorganic powders. The only citation reporting a per-day number reports a PEAK day, from a
deployment whose own authors call its scheduler non-optimal. The one work that does operate
continuously at scale across three institutions for over a thousand days is a CAGE SENSOR:
it observes, it does not actuate, its alerts are held until morning, and the analysis is
retrospective. None of that is a production rate. Every citation below is recorded with
what it does not establish, because rounding a demonstration up into a benchmark is the
exact failure this package exists to refuse.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

SECONDS_PER_HOUR = 3600.0
SECONDS_PER_DAY = 24 * SECONDS_PER_HOUR


class Endpoint(str, Enum):
  """What a plates-per-day target counts. Four different specifications, one phrase.

  The line this enum draws is between a rate the scheduler SETS and a rate the workcell
  RETURNS. Admissions are set: the scheduler decides when a plate enters and nothing
  downstream can change that decision after the fact. The other three are returns, and each
  one is the previous one multiplied by a survival fraction -- steps that abort, gates that
  fail, results withheld. A lab that states a target without saying which of these it means
  has not specified anything, because the four differ by exactly the rate at which its work
  fails, and that rate is a measurement rather than an assumption.
  """

  STARTED = "started"  # admitted to the workcell
  COMPLETED = "completed"  # reached the last step
  QC_PASSED = "qc_passed"  # reached the last step and passed its gates
  RELEASED = "released"  # result released for use

  @property
  def is_admission_rate(self) -> bool:
    """True only for STARTED: the one endpoint an interval computes directly.

    For every other endpoint the interval is strictly shorter than the naive division, by
    a factor nobody in this repo has measured. `intelligence.knowledge_summary` reports
    almost every benchmark as UNMEASURED, so the survival fraction is not merely unknown
    here, it is unknowable from what this lab has recorded.
    """
    return self is Endpoint.STARTED


@dataclass(frozen=True)
class Target:
  """A throughput target as it was actually stated, including what it left out.

  `endpoint` defaults to None on purpose rather than to STARTED. A default would resolve
  the ambiguity silently and in the direction that flatters the number -- STARTED is always
  the loosest of the four -- and the whole point of this dataclass is that the ambiguity
  survives long enough to be refused.
  """

  plates_per_day: float
  endpoint: Optional[Endpoint] = None
  note: str = ""

  def __post_init__(self) -> None:
    if self.plates_per_day <= 0:
      raise ValueError(
        f"a target of {self.plates_per_day} plates/day is not a target; an interval over it "
        "is a division by zero or a negative clock"
      )

  @property
  def ambiguous(self) -> bool:
    return self.endpoint is None

  def why_ambiguous(self) -> str:
    """The refusal, with the four readings named so the caller can pick one."""
    return (
      f"a target of {self.plates_per_day:g} plates/day does not say what it counts. It could "
      "mean plates STARTED, plates COMPLETED, plates QC_PASSED, or plates RELEASED, and those "
      "four differ by the failure and rerun rate between them. Only STARTED is an admission "
      "rate an interval computes directly; the rest need a measured survival fraction this "
      "lab does not have. State the endpoint rather than accepting the loosest reading"
    )


def launch_interval(plates_per_day: float, operating_hours: float = 24.0) -> float:
  """Seconds between plate admissions to sustain a rate inside a window.

  One division, and the only function here that needs no evidence of any kind. It is
  deliberately a function on two numbers rather than a method on `Target`: the arithmetic is
  true whatever the target means, and the endpoint refusal belongs one layer up, where the
  number becomes a claim about a lab rather than a quotient.

  The result is an ADMISSION interval. If the caller's target counts anything downstream of
  admission, this is a ceiling on the true interval and the real one is shorter -- see
  `required_admissions`.
  """
  if plates_per_day <= 0:
    raise ValueError(f"{plates_per_day} plates/day has no launch interval")
  if operating_hours <= 0:
    raise ValueError(f"{operating_hours} operating hours is not a window")
  if operating_hours > 24:
    raise ValueError(
      f"{operating_hours} operating hours does not fit in a day; a window longer than the "
      "clock it is measured against would make the interval look achievable by arithmetic"
    )
  return (operating_hours * SECONDS_PER_HOUR) / plates_per_day


def intervals(plates_per_day: float, operating_hours: float) -> Tuple[float, float]:
  """(round-the-clock seconds, staffed-hours seconds) for the same target.

  Both, always, because the gap between them is the argument. Quoting only the 24-hour
  figure describes a lab that runs unattended, and quoting only the staffed figure hides
  what unattended running would buy.
  """
  return (
    launch_interval(plates_per_day, 24.0),
    launch_interval(plates_per_day, operating_hours),
  )


def required_admissions(target: Target, yield_fraction: Optional[float] = None) -> Optional[float]:
  """Plates that must be ADMITTED per day to hit a target stated on some endpoint.

  Returns None for a downstream endpoint with no declared yield, which is the honest answer
  rather than the convenient one. The convenient answer is to assume a yield of 1.0, and it
  is wrong in a specific direction: it under-admits, so the workcell misses the target by
  exactly the failure rate and the shortfall gets blamed on the instruments.
  """
  if target.ambiguous:
    raise ValueError(target.why_ambiguous())
  if target.endpoint is not None and target.endpoint.is_admission_rate:
    return target.plates_per_day
  if yield_fraction is None:
    return None
  if not 0 < yield_fraction <= 1:
    raise ValueError(f"a yield of {yield_fraction} is not a fraction of plates that survive")
  return target.plates_per_day / yield_fraction


class Forcing(str, Enum):
  """What a sustained admission interval forces on a workcell.

  The line here is whether hardware relieves it, and it splits the four evenly. LINES and
  BUFFER are capital: a second line, a deeper hotel, a faster slowest step. RECOVERY and
  UPKEEP are charges against the same window, and no purchase order touches them -- a
  stoppage costs admissions at the launch rate whatever the instrument is capable of, and
  tips still have to be loaded, waste emptied, and audit trails reviewed inside the identical
  24 hours. Drawing the line in the enum rather than in prose is deliberate: a workcell that
  misses its target buys hardware by reflex, and two of these four say the money will not help.
  """

  LINES = "lines"  # parallel lines, because the interval is shorter than a single step
  BUFFER = "buffer"  # plates resident at once, which the deck must physically hold
  RECOVERY = "recovery"  # admissions lost per unit of downtime, unrecoverable at a sustained rate
  UPKEEP = "upkeep"  # maintenance, replenishment and record review, inside the same window

  @property
  def relieved_by_hardware(self) -> bool:
    return self in (Forcing.LINES, Forcing.BUFFER)


@dataclass(frozen=True)
class Implication:
  """One thing an admission interval forces, with the sum shown so it can be checked.

  `computable` is the field to read first, and it is False whenever the caller declared no
  duration for the quantity involved. That is the same refusal `throughput` makes: the
  reference protocol has no measured step durations at all, so a line count or a buffer
  depth over them would be a capital plan resting on a guess. RECOVERY and UPKEEP are always
  computable because they are arithmetic on the interval alone.
  """

  forcing: Forcing
  statement: str
  arithmetic: str
  computable: bool
  value: Optional[float] = None
  unachievable: bool = False  # one line cannot meet this target with the declared step

  @property
  def relieved_by_hardware(self) -> bool:
    return self.forcing.relieved_by_hardware


@dataclass(frozen=True)
class Cadence:
  """A target converted into the interval a plate must enter, and what that costs.

  Carries both intervals rather than one, plus whatever durations the caller was willing to
  declare. The implied constraints are a METHOD rather than a stored field, for the same
  reason the ledger computes verdicts instead of storing them: a derived value kept beside
  the values it derives from eventually disagrees with them, and nothing reveals which one
  is wrong. Everything here recomputes from `interval_seconds` on demand.
  """

  target: Target
  operating_hours: float
  interval_seconds: float  # inside the staffed window
  round_the_clock_seconds: float  # the same target spread over all 24 hours
  slowest_step_seconds: Optional[float] = None
  end_to_end_seconds: Optional[float] = None

  @property
  def window_seconds(self) -> float:
    return self.operating_hours * SECONDS_PER_HOUR

  @property
  def minutes_between_plates(self) -> float:
    return self.interval_seconds / 60.0

  @property
  def walk_away_multiplier(self) -> float:
    """How much tighter the staffed interval is than the round-the-clock one.

    Exactly 24 / operating_hours, which is the point: the penalty for not running unattended
    does not depend on the target, the protocol, or the instruments. It is a property of the
    clock, and it is the whole quantitative case for closing the steps that need a human.
    """
    return self.round_the_clock_seconds / self.interval_seconds

  @property
  def lines_required(self) -> Optional[int]:
    """Parallel lines needed, or None when no slowest step was declared."""
    if self.slowest_step_seconds is None:
      return None
    return max(1, math.ceil(self.slowest_step_seconds / self.interval_seconds))

  @property
  def single_line_feasible(self) -> Optional[bool]:
    """False when the interval is shorter than the slowest declared step.

    Not a scheduling result. A single line admits at most one plate per slowest-step
    duration, so a target below that is unachievable on one line no matter how fast every
    other instrument becomes, and no buffer, scheduler, or plate mover lowers the floor.
    """
    lines = self.lines_required
    return None if lines is None else lines <= 1

  @property
  def plates_in_flight(self) -> Optional[int]:
    """Plates resident in the workcell at once, or None with no end-to-end duration."""
    if self.end_to_end_seconds is None:
      return None
    return max(1, math.ceil(self.end_to_end_seconds / self.interval_seconds))

  def admissions_lost(self, stoppage_seconds: float) -> float:
    """Admissions given up by stopping for this long.

    Fractional on purpose. Rounding down would suggest a short stop is free, and at a
    sustained target it is not: the day has no idle time to absorb it, so a fraction of a
    plate lost today is a whole plate lost by the third stop.
    """
    if stoppage_seconds < 0:
      raise ValueError("a stoppage cannot be negative")
    return stoppage_seconds / self.interval_seconds

  def interval_net_of(self, upkeep_seconds: float) -> float:
    """The interval once upkeep has taken its share of the same window.

    Refuses upkeep that consumes the window rather than returning a negative or infinite
    interval, because a negative interval formats as a number and would be quoted as one.
    """
    if upkeep_seconds < 0:
      raise ValueError("upkeep cannot be negative")
    remaining = self.window_seconds - upkeep_seconds
    if remaining <= 0:
      raise ValueError(
        f"{upkeep_seconds:g} s of upkeep consumes the whole {self.window_seconds:g} s window; "
        "there is no interval left to admit a plate at, and the target is unreachable before "
        "any instrument is considered"
      )
    return remaining / self.target.plates_per_day

  def implied_constraints(self) -> List[Implication]:
    """The four things this interval forces, computed or explicitly refused.

    Order is fixed and every forcing appears exactly once, including the ones that had to be
    refused. A report that omits an unanswerable constraint reads as though it does not
    apply, which is the opposite of what a missing duration means.
    """
    return [
      self._lines(),
      self._buffer(),
      self._recovery(),
      self._upkeep(),
    ]

  # -- the four forcings -------------------------------------------------------

  def _lines(self) -> Implication:
    if self.slowest_step_seconds is None:
      return Implication(
        forcing=Forcing.LINES,
        statement=(
          "no slowest-step duration was declared, so the line count is not computable. That "
          "is not a gap in this model: `throughput` reports every step of the reference "
          "protocol as UNKNOWN, and a line count over guessed durations is a capital plan "
          "resting on a guess"
        ),
        arithmetic="ceil(slowest step / interval) -- the numerator does not exist",
        computable=False,
      )
    slowest = self.slowest_step_seconds
    lines = self.lines_required or 1
    arithmetic = f"ceil({slowest:g} s / {self.interval_seconds:.1f} s) = {lines} line(s)"
    if lines > 1:
      statement = (
        f"one line holds a plate at its slowest step for {slowest:g} s, so it admits at most "
        f"one plate per {slowest:g} s. The target needs one every {self.interval_seconds:.1f} s, "
        f"which is unachievable on a single line: {lines} lines must run in parallel. Speeding "
        "up every OTHER instrument changes nothing, because a single line's admission interval "
        "is floored by its slowest step and no scheduler, buffer, or plate mover lowers that floor"
      )
    else:
      statement = (
        f"the slowest declared step holds a line for {slowest:g} s, which fits inside the "
        f"{self.interval_seconds:.1f} s admission interval, so one line is arithmetically "
        "sufficient. That is a claim about one step and nothing else -- it assumes the caller "
        "named the true slowest step and that no two steps contend for the same instrument, "
        "which `orchestrate` computes separately and which the one-process-per-instrument rule "
        "makes the common case"
      )
    return Implication(
      forcing=Forcing.LINES,
      statement=statement,
      arithmetic=arithmetic,
      computable=True,
      value=float(lines),
      unachievable=lines > 1,
    )

  def _buffer(self) -> Implication:
    if self.end_to_end_seconds is None:
      return Implication(
        forcing=Forcing.BUFFER,
        statement=(
          "no end-to-end duration was declared, so the number of plates resident at once is "
          "not computable. `throughput` refuses a makespan for the same reason, and a buffer "
          "depth is a makespan divided by an interval -- it inherits every unmeasured second"
        ),
        arithmetic="ceil(end to end / interval) -- the numerator does not exist",
        computable=False,
      )
    e2e = self.end_to_end_seconds
    resident = self.plates_in_flight or 1
    return Implication(
      forcing=Forcing.BUFFER,
      statement=(
        f"a plate is inside the workcell for {e2e:g} s end to end. At an admission every "
        f"{self.interval_seconds:.1f} s that is {resident} plates resident simultaneously, so "
        f"the decks, nests and hotel must physically hold {resident} plates and the record must "
        f"tell all {resident} apart -- `provenance` counts an unobserved custody hop for every "
        "one it cannot. ISO 23783-1:2022 and ISO 23783-3:2022 specify automated liquid handler "
        "vocabulary and volumetric performance reporting; neither states a rate or a capacity, "
        "so no published standard sizes this for you"
      ),
      arithmetic=f"ceil({e2e:g} s / {self.interval_seconds:.1f} s) = {resident} plates resident",
      computable=True,
      value=float(resident),
    )

  def _recovery(self) -> Implication:
    per_minute = 60.0 / self.interval_seconds
    return Implication(
      forcing=Forcing.RECOVERY,
      statement=(
        f"a stoppage costs {per_minute:.2f} admissions for every minute stopped, and a "
        "SUSTAINED target has no idle time to make them back. Recovering an hour means running "
        "above the target afterward, which is a higher cadence than the one anybody costed, and "
        "it compounds with whatever caused the stoppage. Published autonomous runs report "
        "recovery as human work: AlabOS carries an explicit user-request module for robot-arm "
        "error recovery and consumable replacement, and its authors state that worn hardware and "
        "communication exceptions not caught in soak testing still require operators"
      ),
      arithmetic=(
        f"60 s / {self.interval_seconds:.1f} s = {per_minute:.2f} admissions lost per minute"
      ),
      computable=True,
      value=per_minute,
    )

  def _upkeep(self) -> Implication:
    per_hour = SECONDS_PER_HOUR / self.interval_seconds
    return Implication(
      forcing=Forcing.UPKEEP,
      statement=(
        "tips, reagents, waste, calibration and record review are charged against the same "
        f"window as the plates. Every {self.interval_seconds:.1f} s of upkeep inside the "
        f"{self.operating_hours:g} h window costs exactly one admission, so an hour of daily "
        f"upkeep costs {per_hour:.1f} plates. The FDA data integrity guidance expects audit "
        "trails to be reviewed and deliberately prescribes no frequency, deferring to the firm's "
        "own risk assessment -- so the charge is real, it recurs every day, and no published "
        "source sizes it. It has to come out of this window or out of the target"
      ),
      arithmetic=(
        f"3600 s / {self.interval_seconds:.1f} s = {per_hour:.1f} plates per hour of upkeep"
      ),
      computable=True,
      value=per_hour,
    )


def cadence_for(
  target,
  operating_hours: float = 24.0,
  slowest_step_seconds: Optional[float] = None,
  end_to_end_seconds: Optional[float] = None,
) -> Cadence:
  """Convert a stated target into a sustained admission interval.

  Accepts a `Target` or a bare number, and refuses the bare number for the same reason it
  refuses a `Target` with no endpoint: a plain float carries no statement of what it counts,
  so accepting one would be an undocumented route around the refusal rather than a
  convenience.
  """
  t = target if isinstance(target, Target) else Target(plates_per_day=float(target))
  if t.ambiguous:
    raise ValueError(t.why_ambiguous())
  for name, value in (
    ("slowest_step_seconds", slowest_step_seconds),
    ("end_to_end_seconds", end_to_end_seconds),
  ):
    if value is not None and value <= 0:
      raise ValueError(f"{name} of {value} is not a duration")
  staffed = launch_interval(t.plates_per_day, operating_hours)
  return Cadence(
    target=t,
    operating_hours=operating_hours,
    interval_seconds=staffed,
    round_the_clock_seconds=launch_interval(t.plates_per_day, 24.0),
    slowest_step_seconds=slowest_step_seconds,
    end_to_end_seconds=end_to_end_seconds,
  )


# -- the human share of the clock ----------------------------------------------


@dataclass(frozen=True)
class Headroom:
  """How much of the admission interval a human consumes, and where the target dies.

  Note what is absent from every field here: instrument speed. The human seconds per plate
  are set by how often somebody is needed and how long they take; the interval is set by the
  target. A faster robot moves neither, so a workcell that fails this check fails it at any
  hardware budget. That is the whole reason this computation exists separately from
  `orchestrate`, which already reports WHERE a human is needed but not what it costs per plate.
  """

  interval_seconds: float
  intervention_rate: float  # interventions per plate admitted
  minutes_per_intervention: float
  human_seconds_per_plate: float
  consumed_fraction: float

  @property
  def reachable(self) -> bool:
    """False at or above 100 percent of the clock.

    Exactly 1.0 is not reachable, deliberately. A queue whose service time equals its
    interarrival time has zero slack, and any variance at all -- and instrument timings are
    bimodal, which `throughput` records for the one step this repo has actually measured --
    makes the backlog grow without bound rather than hover.
    """
    return self.consumed_fraction < 1.0

  @property
  def slack_seconds(self) -> float:
    """Seconds of the interval left after the human. Negative when the target is unreachable."""
    return self.interval_seconds - self.human_seconds_per_plate

  @property
  def operators_required(self) -> int:
    """Operators needed in parallel to hold this cadence.

    Assumes interventions on different plates can proceed simultaneously, which is false
    wherever they contend for the same instrument -- `orchestrate` already serializes those
    under the one-process-per-instrument rule. So this is a FLOOR on the headcount, not an
    estimate of it.
    """
    if self.human_seconds_per_plate <= 0:
      return 0
    return max(1, math.ceil(self.consumed_fraction))

  @property
  def ceiling_interval_seconds(self) -> Optional[float]:
    """The shortest interval one operator can sustain. None when no human is needed."""
    if self.human_seconds_per_plate <= 0:
      return None
    return self.human_seconds_per_plate

  def ceiling_plates_per_day(self, operating_hours: float = 24.0) -> Optional[float]:
    """The most plates one operator can sustain inside a window, ignoring everything else.

    A strict upper bound and nothing more: it grants the operator every second of the window
    with no breaks, no handover, and no second task, which no shift has ever looked like.
    """
    if self.human_seconds_per_plate <= 0:
      return None
    if operating_hours <= 0 or operating_hours > 24:
      raise ValueError(f"{operating_hours} operating hours is not a window")
    return (operating_hours * SECONDS_PER_HOUR) / self.human_seconds_per_plate

  def why(self) -> str:
    """The finding, including the sentence that makes it a finding rather than a ratio."""
    base = (
      f"a human is needed on {self.intervention_rate:g} of every plate for "
      f"{self.minutes_per_intervention:g} min, which is {self.human_seconds_per_plate:.1f} s of "
      f"attention per plate against a {self.interval_seconds:.1f} s admission interval: "
      f"{self.consumed_fraction * 100:.1f} percent of the clock"
    )
    if self.reachable:
      tail = (
        f". {self.slack_seconds:.1f} s of each interval is left for everything else, and "
        "everything else includes the upkeep and the recovery"
      )
    else:
      tail = (
        f". At or above 100 percent the queue grows without bound and the target is "
        f"unreachable: it needs at least {self.operators_required} operators in parallel, or "
        "fewer interventions, or a longer interval. Instrument speed appears nowhere in this "
        "arithmetic, so a faster robot does not move it in either direction"
      )
    return base + tail


def headroom(
  interval_seconds: float,
  intervention_rate: float,
  minutes_per_intervention: float,
) -> Headroom:
  """What a human intervention rate costs against a launch interval, and when it kills the target.

  All three inputs come from the caller and none is invented. An intervention rate is a thing
  a lab can count in a week without instrumenting anything, which is why this is the one
  measurement in this module worth asking for before any duration study.
  """
  if interval_seconds <= 0:
    raise ValueError(f"{interval_seconds} s is not an admission interval")
  if intervention_rate < 0:
    raise ValueError("an intervention rate cannot be negative")
  if minutes_per_intervention < 0:
    raise ValueError("an intervention cannot take negative time")
  human = intervention_rate * minutes_per_intervention * 60.0
  return Headroom(
    interval_seconds=interval_seconds,
    intervention_rate=intervention_rate,
    minutes_per_intervention=minutes_per_intervention,
    human_seconds_per_plate=human,
    consumed_fraction=human / interval_seconds,
  )


# -- the honest check ----------------------------------------------------------


class Demonstrated(str, Enum):
  """What a published work establishes about RATE, as distinct from capability.

  The line is between a run that HAPPENED and a rate that is HELD. A campaign that ran for
  seventeen days is a real and difficult result and it is not a throughput specification: it
  is one uncontrolled run, in one domain, with no replication and no baseline. SUSTAINED_RATE
  is the category a plates-per-day target actually needs support from, and no row in this
  module's table carries it. The member exists so that fact is computed from an empty
  selection rather than asserted in a comment.
  """

  NO_RATE_CLAIM = "no_rate_claim"  # the work reports no achieved per-day figure at all
  CAPABILITY = "capability"  # the system did the thing, under observation, once or a few times
  CAMPAIGN = "campaign"  # it ran continuously for days or longer, within one domain
  SUSTAINED_RATE = "sustained_rate"  # a production rate, held across domains, over time

  @property
  def establishes_a_rate(self) -> bool:
    return self is Demonstrated.SUSTAINED_RATE


# Full citations, in one place, so a row cannot drift from its reference.
REFERENCES: Dict[str, str] = {
  "a_lab": (
    "Szymanski, N. J. et al. 'An autonomous laboratory for the accelerated synthesis of "
    "inorganic materials.' Nature 624, 86-91 (2023). doi:10.1038/s41586-023-06734-w. "
    "Author Correction: Nature 650, E1 (19 Jan 2026), doi:10.1038/s41586-025-09992-y -- "
    "cite the corrected version"
  ),
  "alabos": (
    "Fei, Y. et al. 'AlabOS: a Python-based reconfigurable workflow management framework for "
    "autonomous laboratories.' Digital Discovery 3(11), 2275-2288 (2024). doi:10.1039/D4DD00129J"
  ),
  "roboculture": (
    "Angers, K. et al. 'RoboCulture enables modular robotic plate-based cell automation.' "
    "Cell Reports Physical Science 7(7), 103335 (2026). doi:10.1016/j.xcrp.2026.103335"
  ),
  "dai": (
    "Dai, T. et al. 'Autonomous mobile robots for exploratory synthetic chemistry.' "
    "Nature 635, 890-897 (2024). doi:10.1038/s41586-024-08173-7"
  ),
  "coley": (
    "Coley, C. W. et al. 'A robotic platform for flow synthesis of organic compounds informed "
    "by AI planning.' Science 365(6453), eaax1566 (2019). doi:10.1126/science.aax1566"
  ),
  "jump": (
    "Chandrasekaran, S. N. et al. 'Three million images and morphological profiles of cells "
    "treated with matched chemical and genetic perturbations.' Nature Methods 21(6), 1114-1121 "
    "(2024). doi:10.1038/s41592-024-02241-6"
  ),
  "homecage_multi": (
    "Eswaraka, J. et al. 'Enhanced health evaluation in mice using continuous home-cage "
    "monitoring and machine learning: a multicentric study.' Lab Animal 55, 275-281 (2026). "
    "doi:10.1038/s41684-026-01745-2"
  ),
  "smartkage": (
    "Ho, H. et al. 'A fully automated home cage for long-term continuous phenotyping of mouse "
    "cognition and behavior.' Cell Reports Methods 3(7), 100532 (2023). "
    "doi:10.1016/j.crmeth.2023.100532"
  ),
  "ncats": (
    "Iversen, P. W. et al. 'HTS Assay Validation.' In: Assay Guidance Manual. Bethesda (MD): "
    "Eli Lilly & Company and NCATS, 2012 (rev. 2012 Oct 1). PMID 22553862, Bookshelf NBK83783"
  ),
  "pylabrobot": (
    "Wierenga, R. P. et al. 'PyLabRobot: An open-source, hardware-agnostic interface for "
    "liquid-handling robots and accessories.' Device 1(4), 100111 (2023). "
    "doi:10.1016/j.device.2023.100111"
  ),
  "labsafety": (
    "Zhou, Y. et al. 'Benchmarking large language models on safety risks in scientific "
    "laboratories.' Nature Machine Intelligence 8, 20-31 (2026). doi:10.1038/s42256-025-01152-1"
  ),
  "iso23783": (
    "ISO 23783-1:2022, Automated liquid handling systems -- Part 1: Vocabulary and general "
    "requirements; and ISO 23783-3:2022, Part 3: Determination, specification and reporting of "
    "volumetric performance. ISO/TC 48"
  ),
  "fda_di": (
    "U.S. Food and Drug Administration, 'Data Integrity and Compliance With Drug CGMP: "
    "Questions and Answers -- Guidance for Industry,' December 2018 (Final, Level 1). "
    "Docket FDA-2018-D-3984. Contains nonbinding recommendations"
  ),
}


@dataclass(frozen=True)
class Demonstration:
  """One published system, what it actually ran, and what it does not establish.

  `does_not_establish` is required rather than optional and no row leaves it empty. A
  citation table whose caveats are optional degrades into a list of names, and a list of
  names is what makes a demonstration look like a benchmark.

  `actuates` separates systems that DO things from systems that WATCH them, and the split is
  the finding of this whole table: the only works here that operate continuously at scale
  across institutions are observational.
  """

  key: str  # indexes REFERENCES
  system: str
  domain: str
  ran_for: str  # duration in the authors' own terms, not converted
  scale: str  # what was actually processed, in the authors' own counts
  demonstrated: Demonstrated
  actuates: bool
  does_not_establish: str

  @property
  def citation(self) -> str:
    return REFERENCES[self.key]

  @property
  def establishes_a_rate(self) -> bool:
    return self.demonstrated.establishes_a_rate


DEMONSTRATIONS: Tuple[Demonstration, ...] = (
  Demonstration(
    key="a_lab",
    system="A-Lab: robotic powder prep, four box furnaces, automated XRD, active learning",
    domain="solid-state synthesis of inorganic oxide and phosphate powders",
    ran_for="17 days of continuous operation",
    scale="36 compounds realized from a set of 57 computationally nominated targets",
    demonstrated=Demonstrated.CAMPAIGN,
    actuates=True,
    does_not_establish=(
      "no per-day rate is stated and a synthesis target is not a plate. One uncontrolled run "
      "on one instrument, with no replication and no human baseline, so 36 of 57 describes "
      "that run rather than a capability. Success meant a phase judged realized by automated "
      "XRD and Rietveld refinement, not expert review -- the senior author conceded a human "
      "could refine these samples better. The 2026 Author Correction removed 'novel' from the "
      "title and reclassified four reported successes as inconclusive, and Leeman et al., "
      "PRX Energy 3, 011002 (2024) reported substantial errors in the automated XRD analysis"
    ),
  ),
  Demonstration(
    key="alabos",
    system="AlabOS: task-graph orchestration, resource reservation, sample-position tracking",
    domain="inorganic solid-state powder synthesis, one prototype laboratory",
    ran_for="approximately 1.5 years of deployment",
    scale=(
      "around 3,500 samples processed, with a stated peak of 149 samples on one day "
      "(9 February 2024)"
    ),
    demonstrated=Demonstrated.CAMPAIGN,
    actuates=True,
    does_not_establish=(
      "the only per-day figure in this table is a PEAK day, which is the opposite of a "
      "sustained cadence -- and dividing 'around 3,500' by 'approximately 1.5 years' would put "
      "a precision on both figures that neither carries, so this module does not. The 3,500 is "
      "a deployment usage statistic, not successful syntheses or discoveries. Single lab, "
      "single domain, no multi-site deployment and no head-to-head benchmark against any other "
      "workflow manager. The authors describe the scheduler as first-come-first-serve with no "
      "task-duration modeling and state that throughput optimization is future work. Autonomy "
      "is human-in-the-loop by design: the user-request module exists because error recovery "
      "and consumable replacement need operators"
    ),
  ),
  Demonstration(
    key="dai",
    system="mobile robots linking a synthesis platform, UPLC-MS, and an 80-MHz benchtop NMR",
    domain="exploratory organic and supramolecular synthesis",
    ran_for="almost four consecutive days in the diversification campaign; three days in another",
    scale="12 analogues via three autonomous synthetic steps; 18 combinations screened",
    demonstrated=Demonstrated.CAMPAIGN,
    actuates=True,
    does_not_establish=(
      "no rate is claimed. The authors' speed claim is narrowly that the algorithmic decisions "
      "are effectively instantaneous -- the data-inspection step, not synthetic throughput. The "
      "decision-maker is a tiered heuristic with human-set thresholds, not machine learning. "
      "Most relevant here: an unexpected intramolecular cyclization produced a species with the "
      "same molecular weight as the expected product, indistinguishable by UPLC or MS, and it "
      "escaped the automated decision rule entirely -- it was caught by human inspection of the "
      "NMR and confirmed by single-crystal X-ray diffraction, an off-workflow manual technique. "
      "That is an intervention with a rate, and it is the rate `headroom` asks for"
    ),
  ),
  Demonstration(
    key="roboculture",
    system="general-purpose arm with vision, force feedback, and a behavior-tree framework",
    domain="yeast (S. cerevisiae) culture in a 96-well plate",
    ran_for="a fully autonomous 15-hour experiment",
    scale="one 96-well plate, three replicate groups; 99.0 percent tip insertion over 576 attempts",
    demonstrated=Demonstrated.CAPABILITY,
    actuates=True,
    does_not_establish=(
      "the authors explicitly disclaim throughput: they position the platform as operating more "
      "like an autonomous vehicle tailored to individual or small-group use than for "
      "high-throughput screening, and do not claim to beat commercial liquid handlers. Autonomy "
      "is narrower than the headline: initial seeding was manual AND the subculture split was "
      "manually initiated as a safety precaution, so the headline decision was human-authorized. "
      "Perception is fiducial-tag dependent and the authors call the calibration fragile and "
      "time-consuming to maintain. One 15-hour run, one plate, one organism"
    ),
  ),
  Demonstration(
    key="coley",
    system="reconfigurable continuous-flow platform, robot-arm reconfigured, AI route planning",
    domain="flow synthesis of known drug and drug-like substances",
    ran_for="not established from the primary source available",
    scale="15 drug or drug-like substances",
    demonstrated=Demonstrated.NO_RATE_CLAIM,
    actuates=True,
    does_not_establish=(
      "no throughput, cost, or scale comparison against manual synthesis is claimed anywhere in "
      "the work. It is not autonomous end to end: the AI proposes routes and an expert chemist "
      "must translate each one into an executable recipe file, which the authors attribute to "
      "the literature not containing enough information to go from inspiration to execution. "
      "Fifteen successes is a demonstration set, not a success rate -- no denominator of "
      "attempted-and-failed targets is available -- so it supports no statement about "
      "reliability. Widely circulated duration figures for this platform come from press "
      "coverage rather than the paper and are deliberately not repeated here"
    ),
  ),
  Demonstration(
    key="jump",
    system="image-based morphological profiling at plate scale (CPJUMP1)",
    domain="compound, CRISPR and ORF perturbations in two cell lines, 384-well format",
    ran_for="a single experiment at a single facility",
    scale="51 physical plates yielding 107 plates of images; roughly 3 million images",
    demonstrated=Demonstrated.NO_RATE_CLAIM,
    actuates=True,
    does_not_establish=(
      "no per-day plate rate is reported and none can be recovered from the paper. The headline "
      "finding is negative: the authors conclude that identifying matches between chemical and "
      "genetic perturbations is a challenging task, so this is a benchmark resource rather than "
      "a solved capability. Single experiment at a single facility, which the authors say "
      "limits generalizability; 160 genes, 303 compounds, one concentration the authors call "
      "not ideal, two cell lines, two time points"
    ),
  ),
  Demonstration(
    key="homecage_multi",
    system="capacitance-sensing digital ventilated cages with an ML alerting model",
    domain="mouse home-cage locomotion monitoring across three institutions",
    ran_for="approximately 300 days at two sites and over 1,000 days at a third",
    scale="1,367 cages; 90,540 + 51,094 + 15,367 cage evaluations",
    demonstrated=Demonstrated.CAMPAIGN,
    actuates=False,
    does_not_establish=(
      "the largest and longest continuously-operating system in this table performs no "
      "experiment. It observes. It executes nothing, moves nothing, and decides nothing at the "
      "bench, so it establishes no throughput of any kind. The analysis is retrospective, with "
      "no prospective or interventional validation that earlier alerts improved any outcome. "
      "Alerts are not real-time -- the authors state they are not reported to caretakers until "
      "the morning. Resolution is cage-level, not animal-level; the algorithm missed 9-20 "
      "percent of verified clinical cases; and four co-authors are employed by the vendor of "
      "the sensing platform being evaluated"
    ),
  ),
  Demonstration(
    key="smartkage",
    system="automated home cage running T-maze, novel object and object-in-place tasks",
    domain="mouse cognitive and behavioral phenotyping, no food or water restriction",
    ran_for="continuous testing over approximately 4.5 months in the longest arm",
    scale="one mouse per cage; lesion groups of n=5 and n=4, AD arm of 5 knock-in mice",
    demonstrated=Demonstrated.CAMPAIGN,
    actuates=True,
    does_not_establish=(
      "the authors call their own system low throughput, in those words, and note the "
      "single-mouse design is suboptimal for stress as well. It runs one animal at a time, so "
      "months of continuous unattended operation produce one subject's data. Underpowered by "
      "the authors' own limitations section, single animal facility, no multi-site replication. "
      "The medial-entorhinal arm classified 1 of 4 correctly, so the discrimination claim holds "
      "for hippocampal lesions and barely at all for the other lesion type. The tracking "
      "training data is proprietary and cannot be released, so the pipeline is not reproducible "
      "end to end"
    ),
  ),
  Demonstration(
    key="ncats",
    system="pre-production HTS assay validation designs (plate uniformity, replicate experiment)",
    domain="biochemical and cell-based screening assays in drug discovery",
    ran_for="a 3-day plate-uniformity study",
    scale=(
      "3 plates per day in the interleaved-signal format, or 6 per day in the CRC plus "
      "uniform-signal format"
    ),
    demonstrated=Demonstrated.NO_RATE_CLAIM,
    actuates=False,
    does_not_establish=(
      "the plates-per-day figures here are a prescribed STUDY DESIGN, not an achieved rate, and "
      "quoting 3 or 6 as a demonstrated throughput would invert what the chapter is for. It is "
      "pre-production readiness guidance: the authors state the replicate-experiment study is a "
      "decision tool to establish that an assay is ready to go into production and is not a "
      "substitute for post-production monitoring. It is an industry and NIH best-practice "
      "manual, not GLP, GMP, CLIA or FDA guidance, and its Z' >= 0.4 criterion is specific to "
      "this context rather than a universal quality bar"
    ),
  ),
  Demonstration(
    key="pylabrobot",
    system="hardware-agnostic Python interface over three liquid-handler families plus readers",
    domain="liquid-handling control software",
    ran_for="not applicable; this is a software interface rather than a run",
    scale="three robot families (liquid handler/STARLet, Tecan Freedom EVO, Opentrons OT-2)",
    demonstrated=Demonstrated.NO_RATE_CLAIM,
    actuates=True,
    does_not_establish=(
      "the paper reports no throughput or timing benchmark of any kind, and no pipetting "
      "accuracy or precision data either -- any performance number attributed to it would be "
      "fabricated. Testing stops at command generation: unit tests check that user input "
      "produces consistent machine-level commands, not that the liquid arrives. Backends are "
      "not at parity, and the simulator claim is architectural -- it is designed to work with "
      "any robot for which a deck model exists, and per-robot work is still required"
    ),
  ),
)


DEMONSTRATIONS_BY_KEY: Dict[str, Demonstration] = {d.key: d for d in DEMONSTRATIONS}


NO_INTEGRATED_PRODUCTION_RATE = (
  "No cited published system establishes integrated multi-domain autonomous laboratory "
  "operation at a production rate. The longest integrated campaign in the cited record is 17 "
  "days in a single domain on inorganic powders; the only per-day figure is a peak day from a "
  "single-lab deployment whose authors call its scheduler non-optimal; and the one system that "
  "runs continuously at scale across institutions is a cage sensor that observes rather than "
  "actuates, retrospectively, with its alerts held until morning. A plates-per-day target is "
  "therefore an engineering commitment, not a demonstrated capability, and nothing in this "
  "module will return a citation that supports one"
)


@dataclass(frozen=True)
class Support:
  """Whether the published record supports a target, and what the nearest evidence actually is.

  `supported` is a property computed from the table rather than a stored False. If someone
  later adds a genuine SUSTAINED_RATE row, this flips on its own, which is the only honest way
  to write a claim that is currently negative -- a hard-coded False would stop being computed
  the moment it stopped being true.
  """

  target: Target
  refused: bool
  reason: str
  nearest: Tuple[Demonstration, ...] = ()

  def supporting(self) -> Tuple[Demonstration, ...]:
    return tuple(d for d in self.nearest if d.establishes_a_rate)

  @property
  def supported(self) -> bool:
    return bool(self.supporting())


def demonstrated_support(plates_per_day) -> Support:
  """Has anybody published a system that sustains this rate?

  Takes a `Target` or a bare number. A bare number is refused, because a number alone does not
  say whether it counts plates started, completed, QC-passed, or released, and the four differ
  by the failure and rerun rate. This matters more here than in `cadence_for`: comparing a
  target against the published record without knowing which endpoint it names would compare
  two different quantities and call the mismatch evidence.

  When the endpoint IS stated, the answer is still no. What the function returns instead is
  every nearest work with what it does not establish, so the refusal is checkable rather than
  merely asserted.
  """
  target = (
    plates_per_day
    if isinstance(plates_per_day, Target)
    else Target(plates_per_day=float(plates_per_day))
  )
  if target.ambiguous:
    return Support(
      target=target,
      refused=True,
      reason=(
        target.why_ambiguous()
        + ". Until it does, there is nothing to check the published record against, and this "
        "function returns no citations rather than the ones that would look most supportive"
      ),
      nearest=(),
    )
  return Support(
    target=target,
    refused=False,
    reason=(
      f"{NO_INTEGRATED_PRODUCTION_RATE}. The target of {target.plates_per_day:g} plates "
      f"{target.endpoint.value} per day is unsupported at any value; the {len(DEMONSTRATIONS)} "
      "works below are the nearest published evidence and each is listed with what it does not "
      "establish"
    ),
    nearest=DEMONSTRATIONS,
  )


def sustained_rate_demonstrations() -> Tuple[Demonstration, ...]:
  """Every cited work that establishes a sustained production rate. Currently none.

  Computed from the table rather than stated, so the emptiness is a result. The function
  exists so a caller can check the claim instead of taking the module docstring's word for it.
  """
  return tuple(d for d in DEMONSTRATIONS if d.establishes_a_rate)


__all__ = [
  "DEMONSTRATIONS",
  "DEMONSTRATIONS_BY_KEY",
  "NO_INTEGRATED_PRODUCTION_RATE",
  "REFERENCES",
  "SECONDS_PER_DAY",
  "SECONDS_PER_HOUR",
  "Cadence",
  "Demonstrated",
  "Demonstration",
  "Endpoint",
  "Forcing",
  "Headroom",
  "Implication",
  "Support",
  "Target",
  "cadence_for",
  "demonstrated_support",
  "headroom",
  "intervals",
  "launch_interval",
  "required_admissions",
  "sustained_rate_demonstrations",
]
