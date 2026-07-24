# First pilot: one bounded low-input genomics workflow

The first commercial proof should not be "an autonomous lab." It should be one
scientifically meaningful workflow in one external lab that reduces coordination and
hands-on burden without lowering the lab's existing QC pass rate.

## Pilot contract

Choose a workflow with:

- scarce samples for which recovery and identity matter;
- a stable written protocol and named acceptance criteria;
- at least one instrument seam already validated or reachable read-only;
- a small number of recurring manual handoffs and failure modes;
- an existing QC baseline; and
- an operator who can explain the tacit stop/recover decisions.

Low-input genomics is the first wedge because the current portfolio spans the assay,
automation, and omics-analysis layers and already exposes the unsupported boundaries.

## Success criteria

Agree on these before the first pilot run:

| Dimension | Pilot metric |
| --- | --- |
| Sample identity | every material/result traces to an accessioned root sample |
| Provenance | every executed, manual, QC, and stop decision has a valid evidence event |
| Evidence integrity | every delivered run dossier verifies to one chain head |
| Scientific quality | existing lab QC pass rate is maintained; no weakened threshold |
| Automation honesty | zero steps execute past an unsupported or failed boundary |
| Operator burden | hands-on and coordination time measured against the current baseline |
| Recovery | named recurring failures produce an explicit stop or recovery handoff |
| Learning | only QC-qualified observations enter the next-design dataset |
| Traceability | a selected result can be replayed from sample through decision in minutes |

Targets should be set from the partner lab's observed baseline. The repository does not
invent a percentage improvement before measuring it.

## Phase 0: workflow and evidence contract

Deliver:

- one protocol version pinned to a commit or immutable artifact;
- sample/container/well manifest;
- workcell and instrument identities;
- acceptance rules, units, evidence floors, and recovery responses;
- list of physical handoffs;
- validation evidence for every claimed adapter;
- explicit unsupported and broken operations; and
- run-dossier schema.

Exit gate: the lab signs off that the plan describes the work it actually performs,
including the unflattering manual steps.

## Phase 1: shadow ledger

Run the existing process unchanged while Clair observes:

- register source materials and derived aliquots;
- record explicit input contribution quantities for every split, pool, or transformation;
- record manual actions, instrument outputs, moves, and custody;
- hash raw evidence artifacts;
- evaluate gates without controlling execution;
- reproduce the lab's existing release decision; and
- compare the generated dossier with the operator's record.

Exit gate: no sample-identity discrepancy and no false automatic pass.

## Phase 2: gated supervised execution

Enable only the operation-specific adapters that have independently passed their
validation ladder. Keep the operator present.

Clair may:

- perform zero-motion and read-only preflights;
- compile a verified run card;
- stop at the first manual or unsupported boundary;
- accept an operator attestation with evidence;
- resume from an explicit handoff; and
- generate the final run dossier.

Clair may not:

- treat simulation as measurement;
- infer completion from a file merely existing;
- use an instrument's general reputation for an unvalidated operation;
- retry ambiguous physical work automatically; or
- create an actuation permit from a model proposal.

Exit gate: the workflow completes with the same or better scientific QC and every
boundary is accounted for.

## Phase 3: advisory process improvement

Define one bounded objective such as:

- decision-quality unique molecules per dollar;
- hands-on minutes per passing library;
- sample consumed per decisionable result; or
- probability of clearing a predeclared release threshold.

Record real-unit design variables, costs, replicates, constraints, fault annotations,
and source evidence. Quarantine mechanical faults before fitting. Compare the advisory
policy with a preset baseline using held-out or prospective runs.

Every next design remains a proposal. A scientist reviews it, the normal protocol and
physical gates compile it into a run, and a separate permission boundary controls any
hardware action.

Exit gate: the policy produces a reproducible, evidence-backed improvement or correctly
refuses to claim one.

## Deliverables

The partner should receive:

- a versioned workflow and workcell manifest;
- sample/material lineage export;
- verified JSONL evidence ledger and chain head;
- human-readable run dossier;
- QC decision table with source-event links;
- exception and recovery report;
- autonomy/headless-prefix report;
- qualified learning dataset with quarantined rows preserved separately; and
- next-design proposal with uncertainty and no execution permission.

## Productization path

Patterns that repeat across the first integrations become the product:

- validated instrument capability descriptors;
- assay-specific acceptance and recovery policies;
- standard sample/material and evidence contracts;
- instrument/resource leases;
- operator handoff and reconciliation flows;
- reusable run dossiers; and
- process-optimization interfaces.

The implementation work is the wedge. The compounding asset is the verified mapping
between scientific intent, physical execution, observed evidence, and recovery.
