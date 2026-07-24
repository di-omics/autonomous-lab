"""Walk a protocol, run what is real, and stop honestly at the first thing that is not.

The executor does one thing, and refusing to actuate is the whole design:

  It performs the zero-decode steps. Enumerating a USB bus, probing a port, reading a run
  folder. These are read-only, need no recovered command set, and work today, so an
  armed run does them for real and returns the data.

  It stops at the first step that cannot run headless, and says why. It does not skip
  ahead to the next automatable step, and it does not simulate the blocked one. A run
  that pretended to sort a plate and then truthfully read a run folder would be worse
  than useless: it would look like a working pipeline.

Actuation is deliberately out of scope here. Anything that moves an instrument goes
through that instrument's own controller and its own arming switches; this layer schedules
and reports, it does not gain a second path to hardware that bypasses those guards.
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .evidence import EventKind, EvidenceLedger, EvidenceLevel, digest, file_digest
from .ledger import Ledger, build_ledger
from .model import Protocol, Step, Verdict, ZeroDecodeOp
from .registry import FEDERATED, registry
from .version import __version__
from .workcell import Workcell

logger = logging.getLogger("plr_re")
_NO_RESULT = object()


@dataclass
class StepResult:
  """What actually happened for one step."""

  step: Step
  verdict: Verdict
  executed: bool
  data: Optional[Any] = None
  note: str = ""


@dataclass
class Handoff:
  """The card handed to a human when the run stops.

  It names the step, why the machine cannot do it, and -- when the blocker is a missing
  command set rather than a physical act -- the bench work that would remove the stop.
  """

  step: Step
  reason: str
  blocking: List[str] = field(default_factory=list)
  gap_closer: str = ""

  def render(self) -> str:
    reg = registry()
    device = reg[self.step.instrument].device if self.step.instrument in reg else (
      FEDERATED[self.step.instrument].device if self.step.instrument in FEDERATED else self.step.instrument
    )
    lines = [
      "-- run stopped: a human is needed --",
      f"  instrument : {device}",
      f"  step       : {self.step.summary}",
      f"  reason     : {self.reason}",
    ]
    if self.blocking:
      lines.append(f"  undecoded  : {', '.join(self.blocking)}")
    if self.gap_closer:
      lines.append(f"  to unblock : {self.gap_closer}")
    return "\n".join(lines)


@dataclass
class RunReport:
  protocol: Protocol
  ledger: Ledger
  results: List[StepResult]
  handoff: Optional[Handoff]
  run_id: Optional[str] = None
  evidence_head: Optional[str] = None
  dry_run: bool = False

  @property
  def completed(self) -> int:
    return sum(1 for r in self.results if r.executed)

  def render(self) -> str:
    lines = [f"protocol: {self.protocol.name}  ({len(self.protocol.steps)} steps)", ""]
    for i, r in enumerate(self.results, 1):
      mark = "ran " if r.executed else "----"
      lines.append(f"  {i:2d}. [{mark}] {r.step.summary}")
      if r.note:
        lines.append(f"          {r.note}")
    lines.append("")
    if self.handoff is not None:
      lines.append(self.handoff.render())
      lines.append("")
      lines.append(
        f"completed {self.completed} of {len(self.protocol.steps)} steps unattended "
        f"before stopping."
      )
    elif self.dry_run:
      lines.append(
        f"previewed all {len(self.protocol.steps)} steps; executed 0."
      )
    else:
      lines.append(f"completed all {self.completed} steps unattended.")
    return "\n".join(lines)


# What would remove each blocker. Keyed by instrument; deliberately specific, because a
# handoff card that says "decode the protocol" helps nobody standing at a bench.
_GAP_CLOSERS: Dict[str, str] = {
  "facsmelody": (
    "resolve the transport first (it is the only instrument here with no prior), then "
    "capture FACSChorus driving one sort action at a time and decode the frames"
  ),
  "agilent6530": (
    "for contact closure: meter the APG rear connector, fill in a pin map, and confirm "
    "Ready with `agilent scan`. For LAN control: capture the MassHunter/ICF traffic"
  ),
  "biotage_v10": (
    "settle the transport (the code seeds serial, the playbook argues for an Ethernet "
    "sniff first), then capture the Control Centre driving one setpoint at a time"
  ),
  "element_aviti": (
    "capture the AvitiOS UI traffic to a HAR and run `decode har` to separate the "
    "control calls from the status polling"
  ),
  "namocell": (
    "confirm USB-serial vs raw bulk with `namocell discover`, then capture the bundled "
    "PC driving one sort at a time"
  ),
  "viaflo96": (
    "capture VIALINK uploading one program, then diff two programs that differ in a "
    "single step to decode the serialization"
  ),
}


class Executor:
  """Runs a protocol as far as it honestly goes.

  armed=False previews every step and touches nothing. armed=True performs supported
  read-only operations for real; it never actuates anything, on any setting.
  """

  def __init__(
    self,
    workcell: Optional[Workcell] = None,
    armed: bool = False,
    evidence: Optional[EvidenceLedger] = None,
    run_id: Optional[str] = None,
    actor: str = "autonomous-lab",
  ):
    if not actor.strip():
      raise ValueError("executor actor must not be empty")
    self.workcell = workcell or Workcell.default()
    self.armed = armed
    self.evidence = evidence
    self.run_id = run_id
    self.actor = actor

  def run(self, protocol: Protocol) -> RunReport:
    run_id = self.run_id or f"run_{uuid.uuid4().hex}"
    if self.evidence is not None and self.evidence.by_run(run_id):
      raise ValueError(
        f"run_id '{run_id}' already exists in the evidence ledger; "
        "use a new ID for a new physical attempt"
      )
    map_keys = _protocol_map_keys(protocol, self.workcell)
    run_workcell = self.workcell.snapshot(map_keys)
    protocol_map_digests = {
      key: _protocol_map_digest(run_workcell.protocol_map(key)) for key in map_keys
    }
    control_dependency = _plr_re_identity()
    kernel_identity = _autonomous_lab_identity()
    federated_dependency = _federated_identity(protocol, run_workcell)
    ledger = build_ledger(protocol, run_workcell)
    if federated_dependency != _federated_identity(protocol, run_workcell):
      raise RuntimeError(
        "federated run-card files changed while capability claims were costed; "
        "retry from a stable checkout"
      )
    results: List[StepResult] = []
    handoff: Optional[Handoff] = None
    self._record(
      run_id,
      EventKind.RUN_STARTED,
      EvidenceLevel.MODELED,
      {
        "protocol": protocol.name,
        "protocol_digest": _protocol_digest(protocol),
        "workcell": run_workcell.name,
        "workcell_digest": _workcell_digest(
          run_workcell,
          protocol_map_digests,
          control_dependency,
          kernel_identity,
          federated_dependency,
        ),
        "protocol_map_digests": protocol_map_digests,
        "control_dependency": control_dependency,
        "kernel_identity": kernel_identity,
        "federated_dependency": federated_dependency,
        "armed": self.armed,
        "actuation_allowed": False,
      },
    )

    for index, row in enumerate(ledger.rows, 1):
      self._record(
        run_id,
        EventKind.PERMISSION_EVALUATED,
        EvidenceLevel.MODELED,
        {
          "step_index": index,
          "instrument": row.step.instrument,
          "op": row.step.op,
          "verdict": row.verdict.value,
          "headless": row.verdict.headless,
          "capability_ready": row.verdict.headless,
          "execution_allowed": bool(self.armed and row.verdict.headless),
          "actuation_allowed": False,
          "reason": row.reason,
          "blocking": list(row.blocking),
        },
      )
      if not row.verdict.headless:
        handoff = Handoff(
          step=row.step,
          reason=row.reason,
          blocking=list(row.blocking),
          gap_closer=(
            _GAP_CLOSERS.get(row.step.instrument, "")
            if row.verdict is Verdict.BLOCKED and row.blocking
            else ""
          ),
        )
        self._record(
          run_id,
          EventKind.RUN_STOPPED,
          EvidenceLevel.MODELED,
          {
            "step_index": index,
            "instrument": row.step.instrument,
            "op": row.step.op,
            "reason": row.reason,
            "completed": sum(1 for result in results if result.executed),
          },
        )
        break

      if not self.armed:
        results.append(
          StepResult(row.step, row.verdict, executed=False, note="[dry-run] would run; nothing sent")
        )
        continue

      self._record(
        run_id,
        EventKind.STEP_STARTED,
        EvidenceLevel.MODELED,
        {
          "step_index": index,
          "instrument": row.step.instrument,
          "op": row.step.op,
          "read_only": True,
        },
      )
      data: Any = _NO_RESULT
      try:
        data = self._perform(row.step, run_workcell)
        _require_successful_read(row.step, data)
      except Exception as e:
        # Whether this is a configuration/adapter failure or a structured negative bench
        # result, stop and seal it. Only a returned result earns MEASURED evidence.
        results.append(StepResult(row.step, row.verdict, executed=False, note=f"failed: {e}"))
        handoff = Handoff(step=row.step, reason=f"a read-only preflight failed: {e}")
        failure_level = (
          EvidenceLevel.MEASURED
          if data is not _NO_RESULT
          else EvidenceLevel.MODELED
        )
        failure_payload: Dict[str, object] = {
          "step_index": index,
          "instrument": row.step.instrument,
          "op": row.step.op,
          "error_type": type(e).__name__,
          "error": str(e),
        }
        if data is not _NO_RESULT:
          failure_payload.update(
            {
              "result": data,
              "result_digest": _result_digest(data),
              "claim_scope": _read_claim_scope(row.step),
              "identity_verified": False,
            }
          )
        self._record(
          run_id,
          EventKind.STEP_FAILED,
          failure_level,
          failure_payload,
        )
        self._record(
          run_id,
          EventKind.RUN_STOPPED,
          failure_level,
          {
            "step_index": index,
            "instrument": row.step.instrument,
            "op": row.step.op,
            "reason": f"a read-only preflight failed: {e}",
            "completed": sum(1 for result in results if result.executed),
          },
        )
        break
      results.append(StepResult(row.step, row.verdict, executed=True, data=data, note=_summarize(data)))
      self._record(
        run_id,
        EventKind.STEP_COMPLETED,
        EvidenceLevel.MEASURED,
        {
          "step_index": index,
          "instrument": row.step.instrument,
          "op": row.step.op,
          "summary": _summarize(data),
          "result": data,
          "result_digest": _result_digest(data),
          "identity_verified": False,
          "claim_scope": _read_claim_scope(row.step),
        },
      )

    if handoff is None:
      self._record(
        run_id,
        EventKind.RUN_COMPLETED,
        (
          EvidenceLevel.MEASURED
          if any(result.executed for result in results)
          else EvidenceLevel.MODELED
        ),
        {
          "completed": sum(1 for result in results if result.executed),
          "step_count": len(protocol.steps),
          "dry_run": not self.armed,
        },
      )
    return RunReport(
      protocol=protocol,
      ledger=ledger,
      results=results,
      handoff=handoff,
      run_id=run_id,
      evidence_head=self.evidence.head_hash if self.evidence is not None else None,
      dry_run=not self.armed,
    )

  def _record(
    self,
    run_id: str,
    kind: EventKind,
    evidence_level: EvidenceLevel,
    payload: Dict[str, object],
  ) -> None:
    if self.evidence is None:
      return
    self.evidence.append(
      run_id=run_id,
      kind=kind,
      actor=self.actor,
      evidence_level=evidence_level,
      payload=payload,
    )

  # -- read-only operations, for real ----------------------------------------

  def _perform(self, step: Step, workcell: Optional[Workcell] = None) -> Any:
    resolved_workcell = workcell or self.workcell
    op = step.op
    cfg = resolved_workcell.instruments.get(step.instrument)
    endpoint = cfg.endpoint if cfg else None

    if op == ZeroDecodeOp.DISCOVER_USB.value:
      from plr_re.instruments.namocell import discover_usb

      return discover_usb()

    if op == ZeroDecodeOp.PROBE_TCP.value:
      from plr_re.instruments.agilent6530 import probe_module

      if not endpoint:
        raise RuntimeError(f"no endpoint for '{step.instrument}'; set one in the workcell")
      host, port = _split_endpoint(endpoint, default_port=23)
      return probe_module(host, port=port)

    if op == ZeroDecodeOp.PROBE_HTTP.value:
      from plr_re.instruments.element_aviti import probe_services

      if not endpoint:
        raise RuntimeError(f"no endpoint for '{step.instrument}'; set one in the workcell")
      # Honor a configured port, and sweep the candidate list only when none was given.
      host, port = _split_endpoint(endpoint, default_port=0)
      return probe_services(host, ports=[port] if port else None)

    if op == ZeroDecodeOp.WATCH_RUN_FOLDER.value:
      from plr_re.instruments.element_aviti import RunFolder

      run_dir = step.params.get("run_dir")
      if not run_dir:
        raise RuntimeError("no run_dir given to watch")
      if not os.path.isdir(str(run_dir)):
        raise RuntimeError(f"run_dir '{run_dir}' is not an existing directory")
      return RunFolder(str(run_dir)).state()

    raise RuntimeError(
      f"executor refuses ProtocolMap command '{op}'; a decode artifact cannot "
      "independently prove that its request bytes are non-actuating"
    )


def _protocol_digest(protocol: Protocol) -> str:
  return digest(
    {
      "name": protocol.name,
      "summary": protocol.summary,
      "artifacts": [
        {
          "name": artifact.name,
          "physical": artifact.physical,
          "note": artifact.note,
        }
        for artifact in protocol.artifacts
      ],
      "steps": [
        {
          "instrument": step.instrument,
          "op": step.op,
          "summary": step.summary,
          "consumes": list(step.consumes),
          "produces": list(step.produces),
          "params": step.params,
          "manual_reason": step.manual_reason,
        }
        for step in protocol.steps
      ],
    }
  )


def _protocol_map_keys(protocol: Protocol, workcell: Workcell) -> tuple:
  """Maps that can actually influence this run's costing.

  Manual steps, absent instruments, and built-in zero-decode reads do not consult a
  ProtocolMap. Resolving their map files would make irrelevant stale configuration
  capable of preventing an honest MANUAL/BLOCKED report.
  """
  known = registry()
  zero_decode = {op.value for op in ZeroDecodeOp}
  keys = set()
  for step in protocol.steps:
    config = workcell.instruments.get(step.instrument)
    if (
      step.instrument in known
      and config is not None
      and config.present
      and not step.manual_reason
      and step.op not in zero_decode
    ):
      keys.add(step.instrument)
  return tuple(sorted(keys))


def _workcell_digest(
  workcell: Workcell,
  protocol_map_digests: Dict[str, str],
  control_dependency: Dict[str, str],
  kernel_identity: Dict[str, str],
  federated_dependency: Dict[str, object],
) -> str:
  return digest(
    {
      "name": workcell.name,
      "instruments": {
        key: {
          "present": config.present,
          "map_path": config.map_path,
          "endpoint": config.endpoint,
          "note": config.note,
        }
        for key, config in sorted(workcell.instruments.items())
      },
      "federated": list(workcell.federated),
      "plr_tested_root": workcell.plr_tested_root,
      "protocol_map_digests": protocol_map_digests,
      "control_dependency": control_dependency,
      "kernel_identity": kernel_identity,
      "federated_dependency": federated_dependency,
    }
  )


def _protocol_map_digest(protocol_map: object) -> str:
  """Seal the exact map object used to cost the run."""
  return digest(asdict(protocol_map))


def _plr_re_identity() -> Dict[str, str]:
  """Identify the control code whose readers and map semantics authorize a run."""
  import plr_re

  root = Path(plr_re.__file__).resolve().parent
  source_hashes = {
    str(path.relative_to(root)): file_digest(str(path))
    for path in sorted(root.rglob("*.py"))
    if path.is_file()
  }
  return {
    "package": "plr-re",
    "version": str(getattr(plr_re, "__version__", "unknown")),
    "source_digest": digest(source_hashes),
  }


def _autonomous_lab_identity() -> Dict[str, str]:
  """Seal the kernel source that computed authorization and evidence semantics."""
  root = Path(__file__).resolve().parent
  source_hashes = {
    str(path.relative_to(root)): file_digest(str(path))
    for path in sorted(root.rglob("*.py"))
    if path.is_file()
  }
  return {
    "package": "autonomous-lab",
    "version": __version__,
    "source_digest": digest(source_hashes),
  }


def _federated_identity(
  protocol: Protocol, workcell: Workcell
) -> Dict[str, object]:
  """Seal every external run-card file consulted while costing this protocol."""
  root_value = workcell.plr_tested_root
  if root_value is None:
    return {
      "repository": "di-omics/plr-tested",
      "configured": False,
      "root": None,
      "files": {},
      "source_digest": digest({}),
    }

  root = os.path.abspath(os.path.expanduser(root_value))
  relevant = set()
  for step in protocol.steps:
    if step.manual_reason or step.instrument not in FEDERATED:
      continue
    if step.instrument not in workcell.federated:
      continue
    spec = FEDERATED[step.instrument]
    relevant.add(spec.entry)
    run = (
      spec.known_failures.get(step.op)
      or spec.written_ops.get(step.op)
      or spec.validated_ops.get(step.op)
    )
    if run is not None:
      relevant.add(run.script)

  files: Dict[str, object] = {}
  for relative in sorted(relevant):
    path = os.path.join(root, relative)
    readable = os.path.isfile(path) and os.access(path, os.R_OK)
    files[relative] = {
      "readable": readable,
      "sha256": file_digest(path) if readable else None,
    }
  return {
    "repository": "di-omics/plr-tested",
    "configured": True,
    "root": root,
    "files": files,
    "source_digest": digest(files),
  }


def _result_digest(data: Any) -> str:
  """Digest the compact structured result sealed into step evidence."""
  if isinstance(data, bytes):
    return hashlib.sha256(data).hexdigest()
  if data is None or isinstance(data, (str, int, float, bool, dict, list, tuple)):
    try:
      return digest(data)
    except TypeError:
      pass
  body = getattr(data, "body", None)
  status = getattr(data, "status", None)
  if isinstance(body, bytes):
    return digest(
      {
        "type": type(data).__name__,
        "status": status,
        "body_sha256": hashlib.sha256(body).hexdigest(),
      }
    )
  return digest(
    {
      "type": type(data).__name__,
      "summary": _summarize(data),
    }
  )


def _split_endpoint(endpoint: str, default_port: int) -> tuple:
  """Split 'host:port' into (host, port). A bare host keeps the default.

  A port that is present but unparseable raises rather than falling through. Returning
  the whole string as the host would turn a typo into a connection attempt against a
  hostname that cannot resolve, and the resulting "unreachable" would read as a fact
  about the instrument instead of a fact about the config. IPv6 must be bracketed.
  """
  ep = endpoint.split("//")[-1].rstrip("/")
  if ep.startswith("["):  # [::1] or [::1]:8080
    host, _, rest = ep.partition("]")
    host = host[1:]
    if rest.startswith(":"):
      port = rest[1:]
      if not port.isdigit():
        raise ValueError(f"endpoint '{endpoint}' has a non-numeric port '{port}'")
      return host, int(port)
    return host, default_port
  if ep.count(":") > 1:
    raise ValueError(
      f"endpoint '{endpoint}' is ambiguous; bracket an IPv6 address as '[::1]:8080'"
    )
  if ":" in ep:
    host, port = ep.rsplit(":", 1)
    if not port.isdigit():
      raise ValueError(f"endpoint '{endpoint}' has a non-numeric port '{port}'")
    return host, int(port)
  return ep, default_port


def _require_successful_read(step: Step, data: Any) -> None:
  """Turn a negative read result into a failed preflight.

  The dependency readers deliberately return structured negative answers for ordinary
  connectivity failures. Those are useful diagnostic results, but they are not
  successful readiness checks and must stop the run just like an exception would.
  """
  if step.op == ZeroDecodeOp.DISCOVER_USB.value:
    if not isinstance(data, list):
      raise RuntimeError("USB discovery returned an invalid result")
    candidates = [
      row
      for row in data
      if isinstance(row, dict) and row.get("likely_control") is True
    ]
    if not candidates:
      raise RuntimeError("USB discovery found no likely serial control-link candidate")
    return

  if step.op == ZeroDecodeOp.PROBE_TCP.value:
    if not isinstance(data, dict) or data.get("reachable") is not True:
      detail = data.get("error") if isinstance(data, dict) else None
      suffix = f": {detail}" if isinstance(detail, str) and detail else ""
      raise RuntimeError(f"TCP probe did not reach the configured endpoint{suffix}")
    return

  if step.op == ZeroDecodeOp.PROBE_HTTP.value:
    if not isinstance(data, list):
      raise RuntimeError("HTTP probe returned an invalid result")
    if not any(
      isinstance(row, dict)
      and row.get("open") is True
      and type(row.get("http_status")) is int
      and 100 <= row["http_status"] <= 599
      for row in data
    ):
      raise RuntimeError(
        "HTTP probe received no HTTP response from the configured endpoint"
      )
    return

  if step.op == ZeroDecodeOp.WATCH_RUN_FOLDER.value:
    if not isinstance(data, dict):
      raise RuntimeError("run-folder reader returned an invalid result")
    if data.get("state") != "complete":
      raise RuntimeError(
        f"run completion is not evidenced; state is {data.get('state')!r}"
      )
    outcome = data.get("outcome")
    if (
      data.get("has_uploaded") is not True
      or not isinstance(outcome, str)
      or not outcome.strip()
    ):
      raise RuntimeError(
        "run completion is not evidenced by a parsed upload marker with an outcome"
      )
    return

  raise RuntimeError(f"no success predicate for read-only operation '{step.op}'")


def _read_claim_scope(step: Step) -> str:
  """The narrow fact a successful generic read establishes."""
  return {
    ZeroDecodeOp.DISCOVER_USB.value: (
      "a likely serial control-link candidate was enumerated; "
      "instrument identity is unconfirmed"
    ),
    ZeroDecodeOp.PROBE_TCP.value: (
      "the configured socket accepted a TCP connection; instrument identity is "
      "unconfirmed"
    ),
    ZeroDecodeOp.PROBE_HTTP.value: (
      "the configured endpoint returned an HTTP status; service and instrument "
      "identity are unconfirmed"
    ),
    ZeroDecodeOp.WATCH_RUN_FOLDER.value: (
      "the configured folder contained a parsed completion marker and outcome; "
      "instrument identity is unconfirmed"
    ),
  }[step.op]


def _summarize(data: Any) -> str:
  """One line of what a read returned, for the run report."""
  if isinstance(data, list):
    return f"{len(data)} result(s)"
  if isinstance(data, dict):
    if "state" in data:
      return f"state={data['state']} outcome={data.get('outcome')}"
    if "reachable" in data:
      return f"reachable={data['reachable']} banner={data.get('banner', '')[:40]!r}"
  return ""
