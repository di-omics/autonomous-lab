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

from .doctor import check_federated, render as render_checks
from .executor import Executor
from .ledger import build_ledger, rank_unlocks
from .model import Verdict
from .record import RunRecord
from .registry import FEDERATED, registry
from .workcell import Workcell
from . import acceptance, control, criteria, permission, protocols, samples


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
  """Check the federated claims against a real plr-tested checkout."""
  wc = _workcell(args)
  root = wc.plr_tested_root
  if not root:
    print(
      "error: doctor needs a plr-tested checkout to check against; pass --plr-tested PATH",
      file=sys.stderr,
    )
    return 2
  checks = check_federated(root)
  print(render_checks(checks))
  return 0 if all(c.ok for c in checks) else 1


def _run(args) -> int:
  wc = _workcell(args)
  report = Executor(wc, armed=args.armed).run(protocols.get(args.protocol))
  print(report.render())
  return 0 if report.handoff is None else 1


def _gates(args) -> int:
  """The acceptance rubrics, and whether this bench can actually apply them."""
  wc = _workcell(args)
  blocked = 0
  for name in sorted(criteria.REFERENCE_GATES):
    gate = criteria.get(name)
    can, why = gate.measurable(wc)
    ready, unpinned = gate.ready_for_hardware()
    print(f"\n  {gate.name}")
    print(f"    guards       {gate.guards}")
    print(f"    measured by  {gate.produced_by[0]}.{gate.produced_by[1]}")
    print(f"    measurable   {'yes' if can else 'NO'}  {why}")
    for c in gate.criteria:
      tag = "" if c.origin is acceptance.Origin.TRANSCRIBED else f"  [{c.origin.value.upper()}]"
      print(f"      {c.describe()}{tag}")
      print(f"        source: {c.source}")
    if not ready:
      blocked += 1
      print("    NOT READY FOR HARDWARE:")
      for r in unpinned:
        print(f"      {r}")
    if gate.note:
      print(f"    note         {gate.note}")
  transcribed = sum(
    1 for g in criteria.REFERENCE_GATES.values() for c in g.criteria
    if c.origin is acceptance.Origin.TRANSCRIBED
  )
  total = sum(len(g.criteria) for g in criteria.REFERENCE_GATES.values())
  print(f"\n  {transcribed} of {total} thresholds are transcribed from a citable source.")
  print(f"  {blocked} of {len(criteria.REFERENCE_GATES)} rubrics cannot gate material yet.")
  return 1 if blocked else 0


def _provenance(args) -> int:
  """What a bad result at the end of the reference run would implicate."""
  for indexed in (False, True):
    lin = samples.reference_lineage(indexed=indexed)
    s = lin.summary("pool")
    print(f"\n  pooled library, index map {'recorded' if indexed else 'NOT recorded'}:")
    print(f"    attribution        {s['attribution']}")
    print(f"    indistinguishable  {s['indistinguishable']} contributor(s)")
    print(f"    weakest witness    {s['weakest_witness']}")
    print(f"    events in chain    {s['events']}")
  print(
    "\n  Recording an index per well is the entire difference between a bad library that\n"
    "  names a well and one that only names a plate. Neither run is machine-witnessed:\n"
    "  no step in this protocol has an instrument that writes provenance today."
  )
  return 0


def _session(args) -> int:
  """Propose every step of a protocol and let the gates decide. The integrated view."""
  wc = _workcell(args)
  p = protocols.get(args.protocol)
  sess = permission.Session(
    workcell=wc,
    lineage=samples.reference_lineage(),
    record=RunRecord(f"session:{p.name}"),
  )
  for step in p.steps:
    sess.request(step, proposer=args.proposer)
  print(f"protocol: {p.name}\n{p.summary}\n")
  for d in sess.decisions:
    print(d.render())
    print()
  orders = sess.work_orders()
  print(f"work orders ({len(orders)} distinct, from {len(sess.refused())} refusals):")
  for i, a in enumerate(orders, 1):
    print(f"  {i}. {a}")
  print(f"\n  {sess.record.verify().render()}")
  print(f"  head {sess.record.seal()[:16]}...")
  if args.write_record:
    sess.record.to_jsonl(args.write_record)
    print(f"  record written to {args.write_record}")
  return 0 if not sess.refused() else 1


