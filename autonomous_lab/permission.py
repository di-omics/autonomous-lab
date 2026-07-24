"""Proposal and permission: anything may ask, only the gates decide.

This is the seam the whole package is built around. An agent, a scheduler, a controller, or
a person proposes an action. Nothing about proposing it makes it allowed. A deterministic
function then asks whether the physical state and the scientific evidence justify doing it,
and writes the question, the answer, and the reasoning to the run record.

Keeping those two things in separate types is the point, and it is a design choice with a
specific failure in mind. If a model can reach the thing that decides, then given enough
attempts it will find the phrasing that gets a yes, and the safety property becomes a
property of the prompt rather than of the lab. Here, `decide` reads a `Request` and returns
a `Decision`. There is no argument that makes it more permissive, no confidence score that
buys leniency, and nothing a proposer can put in a request that changes the rules applied
to it. The most persuasive possible proposal for running a step whose command is undecoded
gets the same refusal as the least.

A decision combines three independent questions, and all three are evaluated even when the
first one already refuses:

  Capability -- can this step physically run? The ledger's verdict, unchanged.
  Acceptance -- do the criteria guarding this step clear on the evidence available?
  Provenance -- is the material traceable enough for the result to mean anything?

They are evaluated together rather than short-circuited because a person who gets one
reason fixes one thing and comes back. A refusal that names every blocker at once is the
difference between three round trips to the bench and one.

Refusals are first-class artifacts. A refused request produces a record entry asserting
that nothing was sent, plus a card naming the specific next action that would change the
answer. That is the part that is actually useful to a working scientist: not that the
system said no, but that it said what to do about it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Sequence, Tuple

from .acceptance import Gate, GateResult, Judgement, Measurement
from .criteria import gates_for
from .executor import gap_closer
from .ledger import cost_step
from .model import Step, Verdict
from .record import RunRecord
from .samples import Attribution, Lineage, Witness
from .workcell import Workcell


class Grant(str, Enum):
  """What a decision permits."""

  GRANTED = "granted"  # may run unattended
  SUPERVISED = "supervised"  # may run with a human present and a confirm token typed
  REFUSED = "refused"  # may not run

  @property
  def may_run(self) -> bool:
    return self is not Grant.REFUSED


@dataclass(frozen=True)
class Request:
  """Somebody asking to do something. Carries no authority whatsoever.

  `proposer` is recorded but never consulted. It is there so the record says who asked,
  which matters for an audit and matters not at all for the decision.
  """

  step: Step
  proposer: str = "unknown"
  measurements: Tuple[Measurement, ...] = ()
  sample: Optional[str] = None
  note: str = ""


@dataclass(frozen=True)
class Decision:
  """The answer, and everything needed to argue with it or act on it."""

  request: Request
  grant: Grant
  capability: Verdict
  reasons: Tuple[str, ...]
  gates: Tuple[GateResult, ...]
  next_actions: Tuple[str, ...]
  confirm_token: Optional[str] = None

  @property
  def refused(self) -> bool:
    return self.grant is Grant.REFUSED

  def render(self) -> str:
    lines = [
      f"{self.grant.value.upper()}: {self.request.step.summary}",
      f"  instrument   {self.request.step.instrument}",
      f"  capability   {self.capability.value}",
      f"  proposed by  {self.request.proposer}  (recorded, not consulted)",
    ]
    for r in self.reasons:
      lines.append(f"  - {r}")
    for g in self.gates:
      lines.append(f"  gate {g.gate}: {g.judgement.value.upper()}  {g.reason}")
    if self.confirm_token:
      lines.append(f"  confirm      an operator must type {self.confirm_token}")
    if self.next_actions:
      lines.append("  what would change this answer:")
      for a in self.next_actions:
        lines.append(f"    * {a}")
    return "\n".join(lines)


def decide(
  request: Request,
  wc: Optional[Workcell] = None,
  lineage: Optional[Lineage] = None,
  gates: Optional[Sequence[Gate]] = None,
  record: Optional[RunRecord] = None,
) -> Decision:
  """Decide one request. Deterministic, and the only thing in the package that grants.

  Pass a `record` and the proposal, the decision, and the reasoning are appended to it. A
  refusal writes an entry asserting `commands_issued: 0`, so the record distinguishes
  "this never ran" from "this is missing", which are otherwise the same absence.
  """
  wc = wc or Workcell.default()
  step = request.step
  reasons: List[str] = []
  next_actions: List[str] = []

  if record is not None:
    record.append(
      "proposed",
      step=step.op,
      instrument=step.instrument,
      proposer=request.proposer,
      summary=step.summary,
    )

  # -- capability ------------------------------------------------------------
  row = cost_step(step, wc)
  capability = row.verdict
  reasons.append(f"capability: {row.reason}")
  confirm_token: Optional[str] = None

  if capability is Verdict.BLOCKED:
    closer = gap_closer(step.instrument)
    if closer:
      next_actions.append(f"unblock {step.instrument}: {closer}")
  elif capability is Verdict.BROKEN:
    next_actions.append(
      f"debug the failing run card for '{step.op}'; it exists and fails on the instrument, "
      "so this is a defect to fix rather than work to write"
    )
  elif capability is Verdict.WRITTEN:
    next_actions.append(
      f"run the existing '{step.op}' run card wet under supervision; the script is written "
      "and dry-validated, and what it lacks is a real run"
    )
  elif capability is Verdict.MANUAL:
    next_actions.append(f"a human performs this at the bench: {step.summary}")
  elif capability is Verdict.SUPERVISED:
    for tok in ("confirm token ",):
      if tok in row.reason:
        confirm_token = row.reason.split(tok, 1)[1].split(",")[0].split(".")[0].strip()
    next_actions.append("an operator must be present at the E-stop for this step")

  # -- acceptance ------------------------------------------------------------
  guarding = list(gates) if gates is not None else gates_for(step.op)
  results: List[GateResult] = []
  for gate in guarding:
    gr = gate.evaluate(request.measurements, wc)
    results.append(gr)
    if gr.judgement is Judgement.UNMEASURABLE:
      reasons.append(f"gate '{gate.name}' cannot be evaluated: {gr.reason}")
      instrument, op = gate.produced_by
      # Two different problems wear the same verdict, and they need different work. Either
      # the bench cannot produce this number at all, which is engineering, or it can and
      # nobody supplied it, which is a missing input. Telling an operator to go fix a
      # working instrument would waste the trip.
      can_measure, _ = gate.measurable(wc)
      if can_measure:
        missing = [c.metric for c in gate.criteria if c.metric not in {m.metric for m in request.measurements}]
        next_actions.append(
          f"supply {', '.join(missing)} from the qualifying run on {instrument}; "
          f"'{op}' can produce these, this request just did not carry them"
        )
      else:
        next_actions.append(
          f"make '{op}' produce a number on {instrument}; until it does, this gate is not "
          "a check that passed, it is a check that never ran"
        )
    elif gr.judgement is Judgement.FAIL:
      reasons.append(f"gate '{gate.name}' failed: {gr.reason}")
      next_actions.append(f"the material does not meet '{gate.name}'; do not proceed with it")
    elif gr.judgement is Judgement.ESCALATE:
      reasons.append(f"gate '{gate.name}' cannot be called: {gr.reason}")
      unpinned = gate.blocking_criteria()
      if unpinned:
        next_actions.append(
          "pin these thresholds with the assay owner: "
          + ", ".join(f"{c.metric} ({c.origin.value})" for c in unpinned)
        )
      else:
        next_actions.append(
          f"get ground truth for '{gate.name}'; the interval straddles the threshold and "
          "the measurement is too uncertain to decide on"
        )
    else:
      reasons.append(f"gate '{gate.name}' passed: {gr.reason}")

  # -- provenance ------------------------------------------------------------
  if lineage is not None and request.sample is not None:
    summary = lineage.summary(request.sample)
    attr = Attribution(summary["attribution"])
    witness = Witness(summary["weakest_witness"])
    reasons.append(
      f"provenance: {request.sample} is {attr.value}, "
      f"{summary['indistinguishable']} indistinguishable contributor(s), "
      f"weakest attestation {witness.value}"
    )
    if attr is Attribution.CONFOUNDED:
      next_actions.append(
        f"record an index per input before pooling; after this point a bad result "
        f"implicates all {summary['indistinguishable']} contributors and cannot be narrowed"
      )

  # -- combine ---------------------------------------------------------------
  gate_blocked = any(g.judgement is not Judgement.PASS for g in results)
  if capability.headless and not gate_blocked:
    grant = Grant.GRANTED
  elif capability is Verdict.SUPERVISED and not gate_blocked:
    grant = Grant.SUPERVISED
  else:
    grant = Grant.REFUSED

  decision = Decision(
    request=request,
    grant=grant,
    capability=capability,
    reasons=tuple(reasons),
    gates=tuple(results),
    next_actions=tuple(dict.fromkeys(next_actions)),  # de-duplicate, keep order
    confirm_token=confirm_token,
  )

  if record is not None:
    record.append(
      "decided",
      step=step.op,
      grant=grant.value,
      capability=capability.value,
      gates={g.gate: g.judgement.value for g in results},
      reasons=list(decision.reasons),
    )
    if grant is Grant.REFUSED:
      # The refusal receipt. Asserting the negative explicitly is what lets a later reader
      # tell "refused, nothing sent" apart from "no record of this step", which look
      # identical if a refusal writes nothing.
      record.append(
        "refused",
        step=step.op,
        commands_issued=0,
        instrument_contacted=False,
        material_consumed=False,
        next_actions=list(decision.next_actions),
      )
  return decision


@dataclass
class Session:
  """One run: a workcell, a lineage, a record, and every decision made against them.

  The integration point. Everything the package knows is wired together here, so a caller
  gets capability, acceptance, provenance, and an auditable record from one object rather
  than assembling four.
  """

  workcell: Workcell = field(default_factory=Workcell.default)
  lineage: Optional[Lineage] = None
  record: RunRecord = field(default_factory=lambda: RunRecord("session"))
  decisions: List[Decision] = field(default_factory=list)

  def request(self, step: Step, proposer: str = "unknown", **kw) -> Decision:
    req = Request(step=step, proposer=proposer, **kw)
    d = decide(req, self.workcell, self.lineage, record=self.record)
    self.decisions.append(d)
    return d

  def granted(self) -> List[Decision]:
    return [d for d in self.decisions if not d.refused]

  def refused(self) -> List[Decision]:
    return [d for d in self.decisions if d.refused]

  def work_orders(self) -> List[str]:
    """Every distinct next action across all refusals, de-duplicated, in order.

    The output a working scientist actually wants: not a list of what failed, but the
    shortest list of things to change. Two refusals that need the same bench work should
    produce one line here, not two.
    """
    out: List[str] = []
    for d in self.refused():
      for a in d.next_actions:
        if a not in out:
          out.append(a)
    return out

  def render(self) -> str:
    lines = [
      f"session: {len(self.decisions)} request(s), "
      f"{len(self.granted())} granted, {len(self.refused())} refused",
      "",
    ]
    for d in self.decisions:
      lines.append(d.render())
      lines.append("")
    orders = self.work_orders()
    if orders:
      lines.append(f"work orders ({len(orders)} distinct):")
      for i, a in enumerate(orders, 1):
        lines.append(f"  {i}. {a}")
      lines.append("")
    lines.append(self.record.verify().render())
    return "\n".join(lines)
