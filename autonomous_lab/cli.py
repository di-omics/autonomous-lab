"""autonomous-lab command line.

Nothing here touches an instrument except the zero-decode reads: enumerating a USB bus,
probing a port, reading a run folder. `run --armed` performs those for real and stops at
the first step that needs a human. There is no flag that actuates anything; commands that
move an instrument live in plr-re, behind its own arming switches.

`ledger` and `gaps` exit non-zero while a protocol cannot run unattended, matching
`plr-re map coverage`, so they work as gates and not only as reports.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import List

from .doctor import (
  BUNDLED_ROOT,
  MANIFEST_PATH,
  check_federated,
  check_manifest,
  render as render_checks,
)
from .executor import Executor
from .intelligence import (
  BENCHMARKS,
  JUDGMENTS,
  knowledge_summary,
  loop_closure,
  untrusted_ops,
)
from .coverage import coverage_report, mandatory_gates
from .durability import entitlement_summary, untrusted_instruments
from .feedback import feedback_report
from .ledger import build_ledger, rank_unlocks
from .teaching import demonstration_queue, teaching_summary, transfer_report
from .lineage import MISASSIGNMENT, Separability, lineage_report
from .model import Verdict
from .provenance import provenance_report
from .qc import MEASUREMENTS, gate_report
from .recovery import recovery_report, visual_checks_that_would_help
from .registry import FEDERATED, registry
from .throughput import estimate as throughput_estimate
from .vision import VisionCapability, gaps as vision_gaps, summarize as vision_summary
from .workcell import Workcell
from . import protocols


def _log_setup():
  logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def _workcell(args) -> Workcell:
  wc = Workcell.from_json(args.workcell) if args.workcell else Workcell.default()
  if getattr(args, "plr_tested", None):
    wc.plr_tested_root = args.plr_tested
  return wc


def _stock(args) -> int:
  wc = _workcell(args)
  print(f"workcell: {wc.name}\n")
  print("reverse-engineered instruments (di-omics/plr-reverse-engineer):")
  for key, s in sorted(registry().items()):
    cov = wc.coverage(key)
    zero = ", ".join(op.value for op in s.zero_decode) or "none"
    cfg = wc.instruments.get(key)
    here = "" if (cfg and cfg.present) else "  [not in workcell]"
    print(f"\n  {s.device}  ({key}){here}")
    print(f"    role         {s.role.value}")
    print(f"    transport    {s.transport.value} ({s.transport_note})")
    print(f"    decoded      {cov['decoded']}/{cov['total']} commands")
    print(f"    works today  {zero}")
    if s.controller is None:
      print("    controller   none in plr-re")
    if s.note:
      print(f"    note         {s.note}")
  print("\nfederated instruments (di-omics/plr-tested):")
  for key in sorted(FEDERATED):
    f = FEDERATED[key]
    wired = "wired" if (key in wc.federated and wc.plr_tested_root) else "not wired"
    print(f"\n  {f.device}  ({key})  [{wired}]")
    print(f"    role         {f.role.value}")
    print(f"    entry        {f.entry}")
    print(f"    validated    {f.validated}")
    print(f"    run cards    {', '.join(sorted(f.validated_ops)) or 'none'}")
    if f.known_failures:
      # Surfaced, never omitted: a run card that exists and fails is a fact about this
      # lab, and hiding it would make a known defect look like unwritten work.
      print(f"    FAILED       {', '.join(sorted(f.known_failures))}")
    if f.note:
      print(f"    note         {f.note}")
  return 0


def _protocols(args) -> int:
  for name, p in sorted(protocols.REFERENCE_PROTOCOLS.items()):
    print(f"{name}  ({len(p.steps)} steps)")
    print(f"  {p.summary}")
  return 0


def _ledger(args) -> int:
  wc = _workcell(args)
  p = protocols.get(args.protocol)
  ledger = build_ledger(p, wc)
  print(f"protocol: {p.name}\n{p.summary}\n")
  for i, row in enumerate(ledger.rows, 1):
    print(f"  {i:2d}. {row.verdict.value.upper():<10} {row.step.instrument:<14} {row.step.summary}")
    print(f"      {row.reason}")
  counts = ledger.counts()
  # Print every verdict, so the row counts always sum to the step count. A tally that
  # quietly dropped a category would be the exact failure this tool exists to prevent.
  tally = "  ".join(f"{name} {counts[name]}" for name in (v.value for v in Verdict))
  print(f"\n  {tally}   (of {len(ledger.rows)})")
  print(f"  autonomy         {100 * ledger.autonomy():.0f}%  (steps that run headless today)")
  print(f"  reachable        {100 * ledger.reachable():.0f}%  (incl. steps a human supervises)")
  print(
    f"  unattended run   reaches step {ledger.headless_prefix()} of {len(ledger.rows)} before it stops"
  )
  hops = ledger.handoffs()
  if hops:
    print(f"  physical hops    {len(hops)} (no decoding removes these; only a plate mover does)")
    for art, src, dst in hops:
      print(f"                   {art}: {src} -> {dst}")
  stop = ledger.first_stop()
  if stop is not None:
    print(f"\n  first stop: {stop.step.summary}\n              {stop.reason}")
  return 0 if ledger.headless_prefix() == len(ledger.rows) else 1


def _gaps(args) -> int:
  wc = _workcell(args)
  names = [args.protocol] if args.protocol else sorted(protocols.REFERENCE_PROTOCOLS)
  ranked = rank_unlocks([protocols.get(n) for n in names], wc)
  print(f"reverse-engineering queue across: {', '.join(names)}\n")
  if not ranked:
    print("  nothing blocked.")
    return 0
  print("  Ranked by steps freed. The coverage gate is all-or-nothing, so the unit here")
  print("  is a finished map: decoding one command of an instrument frees nothing.\n")
  for u in ranked:
    print(f"  {u.instrument:<14} frees {u.steps_unblocked} step(s), needs {u.cost} command(s) decoded")
    print(f"                 {', '.join(u.commands_to_decode)}")
  return 1


def _doctor(args) -> int:
  """Check the federated claims against the record plr-tested publishes about them.

  Two passes with different powers, and only one of them needs the operator's tree.

  The status comparison reads an evidence manifest. A byte-identical copy of plr-tested's
  own manifest ships in this repo, so with no flag `doctor` runs that comparison against
  the bundled copy: any reader who clones this repo can check the statuses, the run-card
  paths and the confirm tokens the ledger cites. That is the pass that catches the
  disagreement existence cannot -- an operation this package still calls validated that its
  source repo has downgraded.

  `--plr-tested PATH` points the same comparison at the operator's checkout, which is the
  authority, and additionally runs the file-existence pass: that one opens the run cards to
  confirm the cited script is there and the confirm token is really in it, so it cannot run
  without the tree. plr-tested is private, so that pass is the operator's to run.
  """
  wc = _workcell(args)
  root = wc.plr_tested_root
  if root:
    checks = check_federated(root) + check_manifest(root)
    source = f"the plr-tested checkout at {root}"
  else:
    checks = check_manifest(BUNDLED_ROOT)
    source = f"the {MANIFEST_PATH} bundled in this repo"
  print(render_checks(checks, source))
  return 0 if all(c.ok for c in checks) else 1


def _run(args) -> int:
  wc = _workcell(args)
  report = Executor(wc, armed=args.armed).run(protocols.get(args.protocol))
  print(report.render())
  return 0 if report.handoff is None else 1


def _qc(args) -> int:
  """Can this protocol's QC gates be evaluated at all?"""
  wc = _workcell(args)
  p = protocols.get(args.protocol)
  report = gate_report(p.name, build_ledger(p, wc))
  print(f"QC gates on {p.name}\n")
  if not report.rows:
    print("  no gates declared. Nothing about this protocol's results is checked.")
    return 1
  for row in report.rows:
    print(f"  {row.readiness.value.upper():<14} {row.gate.name}")
    print(f"      protects   {row.gate.blocks}")
    print(f"      {row.reason}")
    for c in row.gate.criteria:
      mark = "" if c.basis.validated else "   [unvalidated threshold]"
      print(f"      - {c.describe()}  ({c.basis.value}){mark}")
    print()
  wrong = report.inappropriate(MEASUREMENTS)
  for gate_name, meas in wrong:
    print(f"  WRONG ASSAY  {gate_name} reads '{meas.key}'")
    print(f"      {meas.inappropriate_reason}")
    print()
  unsat = report.unsatisfiable()
  print(f"  {len(report.rows) - len(unsat)} of {len(report.rows)} gate(s) can be evaluated today")
  if unsat:
    print("  A protocol configured with a gate that cannot fire looks supervised and is not.")
  return 0 if report.closes_the_loop() and not wrong else 1


