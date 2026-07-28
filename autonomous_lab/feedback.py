"""Whether a loop that claims to correct itself can actually close, and where it opens.

Every other layer in this package plans a run or costs one. None of them models the run
ADJUSTING ITSELF, which is the thing the phrase "self-driving lab" is actually about. A
closed loop is three operations -- measure, compare, act -- and in a laboratory each one has
its own specific way of being fake:

  MEASURE   the number arrives after the material it describes has already been consumed,
            or the step named as the sensor never produces that number in the first place.
  COMPARE   there is no envelope to compare against, so nothing defines what good is.
  ACT       the correction is one the thing holding the loop may not make.

A loop that fails any of the three is an open loop with a control diagram drawn around it.
This module makes a loop declare all three and computes whether it closes.

The load-bearing idea is LATENCY versus ACTIONABILITY, and it is the one that does the
damage. A measurement taken after the correction point cannot steer anything -- not with a
better instrument, not with a faster instrument, not with a better model reading it. It is a
post-mortem wearing the costume of a control loop. So every loop declares where its
measurement is taken and where its correction would be applied, and any loop whose sensor
sits downstream of its actuator is refused outright.

That refusal is pure graph reasoning over the protocol this repo already models. It needs no
new evidence, no instrument, and no decode, and it kills the two loops this lab would most
like to have:

  The genomics protocol quantifies its library on the plate reader AFTER the pool. The one
  number that could size a pool arrives one step too late to size it. Repair the reader
  tomorrow and the loop is still open, because what is wrong is the ORDER, and the fix is a
  different assay at a different point in the protocol rather than a working instrument.

  Reading yield off the sequencing run to steer the sequencing run is the same shape with a
  flow cell attached. It is a real and useful thing to do, and it is a NEXT-RUN loop rather
  than a control loop. Calling it closed-loop control hides the part that matters, which is
  that the current run is already spent.

The other three refusals are separate on purpose and are never collapsed into the first,
because each one is bought with different work. NO_ENVELOPE means nothing in this repo says
what good is for that quantity, so there is no target to steer toward and the loop is
underspecified rather than late; the fix is a threshold with a basis, which costs an
experiment. SENSOR_DOES_NOT_MEASURE_IT means the step the loop names as its sensor is not
where that number comes from -- qc owns the quantity-to-artifact fact and the protocol owns
which step produces that artifact, and between them they settle it without asking the loop's
author; the fix is a corrected declaration, or an assay this protocol does not currently
run. UNAVAILABLE_MEASUREMENT is resolved from the ledger -- the step the number really comes
from is blocked, manual, or broken -- and the fix is a decode, a debug, or a person. And
UNPERMITTED_CORRECTION means the loop declares a controller weaker than the correction
requires, which is settled by a decision rather than by money. Reporting one number over
five different budgets is the failure this whole package exists to refuse.

The refusals are ordered so the headline is the one a reader must not be sent away from. A
lab told "the measurement is unavailable" will go buy an instrument, and if the loop is also
structurally open that instrument buys nothing at all -- and if the loop is sensing at a step
that never produced the number, repairing the instrument at that step buys nothing either.
So the structural refusal is reported first, the sensor refusal ahead of the instrument one,
and every refusal a loop earns is carried, not just the first, so nobody discovers the next
one only after paying for the last. `counts()` and `by_reason()` tally HEADLINES, which is
one refusal per loop; `blocker_counts()` tallies every refusal earned. The two answer
different questions and the docstrings say which is which, because a lab budgeting off the
headline tally reads a zero next to a refusal four loops earned.

WHAT THIS MODULE WILL NOT SAY. It does not model gain, overshoot, damping, stability, or a
settling time. Those are properties of a plant, and computing any of them needs a plant model
plus measured response data: how far the output moves for a given change in the input, and
how long it takes to get there. This package has neither. `throughput` already refuses to
return plates per day because 18 of 18 steps have never been timed, and the same emptiness
sits underneath every dynamic quantity -- a settling time returned over unmeasured response
data would be a number that gets quoted, and then designed against.

What protocol structure alone DOES support is a count. Between the sensor and the actuator
there are steps, and on a line running full there is material standing at each of them. Every
one of those plates reaches the correction point before the newest measurement can change it,
so the correction cannot help them however good it is. `in_flight_exposure` returns that
count. It is the honest form of "how fast can this loop react": in plates, which the protocol
knows, rather than in seconds, which nobody here has measured.

Three scoping notes, because a verdict read wider than it was computed is worse than no
verdict. CLOSES is a claim about the LOOP -- its order, its target, its sensor, and its
authority. It is not a claim that the step being corrected runs at all; the ledger owns that
question, and `corrections_nobody_can_apply` reports it beside the verdict rather than inside
it, the same way qc keeps a wrong-assay gate separate from an unsatisfiable one. It is also
not a claim that the number is the RIGHT number for the sample. qc already owns that fact in
`Measurement.instrument_appropriate`, and a loop can drive a quantity into its band reliably
while the quantity is confidently about the wrong thing -- so that caveat is resolved from qc
and reported by `loops_on_an_inappropriate_measurement`, beside the verdict and named in the
CLOSES reason, never silently folded into either. And the envelope a loop steers toward is
resolved from the qc criterion that already owns the number, never restated here: two copies
of one cutoff eventually disagree, and a loop steering toward the retired copy would look
exactly like a loop steering toward the live one. Where no gate owns a bound, `for_quantity`
still resolves the UNITS off the qc measurement, because units are qc's fact whether or not
a criterion exists.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .model import Verdict
from .qc import (
  GATES,
  MEASUREMENTS,
  PROTOCOL_GATES,
  Basis,
  Comparison,
  Criterion,
  Gate,
  Measurement,
  Readiness,
)
from .throughput import duration_for

# The dynamic quantities this module refuses to emit, named so the refusal is explicit
# rather than merely absent. Each one needs a plant model and measured response data --
# how much the output moves per unit of input, and over what horizon -- and this package
# has never measured a single step duration, let alone a response curve. Naming them here
# is what makes the omission checkable instead of a thing somebody adds later by accident.
NOT_MODELLED: Tuple[str, ...] = (
  "gain",
  "overshoot",
  "damping",
  "stability margin",
  "time constant",
  "settling time",
)


class Controller(str, Enum):
  """Who computes the correction and applies it. Ordered weakest to strongest.

  The ordering is by how little a generated token can move, not by how much intelligence is
  applied, and that is what makes it computable. A drafting model is still in the path: the
  ratifier reads a proposal that has already framed the problem, and a plausible frame is
  what a model produces most reliably when it is wrong.

  Nothing else in this package decides correction authority, so `_MINIMUM_CONTROLLER` below
  is the sole owner of these floors and there is no sibling to resolve them from. The
  nearest neighbour is `provenance.Actor`, and it is worth naming precisely because it looks
  like one: Actor records WHO performed a step that already happened -- machine, human, or
  agent, where AGENT means a model proposed it and a gate or a person permitted it. It is a
  label on a recorded event. It settles nothing about whether that actor was strong enough
  to make the correction, which is the question this enum exists to answer, and it is asked
  before the act rather than written down after it.
  """

  MODEL = "model"  # a model emits the correction and the correction is applied
  MODEL_PROPOSES = "model_proposes"  # a model drafts; a coded check or a person ratifies
  CODED = "coded"  # a coded controller computes and applies it; no model in the path
  HUMAN = "human"  # a named person decides and performs it, and is accountable for it

  @property
  def model_in_path(self) -> bool:
    """True where model output reaches the correction at all, deciding or drafting.

    This is the line the enum exists to draw. A correction that consumes material does not
    become safe by adding a reviewer to a model's account of why it should be consumed.
    """
    return self in (Controller.MODEL, Controller.MODEL_PROPOSES)

  @property
  def rank(self) -> int:
    return _CONTROLLER_ORDER.index(self)

  def may_apply(self, correction: "Correction") -> bool:
    """Is this controller strong enough for what the correction actually does?

    Strengthening always satisfies. A lab may put a person on a correction a coded
    controller could make; the reverse is the defect this check exists to catch.
    """
    return self.rank >= correction.minimum_controller.rank


# Weakest first. Used by rank, may_apply, and every report that orders by strength.
_CONTROLLER_ORDER: Tuple[Controller, ...] = (
  Controller.MODEL,
  Controller.MODEL_PROPOSES,
  Controller.CODED,
  Controller.HUMAN,
)


class Correction(str, Enum):
  """What the correction does to the process, which is what decides who may apply it.

  Deliberately not qc.Decision, which is the neighbouring vocabulary. A gate decides what to
  do with a plate that already failed; a control loop changes a setting so the next one does
  not. RETUNE has no Decision equivalent at all, and that absence is the tell that these are
  two vocabularies rather than one restated -- reusing Decision here would have forced every
  parameter change to be reported as a RETRY, which is a different physical act.
  """

  HOLD = "hold"  # stop the line where it is and wait for someone
  RETUNE = "retune"  # change a parameter the next execution of the step will run under
  REPEAT = "repeat"  # run the step again on material that is still viable
  DIVERT = "divert"  # route the material down a different path
  DISCARD = "discard"  # destroy material, or spend a scarce input to salvage it

  @property
  def reversible(self) -> bool:
    """Can the material be put back the way it was after a wrong correction?

    True only for HOLD, and the asymmetry is the point rather than an artifact of a short
    list. Stopping commits nothing: the plate is where it was and a wrong stop costs time.
    Everything else spends something before anybody reads the decision that spent it, which
    is why the strength required climbs with the spend rather than with the difficulty.
    """
    return self is Correction.HOLD

  @property
  def minimum_controller(self) -> Controller:
    return _MINIMUM_CONTROLLER[self]


# Why each floor sits where it does. These are arguments, not preferences, and each one
# points at something already computed elsewhere in this package.
_MINIMUM_CONTROLLER: Dict[Correction, Controller] = {
  # Stopping is the one correction a model may make alone, because the failure of a wrong
  # stop is a delay somebody notices immediately. Setting this any higher would mean a lab
  # whose model saw a problem had to wait for a ratifier before the line stopped.
  Correction.HOLD: Controller.MODEL,
  # A parameter change is quiet and cumulative. This repo's own volume_short_within_tolerance
  # failure is exactly a parameter error that nothing flags, biases the dataset instead of
  # breaking it, and stays inside the instrument's tolerance -- so a draft is useful and it
  # is not the last word.
  Correction.RETUNE: Controller.MODEL_PROPOSES,
  # Repeating spends a reagent set, and the qc layer already separates RETRY from RECOVER
  # because material that changed state is destroyed by a repeat rather than rescued by one.
  # Nothing in this module can tell those apart, so a ratifier must.
  Correction.REPEAT: Controller.MODEL_PROPOSES,
  # Routing material is where attribution dies. The lineage layer's whole finding is that a
  # wrong merge is permanent at the moment it happens, and an interlock reading a barcode
  # cannot be argued into a different route by a well-formed account of the situation.
  Correction.DIVERT: Controller.CODED,
  # Destroying a sample cannot be undone by noticing afterward that the correction was
  # wrong. A named person approves it and is accountable for having approved it.
  Correction.DISCARD: Controller.HUMAN,
}


class Closable(str, Enum):
  """Whether a control loop can close, and if not, which of the three legs is fake.

  The five refusals are listed in the order they are reported, and that order is the line
  this enum draws. OPEN_LOOP_SENSOR_TOO_LATE is first because it is the only one no
  purchase, decode, or policy change repairs: the protocol has to be rewritten so the
  measurement happens before the thing it steers. Reporting a cheaper reason ahead of it
  sends a lab to buy an instrument for a loop that could never have closed.

  SENSOR_DOES_NOT_MEASURE_IT sits ahead of UNAVAILABLE_MEASUREMENT for the same reason one
  step down. UNAVAILABLE_MEASUREMENT says the step the number comes from cannot be driven
  here, and its fix is a decode, a debug, or a person AT THAT STEP. That advice is worthless
  when the step named is not where the number comes from: repairing an instrument that never
  produced the quantity produces it no harder. So the question "is this really the sensor"
  is answered first, and the ledger is then read at the step the answer points to.
  """

  OPEN_LOOP_SENSOR_TOO_LATE = "open_loop_sensor_too_late"  # measured at or after the correction point
  NO_ENVELOPE = "no_envelope"  # nothing declares what good is; there is nothing to steer toward
  SENSOR_DOES_NOT_MEASURE_IT = "sensor_does_not_measure_it"  # that step is not where this number comes from
  UNAVAILABLE_MEASUREMENT = "unavailable_measurement"  # the measuring step does not produce a number here
  UNPERMITTED_CORRECTION = "unpermitted_correction"  # the controller is weaker than the correction needs
  CLOSES = "closes"

  @property
  def closed(self) -> bool:
    return self is Closable.CLOSES

  @property
  def structural(self) -> bool:
    """True only for the refusal that money cannot move.

    The other four name work a lab can buy, schedule, decide, or correct on the page. This
    one names an ordering in the protocol, and the only thing that changes it is measuring
    somewhere else. SENSOR_DOES_NOT_MEASURE_IT is deliberately not in here: a loop naming
    the wrong sensor is usually a declaration a author fixes for free, and folding it in
    with a refusal that needs the protocol rewritten would put the two behind one budget.
    """
    return self is Closable.OPEN_LOOP_SENSOR_TOO_LATE


# Reported in this order. CLOSES is not in it: it is what is left when nothing else applies.
_REFUSAL_ORDER: Tuple[Closable, ...] = (
  Closable.OPEN_LOOP_SENSOR_TOO_LATE,
  Closable.NO_ENVELOPE,
  Closable.SENSOR_DOES_NOT_MEASURE_IT,
  Closable.UNAVAILABLE_MEASUREMENT,
  Closable.UNPERMITTED_CORRECTION,
)


def _readiness_of(verdict: Verdict) -> Readiness:
  """Whether a number arrives from a step in this state, in qc's vocabulary.

  This is the partition `qc.readiness()` draws over the same verdicts, and the answer is
  returned as a qc.Readiness rather than as a local tuple of verdicts so the two are one
  vocabulary and not two. qc performs the mapping inline over a gate's inputs and exports no
  function for it, so it cannot be imported today -- which is exactly why the RESULT TYPE is
  imported and why a test costs a real gate through `qc.readiness()` and compares the answer
  to this one. The day qc decides SUPERVISED is not evaluable, or a Verdict is added, that
  test fails here rather than this module going on steering on the retired partition.

  Deliberately not reused to answer whether a machine can ACT at a step. That is a different
  question about the same verdict, `_step_runs_today` answers it, and one constant answering
  both is how the two start disagreeing with nothing to reveal which was meant.
  """
  if verdict is Verdict.AUTOMATED:
    return Readiness.READY
  if verdict is Verdict.SUPERVISED:
    return Readiness.SUPERVISED
  return Readiness.UNSATISFIABLE


def _step_runs_today(verdict: Verdict) -> bool:
  """Whether anything at all reaches a step in this state, machine or supervised operator.

  This is the partition `Ledger.reachable()` draws, asked here about the step a correction
  lands on rather than about the step a number comes from. The ledger computes it inline and
  exports no predicate, so a test pins this against `Ledger.reachable()` over a real ledger
  rather than letting a second copy drift quietly.
  """
  return verdict in (Verdict.AUTOMATED, Verdict.SUPERVISED)


def _correction_can_land(controller: "Controller", verdict: Verdict) -> bool:
  """Can this controller actually apply a correction at a step in this state?

  Two facts and not one. The step has to be reachable at all, which is the ledger's
  question, and where it is not, the only controller that changes the answer is a person --
  and only at a step whose whole description is that a person does it. MANUAL is that step.
  BLOCKED, BROKEN and WRITTEN are not: an undecoded command set, a script that fails on the
  instrument, and a script never run on it are not waiting for somebody to walk over.
  """
  if _step_runs_today(verdict):
    return True
  return controller is Controller.HUMAN and verdict is Verdict.MANUAL


@dataclass(frozen=True)
class Envelope:
  """The band a correction steers the measured quantity back into.

  An envelope with no bound on either side is refused at construction. That is the vacuous
  case and it is the dangerous one: an unbounded band contains every value, so a loop built
  on it reports itself in specification forever, corrects nothing, and looks exactly like a
  loop that is working. Absence of a bound is not a wide bound.

  Neither is an infinite one, and neither is a NaN, so both are refused the same way and for
  the same reason. `upper=inf` is not a permissive ceiling, it is the absence of a ceiling
  spelled as a float, and it walks straight past a guard that only tests `is None`. NaN is
  worse: every comparison against it is False, so it survives the inverted-bound check as
  well and then `contains()` returns True for every value on both sides. A bound has to be
  a real number for a band to be a band.

  `basis` comes from the qc criterion this was resolved from and is carried rather than
  checked. An envelope resting on intuition is still an envelope and the loop can still
  close around it -- what it cannot do is pass unreported, so `unvalidated_envelopes()`
  lists it.

  The raw constructor stays open for a quantity qc does not declare -- residual_solvent_mass
  is a real thing to bound and qc has never heard of it -- which is why `units` is a free
  field here. Where qc DOES declare the quantity, build with `for_quantity` instead: the
  units are qc's fact, and restating them by hand gives this lab a second copy that a reader
  meets through `describe()` and through a closure's reason.
  """

  quantity: str  # the qc.Measurement key this bounds
  units: str
  lower: Optional[float] = None
  upper: Optional[float] = None
  basis: Basis = Basis.INTUITION
  note: str = ""

  def __post_init__(self) -> None:
    if self.lower is None and self.upper is None:
      raise ValueError(
        f"envelope for '{self.quantity}' bounds nothing on either side; an unbounded band "
        "accepts every value, so a loop steering toward it never corrects anything"
      )
    for side, bound in (("lower", self.lower), ("upper", self.upper)):
      if bound is not None and not math.isfinite(bound):
        raise ValueError(
          f"envelope for '{self.quantity}' has a {side} bound of {bound}, which bounds "
          "nothing: an infinite side accepts every value above or below it and a NaN side "
          "accepts every value at all, so a loop steering toward it never corrects anything"
        )
    if self.lower is not None and self.upper is not None and self.upper < self.lower:
      raise ValueError(
        f"envelope for '{self.quantity}' has upper {self.upper} below lower {self.lower}"
      )

  @classmethod
  def for_quantity(
    cls,
    quantity: str,
    lower: Optional[float] = None,
    upper: Optional[float] = None,
    basis: Basis = Basis.INTUITION,
    note: str = "",
  ) -> "Envelope":
    """An envelope whose units are resolved from qc rather than typed in beside them.

    For the case `envelope_from_criterion` cannot serve: qc declares the quantity but no
    gate declares a bound on it, so the number and its basis genuinely originate here. The
    UNITS do not. qc owns them independently of whether any criterion exists, and a hand
    written unit is a second copy that goes on printing after qc revises the measurement.
    Refuses a quantity qc does not declare, so this cannot quietly become a second way to
    invent one.
    """
    measurement = MEASUREMENTS.get(quantity)
    if measurement is None:
      raise KeyError(
        f"qc declares no measurement '{quantity}', so its units cannot be resolved; build "
        "the envelope directly if the quantity is genuinely one qc does not own"
      )
    return cls(
      quantity=quantity,
      units=measurement.units,
      lower=lower,
      upper=upper,
      basis=basis,
      note=note,
    )

  @property
  def validated(self) -> bool:
    return self.basis.validated

  def contains(self, value: float) -> bool:
    if self.lower is not None and value < self.lower:
      return False
    if self.upper is not None and value > self.upper:
      return False
    return True

  def describe(self) -> str:
    if self.lower is not None and self.upper is not None:
      return f"{self.lower} <= {self.quantity} <= {self.upper} {self.units}"
    if self.lower is not None:
      return f"{self.quantity} >= {self.lower} {self.units}"
    return f"{self.quantity} <= {self.upper} {self.units}"


def envelope_from_criterion(gate: Gate, criterion_name: str) -> Envelope:
  """Build an envelope out of a threshold the qc layer already owns.

  The number, the direction, the quantity it bounds, and the basis it rests on are all qc's
  facts. Restating any of them here would give this lab two copies of one cutoff, and the
  day somebody revises the gate the loop would go on steering toward the retired band with
  nothing anywhere to reveal which of the two was live. Units are resolved the same way, off
  the declared measurement, so an envelope cannot be built for a quantity qc does not know.

  A criterion name used twice in one gate is refused rather than resolved to the first hit,
  the same way `_index_of` refuses a step op used twice. The revision this function exists to
  survive is precisely the one that produces a duplicate -- somebody adds the tightened
  cutoff and leaves the permissive one in place -- so resolving silently would hand back the
  retired band exactly when it matters most.
  """
  matches: List[Criterion] = [c for c in gate.criteria if c.name == criterion_name]
  if not matches:
    raise KeyError(
      f"gate '{gate.name}' declares no criterion '{criterion_name}'; "
      f"it has: {[c.name for c in gate.criteria]}"
    )
  if len(matches) > 1:
    raise ValueError(
      f"gate '{gate.name}' declares '{criterion_name}' {len(matches)} times, with bounds "
      f"{[c.bound for c in matches]}; a name used twice is not a criterion. Taking the first "
      "would build the envelope out of whichever copy sits earlier in the tuple, and a loop "
      "steering toward the retired cutoff looks exactly like one steering toward the live one"
    )
  match: Criterion = matches[0]
  measurement = MEASUREMENTS.get(match.measurement)
  if measurement is None:
    raise KeyError(
      f"criterion '{criterion_name}' reads '{match.measurement}', which qc does not declare "
      "as a measurement; an envelope over an undeclared quantity bounds nothing"
    )
  lower: Optional[float] = None
  upper: Optional[float] = None
  if match.comparison is Comparison.AT_LEAST:
    lower = match.bound
  elif match.comparison is Comparison.AT_MOST:
    upper = match.bound
  else:
    lower, upper = match.bound, match.upper
  return Envelope(
    quantity=match.measurement,
    units=measurement.units,
    lower=lower,
    upper=upper,
    basis=match.basis,
    note=f"resolved from qc gate '{gate.name}', criterion '{match.name}'",
  )


@dataclass(frozen=True)
class Loop:
  """One control loop: what it watches, where it watches it, and what it changes.

  There is deliberately no field here that says whether the loop closes. Closability is
  computed against a real protocol and a real ledger, the same way a step's verdict is, and
  a loop that could declare itself closed would be a loop whose author could silence the
  only report in this module worth reading.

  `measured_at` and `corrects` are Step.op values resolved against the protocol, so a loop
  cannot name a step that does not exist, and a loop naming an op that appears twice is
  refused rather than resolved to the first one: an op used at two points in a flow is not a
  position, and guessing which was meant is how a loop reads as closed because the wrong
  occurrence happened to sit upstream.
  """

  name: str
  quantity: str  # the measured quantity; a qc.Measurement key wherever one exists
  measured_at: str  # Step.op where the number is taken
  corrects: str  # Step.op the correction is applied to
  correction: Correction
  applied_by: Controller
  envelope: Optional[Envelope] = None
  note: str = ""

  def permitted(self) -> bool:
    """Is the declared controller strong enough for the declared correction?

    A method rather than a field. A stored answer sitting beside the controller and the
    correction it was derived from eventually disagrees with them, and nothing on the object
    reveals which of the three is wrong.
    """
    return self.applied_by.may_apply(self.correction)

  def steers_toward(self) -> str:
    if self.envelope is None:
      return "nothing; no envelope is declared for this quantity"
    return self.envelope.describe()


@dataclass(frozen=True)
class Blocker:
  """One reason a loop does not close, with the specific thing that is wrong."""

  reason: Closable
  detail: str


@dataclass(frozen=True)
class Closure:
  """A loop costed against a real protocol and a real ledger.

  `blockers` is every refusal the loop earned, in reporting order, and the verdict is the
  first of them. Carrying all of them matters more than it looks: a loop is usually broken
  in more than one way, and a report that showed only the first would send a lab to fix that
  one and rediscover the next after paying for it.

  `corrects_verdict` is the ledger's verdict for the step being corrected, carried here so
  no reader has to look it up separately. It is NOT part of the verdict, and that scoping is
  deliberate -- see `FeedbackReport.corrections_nobody_can_apply`.
  """

  loop: Loop
  blockers: Tuple[Blocker, ...]
  measured_index: int
  corrects_index: int
  corrects_verdict: Verdict

  @property
  def verdict(self) -> Closable:
    return self.blockers[0].reason if self.blockers else Closable.CLOSES

  @property
  def closes(self) -> bool:
    return not self.blockers

  @property
  def reason(self) -> str:
    if self.blockers:
      return self.blockers[0].detail
    closes = (
      f"'{self.loop.quantity}' is measured at '{self.loop.measured_at}', which is upstream of "
      f"'{self.loop.corrects}'; it steers toward {self.loop.steers_toward()}, the number "
      f"arrives, and {self.loop.applied_by.value} may make a {self.loop.correction.value}"
    )
    # The caveat travels with the verdict rather than beside it, because CLOSES is the one
    # string a reader quotes and a wrong-assay loop closes perfectly well around the wrong
    # number. Resolved from qc, so it disappears the day the appropriate assay lands.
    wrong_assay = inappropriate_measurement(self.loop.quantity)
    if wrong_assay is not None:
      closes += (
        f". The loop closes and the number is the wrong one: qc reports "
        f"'{wrong_assay.key}' is not an appropriate measurement here -- "
        f"{wrong_assay.inappropriate_reason}. A closed loop drives this quantity into its "
        "band reliably, and the band is about the wrong thing"
      )
    return closes

  def on_an_inappropriate_measurement(self) -> Optional[Measurement]:
    """The qc measurement this loop steers on, when qc calls it the wrong assay.

    A method rather than a field for the usual reason, and resolved from qc rather than
    copied, so a loop stops being flagged the moment the measurement it reads is replaced
    by one that is appropriate.
    """
    return inappropriate_measurement(self.loop.quantity)

  def all_reasons(self) -> Tuple[str, ...]:
    return tuple(b.detail for b in self.blockers)

  def refusals(self) -> Tuple[Closable, ...]:
    return tuple(b.reason for b in self.blockers)


@dataclass(frozen=True)
class InFlight:
  """How much material is committed between a loop's sensor and its actuator.

  Counted in steps and reported in plates, never in seconds. Seconds would need step
  durations, and neither reference protocol has a single step with a measured one --
  `throughput.estimate(...).why_not()` says 18 of 18 for the genomics flow. The package is
  not entirely untimed, and the distinction matters because an absolute claim here is false:
  `throughput.DURATIONS` carries one MEASURED entry, the Tecan's tray cycle, timed on real
  hardware. It is the duration of a drawer opening and it belongs to no step in either
  protocol, so it buys no reaction time for any loop. `meaning` counts the untimed steps of
  the protocol in front of it rather than restating any of this, so the sentence a reader is
  shown is computed and stops being true the day somebody times the flow.
  """

  loop: Loop
  steps_between: int
  intervening: Tuple[str, ...]
  meaning: str

  @property
  def immediate(self) -> bool:
    """True only when the correction lands at the very next step.

    The single case where a correction reaches every plate it was computed for. Anything
    else means material passes the correction point under the setting the correction is
    about to change, and no amount of controller quality reaches it.
    """
    return self.steps_between == 0


def _index_of(protocol, op: str, role: str) -> int:
  """Where a step op sits in the protocol's order, refusing anything ambiguous."""
  hits = [i for i, step in enumerate(protocol.steps) if step.op == op]
  if not hits:
    raise KeyError(
      f"loop names '{op}' as its {role}, which is not a step in protocol '{protocol.name}'"
    )
  if len(hits) > 1:
    raise ValueError(
      f"'{op}' appears {len(hits)} times in protocol '{protocol.name}' (positions "
      f"{hits}), so it is not a position and cannot be a loop's {role}. Picking the first "
      "occurrence would report a loop as closed whenever the wrong one happened to sit "
      "upstream"
    )
  return hits[0]


