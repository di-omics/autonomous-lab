"""Reference rubrics: the acceptance criteria the single-cell genomics run is gated on.

These are transcribed from the rubrics that already exist in di-omics/plr-tested, with one
change that is the reason this file is worth reading: every threshold carries the origin it
actually has, rather than the origin it looks like it has when you read the code.

The honest finding from going through that repo is worth stating plainly, because it is
not what the code appears to say. Of the thresholds those gates enforce, essentially none
are cited to an external document. The numbers that ARE carefully sourced there -- the
PicoGreen 480/520 optics, the Rhodamine 554/627 maxima, the 0.90X and 0.65X bead ratios,
the 22.5 uL master mix -- are assay optics and reagent volumes. The QC cutoffs that decide
whether a sample lives or dies are local defaults, several of them marked TUNABLE in their
own source. That is a completely reasonable place for a young assay to be. It is only a
problem if the rubric presents them as settled, so here they are marked TUNABLE and the
report says so every time it prints them.

The two genuinely transcribed thresholds in this file come from the EM-seq rubric, where
the control-read minima are attributed to a kit document. They are included precisely so
the difference between a cited number and a working default is visible side by side.

The other thing these rubrics show is what the ledger has been saying all along, arriving
from the other direction. Three of the five gates below need a number from the plate
reader, and the plate reader has never returned one. They do not evaluate to PASS or FAIL.
They evaluate to UNMEASURABLE, which is the correct answer and is not available in the
gate machinery these were transcribed from: there, an out-of-curve read still receives a
hard pass or fail from an extrapolated concentration.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from .acceptance import Criterion, Gate, Origin

# Where these came from, so a reader can go check. Paths are in di-omics/plr-tested.
_GENE_EDIT = "plr-tested packages/gene-edit/edit_confirmation/config.py"
_EMSEQ = "plr-tested packages/emseq/configs/acceptance_criteria.yaml"


LIQUID_HANDLING = Gate(
  name="liquid_handling_qualification",
  guards="any sample material touching the deck",
  produced_by=("tecan", "read_absorbance"),
  criteria=(
    Criterion(
      metric="dispense_cv_percent",
      comparator="<=",
      threshold=5.0,
      units="%",
      origin=Origin.TUNABLE,
      source=(
        f"{_GENE_EDIT}:130 lh_cv_max_percent, described there as an operator-set "
        "liquid-handling qualification cutoff on the Rhodamine B dispense. Not "
        "externally cited; a local working default"
      ),
      note="measured across 8 replicates per volume, one STAR channel column",
    ),
    Criterion(
      metric="curve_r2",
      comparator=">=",
      threshold=0.98,
      units="R2",
      origin=Origin.TUNABLE,
      source=(
        f"{_GENE_EDIT}:137 curve_r2_min, standard-curve linearity floor. Rationale "
        "given in-repo, no external citation"
      ),
    ),
  ),
  note=(
    "Gate 0. Everything downstream inherits this: if the deck cannot dispense "
    "reproducibly, no later number means anything."
  ),
)


AMPLIFICATION_YIELD = Gate(
  name="amplification_yield",
  guards="committing amplified material to library prep",
  produced_by=("tecan", "read_absorbance"),
  criteria=(
    Criterion(
      metric="pta_yield_ng",
      comparator=">=",
      threshold=100.0,
      units="ng",
      origin=Origin.TUNABLE,
      source=(
        f"{_GENE_EDIT}:140 pta_yield_min_ng, whose own source string says: TUNABLE, set "
        "from the whole-genome amplification yield seen on your samples, verify"
      ),
      note="mass over a 12 uL reaction; the ng/mL to ng/uL conversion is a known 1000x trap",
    ),
    Criterion(
      metric="yield_cv_percent",
      comparator="<=",
      threshold=30.0,
      units="%",
      origin=Origin.TUNABLE,
      source=(
        f"{_GENE_EDIT}:141 pta_yield_cv_max_percent, in-repo rationale 'systematic "
        "amplification spread; above this the run is suspect'. Not externally cited"
      ),
    ),
  ),
  note="Gate 1. Drops wells rather than stopping the run, when the run-level checks hold.",
)


LIBRARY_LOADING = Gate(
  name="library_loading_window",
  guards="committing a flow cell",
  produced_by=("tecan", "read_absorbance"),
  criteria=(
    Criterion(
      metric="library_conc_ng_per_ul",
      comparator=">=",
      threshold=2.0,
      units="ng/uL",
      origin=Origin.TUNABLE,
      source=(
        f"{_GENE_EDIT}:144 library_conc_min_ng_per_ul, own source string: TUNABLE, "
        "loading window for TapeStation and the sequencer, verify"
      ),
    ),
    Criterion(
      metric="library_conc_ng_per_ul",
      comparator="<=",
      threshold=60.0,
      units="ng/uL",
      origin=Origin.TUNABLE,
      source=f"{_GENE_EDIT}:145 library_conc_max_ng_per_ul, same TUNABLE string",
    ),
  ),
  note=(
    "Gate 2. This is the gate the reference protocol stops at, and the one that makes "
    "the reader's failure expensive rather than cosmetic."
  ),
)


THERMAL_HEADROOM = Gate(
  name="thermal_headroom",
  guards="running a real thermal cycle on material",
  produced_by=("odtc", "targeted_pcr_round1"),
  criteria=(
    Criterion(
      metric="setpoint_error_C",
      comparator="<=",
      threshold=1.0,
      units="C",
      origin=Origin.TUNABLE,
      source=(
        "no published band for this assay. The one validated run observed a mean "
        "setpoint error of 0.27 C over 30 cycles (plr-tested instrument-integrations/"
        "odtc, on the instrument 2026-07-10), so 1.0 C is a working default with real "
        "headroom over the only evidence available"
      ),
    ),
    Criterion(
      metric="block_ceiling_headroom_C",
      comparator=">=",
      threshold=2.0,
      units="C",
      origin=Origin.TODO,
      source=(
        "nobody has set a required headroom. The validated program denatures at 98 C "
        "against a 99 C block ceiling, which is 1 C of margin, and no one has decided "
        "whether that is acceptable for a real run. Until they do, this gate cannot "
        "pass material"
      ),
      note="the honest state of a known risk, rather than a number invented to clear it",
    ),
  ),
  note=(
    "The only gate here whose numbers come off an instrument that has actually produced "
    "them. It still cannot pass, because the second threshold is nobody's decision yet."
  ),
)


SEQUENCING_CONTROLS = Gate(
  name="sequencing_controls",
  guards="accepting a sequencing run as usable",
  # Not a zero-decode read: the run folder reports state and outcome, not per-control read
  # counts. Naming the run-folder watcher here would be the overclaim -- it would make a
  # gate look evaluable because a nearby, different thing works.
  produced_by=("element_aviti", "read_control_metrics"),
  criteria=(
    Criterion(
      metric="lambda_reads",
      comparator=">=",
      threshold=5000.0,
      units="reads",
      origin=Origin.TRANSCRIBED,
      source=f"NEB M7634 v3.0 section 3.1.1 control-read minima, via {_EMSEQ}",
    ),
    Criterion(
      metric="puc19_reads",
      comparator=">=",
      threshold=500.0,
      units="reads",
      origin=Origin.TRANSCRIBED,
      source=f"NEB M7634 v3.0 section 3.1.1 control-read minima, via {_EMSEQ}",
    ),
  ),
  note=(
    "The only externally cited thresholds in this file, and they still evaluate to "
    "UNMEASURABLE: a well-sourced rubric in front of an instrument with no decoded read "
    "is not closer to running than an unsourced one."
  ),
)


REFERENCE_GATES: Dict[str, Gate] = {
  g.name: g
  for g in (LIQUID_HANDLING, AMPLIFICATION_YIELD, LIBRARY_LOADING, THERMAL_HEADROOM, SEQUENCING_CONTROLS)
}


# Which gate stands in front of which step of the reference protocol. A gate guards the
# step it is listed against: it is evaluated before that step is allowed to start.
GATES_FOR_STEP: Dict[str, Tuple[str, ...]] = {
  "pta_wga_lysis": ("liquid_handling_qualification",),
  "targeted_pcr_round1": ("thermal_headroom",),
  "targeted_pcr_round1_cleanup": ("amplification_yield",),
  "start_run": ("library_loading_window",),
  "watch_run_folder": ("sequencing_controls",),
}


def get(name: str) -> Gate:
  if name not in REFERENCE_GATES:
    raise KeyError(f"unknown gate '{name}'; known: {sorted(REFERENCE_GATES)}")
  return REFERENCE_GATES[name]


def gates_for(op: str) -> List[Gate]:
  """Every gate that must clear before this operation may start."""
  return [REFERENCE_GATES[n] for n in GATES_FOR_STEP.get(op, ())]