def _vision(args) -> int:
  """What a camera would catch here, and what no camera ever will."""
  cap = VisionCapability.none()
  counts = vision_summary(cap)
  print(f"visual checks in this workcell ({cap.name})\n")
  for gap in vision_gaps(cap):
    state = "available" if gap.available else ("IMPOSSIBLE" if not gap.check.possible else "blocked")
    print(f"  {state:<11} {gap.check.name}")
    print(f"      observes   {gap.check.observes}")
    print(f"      catches    {gap.check.catches}  ({gap.check.observable.value})")
    print(f"      {gap.reason}")
    if gap.check.note:
      print(f"      note       {gap.check.note}")
    print()
  print(
    f"  {counts['available']} available, {counts['blocked']} blocked, "
    f"{counts['impossible']} impossible of {counts['total']}"
  )
  if cap.note:
    print(f"  {cap.note}")
  return 0 if counts["available"] == counts["total"] else 1


def _failures(args) -> int:
  """Which failures would be caught, when, and which are silent."""
  wc = _workcell(args)
  p = protocols.get(args.protocol)
  ledger = build_ledger(p, wc)
  report = recovery_report(p, gate_report(p.name, ledger), VisionCapability.none())
  print(f"failure modes on {p.name}\n")
  for row in report.rows:
    f = row.failure
    flag = "  <-- silent and destructive" if row.destructive_and_silent else ""
    print(f"  {row.latency.value.upper():<17} {f.name}  [{f.severity.value}]{flag}")
    print(f"      {f.description}")
    print(f"      plan: {f.declared_detection.value} at {f.declared_latency.value}")
    print(f"      real: {row.detection.value} -- {row.reason}")
    print()
  c = report.counts()
  print(
    f"  {c['total']} failure mode(s): {c['silent']} silent, "
    f"{c['destructive_and_silent']} silent AND destructive, {c['degraded']} worse than planned"
  )
  print(
    f"  {c['vision_would_not_help']} of the silent ones are invisible to any camera; "
    "they need a different sensor or a calibration experiment"
  )
  helpful = visual_checks_that_would_help(report)
  if helpful:
    print("\n  cameras would convert these from silent to caught:")
    for name in helpful:
      print(f"    - {name}")
  return 0 if not report.destructive_and_silent() else 1