def inappropriate_measurement(quantity: str) -> Optional[Measurement]:
  """The qc measurement behind a quantity, when qc says it is the wrong assay for the sample.

  Resolved from `qc.Measurement.instrument_appropriate` and never restated. This is the
  quiet failure qc separates from an unsatisfiable gate, and it needs separating here for
  the same reason: an unavailable measurement fails loudly, because no number arrives, while
  a wrong-assay measurement arrives, compares cleanly, and steers the process confidently
  toward a band computed about the wrong thing. Of the two, this is the one that spends the
  flow cell.
  """
  measurement = MEASUREMENTS.get(quantity)
  if measurement is None or measurement.instrument_appropriate:
    return None
  return measurement


def _resolve_sensor(loop: Loop, protocol) -> Tuple[int, Optional[Blocker]]:
  """Where this loop's number actually comes from, and the refusal if that is not where the
  loop says.

  The declaration is not evidence. `measured_at` is a string an author types, and the shipped
  loops being consistent with it says nothing about the next one -- a loop can name an HTTP
  liveness probe as the sensor for a library concentration, and every downstream check will
  then be costed against the probe's ledger row, which is AUTOMATED, which reads as "the
  number arrives". That is the empty-measurement failure this package hunts, wearing a
  control diagram: absent data yielding a verdict whose own prose asserts the data arrived.

  So where qc declares the quantity, the sensor is resolved the way `qc.readiness()` resolves
  it and not from the declaration: the measurement names the artifact it comes from, the
  protocol names the step that produces that artifact, and that step is the sensor. Every
  later check is costed against THAT row. Where the two disagree the loop is refused and the
  refusal names both, because one of them is wrong and this module cannot tell which.

  Where qc does NOT declare the quantity there is no artifact to resolve through, and
  residual_solvent_mass is a real quantity in exactly that position. The declaration is then
  all there is, and the one thing still checkable is whether the named step yields anything
  at all: a step whose `produces` is empty hands back no artifact, so it hands back no
  number, and a loop reading one is reading a value the protocol never creates. That is a
  necessary condition and not a sufficient one, and the docstring says so rather than letting
  a weaker check be read as the stronger one.
  """
  declared_index = _index_of(protocol, loop.measured_at, "measured_at")
  measurement = MEASUREMENTS.get(loop.quantity)

  if measurement is None:
    if not protocol.steps[declared_index].produces:
      return declared_index, Blocker(
        Closable.SENSOR_DOES_NOT_MEASURE_IT,
        f"'{loop.quantity}' is not a quantity qc declares, so nothing resolves where it comes "
        f"from, and the step this loop names as its sensor -- '{loop.measured_at}' -- produces "
        "no artifact at all. Nothing in this protocol creates that number, so the comparison "
        "would run against a value nobody hands it. Declare the quantity in qc, or name a "
        "step that actually produces something",
      )
    return declared_index, None

  producers = [
    i for i, step in enumerate(protocol.steps) if measurement.produced_by in step.produces
  ]
  if not producers:
    return declared_index, Blocker(
      Closable.SENSOR_DOES_NOT_MEASURE_IT,
      f"qc says '{loop.quantity}' comes from artifact '{measurement.produced_by}', which no "
      f"step in protocol '{protocol.name}' produces. The loop names '{loop.measured_at}' as "
      "its sensor, but this protocol never creates that number anywhere, so no instrument "
      "repair at that step or any other makes it arrive",
    )
  if len(producers) > 1:
    raise ValueError(
      f"artifact '{measurement.produced_by}' is produced at {len(producers)} positions in "
      f"protocol '{protocol.name}' ({[protocol.steps[i].op for i in producers]}), so "
      f"'{loop.quantity}' has no single source and cannot be resolved to a sensor. Picking "
      "one would cost the loop against whichever row happened to come first"
    )
  resolved_index = producers[0]
  if resolved_index != declared_index:
    return resolved_index, Blocker(
      Closable.SENSOR_DOES_NOT_MEASURE_IT,
      f"this loop declares '{loop.quantity}' is measured at '{loop.measured_at}', but qc says "
      f"it comes from artifact '{measurement.produced_by}', which this protocol produces at "
      f"'{protocol.steps[resolved_index].op}' (step {resolved_index + 1}). "
      f"'{loop.measured_at}' produces {list(protocol.steps[declared_index].produces) or 'nothing'}"
      ", so it is not where this number is taken. Costing the loop against the declared step "
      "would read that step's verdict as though it were this measurement's, which is how a "
      "loop over a number nobody produces reports that the number arrives",
    )
  return declared_index, None


