# autonomous-lab

Whether a lab can close a loop from hypothesis to evidence, and which leg breaks first.

[plr-reverse-engineer](https://github.com/di-omics/plr-reverse-engineer) brings lab
instruments under PyLabRobot control one at a time.
[plr-tested](https://github.com/di-omics/plr-tested) is the PyLabRobot code that has
actually been run on real hardware. This asks the question that only makes sense across
all of them at once: given the instruments on the bench and the command sets decoded so
far, how much of a real protocol runs unattended, and what exactly is blocking the rest?

It answers by costing every step against the actual state of the code. Nothing here is
asserted. The registry is derived from `plr_re.protocolmap.SEEDS`, verdicts are computed
from the resolved `ProtocolMap`, and a step counts as automated only if its command is
genuinely decoded. There is no field a protocol author can set to declare one.

Executing the protocol is only the first of four things a lab must do. It also has to
**measure** a result that means something, **decide** what follows, and **record** it well
enough to replay. Those three are usually assumed. Here they are computed, against the same
evidence, and they fail for different reasons than execution does.

```
pip install 'autonomous-lab @ git+https://github.com/di-omics/autonomous-lab'

autonomous-lab loop single_cell_genomics      # can this lab close a loop? which leg breaks?

autonomous-lab stock                          # every instrument, its role, how far its map is
autonomous-lab ledger single_cell_genomics    # cost a protocol step by step
autonomous-lab gaps                           # the RE queue, ranked by steps freed
autonomous-lab doctor --plr-tested ../plr-tested   # check my claims against your checkout
autonomous-lab run single_cell_genomics       # run it as far as it honestly goes

autonomous-lab qc single_cell_genomics        # can the QC gates be evaluated at all?
autonomous-lab failures single_cell_genomics  # what goes wrong, and would anything notice?
autonomous-lab vision                         # what a camera catches; what none ever will
autonomous-lab throughput single_cell_genomics  # plates/day, or why that number does not exist
autonomous-lab provenance single_cell_genomics  # what could be proven about a run afterwards
autonomous-lab knowledge                      # encoded expert judgment and robot benchmarks
```

## What it reports today

Costing the single-cell genomics reference protocol (Namocell sort -> STAR whole-genome sequencing ->
ODTC PCR1 -> STAR library -> AVITI sequencing -> run-folder readout), with a plr-tested
checkout wired in via `--plr-tested`:

| | steps | |
| --- | --- | --- |
| automated | 3 of 18 | run headless today: two link preflights and the AVITI run-folder read |
| supervised | 2 of 18 | a validated run card exists in plr-tested, gated on a confirm token and an operator |
| blocked | 8 of 18 | the command is undecoded; the coverage gate refuses the run |
| manual | 4 of 18 | seating a cartridge, loading a flow cell, and two STAR steps nobody has written a validated script for |
| broken | 1 of 18 | the run card exists, was run on the instrument, and failed |

**An unattended run reaches step 1 of 18 before it stops.** That number, not the 17%
autonomy figure, is what "how automated is this lab" actually means: a read-only step near
the end is only reachable if everything before it also ran. There are also 5 physical
plate hops that no amount of decoding removes -- only a plate mover does.

`broken` is its own row on purpose. The Tecan plate reader's absorbance run card is
written and was run on the instrument, where it fails deterministically: `TimeoutError`
on `ABSOLUTE MTP,Y=`, 2 of 2, and the reader has never returned an OD matrix. Calling that
`manual` would say "someone writes and proves that script first", which is false, and it
would make a known defect look like unwritten work. One means do reverse-engineering; the
other means debug a real failure. A planner needs to know which.

The reason the numbers are this low is the honest one. Across all six reverse-engineered
instruments, **0 of 54 seeded commands are decoded**. Not one of them can be driven
headlessly, and plr-re's own coverage gate refuses an armed run against an incomplete map.
The only real instrument contact available today is the AVITI run-folder read, USB
enumeration, and two socket probes. This tool exists to say that precisely, and to say
what would change it.

## Execution is one leg of four

```
$ autonomous-lab loop single_cell_genomics

  EXECUTE   BROKEN
      an unattended run reaches step 1 of 18; it stops at 'manual_load'
  MEASURE   BROKEN
      2 of 2 gate(s) cannot be evaluated: sort_occupancy_before_amplification;
      library_quant_before_flow_cell
  DECIDE    BROKEN
      6 failure mode(s) destroy material with nothing in this lab to notice
  RECORD    BROKEN
      5 unobserved custody transfer(s); the record's identity claim is an assertion
```

Four legs, four different next actions. That is the whole reason not to collapse this into
one autonomy percentage: EXECUTE means reverse-engineering, MEASURE means an instrument
that returns a usable number, DECIDE means a detection path for the failures that destroy
material, RECORD means barcodes or an arm that reports. A lab tracking only autonomy spends
all four budgets on the first one.

### MEASURE: a gate that cannot fire

A QC gate can be perfectly specified and still be unevaluable, because the measurement it
reads comes from a step that is blocked, manual, or broken. Both genomics gates are in that
state, and the second one is the interesting case:

```
$ autonomous-lab qc single_cell_genomics

  UNSATISFIABLE  library_quant_before_flow_cell
      protects   committing a flow cell and a sequencing run to an unquantified library
      'library_conc_od' needs read_absorbance, which is broken

  WRONG ASSAY  library_quant_before_flow_cell reads 'library_conc_od'
      A260 does not discriminate library from primer, carrier, or free nucleotide, and at
      single-cell input those dominate the signal. A gate on this number passes an empty
      library.
```

Those are two independent failures and both are reported. The first is loud: no number
arrives, so the gate never fires. The second is quiet and survives fixing the first --
repair the Tecan tomorrow and the gate starts returning confident passes on libraries that
are not there, because A260 is the wrong assay for picogram input no matter how well the
reader works. **A gate that cannot fire makes a run look supervised when it is not**, and a
gate reading the wrong assay is worse, because it looks like it fired.

Thresholds carry the basis they rest on -- `in_house`, `vendor`, `literature`, `intuition`
-- and only in-house counts as validated. Vendor cutoffs are real evidence and are not
evidence about *this* assay at *this* input, which is the entire difficulty of low-input
work: the kit insert was established at nanograms and the sample is picograms.

### DECIDE: the failures nothing would catch

```
$ autonomous-lab failures single_cell_genomics

  14 failure mode(s): 9 silent, 6 silent AND destructive, 7 worse than planned
  4 of the silent ones are invisible to any camera
```

Every failure declares how it would be caught. `effective()` then resolves that plan
against the real ledger, the real gate readiness, and the real vision capability, and
downgrades it when the path does not exist. A failure whose plan says "the QC gate catches
it" is undetected in practice when that gate is unsatisfiable.

Two are worth reading in full. `bead_pellet_aspirated` destroys the sample completely and
silently -- the beads carry the whole library, and every downstream step runs normally on
an empty well. Its only detection paths are a camera this lab does not have and a
quantification gate this lab cannot evaluate, so its effective latency is NEVER: the first
evidence is a sequencing run that cost a flow cell to produce.

`odtc_callback_theft` is documented in this repo's own registry. Start a second driver
process against the ODTC and it re-registers the event receiver, silently stealing the
first process's callbacks. Nothing raises. The first process waits forever for a
thermal-complete event being delivered elsewhere. It is the cleanest example here of a
failure no sensor catches, because it is not a physical event at all -- and it is why
`ONE_PROCESS_PER_INSTRUMENT` is a hard constraint rather than a style rule.

### What a camera can and cannot ever do

```
$ autonomous-lab vision
  0 available, 6 blocked, 0 impossible of 6
```

Conditions sort into `visible`, `visible_indirect`, and `invisible`, and that last boundary
is a claim about physics rather than model quality. No amount of training data separates a
well of active enzyme from one of denatured enzyme, because the photons are identical. Four
of this lab's six silent failures are on that side of the line: **buying cameras would not
fix them**, and a plan that budgets for cameras to solve them is spending on the wrong
sensor.

For the ones vision *could* catch, the blocker is not the camera. Every check needs labeled
examples of the failure and a measured sensitivity on held-out real failures, and both are
structurally hard: failures are rare by design, and nobody photographs the run that went
wrong at the moment it went wrong. A lab that wants vision QC has to start collecting
failure images long before it has a model. A detector whose miss rate nobody has measured
is not a safety device -- it is worse than none, because the operator stops looking.

### Throughput: an honest refusal

```
$ autonomous-lab throughput single_cell_genomics
  timed steps      0 of 18  (0%)
  attended steps   15 of 18 need a human

  NOT COMPUTABLE
  18 of 18 steps have never been timed; a throughput number over them would be a guess.
```

The scheduling model is real -- pipelined, with instruments serialized by the
one-process-per-instrument rule, so the busiest instrument sets the cycle time. It computes
the moment durations exist. What it will not do is fill a gap with a plausible number and
return a total that looks like an answer, because that total gets quoted and becomes a
specification nobody measured.

The one timing this lab has actually produced is the Tecan's drawer: close stable at 3.6 s,
open bimodal at 3.2 s versus 5.3 s. The model budgets the worst case, not the mean, because
a handoff scheduled on the mean collides with an arm that arrived on time. That instrument
still cannot read a plate.

The second constraint is the one automation vendors leave out: 15 of 18 steps need a human,
and humans are not available overnight. Instrument speed cannot raise that ceiling.

### RECORD: where provenance actually breaks

```
$ autonomous-lab provenance single_cell_genomics
  steps an instrument could confirm   3 of 18
  steps recorded on intent alone      15
  unobserved custody transfers        5
```

Every event carries who attests to it: `confirmed` (an instrument reported it and the
report was read), `witnessed` (a human attests), or `asserted` (software sent the command
and nothing contradicted it). **Asserted is not evidence** -- it is a log line about intent,
and the easy version of a run ledger records intent and presents it as history. A dry run
therefore produces a record containing no evidence at all, which is the correct and slightly
uncomfortable result.

The chain is hash-linked, so an edit or a splice is detectable. That is tamper-evidence, not
security: it proves the record was not changed after the fact and proves nothing about
whether the events are true.

Custody breaks at exactly the five physical hops the ledger already counts -- resolved from
that same computation rather than a second list that could disagree. Between two
instruments a human carries the plate, no instrument observes the transfer, and the binding
between the plate now on the deck and the record describing it rests on the human having
carried the right one. Software cannot close that by being careful. A barcode read at both
ends can, or an arm that reports the move.

### The tacit layer

```
$ autonomous-lab knowledge
  4 of 8 judgments validated against this lab's own data
  2 of 7 benchmarks met (4 unmeasured, 1 failed)
```

A written protocol is the subset of what an experienced scientist does that survived being
written down. The rest -- when a result is real, when a sample is still recoverable, when a
clean-looking plate should be thrown away -- lives in one head and is the thing that fails
to transfer when a lab automates.

So it is written down, with the basis it rests on and whether this lab has validated it.
Some are load-bearing and unvalidated, and recording that honestly is what makes them
improvable; a judgment stored without its basis is indistinguishable from a rule.

> `column_wise_failure_is_hardware` -- when wells fail in a column-wise pattern rather than
> at random, stop and inspect the instrument before repeating any biology. Biology fails
> randomly across a plate; hardware fails geometrically. Repeating the prep will reproduce
> it exactly.

Benchmarks are the other half: what a robot must prove before it is trusted with a task.
An operation nobody has benchmarked is **untrusted by default**, which is the opposite of
the usual convention and the correct one -- the absence of a measurement is not evidence of
adequacy. The STAR's dry motion is validated; its volumetric accuracy at the working volume
has never been measured, and no camera retires that benchmark. It needs a calibration
experiment.

## The RE queue is computed, not argued about

```
$ autonomous-lab gaps
  namocell       frees 5 step(s), needs 9 command(s) decoded
  element_aviti  frees 3 step(s), needs 8 command(s) decoded
  biotage_v10    frees 3 step(s), needs 9 command(s) decoded
  agilent6530    frees 2 step(s), needs 10 command(s) decoded
```

Ranked by instrument, not by command, and that is forced by the code rather than a
presentation choice: plr-re's coverage gate is all-or-nothing across a map, so decoding a
single command frees exactly zero steps. The unit of progress is a finished map, and a
per-command queue would be advice nobody could act on.

## Don't take my word for the hardware claims

The instrument registry is derived from `SEEDS`, so it cannot drift. The federated claims
have no such luxury: `validated_ops` is hand-written paths and prose about a repo this one
does not control, which makes it exactly the kind of assertion this package refuses to
accept from anybody else. So it ships a checker.

```
$ autonomous-lab doctor --plr-tested ../plr-tested
  [ok  ] star.wgs_prep_lysis  run card exists: liquid-handler/starlab_live/00_wgs_prep_1col_src1lysis_src3rxn_dst1_hhs_DRY.py
  [ok  ] star.wgs_prep_lysis  confirm token appears in the run card: RUN_SINGLE_COL_WGS_PREP_HHS
  ...
  all 16 checkable claims hold.
```

For every operation this package calls validated, `doctor` confirms the run card really
exists at that path in your plr-tested checkout, and that the confirm token the ledger
tells you to type really appears in that script. It exits non-zero on drift. This caught a
real bug during development: every STAR step was citing `RUN_PCR_ENRICHMENT_ODTC_LIDDED_FULL`,
when the whole-genome sequencing preparation run card actually gates on `RUN_SINGLE_COL_WGS_PREP_HHS`. The ledger was
telling an operator to type a token that would have refused the run.

What it deliberately **cannot** check is `evidence` -- whether an operator really watched
the thing run. That is prose about the physical world and no checker reaches it, which is
why the evidence strings stay narrow and carry their own caveats.

## Three things it refuses to do

1. **Let an instrument's reputation transfer to a step.** plr-tested has a validated
   whole-genome sequencing preparation addition and a validated PCR enrichment choreography; it has no validated bead cleanup
   and no validated library pooling. So those cost out as manual even though they name a
   validated instrument. A federated step is supervised only when a run card for *that
   step* has been proven. The whole-genome sequencing leg that does count is dry-validated, and the ledger
   says so in the same breath: its wet form has never run.
2. **Model only part of what would refuse a run.** `GuardedReplayer.setup()` has three
   preconditions, not one: coverage, an endpoint, and a transport a connection class can
   open. `DEFAULT_TRANSPORT` is UNKNOWN for three of these instruments by design, so a
   decode alone does not make one dialable.
3. **Skip ahead.** The executor performs the zero-decode reads and stops at the first step
   needing a human, with a card naming the bench work that would remove the stop. A run
   that faked a sort and then truthfully read a run folder would be worse than useless --
   it would look like a working pipeline.

## The registry derives itself

Instruments are not listed here. They are read from `plr_re.protocolmap.SEEDS`, so this
package cannot drift out of sync with the repo that actually does the reverse-engineering,
and a new playbook joins the lab with no edit. Install a plr-re that has the Integra
VIAFLO 96 playbook and it registers itself, roles and all, and appears in the queue.

That also means what you see depends on the plr-re you installed: `main` has five
instruments today, and a branch with an unmerged playbook has six. An instrument this
package knows about but your plr-re does not costs out as unavailable rather than crashing.

## Reference protocols

- `single_cell_genomics` -- Namocell sort, STAR whole-genome sequencing preparation, ODTC PCR enrichment round 1, STAR library
  prep, AVITI sequencing, run-folder readout.
- `small_molecule_qc` -- VIAFLO 96 serial dilution, Biotage V-10 solvent removal, Agilent
  6530 Q-TOF LC/MS.

The genomics one quantifies the library on the plate reader before it pools and sequences,
because that is what you actually do, and because skipping it would score better and be
worth less.

Both are written to be unflattering. They include the cartridge seating and the flow-cell
loading that a demo would quietly omit, because a plan that skipped them would produce a
better number and be worth nothing.

Write your own by declaring `Step`s and the `Artifact`s they move; artifacts marked
physical get counted as plate hops. A protocol that references an artifact it does not
declare, or consumes one nothing produces, is refused before it is costed.

## Safety

This package schedules and reports. It never actuates. `run --armed` performs only the
read-only operations -- enumerating a USB bus, probing a port, reading a run folder --
and there is no flag that moves an instrument. Anything that does goes through plr-re's
controllers, behind their own `armed` and `allow_actuation` switches, with a human
present.

Note also plr-tested's hard constraint, which any scheduler built on this must respect:
one driver process per instrument. Two STAR clients raise `USBError [Errno 16] Resource
busy`, and on the ODTC the collision is quieter, because a second process re-registers the
event receiver and silently steals the first one's callbacks.

## Tests

```
pip install -e '.[dev]' && pytest
```

128 device-free tests. The ones that matter most try to make the layer lie:

- claim a step is automated when its command is undecoded; claim a decoded command is
  runnable while its siblings are not; claim a federated leg runs when no run card was ever
  proven for it.
- pass a QC gate that received no measurement at all. This is the single most important
  test in the suite: the natural implementation iterates the values it was handed, so a
  gate evaluated against an empty dict passes every criterion vacuously, and that is how a
  lab commits a flow cell to an empty library.
- report a failure as caught when its detection path is a camera this lab does not own or a
  gate it cannot evaluate; rely on an operator noticing a condition nobody can see.
- return a plates-per-day figure over durations nobody measured.
- verify a run record after an event has been edited, removed, or reordered.
- treat an unbenchmarked operation as trusted.

Two tests exist to keep the honesty from drifting quietly. One asserts that even a fully
equipped workcell -- every camera, every calibration, every model -- still leaves
destructive failures undetected, so nobody can reclassify an invisible failure into a
visible one and declare the problem solved. The other asserts that custody gaps are derived
from the ledger's own physical-hop computation rather than a parallel list, because two
independent lists eventually disagree and nobody notices which is wrong.

The doctor tests prove the checker itself catches a renamed run card and a stale token,
because a checker that passed unconditionally would just launder the assertion.