def _throughput(args) -> int:
  """How many plates a day, or why that cannot be said."""
  wc = _workcell(args)
  p = protocols.get(args.protocol)
  est = throughput_estimate(p, build_ledger(p, wc))
  print(f"throughput for {p.name}\n")
  print(f"  timed steps      {len(est.measured_ops)} of {len(p.steps)}  ({100 * est.measured_fraction:.0f}%)")
  print(f"  attended steps   {len(est.attended_ops)} of {len(p.steps)} need a human")
  if est.computable:
    print(f"  one plate        {est.floor_seconds:.0f} s")
    print(f"  bottleneck       {est.bottleneck} at {est.bottleneck_seconds:.0f} s per plate")
    span = est.makespan(10)
    if span is not None:
      print(f"  10 plates        {span:.0f} s")
    rate = est.plates_per_day()
    if rate is not None:
      print(f"  plates/day       {rate:.1f}  (bounded by attended hours)")
  else:
    print(f"  measured floor   {est.floor_seconds:.0f} s (a lower bound, not a total)")
    print("\n  NOT COMPUTABLE")
    print(f"  {est.why_not()}")
    print(
      "\n  A plates-per-day figure over untimed steps would be a guess formatted as a\n"
      "  specification. The floor is real; the total is not available."
    )
  return 0 if est.computable else 1


def _provenance(args) -> int:
  """What could actually be proven about a run afterwards."""
  wc = _workcell(args)
  p = protocols.get(args.protocol)
  report = provenance_report(build_ledger(p, wc))
  c = report.counts()
  print(f"provenance for {p.name}\n")
  print(f"  steps an instrument could confirm   {c['steps_confirmable']} of {c['steps_total']}")
  print(f"  steps recorded on intent alone      {c['steps_asserted_only']}")
  print(f"  unobserved custody transfers        {c['custody_gaps']}\n")
  for gap in report.gaps:
    print(f"  GAP  {gap.artifact}: {gap.from_instrument} -> {gap.to_instrument}")
    print(f"       {gap.reason}")
    print(f"       closes it: {gap.closes_it}")
    print()
  if report.gaps:
    print(
      "  The chain of custody breaks at exactly the physical hops the ledger counts.\n"
      "  Software cannot close these; a barcode read or a reporting arm can."
    )
  return 0 if report.unbroken else 1


