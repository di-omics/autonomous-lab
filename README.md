# autonomous-lab

Whether a lab can close a loop from hypothesis to evidence, and which leg breaks first.

[plr-reverse-engineer](https://github.com/di-omics/plr-reverse-engineer) brings lab
instruments under PyLabRobot control one at a time.
`plr-tested` *(private)* is the PyLabRobot code that has actually been run on real
hardware. Its evidence manifest ships in this repo, so the status, run-card and
confirm-token claims below can be checked with `autonomous-lab doctor` and no checkout. This asks the question that only makes sense across all of them at once: given the instruments on the bench and the command sets decoded so
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
autonomous-lab doctor                         # check my hardware claims; needs nothing else
autonomous-lab run single_cell_genomics       # run it as far as it honestly goes

autonomous-lab qc single_cell_genomics        # can the QC gates be evaluated at all?
autonomous-lab failures single_cell_genomics  # what goes wrong, and would anything notice?
autonomous-lab vision                         # what a camera catches; what none ever will
autonomous-lab throughput single_cell_genomics  # plates/day, or why that number does not exist
autonomous-lab provenance single_cell_genomics  # what could be proven about a run afterwards
autonomous-lab lineage single_cell_genomics   # which cell did this read come from?
autonomous-lab knowledge                      # encoded expert judgment and robot benchmarks

autonomous-lab information single_cell_genomics  # what caps information per dollar per cycle
autonomous-lab worldmodel                     # what a predictive model buys, and never will
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

### Sample identity: which cell the read came from

Everything above tracks **containers**. The ledger costs a plate hop, provenance records
that `library_plate` moved from the STAR to the reader, and both are right. But no
experiment's conclusion is about a plate. The claim a single-cell run exists to make is
*this variant was in this cell*, and that runs through a different graph.

```
$ autonomous-lab lineage single_cell_genomics

  TODAY     CLAIMED
      4 step(s) in the chain do not happen in this lab at all, starting at
      'load_protocol', so there is no material to attribute yet
  CEILING   CLAIMED   (every command decoded)
      the material crosses 5 unobserved custody hop(s) ... barcodes read at both
      ends close this, decoding does not

  LINCHPIN  pcr_enrichment_round1_cleanup on star, attested: witnessed
  BLIND MEASUREMENT  read_absorbance on tecan -- reads 96 cell(s) as one number
```

The two graphs come apart at pooling. Material is `ADDRESSED` when each unit sits in its
own well, `TAGGED` when units share a vessel but carry indices, and `BULK` or `MERGED`
when neither holds. `BULK` and `MERGED` look identical in a tube and are opposite facts:
bulk means identity never existed -- cells in a suspension were never individually known,
and **the sort is what creates their identity** -- while merged means it existed and was
thrown away. Pool 96 wells with no index first and no barcode reader, no camera, and no
amount of decoding gets it back. That is the one failure in this repo that is permanent at
the moment it happens.

Three results here are worth more than the verdict.

**The linchpin is a manual step.** Indexing is the only operation whose effect survives
pooling, so every per-cell claim the run makes rests on it. In this lab it is
`pcr_enrichment_round1_cleanup`, which has no validated run card, so a person pipettes 96
different indices into 96 wells and nothing reads back that they landed correctly. The
sequencing still runs either way, and still returns data.

**The only quantification is blind to the failure it should catch.** `read_absorbance`
measures after pooling, so it reads 96 cells as one number. `bead_pellet_aspirated`
destroys a single well; that moves the pooled value by about a ninety-sixth and fails no
gate. The recovery layer already calls that failure silent. This says *why* -- and it is
computed from the same protocol, not asserted alongside it. A tag makes attribution
recoverable only to an instrument that can **read** the tag: the sequencer demultiplexes,
the plate reader looking at the same tube cannot, and only the sequencer is exempted.

**Finishing every decode does not fix it.** `ceiling` grants the entire reverse-engineering
queue and asks what attribution would then be possible. It stops at CLAIMED, because what
caps it is five plate hops a human carries unobserved. **The EXECUTE budget cannot buy the
RECORD leg.** That is the same conclusion the custody analysis reaches, arrived at from the
sample side rather than the container side, and it is computed from the ledger's own
hop count rather than a second list.

Two things it refuses. A protocol whose material-moving steps do not declare what they do
to identity is **refused rather than defaulted**, because defaulting to a passthrough would
report an intact chain straight through the operation that destroys it. And a correctly
tagged pool still carries an unmeasured error term: index misassignment is recorded with
basis `literature`, not `in_house`, because this lab has never bounded its own rate.

The chemistry protocol is the contrast. A compound plate arrives already individuated and
never pools, so it stays `ADDRESSED` throughout and its only identity problem is custody.
The genomics protocol's exposure comes from its chemistry, not from its instruments being
worse.

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

## What all of it is for: information per dollar per cycle

Every layer above answers a piece of one question nobody had assembled: **how much does this
lab learn per dollar per experimental cycle?** Stating it plainly reframes the package.
Throughput is not the goal and autonomy is not the goal. A lab running a thousand plates a
day that cannot tell which of them are real has bought motion, not information.

```
$ autonomous-lab information single_cell_genomics

  NOT COMPUTED
  3 of 3 inputs are missing (stated_question, stated_prior, measured_per_cycle_costs).
  Without a prior there is no joint, no posterior and therefore no KL -- the objects do
  not exist, so this is not an uncertain number, it is the absence of a functional to
  evaluate. Obtainable this week: stated_question.

  CEILING   DESIGN
      all 2 declared gate(s) are unevaluable, so the cycle emits data and returns no
      decision. More reads over the same design produce more data and still no decision
      decisions per cycle    0 of 2 gate(s)

  REWORK, priced in cycles
      caught at the step 3   cycle plus the decision 2   never caught, unbounded 9

  BINDING CONSTRAINT, in evaluation order
    BINDS  execution        an unattended run reaches step 1 of 18
    BINDS  measurement      2 of 2 gate(s) cannot be evaluated
    BINDS  decision         6 failure mode(s) destroy material with nothing to notice
    BINDS  record           5 unobserved custody transfer(s)
      ?    coverage / durability / expert_transfer   no report supplied
```

**It refuses to emit the number**, and the refusal is the most defensible part. Expected
information gain needs a stated question and a stated prior, and almost no lab writes either
down. Emitting a figure over an unstated prior is what `throughput` refuses to do with
unmeasured durations, one level of abstraction up and with more authority. So it computes
the structure, which is real without a prior, and names the one missing input obtainable
this week: stating the target quantity costs a sentence and changes the answer, because a
parameter-level bound is an overestimate of what is learned about anything derived from it.

**The ceiling is set by design, not by spend.** Every gate on the reference protocol is
unevaluable, so the cycle yields data and **zero decisions**. More reads buy more data and
still no decision. Separating "buy more" from "this cannot work" is the most useful thing
here, and it is resolved from `lineage` and `qc` rather than recomputed.

**Rework is priced in cycles, not dollars**, which is the honest currency when no cost model
exists. Three failures cost a step, two cost the cycle plus the decision taken on it, and
**nine are unbounded** -- never caught, so nothing triggers the rerun and there is no number
of cycles to charge.

**The binding constraint is the procurement answer.** Seven layers evaluated in order,
returning the first that binds. On this protocol it is **execution**, and nothing downstream
of it is worth buying until it is relieved. That is a specific, checkable answer to "what
should we spend on", and it is frequently not the thing being shopped for.

## What a world model buys, and the boundary it does not move

`vision` already draws the hard line: some conditions are INVISIBLE, and that is physics
rather than model quality. It also names the real blocker for the visible ones, which is not
the camera: every check needs **labelled examples of the failure**, and failures are rare by
design and nobody photographs the run that went wrong while it was going wrong.

A predictive model of the scene changes exactly one of those, and being precise about which
is the whole module.

```
$ autonomous-lab worldmodel

  checks a label-free approach would unblock   5
    bead_pellet_retained_through_wash  (catches bead_pellet_aspirated)
    ...
  conditions no approach lifts at any capability   11
```

It attacks the labelled-failure blocker directly, since a model of what the scene *should*
look like flags deviation without ever having seen the failure. It moves the invisible
boundary **by nothing at all**: a well of denatured enzyme and a well of active enzyme emit
identical photons, so a predictor emits the same frame for both and the deviation signal is
zero for the failure that matters most. That list of 11 is computed from `vision`'s own
taxonomy rather than restated, so it cannot drift.

And what a deviation signal *is* matters as much as what it detects. It says the scene is not
what was expected. It does not say what went wrong, and it does not say the deviation
matters. **An anomaly detector that fires on a technician's sleeve has detected something
real and useless.** A label-free approach removes the labelling requirement and introduces
its own: nominal data for this bench under this lighting, and a false-positive rate measured
on real nominal variation. A detector whose miss rate on real failures nobody measured is
not a safety device, it is a belief about one.

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
accept from anybody else. So it ships a checker, and the evidence the checker reads.

```
$ autonomous-lab doctor
federated claims checked against the evidence/manifest.json bundled in this repo:

  [ok  ] hhs.iswap_to_hhs             status agrees with plr-tested: validated
  [ok  ] hhs.iswap_to_hhs             cites the same run card as plr-tested
  [ok  ] hhs.iswap_to_hhs             confirm token agrees with plr-tested: RUN_ISWAP_PLATE_TEST
  ...
  [ok  ] (coverage)                   6 validated operation(s) in plr-tested are not modelled here

  all 28 checkable claims hold.
```

No flag, no checkout, no credentials. Install or clone this repo and that command runs,
which is the point. `plr-tested` *(private)* holds supervised physical-instrument run cards
and observed failures, kept as evidence, and it is private because the work is high stakes
and a reader who cannot inspect the evidence should not be shown a claim resting on it.
That rule cuts both ways: a status table citing a repo nobody else can open is exactly such
a claim. So what travels here instead is the record. `evidence/manifest.json` is a
byte-identical copy of the machine-readable manifest `plr-tested` publishes and verifies in
its own CI under its own rules. It carries operation names, run-card paths, confirm tokens,
statuses, hosts, dates, evidence sentences and caveats, and none of the operator-owned
inputs -- volumes, reagents, method values -- that made the source repo private.
`evidence/README.md` gives the full schema and what is left out.

So `doctor` compares this package's claims against that record operation by operation: same
status, same run card, same confirm token. Where they disagree, the repo with the
instrument wins, because it is the one with the operator. **Before this, `validated_ops`
was an assertion about someone else's repo that only its own author could refute. Now it is
a claim any reader can contradict, and CI does it on a schedule without anyone remembering
to look.** A missing manifest is reported as a failure rather than skipped -- the absence of
a check is not a pass.

Writing the manifest immediately caught one: the ODTC and Tecan run cards gate on
`--confirm i-am-watching`, and this package had recorded them as having no gate at all.

The one check that still needs the tree is whether the cited files are really there, since
it has to open them. Point `doctor` at a checkout and it runs that pass too:

```
$ autonomous-lab doctor --plr-tested ../plr-tested
federated claims checked against the plr-tested checkout at ../plr-tested:

  [ok  ] hhs                          entry exists: liquid-handler/run_on_pi.sh
  [ok  ] hhs.iswap_to_hhs             run card exists (validated): liquid-handler/starlab_live/test_iswap_plate_rail35pos0_to_rail27_variable.py
  [ok  ] hhs.iswap_to_hhs             confirm token appears in the run card: RUN_ISWAP_PLATE_TEST
  ...

  all 49 checkable claims hold.
```

That confirms the run card exists at the cited path and that the confirm token the ledger
tells you to type really appears in the script. It exits non-zero on drift, and it caught a
real bug during development: every STAR step was citing `RUN_PCR_ENRICHMENT_ODTC_LIDDED_FULL`,
when the whole-genome sequencing preparation run card actually gates on `RUN_SINGLE_COL_WGS_PREP_HHS`. The ledger was
telling an operator to type a token that would have refused the run.

Existence is not status, which is why it is the weaker of the two passes and not the one
that ships. A run card still on disk proves nothing about whether anyone watched it run,
and it cannot catch `plr-tested` downgrading an operation to `written` while this package
goes on calling it validated. The manifest can, and anybody can run that check.

What neither checker can reach is `evidence` -- whether an operator really watched the
thing run. That is prose about the physical world, which is why the evidence strings stay
narrow and carry their own caveats.

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

149 device-free tests. The ones that matter most try to make the layer lie:

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
- report an intact sample chain through a pooling step that destroyed attribution, or
  claim a pooled absorbance reading says something about one well.

Two tests exist to keep the honesty from drifting quietly. One asserts that even a fully
equipped workcell -- every camera, every calibration, every model -- still leaves
destructive failures undetected, so nobody can reclassify an invisible failure into a
visible one and declare the problem solved. The other asserts that custody gaps are derived
from the ledger's own physical-hop computation rather than a parallel list, because two
independent lists eventually disagree and nobody notices which is wrong.

The doctor tests prove the checker itself catches a renamed run card and a stale token,
because a checker that passed unconditionally would just launder the assertion. One of them
runs the manifest comparison against the bundled `evidence/manifest.json`, so a status this
package claims that plr-tested does not agree with fails the suite here, on any machine,
rather than only where the private checkout exists.
