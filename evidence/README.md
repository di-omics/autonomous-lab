# evidence/manifest.json

`manifest.json` is a byte-identical copy of the evidence manifest published by
`plr-tested` *(private)* -- supervised physical-instrument run cards and observed failures,
kept as evidence. Private because the work is high stakes, and a reader who cannot inspect
the evidence should not be shown a claim resting on it.

That privacy created a problem this file solves. `autonomous_lab/registry.py` records which
operations have met an instrument, and those records are hand-written prose about a repo
this one does not control. The checker that contradicts them used to require a checkout of
`plr-tested`, so in practice only its owner could run it, which is the one arrangement this
package refuses: a claim shown to a reader who cannot check it.

The manifest is status metadata. It names operations, run cards, confirm tokens, statuses,
hosts, dates, and the caveats attached to each -- and none of the operator-owned inputs
that made the source repo private. So the record can travel even though the repo cannot,
and `autonomous-lab doctor` runs the status comparison against this copy with no flag and
no checkout.

The copy is byte-identical on purpose. A reformatted or trimmed copy would be this
package's account of someone else's record, which is the kind of derivative assertion the
cross-check exists to eliminate. If it ever needs updating, replace it wholesale from the
source; do not edit it here.

Two strings inside the file point at the source tree and not at this one. Its `note` field
cites `evidence/check.py` and `evidence/README.md`; those are `plr-tested`'s own checker and
its own document, and neither is in this repo. The checker that runs here is
`autonomous-lab doctor`.

## Schema

`schema_version` is an integer, currently `1`. A consumer that does not recognise the value
should refuse the file rather than guess at it.

Five keys at the top level:

| key | type | meaning |
| --- | --- | --- |
| `schema_version` | integer | format version of this document |
| `note` | string | prose stating what the file is and that it, not the README tables, is what a machine should read |
| `vocabulary` | object | status name -> its definition, so the words are defined in the file that uses them |
| `hosts` | object | host id -> what that machine is wired to |
| `instruments` | array | one entry per instrument |

`vocabulary` carries the whole status vocabulary, and the definitions are the file's own:

| status | definition |
| --- | --- |
| `validated` | ran on the physical instrument, with a person watching, and passed |
| `written` | the script exists and runs dry or sim-clean; it has never met the instrument |
| `failed` | ran on the physical instrument and did not pass |
| `not_started` | named as intended work; no script exists yet |

`failed` is a status and not an omission. A run card that exists and fails is a fact about
the lab, and dropping it would make a known defect look like unwritten work.

`hosts` maps a short id to a one-line description of the machine. The current file declares
two, `starpi` and `starpi2`. Every `observed.host` value is one of these keys, which is why
the map exists: a bare hostname in a run record means nothing to a reader who has never
seen the bench.

### instruments[]

| field | type | meaning |
| --- | --- | --- |
| `key` | string | short identifier, unique across the array (`star`, `hhs`, `odtc`, `tecan`) |
| `device` | string | what the instrument is, in words |
| `entry` | string | repo-relative path to the run card entry point that dispatches this instrument's scripts |
| `operations` | array | the operations recorded for it |

`entry` is not unique across instruments, and that is a fact about the bench rather than a
duplication: `star` and `hhs` share `liquid-handler/run_on_pi.sh` because the heater-shaker
is driven over the liquid handler's bus, and `odtc` and `tecan` share
`instrument-integrations/run_on_pi.sh`.

### instruments[].operations[]

Every operation object carries all eight fields. None is optional; absence is expressed as
`null` or as an empty string or array, so a consumer never has to distinguish "not recorded"
from "not applicable" by whether a key is present.

| field | type | meaning |
| --- | --- | --- |
| `op` | string | operation name, unique within its instrument. This is the join key against `registry.py` |
| `script` | string or null | repo-relative path to the run card; `null` when no script exists |
| `confirm_token` | string or null | the literal token an operator must pass to `--confirm`; `null` when the run card has no confirm gate |
| `status` | string | one of the four `vocabulary` keys |
| `wet` | boolean | whether the operation involves liquid |
| `observed` | object or null | `{ "host": <hosts key>, "date": "YYYY-MM-DD" }`; `null` when nothing was observed |
| `evidence` | string | one or two sentences on what was actually seen. Empty string when nothing has been seen |
| `caveats` | array of strings | what the status does not cover. Empty array when there is nothing to qualify |

### Invariants

These hold across the current file and a conforming manifest should preserve them, because
each one is what keeps a status from reading as more than it is.

- `script` is `null` exactly for the `not_started` operations. A status of `written` or
  better implies a path.
- `observed` is non-null exactly for `validated` and `failed`. Both mean the operation met
  the instrument, and a meeting has a host and a date. `written` and `not_started` never
  carry an `observed` block, because there is nothing to have observed.
- `evidence` is an empty string exactly for the `not_started` operations, and non-empty
  everywhere else.
- `confirm_token` is independent of `status`. It is `null` for operations at three
  different statuses, including validated ones, because a confirm gate is a property of how
  the run card is written and not of whether anyone has watched it run.
- `observed.date` is ISO `YYYY-MM-DD`. It records when the operation was observed, not when
  the file was written.
- No `validated` operation has `wet: true`. Everything proven on an instrument so far was
  proven dry, and the flag is what stops a dry proof from being read as a wet one.

### Counts in the current file

4 instruments and 19 operations: 13 `validated`, 2 `written`, 1 `failed`, 3 `not_started`.
The one `failed` operation is `tecan.read_absorbance`. Both `wet: true` operations are
unproven -- one `written`, one `not_started`.

## Building a conforming checkout

These are the three things the manifest asserts about the tree it describes:

1. Every `instruments[].entry` path exists, relative to the checkout root.
2. Every non-null `operations[].script` path exists, relative to the checkout root.
3. Every script whose operation has a non-null `confirm_token` contains that token
   literally. The token is what an operator is told to type, so if it is not in the file,
   the run refuses and the instruction was wrong.

Nothing else about the tree is specified. The manifest says where the run cards are and
what they are gated on; it says nothing about their contents, and it cannot.

`autonomous-lab doctor --plr-tested PATH` checks those three, but only for the operations
this package actually models: 9 of the 19 the manifest carries. The other 10 are recorded
here and unmodelled, so nothing in this repo opens their files. A conforming checkout has
to hold for all 19; this package can only speak for the subset it cites.

## What the file deliberately does not contain

The manifest is metadata about runs, not the runs. Three of its caveat lines state the
exclusion in the file itself: transfer volumes, source mapping and wet-run parameters are
"operator-owned inputs and are not recorded here"; so are cleanup ratio, input volume and
reagent settings; and for the supervised PCR-enrichment cycling, "Operator method values
are not published."

So the file carries no reagents, no volumes, no protocol method values, no run card bodies
-- only repo-relative paths to them -- and no addresses or credentials for anything on the
bench. The only machine identifiers in it are the two `hosts` nicknames, which are labels
for a reader rather than anything reachable.

Instrument observations are a different matter and they do appear: bring-up setpoints, the
block and lid ceilings, a USB device id, timings. Those are facts about the machine, and
publishing them costs nothing and lets a reader judge the caveats. What stays out is the
experiment.

That split is why this copy exists. Everything needed to contradict a status claim is here;
everything that made the source repo private is not.