def _lineage(args) -> int:
  """Can this lab say which cell a result came from?"""
  wc = _workcell(args)
  p = protocols.get(args.protocol)
  report = lineage_report(p, build_ledger(p, wc), args.datum, unit=args.unit)
  g = report.graph
  c = report.counts()

  print(f"sample lineage for {p.name}: '{args.datum}' back to one {report.unit}\n")
  print(f"  {report.unit}s in the run                  {c['units']}")
  print(f"  steps in the identity chain         {c['steps_in_chain']}")
  print(f"  steps that happen at all today      {c['steps_that_happen_today']}")
  print(f"  steps on a human's word             {c['steps_on_a_human_s_word']}")
  print(f"  unobserved custody hops             {c['unobserved_custody_hops']}\n")

  print(f"  TODAY     {report.verdict.value.upper()}")
  print(f"      {report.reason}")
  print(f"  CEILING   {report.ceiling.value.upper()}   (every command decoded)")
  print(f"      {report.ceiling_reason}\n")

  print("  where the material stands:")
  # The sample stream only. A flow cell is real, is not a cell, and would read as one.
  for name, cohort in ((n, g.cohorts[n]) for n in g.ancestry(args.datum) if n in g.cohorts):
    flag = "  <-- COLLISION" if cohort.tag_collision else ""
    print(
      f"    {name:18} {cohort.members:>4} {report.unit}(s)  {cohort.separability.value}{flag}"
    )

  tag = g.tag_edge()
  if tag is not None:
    att = tag.attestation.value if tag.attestation else "nobody"
    print(f"\n  LINCHPIN  {tag.step_op} on {tag.instrument}, attested: {att}")
    print(
      "      This is the only step whose effect survives pooling. Every per-"
      f"{report.unit}\n      claim the run makes rests on it, and no instrument reads back"
      " that it\n      happened correctly."
    )

  destroyed = g.destroyed_at()
  if destroyed is not None:
    print(f"\n  DESTROYED AT  {destroyed.step_op}")
    print("      Material was pooled with no label applied first. This is not recoverable")
    print("      by any instrument, now or later.")

  blind = g.post_merge_measurements()
  for e in blind:
    print(f"\n  BLIND MEASUREMENT  {e.step_op} on {e.instrument}")
    print(
      f"      reads {e.before.members} {report.unit}(s) as one number. A failure confined"
      f" to one\n      of them moves it by about 1/{e.before.members} and fails no gate."
    )

  if any(c.separability is Separability.TAGGED for c in g.cohorts.values()):
    print("\n  UNMEASURED ERROR TERM  index misassignment")
    print(f"      {MISASSIGNMENT.mechanism}")
    print(f"      basis: {MISASSIGNMENT.basis.value}; measured in this lab: no")
    print(f"      mitigated by: {MISASSIGNMENT.mitigated_by}")

  print(
    "\n  Tracking a plate and tracking a sample are different problems. This lab's"
    f"\n  container record can be perfect and still not say which {report.unit} a result"
    " came from."
  )
  return 0 if report.verdict.ok else 1


