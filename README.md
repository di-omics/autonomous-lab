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

autonomous-lab coverage single_cell_genomics  # would anything catch each failure?
autonomous-lab durability                     # what each instrument may be trusted with
autonomous-lab teaching single_cell_genomics  # what an expert demonstrated, what the machine attains
autonomous-lab feedback single_cell_genomics  # can a control loop actually close?
```

## What it reports today

Costing the single-cell genomics reference protocol (Namocell sort -> STAR whole-genome sequencing ->
ODTC PCR1 -> STAR library -> AVITI sequencing -> run-folder readout), with a run-card
checkout wired in via `--run-cards`:

| | steps | |
| --- | --- | --- |
| automated | 3 of 18 | run headless today: two link preflights and the AVITI run-folder read |
| supervised | 2 of 18 | a validated run card exists in the checkout, gated on a confirm token and an operator |
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

## Would anything catch it? Vision and gates, composed

Three layers here each hold a third of one answer and never meet. `vision` knows what a
camera can and can never see. `qc` knows which gates exist and whether they can fire.
`recovery` knows which failures destroy material. Nobody joined them, so nobody could answer
the question a lab actually asks: **for every failure that destroys material, is there
anything at all that would catch it?**

```
$ autonomous-lab coverage single_cell_genomics

  failure modes            14
  covered                  0
  uncovered                14, of which 9 destroy material
  closable as it stands    7   (build the detector, or make the gate fire)
  needs a new instrument   7
