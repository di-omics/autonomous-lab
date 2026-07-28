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

BENCHMARK OR ENVELOPE. `intelligence.Benchmark` and `Envelope` look like one object and are
two kinds of evidence. A benchmark is a target somebody ASSERTED -- a CV below 5 percent, a
recovery inside specification. An envelope is a target somebody DEMONSTRATED -- the range a
competent person actually produced, on this material, on this bench. As evidence that a
number is ACHIEVABLE the envelope is strictly stronger, and the reason is arithmetic rather
than rhetoric: an assertion has no n. It cannot be wrong about the spread because it never
states one, and a claim that cannot be wrong is not evidence. As a statement of what the
science NEEDS the benchmark is the stronger one, and no quantity of demonstrations replaces
it -- an expert can demonstrate 40 percent recovery repeatably and 40 percent can still be
too little for the assay. They answer different questions and a lab needs both. What it must
not do is let one stand in for the other, so `transfer_report` carries them side by side and
resolves the benchmark from `intelligence` rather than restating its target here.

THE BACKLOG NOBODY WRITES DOWN. `taught()` answers whether an operation has an expert
envelope at all, and in this repo the answer is no for every operation, because there is not
one recorded demonstration anywhere in it. That is not an omission in this module. It is the
state of the evidence, and writing it down converts it into the queue of what an SME still
has to demonstrate -- the real backlog of an automation programme, and the one nobody keeps,
because it is the only part of the plan that cannot be worked on by the people building the
automation. `demonstration_queue` ranks it the way `ledger.unlocks` ranks decoding work: by
what one sitting would free, rather than by what is convenient to schedule.

The machine side is empty here for a reason worth stating. This lab has timed exactly one
mechanism, and that measurement lives in `throughput.DURATIONS`, which records a value and a
worst case rather than the series behind them. A summary cannot supply an n, so it cannot be
placed against an envelope, and copying its numbers into this module would be a second copy
of a fact a sibling already owns. How a lab records its measurements decides which questions
it can answer later, and that is a finding rather than a formatting complaint.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