def _observe(args) -> int:
  """Append what actually happened to a run record. The other half of the loop.

  Verifies the chain before extending it. Appending to a record whose history has been
  edited would launder the edit under a fresh valid digest, which is the one thing a
  tamper-evident log must not let you do casually.
  """
  rec = RunRecord.from_jsonl(args.record)
  check = rec.verify()
  if not check.ok:
    print(f"error: refusing to extend a broken chain. {check.render()}", file=sys.stderr)
    return 1
  rec.append("outcome", step=args.step, ok=not args.failed, note=args.note or "")
  rec.to_jsonl(args.record)
  print(f"recorded {args.step} {'FAILED' if args.failed else 'ok'}; {len(rec)} entries")
  print(f"  head {rec.seal()[:16]}...")
  return 0


def _control(args) -> int:
  """What the runs so far say about which step to fix first."""
  p = protocols.get(args.protocol)
  if not args.record:
    print(
      "no run record given, so there is nothing to learn from.\n\n"
      "  The reliability model has no observations, and a ranking built on a prior\n"
      "  nobody chose would be fiction at the top of a queue meant to direct real work.\n"
      "  Produce one with:  autonomous-lab session <protocol> --write-record run.jsonl\n"
      "  then append 'outcome' entries as steps actually run.",
      file=sys.stderr,
    )
    return 2
  rec = RunRecord.from_jsonl(args.record)
  check = rec.verify()
  print(f"  {check.render()}")
  if not check.ok:
    print("  refusing to learn from a record whose chain does not hold.", file=sys.stderr)
    return 1
  model = control.ReliabilityModel.from_record(rec)
  if not model.known_steps():
    print("\n  the record has no 'outcome' entries; nothing has been observed to run yet.")
    return 2
  print(f"\n  per-step reliability ({len(model.known_steps())} step(s) observed):")
  for step in model.known_steps():
    print(f"    {model.of(step).render()}")
  ranked = model.rank_by_expected_waste(p)
  if ranked:
    print("\n  ranked by expected waste (failure rate x steps already invested):")
    print("    A step that fails early costs little. The same rate at step 17 throws")
    print("    away everything before it, and that is what should be fixed first.\n")
    for w in ranked:
      tag = "" if w.informative else "   (too few runs to act on)"
      print(
        f"    {w.step:<32} step {w.position:2d}   {w.failure_rate:5.1%} fail   "
        f"expected waste {w.expected_waste:5.2f} step(s){tag}"
      )
  return 0


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

  gt = sub.add_parser("gates", help="the acceptance rubrics, and whether this bench can apply them")
  common(gt)
  gt.set_defaults(func=_gates)

  pv = sub.add_parser("provenance", help="what a bad result would implicate, with and without indexing")
  common(pv)
  pv.set_defaults(func=_provenance)

  ss = sub.add_parser(
    "session", help="propose every step and let the gates decide; the integrated view"
  )
  ss.add_argument("protocol")
  ss.add_argument("--proposer", default="agent:planner", help="recorded, never consulted")
  ss.add_argument("--write-record", dest="write_record", help="write the run record as JSONL")
  common(ss)
  ss.set_defaults(func=_session)

  ob = sub.add_parser("observe", help="append what actually happened to a run record")
  ob.add_argument("--record", required=True, help="the run record JSONL to extend")
  ob.add_argument("--step", required=True, help="the operation that ran")
  ob.add_argument("--failed", action="store_true", help="record a failure (default: success)")
  ob.add_argument("--note", help="what happened, for a human reading this later")
  common(ob)
  ob.set_defaults(func=_observe)

  ct = sub.add_parser("control", help="what the runs so far say about which step to fix first")
  ct.add_argument("protocol", nargs="?", default="single_cell_genomics")
  ct.add_argument("--record", help="a run record JSONL to learn from")
  common(ct)
  ct.set_defaults(func=_control)

  rn = sub.add_parser("run", help="run a protocol as far as it honestly goes")
  rn.add_argument("protocol")
  rn.add_argument(
    "--armed", action="store_true", help="perform the read-only steps for real (never actuates)"
  )
  common(rn)
  rn.set_defaults(func=_run)

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
