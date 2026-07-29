"""What an expert demonstrated, what the machine did, and whether those are the same thing.

`intelligence` records what a senior scientist KNOWS: judgments as prose, benchmarks as
targets. Neither of those is the transfer. A judgment is knowledge written down and a
benchmark is a number somebody asserted; the step between "the robot executes the script"
and "the robot performs the task as well as the person who taught it" is a DEMONSTRATION --
an expert performing the operation, the outcome measured, and the machine's performance
placed against it. That comparison is the actual content of automating expert work, and it
is the one thing nobody records.

A DEMONSTRATION IS DATA, NOT AUTHORITY. This is the discipline of the whole module and it
cuts against how demonstrations are normally used, which is as a specification: the expert
did it this way, so this way is correct. A scientist doing something twice is not a
specification. It is two observations with a spread, and the SPREAD is the information --
it is the only thing that separates how much of the difference between a good plate and a
bad one is the operation and how much is the day. A single demonstration establishes a
value and no tolerance at all, and a tolerance invented around it -- plus or minus ten
percent, plus or minus two sigma of a distribution nobody sampled -- would be the fabricated
number this repo refuses everywhere else. So `Envelope` refuses to state a tolerance below
MIN_DEMONSTRATIONS, and reports the refusal rather than widening quietly.

The tolerance, where there is one, is the observed range and nothing else. No multiplier, no
assumed distribution, no smoothing. The min and max of what actually happened is a fact;
mean plus k standard deviations is a fact plus a k somebody chose, and k is exactly the kind
of number that reaches a report with no author attached to it.

THREE ENTRIES IS NOT THREE MEASUREMENTS. A minimum that counts rows is not a minimum,
because one number pasted three times satisfies it while carrying the evidence of one
number. So a record has to be a measurement before it is counted: it names where it came
from, its value is a finite number, and it is not byte-identical to another record already
in the same envelope. Two identical records are one measurement recorded twice or two runs
nobody troubled to distinguish, and neither of those is two measurements. The same reasoning
refuses a range of width zero over enough runs: independent measurements of a continuous
quantity do not agree to full float precision, so that range is a transcribed number rather
than a demonstrated one, and reporting it would state the tightest envelope in the module on
the weakest evidence in it.

AN ENVELOPE IS A RANGE OVER ONE EXPERIMENT. `conditions` is the field that says which
experiment, and pooling two of them is the failure this module exists to prevent rather than
a convenience. A nanogram demonstration and a picogram demonstration in one envelope produce
a range wider than either, and wide is not the safe direction: a narrow envelope asks for
more demonstrations, a wide one hides a failure. `Envelope` therefore refuses mixed
conditions the way it refuses mixed metrics, and `_build_envelopes` keys by operation AND
conditions, so an operation demonstrated two ways has two envelopes and no single answer to
"the envelope for this operation" -- which is the honest answer rather than a gap.

ONE GOOD MACHINE RUN IS NOT PARITY, which is why `Attainment` has four values rather than
three. A machine that ran the operation once, well, has produced a number that sits inside
the expert's range; reporting that as MEETS claims the machine performs like the person, on
evidence that cannot distinguish it from luck. The result carries no more information than
not having measured, and INDISTINGUISHABLE_FROM_UNMEASURED says so in its name rather than
in a footnote nobody reads. The same value covers the mirror case, where the machine has run
plenty and the expert side is too thin to place it against: either way there are numbers on
the page and they mean nothing yet. Parity is also judged on the machine's WORST observation
rather than its mean, because a mean lets one excellent run pay for a bad one, and at the
bench the bad plate is the one that costs the sample.

BOTH SIDES OF THE COMPARISON GET THE SAME CHECKS. `Envelope` refusing to pool two metrics is
worth nothing while `attainment` will place a percent against a fraction, and the machine
side is where the flattering number enters, because it is the side a script writes rather
than the side a person writes down after measuring. So an observation whose operation,
metric, or units differ from the envelope's is refused rather than compared, and the prose
reports the observation's own units beside the observation's own value, so a mismatch cannot
be papered over in a sentence.

BENCHMARK OR ENVELOPE. `intelligence.Benchmark` and `Envelope` look like one object and are
two kinds of evidence. A benchmark is a target somebody ASSERTED -- a CV below 5 percent, a
recovery inside specification. An envelope is a target somebody DEMONSTRATED -- the range a
competent person actually produced, on this material, on this bench. As evidence that a
number is ACHIEVABLE the envelope is usually the stronger, and the reason is arithmetic
rather than rhetoric: an UNMEASURED assertion has no n. It cannot be wrong about the spread
because it never states one, and a claim that cannot be wrong is not evidence. The qualifier
carries weight, because `intelligence` records a STATUS on every benchmark and two of them
are met with a counted series behind them. So `asserted_only` resolves `BenchmarkStatus`
rather than the presence of a Benchmark object, and a met benchmark with no envelope gets
its own row state instead of being filed as a target nobody has hit. As a statement of what
the science NEEDS the benchmark is the stronger one, and no quantity of demonstrations
replaces it -- an expert can demonstrate 40 percent recovery repeatably and 40 percent can
still be too little for the assay. They answer different questions and a lab needs both.
What it must not do is let one stand in for the other, so `transfer_report` carries them
side by side and resolves the benchmark from `intelligence` and the enforced threshold from
`qc` rather than restating either target here.

THE BACKLOG NOBODY WRITES DOWN. `taught()` answers whether an operation has an expert
envelope at all, and in this repo the answer is no for every operation, because there is not
one recorded demonstration anywhere in it. That is not an omission in this module. It is the
state of the evidence, and writing it down converts it into the queue of what an SME still
has to demonstrate -- the real backlog of an automation programme, and the one nobody keeps,
because it is the only part of the plan that cannot be worked on by the people building the
automation. `demonstration_queue` ranks it the way `ledger.unlocks` ranks decoding work: by
what one sitting would free, rather than by what is convenient to schedule.

A backlog that quietly drops what it cannot schedule is the flattering version of that
queue, so an operation with no `Transferable` is not skipped. A missing spec and a
deliberate exemption look identical from inside a loop and are opposite claims: the first is
the least taught state in the protocol, the second is a step whose outcome the instrument
decides. `EXEMPT` makes the second explicit and readable, and anything in neither table
lands in `DemonstrationQueue.unspecified`, where "nobody has said what to measure" reads as
work rather than as absence.

The machine side is empty here for a reason worth stating. This lab has timed exactly one
mechanism, and that measurement lives in `throughput.DURATIONS`, which records a value and a
worst case rather than the series behind them. A summary cannot supply an n, so it cannot be
placed against an envelope, and copying its numbers into this module would be a second copy
of a fact a sibling already owns. How a lab records its measurements decides which questions
it can answer later, and that is a finding rather than a formatting complaint.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

from .intelligence import BENCHMARKS_BY_OP, Benchmark
from .qc import GATES as QC_GATES
from .qc import MEASUREMENTS, Basis, Criterion

# How many demonstrations of one operation before a tolerance may be stated at all. Three is
# a floor set by convention rather than by a power calculation, and the module reports the
# number it used instead of burying it: two points have exactly one degree of freedom, so
# the interval they imply IS the two points, and nothing in them can say whether either is
# an outlier. The same minimum applies to the machine side, because the question is whether
# two spreads overlap and a single number has no spread to compare. Raising this would be
# defensible. Having none is not.
MIN_DEMONSTRATIONS = 3


class Goal(str, Enum):
  """Which way is better for a metric, which decides what leaving the range means.

  Without this the comparison has to pick a direction, and the natural pick -- inside the
  range is good, outside is bad -- silently fails a machine that is more accurate than the
  person who taught it. The reverse error is worse: on a delivered volume, overshooting the
  expert by the same margin that would fail on the low side is not better performance, it is
  a different failure, and a one-sided comparison passes it.
  """

  HIGHER = "higher"  # more is better: recovery, occupancy, yield
  LOWER = "lower"  # less is better: CV, carryover, residual volume
  WINDOW = "window"  # a target with two sides: delivered volume against nominal

  @property
  def outside_is_always_worse(self) -> bool:
    """True when leaving the demonstrated range in either direction is a failure.

    `attainment` branches on this rather than restating the two-sided rule as an unnamed
    `else`. A fourth Goal added later then reaches an explicit refusal instead of silently
    inheriting WINDOW semantics from a fall-through while this property reports False for
    it -- two computations of one fact, disagreeing with nothing to reveal it.
    """
    return self is Goal.WINDOW


class Attainment(str, Enum):
  """How a machine's performance places against what an expert demonstrated.

  Four values because three would force the interesting case into the wrong bucket. MEETS
  and BELOW are claims about performance and both need enough observations to be made at
  all. UNMEASURED means one side of the comparison is empty. The fourth means the numbers
  exist and cannot yet distinguish the machine from a machine nobody measured, which is the
  state most demos are in and the state no demo reports itself as being in.
  """

  MEETS = "meets"  # enough machine observations, and the worst of them attains the envelope
  BELOW = "below"  # enough machine observations, and they do not attain it
  UNMEASURED = "unmeasured"  # one side has no observations at all; nothing to compare
  INDISTINGUISHABLE_FROM_UNMEASURED = "indistinguishable_from_unmeasured"  # too few to place

  @property
  def demonstrated_parity(self) -> bool:
    """True only when a machine has been SHOWN to perform as well as the person.

    The other three are not degrees of parity, they are three ways of not knowing, and a
    report that treated them as a scale would rank ignorance against evidence.
    """
    return self is Attainment.MEETS


def _measured(kind: str, record) -> None:
  """The checks a record must survive to be a measurement rather than only a row.

  Shared by both record types because they are deliberately separate evidence about
  separate agents, and the reasons a value fails to be a measurement are not separate at
  all. A check written on one side and not the other is a check the flattering number walks
  around.

  `by` is normalized rather than merely stored, because it is the only mechanism separating
  "three runs by one person" from "three runs by three people". A trailing space would
  otherwise upgrade one demonstrator's habits into the spread of the operation, and the
  caveat that fires on a single demonstrator is the one that must travel with every parity
  claim made against the envelope.
  """
  handle = record.by.strip().casefold()
  if not handle:
    raise ValueError(
      f"a {kind} of '{record.operation}' records no handle for who or what produced it; an "
      "unattributed measurement cannot be counted toward a spread across demonstrators"
    )
  object.__setattr__(record, "by", handle)
  if not record.evidence.strip():
    raise ValueError(
      f"a {kind} of '{record.operation}' by {handle} records no evidence; a value with no "
      "run id, notebook page, or dataset behind it is a number nobody can go back to, and "
      "every function in this module would compute on it and report a result"
    )
  if not math.isfinite(record.value):
    raise ValueError(
      f"a {kind} of '{record.operation}' by {handle} has value {record.value}; a run whose "
      "outcome could not be measured is not an observation of the operation, and counting "
      "it would pad the n the minimum exists to hold"
    )


@dataclass(frozen=True)
class Demonstration:
  """One expert, performing one operation once, with the outcome measured.

  `by` is a stable handle for the demonstrator rather than a name, and it is here because
  three demonstrations from one person and three from three people are not the same
  evidence. The first describes that person; only the second begins to describe the
  operation. Pooling them without recording which is which is how an envelope ends up
  encoding one individual's habits and calling it a standard.

  `conditions` is what would have to match for this demonstration to say anything about
  another run -- the material, the input amount, the labware. A demonstration at nanogram
  input is not evidence about picogram input, and the whole difficulty of low-input work is
  that the two look like the same operation.

  `evidence` is required rather than decorative. `qc.Criterion` carries a basis,
  `intelligence.Benchmark` carries evidence, `throughput.Duration` carries a basis; a value
  here with no source would be the only number in the package nobody could go back to, and
  it would still reach a MEETS.
  """

  operation: str
  metric: str
  units: str
  value: float
  by: str  # demonstrator handle, not a name
  conditions: str
  evidence: str  # run id, notebook page, dataset path: where this number came from

  def __post_init__(self) -> None:
    _measured("demonstration", self)


@dataclass(frozen=True)
class MachineObservation:
  """One machine run of an operation, measured on the same metric as the expert.

  Deliberately a separate type from `Demonstration` despite carrying the same fields. They
  are different evidence about different agents, and one container for both invites the
  arithmetic that pools them -- which would compute a range over expert and machine runs
  together and report the machine as being inside it.

  "The same metric as the expert" is enforced by `attainment`, not left to this sentence.
  """

  operation: str
  metric: str
  units: str
  value: float
  by: str  # the run card, script, or instrument that produced it
  conditions: str
  evidence: str  # run id, log, dataset path: where this number came from

  def __post_init__(self) -> None:
    _measured("machine observation", self)


def _repeats(records: Sequence) -> Tuple:
  """Records byte-identical to an earlier one in the same sequence.

  Equality is every field, evidence included, so two real runs differ by their source even
  when they land on the same value. What this catches is one row entered twice, which is
  either a data-entry error or a claim that one run happened three times, and neither is the
  independent n the minimum is counting.
  """
  seen: List = []
  repeats: List = []
  for r in records:
    if r in seen:
      repeats.append(r)
    else:
      seen.append(r)
  return tuple(repeats)


@dataclass(frozen=True)
class Envelope:
  """What "as good as the expert" means for one operation, derived from demonstrations.

  Nothing here is declared. There is no field an author can set to state a tolerance, a
  center, or a spread, because a derived value kept beside the values it derives from
  eventually disagrees with them and nothing reveals which one is wrong. Every number this
  class reports is a method over `demonstrations`, and an envelope with too few of them
  returns None and says why rather than returning a plausible interval.

  `goal`, `metric`, and `units` come from the operation's `Transferable` spec, and all three
  are checked against it HERE rather than only inside `_build_envelopes`. `goal` is the
  single field that decides whether leaving the range is a failure: relabelling a WINDOW
  operation as HIGHER turns this module's own documented over-delivery failure into
  demonstrated parity, and a class in `__all__` that accepts that label is an
  author-settable silencer whatever its docstring promises.

  Every demonstration must also share one `conditions` value. An envelope is a range over
  one experiment; a range over two is wider than either, and wide is the direction that
  hides a failure.
  """

  operation: str
  metric: str
  units: str
  goal: Goal
  demonstrations: Tuple[Demonstration, ...] = ()

  def __post_init__(self) -> None:
    spec = TRANSFERABLE_BY_OP.get(self.operation)
    if spec is None:
      raise ValueError(
        f"no Transferable declares what a demonstration of '{self.operation}' measures; an "
        "envelope over a metric nobody specified cannot be compared to anything"
      )
    if self.metric != spec.metric or self.units != spec.units or self.goal is not spec.goal:
      raise ValueError(
        f"the spec for '{self.operation}' measures {spec.metric} in {spec.units} where "
        f"{spec.goal.value} is better; this envelope declares {self.metric} in {self.units} "
        f"where {self.goal.value} is better. Which direction is better is not a property of "
        "the demonstrations, and an envelope that redefines it states a verdict, not a range"
      )
    for d in self.demonstrations:
      if d.operation != self.operation:
        raise ValueError(
          f"envelope for '{self.operation}' holds a demonstration of '{d.operation}'"
        )
      if d.metric != self.metric or d.units != self.units:
        raise ValueError(
          f"envelope for '{self.operation}' measures {self.metric} in {self.units}, but a "
          f"demonstration by {d.by} records {d.metric} in {d.units}; two metrics pooled into "
          "one range is a number about nothing"
        )
    conditions = self.conditions()
    if len(conditions) > 1:
      raise ValueError(
        f"envelope for '{self.operation}' pools demonstrations from {len(conditions)} "
        f"experiments ({'; '.join(conditions)}); an envelope is a range over one set of "
        "conditions, and pooling two widens it past the failure it was there to catch"
      )
    repeats = _repeats(self.demonstrations)
    if repeats:
      first = repeats[0]
      raise ValueError(
        f"envelope for '{self.operation}' holds {len(repeats)} demonstration(s) identical to "
        f"an earlier entry (by {first.by}, value {first.value}, evidence '{first.evidence}'); "
        f"one measurement recorded twice is not two measurements, and {MIN_DEMONSTRATIONS} "
        "of them is not a tolerance"
      )

  # -- derived, and therefore methods ----------------------------------------

  def n(self) -> int:
    return len(self.demonstrations)

  def demonstrators(self) -> Tuple[str, ...]:
    out: List[str] = []
    for d in self.demonstrations:
      if d.by not in out:
        out.append(d.by)
    return tuple(out)

  def conditions(self) -> Tuple[str, ...]:
    out: List[str] = []
    for d in self.demonstrations:
      if d.conditions not in out:
        out.append(d.conditions)
    return tuple(out)

  def center(self) -> Optional[float]:
    """The mean of what was demonstrated, or None when nothing was.

    Defined at n=1, where it is simply the one value. That is the honest reading of a single
    demonstration: a value was established, and nothing about a tolerance was.
    """
    if not self.demonstrations:
      return None
    return sum(d.value for d in self.demonstrations) / len(self.demonstrations)

  def tolerance(self) -> Optional[Tuple[float, float]]:
    """The demonstrated range, or None where the demonstrations do not support one.

    min and max of the observations, with no widening and no distribution assumed. The
    interval is then a record of what happened rather than a model of what might, and it is
    wrong only in the direction of being too narrow -- which is the safe direction, because
    a narrow envelope asks for more demonstrations and a wide one hides a failure. That
    argument holds only because the constructor refuses to pool two sets of conditions:
    pooling is precisely how min and max get wider than either experiment.

    A range of exactly zero over enough demonstrations is refused rather than reported. It
    would be the tightest envelope in the module resting on the least evidence in it, and on
    a continuous quantity it is a copied number rather than a reproduced one.
    """
    if len(self.demonstrations) < MIN_DEMONSTRATIONS:
      return None
    values = [d.value for d in self.demonstrations]
    low, high = min(values), max(values)
    if low == high:
      return None
    return (low, high)

  def spread(self) -> Optional[float]:
    band = self.tolerance()
    return None if band is None else band[1] - band[0]

  def refusal(self) -> Optional[str]:
    """Why this envelope states no tolerance, or None when it states one.

    Reported rather than silently returning an interval anyway. A refusal that nobody can
    read is indistinguishable from an answer nobody checked.
    """
    if self.tolerance() is not None:
      return None
    n = self.n()
    if n == 0:
      return (
        f"'{self.operation}' has no recorded demonstration; there is no value and no "
        "tolerance, and nothing here says what performing it well would look like"
      )
    if n >= MIN_DEMONSTRATIONS:
      return (
        f"'{self.operation}' has {n} demonstration(s) of {self.metric} and every one reads "
        f"{self.demonstrations[0].value} to full precision; independent runs of a continuous "
        "quantity do not agree exactly, so this is a transcribed number rather than a "
        "demonstrated range"
      )
    return (
      f"'{self.operation}' has {n} demonstration(s) of {self.metric}; a tolerance needs "
      f"{MIN_DEMONSTRATIONS}. The value is established and the spread is not, so no envelope "
      f"is stated. {MIN_DEMONSTRATIONS - n} more demonstration(s) would produce one"
    )

  def caveat(self) -> Optional[str]:
    """What the envelope does not cover even where it states a tolerance.

    A range from one demonstrator describes that demonstrator. It is still the best evidence
    available and it is not evidence about the operation, so the caveat travels with every
    parity claim made against it rather than living in a methods section.

    There is deliberately no mixed-conditions branch. The constructor refuses that envelope
    outright, and a caveat that can never fire would be a second statement of a rule the
    constructor already owns.
    """
    if self.tolerance() is None:
      return None
    if len(self.demonstrators()) == 1:
      return (
        f"every demonstration is by {self.demonstrators()[0]}; the range describes one "
        "person's performance, not the spread of the operation"
      )
    return None

  def describe(self) -> str:
    band = self.tolerance()
    if band is None:
      return f"no envelope for {self.operation}"
    return f"{self.metric} in {band[0]}-{band[1]} {self.units} over {self.n()} demonstrations"


@dataclass(frozen=True)
class Parity:
  """A machine's performance placed against an expert envelope, with the reason it placed there.

  `expert_n` and `machine_n` are carried because the attainment is meaningless without them
  and they are the first thing dropped when a result is summarized. MEETS over three and
  three is a finding; MEETS over three and one is a bug this module refuses to produce.

  `matched_n` is separate from `machine_n` because they answer different questions and
  collapsing them erases runs. `machine_n` counts the observations handed in; `matched_n`
  counts the ones measured under the conditions the expert demonstrated. Reporting a
  condition mismatch as machine_n=0 would make a report that discarded twenty runs
  indistinguishable from one that never had any, and the difference between those is whether
  somebody has work to re-file or work to do.
  """

  operation: str
  attainment: Attainment
  reason: str
  expert_n: int
  machine_n: int
  matched_n: int

  @property
  def demonstrated(self) -> bool:
    return self.attainment.demonstrated_parity


def attainment(
  envelope: Optional[Envelope],
  observations: Sequence[MachineObservation],
  operation: Optional[str] = None,
) -> Parity:
  """Place machine observations against an expert envelope.

  The order of the checks is the substance of the function, because every one of them is a
  path by which a comparison with too little behind it becomes a MEETS:

    an observation of another quantity      refused, not compared; raises
    the same observation entered twice      refused, not counted; raises
    no envelope, or no demonstrations       nothing to attain; UNMEASURED
    no machine observations                 nothing to place; UNMEASURED
    none under the demonstrated conditions  measured, but not of the same experiment
    envelope states no tolerance            a value with no spread cannot contain anything
    too few machine observations            a number that cannot be told from luck
    otherwise                               compare the machine's WORST run to the envelope

  The first two raise rather than returning a verdict, matching `Envelope.__post_init__`.
  They are not states of the evidence, they are the wrong evidence, and a function that
  returned UNMEASURED for them would leave a recovery figure logged in percent sitting in a
  report as a row somebody might later fill in.

  Conditions are matched by exact string equality, which is crude on purpose. The
  alternative to a blunt match is no match, and no match compares a picogram run against a
  nanogram demonstration and reports parity.
  """
  # The untaught case -- no envelope AND no observations -- is the common one, and it is
  # exactly the case where neither argument carries the operation's name. Without the
  # caller supplying it the refusal reads "no expert envelope places 'unknown'", which
  # names nothing and is useless as a queue entry.
  op = (
    envelope.operation
    if envelope is not None
    else (observations[0].operation if observations else (operation or "unknown"))
  )

  if envelope is not None:
    for o in observations:
      if (
        o.operation != envelope.operation
        or o.metric != envelope.metric
        or o.units != envelope.units
      ):
        raise ValueError(
          f"envelope for '{envelope.operation}' measures {envelope.metric} in "
          f"{envelope.units}, but a machine observation by {o.by} records {o.metric} in "
          f"{o.units} for '{o.operation}'; two metrics pooled into one comparison is a "
          "number about nothing, and the machine side is where that number enters"
        )
  repeats = _repeats(observations)
  if repeats:
    first = repeats[0]
    raise ValueError(
      f"{len(repeats)} machine observation(s) of '{op}' are identical to an earlier entry "
      f"(by {first.by}, value {first.value}, evidence '{first.evidence}'); one run counted "
      f"{MIN_DEMONSTRATIONS} times is one run, and the minimum exists to refuse it"
    )

  if envelope is None or envelope.n() == 0:
    return Parity(
      operation=op,
      attainment=Attainment.UNMEASURED,
      reason=(
        f"no expert envelope places '{op}'; there is no demonstrated range to attain, and a "
        "machine number with nothing to compare it to is not a result"
      ),
      expert_n=0 if envelope is None else envelope.n(),
      machine_n=len(observations),
      matched_n=0,
    )

  if not observations:
    return Parity(
      operation=op,
      attainment=Attainment.UNMEASURED,
      reason=(
        f"the expert side has {envelope.n()} demonstration(s) and the machine has never "
        f"been measured on '{op}'; nothing is being compared"
      ),
      expert_n=envelope.n(),
      machine_n=0,
      matched_n=0,
    )

  demonstrated_conditions = envelope.conditions()
  matching = tuple(o for o in observations if o.conditions in demonstrated_conditions)
  if not matching:
    return Parity(
      operation=op,
      attainment=Attainment.UNMEASURED,
      reason=(
        f"{len(observations)} machine observation(s) exist, none under the conditions the "
        f"expert demonstrated ({'; '.join(demonstrated_conditions)}); under those conditions "
        "the machine is unmeasured"
      ),
      expert_n=envelope.n(),
      machine_n=len(observations),
      matched_n=0,
    )

  band = envelope.tolerance()
  if band is None:
    return Parity(
      operation=op,
      attainment=Attainment.INDISTINGUISHABLE_FROM_UNMEASURED,
      reason=(
        f"the machine has {len(matching)} matching observation(s) and the expert side states "
        f"no tolerance: {envelope.refusal()}"
      ),
      expert_n=envelope.n(),
      machine_n=len(observations),
      matched_n=len(matching),
    )

  if len(matching) < MIN_DEMONSTRATIONS:
    return Parity(
      operation=op,
      attainment=Attainment.INDISTINGUISHABLE_FROM_UNMEASURED,
      reason=(
        f"{len(matching)} machine observation(s) of '{op}' against an envelope of "
        f"{envelope.n()}; {MIN_DEMONSTRATIONS} are needed before the machine can be placed. "
        "A run that landed inside the range cannot be told from one that got lucky"
      ),
      expert_n=envelope.n(),
      machine_n=len(observations),
      matched_n=len(matching),
    )

  values = [o.value for o in matching]
  low, high = min(values), max(values)
  lo, hi = band
  # Units come off the observation, not off the envelope. The guard above has already made
  # them equal; reading them from the value's own record is what keeps a future mismatch out
  # of the prose rather than hidden inside it.
  units = matching[0].units
  if envelope.goal.outside_is_always_worse:
    meets = low >= lo and high <= hi
    worst = f"runs span {low}-{high} {units} against a demonstrated {lo}-{hi}"
  elif envelope.goal is Goal.HIGHER:
    meets = low >= lo
    worst = f"worst run {low} {units} against a demonstrated floor of {lo}"
  elif envelope.goal is Goal.LOWER:
    meets = high <= hi
    worst = f"worst run {high} {units} against a demonstrated ceiling of {hi}"
  else:
    raise ValueError(
      f"'{envelope.goal}' is a Goal this comparison does not handle; a direction that falls "
      "through to a default silently inherits some other metric's semantics"
    )

  caveat = envelope.caveat()
  tail = f". Caveat: {caveat}" if caveat else ""
  if meets:
    return Parity(
      operation=op,
      attainment=Attainment.MEETS,
      reason=(
        f"{len(matching)} machine observation(s) attain the envelope from "
        f"{envelope.n()} demonstration(s): {worst}{tail}"
      ),
      expert_n=envelope.n(),
      machine_n=len(observations),
      matched_n=len(matching),
    )
  return Parity(
    operation=op,
    attainment=Attainment.BELOW,
    reason=(
      f"{len(matching)} machine observation(s) do not attain the envelope from "
      f"{envelope.n()} demonstration(s): {worst}{tail}"
    ),
    expert_n=envelope.n(),
    machine_n=len(observations),
    matched_n=len(matching),
  )


# -- what would have to be demonstrated, per operation -------------------------


@dataclass(frozen=True)
class Transferable:
  """One operation whose expertise has to transfer, and the measurement that would decide it.

  A specification of a demonstration, not a demonstration -- the same kind of object as
  `intelligence.Benchmark.how_to_measure` and `vision.VisualCheck.requires`. Writing it
  before anyone performs it is what turns "we should watch someone do this" into an
  experiment with a metric, a unit, and a direction, which is the difference between a
  backlog and a wish.

  `measurement` keys into `qc.MEASUREMENTS` wherever the quantity is one this package
  already names. `qc` owns that definition and its units; restating them here as free
  strings would be two statements of one quantity, and the two drift the first time either
  is edited. Where the key is set, `metric` and `units` are checked against the resolved
  `Measurement` and a disagreement is refused. `enforced_criteria()` then resolves the
  thresholds a gate will actually apply to it, which is the number with a value on it.

  `basis` records where the CHOICE OF METRIC came from. A metric choice is a scientific
  claim and this package treats those as attributable everywhere else -- `qc.Criterion`,
  `intelligence.Judgment`, `throughput.Duration` all carry one. The uncomfortable answer
  here is INTUITION for every entry, and recording that is what makes them arguable.

  `why_this_metric` is prose and no checker reads it. It is here because the wrong metric is
  the failure that survives every other check in this module: a demonstration measured on
  something that does not decide the outcome produces a real envelope, a real attainment,
  and a machine certified at performing the wrong thing well.
  """

  op: str
  metric: str
  units: str
  goal: Goal
  conditions: str  # what a demonstration must hold constant for it to transfer
  demonstrator: str  # the kind of expert whose performance is the standard
  why_this_metric: str
  basis: Basis  # where the choice of metric came from, not where a threshold came from
  measurement: Optional[str] = None  # key into qc.MEASUREMENTS, where qc names this quantity
  note: str = ""

  def __post_init__(self) -> None:
    if self.measurement is None:
      return
    known = MEASUREMENTS.get(self.measurement)
    if known is None:
      raise ValueError(
        f"'{self.op}' claims to measure qc measurement '{self.measurement}', which qc does "
        "not define; a key that resolves to nothing is a restatement wearing a link"
      )
    if self.units != known.units or self.metric != known.note:
      raise ValueError(
        f"'{self.op}' states {self.metric} in {self.units}; qc's '{self.measurement}' is "
        f"{known.note} in {known.units}. qc owns this quantity, and two statements of one "
        "quantity eventually disagree with nothing to reveal which is wrong"
      )

  def enforced_criteria(self) -> Tuple[Criterion, ...]:
    """The asserted thresholds a gate will apply to this metric, resolved from `qc`.

    Any envelope this module eventually produces gets judged against these, so a report
    showing the demonstrated range beside `intelligence`'s benchmark and omitting them would
    omit the only asserted number with a value on it -- the one that actually stops a run.
    """
    if self.measurement is None:
      return ()
    out: List[Criterion] = []
    for gate in QC_GATES.values():
      for c in gate.criteria:
        if c.measurement == self.measurement:
          out.append(c)
    return tuple(out)


# The operations in the reference protocols where an expert's performance is the standard
# and no protocol text captures it. Deliberately not every step: a step whose outcome is set
# by the instrument rather than by the person has nothing to transfer. That exclusion is
# written out in EXEMPT below rather than left to this tuple's absences, because an absence
# and an exemption have the same shape and make opposite claims.
TRANSFERABLE: Tuple[Transferable, ...] = (
  Transferable(
    op="start_sort",
    # Resolved from qc rather than restated. qc.MEASUREMENTS owns this quantity, and the
    # gate that will enforce a threshold on it reads the same key.
    metric=MEASUREMENTS["well_occupancy"].note,
    units=MEASUREMENTS["well_occupancy"].units,
    measurement="well_occupancy",
    goal=Goal.HIGHER,
    conditions="a known cell line at the working suspension density, 96-well plate, one cell per well",
    demonstrator="a scientist who runs the sorter routinely and adjusts the gate by eye",
    basis=Basis.INTUITION,
    why_this_metric=(
      "occupancy is what the rest of the run is spent on. Everything downstream costs a "
      "reagent set per well whether or not a cell landed in it, so the operation's value is "
      "the fraction of wells that hold one, and nothing else about the sort is worth "
      "demonstrating first"
    ),
    note=(
      "the expert contribution is the gate, which is set by looking at a scatter plot and "
      "deciding where the population ends. Two scientists set it differently and both are "
      "defensible, which is precisely why the spread across demonstrators is the quantity "
      "worth having"
    ),
  ),
  Transferable(
    op="wgs_prep_lysis",
    metric="delivered volume per well against nominal at the working volume",
    units="uL",
    goal=Goal.WINDOW,
    conditions="the working volume of this prep, the tips actually used, a full plate",
    demonstrator="a scientist pipetting the same addition by hand",
    basis=Basis.INTUITION,
    why_this_metric=(
      "at picogram input a volume error is an efficiency change rather than a rounding, and "
      "it biases the dataset instead of breaking it. Two sided because delivering more than "
      "nominal is not better -- it changes the reaction the same way, in the other direction"
    ),
    note=(
      "this is the operation where the machine most plausibly beats the person, and the "
      "envelope is what would show it rather than assert it"
    ),
  ),
  Transferable(
    op="pcr_enrichment_round1_cleanup",
    metric="fraction of input recovered through the full bead protocol",
    units="fraction",
    goal=Goal.HIGHER,
    conditions="a spike-in of known quantity, the same bead ratio, the same elution volume",
    demonstrator="a scientist who has done this cleanup enough to read a pellet",
    basis=Basis.INTUITION,
    why_this_metric=(
      "recovery is the only quantity that distinguishes a cleanup that worked from one that "
      "removed the library along with the supernatant, and both produce a plate that looks "
      "identical and runs normally through every subsequent step"
    ),
    note=(
      "the operation this repo's tacit layer already has a judgment about: a diffuse pellet "
      "means rebind. A demonstration is what turns that judgment into a number a machine can "
      "be held to"
    ),
  ),
  Transferable(
    op="library_pool",
    metric="coefficient of variation of per-well representation in the pool",
    units="percent",
    goal=Goal.LOWER,
    conditions="the same number of wells, normalized from the same quantification method",
    demonstrator="a scientist normalizing and pooling by hand from a quant plate",
    basis=Basis.INTUITION,
    why_this_metric=(
      "pooling is where a plate stops being 96 samples and becomes one tube. Uneven "
      "representation is not recoverable afterward at any read depth, and it is invisible "
      "until the run is already sequenced"
    ),
  ),
  Transferable(
    op="pcr_enrichment_round1",
    metric="volume retained per well through the thermal hold",
    units="fraction of starting volume",
    goal=Goal.HIGHER,
    conditions="the same seal, the same block, the same program, door closed",
    demonstrator="a scientist sealing and loading the plate",
    basis=Basis.INTUITION,
    why_this_metric=(
      "the thermal program belongs to the instrument; what a person contributes at this step "
      "is the seal, and evaporation is what a bad one costs. Measuring block uniformity here "
      "would measure the machine, which is a different question and already a benchmark"
    ),
    note=(
      "this repo's own registry records that the choreography never closes the door around "
      "the thermal leg, so a demonstration and a machine run today are not the same "
      "configuration and `conditions` would not match"
    ),
  ),
  Transferable(
    op="run_program",
    metric="delivered volume across the dilution series against nominal",
    units="uL",
    goal=Goal.WINDOW,
    conditions="the same dilution factor, the same plate, the same tip type",
    demonstrator="a scientist performing the serial dilution by hand",
    basis=Basis.INTUITION,
    why_this_metric=(
      "a serial dilution compounds its own error: a systematic offset at the first transfer "
      "is present in every subsequent one, so the metric has to be the delivered volume "
      "rather than the final concentration, which hides the compounding"
    ),
  ),
)


TRANSFERABLE_BY_OP: Dict[str, Transferable] = {t.op: t for t in TRANSFERABLE}


# Operations a protocol runs where nothing transfers from a person, with the reason why.
# This table exists so that "no Transferable" stops being one state covering two claims.
#
# The entries are deliberately narrow, because a table that exempts an operation is a table
# that removes it from a backlog, and a generous one would be the author-settable field that
# silences a report. Writing a parameter, issuing a start, reading a status, and checking a
# control link are operations whose outcome the instrument decides; a person does not perform
# them better. Anything a person does with their hands -- loading material, priming fluidics
# -- is NOT here, because the honest answer for those is that nobody has yet said what to
# measure, and that answer belongs in the queue.
EXEMPT: Dict[str, str] = {
  "discover_usb": "a control-link check; it reports whether the path enumerates, and nobody enumerates it better",
  "probe_http": "a control-link check against the instrument's API; the answer is the instrument's",
  "probe_tcp": "a control-link check against the instrument's socket; the answer is the instrument's",
  "load_protocol": "transferring a file to the instrument; the file's contents are the expert work, not the transfer",
  "upload_program": "transferring a file to the instrument; the file's contents are the expert work, not the transfer",
  "upload_manifest": "transferring a file to the sequencer; the manifest's contents are the expert work, not the transfer",
  "select_program": "naming a stored program; the choice is made upstream and this step is a write",
  "set_deposition": "writing a dispense parameter; the value is the expert decision and it is made before this step",
  "set_run_parameters": "writing run parameters to the sequencer; the values are decided upstream",
  "set_temperature": "writing a setpoint; holding it is the instrument's job and its uniformity is a benchmark",
  "set_injection": "writing injection parameters; the method is the expert work and it is written before this step",
  "start_run": "issuing a start; what follows is the instrument's run, on parameters already written",
  "start_method": "issuing a start; what follows is the instrument's method, on a setpoint already written",
  "wait_complete": "waiting for the instrument to report done; there is no performance here to measure",
  "get_status": "reading state off the instrument; the number is the instrument's",
  "watch_run_folder": "reading state off a folder the sequencer writes; the number is the sequencer's",
  "read_absorbance": "the instrument's own measurement; whether it can be trusted is a benchmark in `intelligence`, not a demonstration",
}

_BOTH = sorted(set(EXEMPT) & set(TRANSFERABLE_BY_OP))
if _BOTH:
  raise ValueError(
    f"{_BOTH} are declared both transferable and exempt; an operation cannot both need a "
    "demonstration and have nothing to demonstrate"
  )


# Every expert demonstration recorded in this repo. There are none.
#
# This is the finding, not a placeholder. Six instruments have been reverse-engineered, two
# protocols written out step by step, gates specified, failure modes enumerated -- and not
# one person has been measured performing any of it. Filling this tuple with a plausible
# series would make every function below return numbers, and every one of those numbers
# would be invented, which is the exact failure this module was written to refuse. The empty
# state is what makes `demonstration_queue` say something true.
DEMONSTRATIONS: Tuple[Demonstration, ...] = ()


# Machine observations of the same metrics. Also none, and for a more interesting reason:
# the one mechanism this lab has timed is recorded in `throughput.DURATIONS` as a value and
# a worst case, which is a summary rather than a series. A summary has no n, so it cannot be
# placed against an envelope at all. Restating those seconds here would give this module a
# second copy of a fact `throughput` owns, and two copies of one number eventually disagree
# invisibly.
MACHINE_OBSERVATIONS: Tuple[MachineObservation, ...] = ()


def _build_envelopes() -> Dict[Tuple[str, str], Envelope]:
  """One envelope per (operation, conditions).

  Keyed on both because an envelope is a range over one experiment. Grouping on the
  operation alone would put a nanogram demonstration and a picogram demonstration into one
  range -- the comparison `attainment` refuses on the machine side, handed to it on the
  expert side already pooled and no longer visible as two experiments.
  """
  by_key: Dict[Tuple[str, str], List[Demonstration]] = {}
  for d in DEMONSTRATIONS:
    by_key.setdefault((d.operation, d.conditions), []).append(d)
  out: Dict[Tuple[str, str], Envelope] = {}
  for (op, conditions), demos in by_key.items():
    spec = TRANSFERABLE_BY_OP.get(op)
    if spec is None:
      raise ValueError(
        f"a demonstration of '{op}' is recorded, but no Transferable declares what it "
        "measures; a demonstration whose metric nobody specified cannot be compared to "
        "anything"
      )
    out[(op, conditions)] = Envelope(
      operation=op,
      metric=spec.metric,
      units=spec.units,
      goal=spec.goal,
      demonstrations=tuple(demos),
    )
  return out


ENVELOPES: Dict[Tuple[str, str], Envelope] = _build_envelopes()


def envelopes_for(operation: str) -> Tuple[Envelope, ...]:
  """Every envelope recorded for an operation, one per set of conditions."""
  return tuple(env for (op, _conditions), env in ENVELOPES.items() if op == operation)


def envelope_for(operation: str, conditions: Optional[str] = None) -> Optional[Envelope]:
  """The expert envelope for an operation, or None where nobody has demonstrated it.

  With `conditions` unset this answers only where the operation has been demonstrated under
  exactly one set of them. Two sets are two experiments, and "the envelope for this
  operation" is then a question with no answer rather than a choice this function should
  quietly make on the caller's behalf. `taught()` says which of the two it is in words.
  """
  if conditions is not None:
    return ENVELOPES.get((operation, conditions))
  found = envelopes_for(operation)
  return found[0] if len(found) == 1 else None


def observations_for(operation: str) -> Tuple[MachineObservation, ...]:
  return tuple(o for o in MACHINE_OBSERVATIONS if o.operation == operation)


def demonstrations_still_needed(operation: str) -> int:
  """How many more expert demonstrations before this operation has an envelope.

  Never zero while `taught()` reports untaught. The two get read side by side, and a backlog
  saying nothing is outstanding beside a verdict saying nothing is established is a
  disagreement no reader can resolve.
  """
  best = 0
  for env in envelopes_for(operation):
    if env.tolerance() is not None:
      return 0
    best = max(best, env.n())
  return max(1, MIN_DEMONSTRATIONS - best)


def taught(operation: str) -> Tuple[bool, str]:
  """Does an expert envelope exist for this operation at all?

  A missing demonstration is not a pass, in the same way a missing benchmark is not trust
  and a missing measurement is not a met criterion. An operation nobody has demonstrated is
  untaught, and an operation demonstrated once is still untaught: something was shown, and
  what was shown carries no tolerance, so there is nothing for a machine to be held to.

  An exempt operation is untaught too. Exemption says no demonstration is coming, not that
  one has happened, and reporting it as taught would be the author-settable field that
  quiets a report.
  """
  env = envelope_for(operation)
  spec = TRANSFERABLE_BY_OP.get(operation)
  if env is None:
    several = envelopes_for(operation)
    if len(several) > 1:
      return False, (
        f"'{operation}' has been demonstrated under {len(several)} different sets of "
        "conditions; each is its own envelope and none of them is the envelope for the "
        "operation, so there is no single range to hold a machine to"
      )
    if operation in EXEMPT:
      return False, (
        f"'{operation}' is exempt from demonstration: {EXEMPT[operation]}. Nothing is being "
        "claimed about an expert's performance of it, and nothing will be"
      )
    if spec is None:
      return False, (
        f"no expert demonstration of '{operation}' is recorded and none is specified; "
        "nothing here says what 'as good as the expert' would mean for it"
      )
    return False, (
      f"'{operation}' has a specified demonstration ({spec.metric}) and zero recorded; an "
      f"SME has to perform it {MIN_DEMONSTRATIONS} times before there is an envelope"
    )
  if env.tolerance() is None:
    return False, env.refusal() or "no tolerance"
  return True, (
    f"{env.n()} demonstration(s) from {len(env.demonstrators())} demonstrator(s): "
    f"{env.describe()}"
  )


class _Counted:
  """A result that reports how many things it examined, not only what it found.

  An empty list is the same object whether nothing was checked or everything passed, and no
  reader can tell those apart -- which is how a report over zero operations reads as a lab
  that has finished teaching its machines. These results behave like the sequence they
  replace, so a caller that only wanted the rows keeps working, and they carry the count for
  the caller that has to tell a refusal from a clean bill.
  """

  def _rows(self) -> Tuple:
    raise NotImplementedError

  def __bool__(self) -> bool:
    return bool(self._rows())

  def __len__(self) -> int:
    return len(self._rows())

  def __iter__(self):
    return iter(self._rows())

  def __getitem__(self, index):
    return self._rows()[index]


@dataclass(frozen=True)
class UntaughtOperations(_Counted):
  """Every operation of one protocol with no expert envelope, and how many were examined."""

  rows: Tuple[Tuple[str, str], ...]
  operations_considered: int

  def _rows(self) -> Tuple:
    return self.rows

  def refusal(self) -> Optional[str]:
    """Why this result says nothing, or None where it says something."""
    if self.operations_considered:
      return None
    return (
      "no operation was examined; this protocol declares no steps, so an empty result means "
      "nothing was checked rather than nothing is untaught"
    )


def untaught_operations(protocol) -> UntaughtOperations:
  """(op, reason) for every distinct operation in a protocol with no expert envelope.

  Deliberately overlaps `intelligence.untrusted_ops` and answers a different question. That
  one asks whether the machine has earned the right to run unattended; this one asks whether
  anybody has established what running it well looks like. An operation can fail both, and
  the work that fixes them is done by different people -- one is bench time on the
  instrument, the other is bench time by the scientist, and the second cannot be bought.
  """
  out: List[Tuple[str, str]] = []
  seen: List[str] = []
  for step in protocol.steps:
    if step.op in seen:
      continue
    seen.append(step.op)
    ok, why = taught(step.op)
    if not ok:
      out.append((step.op, why))
  return UntaughtOperations(rows=tuple(out), operations_considered=len(seen))


# -- the transfer report -------------------------------------------------------


@dataclass(frozen=True)
class TransferRow:
  """One operation: what the expert established, what the machine did, and whether it attains.

  `benchmarks` is resolved from `intelligence` and `criteria` from `qc` rather than either
  being restated, so this report cannot disagree with those layers about what was asserted.
  The row carries all three because the whole point is that they are different evidence:
  side by side, an operation with an unmet benchmark and no envelope is visibly a target
  nobody has shown is reachable, and an operation with a qc criterion and no envelope is a
  threshold a gate will enforce against a range that does not exist.
  """

  operation: str
  envelope: Optional[Envelope]
  observations: Tuple[MachineObservation, ...]
  parity: Parity
  benchmarks: Tuple[Benchmark, ...]
  criteria: Tuple[Criterion, ...]
  specified: bool  # a Transferable declares what a demonstration would measure

  @property
  def has_expert_envelope(self) -> bool:
    return self.envelope is not None and self.envelope.tolerance() is not None

  @property
  def unmet_benchmarks(self) -> Tuple[Benchmark, ...]:
    """Benchmarks `intelligence` has not recorded as met. Resolved there, not recomputed."""
    return tuple(b for b in self.benchmarks if not b.status.trusted)

  @property
  def met_benchmarks(self) -> Tuple[Benchmark, ...]:
    return tuple(b for b in self.benchmarks if b.status.trusted)

  @property
  def asserted_only(self) -> bool:
    """A target somebody asserted, nobody has met, and nobody has demonstrated is reachable.

    The status is the whole point and it is why `intelligence.BenchmarkStatus` exists. A
    benchmark that was MEASURED and PASSED, with a counted series behind it, is not a target
    nobody has hit, and filing it here would state the opposite of the evidence.
    """
    return bool(self.unmet_benchmarks or self.criteria) and not self.has_expert_envelope

  @property
  def met_without_envelope(self) -> bool:
    """Every asserted target met, and no expert range to place the machine in.

    Its own state rather than a shade of `asserted_only`: something was measured and it
    passed, and what is missing is the demonstration that would say whether the target was
    the right one.
    """
    return (
      bool(self.met_benchmarks)
      and not self.unmet_benchmarks
      and not self.has_expert_envelope
    )


@dataclass
class TransferReport:
  """Every operation asked the transfer question at once."""

  rows: List[TransferRow]

  def untaught(self) -> List[TransferRow]:
    return [r for r in self.rows if not r.has_expert_envelope]

  def attained(self) -> List[TransferRow]:
    return [r for r in self.rows if r.parity.demonstrated]

  def below(self) -> List[TransferRow]:
    """Operations the machine performs WORSE than the person, on enough runs to say so.

    The one verdict in this module that is a finding against the machine, and it had no
    accessor and no count. A bucket nobody can read out is a bucket that never fires.
    """
    return [r for r in self.rows if r.parity.attainment is Attainment.BELOW]

  def unmeasured(self) -> List[TransferRow]:
    return [r for r in self.rows if r.parity.attainment is Attainment.UNMEASURED]

  def asserted_only(self) -> List[TransferRow]:
    """Operations with an unmet assertion and no envelope.

    The most common state in a real programme and the one that reads as progress: a number
    exists, it is written down, it has a unit, and nobody has shown a person can hit it.
    """
    return [r for r in self.rows if r.asserted_only]

  def met_without_envelope(self) -> List[TransferRow]:
    return [r for r in self.rows if r.met_without_envelope]

  def unplaceable(self) -> List[TransferRow]:
    """Operations where numbers exist on both sides and still say nothing."""
    return [
      r
      for r in self.rows
      if r.parity.attainment is Attainment.INDISTINGUISHABLE_FROM_UNMEASURED
    ]

  def discarded_observations(self) -> int:
    """Machine runs that exist and sit under conditions no expert demonstrated.

    Carried because a row whose runs were all discarded reports UNMEASURED, which is the
    same word a row with no runs at all gets. The count is what separates them, and
    `conditions` is free text on both sides, so relabelling one string is otherwise enough
    to make a BELOW verdict disappear without trace.
    """
    return sum(r.parity.machine_n - r.parity.matched_n for r in self.rows)

  def transfers(self) -> bool:
    """True only if every operation in this report has an envelope the machine attains.

    The `bool(self.rows)` guard is the point of the method. An empty report satisfies `all()`
    vacuously, and a transfer report over zero operations is not a lab that has finished
    teaching its machines -- it is a report nobody gave any operations to.
    """
    return bool(self.rows) and all(r.parity.demonstrated for r in self.rows)

  def refusal(self) -> Optional[str]:
    """Why this report says nothing, or None where it says something."""
    if self.rows:
      return None
    return (
      "no operation was examined; every count here is a zero about no lab, and an empty "
      "report is not a lab with nothing left to teach"
    )

  def counts(self) -> Dict[str, int]:
    """One key per attainment, so the four verdict buckets sum to `operations`.

    Without `below` and `unmeasured` the row saying the machine performs worse than the
    person was invisible in every number this report produced. A set of buckets that does
    not sum is a set of buckets with somewhere for a verdict to go missing.
    """
    return {
      "operations": len(self.rows),
      "specified": sum(1 for r in self.rows if r.specified),
      "with_envelope": sum(1 for r in self.rows if r.has_expert_envelope),
      "attained": len(self.attained()),
      "below": len(self.below()),
      "unmeasured": len(self.unmeasured()),
      "unplaceable": len(self.unplaceable()),
      "asserted_only": len(self.asserted_only()),
      "met_without_envelope": len(self.met_without_envelope()),
      "discarded_observations": self.discarded_observations(),
    }


def transfer_report(operations: Sequence[str]) -> TransferReport:
  """For each operation: is there an envelope, is there machine performance, does it attain?

  Duplicate operations collapse, keeping the given order. Everything on a row is resolved
  from the layer that owns it -- envelopes from the demonstrations, benchmarks from
  `intelligence`, enforced thresholds from `qc` -- so a row cannot state a target this
  package states differently elsewhere.
  """
  rows: List[TransferRow] = []
  seen = set()
  for op in operations:
    if op in seen:
      continue
    seen.add(op)
    obs = observations_for(op)
    env = envelope_for(op)
    if env is None:
      # Several sets of conditions: place the machine against the envelope for the
      # conditions it was actually run under, and against nothing where its runs span more
      # than one. Picking one for the caller is what reports a picogram run as parity.
      conditions = {o.conditions for o in obs}
      if len(conditions) == 1:
        env = envelope_for(op, conditions=conditions.pop())
    spec = TRANSFERABLE_BY_OP.get(op)
    rows.append(
      TransferRow(
        operation=op,
        envelope=env,
        observations=obs,
        parity=attainment(env, obs, operation=op),
        benchmarks=tuple(BENCHMARKS_BY_OP.get(op, ())),
        criteria=() if spec is None else spec.enforced_criteria(),
        specified=spec is not None,
      )
    )
  return TransferReport(rows=rows)


# -- what an expert should demonstrate next ------------------------------------


@dataclass(frozen=True)
class NextDemonstration:
  """One entry in the SME queue: sit at this instrument, demonstrate these operations."""

  instrument: str
  operations: Tuple[str, ...]
  steps_blocked: int

  @property
  def demonstrations_needed(self) -> int:
    """Derived from the operations rather than stored beside them.

    A stored count is a field an author can set to disagree with the list it counts, and
    nothing in the row would reveal which of the two was wrong.
    """
    return sum(demonstrations_still_needed(op) for op in self.operations)

  @property
  def cost(self) -> int:
    """Demonstrations to perform. A crude proxy for the expert's time, and an honest one:
    each is one full run of the operation on real material, with the outcome measured."""
    return self.demonstrations_needed


@dataclass(frozen=True)
class UnspecifiedOperation:
  """An operation a protocol runs that neither TRANSFERABLE nor EXEMPT accounts for.

  Not a queue entry, because it cannot be scheduled: a demonstration needs a metric, a unit,
  and a direction, and none of those exists yet. The work it names is deciding what to
  measure, which is an afternoon at a desk rather than an afternoon at the bench with real
  material, and keeping the two in separate buckets is what stops them being ranked against
  each other. What it is not is absent.
  """

  instrument: str
  operation: str

  @property
  def demonstrations_needed(self) -> int:
    return demonstrations_still_needed(self.operation)


@dataclass(frozen=True)
class DemonstrationQueue(_Counted):
  """The SME queue, plus what it could not queue and why.

  `entries` on its own is a list that reads identically for "nothing to rank", "nothing was
  handed to me", and "everything is taught". `operations_considered` separates the second
  from the other two, and `unspecified` stops the third being reached by dropping work.
  """

  entries: Tuple[NextDemonstration, ...]
  unspecified: Tuple[UnspecifiedOperation, ...]
  exempt: Tuple[str, ...]
  operations_considered: int

  def _rows(self) -> Tuple:
    return self.entries

  def refusal(self) -> Optional[str]:
    """Why this queue says nothing, or None where it says something."""
    if self.operations_considered:
      return None
    return (
      "no operation was examined; nothing was handed to this queue, and an empty queue over "
      "no protocols is not a lab that has finished teaching its machines"
    )

  def cost(self) -> int:
    """Demonstrations across the whole queue, including work nobody has specified yet."""
    return sum(e.cost for e in self.entries) + sum(
      u.demonstrations_needed for u in self.unspecified
    )


def demonstration_queue(protocols: Sequence) -> DemonstrationQueue:
  """The SME queue, ranked by how many untaught operations one sitting would settle.

  Grouped by INSTRUMENT for the same reason `ledger.unlocks` is, and the reason is not the
  same strength of constraint, which is worth being exact about. The ledger's grouping is
  forced by code: the coverage gate refuses an armed run while any sibling command is
  undecoded, so a single decode unblocks exactly zero steps. This grouping is forced by
  physics and scheduling instead -- a demonstration needs the expert, the instrument, the
  labware, and real material in one place at one time, so the unit of progress is a sitting
  rather than an operation. Ranking individual operations would produce a queue whose top
  three entries are three separate afternoons of the same person's time.

  Scoped to the operations the given protocols actually contain, and the ranking is computed
  from them: hand it a different set of protocols and the order changes, because a station
  carrying operations in several flows is where a scientist's afternoon buys the most.

  An operation with no `Transferable` is not skipped. It goes to `unspecified` unless EXEMPT
  accounts for it, because "nobody wrote a spec" and "nothing transfers here" are opposite
  claims that a `continue` renders identical, and the first is the least taught state in the
  protocol.
  """
  ops_by_instrument: Dict[str, List[str]] = {}
  steps: Dict[str, int] = {}
  unspecified: List[UnspecifiedOperation] = []
  exempt: List[str] = []
  considered: List[str] = []

  for protocol in protocols:
    for step in protocol.steps:
      if step.op not in considered:
        considered.append(step.op)
      if step.op in EXEMPT:
        if step.op not in exempt:
          exempt.append(step.op)
        continue
      ok, _why = taught(step.op)
      if ok:
        continue
      if step.op not in TRANSFERABLE_BY_OP:
        # Keyed by (instrument, op) rather than op alone, because this is a queue of
        # sittings: the same unspecified operation at two stations is two of them.
        entry = UnspecifiedOperation(instrument=step.instrument, operation=step.op)
        if entry not in unspecified:
          unspecified.append(entry)
        continue
      ops = ops_by_instrument.setdefault(step.instrument, [])
      if step.op not in ops:
        ops.append(step.op)
      steps[step.instrument] = steps.get(step.instrument, 0) + 1

  entries = [
    NextDemonstration(
      instrument=key,
      operations=tuple(ops),
      steps_blocked=steps.get(key, 0),
    )
    for key, ops in ops_by_instrument.items()
  ]
  entries.sort(key=lambda q: (-len(q.operations), -q.steps_blocked, q.cost, q.instrument))
  return DemonstrationQueue(
    entries=tuple(entries),
    unspecified=tuple(unspecified),
    exempt=tuple(exempt),
    operations_considered=len(considered),
  )


def teaching_summary() -> Dict[str, int]:
  """How much of the expert performance behind these protocols has been recorded.

  Counted over this module's own tables. What a given protocol contains that neither table
  accounts for is protocol-scoped and lives on `DemonstrationQueue.unspecified`, because a
  summary reaching for a global set of protocols would be answering about a lab nobody named
  in the call.
  """
  return {
    "operations_specified": len(TRANSFERABLE),
    "operations_exempt": len(EXEMPT),
    "demonstrations_recorded": len(DEMONSTRATIONS),
    "operations_with_envelope": sum(
      1 for op in TRANSFERABLE_BY_OP if taught(op)[0]
    ),
    "machine_observations_recorded": len(MACHINE_OBSERVATIONS),
    "minimum_demonstrations": MIN_DEMONSTRATIONS,
  }


__all__ = [
  "DEMONSTRATIONS",
  "ENVELOPES",
  "EXEMPT",
  "MACHINE_OBSERVATIONS",
  "MIN_DEMONSTRATIONS",
  "TRANSFERABLE",
  "TRANSFERABLE_BY_OP",
  "Attainment",
  "Demonstration",
  "DemonstrationQueue",
  "Envelope",
  "Goal",
  "MachineObservation",
  "NextDemonstration",
  "Parity",
  "Transferable",
  "TransferReport",
  "TransferRow",
  "UnspecifiedOperation",
  "UntaughtOperations",
  "attainment",
  "demonstration_queue",
  "demonstrations_still_needed",
  "envelope_for",
  "envelopes_for",
  "observations_for",
  "taught",
  "teaching_summary",
  "transfer_report",
  "untaught_operations",
]
