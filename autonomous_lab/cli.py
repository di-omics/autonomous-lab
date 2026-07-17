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
from .registry import FEDERATED, registry
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
