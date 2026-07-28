"""Whether a loop that claims to correct itself can actually close, and where it opens.

Every other layer in this package plans a run or costs one. None of them models the run
ADJUSTING ITSELF, which is the thing the phrase "self-driving lab" is actually about. A
closed loop is three operations -- measure, compare, act -- and in a laboratory each one has
its own specific way of being fake:

  MEASURE   the number arrives after the material it describes has already been consumed.
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

The other two refusals are separate on purpose and are never collapsed into the first,
because each one is bought with different work. NO_ENVELOPE means nothing in this repo says
what good is for that quantity, so there is no target to steer toward and the loop is
underspecified rather than late; the fix is a threshold with a basis, which costs an
experiment. UNAVAILABLE_MEASUREMENT is resolved from the ledger -- the step the number comes
from is blocked, manual, or broken -- and the fix is a decode, a debug, or a person. And
UNPERMITTED_CORRECTION means the loop declares a controller weaker than the correction
requires, which is settled by a decision rather than by money. Reporting one number over
four different budgets is the failure this whole package exists to refuse.

The refusals are ordered so the headline is the one a reader must not be sent away from. A
lab told "the measurement is unavailable" will go buy an instrument, and if the loop is also
structurally open that instrument buys nothing at all. So the structural refusal is reported
first and the fixable ones after it, and every refusal a loop earns is carried, not just the
first, so nobody discovers the next one only after paying for the last.

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

Two scoping notes, because a verdict read wider than it was computed is worse than no
verdict. CLOSES is a claim about the LOOP -- its order, its target, its measurement, and its
authority. It is not a claim that the step being corrected runs at all; the ledger owns that
question, and `corrections_nobody_can_apply` reports it beside the verdict rather than inside
it, the same way qc keeps a wrong-assay gate separate from an unsatisfiable one. And the
envelope a loop steers toward is resolved from the qc criterion that already owns the number,
never restated here: two copies of one cutoff eventually disagree, and a loop steering toward
the retired copy would look exactly like a loop steering toward the live one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .model import Verdict
from .qc import GATES, MEASUREMENTS, PROTOCOL_GATES, Basis, Comparison, Criterion, Gate

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

  This names the same distinction the authority layer draws over decision classes, and it is
  restated rather than imported on purpose -- a loop's controller is a property of the loop,
  the ordering here is short enough to read in one screen, and this module has to be
  checkable on its own. If the two are ever wired together, the authority layer owns the
  requirement and this resolves from it rather than keeping a second copy.
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

  The four refusals are listed in the order they are reported, and that order is the line
  this enum draws. OPEN_LOOP_SENSOR_TOO_LATE is first because it is the only one no
  purchase, decode, or policy change repairs: the protocol has to be rewritten so the
  measurement happens before the thing it steers. Reporting a cheaper reason ahead of it
  sends a lab to buy an instrument for a loop that could never have closed.
  """

  OPEN_LOOP_SENSOR_TOO_LATE = "open_loop_sensor_too_late"  # measured at or after the correction point
  NO_ENVELOPE = "no_envelope"  # nothing declares what good is; there is nothing to steer toward
  UNAVAILABLE_MEASUREMENT = "unavailable_measurement"  # the measuring step does not produce a number here
  UNPERMITTED_CORRECTION = "unpermitted_correction"  # the controller is weaker than the correction needs
  CLOSES = "closes"

  @property
  def closed(self) -> bool:
    return self is Closable.CLOSES

  @property
  def structural(self) -> bool:
    """True only for the refusal that money cannot move.

    The other three name work a lab can buy, schedule, or decide. This one names an ordering
    in the protocol, and the only thing that changes it is measuring somewhere else.
    """
    return self is Closable.OPEN_LOOP_SENSOR_TOO_LATE


# Reported in this order. CLOSES is not in it: it is what is left when nothing else applies.
_REFUSAL_ORDER: Tuple[Closable, ...] = (
  Closable.OPEN_LOOP_SENSOR_TOO_LATE,
  Closable.NO_ENVELOPE,
  Closable.UNAVAILABLE_MEASUREMENT,
  Closable.UNPERMITTED_CORRECTION,
)