def _coverage(args) -> int:
  """Vision and QC gates composed: would anything catch each failure?"""
  wc = _workcell(args)
  p = protocols.get(args.protocol)
  ledger = build_ledger(p, wc)
  gates = gate_report(p.name, ledger)
  cap = VisionCapability.none()
  report = coverage_report(p, ledger, gates, recovery_report(p, gates, cap), cap)
  c = report.counts()

  print(f"detection coverage for {p.name}\n")
  print(f"  failure modes            {c['total']}")
  print(f"  covered                  {c['covered']}  (vision {c['vision']}, gate {c['gate']}, both {c['both']})")
  print(f"  uncovered                {c['uncovered']}, of which {c['uncovered_destructive']} destroy material")
  print(f"  closable as it stands    {c['fixable']}  (build the detector, or make the gate fire)")
  print(f"  needs a new instrument   {c['structural']}\n")

  # FIXABLE covers two different jobs -- a detector nobody built, and a gate whose input
  # nobody made arrive. Printing them under one heading would tell a reader to point a
  # camera at a condition no camera resolves, which is the exact error this module exists
  # to prevent, committed by its own report.
  fixable = report.fixable()
  by_vision = [r for r in fixable if r.observable.reachable_by_vision]
  by_repair = [r for r in fixable if not r.observable.reachable_by_vision]

  if by_vision:
    print("  A CAMERA WOULD CATCH THESE -- the check is buildable, nobody built it:")
    for r in by_vision:
      print(f"    {r.failure.name:34} ({r.observable.value})")
      if r.vision_reason:
        print(f"        {r.vision_reason[:96]}")
    print()

  if by_repair:
    print("  INVISIBLE, BUT A DECLARED GATE ALREADY READS THEM -- make the gate fire:")
    for r in by_repair:
      print(f"    {r.failure.name:34} ({r.observable.value})")
      if r.gate_reason:
        print(f"        {r.gate_reason[:96]}")
    print()

  structural = report.structural()
  if structural:
    print("  NO CAMERA REACHES THESE AT ANY CAPABILITY -- they need an assay:")
    for r in structural:
      print(f"    {r.failure.name:34} ({r.observable.value})")
    print()

  demands = mandatory_gates(gates)
  if demands:
    print(f"  {len(demands)} MANDATORY GATE(S) -- invisible and destructive, so a gate is the only option:")
    for d in demands:
      print(f"    {d.failure.name}")
      print(f"        {d.reason[:100]}")
    print()

  print(
    "  Vision and gates are complementary instruments, not alternatives. Where the photons\n"
    "  are identical either way, no model resolves it and only an assay does."
  )
  return 0 if report.complete() else 1


def _durability(args) -> int:
  """What each instrument is currently entitled to be trusted with."""
  wc = _workcell(args)
  s = entitlement_summary(wc)
  print(f"instrument entitlement for workcell '{wc.name}'\n")
  for k, v in sorted(s.items()):
    print(f"  {k:24} {v}")
  print()
  rows = untrusted_instruments(wc)
  if not rows:
    print("  Every instrument is currently entitled.")
    return 0
  print(f"  {len(rows)} instrument(s) not currently entitled:\n")
  for u in rows:
    print(f"    {getattr(u, 'instrument', '?')}  [{getattr(getattr(u, 'standing', None), 'value', '?')}]")
    print(f"        {getattr(u, 'reason', '')[:110]}")
    restore = getattr(u, "restores_it", "")
    if restore:
      print(f"        restores it: {restore[:110]}")
    print()
  print(
    "  An instrument with no service history is not a healthy instrument, it is an\n"
    "  unmeasured one -- the same convention this package applies to benchmarks."
  )
  return 1


def _teaching(args) -> int:
  """What an expert has demonstrated, and what the machine attains against it."""
  p = protocols.get(args.protocol)
  ops = sorted({s.op for s in p.steps})
  report = transfer_report(ops)
  s = teaching_summary()
  print(f"expert transfer for {p.name}\n")
  for k, v in sorted(s.items()):
    print(f"  {k:32} {v}")
  print()
  for row in report.rows:
    print(f"  {row.operation:34} {row.parity.attainment.value}")
    print(f"      expert n={row.parity.expert_n}, machine n={row.parity.machine_n}")
    if row.parity.reason:
      print(f"      {row.parity.reason[:104]}")
  queue = demonstration_queue([p])
  if queue:
    print("\n  WHAT TO DEMONSTRATE NEXT (ranked by steps unblocked):")
    for n in queue[:6]:
      ops = ", ".join(n.operations[:3])
      print(f"    {n.instrument:16} {n.demonstrations_needed} demo(s) -> unblocks {n.steps_blocked} step(s)")
      print(f"                     {ops}")
  print(
    "\n  A demonstration is data, not authority. One performance is a value with no\n"
    "  tolerance, and a tolerance invented around it would be a fabricated number."
  )
  return 0