def _refuse_mismatched_ledger(protocol, ledger) -> None:
  """Refuse a ledger that does not line up, row for row, with the protocol being costed.

  Every row lookup in this module is POSITIONAL -- the step at index i is costed by the row
  at index i -- so the two have to be the same list of steps and not merely two things with
  the same name. Comparing names alone leaves the whole check open: two protocols may share
  a name and share no steps, and the module then reads an unrelated step's verdict as though
  it were the sensor's. A blocked sensor borrowed from a protocol whose first step happens to
  be a socket probe reads as AUTOMATED, and the loop is reported closed on the strength of an
  instrument it never touches. A ledger shorter than the protocol truncates silently and one
  longer reads past the end, so the length is part of the identity too.
  """
  if ledger.protocol.name != protocol.name:
    raise ValueError(
      f"ledger was built for protocol '{ledger.protocol.name}' but the loop is being costed "
      f"against '{protocol.name}'; a verdict mixed from two protocols describes neither"
    )
  ledger_ops = tuple(row.step.op for row in ledger.rows)
  protocol_ops = tuple(step.op for step in protocol.steps)
  if ledger_ops != protocol_ops:
    raise ValueError(
      f"the ledger named '{ledger.protocol.name}' was built over a different step list than "
      f"the protocol of that name being costed here: {list(ledger_ops)} against "
      f"{list(protocol_ops)}. Rows are matched to steps by position, so costing across these "
      "two would read one step's verdict as another step's, which is the mixed verdict the "
      "name check exists to refuse"
    )