from .intelligence import BENCHMARKS_BY_OP, Benchmark

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
    """True when leaving the demonstrated range in either direction is a failure."""
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
  """

  operation: str
  metric: str
  units: str
  value: float
  by: str  # demonstrator handle, not a name
  conditions: str
  evidence: str = ""


@dataclass(frozen=True)
class MachineObservation:
  """One machine run of an operation, measured on the same metric as the expert.

  Deliberately a separate type from `Demonstration` despite carrying the same fields. They
  are different evidence about different agents, and one container for both invites the
  arithmetic that pools them -- which would compute a range over expert and machine runs
  together and report the machine as being inside it.
  """

  operation: str
  metric: str
  units: str
  value: float
  by: str  # the run card, script, or instrument that produced it
  conditions: str
  evidence: str = ""


@dataclass(frozen=True)
class Envelope:
  """What "as good as the expert" means for one operation, derived from demonstrations.

  Nothing here is declared. There is no field an author can set to state a tolerance, a
  center, or a spread, because a derived value kept beside the values it derives from
  eventually disagrees with them and nothing reveals which one is wrong. Every number this
  class reports is a method over `demonstrations`, and an envelope with too few of them
  returns None and says why rather than returning a plausible interval.

  `goal` and the metric come from the operation's `Transferable` spec, not from the
  demonstrations, so a demonstration cannot redefine what better means by being recorded.
  """

  operation: str
  metric: str
  units: str
  goal: Goal
  demonstrations: Tuple[Demonstration, ...] = ()

  def __post_init__(self) -> None:
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
    """The demonstrated range, or None when there are too few demonstrations to state one.

    min and max of the observations, with no widening and no distribution assumed. The
    interval is then a record of what happened rather than a model of what might, and it is
    wrong only in the direction of being too narrow -- which is the safe direction, because
    a narrow envelope asks for more demonstrations and a wide one hides a failure.
    """
    if len(self.demonstrations) < MIN_DEMONSTRATIONS:
      return None
    values = [d.value for d in self.demonstrations]
    return (min(values), max(values))

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
  """

  operation: str
  attainment: Attainment
  reason: str
  expert_n: int
  machine_n: int

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

    no envelope, or no demonstrations       nothing to attain; UNMEASURED
    no machine observations                 nothing to place; UNMEASURED
    none under the demonstrated conditions  measured, but not of the same experiment
    envelope states no tolerance            a value with no spread cannot contain anything
    too few machine observations            a number that cannot be told from luck
    otherwise                               compare the machine's WORST run to the envelope

  Conditions are matched by exact string equality, which is crude on purpose. The
  alternative to a blunt match is no match, and no match compares a picogram run against a
  nanogram demonstration and reports parity.
  """
  # The untaught case -- no envelope AND no observations -- is the common one, and it is
  # exactly the case where neither argument carries the operation's name. Without the
  # caller supplying it the refusal reads "no expert has demonstrated 'unknown'", which
  # names nothing and is useless as a queue entry.
  op = (
    envelope.operation
    if envelope is not None
    else (observations[0].operation if observations else (operation or "unknown"))
  )

  if envelope is None or envelope.n() == 0:
    return Parity(
      operation=op,
      attainment=Attainment.UNMEASURED,
      reason=(
        f"no expert has demonstrated '{op}'; there is no envelope to place a machine "
        "against, and a machine number with nothing to compare it to is not a result"
      ),
      expert_n=0 if envelope is None else envelope.n(),
      machine_n=len(observations),
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
      machine_n=0,
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
      machine_n=len(matching),
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
      machine_n=len(matching),
    )

  values = [o.value for o in matching]
  low, high = min(values), max(values)
  lo, hi = band
  if envelope.goal is Goal.HIGHER:
    meets = low >= lo
    worst = f"worst run {low} {envelope.units} against a demonstrated floor of {lo}"
  elif envelope.goal is Goal.LOWER:
    meets = high <= hi
    worst = f"worst run {high} {envelope.units} against a demonstrated ceiling of {hi}"
  else:
    meets = low >= lo and high <= hi
    worst = f"runs span {low}-{high} {envelope.units} against a demonstrated {lo}-{hi}"

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
      machine_n=len(matching),
    )
  return Parity(
    operation=op,
    attainment=Attainment.BELOW,
    reason=(
      f"{len(matching)} machine observation(s) do not attain the envelope from "
      f"{envelope.n()} demonstration(s): {worst}{tail}"
    ),
    expert_n=envelope.n(),
    machine_n=len(matching),
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
  note: str = ""


# The operations in the reference protocols where an expert's performance is the standard
# and no protocol text captures it. Deliberately not every step: a step whose outcome is set
# by the instrument rather than by the person -- a thermal hold, a run-folder read -- has
# nothing to transfer, and listing it would inflate the backlog with work no demonstration
# would settle.
TRANSFERABLE: Tuple[Transferable, ...] = (
  Transferable(
    op="start_sort",
    metric="fraction of target wells containing exactly one cell",
    units="fraction",
    goal=Goal.HIGHER,
    conditions="a known cell line at the working suspension density, 96-well plate, one cell per well",
    demonstrator="a scientist who runs the sorter routinely and adjusts the gate by eye",
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
    why_this_metric=(
      "a serial dilution compounds its own error: a systematic offset at the first transfer "
      "is present in every subsequent one, so the metric has to be the delivered volume "
      "rather than the final concentration, which hides the compounding"
    ),
  ),
)


TRANSFERABLE_BY_OP: Dict[str, Transferable] = {t.op: t for t in TRANSFERABLE}


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


def _build_envelopes() -> Dict[str, Envelope]:
  by_op: Dict[str, List[Demonstration]] = {}
  for d in DEMONSTRATIONS:
    by_op.setdefault(d.operation, []).append(d)
  out: Dict[str, Envelope] = {}
  for op, demos in by_op.items():
    spec = TRANSFERABLE_BY_OP.get(op)
    if spec is None:
      raise ValueError(
        f"a demonstration of '{op}' is recorded, but no Transferable declares what it "
        "measures; a demonstration whose metric nobody specified cannot be compared to "
        "anything"
      )
    out[op] = Envelope(
      operation=op,
      metric=spec.metric,
      units=spec.units,
      goal=spec.goal,
      demonstrations=tuple(demos),
    )
  return out


ENVELOPES: Dict[str, Envelope] = _build_envelopes()


def envelope_for(operation: str) -> Optional[Envelope]:
  """The expert envelope for an operation, or None where nobody has demonstrated it."""
  return ENVELOPES.get(operation)


def observations_for(operation: str) -> Tuple[MachineObservation, ...]:
  return tuple(o for o in MACHINE_OBSERVATIONS if o.operation == operation)


def demonstrations_still_needed(operation: str) -> int:
  """How many more expert demonstrations before this operation has an envelope."""
  env = envelope_for(operation)
  have = 0 if env is None else env.n()
  return max(0, MIN_DEMONSTRATIONS - have)


def taught(operation: str) -> Tuple[bool, str]:
  """Does an expert envelope exist for this operation at all?

  A missing demonstration is not a pass, in the same way a missing benchmark is not trust
  and a missing measurement is not a met criterion. An operation nobody has demonstrated is
  untaught, and an operation demonstrated once is still untaught: something was shown, and
  what was shown carries no tolerance, so there is nothing for a machine to be held to.
  """
  env = envelope_for(operation)
  spec = TRANSFERABLE_BY_OP.get(operation)
  if env is None:
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


def untaught_operations(protocol) -> List[Tuple[str, str]]:
  """(op, reason) for every distinct operation in a protocol with no expert envelope.

  Deliberately overlaps `intelligence.untrusted_ops` and answers a different question. That
  one asks whether the machine has earned the right to run unattended; this one asks whether
  anybody has established what running it well looks like. An operation can fail both, and
  the work that fixes them is done by different people -- one is bench time on the
  instrument, the other is bench time by the scientist, and the second cannot be bought.
  """
  out: List[Tuple[str, str]] = []
  seen = set()
  for step in protocol.steps:
    if step.op in seen:
      continue
    seen.add(step.op)
    ok, why = taught(step.op)
    if not ok:
      out.append((step.op, why))
  return out


# -- the transfer report -------------------------------------------------------


@dataclass(frozen=True)
class TransferRow:
  """One operation: what the expert established, what the machine did, and whether it attains.

  `benchmarks` is resolved from `intelligence` rather than restated, so this report cannot
  disagree with that layer about what was asserted. The row carries both because the whole
  point is that they are different evidence: side by side, an operation with a benchmark and
  no envelope is visibly a target nobody has shown is reachable.
  """

  operation: str
  envelope: Optional[Envelope]
  observations: Tuple[MachineObservation, ...]
  parity: Parity
  benchmarks: Tuple[Benchmark, ...]
  specified: bool  # a Transferable declares what a demonstration would measure

  @property
  def has_expert_envelope(self) -> bool:
    return self.envelope is not None and self.envelope.tolerance() is not None

  @property
  def asserted_only(self) -> bool:
    """A target somebody asserted, and nobody has demonstrated is reachable."""
    return bool(self.benchmarks) and not self.has_expert_envelope


@dataclass
class TransferReport:
  """Every operation asked the transfer question at once."""

  rows: List[TransferRow]

  def untaught(self) -> List[TransferRow]:
    return [r for r in self.rows if not r.has_expert_envelope]

  def attained(self) -> List[TransferRow]:
    return [r for r in self.rows if r.parity.demonstrated]

  def asserted_only(self) -> List[TransferRow]:
    """Operations with a benchmark and no envelope.

    The most common state in a real programme and the one that reads as progress: a number
    exists, it is written down, it has a unit, and nobody has shown a person can hit it.
    """
    return [r for r in self.rows if r.asserted_only]

  def unplaceable(self) -> List[TransferRow]:
    """Operations where numbers exist on both sides and still say nothing."""
    return [
      r
      for r in self.rows
      if r.parity.attainment is Attainment.INDISTINGUISHABLE_FROM_UNMEASURED
    ]

  def transfers(self) -> bool:
    """True only if every operation in this report has an envelope the machine attains.

    The `bool(self.rows)` guard is the point of the method. An empty report satisfies `all()`
    vacuously, and a transfer report over zero operations is not a lab that has finished
    teaching its machines -- it is a report nobody gave any operations to.
    """
    return bool(self.rows) and all(r.parity.demonstrated for r in self.rows)

  def counts(self) -> Dict[str, int]:
    return {
      "operations": len(self.rows),
      "specified": sum(1 for r in self.rows if r.specified),
      "with_envelope": sum(1 for r in self.rows if r.has_expert_envelope),
      "attained": len(self.attained()),
      "unplaceable": len(self.unplaceable()),
      "asserted_only": len(self.asserted_only()),
    }


def transfer_report(operations: Sequence[str]) -> TransferReport:
  """For each operation: is there an envelope, is there machine performance, does it attain?

  Duplicate operations collapse, keeping the given order. Everything on a row is resolved
  from the layer that owns it -- envelopes from the demonstrations, benchmarks from
  `intelligence` -- so a row cannot state a target this package states differently elsewhere.
  """
  rows: List[TransferRow] = []
  seen = set()
  for op in operations:
    if op in seen:
      continue
    seen.add(op)
    env = envelope_for(op)
    obs = observations_for(op)
    rows.append(
      TransferRow(
        operation=op,
        envelope=env,
        observations=obs,
        parity=attainment(env, obs, operation=op),
        benchmarks=tuple(BENCHMARKS_BY_OP.get(op, ())),
        specified=op in TRANSFERABLE_BY_OP,
      )
    )
  return TransferReport(rows=rows)


# -- what an expert should demonstrate next ------------------------------------


@dataclass(frozen=True)
class NextDemonstration:
  """One entry in the SME queue: sit at this instrument, demonstrate these operations."""

  instrument: str
  operations: Tuple[str, ...]
  demonstrations_needed: int
  steps_blocked: int

  @property
  def cost(self) -> int:
    """Demonstrations to perform. A crude proxy for the expert's time, and an honest one:
    each is one full run of the operation on real material, with the outcome measured."""
    return self.demonstrations_needed


def demonstration_queue(protocols: Sequence) -> List[NextDemonstration]:
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
  """
  ops_by_instrument: Dict[str, List[str]] = {}
  steps: Dict[str, int] = {}
  needed: Dict[str, int] = {}

  for protocol in protocols:
    for step in protocol.steps:
      if step.op not in TRANSFERABLE_BY_OP:
        continue
      ok, _why = taught(step.op)
      if ok:
        continue
      ops = ops_by_instrument.setdefault(step.instrument, [])
      if step.op not in ops:
        ops.append(step.op)
        needed[step.instrument] = needed.get(step.instrument, 0) + demonstrations_still_needed(
          step.op
        )
      steps[step.instrument] = steps.get(step.instrument, 0) + 1

  out = [
    NextDemonstration(
      instrument=key,
      operations=tuple(ops),
      demonstrations_needed=needed.get(key, 0),
      steps_blocked=steps.get(key, 0),
    )
    for key, ops in ops_by_instrument.items()
  ]
  out.sort(key=lambda q: (-len(q.operations), -q.steps_blocked, q.cost, q.instrument))
  return out


def teaching_summary() -> Dict[str, int]:
  """How much of the expert performance behind these protocols has been recorded."""
  return {
    "operations_specified": len(TRANSFERABLE),
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
  "MACHINE_OBSERVATIONS",
  "MIN_DEMONSTRATIONS",
  "TRANSFERABLE",
  "TRANSFERABLE_BY_OP",
  "Attainment",
  "Demonstration",
  "Envelope",
  "Goal",
  "MachineObservation",
  "NextDemonstration",
  "Parity",
  "Transferable",
  "TransferReport",
  "TransferRow",
  "attainment",
  "demonstration_queue",
  "demonstrations_still_needed",
  "envelope_for",
  "observations_for",
  "taught",
  "teaching_summary",
  "transfer_report",
  "untaught_operations",
]
