# Evidence model

Clair makes the origin and strength of a claim first-class. The same numeric value means
something different when it came from a mathematical surface, a simulator, a reader
export, or a separately validated hardware path.

## Evidence levels

| Level | Allowed claim | Not allowed |
| --- | --- | --- |
| `modeled` | A model or deterministic computation produced this value | Physical execution or measurement |
| `simulated_execution` | A software/device simulator produced this value | Contact with a physical instrument |
| `measured` | A value was read from the physical world | The integration itself is validated |
| `hardware_validated` | A physical measurement used a separately validated integration | General validity outside that validation scope |

The levels form a minimum-evidence ordering. A gate configured to require `measured`
evidence holds on `modeled` and `simulated_execution`; it does not silently upgrade them.

Evidence strength is only one axis. A measured value can still fail assay QC, have the
wrong unit, belong to the wrong sample, or come from an expired calibration. The current
gate checks material linkage, unit, evidence floor, and numeric comparator independently;
calibration validity windows remain a production gap.

## Event envelope

Every event has:

```json
{
  "schema_version": 1,
  "sequence": 0,
  "event_id": "evt_...",
  "recorded_at": "2026-07-24T00:00:00Z",
  "run_id": "run_...",
  "kind": "measurement_recorded",
  "actor": "reader-adapter",
  "evidence_level": "measured",
  "payload": {},
  "previous_hash": "0000...",
  "event_hash": "abcd..."
}
```

The payload is restricted to JSON scalars, objects, and arrays. NaN and Infinity are
refused because they do not have portable canonical JSON representations.

The canonical schema is
[`schemas/evidence-event.schema.json`](../schemas/evidence-event.schema.json).

## Hash chain

`event_hash` is SHA-256 over canonical JSON containing every field except
`event_hash`. `previous_hash` is the prior event's digest; the first event points to 64
zeroes.

Verification detects:

- a changed event body;
- deleted or inserted events inside the chain;
- event reordering;
- duplicate event IDs;
- broken sequence numbers; and
- unsupported schema versions.

Deleting a suffix produces a different but internally valid head. Detecting that requires
comparison with a previously signed or externally anchored expected head. The chain also
does not prove who wrote an event. Production deployments should sign and externally
anchor chain heads, authenticate actors, and protect the storage layer.

## Raw artifacts

The ledger should not contain large or sensitive raw data. A current scalar measurement
may carry the SHA-256 digest of its external source bytes. A production artifact
reference should additionally require:

- a stable artifact URI or object ID;
- media type and schema/version;
- producing instrument, run, step, sample/material, and command IDs; and
- the analysis/code version that derived a scalar.

`file_digest(path)` is provided for local SHA-256 calculation.

## QC decisions

A `gate_evaluated` event records:

- gate and material IDs;
- the canonical comparator/threshold/unit/evidence policy and its digest;
- overall pass/fail/hold/error result;
- the result of every rule;
- measurement and source-event IDs;
- observed values, units, and evidence levels; and
- a single `allowed` boolean derived only from a complete pass.

Missing data produces `hold`. Unit mismatch produces `error`. A value outside the
comparator's allowed range produces `fail`. None authorize downstream use. Before an
observation can train the
optimizer, replay resolves the latest pre-gate measurements and recomputes every rule
and the overall decision from the sealed policy.

## Learning qualification

An observation can be:

- `qualified`: passed its QC gate and is eligible for training subject to the
  optimizer's configured evidence floor; or
- `quarantined`: retained for diagnosis but excluded from training.

Mechanical faults, incomplete readouts, failed control quality, and unresolved sample
identity belong in quarantine. A legitimate but scientifically infeasible result can
still be qualified and carry `feasible: false` so the model learns the constraint.
Feasibility is separate from QC qualification. The current kernel accepts explicitly
referenced, externally evaluated boolean constraint attestations: each has a stable
constraint ID, `boolean` unit, a `0` or `1` value, and a matching boolean label. Clair
validates those fields, their evidence, and their freshness before an observation is
sealed. It does not reconstruct the upstream scientific rule or threshold; a constraint
that needs native threshold replay should be expressed as a deterministic gate until a
canonical constraint-policy type is added.

Each proposal records:

- bounded values;
- objective and direction policy;
- source observation event IDs;
- policy and dataset digests;
- predicted objective;
- feasibility estimate plus whether it is calibrated;
- uncertainty plus whether it is calibrated; and
- `execution_allowed: false`.

The proposal can become input to a separately validated plan. It cannot become a robot
command directly.