# Which verdicts mean a number actually arrives from a step. Identical to the partition
# qc.Readiness draws over the same verdicts, and taken here off the ledger row the ledger
# already computed rather than by costing the step a second time. A step that is blocked,
# manual, written, or broken produces nothing to compare against, and a loop reading one is
# steering on a value nobody will ever hand it.
_MEASUREMENT_ARRIVES: Tuple[Verdict, ...] = (Verdict.AUTOMATED, Verdict.SUPERVISED)


@dataclass(frozen=True)
class Envelope:
  """The band a correction steers the measured quantity back into.

  An envelope with no bound on either side is refused at construction. That is the vacuous
  case and it is the dangerous one: an unbounded band contains every value, so a loop built
  on it reports itself in specification forever, corrects nothing, and looks exactly like a
  loop that is working. Absence of a bound is not a wide bound.

  `basis` comes from the qc criterion this was resolved from and is carried rather than
  checked. An envelope resting on intuition is still an envelope and the loop can still
  close around it -- what it cannot do is pass unreported, so `unvalidated_envelopes()`
  lists it.
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
    if self.lower is not None and self.upper is not None and self.upper < self.lower:
      raise ValueError(
        f"envelope for '{self.quantity}' has upper {self.upper} below lower {self.lower}"
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
  """
  match: Optional[Criterion] = next((c for c in gate.criteria if c.name == criterion_name), None)
  if match is None:
    raise KeyError(
      f"gate '{gate.name}' declares no criterion '{criterion_name}'; "
      f"it has: {[c.name for c in gate.criteria]}"
    )
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
    return (
      f"'{self.loop.quantity}' is measured at '{self.loop.measured_at}', which is upstream of "
      f"'{self.loop.corrects}'; it steers toward {self.loop.steers_toward()}, the number "
      f"arrives, and {self.loop.applied_by.value} may make a {self.loop.correction.value}"
    )

  def all_reasons(self) -> Tuple[str, ...]:
    return tuple(b.detail for b in self.blockers)

  def refusals(self) -> Tuple[Closable, ...]:
    return tuple(b.reason for b in self.blockers)


