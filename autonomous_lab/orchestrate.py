"""Running more than one plate: what serializes, where it stalls, and what an arm buys.

Every other layer in this package costs a SINGLE run. That is the right first question and
it is not the question a workcell asks. A workcell exists because one plate at a time
wastes the instruments, and the moment a second plate enters, a set of constraints appears
that a single-run report cannot see: two plates want the same liquid handler, a human is
needed at step four and it is 2am, and the plate that finished amplifying is sitting on a
deck nobody can clear.

This module computes that, and it computes it **without durations**, which is the part
worth being careful about. `throughput` already refuses to return plates-per-day because 18
of 18 steps have never been timed, and that refusal stands. But most of what a workcell
planner needs is structural rather than temporal:

  Which instrument is the serialization point? The one that appears in the most steps. That
  is true at any speed, so it needs no stopwatch. Buying a second one is the only thing that
  changes it, and knowing which one to buy is worth more than a cycle time.

  How many plates can be in flight unattended? Bounded by how far an unattended run gets at
  all -- which the ledger already computes -- and then by how many distinct instruments that
  prefix touches. A prefix of one step pipelines no plates no matter how fast it is.

  Where does the run stop, and on what? Five different constraints stop a run and they are
  fixed by five different budgets. Collapsing them into "blocked" is the same mistake as
  collapsing loop closure into one autonomy percentage.

The last computation is the one this repo did not have anywhere. `arm_relief()` asks what a
plate-moving arm would actually buy, and answers it by constraint class rather than by
enthusiasm. An arm removes HANDOFF stalls -- it carries the plate and reports the move, which
is the one thing that closes a custody gap. It removes none of the others. A lab that buys an
arm to fix a schedule stalling on undecoded commands has bought the wrong machine, and the
distinction is computable before the purchase order rather than after it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .model import Protocol, Verdict, ZeroDecodeOp


class Constraint(str, Enum):
  """Why a multi-plate run stops here. Each one is fixed by a different budget.

  Ordered by how early in a lab's life it usually bites. DECODE is reverse-engineering
  work, HANDOFF is a plate mover or a barcode, GATE is an instrument that returns a usable
  number, TRUST is a calibration experiment, and ATTENDED is the one no purchase fixes --
  a step a human must physically do, which caps overnight running at zero however fast
  everything else becomes.
  """

  DECODE = "decode"  # the command is undecoded; the step cannot run at all
  ATTENDED = "attended"  # a human must be at the bench for this step
  HANDOFF = "handoff"  # material must be carried between instruments, unobserved
  GATE = "gate"  # a QC gate sits here and cannot be evaluated
  TRUST = "trust"  # the operation has no met benchmark, so it is not trusted unattended

  @property
  def arm_fixes_it(self) -> bool:
    """Whether a plate-moving arm removes this stall.

    Only HANDOFF. An arm carries plates and reports the move; it does not decode a command
    set, does not make a broken reader return a number, and does not run a calibration.
    Stated as a property rather than left to the reader because "buy a robot" is the
    default answer to a stalling schedule and it is usually the wrong one.
    """
    return self is Constraint.HANDOFF


@dataclass(frozen=True)
class Stall:
  """One point where a multi-plate run stops, and what specifically clears it."""

  step_op: str
  instrument: str
  constraint: Constraint
  detail: str
  clears_it: str

  @property
  def arm_fixes_it(self) -> bool:
    return self.constraint.arm_fixes_it


@dataclass(frozen=True)
class Contention:
  """One instrument and how much of the protocol it owns.

  `steps` is the count of protocol steps that run on this instrument. Under the
  one-process-per-instrument rule those steps serialize across every plate in flight, so
  the instrument with the highest count is the structural bottleneck at any plate count and
  at any speed. This is the number that survives having no timing data.
  """

  instrument: str
  steps: int
  share: float  # fraction of the protocol's steps

  def serialized_slots(self, plates: int) -> int:
    """How many times this instrument must be used to push `plates` plates through.

    A lower bound on the schedule that needs no durations: the busiest instrument cannot
    do better than this many sequential operations, whatever the others do.
    """
    return self.steps * plates


@dataclass
class Schedule:
  """What a workcell running this protocol would actually do, and where it would stop."""

  protocol: str
  plates: int
  stalls: List[Stall] = field(default_factory=list)
  contention: List[Contention] = field(default_factory=list)
  unattended_steps: int = 0
  pipeline_depth: int = 0

  @property
  def bottleneck(self) -> Optional[Contention]:
    return self.contention[0] if self.contention else None

  @property
  def runs_unattended(self) -> bool:
    return self.unattended_steps > 0 and not self.stalls

  def first_stall(self) -> Optional[Stall]:
    return self.stalls[0] if self.stalls else None

  def by_constraint(self) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for s in self.stalls:
      out[s.constraint.value] = out.get(s.constraint.value, 0) + 1
    return out

  def arm_relief(self) -> Tuple[List[Stall], List[Stall]]:
    """(stalls an arm removes, stalls it does not).

    The honest form of "should we buy a plate mover". An arm is the only thing that closes
    a custody gap, so where the second list dominates, the arm is not the next purchase --
    and the first stall in the second list names what is.
    """
    removed = [s for s in self.stalls if s.arm_fixes_it]
    remains = [s for s in self.stalls if not s.arm_fixes_it]
    return removed, remains

  def makespan(self) -> None:
    """Deliberately not implemented.

    A workcell schedule over untimed steps is a drawing, not a plan. `throughput` already
    refuses this for one plate and the refusal does not get weaker by adding plates: it gets
    stronger, because a pipelined estimate compounds every unmeasured duration in it. The
    structural results above are real without it, which is the whole design of this module.
    """
    return None

  def why_no_makespan(self) -> str:
    return (
      "no step in this protocol has a measured duration, so a cycle time over them would "
      "be a guess formatted as a specification. The serialization structure above holds "
      "without one"
    )


# Read-only operations: they enumerate a bus or open a socket and move nothing, so no
# robot benchmark stands between them and running unattended.
_ZERO_DECODE_OPS = {op.value for op in ZeroDecodeOp}
_COULD_RUN = (Verdict.AUTOMATED, Verdict.SUPERVISED)


def contention(protocol: Protocol) -> List[Contention]:
  """Instruments ranked by how much of the protocol they own, busiest first."""
  counts: Dict[str, int] = {}
  for step in protocol.steps:
    counts[step.instrument] = counts.get(step.instrument, 0) + 1
  total = len(protocol.steps) or 1
  rows = [Contention(instrument=k, steps=v, share=v / total) for k, v in counts.items()]
  return sorted(rows, key=lambda c: (-c.steps, c.instrument))


def _hop_targets(ledger) -> Dict[str, List[Tuple[str, str]]]:
  """Which steps receive material carried from another instrument, keyed by consumer."""
  out: Dict[str, List[Tuple[str, str]]] = {}
  producer: Dict[str, str] = {}
  physical = {a.name for a in ledger.protocol.artifacts if a.physical}
  for step in ledger.protocol.steps:
    for art in step.consumes:
      src = producer.get(art)
      if art in physical and src is not None and src != step.instrument:
        out.setdefault(step.op, []).append((art, src))
    for art in step.produces:
      producer[art] = step.instrument
  return out


def orchestrate(
  protocol: Protocol, ledger, gates=None, plates: int = 1, untrusted: Optional[List] = None
) -> Schedule:
  """Plan a multi-plate run: what serializes, where it stalls, on which constraint.

  Every stall is resolved from a layer that already computed it -- verdicts from the
  ledger, hops from `handoffs()`, gate readiness from `qc`, benchmarks from `intelligence`
  -- rather than recomputed here. A second computation of the same fact eventually
  disagrees with the first and nothing reveals which one is wrong.
  """
  sched = Schedule(protocol=protocol.name, plates=plates, contention=contention(protocol))

  hops = _hop_targets(ledger)
  unevaluable = set()
  if gates is not None:
    for row in gates.unsatisfiable():
      unevaluable.add((row.gate.after_step, row.gate.name, row.reason))
  untrusted_ops = {op for op, _reason in (untrusted or [])}

  reached = 0
  for row in ledger.rows:
    step = row.step
    stalls_here: List[Stall] = []

    if row.verdict in (Verdict.BLOCKED, Verdict.WRITTEN, Verdict.BROKEN):
      stalls_here.append(
        Stall(
          step_op=step.op,
          instrument=step.instrument,
          constraint=Constraint.DECODE,
          detail=f"verdict is {row.verdict.value}; the step does not run headlessly today",
          clears_it=(
            "debug the failure"
            if row.verdict is Verdict.BROKEN
            else "finish this instrument's map, or prove the run card on hardware"
          ),
        )
      )
    elif row.verdict is Verdict.MANUAL:
      stalls_here.append(
        Stall(
          step_op=step.op,
          instrument=step.instrument,
          constraint=Constraint.ATTENDED,
          detail=step.manual_reason or "a human performs this step at the bench",
          clears_it="an instrument or an arm that performs it, or accept attended-hours only",
        )
      )

    for artifact, src in hops.get(step.op, []):
      stalls_here.append(
        Stall(
          step_op=step.op,
          instrument=step.instrument,
          constraint=Constraint.HANDOFF,
          detail=f"'{artifact}' is carried from {src} to {step.instrument} by hand",
          clears_it="a plate mover that reports the move, or a barcode read at both ends",
        )
      )

    for after_step, name, reason in unevaluable:
      if after_step == step.op:
        stalls_here.append(
          Stall(
            step_op=step.op,
            instrument=step.instrument,
            constraint=Constraint.GATE,
            detail=f"gate '{name}' sits here and cannot be evaluated: {reason}",
            clears_it="an instrument that returns the measurement this gate reads",
          )
        )

    # TRUST only where it is the BINDING constraint: a step that could otherwise run, and
    # that actually actuates. Almost nothing here has a met benchmark, so applying it to
    # every step would bury the four constraints that differ from each other -- and a
    # socket probe or a bus enumeration moves nothing, so no robot benchmark gates it.
    actuates = step.op not in _ZERO_DECODE_OPS
    if step.op in untrusted_ops and actuates and row.verdict in _COULD_RUN:
      stalls_here.append(
        Stall(
          step_op=step.op,
          instrument=step.instrument,
          constraint=Constraint.TRUST,
          detail=(
            f"verdict is {row.verdict.value}, so the machine can do it -- but no benchmark "
            "has been met, so it is not trusted to do it unattended"
          ),
          clears_it="run the calibration experiment that retires its benchmark",
        )
      )

    if stalls_here and not sched.stalls:
      # The first stalling step is where an unattended run actually stops.
      sched.unattended_steps = reached
    sched.stalls.extend(stalls_here)
    if not stalls_here:
      reached += 1

  if not sched.stalls:
    sched.unattended_steps = reached
  prefix = [r.step.instrument for r in ledger.rows[: sched.unattended_steps]]
  sched.pipeline_depth = len(set(prefix))
  return sched