def _feedback(args) -> int:
  """Can a control loop on this protocol actually close?"""
  wc = _workcell(args)
  p = protocols.get(args.protocol)
  report = feedback_report(p, build_ledger(p, wc))
  print(f"control loops for {p.name}\n")
  if not report.rows:
    print("  No control loop is declared for this protocol.")
    print("  A protocol with no loop is open-loop by construction, however automated it is.")
    return 1
  for row in report.rows:
    verdict = getattr(getattr(row, "closable", None), "value", "?")
    print(f"  {getattr(getattr(row, 'loop', None), 'name', '?'):28} {verdict.upper()}")
    reason = getattr(row, "reason", "")
    if reason:
      print(f"      {reason[:110]}")
    exposure = getattr(row, "in_flight", None)
    if exposure is not None:
      print(f"      committed before a correction lands: {exposure}")
    print()
  print(
    "  A sensor downstream of its own actuator is a post-mortem wearing the costume of a\n"
    "  control loop. This module does not model gain or settling -- that needs a plant\n"
    "  model and measured response data nothing here has."
  )
  return 0 if all(getattr(getattr(r, "closable", None), "value", "") == "closes" for r in report.rows) else 1


def _knowledge(args) -> int:
  """The tacit layer: expert judgments and the benchmarks a robot must meet."""
  s = knowledge_summary()
  print("encoded expert judgment\n")
  for j in JUDGMENTS:
    mark = "" if j.validated else "   [unvalidated]"
    print(f"  {j.name}  ({j.basis.value}){mark}")
    print(f"      when  {j.when}")
    print(f"      then  {j.then}")
    print(f"      why   {j.because}")
    if j.guards:
      print(f"      guards against  {j.guards}")
    print()
  print("robot benchmarks\n")
  for b in BENCHMARKS:
    print(f"  {b.status.value.upper():<12} {b.name}  ({b.op})")
    print(f"      target   {b.target}")
    if b.evidence:
      print(f"      evidence {b.evidence}")
    if b.how_to_measure and not b.status.trusted:
      print(f"      measure  {b.how_to_measure}")
    print()
  print(
    f"  {s['judgments_validated']} of {s['judgments']} judgments validated against this "
    f"lab's own data"
  )
  print(
    f"  {s['benchmarks_met']} of {s['benchmarks']} benchmarks met "
    f"({s['benchmarks_unmeasured']} unmeasured, {s['benchmarks_failed']} failed)"
  )
  return 0


def _loop(args) -> int:
  """The capstone: can this lab close one hypothesis-to-evidence loop?"""
  wc = _workcell(args)
  p = protocols.get(args.protocol)
  ledger = build_ledger(p, wc)
  gates = gate_report(p.name, ledger)
  recovery = recovery_report(p, gates, VisionCapability.none())
  prov = provenance_report(ledger)
  closure = loop_closure(ledger, gates, recovery, prov)

  print(f"loop closure for {p.name}\n")
  for leg in closure.legs:
    print(f"  {leg.leg.value.upper():<9} {'ok' if leg.ok else 'BROKEN'}")
    print(f"      {leg.reason}")
  print()
  if closure.closes:
    print("  This lab can close a hypothesis-to-evidence loop on this protocol.")
    return 0
  print(f"  {len(closure.broken())} of 4 legs broken. The loop does not close.")
  print(
    "\n  Each leg implies different work: EXECUTE means reverse-engineering, MEASURE means\n"
    "  an instrument that returns a usable number, DECIDE means a detection path for the\n"
    "  failures that destroy material, RECORD means barcodes or an arm that reports."
  )
  untrusted = untrusted_ops(p)
  print(f"\n  Separately, {len(untrusted)} of {len({s.op for s in p.steps})} operations have no met benchmark.")
  return 1


