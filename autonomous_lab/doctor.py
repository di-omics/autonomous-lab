"""Check this package's claims against the repos it makes them about.

The instrument registry is derived from `plr_re.protocolmap.SEEDS`, so it cannot drift:
if plr-re changes, the registry changes with it. The federated claims have no such luxury.
`validated_ops` is hand-written prose and paths about a DIFFERENT repo, which makes it
exactly the kind of assertion this package refuses to accept from anybody else. A script
gets renamed in plr-tested and the ledger goes on confidently citing a run card that is
not there.

So `doctor` checks the checkable part. For every operation this package calls validated:

  * does the run card actually exist at that path in the plr-tested checkout?
  * does the confirm token this package tells you to pass actually appear in that script?
  * does the entry (run_on_pi.sh) exist?

What it deliberately cannot check is `evidence` -- whether an operator really watched the
thing run. That is prose about the physical world and no checker reaches it. Which is why
the evidence strings stay narrow and carry their own caveats.

This reads files. It runs nothing, connects to nothing, and touches no instrument.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

from .registry import FEDERATED


@dataclass(frozen=True)
class Check:
  """One verifiable claim, and whether it survived contact with the checkout."""

  instrument: str
  op: Optional[str]
  claim: str
  ok: bool
  detail: str

  def render(self) -> str:
    mark = "ok  " if self.ok else "DRIFT"
    where = f"{self.instrument}.{self.op}" if self.op else self.instrument
    line = f"  [{mark}] {where:<28} {self.claim}"
    if not self.ok:
      line += f"\n           {self.detail}"
    return line


def check_federated(plr_tested_root: str) -> List[Check]:
  """Verify every federated claim against a plr-tested checkout."""
  out: List[Check] = []
  root = os.path.expanduser(plr_tested_root)

  if not os.path.isdir(root):
    return [
      Check(
        instrument="(all)",
        op=None,
        claim="plr-tested checkout is readable",
        ok=False,
        detail=f"no directory at '{root}'",
      )
    ]

  for key in sorted(FEDERATED):
    fed = FEDERATED[key]

    entry_path = os.path.join(root, fed.entry)
    out.append(
      Check(
        instrument=key,
        op=None,
        claim=f"entry exists: {fed.entry}",
        ok=os.path.exists(entry_path),
        detail=f"expected a run card at {entry_path}",
      )
    )

    # Known failures are checked exactly like validated ops. The claim "this exists and
    # fails" also rots: if the script is gone, the ledger is reporting a defect in code
    # nobody has, which is its own kind of wrong.
    claims = [(op, run, "validated") for op, run in fed.validated_ops.items()]
    claims += [(op, run, "known failure") for op, run in fed.known_failures.items()]
    claims += [(op, run, "written") for op, run in fed.written_ops.items()]

    for op, run, kind in sorted(claims):
      script_path = os.path.join(root, run.script)
      exists = os.path.isfile(script_path)
      out.append(
        Check(
          instrument=key,
          op=op,
          claim=f"run card exists ({kind}): {run.script}",
          ok=exists,
          detail=(
            f"this package cites {run.script} as the {kind} run card for {key}.{op}, but "
            f"there is no file at {script_path}. Either it was renamed in {fed.repo} or "
            "the claim is wrong; until it resolves, the ledger is citing a run card "
            "nobody can run."
          ),
        )
      )
      if not exists or run.confirm_token is None:
        continue
      # The token is what the ledger tells an operator to type. If it is not in the
      # script, the instruction is wrong and the run would refuse -- a small lie with a
      # real cost at the bench.
      try:
        with open(script_path, encoding="utf-8", errors="replace") as fh:
          body = fh.read()
      except OSError as e:
        out.append(
          Check(key, op, f"confirm token {run.confirm_token}", False, f"could not read: {e}")
        )
        continue
      out.append(
        Check(
          instrument=key,
          op=op,
          claim=f"confirm token appears in the run card: {run.confirm_token}",
          ok=run.confirm_token in body,
          detail=(
            f"the ledger tells an operator to pass --confirm {run.confirm_token}, but that "
            f"token is not in {run.script}. The run would refuse."
          ),
        )
      )

  return out


def render(checks: List[Check]) -> str:
  lines = ["federated claims checked against the plr-tested checkout:\n"]
  lines += [c.render() for c in checks]
  bad = [c for c in checks if not c.ok]
  lines.append("")
  if bad:
    lines.append(f"  {len(bad)} of {len(checks)} claims did not survive the check.")
    lines.append("  Until they do, treat the supervised rows in the ledger as unproven.")
  else:
    lines.append(f"  all {len(checks)} checkable claims hold.")
    lines.append(
      "  Note what this does NOT check: whether an operator really watched these run. "
      "That is prose about the physical world, and no checker reaches it."
    )
  return "\n".join(lines)