def can_close(loop: Loop, protocol, ledger) -> Closure:
  """Can this loop actually close against this protocol and this workcell?

  Step ordering is resolved from the protocol, which step a quantity comes from is resolved
  from qc, and whether that step runs is resolved from the ledger. None of the three is
  re-derived and none of the three is taken from the loop's author: the protocol owns the
  order the bench runs in, qc owns which artifact carries which number, the ledger owns
  whether a step produces anything, and a second computation of any of them would eventually
  disagree with the first with nothing to say which was right.

  That is why `measured_index` is the RESOLVED sensor rather than the declared one. Every
  check downstream of it -- can the number reach the material, does the number arrive -- is
  a question about the step the number actually comes from, and asking them at a step an
  author merely named is how a loop over an unproduced quantity reports that it closes.

  Every check runs. The function does not return early on the first refusal, because a loop
  broken three ways that reported one way would be fixed one way and still be broken.
  """
  _refuse_mismatched_ledger(protocol, ledger)

  measured_index, sensor_blocker = _resolve_sensor(loop, protocol)
  corrects_index = _index_of(protocol, loop.corrects, "corrects")
  blockers: List[Blocker] = []
  if sensor_blocker is not None:
    blockers.append(sensor_blocker)

  # -- 1. can the measurement reach the material it is supposed to steer? ------
  # The one refusal no purchase moves, so it is checked and reported first.
  if measured_index > corrects_index:
    blockers.append(
      Blocker(
        Closable.OPEN_LOOP_SENSOR_TOO_LATE,
        f"'{loop.quantity}' is measured at '{loop.measured_at}' (step {measured_index + 1}), "
        f"which is downstream of '{loop.corrects}' (step {corrects_index + 1}). The material "
        "has already passed the correction point when the number arrives, so this steers a "
        "future run and not this one. That is a next-run adjustment, not a control loop, and "
        "no instrument, decode, or model changes it -- only measuring earlier does",
      )
    )
  elif measured_index == corrects_index:
    blockers.append(
      Blocker(
        Closable.OPEN_LOOP_SENSOR_TOO_LATE,
        f"'{loop.measured_at}' is both the sensor and the actuator. This package models a "
        "step as atomic, so it cannot see a correction applied inside one and will not claim "
        "a loop closes on evidence it does not have. Declare the measurement as its own step "
        "if the instrument really reports mid-operation",
      )
    )

  # -- 2. is there anything to compare against? --------------------------------
  # An envelope bounding some other quantity is not an envelope for this one. That case
  # looks like a fully specified loop in every summary that counts declarations.
  envelope = loop.envelope
  if envelope is None:
    blockers.append(
      Blocker(
        Closable.NO_ENVELOPE,
        f"nothing declares what a good '{loop.quantity}' is, so there is no band to steer "
        "toward and no way to tell a correction that helped from one that did not. This is "
        "not a missing instrument; it is a missing threshold, and it costs an experiment and "
        "a stated basis",
      )
    )
  elif envelope.quantity != loop.quantity:
    blockers.append(
      Blocker(
        Closable.NO_ENVELOPE,
        f"the declared envelope bounds '{envelope.quantity}', not '{loop.quantity}'. A band "
        "on a neighbouring quantity is not a target for this one, and it counts as a "
        "declaration in every summary that only counts whether an envelope is present",
      )
    )

  # -- 3. does the number actually arrive? -------------------------------------
  # Read at the RESOLVED sensor, so a mis-declared loop is costed against the step the
  # number really comes from rather than against the one it named.
  measuring_row = ledger.rows[measured_index]
  if not _readiness_of(measuring_row.verdict).evaluable:
    blockers.append(
      Blocker(
        Closable.UNAVAILABLE_MEASUREMENT,
        f"'{loop.quantity}' comes from '{measuring_row.step.op}', which this workcell costs "
        f"as {measuring_row.verdict.value}: {measuring_row.reason}. A loop over a number "
        "nobody produces is an open loop that reports no error, because the comparison never "
        "runs",
      )
    )

  # -- 4. may the declared controller make this correction? --------------------
  if not loop.permitted():
    blockers.append(
      Blocker(
        Closable.UNPERMITTED_CORRECTION,
        f"a {loop.correction.value} correction needs at least "
        f"{loop.correction.minimum_controller.value} and this loop declares "
        f"{loop.applied_by.value}"
        + (
          ". The correction is reversible, so the floor is low and this is still below it"
          if loop.correction.reversible
          else ". The correction cannot be undone by noticing afterward that it was wrong"
        ),
      )
    )

  blockers.sort(key=lambda b: _REFUSAL_ORDER.index(b.reason))
  return Closure(
    loop=loop,
    blockers=tuple(blockers),
    measured_index=measured_index,
    corrects_index=corrects_index,
    corrects_verdict=ledger.rows[corrects_index].verdict,
  )