def build_parser() -> argparse.ArgumentParser:
  p = argparse.ArgumentParser(prog="autonomous-lab", description=__doc__)
  sub = p.add_subparsers(dest="cmd", required=True)

  def common(sp):
    sp.add_argument("--workcell", help="workcell JSON (default: every instrument, nothing decoded)")
    sp.add_argument(
      "--plr-tested",
      dest="plr_tested",
      help="path to a di-omics/plr-tested checkout, to wire the validated STAR/ODTC legs",
    )

  st = sub.add_parser("stock", help="every instrument, its role, and how far its map is")
  common(st)
  st.set_defaults(func=_stock)

  pr = sub.add_parser("protocols", help="list the reference protocols")
  common(pr)
  pr.set_defaults(func=_protocols)

  lg = sub.add_parser(
    "ledger", help="cost a protocol: what runs headless, what a human does, what is blocked"
  )
  lg.add_argument("protocol")
  common(lg)
  lg.set_defaults(func=_ledger)

  gp = sub.add_parser("gaps", help="the reverse-engineering queue, ranked by steps freed")
  gp.add_argument("protocol", nargs="?", help="default: all reference protocols")
  common(gp)
  gp.set_defaults(func=_gaps)

  dc = sub.add_parser(
    "doctor",
    help=(
      "check this package's claims against the bundled evidence manifest; add "
      "--plr-tested PATH to also open the run cards in a checkout"
    ),
  )
  common(dc)
  dc.set_defaults(func=_doctor)

  rn = sub.add_parser("run", help="run a protocol as far as it honestly goes")
  rn.add_argument("protocol")
  rn.add_argument(
    "--armed", action="store_true", help="perform the read-only steps for real (never actuates)"
  )
  common(rn)
  rn.set_defaults(func=_run)

  qc = sub.add_parser("qc", help="can this protocol's QC gates be evaluated at all?")
  qc.add_argument("protocol")
  common(qc)
  qc.set_defaults(func=_qc)

  vs = sub.add_parser("vision", help="what a camera would catch, and what no camera ever will")
  common(vs)
  vs.set_defaults(func=_vision)

  fl = sub.add_parser("failures", help="which failures are caught, when, and which are silent")
  fl.add_argument("protocol")
  common(fl)
  fl.set_defaults(func=_failures)

  tp = sub.add_parser("throughput", help="plates per day, or why that number does not exist")
  tp.add_argument("protocol")
  common(tp)
  tp.set_defaults(func=_throughput)

  pv = sub.add_parser("provenance", help="what could be proven about a run afterwards")
  pv.add_argument("protocol")
  common(pv)
  pv.set_defaults(func=_provenance)

  ln = sub.add_parser("lineage", help="which sample a result came from, and whether that is provable")
  common(ln)
  ln.add_argument("protocol", nargs="?", default="single_cell_genomics")
  ln.add_argument("--datum", default="run_outcome", help="the result to trace back")
  ln.add_argument("--unit", default="cell", help="what the science needs to distinguish")
  ln.set_defaults(func=_lineage)

  cvg = sub.add_parser("coverage", help="would anything catch each failure? vision and gates composed")
  common(cvg)
  cvg.add_argument("protocol", nargs="?", default="single_cell_genomics")
  cvg.set_defaults(func=_coverage)

  dur = sub.add_parser("durability", help="what each instrument is entitled to be trusted with")
  common(dur)
  dur.set_defaults(func=_durability)

  tch = sub.add_parser("teaching", help="what an expert demonstrated, and what the machine attains")
  common(tch)
  tch.add_argument("protocol", nargs="?", default="single_cell_genomics")
  tch.set_defaults(func=_teaching)

  fbk = sub.add_parser("feedback", help="can a control loop on this protocol actually close?")
  common(fbk)
  fbk.add_argument("protocol", nargs="?", default="single_cell_genomics")
  fbk.set_defaults(func=_feedback)

  kn = sub.add_parser("knowledge", help="encoded expert judgment and robot benchmarks")
  common(kn)
  kn.set_defaults(func=_knowledge)

  lp = sub.add_parser("loop", help="can this lab close one hypothesis-to-evidence loop?")
  lp.add_argument("protocol")
  common(lp)
  lp.set_defaults(func=_loop)

  return p


def main(argv: List[str] = None) -> int:
  _log_setup()
  args = build_parser().parse_args(argv)
  try:
    return args.func(args)
  except (ValueError, KeyError, FileNotFoundError, RuntimeError) as e:
    # Expected, actionable failures (an unknown protocol, a missing map, a workcell typo)
    # print cleanly instead of dumping a traceback.
    print(f"error: {e}", file=sys.stderr)
    return 1
  except ImportError as e:
    # plr-re is the hard dependency; say so rather than showing a bare import error.
    print(
      f"error: {e}\n"
      "autonomous-lab needs plr-re. Install it with:\n"
      "  pip install 'plr-re @ git+https://github.com/di-omics/plr-reverse-engineer'",
      file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
  raise SystemExit(main())
