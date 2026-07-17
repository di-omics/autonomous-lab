# autonomous-lab

How much of an end-to-end lab run happens without a human, and what is in the way.

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

```
pip install 'autonomous-lab @ git+https://github.com/di-omics/autonomous-lab'

autonomous-lab stock                          # every instrument, its role, how far its map is
autonomous-lab ledger single_cell_genomics    # cost a protocol step by step
autonomous-lab gaps                           # the RE queue, ranked by steps freed
autonomous-lab run single_cell_genomics       # run it as far as it honestly goes
```

## What it reports today

Costing the single-cell genomics reference protocol (Namocell sort -> STAR whole-genome sequencing ->
ODTC PCR1 -> STAR library -> AVITI sequencing -> run-folder readout), with a plr-tested
checkout wired in via `--plr-tested`:

| | steps | |
| --- | --- | --- |
| automated | 3 of 17 | run headless today: two link preflights and the AVITI run-folder read |
| supervised | 2 of 17 | a validated run card exists in plr-tested, gated on a confirm token and an operator |
| blocked | 8 of 17 | the command is undecoded; the coverage gate refuses the run |
| manual | 4 of 17 | seating a cartridge, loading a flow cell, and two STAR steps nobody has written a validated script for |

**An unattended run reaches step 1 of 17 before it stops.** That number, not the 18%
autonomy figure, is what "how automated is this lab" actually means: a read-only step near
the end is only reachable if everything before it also ran. There are also 4 physical
plate hops that no amount of decoding removes -- only a plate mover does.

The reason the numbers are this low is the honest one. Across all six reverse-engineered
instruments, **0 of 54 seeded commands are decoded**. Not one of them can be driven
headlessly, and plr-re's own coverage gate refuses an armed run against an incomplete map.
The only real instrument contact available today is the AVITI run-folder read, USB
enumeration, and two socket probes. This tool exists to say that precisely, and to say
what would change it.

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

## Three things it refuses to do

1. **Let an instrument's reputation transfer to a step.** plr-tested has a validated
   whole-genome sequencing addition and a validated targeted PCR choreography; it has no validated bead cleanup
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

- `single_cell_genomics` -- Namocell sort, STAR whole-genome sequencing, ODTC targeted PCR PCR1, STAR library
  prep, AVITI sequencing, run-folder readout.
- `small_molecule_qc` -- VIAFLO 96 serial dilution, Biotage V-10 solvent removal, Agilent
  6530 Q-TOF LC/MS.

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

35 device-free tests. The ones that matter most try to make the ledger lie: claim a step
is automated when its command is undecoded, claim a decoded command is runnable while its
siblings are not, claim a federated leg runs when no run card was ever proven for it.