def in_flight_exposure(loop: Loop, protocol) -> InFlight:
  """How many plates are already committed between the sensor and the correction point.

  This is the only thing this module will say about how fast a loop reacts, and it is said
  in plates because plates are what the protocol knows. Every step between the two holds
  material on a line running full, and all of it reaches the correction point before the
  newest measurement can change anything there. A perfect controller does not help those
  plates, which makes this a property of the protocol rather than of the controller.

  Refused for a loop whose sensor is not upstream of its actuator. There is no in-flight
  count for a correction that never reaches its own material, and returning zero would read
  as the best possible case rather than as the absence of a loop.

  The sensor is resolved the same way `can_close` resolves it, so the two agree about which
  step the number comes from. A loop that names the wrong sensor gets its exposure counted
  from the step qc says the number is actually taken at, and `can_close` is where that
  disagreement is reported.
  """
  measured_index, _ = _resolve_sensor(loop, protocol)
  corrects_index = _index_of(protocol, loop.corrects, "corrects")
  if measured_index >= corrects_index:
    raise ValueError(
      f"loop '{loop.name}' measures at or after the step it corrects, so no material is in "
      f"flight between them -- the correction never reaches this run's material at all. "
      f"can_close refuses it as {Closable.OPEN_LOOP_SENSOR_TOO_LATE.value}"
    )
  intervening = tuple(step.op for step in protocol.steps[measured_index + 1 : corrects_index])
  count = len(intervening)
  # Counted off throughput rather than asserted. "Nothing here has ever been timed" is a
  # claim about a sibling's data, it is false about this package as a whole -- one duration
  # in DURATIONS is MEASURED -- and a claim of that shape printed into a string a reader is
  # shown is exactly the kind this repo refuses. So the sentence carries the count for the
  # protocol in front of it, and stops saying this the day somebody times the flow.
  untimed = tuple(step.op for step in protocol.steps if not duration_for(step.op).known)
  timing = (
    f"{len(untimed)} of {len(protocol.steps)} steps in this protocol have never been timed, "
    "so nothing here converts plates into seconds; throughput refuses the same conversion "
    "over the same steps"
    if untimed
    else "every step in this protocol has a measured duration; ask throughput for seconds"
  )
  if count == 0:
    meaning = (
      f"the correction lands at '{loop.corrects}', the step immediately after the "
      f"measurement. Nothing is committed in between, so every plate this loop measures is a "
      f"plate it can still steer. This is the tightest loop the protocol admits. {timing}"
    )
  else:
    meaning = (
      f"{count} step position(s) sit between '{protocol.steps[measured_index].op}' and "
      f"'{loop.corrects}': {', '.join(intervening)}. On a line running full that is {count} "
      f"plate(s) already past the sensor and not yet at the correction point; each was "
      f"admitted before this measurement existed and reaches '{loop.corrects}' under the "
      f"setting the correction is about to change. No controller helps them. {timing}"
    )
  return InFlight(loop=loop, steps_between=count, intervening=intervening, meaning=meaning)