@dataclass(frozen=True)
class InFlight:
  """How much material is committed between a loop's sensor and its actuator.

  Counted in steps and reported in plates, never in seconds. Seconds would need step
  durations, and `throughput` already refuses to return a plates-per-day figure because no
  step in this repo has ever been timed. The same emptiness would sit under any reaction
  time reported here, so this reports the thing the protocol actually knows.
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


def can_close(loop: Loop, protocol, ledger) -> Closure:
  """Can this loop actually close against this protocol and this workcell?

  Step ordering is resolved from the protocol and measurement availability from the ledger.
  Neither is re-derived: the protocol owns the order the bench runs in, the ledger owns
  whether a step produces anything, and a second computation of either would eventually
  disagree with the first with nothing to say which was right.

  Every check runs. The function does not return early on the first refusal, because a loop
  broken three ways that reported one way would be fixed one way and still be broken.
  """
  if ledger.protocol.name != protocol.name:
    raise ValueError(
      f"ledger was built for protocol '{ledger.protocol.name}' but the loop is being costed "
      f"against '{protocol.name}'; a verdict mixed from two protocols describes neither"
    )

  measured_index = _index_of(protocol, loop.measured_at, "measured_at")
  corrects_index = _index_of(protocol, loop.corrects, "corrects")
  blockers: List[Blocker] = []

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
  measuring_row = ledger.rows[measured_index]
  if measuring_row.verdict not in _MEASUREMENT_ARRIVES:
    blockers.append(
      Blocker(
        Closable.UNAVAILABLE_MEASUREMENT,
        f"'{loop.quantity}' comes from '{loop.measured_at}', which this workcell costs as "
        f"{measuring_row.verdict.value}: {measuring_row.reason}. A loop over a number nobody "
        "produces is an open loop that reports no error, because the comparison never runs",
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
  """
  measured_index = _index_of(protocol, loop.measured_at, "measured_at")
  corrects_index = _index_of(protocol, loop.corrects, "corrects")
  if measured_index >= corrects_index:
    raise ValueError(
      f"loop '{loop.name}' measures at or after the step it corrects, so no material is in "
      f"flight between them -- the correction never reaches this run's material at all. "
      f"can_close refuses it as {Closable.OPEN_LOOP_SENSOR_TOO_LATE.value}"
    )
  intervening = tuple(step.op for step in protocol.steps[measured_index + 1 : corrects_index])
  count = len(intervening)
  if count == 0:
    meaning = (
      f"the correction lands at '{loop.corrects}', the step immediately after the "
      f"measurement. Nothing is committed in between, so every plate this loop measures is a "
      "plate it can still steer. This is the tightest loop the protocol admits"
    )
  else:
    meaning = (
      f"{count} step position(s) sit between '{loop.measured_at}' and '{loop.corrects}': "
      f"{', '.join(intervening)}. On a line running full that is {count} plate(s) already "
      f"past the sensor and not yet at the correction point; each was admitted before this "
      f"measurement existed and reaches '{loop.corrects}' under the setting the correction "
      "is about to change. No controller helps them. Nothing here converts that into "
      "seconds: no step in this package has ever been timed, and throughput refuses the same "
      "conversion for the same reason"
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
    envelope=Envelope(
      quantity="run_yield_pf",
      units="Gbp",
      lower=1.0,
      basis=Basis.INTUITION,
      note=(
        "a floor on usefulness rather than a specification. Deliberately not resolved from a "
        "qc criterion, because no gate in this repo reads run yield -- and an envelope with "
        "no gate behind it is exactly the kind that never gets revised"
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
      "like. Its order is fine. What is absent is a target: qc declares no gate at all for "
      "this protocol, because nothing reads the chromatogram back, so there is no number in "
      "this repo that says what a good dry-down is. A loop here would run, act, and have no "
      "way to be wrong"
    ),
  ),
):
  LOOPS[_loop.name] = _loop


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
    out: Dict[str, List[Closure]] = {}
    for row in self.rows:
      out.setdefault(row.verdict.value, []).append(row)
    return out

  def unvalidated_envelopes(self) -> List[Closure]:
    """Loops steering toward a band this lab has not earned with its own data.

    A caveat and not a refusal, deliberately. A loop around a vendor or intuition threshold
    genuinely closes -- it drives the quantity into that band, reliably, whether or not the
    band is the right one. Making it a fifth refusal would say the fix is the same as for a
    loop with no target at all, and it is not: this one needs a titration, not a threshold.
    """
    return [
      r for r in self.rows if r.loop.envelope is not None and not r.loop.envelope.validated
    ]

  def corrections_nobody_can_apply(self) -> List[Closure]:
    """Loops whose correction lands on a step no code path reaches, with no human declared.

    Kept out of the verdict on purpose, the same way qc keeps a wrong-assay gate out of
    readiness. Whether a step can be performed is the ledger's question and it is already
    answered there; re-deciding it inside a closure verdict would put an execution problem
    and a control problem behind one word. A human-applied correction at a manual step is a
    perfectly good closed loop, just a slow one, so only a declared machine controller
    counts here.
    """
    return [
      r
      for r in self.rows
      if r.loop.applied_by is not Controller.HUMAN
      and r.corrects_verdict not in _MEASUREMENT_ARRIVES
    ]

  def counts(self) -> Dict[str, int]:
    out = {reason.value: 0 for reason in Closable}
    for row in self.rows:
      out[row.verdict.value] += 1
    out["total"] = len(self.rows)
    return out

  def closes_any(self) -> bool:
    """True only if at least one declared loop actually closes.

    Not `all`. A lab does not need every proposed loop to close, and a report that demanded
    it would flatten the interesting result -- which is which loops close and which do not.
    """
    return bool(self.closable())


def feedback_report(protocol, ledger) -> FeedbackReport:
  """Cost every loop declared for a protocol against the ledger built for it."""
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
  "in_flight_exposure",
  "loops_for",
  "ungated_protocols",
]
