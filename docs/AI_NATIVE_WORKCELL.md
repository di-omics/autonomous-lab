# Making an existing laboratory AI-native

The core bet is that laboratories do not need to replace every useful instrument with a
new product marketed as AI-native. They need a trustworthy translation layer between
domain intent and the heterogeneous hardware already on the bench.

That translation layer has six jobs:

1. expose the instrument through a guarded Python interface
2. describe actions and results with typed contracts an agent can discover
3. observe visible and non-visible physical state with the right evidence source
4. encode the domain expert's acceptance criteria and failure responses
5. coordinate robots, instruments, cameras, samples, and stations without double-booking
6. retain every action, observation, decision, and outcome as operational memory

This document is an architecture target. It is not a claim that the public portfolio has
completed a wet end-to-end autonomous workflow.

## Portfolio architecture

| Layer | Responsibility | Public implementation |
| --- | --- | --- |
| Instrument adaptation | Capture, decode, map, and guarded-replay commands for hardware with no usable API | [plr-reverse-engineer](https://github.com/di-omics/plr-reverse-engineer) |
| Physical evidence | Preserve exact run cards, confirmation tokens, observed successes, and known failures | [plr-tested](https://github.com/di-omics/plr-tested) |
| Typed agent boundary | Attach process-local run, task, policy, operation, and registered-sample context to typed PyLabRobot tools; record intent before driver construction in an `fsync`-backed JSONL hash chain; default to simulation; require an exact tool allowlist plus operator confirmation for real mutation | [plr-mcp](https://github.com/di-omics/plr-mcp) |
| Spatial and lab vision | Exercise synthetic imaging QC and release decisions with expected-versus-observed identity, SHA-256 manifests, event-chain verification, and `RELEASE`/`RETRY`/`HOLD`; keep identity and provenance failures expert-only | [spatial-flow](https://github.com/di-omics/spatial-flow), [lab-cv](https://github.com/di-omics/lab-cv) |
| Robot execution | Validate typed labware moves in simulation with software-visible pre/postconditions, at most three attempts, halt/recheck recovery for transient faults, refusal to replay partial picks, and hash-linked traces | [plr-lab-robot](https://github.com/di-omics/plr-lab-robot) |
| Laboratory intelligence | Evaluate exact expert policy and contract fingerprints, bind evidence to the task sample, share process-local workcell leases, issue expiring permits, track sample provenance, quarantine ambiguity, and audit the run | [autonomous-lab](https://github.com/di-omics/autonomous-lab) |

The layers are separable on purpose. A better vision model cannot waive an assay-QC
gate. A complete command map cannot prove a biological endpoint. A model proposal cannot
claim the robot or instrument resource before deterministic permission.

These repositories implement compatible, reviewable slices of the architecture. They
are not yet wired into one deployed wet-lab runtime: `plr-mcp` carries identities and
tool intent but does not evaluate sample-state policy, `spatial-flow` uses synthetic
images rather than a trained production CV model, and `plr-lab-robot` has no robot-
hardware validation claim.

## The domain expert is the system designer

The expert does more than write a protocol. They define the executable envelope around
the protocol:

- what evidence must exist before an action
- which source is allowed to establish each fact
- acceptable ranges, controls, and benchmark limits
- whether a failure is retryable, recoverable, terminal, or ambiguous
- the exact recovery and its bounded attempt budget
- which sample states remain usable after the failure
- what result permits the next step
- which unknowns require a person rather than a model guess

In code, this becomes a versioned `ExpertPolicy`, not hidden prompt prose. A policy names
its owner, evidence gates, allowed sources, freshness window, rationale, failure action,
and recovery ID. Its canonical SHA-256 fingerprint is recorded with every decision. A
fingerprinted `OperationContract` then binds the pre- and postcondition policies to one
operation ID, state transition, finite retry/recovery budgets, mandatory resource set,
approved adapters, and named recovery bindings. Every gate subject must be either
`$sample` or an exact leased resource, and both policies must include a `$sample` gate;
the placeholder is bound to the task's actual sample before evaluation. The orchestrator
accepts a contract only when its exact fingerprint appears in the immutable in-memory
`ContractRegistry`. This prevents a model from constructing a new contract, omitting a
resource, or reusing a passing policy or another sample's evidence to authorize an
unrelated discard or robot motion. A signed, durable approval service remains production
work.

## Visible and non-visible state

Computer vision is essential, but it is not a universal sensor.

Vision can establish facts such as:

- the expected labware is present
- a plate or rack is inside a pose-error benchmark
- a seal, lid, tip, cap, or liquid surface is visibly present
- an imaging field passes focus, registration, tissue, or artifact QC
- a robotic postcondition is visible after manipulation

Vision alone cannot establish facts such as:

- concentration, purity, or library complexity
- an internal temperature, pressure, or interlock
- whether a vendor control plane accepted a command
- whether a sample identity was preserved upstream
- whether a biological endpoint met its assay acceptance criterion

Those require assay QC, instrument telemetry, provenance, or explicit operator evidence.
`EvidenceGate.allowed_sources` prevents a convenient camera score from standing in for a
fact it cannot support.

## Workcell task lifecycle

A workcell task supplies a unique task ID, a bounded proposal, a sample ID, and one exact
reviewed contract. It does not get to declare its own action scope or response budget:
expected and successful locations, mandatory resources, retry and recovery limits,
pre- and postcondition policies, and allowed adapters all derive from that contract.

```text
propose
  -> verify the ledger, claim a unique task ID, and check initial sample provenance
  -> resolve the exact contract fingerprint and adapter binding in the approval registry
  -> atomically lease the task ID, sample ID, and every contract resource
  -> enter exclusive tracker custody and re-check provenance under both locks
  -> bind $sample and collect fresh, source-appropriate evidence for leased subjects
  -> evaluate the fingerprinted policy in the non-injectable decision engine
  -> re-check freshness, record operation intent, and issue an expiring attempt permit
  -> carry a deterministic idempotency key to the approved adapter
  -> call only an adapter approved by the operation contract
  -> retry only a certified no-sample-state-change result
  -> run only the policy's named, adapter-bound recovery
  -> detach and validate the typed result
  -> collect post-operation evidence only after the completion record
  -> re-verify the ledger, policy result, and evidence freshness
  -> advance provenance only when the outcome is supported
  -> otherwise retain the last confirmed location, record the possible destination,
     quarantine the sample, and escalate or stop
  -> release the exact lease generation before the terminal task event
  -> retain the full chain for replay and learning
```

Atomic leasing matters because one laboratory action may need a robot arm, overhead
camera, instrument, staging station, and exclusive custody of a sample at once. Inside
one process, the `ResourceManager` atomically leases a `sample:<id>` key alongside every
contract resource, while `SampleTracker` holds exclusive custody across evidence,
execution, post-operation evaluation, and provenance update. If anything is occupied,
the task acquires none and calls neither its evidence provider nor operation adapter.
The resource set is derived from the contract rather than trusted from a model-authored
task.

The one-driver-per-instrument constraint must become a resource rule, not remain a README
warning. All managers with the same `workcell_namespace` share one process-wide ownership
registry across runs, cameras, movers, arms, and stations. That namespace is stable,
deployment-owned trust configuration for one physical workcell; it must never be supplied
by a model or task. Different namespaces intentionally isolate different cells. The
manager does not stop a separate controller process, so production still needs a durable
inter-process or distributed lease around the driver boundary.

The permit expires with its evidence and carries an attempt-specific deterministic
idempotency key. An approved hardware adapter must check expiry at the command boundary
and persistently deduplicate that key before actuation. The in-memory orchestrator cannot
guarantee either behavior across an adapter queue or process crash.

## Operational memory, not model memory

The reusable product is not a transcript of what an agent said. It is the structured
record of what the software observed or was told, how deterministic policy evaluated it,
and what execution was attempted. The evidence ladder below determines what that record
can claim about the physical lab:

- sample and parent identities
- location and custody transitions
- exact policy and operation-contract fingerprints
- adapter IDs, versions, and configuration hashes
- observations and evidence references
- deterministic gate results
- retry and recovery selections
- resource ownership
- operation/recovery starts, permits, idempotency keys, and typed outcomes
- post-operation evidence decisions and uncertainty quarantine
- first unsupported boundaries and known failures

`RunLedger` serializes concurrent appends and hash-chains those events so edits,
reordering, and deletion from the middle of the available record are detectable during
replay. Public event views are detached; the sample mapping is read-only and exposes
immutable `SampleState` values, while later tracker transitions remain visible through
that live view. One active ledger owns a logical run ID inside the process. Tail deletion
requires comparing an externally committed chain head or event count. A process crash
loses this ledger and can separate external actuation from its next audit append. A
production system would use crash-atomic durable storage, publish and sign commitments,
and enforce run authority across processes; the public implementation is currently in
memory and labels those limitations.

Over time, validated device maps, acceptance policies, recovery traces, and benchmarked
outcomes become the operational memory used to improve the next workcell. The learning
target is not "did the model sound right?" It is "did the physical loop produce valid
evidence without crossing an unsupported boundary?"

## Evidence ladder

Every repository should use the same ladder:

1. `synthetic`: device-free fixture or generated data
2. `simulated`: real control code against a simulator
3. `dry-run on hardware`: physical motion or control path without the full wet assay
4. `hardware-executed under supervision`: named physical interaction with observed result
5. `wet/bio-validated`: biological data met a stated acceptance criterion
6. `independently reproduced`: bounded workflow passed outside the development setup

Progress moves up this ladder through evidence, never through a README rewrite.

## What compounds

One integration should leave behind reusable assets rather than a one-off script:

- a device mapping and transport contract
- typed actions and results
- a workcell resource model
- perception benchmarks and labeled failure fixtures
- sample-state transitions
- assay-specific expert policy
- recovery rules and traces
- replayable audit records
- measured timing and throughput data

That is how an expert-orchestrated integration service becomes software: each bounded
deployment expands the set of instruments, physical states, policies, and failures the
system can handle without pretending that an unvalidated path is autonomous.
