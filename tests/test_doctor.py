"""Tests for the federated-claim checker.

The checker exists because `validated_ops` is hand-written prose about a repo this one
does not control. These tests prove it actually catches the two ways that drifts: a run
card that moved, and a confirm token that no longer appears in it. A checker that passed
unconditionally would be worse than none, because it would launder the assertion.
"""

from __future__ import annotations

from autonomous_lab.doctor import check_federated, render
from autonomous_lab.registry import FEDERATED, FederatedSpec, Role, ValidatedRun


def _fake_root(tmp_path, script_rel, body, entry_rel="hamilton-star/run_on_pi.sh"):
  script = tmp_path / script_rel
  script.parent.mkdir(parents=True, exist_ok=True)
  script.write_text(body, encoding="utf-8")
  entry = tmp_path / entry_rel
  entry.parent.mkdir(parents=True, exist_ok=True)
  entry.write_text("#!/bin/sh\n", encoding="utf-8")
  return tmp_path


def _one_instrument(monkeypatch, spec):
  monkeypatch.setattr("autonomous_lab.doctor.FEDERATED", {spec.key: spec})


def _spec(script="s/run.py", token="RUN_THING"):
  return FederatedSpec(
    key="star",
    device="Hamilton Microlab STAR",
    role=Role.LIQUID_HANDLING,
    repo="di-omics/plr-tested",
    entry="hamilton-star/run_on_pi.sh",
    validated="x",
    validated_ops={
      "thing": ValidatedRun(script=script, confirm_token=token, evidence="watched it run")
    },
  )


def test_a_missing_checkout_is_reported_not_crashed():
  checks = check_federated("/nowhere/at/all")
  assert len(checks) == 1
  assert not checks[0].ok


def test_claims_hold_when_the_run_card_and_token_are_really_there(tmp_path, monkeypatch):
  _one_instrument(monkeypatch, _spec())
  root = _fake_root(tmp_path, "s/run.py", 'parser.add_argument("--confirm")\nTOKEN = "RUN_THING"\n')
  checks = check_federated(str(root))
  assert all(c.ok for c in checks)
  assert "all 3 checkable claims hold" in render(checks)


def test_a_renamed_run_card_is_caught(tmp_path, monkeypatch):
  """The exact drift the checker exists for: plr-tested renames a script and the ledger
  goes on citing a run card that is not there."""
  _one_instrument(monkeypatch, _spec(script="s/moved_away.py"))
  root = _fake_root(tmp_path, "s/run.py", 'TOKEN = "RUN_THING"\n')
  checks = check_federated(str(root))
  bad = [c for c in checks if not c.ok]
  assert len(bad) == 1
  assert "run card exists" in bad[0].claim
  assert "DRIFT" in render(checks)


def test_a_stale_confirm_token_is_caught(tmp_path, monkeypatch):
  """The subtler drift: the script is there, but the token the ledger tells an operator
  to type is not in it, so the run would refuse."""
  _one_instrument(monkeypatch, _spec(token="RUN_STALE_TOKEN"))
  root = _fake_root(tmp_path, "s/run.py", 'TOKEN = "RUN_THING"\n')
  checks = check_federated(str(root))
  bad = [c for c in checks if not c.ok]
  assert len(bad) == 1
  assert "confirm token" in bad[0].claim
  assert "would refuse" in bad[0].detail


def test_an_op_with_no_token_skips_the_token_check(tmp_path, monkeypatch):
  """The ODTC run card has no confirm gate. Absence of a token is not drift."""
  _one_instrument(monkeypatch, _spec(token=None))
  root = _fake_root(tmp_path, "s/run.py", "print('hi')\n")
  checks = check_federated(str(root))
  assert all(c.ok for c in checks)
  assert not any("confirm token" in c.claim for c in checks)


def test_every_shipped_federated_op_declares_a_run_card():
  """A validated_ops entry with no script would be an unverifiable claim, which is the
  thing this package refuses to make."""
  for key, fed in FEDERATED.items():
    assert fed.entry, f"{key} has no entry"
    for op, run in fed.validated_ops.items():
      assert run.script, f"{key}.{op} claims validation with no run card"
      assert run.evidence, f"{key}.{op} claims validation with no evidence"
