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
| Instrument adaptation | Capture, decode, map, and guarded-replay commands for hardware with no usable API | `di-omics/plr-reverse-engineer` |
| Physical evidence | Preserve exact run cards, confirmation tokens, observed successes, and known failures | `di-omics/plr-tested` |
| Typed agent tools | Expose simulation-first PyLabRobot capabilities through typed MCP tools and opt-in backends | `di-omics/plr-mcp` |
| Perception | Measure pose, presence, morphology, imaging quality, and visible failure state | `di-omics/lab-cv`, `di-omics/spatial-flow` |
| Robot execution | Onboard arms, calibrate hand-eye geometry, express manipulation tasks, and test recovery | `di-omics/plr-lab-robot` |
| Laboratory intelligence | Evaluate expert policy, lease workcell resources, track samples, bound recovery, and audit the run | `di-omics/autonomous-lab` |

The layers are separable on purpose. A better vision model cannot waive an assay-QC
gate. A complete command map cannot prove a biological endpoint. A model proposal cannot
claim the robot or instrument resource before deterministic permission.

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
its owner, evidence gates, rationale, failure action, and recovery. The orchestrator
evaluates it deterministically and records the version with the decision.

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

A workcell task is a bounded proposal with a sample, expected location, success location,
required resources, policy, and retry/recovery budgets.

```text
propose
  -> verify sample identity and location
  -> atomically lease every required resource
  -> collect source-appropriate evidence
  -> evaluate the versioned expert policy
  -> call one typed adapter only when permitted
  -> verify outcome or select bounded retry/recovery
  -> advance sample provenance only on success
  -> release resources on every terminal path
  -> retain the full chain for replay and learning
```

Atomic leasing matters because one laboratory action may need a robot arm, overhead
camera, instrument, and staging station at once. If any resource is occupied, the task
acquires none and calls neither its evidence provider nor its operation adapter.

The one-driver-per-instrument constraint is a resource rule, not a README warning. It is
represented by the same lease used for cameras, movers, arms, and stations.

## Operational memory, not model memory

The reusable product is not a transcript of what an agent said. It is the structured
record of what the lab proved:

- sample and parent identities
- location and custody transitions
- policy and adapter versions
- observations and evidence references
- deterministic gate results
- retry and recovery selections
- resource ownership
- typed operation outcomes
- first unsupported boundaries and known failures

`RunLedger` hash-chains those events so accidental edits, missing events, and reordering
are detectable during replay. A production system would persist and sign the records;
the public implementation is currently in memory and labels that limitation.

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