# -- the loops this lab would want, costed --------------------------------------
# Written as a lab would actually propose them, which is why most of them fail. Each names a
# real quantity in the reference protocols and a real step it would change.

LIBRARY_CONCENTRATION = envelope_from_criterion(
  GATES["library_quant_before_flow_cell"], "library_present"
)
LIBRARY_PURITY = envelope_from_criterion(
  GATES["library_quant_before_flow_cell"], "not_protein_contaminated"
)
SORT_OCCUPANCY = envelope_from_criterion(
  GATES["sort_occupancy_before_amplification"], "enough_wells_occupied"
)


LOOPS: Dict[str, Loop] = {}


def _register(registry: Dict[str, Loop], loop: Loop) -> None:
  """Add a loop to a registry, refusing a name that is already taken.

  A bare assignment into the dict makes a duplicate name a silent replacement, and the
  replacement deletes a finding without a word: register a benign loop under the name of
  this repo's flagship open loop and `structurally_open()` quietly loses a row while
  `PROTOCOL_LOOPS` goes on listing the name once, so nothing anywhere reveals the swap.
  `_index_of` refuses a duplicated step op loudly for exactly this reason; the registry that
  feeds it has to do the same.
  """
  if loop.name in registry:
    raise ValueError(
      f"a loop named '{loop.name}' is already registered, measuring '{registry[loop.name].quantity}' "
      f"at '{registry[loop.name].measured_at}'. A second registration replaces the first "
      "silently and deletes whatever the first one reported; rename one of them"
    )
  registry[loop.name] = loop


