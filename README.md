# autonomous-lab

An autonomy layer for a real lab: what can run without a human, whether it should run at
all, what actually happened, and what to fix next.

[plr-reverse-engineer](https://github.com/di-omics/plr-reverse-engineer) brings lab
instruments under PyLabRobot control one at a time.
[plr-tested](https://github.com/di-omics/plr-tested) is the PyLabRobot code that has
actually been run on real hardware. This package asks the questions that only make sense
across all of them at once, and it is built so that none of its answers can be flattering
by accident.

It is four layers, and each one refuses to overstate what the layer below it supports.

| | question | refusal that defines it |
| --- | --- | --- |
| **capability** | can this step run at all? | a step is automated only if its command is genuinely decoded. No field declares it. |
| **acceptance** | should it, given the numbers? | a gate in front of an instrument that has never returned data reports UNMEASURABLE, not PASS. |
| **provenance** | what would a bad result implicate? | a pooled library names a plate, not a well, unless an index was really recorded. |
| **control** | what should we try next? | the controller proposes setpoints and cannot move an acceptance threshold. |

```
pip install 'autonomous-lab @ git+https://github.com/di-omics/autonomous-lab'

autonomous-lab stock                          # every instrument, its role, how far its map is
autonomous-lab ledger single_cell_genomics    # cost a protocol step by step
autonomous-lab gaps                           # the RE queue, ranked by steps freed
autonomous-lab gates                          # the acceptance rubrics, and their provenance
autonomous-lab provenance                     # what a bad result would implicate
autonomous-lab session single_cell_genomics   # propose every step; let the gates decide
autonomous-lab observe --record run.jsonl --step pta_wga_lysis   # what actually happened
autonomous-lab control --record run.jsonl     # which step to fix first, and why
autonomous-lab doctor --plr-tested ../plr-tested   # check my claims against your checkout
```

## Capability: how far an unattended run gets

Costing the single-cell genomics reference protocol (Namocell sort -> STAR whole-genome
amplification -> ODTC PCR1 -> STAR library -> AVITI sequencing -> run-folder readout),
with a plr-tested checkout wired in via `--plr-tested`:

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

## Acceptance: the judgement that actually stops experiments

Capability asks whether a step *can* run. What stops real experiments is the other
question: given the numbers that came back, *should* the next one start? That is the thing
a senior scientist supplies and a protocol document never quite writes down.

A criterion here **cannot be constructed without a source**, and it carries the origin it
actually has, using plr-tested's own vocabulary: `TRANSCRIBED` (copied from something you
can point at), `TUNABLE` (a defensible local default), `CALIBRATE`, `TODO`. The last two
block a hardware run outright, because comparing a measurement to a number somebody intends
to decide later is not a decision, it is the appearance of one.

Running that over the rubrics transcribed from plr-tested produces an uncomfortable
number, which is why it is printed:

```
$ autonomous-lab gates
  2 of 10 thresholds are transcribed from a citable source.
  1 of 5 rubrics cannot gate material yet.
```

That is not a criticism of those rubrics; it is a normal place for a young assay to be.
The numbers plr-tested sources carefully -- PicoGreen's 480/520 optics, Rhodamine's
554/627 maxima, the 0.90X and 0.65X bead ratios, the 22.5 uL master mix -- are assay optics
and reagent volumes. The cutoffs that decide whether a sample lives or dies are mostly
local defaults, several marked TUNABLE in their own source. The only externally cited
thresholds in this file are the EM-seq control-read minima, attributed to a kit document.
It is only a problem if a rubric presents a working default as settled science, so here
the report says which is which every single time.

Then the layers meet, and the result is the point of the package:

```
$ autonomous-lab session single_cell_genomics
  gate library_loading_window: UNMEASURABLE
    Tecan Infinite 200 PRO cannot produce 'read_absorbance': the run card exists and
    FAILED on the instrument [...] No wells, no OD matrix.
```

Hand that gate a perfectly plausible library concentration and it still refuses, because
the instrument it is attributed to has never returned one. A value that arrives from an
instrument that cannot produce it is evidence about the caller, not about the sample.

**Four of the five reference gates evaluate to UNMEASURABLE. The fifth is measurable and
still cannot pass, because one of its thresholds is nobody's decision yet.** Zero gates can
pass material today. That is the honest state of this bench, and a gate layer that could
not say so would be worse than not having one.

`UNMEASURABLE` is the verdict the machinery this was transcribed from does not have, and
its absence there is a real gap: an out-of-curve PicoGreen read still receives a hard pass
or fail from an extrapolated concentration. A gate that returns PASS because it found no
contradicting data is the most dangerous thing that can be in a package like this.

Where a calibration set exists, `ConformalBand` gives intervals with a finite-sample
coverage guarantee, and a criterion is only decided when the *whole* interval falls on one
side of the threshold. When it straddles, the verdict is ESCALATE: go get ground truth. The
guarantee is model-agnostic and is checked empirically in the test suite rather than
asserted, including under a deliberately miscalibrated spread.

## Provenance: what a bad result implicates

The ledger counts plate hops. This layer tracks the individual material making them, and
it exists mostly to be honest about one operation.

```
$ autonomous-lab provenance
  pooled library, index map NOT recorded:
    attribution        confounded
    indistinguishable  96 contributor(s)
  pooled library, index map recorded:
    attribution        indexed
    indistinguishable  96 contributor(s)
```

Pooling is not a transfer, it is a loss of resolution. Ninety-six wells go into one tube
and a downstream measurement no longer refers to any one of them. If every input carried a
recorded index the resolution is recoverable by demultiplexing; if it did not, it is gone
permanently. A half-recorded index map is refused outright, because it would let a
demultiplexer silently drop the inputs it cannot name.

Every event also carries a witness -- machine, operator, or inferred -- and the chain
reports its **weakest** link, not its best. A chain with one inferred hop is an inferred
chain, however well instrumented the rest of it was. The reference lineage is inferred
throughout, and says so: no step in that protocol has an instrument that writes provenance.

## The record, and what a hash chain is worth

Every proposal, decision, and refusal lands in an append-only run record where each entry
carries the digest of the one before it. Edit an entry and `verify()` names it; delete or
reorder one and the links break. There is no update method and no delete method.

Stated plainly, because a tamper-evident log invites more faith than it has earned: it
detects edits to a written record, which is the failure it is aimed at. It does **not** make
the record true -- if the writer records a measurement that never happened, the chain
protects that lie as carefully as the truth, which is what the evidence tiers are for. And
it does **not** stop the author from rewriting the whole file. `seal()` returns the head
digest precisely so it can be handed to something outside the process; until it is, what
you have is an internally consistent record and calling it more would be an overclaim.

## Proposal and permission

Anything may ask. Only the gates decide.

```python
from autonomous_lab import Session
sess = Session(workcell=wc, lineage=lineage)
sess.request(step, proposer="agent:planner")   # recorded, never consulted
```

An agent, a scheduler, a controller, or a person proposes an action, and a deterministic
function decides. There is no argument that makes it more permissive, no confidence score
that buys leniency, and nothing a proposer can put in a request that changes the rules
applied to it. A test asserts that the most persuasive possible proposal -- system
override, pre-approved, urgent, confidence 0.99 -- gets a byte-identical decision to `cron`
asking plainly. If a model can reach the thing that decides, the safety property becomes a
property of the prompt rather than of the lab.

Refusals are first-class. A refused request writes a receipt asserting `commands_issued: 0`,
because "refused, nothing sent" and "no record of this step" are otherwise the same absence.
And every refusal carries the specific next action that would change the answer, which is
what a working scientist actually wants:

```
work orders (12 distinct, from 16 refusals)
```

Sixteen refusals collapse into twelve distinct things to change, including a distinction
worth the code it took: a gate can be UNMEASURABLE because the bench cannot produce a
number, or because it can and this request did not carry one. Those need different work, and
sending an operator to fix a working instrument would waste the trip.

## Control: which step to fix first

```
$ autonomous-lab control single_cell_genomics --record run.jsonl
  targeted_pcr_round1_cleanup      step 10   70.0% fail   expected waste  6.30 step(s)
  start_sort                       step  6   50.0% fail   expected waste  2.50 step(s)
  pta_wga_lysis                    step  8    7.1% fail   expected waste  0.50 step(s)
```

Ranked by expected waste, not by failure rate. A step that fails half the time at position
1 costs almost nothing -- you find out immediately and start again. The same rate at step 10
throws away nine completed steps, a plate, and a day. This complements `gaps`, which ranks
by what is impossible; this ranks by what is expensive.

Reliability is a Beta-Binomial posterior and prints its credible interval, because the
interesting regime for a real lab is five runs and not five hundred:

```
  start_sort    50.0% success   90% CI [0.10, 0.90]   n=2   (too few runs to act on)
```

The controller that proposes new setpoints has one invariant, and it is the reason the rest
of it is safe to have: **it cannot move a gate.** It proposes parameters. It has no API that
alters a criterion, widens a threshold, or overrides a judgement, and a test says so. An
optimizer that can relax its own acceptance criteria will eventually discover that the
cheapest way to satisfy a constraint is to delete it, and in a lab that is indistinguishable
from a scientist quietly lowering a cutoff until the run passes. Faced with criteria nothing
can satisfy, it refuses to propose rather than proposing something it expects to fail.

It also refuses to learn from itself. Only observations that earned a `measured` tier train
the surrogate; modeled and simulated runs are recorded and ignored. A controller that
learned from its own simulator would converge confidently on the simulator's biases, and it
would look exactly like learning.

The good Gaussian process lives in
[ml-bio-eval](https://github.com/di-omics/ml-bio-eval) behind numpy and sklearn. This one is
a kernel-weighted regression with a heuristic spread, deliberately: conformal calibration is
model-agnostic, so wrapping a crude spread still yields a real coverage guarantee, and the
whole package stays stdlib and computes on a laptop.

## Don't take my word for the hardware claims

The instrument registry is derived from `SEEDS`, so it cannot drift. The federated claims
have no such luxury: `validated_ops` is hand-written paths and prose about a repo this one
does not control, which makes it exactly the kind of assertion this package refuses to
accept from anybody else. So it ships a checker.

```
$ autonomous-lab doctor --plr-tested ../plr-tested
  [ok  ] star.pta_wga_lysis  run card exists: hamilton-star/starlab_live/00_pta_wga_...py
  [ok  ] star.pta_wga_lysis  confirm token appears in the run card: RUN_SINGLE_COL_PTA_HHS
  all 17 checkable claims hold.
```

For every operation this package calls validated, `doctor` confirms the run card really
exists at that path in your plr-tested checkout, and that the confirm token the ledger tells
you to type really appears in that script. It exits non-zero on drift. This caught a real
bug during development: every STAR step was citing `RUN_TARGETED_PCR_ODTC_LIDDED_FULL` when
the PTA/WGA run card actually gates on `RUN_SINGLE_COL_PTA_HHS`. The ledger was telling an
operator to type a token that would have refused the run.

What it deliberately **cannot** check is `evidence` -- whether an operator really watched the
thing run. That is prose about the physical world and no checker reaches it, which is why
the evidence strings stay narrow and carry their own caveats.

## Things it refuses to do

1. **Let an instrument's reputation transfer to a step.** plr-tested has a validated PTA/WGA
   addition and a validated targeted PCR choreography; it has no validated bead cleanup and
   no validated library pooling. Those cost out as manual even though they name a validated
   instrument.
2. **Let a caller declare what its own data is worth.** Evidence tiers are earned by checking
   the producing instrument against the registry. Claim `measured` off an instrument whose
   run card has never returned data and the claim is downgraded, with a reason.
3. **Pass a gate it cannot evaluate.** UNMEASURABLE is a verdict, distinct from FAIL and from
   ESCALATE, because the next action differs: engineering, versus judgement, versus a better
   measurement.
4. **Let a proposer influence its own decision.** Asserted by test.
5. **Let the optimizer touch the safety layer.** Asserted by test.
6. **Model only part of what would refuse a run.** `GuardedReplayer.setup()` has three
   preconditions, not one: coverage, an endpoint, and a transport a connection class can
   open.
7. **Skip ahead.** The executor performs the zero-decode reads and stops at the first step
   needing a human. A run that faked a sort and then truthfully read a run folder would be
   worse than useless.

## Safety

This package schedules, judges, and reports. It never actuates. `run --armed` performs only
the read-only operations -- enumerating a USB bus, probing a port, reading a run folder --
and there is no flag that moves an instrument. Anything that does goes through plr-re's
controllers, behind their own `armed` and `allow_actuation` switches, with a human present.

Note also plr-tested's hard constraint, which any scheduler built on this must respect: one
driver process per instrument. Two STAR clients raise `USBError [Errno 16] Resource busy`,
and on the ODTC the collision is quieter, because a second process re-registers the event
receiver and silently steals the first one's callbacks.

## Tests

```
pip install -e '.[dev]' && pytest
```

131 device-free tests. The ones that matter most try to make each layer lie: claim a step is
automated when its command is undecoded, promote a number off an instrument that has never
returned one, pass a gate with no measurement behind it, blame a well for a result that came
out of a 96-way pool, edit a decision after the fact, train the controller on its own
simulator, or talk the permission layer into a yes. The conformal coverage guarantee is
measured rather than asserted, under a deliberately miscalibrated spread. The doctor tests
prove the checker itself catches a renamed run card and a stale token, because a checker
that passed unconditionally would just launder the assertion.