```

The composition is the product, because vision and gates are **complementary instruments,
not alternatives**. Where the photons are identical either way, no model resolves it and
only an assay does. So the report splits three ways, and each third is a different job:

- **six a camera would catch** -- `bead_pellet_aspirated` among them, the failure the
  recovery layer already calls the worst silent one. The check is declared and undeployable:
  missing camera, pose, labels, model, validation. That is a CV project with a known payoff.
- **one invisible, but a declared gate already reads it** -- `enzyme_activity_lost` sits
  behind `library_quant_before_flow_cell`, which is unsatisfiable because the reader is
  broken. No camera is involved. Repair the instrument and the coverage arrives.
- **seven no camera reaches at any capability** -- these are `mandatory_gates()`. Buying a
  better model buys nothing against them. They need an assay that does not currently exist
  in the protocol.

`sota_lift(current, proposed)` prices a model upgrade honestly. It returns both lists, and
the second is required output: **a report showing only what a capability lifts is a purchase
justification**, and every purchase justification is correct about the failures it lists and
silent about the ones that make the purchase insufficient.

Two things it refuses to count as coverage: a vision check that exists but whose
requirements are unmet, and a gate that exists but cannot be evaluated. Both are the
vacuous-pass failure in a new costume -- a plan that counts unbuilt detectors and unfirable
gates reports a lab as covered while material is quietly destroyed.

## Keeping it running, teaching it, and closing the loop

Three further layers cover what a workcell needs once it has to survive contact with a
calendar.

**`durability`** asks what an instrument is currently *entitled* to be trusted with. It is
deliberately not a failure predictor -- that needs population reliability data this package
does not have, and an invented MTBF becomes a specification nobody measured. What it does
compute is whether a planned campaign **crosses a service or calibration boundary mid-run**,
which is the insurance question: a plate that started before an expiry and finished after it
has an ambiguous provenance, and nothing downstream repairs that. An instrument with no
service history reports as unmeasured rather than healthy, matching how an unbenchmarked
operation is untrusted by default.

**`teaching`** models the transfer that makes any of this worth doing: an expert
demonstrating an operation, and a machine measured against that demonstration. The honest
core is that **a demonstration is data, not authority.** A scientist doing something twice is
not a specification -- it is two observations with a spread, and the spread is the
information. So an envelope refuses to produce a tolerance from a single demonstration, and
a machine with one good run reports as indistinguishable from unmeasured rather than as
meeting the bar. Most operations have no envelope at all, and that list is the real backlog
of an automation programme; `demonstration_queue` ranks what an expert should demonstrate
next by how many operations it unblocks, the same way `unlocks()` ranks decoding work.

**`feedback`** asks whether a control loop can actually close. Each of measure, compare, and
act has its own way of being fake, and the load-bearing one is latency: **a measurement taken
after the material is consumed cannot steer anything, however accurate it is.** It is a
post-mortem wearing the costume of a control loop. So a loop declares where it senses and
where it corrects, and any loop whose sensor sits downstream of its actuator is refused --
pure graph reasoning over the protocol, and it kills most proposed closed-loop designs. What
it will not do is model gain, overshoot, or settling, because that needs a plant model and
measured response data nothing here has. What it *can* say is how many plates are already in
flight between sensor and actuator, since every one of them is committed before the
correction lands.

## Printing the fixture instead of waiting for it

This portfolio's argument is that a lab does not need a vendor to ship AI-native labware.
That argument is only honest if a part you printed yourself is held to the same standard as
everything else here -- and a printed fixture is untested hardware, made in-house, sitting
inside the working envelope of a moving robot, sometimes near reagents.

`printed` computes whether a specific part may be used for a specific purpose. The load-
bearing boundary is physical rather than regulatory: **fused-deposition parts were measured
by computed tomography at 4.05 to 6.32 percent porosity with infill fixed at 100 percent.**
A part that porous cannot be validated as cleanable, so it does not go in a fluid path, and
no amount of coating or annealing is accepted here as having fixed that -- post-processing
is recorded as a claim, not a solution.

The consequences fall out rather than being asserted. Of the materials described here, only
a certified biocompatible photopolymer reaches culture contact, and only that plus machined
stock reach sample contact. Everything printable holds things; nothing printable holds
liquid. A blank fixture is refused for every use, because the failure this module exists to
prevent is a part that passes by virtue of having nothing declared about it.

Four refusals are worth naming, because each is a real way a printed part fails on a deck:

- **`porous_process_in_fluid_path`** -- the boundary above.
- **`softens_in_the_cycle`** -- PETG's glass transition is 69-77 C, so a 121 C autoclave
  cycle relaxes its frozen-in extrusion stresses. The part comes out the wrong shape.
- **`not_positively_located`** -- an unlocated fixture is a crash waiting for the first
  knock. It needs no operator error to move, and once it has moved every taught position
  that references it is wrong with nothing reporting that anything changed.
- **`dimension_not_measured`** -- a designed dimension is a fact about the model. Desktop
  tolerance runs about +/-0.5 percent with a +/-0.5 mm floor and scales with length,
  shrinkage is material and vendor specific, and the first layer comes out wider than the
  model by roughly the 0.2 mm a slicer compensates by default.

`hardware/tilt_module.scad` is the worked example: a passive fixed-angle tilt fixture that
pools residual liquid at one side of each well so a tip can reach more of it. No hinge and
no adjustment, because an adjustable angle is an angle nobody records. It defaults to
printing the **test coupon** rather than the fixture, so the fit is proven before hours are
committed. And it states no recovery figure anywhere -- `docs/PRINTED_FIXTURES.md` gives the
gravimetric protocol that would produce one instead. An unmeasured fixture is a net addition
of a crash surface, a cleaning obligation, and an uncharacterized material to a workcell
that had none of them.

## From a video to an arm that can be trusted

The camera layer, the arm, and the printed fixture had nothing joining them. `imitation`
is the join: capture a demonstration, train an arm from it, and use a printed fixture to
make the task tractable. It computes whether a given capture can train a policy at all, and
whether the resulting policy may be handed material.

Three things carry it, and each is where the naive version fails.

**A video is not a demonstration.** A policy needs actions, not pixels. Teleoperation and
kinesthetic capture record the arm's own joint states, so the action stream is measured. A
monocular human video has no joint states: it needs pose estimation and then a retargeting
model onto a gripper with different kinematics, which is two estimators in series rather
than a format conversion. No verified millimetre figure for human-to-robot retargeting error
was found at all. The two published magnitudes belong to the hand-pose stage alone, at
185.67 mm mean per-joint error for one monocular estimator, so an unmeasured retargeting is
not a small unknown.

**The fixture is inside what the policy learned.** A printed nest removes degrees of freedom
the policy would otherwise learn from data, which is why fixtures and learning belong in one
story. It cuts both ways: reprint that nest with different shrinkage and the demonstrations
collected against the old one may be stale. So a policy carries the fixture revision it
learned on, and a capture that recorded no fixture at all does not count as agreeing with
one that did. The part was physically there whether or not anybody wrote it down.

**A properly run evaluation is not a good result.** This is the distinction the module got
wrong first and now enforces hardest. `Trust.MEASURED` means the evaluation was conducted
correctly: held out, externally scored, above the trial floor. It says nothing about whether
the policy works, and a policy that succeeded in **zero of twenty** held-out trials is
MEASURED. So `evidence_complete` and `trusted` are separate, and `trusted` additionally
requires a **declared acceptance rate that the interval's lower bound clears**. There is no
default rate, because what is tolerable is a property of the task: a failure rate a retry
fixes is not a failure rate for a transfer that consumes the last of a sample. Judging on
the lower bound rather than the point estimate is what makes 18 of 20 fail an 80 percent
bar that 90 of 100 clears, at the same point estimate.

A run needs a fourth thing none of those provide: a bound that lives **outside** the policy.
A learned policy carries no guarantee about an input it has not seen, so the limit on what
it can reach, how fast and how hard cannot come from the policy or from a model checking the
policy. `Interlock` demands workspace, speed and force bounds, something named as enforcing
them, and -- following `vision`'s rule for detectors -- a **measured miss rate**, obtained by
deliberately driving the violation rather than by observing that nothing went wrong.

`docs/CAPTURE_TO_POLICY.md` is the practical side: which capture modality to choose and why
that single decision determines how much of the rest is solved work, what a usable capture
contains, where the printed fixture earns its place, and the ladder from simulation to
material where no rung implies the one above it.

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

1. **Let an instrument's reputation transfer to a step.** The proven run cards are a
   whole-genome sequencing preparation addition and a PCR enrichment choreography; there
   is no validated bead cleanup and no validated library pooling. So those cost out as
   manual even though they name a validated instrument. A federated step is supervised
   only when a run card for *that step* has been proven. The whole-genome sequencing leg
   that does count is dry-validated, and the ledger says so in the same breath: its wet
   form has never run.
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

Note also the hard constraint the instruments impose, which any scheduler built on this
must respect: one driver process per instrument. Two STAR clients raise
`USBError [Errno 16] Resource busy`, and on the ODTC the collision is quieter, because a
second process re-registers the event receiver and silently steals the first one's
callbacks.

## Tests

```
pip install -e '.[dev]' && pytest
```

477 device-free tests. The ones that matter most try to make the layer lie:

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
