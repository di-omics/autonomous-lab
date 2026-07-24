# autonomous-lab

A laboratory intelligence layer for a real workcell: what can run without a human,
whether the available evidence permits it, what happened to the material, and what work
would improve the next run.

[plr-reverse-engineer](https://github.com/di-omics/plr-reverse-engineer) brings laboratory
instruments under PyLabRobot control one at a time.
[plr-tested](https://github.com/di-omics/plr-tested) contains orchestration that has been
exercised on physical hardware. This package joins those facts without overstating them.

It is four layers, each with a refusal that defines its boundary.

| layer | question | refusal |
| --- | --- | --- |
| capability | Can this step run at all? | A command is automated only when its resolved map says it is decoded. |
| evidence | Do the measurements justify proceeding? | A missing, unsourced, or unproducible measurement never becomes a pass. |
| provenance | What material and evidence would a result implicate? | A pooled result does not name a well unless an index was actually recorded. |
| learning | What should improve next? | The controller can propose setpoints and cannot alter the gates that judge them. |

```sh
pip install 'autonomous-lab @ git+https://github.com/di-omics/autonomous-lab'

autonomous-lab stock
autonomous-lab protocols
autonomous-lab ledger single_cell_genomics
autonomous-lab gaps
autonomous-lab gates
autonomous-lab provenance
autonomous-lab session single_cell_genomics
autonomous-lab observe --record run.jsonl --step wgs_prep_lysis
autonomous-lab control single_cell_genomics --record run.jsonl
autonomous-lab doctor --plr-tested ../plr-tested
```

## Capability

The ledger costs every protocol step against the resolved command map and any validated
run card for that exact operation. Instrument reputation does not transfer to an unwritten
step. A device can therefore have separate automated, supervised, written, manual, broken,
and blocked operations.

The single-cell genomics reference protocol includes the bench work a demonstration might
omit: sample loading, cartridge handling, pooling, flow-cell loading, and physical plate
hops. Its headless prefix stops at the first real dependency on an operator or an
undecoded command. Read-only preflight and run-folder operations do not make unreachable
downstream work look autonomous.

`autonomous-lab gaps` ranks instruments by protocol steps released, not by individual
commands. The reverse-engineering coverage gate applies to a complete map, so a
per-command score would imply progress that the runtime still refuses to use.

## Evidence gates

A `Criterion` cannot be constructed without a source. Its origin says whether the
threshold was transcribed from a citable record, is a tunable local value, requires
calibration, or is still undecided. Calibration and undecided origins block a hardware
decision.

The reference gate catalog defines metric names and where their measurements must come
from. It does not embed method thresholds. Those values belong to an operator-owned JSON
evidence profile:

```json
{
  "thermal_performance.maximum_setpoint_error": {
    "threshold": 0.5,
    "units": "instrument units",
    "source": "synthetic example; cite the qualification record and section",
    "origin": "transcribed"
  }
}
```

Use `autonomous-lab gates --evidence-profile profile.json` to inspect a profile. Omitted
entries stay visible as `unset`, report their required key, and make the catalog not ready
for hardware. Unknown keys and entries without a numeric threshold or source are refused.
`autonomous_lab.criteria.profile_keys()` lists the complete contract.

Evidence tiers are earned rather than declared:

- `modeled`: produced by a model or calculation
- `simulated`: exercised through orchestration without physical material
- `measured`: returned by a physical instrument with a qualifying run path
- `validated`: measured and accepted by the applicable evidence gates

The registry caps each claim at what the producing operation has actually demonstrated. A
number attributed to a failed read path is downgraded even when the caller labels it
measured.

`UNMEASURABLE` is distinct from `FAIL` and `ESCALATE`. It means the workcell cannot produce
the required number, or the request did not carry one. The permission layer reports which
case occurred so an operator receives either an engineering action or a request for the
missing measurement.

Where calibration data exists, `ConformalBand` provides finite-sample intervals. A
criterion passes only when the whole interval clears its threshold, fails only when the
whole interval misses, and escalates when the interval straddles it.

## Provenance

The material lineage records acquisition, derivation, split, pool, move, and consumption
events. Every event carries an operator, machine, or inferred witness, and the chain
reports its weakest witness.

Pooling is modeled as a loss of resolution rather than a transfer. Without a complete
index map, a downstream result implicates every contributor. With a recorded index for
every input, attribution can be recovered. A partial map is refused because silently
dropping unnamed inputs would overstate traceability.

```sh
autonomous-lab provenance
```

The command renders both indexed and unindexed reference lineages so the attribution
boundary is explicit.

## Run records

Every proposal, decision, refusal, and observed outcome can be written to an append-only
JSONL record. Each entry includes the digest of the previous entry. Editing, deleting, or
reordering an entry breaks `verify()`.

The hash chain proves internal consistency, not physical truth. A false observation can be
recorded consistently, and the author can rewrite an entire unanchored file. `seal()`
returns the head digest so another system can retain an external checkpoint.

`observe` verifies the chain before extending it:

```sh
autonomous-lab session single_cell_genomics --write-record run.jsonl
autonomous-lab observe --record run.jsonl --step wgs_prep_lysis
autonomous-lab observe --record run.jsonl --step wgs_prep_lysis --failed
```

## Proposal and permission

Anything may request an action. Only deterministic capability, evidence, and provenance
checks decide it.

```python
from autonomous_lab import Session

session = Session(workcell=workcell, lineage=lineage)
decision = session.request(step, proposer="scheduler")
```

The proposer is recorded and never consulted. Confidence, urgency, free-form notes, and
claimed authority do not alter the decision. A refused request writes an explicit receipt
with `commands_issued: 0`, `instrument_contacted: false`, and
`material_consumed: false`.

Each refusal also carries the concrete action that could change its answer. A `Session`
deduplicates those actions into work orders so related refusals do not create repeated
trips to the bench.

## Learning and control

The feedback layer reads outcomes from verified run records. A Beta-Binomial model reports
per-step reliability with credible intervals, and expected-waste ranking combines failure
probability with the amount of completed work at risk.

The controller trains only on evidence that earned the `measured` tier. Modeled and
simulated observations remain in the record but do not train its surrogate. Below the
minimum number of trustworthy observations it refuses to propose.

When enough evidence exists, the controller searches an operator-bounded design space and
returns a proposed setpoint with uncertainty. Criteria are frozen and read-only: the
controller has no method that can relax, replace, or override a gate.

## Hardware claims

Federated operation claims are hand-written assertions about another repository, so
`doctor` checks them against a local `plr-tested` checkout:

```sh
autonomous-lab doctor --plr-tested ../plr-tested
```

For each operation, it verifies that the declared run card exists and that any declared
confirmation token appears in the script. It deliberately cannot prove prose evidence
about what an operator observed on the bench.

Instrument inventory is derived from `plr_re.protocolmap.SEEDS`, which keeps registered
reverse-engineering playbooks aligned with the installed `plr-re` version.

## Reference protocols

- `single_cell_genomics`: Namocell sorting, STAR WGS preparation, ODTC PCR enrichment,
  STAR library handling, AVITI sequencing, and run-folder readout.
- `small_molecule_qc`: VIAFLO 96 serial dilution, Biotage V-10 solvent removal, and
  Agilent 6530 Q-TOF LC/MS.

Custom protocols declare `Step` objects and the `Artifact` objects they consume and
produce. A protocol that references an undeclared artifact or consumes material that
nothing produces is refused before costing.

## Safety

This package schedules, judges, records, and reports. It never actuates. Its execution path
performs only read-only operations such as USB enumeration, endpoint probes, and run-folder
inspection. Instrument movement remains behind the separate armed controls in the device
repositories and requires the hardware-specific supervision described there.

The workcell also respects the one-driver-process-per-instrument constraint. Competing
clients can contend for a device or steal callbacks, so a scheduler must not treat
independent steps as permission to open multiple drivers for the same instrument.

## Tests

```sh
pip install -e '.[dev]'
pytest
ruff check autonomous_lab tests
```

The suite is device-free. It tests the refusal boundaries: undecoded commands cannot be
declared automated, unsupported measurements cannot be promoted, unset profile values
cannot gate hardware, missing measurements do not become passes, pooled material cannot
claim unrecorded attribution, edited records fail verification, simulated observations do
not train the controller, and proposal wording cannot influence permission.
