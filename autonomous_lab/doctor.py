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

Those three catch a renamed file and a stale token, which is most of the rot. They cannot
catch the more interesting disagreement: plr-tested deciding an operation is only WRITTEN
while this package still calls it VALIDATED. Existence is not status, and a run card that
exists proves nothing about whether anyone watched it run.

plr-tested now publishes `evidence/manifest.json`, its own machine-readable record of what
has met an instrument, checked in its own CI by its own rules. So `check_manifest` compares
this package's claims against that file, operation by operation: same script, same confirm
token, same status. Where they disagree, the repo that owns the hardware wins, because it
is the one with the operator and the instrument -- and this package's copy is the
derivative.

That is the whole point of the cross-check. Before it, `validated_ops` was an assertion
about someone else's repo that only its own author could refute. Now it is a claim that the
source of truth can contradict, in CI, without anybody remembering to look.

What neither checker reaches is `evidence` -- whether an operator really watched the thing
run. That is prose about the physical world. Which is why the evidence strings stay narrow
and carry their own caveats.

This reads files. It runs nothing, connects to nothing, and touches no instrument.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

from .registry import FEDERATED

# Where plr-tested publishes its own record. A checkout without it predates the manifest.
MANIFEST_PATH = os.path.join("evidence", "manifest.json")

# How this package's three buckets map onto the manifest's status vocabulary.
_BUCKET_STATUS: Dict[str, str] = {
  "validated": "validated",
  "written": "written",
  "known failure": "failed",
}


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


def _claims() -> List[tuple]:
  """(instrument, op, ValidatedRun, bucket) for every federated claim this package makes."""
  out: List[tuple] = []
  for key in sorted(FEDERATED):
    fed = FEDERATED[key]
    for op, run in sorted(fed.validated_ops.items()):
      out.append((key, op, run, "validated"))
    for op, run in sorted(fed.written_ops.items()):
      out.append((key, op, run, "written"))
    for op, run in sorted(fed.known_failures.items()):
      out.append((key, op, run, "known failure"))
  return out


def check_manifest(plr_tested_root: str) -> List[Check]:
  """Compare this package's claims against plr-tested's own evidence manifest.

  A missing manifest is reported as a failure rather than skipped. That is deliberate and
  it is the same rule this package applies everywhere else: the absence of a check is not a
  pass. A checkout with no manifest means these claims are unverified against their source,
  and reporting that as fine would be exactly the comfortable silence the manifest exists to
  remove.
  """
  root = os.path.expanduser(plr_tested_root)
  path = os.path.join(root, MANIFEST_PATH)

  if not os.path.isfile(path):
    return [
      Check(
        instrument="(manifest)",
        op=None,
        claim=f"plr-tested publishes {MANIFEST_PATH}",
        ok=False,
        detail=(
          f"no manifest at {path}. This checkout predates it, or is not plr-tested. Without "
          "it, every federated status here is an assertion about another repo that nothing "
          "can contradict; update the checkout to cross-check them."
        ),
      )
    ]

  try:
    with open(path, encoding="utf-8") as fh:
      data = json.load(fh)
  except (OSError, ValueError) as e:
    return [
      Check("(manifest)", None, f"{MANIFEST_PATH} parses", False, f"could not read it: {e}")
    ]

  # (instrument, op) -> the manifest's entry for it.
  published: Dict[tuple, dict] = {}
  for inst in data.get("instruments", []):
    for op in inst.get("operations", []):
      published[(inst.get("key"), op.get("op"))] = op

  out: List[Check] = []
  for key, op, run, bucket in _claims():
    entry = published.get((key, op))
    if entry is None:
      out.append(
        Check(
          instrument=key,
          op=op,
          claim="the operation is published in plr-tested's manifest",
          ok=False,
          detail=(
            f"this package claims {key}.{op} is {bucket}, but plr-tested's manifest does "
            "not record that operation at all. Either it was never published or the name "
            "differs; an unpublished claim is this package's word alone."
          ),
        )
      )
      continue

    expected = _BUCKET_STATUS[bucket]
    actual = entry.get("status")
    out.append(
      Check(
        instrument=key,
        op=op,
        claim=f"status agrees with plr-tested: {expected}",
        ok=actual == expected,
        detail=(
          f"this package calls {key}.{op} '{bucket}', which means status '{expected}'. "
          f"plr-tested's manifest says '{actual}'. The repo with the instrument wins; "
          "update this package."
        ),
      )
    )

    out.append(
      Check(
        instrument=key,
        op=op,
        claim="cites the same run card as plr-tested",
        ok=entry.get("script") == run.script,
        detail=(
          f"this package cites {run.script}; plr-tested's manifest cites "
          f"{entry.get('script')}."
        ),
      )
    )

    out.append(
      Check(
        instrument=key,
        op=op,
        claim=f"confirm token agrees with plr-tested: {run.confirm_token or 'none'}",
        ok=entry.get("confirm_token") == run.confirm_token,
        detail=(
          f"this package tells an operator to pass --confirm {run.confirm_token!r}; "
          f"plr-tested's manifest records {entry.get('confirm_token')!r}. One of them "
          "would refuse the run."
        ),
      )
    )

  # Operations plr-tested has proven that this package does not model. Not drift -- this
  # package deliberately models only what its reference protocols reach -- but worth
  # surfacing, because an unmodelled validated operation is capability the ledger is
  # silently declining to credit.
  unmodelled = sorted(
    f"{k}.{o}"
    for (k, o), entry in published.items()
    if entry.get("status") == "validated" and (k, o) not in {(k2, o2) for k2, o2, _r, _b in _claims()}
  )
  if unmodelled:
    out.append(
      Check(
        instrument="(coverage)",
        op=None,
        claim=f"{len(unmodelled)} validated operation(s) in plr-tested are not modelled here",
        ok=True,
        detail=", ".join(unmodelled),
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