for _loop in (
  Loop(
    name="pooled_quant_steers_pooling",
    quantity="library_conc_od",
    measured_at="read_absorbance",
    corrects="library_pool",
    correction=Correction.RETUNE,
    applied_by=Controller.CODED,
    envelope=LIBRARY_CONCENTRATION,
    note=(
      "the loop everybody draws first and the clearest open loop in this repo. Normalizing a "
      "pool is exactly what a concentration measurement is for, and this protocol measures "
      "after the pool, so the number describes material whose composition is already fixed. "
      "The order is what is wrong, not the reader: repairing the Tecan leaves this open, and "
      "quantifying per well before pooling closes it with no decode at all"
    ),
  ),
  Loop(
    name="quant_steers_flow_cell_loading",
    quantity="library_conc_od",
    measured_at="read_absorbance",
    corrects="upload_manifest",
    correction=Correction.RETUNE,
    applied_by=Controller.CODED,
    envelope=LIBRARY_CONCENTRATION,
    note=(
      "structurally sound and the one worth fixing: the quant genuinely does precede the "
      "manifest, so a working reader would close it. What it steers toward is another "
      "matter, and qc already reports it -- A260 at picogram input is precise and about the "
      "wrong thing, so a closed loop here would confidently load an empty library"
    ),
  ),
  Loop(
    name="purity_steers_flow_cell_loading",
    quantity="library_purity_260_280",
    measured_at="read_absorbance",
    corrects="set_run_parameters",
    correction=Correction.HOLD,
    applied_by=Controller.MODEL,
    envelope=LIBRARY_PURITY,
    note=(
      "the weakest correction in the set and the only one a model may make alone, because "
      "stopping before a flow cell is committed spends nothing but time. It still does not "
      "close, and for a reason that has nothing to do with the model"
    ),
  ),
  Loop(
    name="occupancy_steers_amplification",
    quantity="well_occupancy",
    measured_at="start_sort",
    corrects="wgs_prep_lysis",
    correction=Correction.DIVERT,
    applied_by=Controller.MODEL_PROPOSES,
    envelope=SORT_OCCUPANCY,
    note=(
      "the loop with the best shape in this repo -- the sort is genuinely upstream of the "
      "amplification, and skipping empty wells is worth a reagent set. It fails twice, and "
      "the two failures are bought separately: the dispenser's command set is undecoded, and "
      "routing material past a step is not something a drafting model should do unratified"
    ),
  ),
  Loop(
    name="yield_steers_resequencing",
    quantity="run_yield_pf",
    measured_at="watch_run_folder",
    corrects="start_run",
    correction=Correction.REPEAT,
    applied_by=Controller.MODEL_PROPOSES,
    envelope=Envelope.for_quantity(
      quantity="run_yield_pf",
      lower=1.0,
      basis=Basis.INTUITION,
      note=(
        "a floor on usefulness rather than a specification. The BOUND is deliberately not "
        "resolved from a qc criterion, because no gate in this repo reads run yield -- and an "
        "envelope with no gate behind it is exactly the kind that never gets revised. The "
        "units are qc's regardless: qc declares run_yield_pf whether or not anything gates "
        "on it, and typing 'Gbp' here would be a second copy that outlives the first"
      ),
    ),
    note=(
      "what a lab means when it says the system learns from its runs. It is real and it is "
      "useful and it is not control: the yield is read off a run that is already finished, "
      "so the flow cell it would have saved is spent. Reporting it as a closed loop is how a "
      "next-run adjustment gets budgeted as a safeguard"
    ),
  ),
  Loop(
    name="evaporation_steers_injection",
    quantity="residual_solvent_mass",
    measured_at="get_status",
    corrects="set_injection",
    correction=Correction.RETUNE,
    applied_by=Controller.CODED,
    envelope=None,
    note=(
      "the chemistry loop, and the one that shows what a missing envelope actually looks "
      "like. Its ORDER is fine and that is the only leg of it that is. What is absent is a "
      "target: qc declares no gate at all for this protocol, because nothing reads the "
      "chromatogram back, so there is no number in this repo that says what a good dry-down "
      "is. Its sensor is absent too, which the module now says out loud -- get_status polls "
      "the V-10 until the method finishes and produces no artifact, so the residual mass it "
      "steers on is not a number this protocol yields either. A loop here would run, act, "
      "and have no way to be wrong"
    ),
  ),
):
  _register(LOOPS, _loop)


# Keyed by protocol so a protocol with no declared loops is visibly unlooped rather than
# silently so, matching how qc keys its gates.
PROTOCOL_LOOPS: Dict[str, Tuple[str, ...]] = {
  "single_cell_genomics": (
    "occupancy_steers_amplification",
    "pooled_quant_steers_pooling",
    "quant_steers_flow_cell_loading",
    "purity_steers_flow_cell_loading",
    "yield_steers_resequencing",
  ),
  "small_molecule_qc": ("evaporation_steers_injection",),
}


# A name listed twice, or listed and never registered, is the same silent deletion the
# registry guard refuses one level down: the report would cost one loop twice, or fail on a
# lookup at report time rather than here where the mistake is.
for _protocol_name, _names in PROTOCOL_LOOPS.items():
  if len(set(_names)) != len(_names):
    raise ValueError(
      f"protocol '{_protocol_name}' lists a loop name more than once: {list(_names)}; the "
      "same loop costed twice reads as two findings"
    )
  for _name in _names:
    if _name not in LOOPS:
      raise ValueError(
        f"protocol '{_protocol_name}' lists loop '{_name}', which is not registered"
      )


