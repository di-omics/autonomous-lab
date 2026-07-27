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

from .demo import SCENARIOS, run_closed_loop_demo
from .doctor import check_federated, check_manifest, render as render_checks
from .executor import Executor
from .intelligence import (
  BENCHMARKS,
  JUDGMENTS,
  knowledge_summary,
  loop_closure,
  untrusted_ops,
)
from .ledger import build_ledger, rank_unlocks
from .lineage import MISASSIGNMENT, Separability, lineage_report
from .model import Verdict
from .orchestration_demo import ORCHESTRATION_SCENARIOS, run_orchestration_demo
from .provenance import provenance_report
from .qc import MEASUREMENTS, gate_report
from .recovery import recovery_report, visual_checks_that_would_help
from .registry import FEDERATED, registry
from .throughput import (
  estimate as throughput_estimate,
  illustrative_genomics_plan,
  render_report,
)
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
  print("\nfederated instruments (driven from di-omics/plr-tested):")
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
  """Check the federated claims against a real plr-tested checkout.

  Two passes with different powers. The first checks that cited files and tokens exist,
  which catches a rename. The second compares this package's status claims against
  plr-tested's own published manifest, which catches the disagreement existence cannot:
  an operation this package still calls validated that its source repo has downgraded.
  """
  wc = _workcell(args)
  root = wc.plr_tested_root
  if not root:
    print(
      "error: doctor needs a plr-tested checkout to check against; pass --plr-tested PATH",
      file=sys.stderr,
    )
    return 2
  checks = check_federated(root) + check_manifest(root)
  print(render_checks(checks))
  return 0 if all(c.ok for c in checks) else 1


def _run(args) -> int:
  wc = _workcell(args)
  report = Executor(wc, armed=args.armed).run(protocols.get(args.protocol))
  print(report.render())
  return 0 if report.handoff is None else 1


def _demo_loop(args) -> int:
  """Exercise proposal -> evidence gates -> decision -> audit record in simulation."""
  report = run_closed_loop_demo(args.scenario or "pass")
  print(report.render())
  return 0 if report.decision.permitted else 1


def _illustrative_throughput(args) -> int:
  """Report the bottleneck in an explicitly illustrative capacity model."""
  plan = illustrative_genomics_plan()
  print(render_report(plan, plan.report(args.samples or 96)))
  return 0


def _orchestrate(args) -> int:
  """Exercise resource locks, evidence gates, bounded recovery, and provenance."""
  report = run_orchestration_demo(args.scenario)
  print("SYNTHETIC WORKCELL ORCHESTRATION - NO HARDWARE CLAIM\n")
  print(report.render())
  return 0 if report.succeeded else 1


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


def _protocol_throughput(args) -> int:
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


def _protocol_loop(args) -> int:
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


def _throughput(args) -> int:
  """Dispatch the protocol estimator or the explicitly illustrative capacity model."""
  if args.protocol is not None:
    if args.samples is not None:
      raise ValueError("throughput accepts either PROTOCOL or --samples, not both")
    return _protocol_throughput(args)
  return _illustrative_throughput(args)


def _loop(args) -> int:
  """Dispatch protocol loop closure or the synthetic evidence-gate demonstration."""
  if args.protocol is not None:
    if args.scenario is not None:
      raise ValueError("loop accepts either PROTOCOL or --scenario, not both")
    return _protocol_loop(args)
  return _demo_loop(args)


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
    "doctor", help="check this package's claims about plr-tested against a real checkout"
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

  tp = sub.add_parser(
    "throughput",
    help="cost measured protocol throughput, or show the illustrative capacity model",
  )
  tp.add_argument("protocol", nargs="?", help="omit for the explicitly illustrative model")
  tp.add_argument("--samples", type=int, help="sample count for illustrative mode (default: 96)")
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

  kn = sub.add_parser("knowledge", help="encoded expert judgment and robot benchmarks")
  common(kn)
  kn.set_defaults(func=_knowledge)

  lp = sub.add_parser(
    "loop",
    help="cost protocol loop closure, or run a synthetic evidence-gate scenario",
  )
  lp.add_argument("protocol", nargs="?", help="protocol to cost; omit for synthetic mode")
  lp.add_argument("--scenario", choices=SCENARIOS, help="synthetic QC/vision/telemetry scenario")
  common(lp)
  lp.set_defaults(func=_loop)

  orch = sub.add_parser(
    "orchestrate",
    help="synthetic workcell task with atomic resource locks and bounded recovery",
  )
  orch.add_argument("--scenario", choices=ORCHESTRATION_SCENARIOS, default="pass")
  orch.set_defaults(func=_orchestrate)

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