@dataclass
class FeedbackReport:
  """Every declared loop on a protocol, costed against a real workcell."""

  protocol: str
  rows: List[Closure]

  def closable(self) -> List[Closure]:
    return [r for r in self.rows if r.closes]

  def refused(self) -> List[Closure]:
    return [r for r in self.rows if not r.closes]

  def structurally_open(self) -> List[Closure]:
    """Loops whose sensor is not upstream of their actuator.

    Reported on its own because it is the group whose fix is a protocol change. Every other
    refusal in this module is bought with work; this one is bought with a redesign, and
    folding them together would put both budgets behind one number.
    """
    return [r for r in self.rows if r.verdict.structural]

  def by_reason(self) -> Dict[str, List[Closure]]:
    """Rows grouped by their HEADLINE refusal, which is one refusal per loop.

    Reads the same way `counts()` does and carries the same caveat: a loop refused three
    ways appears once, under the first. `blocker_counts()` is the view over everything a
    loop earned.
    """
    out: Dict[str, List[Closure]] = {}
    for row in self.rows:
      out.setdefault(row.verdict.value, []).append(row)
    return out

  def unvalidated_envelopes(self) -> List[Closure]:
    """Loops not steering toward a band this lab has earned with its own data.

    A caveat and not a refusal, deliberately. A loop around a vendor or intuition threshold
    genuinely closes -- it drives the quantity into that band, reliably, whether or not the
    band is the right one. Making it a refusal would say the fix is the same as for a loop
    with no target at all, and it is not: this one needs a titration, not a threshold.

    A loop with NO envelope is in this list too, and the reason is the failure mode this
    package hunts. Filtering on `envelope is not None` meant a loop that declared nothing
    was not merely unflagged, it was counted among the clean ones -- so deleting the field
    the metric is about improved the metric, and a lab looked better taught about its own
    thresholds for having said less. No basis at all is strictly worse than a vendor basis,
    never better. `envelopes_by_state()` keeps the two apart for a reader who needs them
    apart.
    """
    return [
      r for r in self.rows if r.loop.envelope is None or not r.loop.envelope.validated
    ]

  def envelopes_by_state(self) -> Dict[str, List[Closure]]:
    """Every row partitioned three ways: validated band, unvalidated band, no band at all.

    Three states and not two, so an absent envelope can never be summarised as a validated
    one by a caller counting whatever is left over. Each needs different work: nothing, a
    titration, and an experiment plus a stated basis.
    """
    out: Dict[str, List[Closure]] = {"validated": [], "unvalidated": [], "absent": []}
    for row in self.rows:
      if row.loop.envelope is None:
        out["absent"].append(row)
      elif row.loop.envelope.validated:
        out["validated"].append(row)
      else:
        out["unvalidated"].append(row)
    return out

  def loops_on_an_inappropriate_measurement(self) -> List[Closure]:
    """Loops steering on a number qc says is the wrong assay for this sample.

    The analogue of `qc.GateReport.inappropriate`, and it is here because a reader of this
    module alone would otherwise see CLOSES and nothing else. The two failures are opposites
    in how they present: an unavailable measurement fails loudly, because no number arrives,
    while this one arrives, compares cleanly, and closes the loop around a quantity that is
    confidently about something else. Beside the verdict rather than inside it, because the
    loop does close -- it drives the number into the band every time -- and the fix is a
    different assay rather than a different loop.
    """
    return [r for r in self.rows if r.on_an_inappropriate_measurement() is not None]

  def corrections_nobody_can_apply(self) -> List[Closure]:
    """Loops whose correction lands on a step nothing declared can actually perform.

    Kept out of the verdict on purpose, the same way qc keeps a wrong-assay gate out of
    readiness. Whether a step can be performed is the ledger's question and it is already
    answered there; re-deciding it inside a closure verdict would put an execution problem
    and a control problem behind one word.

    The carve-out for a human controller is exactly as wide as the argument for it and no
    wider. That argument is about MANUAL: a manual step is one a person does at the bench,
    so a person applying the correction there is a real closed loop, just a slow one. It
    says nothing about BLOCKED, BROKEN or WRITTEN, which are a step whose command set is
    undecoded, a script that fails on the instrument, and a script that has never been run
    on it. No bench scientist ratifies any of those away by being named in a declaration.
    Skipping every HUMAN row made `applied_by` an author-settable field that emptied this
    whole report -- one word in a declaration, and five stranded corrections became none --
    which is the override this module is supposed to make impossible.
    """
    return [
      r for r in self.rows if not _correction_can_land(r.loop.applied_by, r.corrects_verdict)
    ]

  def counts(self) -> Dict[str, int]:
    """HEADLINE tally: one refusal per loop, the one it is reported under.

    Named here rather than left to be inferred, because this is the number a lab budgets
    from and it is not the number of problems. A loop refused for its sensor AND its
    authority is counted once, under the sensor, and this tally shows a zero next to the
    authority problem it has. `blocker_counts()` is the other view, and the module's promise
    that every refusal is carried is kept there.
    """
    out = {reason.value: 0 for reason in Closable}
    for row in self.rows:
      out[row.verdict.value] += 1
    out["total"] = len(self.rows)
    return out

  def blocker_counts(self) -> Dict[str, int]:
    """Every refusal every loop earned, tallied in reporting order.

    The tally that keeps this module's own promise. `counts()` reports headlines, and on the
    genomics protocol it says zero unpermitted corrections while a loop is sitting there
    with one -- so a lab reading it concludes there is no authority problem and budgets only
    the decode, which is the sequential rediscovery this module exists to prevent. Sums to
    more than the row count whenever a loop is broken more than one way, and that is the
    information: the gap between this and `counts()` is how much is hiding behind headlines.
    """
    out = {reason.value: 0 for reason in _REFUSAL_ORDER}
    for row in self.rows:
      for blocker in row.blockers:
        out[blocker.reason.value] += 1
    return out

  def unlooped(self) -> bool:
    """True when nobody has declared a loop for this protocol at all.

    An empty report and a spotless report are otherwise the same object, and of the two the
    empty one is worse: a protocol with no declared loop is open-loop by construction,
    however automated it is, and every accessor here reports perfection over zero rows.
    Resolved from PROTOCOL_LOOPS, which is the thing that would be missing.
    """
    return not PROTOCOL_LOOPS.get(self.protocol, ())

  def closes_any(self) -> bool:
    """True only if at least one declared loop actually closes.

    Not `all`. A lab does not need every proposed loop to close, and a report that demanded
    it would flatten the interesting result -- which is which loops close and which do not.
    """
    return bool(self.closable())


def feedback_report(protocol, ledger) -> FeedbackReport:
  """Cost every loop declared for a protocol against the ledger built for it.

  The ledger is checked against the protocol HERE, before the loop list is consulted, and
  not only inside `can_close`. A protocol nobody has declared a loop for produces no rows,
  so `can_close` is never reached, so the mismatch guard never runs -- and a caller who
  handed in a ledger built for something else got a spotless report out of a check that
  would have refused every row it was given. A guard reachable only when there is something
  to guard is not a guard.
  """
  _refuse_mismatched_ledger(protocol, ledger)
  names = PROTOCOL_LOOPS.get(protocol.name, ())
  return FeedbackReport(
    protocol=protocol.name,
    rows=[can_close(LOOPS[name], protocol, ledger) for name in names],
  )


def loops_for(protocol_name: str) -> Tuple[Loop, ...]:
  return tuple(LOOPS[name] for name in PROTOCOL_LOOPS.get(protocol_name, ()))


def ungated_protocols() -> Tuple[str, ...]:
  """Protocols with declared loops and no qc gates behind them.

  Resolved from qc rather than restated, so it empties itself the day somebody writes a gate
  for the chemistry flow. A protocol in this list cannot supply an envelope to any loop over
  it, which is why its loops refuse with NO_ENVELOPE rather than with anything instrumental.
  """
  return tuple(
    name for name in PROTOCOL_LOOPS if not PROTOCOL_GATES.get(name, ())
  )


__all__ = [
  "Blocker",
  "Closable",
  "Closure",
  "Controller",
  "Correction",
  "Envelope",
  "FeedbackReport",
  "InFlight",
  "LOOPS",
  "Loop",
  "NOT_MODELLED",
  "PROTOCOL_LOOPS",
  "can_close",
  "envelope_from_criterion",
  "feedback_report",
  "inappropriate_measurement",
  "in_flight_exposure",
  "loops_for",
  "ungated_protocols",
]
