"""What the published field has actually demonstrated, and the gap to what is being claimed.

Every other module in this package answers a question about THIS lab: which steps run
headless, which gates can fire, what a camera could see, what a run could prove afterwards.
None of them can check an ambition against the outside world. That is the gap this module
closes, and it exists because of a specific, routine, and expensive failure of reasoning.

An autonomous-lab claim is almost never defended on its own evidence. It is defended by
pointing at a famous paper. The paper is real, the result is real, and the scope of the
result is far narrower than the claim it is being made to carry -- a solid-state materials
campaign gets cited to justify a cell-biology production line, a fifteen-hour single-plate
yeast run gets cited to justify sustained unattended culture, a text benchmark gets cited to
justify letting a model judge hazards at a bench. Nobody in that chain lies. The citation is
accurate and the inference is not, and there is no artifact anywhere in the usual workflow
that makes the inference checkable.

So each published work here carries two fields, and the second one is the reason the module
exists. `demonstrates` records what the work showed, with the real numbers. `does_not_establish`
records the boundary its own authors, correctors, or published critics drew around it. A
citation with no stated scope limit is not a strong citation; it is an unread one, and the
tests refuse to let one exist in this table.

The load-bearing computation is `support_for(claim_domain, scope)`. Given a domain and a
claimed operating scope it returns the evidence that speaks to the claim at all, and for each
one the SHORTFALL between what was demonstrated and what is being asserted. Domain is the
first cut and it is harsh on purpose: inorganic powders do not contaminate, do not lose
viability, and do not drift in state between Tuesday and Thursday, so a materials campaign is
not weak evidence about a cell assay, it is evidence about something else. Duration and
repetition are the second cut, and they are where the in-domain citations fall down. Nothing
in this table demonstrates a lab operating without a human at a production rate, and
`unsupported_claims()` is the standing list of the things that keep getting asserted anyway.

CONFIDENCE mirrors `qc.Basis`. There, a threshold from a kit insert and a threshold this lab
titrated are both real and only one is validated. Here, an entry whose every stated number was
confirmed against the source and an entry where an attribution could not be confirmed are both
real and only one is CONFIRMED. The unconfirmable numbers are carried explicitly rather than
dropped or rounded away, because a verification pass whose misses are invisible is worth less
than no verification pass -- it produces the same table with unearned authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple


class Domain(str, Enum):
  """The field a published work actually operated in.

  The load-bearing line is LIVING. Material that is alive fails in ways non-living matter
  cannot: it contaminates, it loses viability, it changes state while it waits, and it is
  never twice in the same condition. A demonstration on inorganic powder or on small
  molecules in flow says nothing about any of those, however impressive the automation, so
  cross-domain citation is not a matter of degree here. It is a category error, and drawing
  the line in the enum is what makes it computable rather than a matter of taste.
  """

  MATERIALS = "materials"  # solid-state inorganic synthesis and characterization
  CHEMISTRY = "chemistry"  # organic and supramolecular synthesis
  CELL_ASSAY = "cell_assay"  # cultured cells, plate-based
  IN_VIVO = "in_vivo"  # whole animals
  ORCHESTRATION = "orchestration"  # workflow management across instruments
  PROVENANCE = "provenance"  # records, custody, audit
  SAFETY = "safety"  # hazard knowledge and hazard judgment
  ABSTRACTION = "abstraction"  # hardware-agnostic control interfaces and their standards

  @property
  def living(self) -> bool:
    return self in (Domain.CELL_ASSAY, Domain.IN_VIVO)


class EvidenceKind(str, Enum):
  """What kind of thing a published work is, which decides what it can ever support.

  The line is DEMONSTRATES_OPERATION, and only EMPIRICAL_DEMONSTRATION crosses it. The other
  four are routinely cited as though they did. A BENCHMARK measures models or methods against
  constructed tasks and no lab ran. A RESOURCE supplies data or software and no scientific
  question was answered. GUIDANCE and STANDARD say what ought to be done and are evidence that
  a practice is recommended, never that anyone achieved it. Citing a standard as proof of
  capability is the most common form of this error, because a standard's existence is easy to
  mistake for its satisfaction.
  """

  EMPIRICAL_DEMONSTRATION = "empirical_demonstration"  # a lab ran and reported what happened
  BENCHMARK = "benchmark"  # constructed tasks scoring models or methods
  GUIDANCE = "guidance"  # recommended practice, nonbinding
  STANDARD = "standard"  # a normative specification
  RESOURCE = "resource"  # a dataset or a piece of software

  @property
  def demonstrates_operation(self) -> bool:
    return self is EvidenceKind.EMPIRICAL_DEMONSTRATION


class Confidence(str, Enum):
  """How much of what this module states about a work was confirmed against the source.

  The same distinction `qc.Basis` draws between a vendor's number and this lab's own. PARTIAL
  is not a doubt about the work; the works here are real and correctly cited. It means a
  number or an attribution that this module would otherwise state could not be checked at the
  source, usually because the article is paywalled and verification rested on a preprint or on
  press coverage. Those items are listed in `unverified` rather than quietly softened, because
  the alternative is a table where the checked and the unchecked look identical.
  """

  PARTIAL = "partial"  # at least one stated number or attribution is unconfirmed
  CONFIRMED = "confirmed"  # every number stated in `demonstrates` was confirmed at the source

  @property
  def fully_verified(self) -> bool:
    return self is Confidence.CONFIRMED


@dataclass(frozen=True)
class Scope:
  """An operating envelope: either what a work demonstrated, or what a claim asserts.

  One type for both sides on purpose. A scope gap is then a comparison of like with like
  rather than prose judgment, and a claim that cannot be written as a scope is a claim too
  vague to check -- which is itself worth discovering before it reaches a slide.

  `continuous_hours` exists only to make duration comparable and is None wherever the source
  hedges. Dai et al. wrote "almost four consecutive days"; converting that to 96 would
  manufacture a precision the authors deliberately withheld. `duration_verbatim` carries the
  authors' own words and is the field to quote.
  """

  summary: str
  material: str = ""
  duration_verbatim: str = ""
  continuous_hours: Optional[float] = None
  # One campaign is descriptive of that campaign. Without repetition a success rate is a
  # record of what happened once, not a capability.
  replicated: bool = False
  # Repeated campaigns at a steady rate over a deployment, as opposed to a single bounded
  # run. This is the field every production claim turns on and no demonstration here sets.
  sustained: bool = False
  # Asserted only by claims. A demonstration declares `human_in_loop` instead.
  unattended: bool = False
  # What a person still did. Empty on a demonstration means fully unattended operation, and
  # nothing in this table is entitled to leave it empty.
  human_in_loop: str = ""

  @property
  def asserts_nothing_comparable(self) -> bool:
    """True when a claim names no material, no duration, and no operating property.

    Such a claim is not modest, it is unwritten. Every comparison below is gated on the
    claim asserting something, so an unwritten claim produces zero shortfalls -- and zero
    shortfalls reads as full support. That is the same defect `qc` guards on the other side
    of this package, where a gate evaluated against an empty measurement dict passes every
    criterion vacuously. A missing assertion is not a satisfied one, and the ambition living
    in `summary` prose is not a thing this module can check.
    """
    return (
      not self.material.strip()
      and self.continuous_hours is None
      and not self.sustained
      and not self.replicated
      and not self.unattended
    )


@dataclass(frozen=True)
class Evidence:
  """One published work, what it showed, and the boundary around it.

  `shorthand` is the phrase this module uses when it refuses a citation, and it is built from
  verified numbers only -- "a 17-day materials campaign", "a 15-hour single-plate yeast run".
  Naming the scope in the refusal is the whole point: "that paper does not support this" is an
  opinion, and "a 15-hour single-plate yeast run does not reach sustained production" is a
  statement someone can check and argue with.

  `does_not_establish` is never optional and never generic. It carries what the authors, the
  published corrections, or the published critics said the work does not show.
  """

  key: str
  citation: str
  url: str
  domain: Domain
  kind: EvidenceKind
  year: int
  confidence: Confidence
  shorthand: str
  demonstrates: str
  does_not_establish: str
  scope: Scope
  # Specific numbers and attributions that could not be confirmed at the source. Carried on
  # CONFIRMED entries too: those are figures in circulation that this module declines to
  # state, and recording them is what stops a later editor from reintroducing one.
  unverified: Tuple[str, ...] = ()

  def __post_init__(self) -> None:
    if not self.does_not_establish.strip():
      raise ValueError(
        f"evidence '{self.key}' states no scope limit; a citation whose boundary nobody "
        "wrote down is the failure mode this module exists to prevent"
      )
    if not self.url.strip():
      raise ValueError(f"evidence '{self.key}' carries no URL or DOI; it cannot be checked")
    if self.confidence is Confidence.PARTIAL and not self.unverified:
      raise ValueError(
        f"evidence '{self.key}' is PARTIAL but names nothing unverified; a confidence "
        "downgrade with no reason attached cannot be acted on or retired"
      )

  @property
  def verified(self) -> bool:
    return self.confidence.fully_verified


# -- the works themselves -------------------------------------------------------
# Numbers are the ones confirmed at the source. Where a figure is in circulation and did not
# survive checking, it is named in `unverified` and stated nowhere else.

EVIDENCE: Tuple[Evidence, ...] = (
  Evidence(
    key="a_lab",
    citation=(
      "Szymanski, N. J. et al. 'An autonomous laboratory for the accelerated synthesis of "
      "inorganic materials.' Nature 624, 86-91 (2023). doi:10.1038/s41586-023-06734-w. "
      "Author Correction: Nature 650, E1 (19 January 2026), doi:10.1038/s41586-025-09992-y; "
      "the corrected version is the one cited here"
    ),
    url="https://doi.org/10.1038/s41586-023-06734-w",
    domain=Domain.MATERIALS,
    kind=EvidenceKind.EMPIRICAL_DEMONSTRATION,
    year=2023,
    confidence=Confidence.CONFIRMED,
    shorthand="a 17-day materials campaign",
    demonstrates=(
      "Autonomous solid-state synthesis of computationally nominated inorganic targets. Over "
      "17 days of continuous operation the platform realized 36 compounds from a set of 57 "
      "targets, a 63 percent rate; the remainder were 4 reclassified as inconclusive and 17 "
      "outright failures. Robotic powder dispensing and mixing, a UR5e arm on a linear rail, "
      "four box furnaces, automated X-ray diffraction with phase identification against the "
      "Inorganic Crystal Structure Database followed by automated Rietveld refinement. Routes "
      "were improved in the loop by the ARROWS3 algorithm from pairwise reactions observed in "
      "failed attempts; initial recipes came from natural-language models trained on the "
      "literature. Targets were oxides and phosphates drawn from ab initio phase-stability data"
    ),
    does_not_establish=(
      "Not discovery of new-to-science materials. The 2026 Author Correction removed 'novel' "
      "from the title and the authors clarified that the intended meaning was new to the "
      "prediction platform, not new to science; the paper establishes autonomous synthesis and "
      "realization of nominated targets. The headline figure is itself a downgrade from the "
      "original 41 of 58: one target was removed as present in the algorithms' training data "
      "and so not a blind target, and 4 of the remaining reported successes were reclassified "
      "as inconclusive from XRD alone -- any pre-2026 copy still shows 41/58 and the old "
      "title. Substantive external critique remains open: Leeman et al., PRX Energy 3, 011002 "
      "(2024) reported substantial errors in the automated powder-XRD analysis and concluded "
      "there was insufficient evidence for the discovery of new materials, the core objection "
      "being that the pipeline did not handle compositional disorder, so ordered versions of "
      "already-known disordered compounds were read as new phases. The correction acknowledges "
      "concerns about unambiguous identification by diffraction without conceding all points. "
      "The senior author's public response concedes the analysis limit directly: a human can "
      "perform a higher-quality refinement on these samples, and replacing the human "
      "materials-discovery process was never the intention. Success means a phase was judged "
      "realized by automated XRD and Rietveld refinement -- not single-crystal confirmation, "
      "not independent replication, not expert review. No material property was measured, no "
      "application was demonstrated, and no claim is made about scale-up or about the value of "
      "any compound produced. One campaign, one instrument, no baseline against human chemists "
      "and no repetition, so 63 percent describes this run and is not a capability benchmark"
    ),
    scope=Scope(
      summary="one continuous campaign of solid-state synthesis on inorganic oxide and phosphate powders",
      material="inorganic oxide and phosphate powders",
      duration_verbatim="over 17 days of continuous operation",
      continuous_hours=408.0,
      replicated=False,
      sustained=False,
      human_in_loop=(
        "the four reclassified targets and the disorder objection were both resolved by human "
        "reading of the diffraction data, not by the workflow"
      ),
    ),
    unverified=(
      "the per-failure-mode breakdown does not reconcile: sluggish kinetics 11, precursor "
      "volatility 1, amorphization 1, computational inaccuracy 3 sums to 16 against 17 failed "
      "targets, so no per-mode count is stated here",
      "which 4 compounds were reclassified as inconclusive; the corrected figure and revised "
      "supplementary data could not be retrieved",
      "whether any of the 36 successes have since been independently reproduced by a non-XRD "
      "method; no evidence was found either way",
      "'43 new materials', which appears in news coverage, matches no version of the paper "
      "(41 original, 36 corrected) and is not used",
    ),
  ),
  Evidence(
    key="dai",
    citation=(
      "Dai, T., Vijayakrishnan, S., Szczypinski, F. T., Ayme, J.-F., Simaei, E., Fellowes, T., "
      "Clowes, R., Kotopanov, L., Shields, C. E., Zhou, Z., Ward, J. W. & Cooper, A. I. "
      "'Autonomous mobile robots for exploratory synthetic chemistry.' Nature 635, 890-897 "
      "(2024). doi:10.1038/s41586-024-08173-7"
    ),
    url="https://www.nature.com/articles/s41586-024-08173-7",
    domain=Domain.CHEMISTRY,
    kind=EvidenceKind.EMPIRICAL_DEMONSTRATION,
    year=2024,
    confidence=Confidence.CONFIRMED,
    shorthand="an almost-four-day exploratory chemistry campaign",
    demonstrates=(
      "Mobile robots linking an automated synthesis platform to remotely located, unmodified "
      "UPLC-MS and 80-MHz benchtop NMR instruments. The structural-diversification campaign "
      "operated for almost four consecutive days under autonomous decision making; a separate "
      "supramolecular campaign ran continuously over 3 days. Three campaigns in total -- "
      "structural diversification, supramolecular host-guest, photochemical synthesis -- "
      "producing 12 structurally diverse analogues through 3 autonomous synthetic steps from 6 "
      "targeted ureas and thioureas, screening 18 possible combinations, and testing six "
      "photocatalysts against a blank control. Two task-specific mobile robots were used, and "
      "the same tasks were also demonstrated with a single robot and a multipurpose gripper"
    ),
    does_not_establish=(
      "Not autonomous structure elucidation and not autonomous anomaly detection, and the "
      "paper supplies its own counterexample. Compound 13 underwent an unexpected "
      "intramolecular cyclization to a species with the same molecular weight as the expected "
      "product, indistinguishable by UPLC chromatogram or MS alone. The workflow acquired the "
      "NMR data; the heuristic decision rule did not flag it, and it was identified by human "
      "inspection and confirmed by single-crystal X-ray diffraction, an off-workflow manual "
      "measurement. The authors concede the discoveries required post-experiment analysis by "
      "human researchers. It involves no machine learning: the decision maker is an explicit "
      "tiered heuristic with success criteria designed by domain experts and thresholds set at "
      "the start, positioned by the authors as an alternative to black-box models for "
      "analytically complex, data-sparse problems, so it is not evidence about AI-driven or "
      "self-improving labs. Analytical resolution is explicitly limited: the low field "
      "strength of the 80-MHz benchtop instrument can artificially increase the apparent number "
      "of peaks. The speed claim is narrow -- the authors claim only that the algorithmic "
      "decisions are effectively instantaneous, which is acceleration of the decision step, not "
      "superior synthetic throughput or chemical judgment. Scalability to industrial labs and "
      "transfer to other reaction classes are stated as expectations, not results, and the "
      "reaction and product space was human-specified up front"
    ),
    scope=Scope(
      summary="three bounded exploratory campaigns within a human-specified reagent space",
      material="organic and supramolecular small molecules in solution",
      duration_verbatim="almost four consecutive days",
      # The authors hedged the figure. Converting "almost four days" to 96 would manufacture
      # a precision they withheld, so duration is not comparable for this entry and the gap
      # says so rather than guessing.
      continuous_hours=None,
      replicated=False,
      sustained=False,
      human_in_loop=(
        "success criteria and thresholds were set by domain experts before the run, and the "
        "one anomaly that mattered was caught by human inspection plus off-workflow "
        "single-crystal X-ray diffraction"
      ),
    ),
  ),
  Evidence(
    key="coley",
    citation=(
      "Coley, C. W.; Thomas, D. A., III; Lummiss, J. A. M.; Jaworski, J. N.; Breen, C. P.; "
      "Schultz, V.; Hart, T.; Fishman, J. S.; Rogers, L.; Gao, H.; Hicklin, R. W.; Plehiers, "
      "P. P.; Byington, J.; Piotti, J. S.; Green, W. H.; Hart, A. J.; Jamison, T. F.; Jensen, "
      "K. F. 'A robotic platform for flow synthesis of organic compounds informed by AI "
      "planning.' Science 2019, 365 (6453), eaax1566. doi:10.1126/science.aax1566"
    ),
    url="https://www.science.org/doi/10.1126/science.aax1566",
    domain=Domain.CHEMISTRY,
    kind=EvidenceKind.EMPIRICAL_DEMONSTRATION,
    year=2019,
    confidence=Confidence.PARTIAL,
    shorthand="a 15-compound flow-synthesis demonstration",
    demonstrates=(
      "A modular continuous-flow platform, automatically reconfigured by a robotic arm to set "
      "up the required unit operations, executing routes proposed by generalization over "
      "millions of published reactions and validated in silico. Demonstrated for 15 drug or "
      "drug-like substances. Additional implementation details are determined by expert "
      "chemists and recorded in reusable recipe files; solvent choice and precise stoichiometry "
      "are named as part of that human step"
    ),
    does_not_establish=(
      "Not autonomous or end-to-end AI-driven synthesis. The AI proposes routes only; a human "
      "expert chemist must translate each proposed route into an executable recipe file, "
      "because the chemical literature does not contain enough information to get from "
      "inspiration to execution automatically. The authors' own framing is a step toward a "
      "paradigm, computer-augmented. Not discovery: all 15 targets are known drug or drug-like "
      "substances made by literature-precedented chemistry, with no novel molecules, no novel "
      "reactions, and no medicinal-chemistry findings. Not closed-loop optimization or "
      "self-correction -- the platform executes a fixed human-refined recipe, and automated "
      "optimization on this same platform arrived only in later work. Not general across "
      "chemistry: the system is bounded by what the modular flow hardware can host. Fifteen "
      "successful targets is a demonstration set and not a success rate; no verifiable "
      "denominator of attempted-and-failed targets exists, so the work supports no statement "
      "about reliability"
    ),
    scope=Scope(
      summary="15 known drug or drug-like targets, each executed from a human-authored recipe file",
      material="organic small molecules in continuous flow",
      duration_verbatim="not stated in any source that could be verified",
      continuous_hours=None,
      replicated=False,
      sustained=False,
      human_in_loop=(
        "an expert chemist authors the recipe file for every route, supplying solvent and "
        "stoichiometry that the route planner does not"
      ),
    ),
    unverified=(
      "that safety or hazard assessment is part of the expert refinement step; the abstract "
      "says only 'additional implementation details' and no accessible source attributes "
      "safety to it, so safety is not claimed here",
      "duration figures of roughly two hours for the simplest target and about 68 hours for "
      "manufacturing multiple compounds, which appear only in press coverage and are stated "
      "nowhere in this entry",
      "a breadth figure of about 30 different reactions, also press-only",
      "'eight distinct retrosynthetic routes and nine process configurations' returned by a "
      "metadata summarizer, which could not be corroborated against the paper and is treated "
      "as fabricated",
      "the identities of the 15 compounds, which are inconsistent across press coverage and "
      "are therefore not enumerated",
    ),
  ),
  Evidence(
    key="roboculture",
    citation=(
      "Angers, K., Darvish, K., Yoshikawa, N., Okhovatian, S., Bannerman, D., Yakavets, I., "
      "Shkurti, F., Aspuru-Guzik, A., & Radisic, M. (2026). 'RoboCulture enables modular "
      "robotic plate-based cell automation.' Cell Reports Physical Science, 7(7), 103335. "
      "doi:10.1016/j.xcrp.2026.103335. Preprint: arXiv:2505.14941"
    ),
    url="https://doi.org/10.1016/j.xcrp.2026.103335",
    domain=Domain.CELL_ASSAY,
    kind=EvidenceKind.EMPIRICAL_DEMONSTRATION,
    year=2026,
    confidence=Confidence.PARTIAL,
    shorthand="a 15-hour single-plate yeast run",
    demonstrates=(
      "A general-purpose robotic manipulator automating plate-based cell culture using vision "
      "and force feedback and a modular behavior-tree framework to execute, monitor, and manage "
      "experiments. A fully autonomous 15-hour yeast culture experiment, with visual servoing "
      "centering the pipette tip over any well of an arbitrarily positioned 96-well plate: 99.0 "
      "percent pipette-tip insertion success over 576 attempts across six random plate "
      "placements, 92.4 percent of them perfect. Three replicate groups at initial "
      "concentrations of 50, 30 and 10 million cells/mL plus blank controls, with 3x dilution "
      "into fresh media at subculturing"
    ),
    does_not_establish=(
      "Not unattended autonomy, and seeding was not the only manual step. The authors state "
      "that splitting was manually initiated as a safety precaution: the robot detected "
      "saturation and tracked growth, but a human authorized the subculturing decision, which "
      "is the headline autonomous-decision capability. Initial seeding of cells likewise "
      "remains a manual step performed before the run. The visual servoing does not generalize "
      "-- it is specifically tailored for well plates and does not generalize to other "
      "laboratory equipment. Perception is fiducial-tag dependent and brittle: it assumes tags "
      "remain unoccluded and requires a calibration process that the authors call fragile and "
      "time-consuming to maintain. The authors explicitly disclaim generality, describing the "
      "system as not yet a fully generalizable system. It is not a throughput claim: they "
      "position it as operating more like an autonomous vehicle tailored to individual or "
      "small-group use than for high-throughput screening, and it neither beats commercial "
      "liquid handlers on throughput nor claims to. The biology is yeast culture only, so it "
      "establishes nothing about mammalian or primary cell culture, nothing about sterility "
      "over multi-day runs, and no scientific result -- the contribution is robotics. Three "
      "replicate groups in one 15-hour run on a single plate is a capability demonstration, "
      "not a validated assay"
    ),
    scope=Scope(
      summary="one 15-hour run on one 96-well plate of yeast, with human-initiated splitting",
      material="Saccharomyces cerevisiae culture in a 96-well plate",
      duration_verbatim="a fully autonomous 15-hour yeast culture experiment",
      continuous_hours=15.0,
      replicated=False,
      sustained=False,
      human_in_loop=(
        "cell seeding was performed manually before the run, and the subculturing split was "
        "manually initiated as a safety precaution"
      ),
    ),
    unverified=(
      "every number here was checked against arXiv v2 rather than the version of record; "
      "sciencedirect.com and cell.com both returned HTTP 403, and the journal retitled the "
      "paper, so the manuscript was revised during review and figures could have shifted",
      "the published abstract is not exposed by Crossref or Semantic Scholar, so the 15-hour, "
      "96-well and 99.0 percent figures were not re-confirmed in the version of record",
    ),
  ),
  Evidence(
    key="jump",
    citation=(
      "Chandrasekaran, S. N. et al. (2024). 'Three million images and morphological profiles "
      "of cells treated with matched chemical and genetic perturbations.' Nature Methods, "
      "21(6), 1114-1121. doi:10.1038/s41592-024-02241-6"
    ),
    url="https://www.nature.com/articles/s41592-024-02241-6",
    domain=Domain.CELL_ASSAY,
    kind=EvidenceKind.BENCHMARK,
    year=2024,
    confidence=Confidence.CONFIRMED,
    shorthand="the CPJUMP1 image-profiling resource",
    demonstrates=(
      "A public resource for evaluating chemical-genetic matching by morphological profiling: "
      "roughly three million images of cells and image-based profiles of seventy five million "
      "single cells, plus well-level aggregated profiles. Compounds, CRISPR knockout guides and "
      "ORF overexpression run side by side across 160 genes and 303 compounds, each perturbed "
      "gene's product being a known target of at least two compounds in the set. Two cell lines "
      "(U2OS, A549), two time points per modality, two guides per gene for all but 15 genes, "
      "one ORF per gene, 51 physical plates yielding 107 plates of images in 384-well format at "
      "a single 5 uM compound concentration"
    ),
    does_not_establish=(
      "It does not establish that chemical-genetic matching works, and citing it as evidence "
      "that morphological profiling successfully links compounds to gene targets inverts the "
      "paper's own conclusion, which is that identifying matches between chemical and genetic "
      "perturbations is a challenging task. The dataset exists so methods that attempt it can "
      "be evaluated. Coverage is narrow at 160 genes and 303 compounds, and about 21 percent of "
      "compounds are annotated against more than one gene family -- the authors flag "
      "polypharmacology as likely to substantially impair matching and note target annotations "
      "may be incomplete. Selection is biased: compounds and genes were curated from a drug "
      "repurposing library and a genetic-perturbation library, so the set holds preclinical and "
      "clinical compounds with stronger binding and higher specificity than random compounds, "
      "and the two-compounds-per-gene criterion over-represents better-studied ones. A single "
      "concentration was used throughout, which the authors call not ideal, so no dose-response "
      "is established. It was generated in a single experiment at a single facility, which the "
      "authors say limits the generalizability of any model trained on it. Two cell lines and "
      "two time points support no claim of generality, and the scope is morphological profiling "
      "only -- no mechanism of action is determined"
    ),
    scope=Scope(
      summary="one imaging experiment at one facility, published as data for evaluating methods",
      material="U2OS and A549 cell lines in 384-well plates",
      duration_verbatim="not reported as a duration",
      continuous_hours=None,
      replicated=False,
      sustained=False,
      human_in_loop="the perturbation set was curated by hand from existing libraries",
    ),
  ),
  Evidence(
    key="ncats",
    citation=(
      "Iversen PW, Beck B, Chen Y-F, Dere W, Devanarayan V, Eastwood BJ, Farmen MW, Iturria SJ, "
      "Montrose C, Moore RA, Weidner JR, Sittampalam GS. 'HTS Assay Validation.' In: Assay "
      "Guidance Manual. Bethesda (MD): Eli Lilly & Company and the National Center for "
      "Advancing Translational Sciences; 2012 May 1, last revised 2012 Oct 1. PMID 22553862; "
      "Bookshelf ID NBK83783"
    ),
    url="https://www.ncbi.nlm.nih.gov/books/NBK83783/",
    domain=Domain.CELL_ASSAY,
    kind=EvidenceKind.GUIDANCE,
    year=2012,
    confidence=Confidence.CONFIRMED,
    shorthand="the HTS assay-readiness guidance",
    demonstrates=(
      "Recommended practice for deciding an assay is ready to enter production screening. The "
      "acceptance criterion is signal window >= 2 OR Z' >= 0.4 on all plates. Plate-uniformity "
      "studies run over 3 days at Max/Mid/Min signal levels, 3 plates per day interleaved or 6 "
      "per day in the concentration-response plus uniform-signal format. Replicate-experiment "
      "studies run 20-30 compounds spanning the concentration range in each of two runs. Drift "
      "and edge effects below 20 percent are considered insignificant; the worked example calls "
      "26 percent drift a cause to investigate. The same acceptance block sets CVmax and CVmid "
      "<= 20 percent, normalized SDmid <= 20, MSR < 3, limits of agreement between 0.33 and "
      "3.0, and an outlier rate below 2 percent"
    ),
    does_not_establish=(
      "The authors' own limit: the replicate-experiment study is a diagnostic and decision tool "
      "used to establish that an assay is ready to go into production, and is not intended as a "
      "substitute for post-production monitoring or to provide an estimate of the overall "
      "minimum significant ratio. Beyond that, it establishes that an assay is technically fit "
      "to screen and establishes nothing about whether a hit it finds is biologically real or "
      "reproducible in another system. It is not a regulatory validation standard -- an "
      "industry and NIH best-practice manual, not GLP, GMP, CLIA or FDA guidance, conferring no "
      "compliance, and not covering clinical or diagnostic assay validation. The 0.4 threshold "
      "is this manual's recommendation for this context and is not a universal cross-domain "
      "quality bar; it should not be conflated with the more widely cited convention of Z' > "
      "0.5 for an excellent assay. The manual leaves room for deviation rather than presenting "
      "its numbers as immutable, directing that alternatives be discussed with a statistician. "
      "Its worked designs are illustrated on 96-well plates and it does not validate these "
      "criteria for every plate density or detection technology"
    ),
    scope=Scope(
      summary="pre-production readiness criteria for biochemical and cell-based screening assays",
      material="biochemical and cell-based screening assays, illustrated on 96-well plates",
      duration_verbatim="plate-uniformity studies run over 3 days",
      continuous_hours=None,
      replicated=False,
      sustained=False,
      human_in_loop="the manual repeatedly directs borderline cases to a statistician",
    ),
    unverified=(
      "no DOI exists for this chapter; Assay Guidance Manual chapters are not assigned one, "
      "and any citation supplying a DOI for it should be treated as suspect",
      "the editor list in effect at the 2012 revision, which is therefore omitted from the "
      "citation rather than asserted",
    ),
  ),
  Evidence(
    key="smartkage",
    citation=(
      "Ho H, Kejzar N, Sasaguri H, Saito T, Saido TC, De Strooper B, Bauza M, Krupic J. 'A "
      "fully automated home cage for long-term continuous phenotyping of mouse cognition and "
      "behavior.' Cell Reports Methods, 2023;3(7):100532. doi:10.1016/j.crmeth.2023.100532"
    ),
    url="https://doi.org/10.1016/j.crmeth.2023.100532",
    domain=Domain.IN_VIVO,
    kind=EvidenceKind.EMPIRICAL_DEMONSTRATION,
    year=2023,
    confidence=Confidence.PARTIAL,
    shorthand="a single-mouse home-cage phenotyping study",
    demonstrates=(
      "Automated cognitive testing in the home cage -- T-maze alternation, novel object "
      "recognition and object-in-place recognition -- combined with monitoring of locomotion, "
      "drinking and quiescence patterns over long periods, with mice learning the tasks rapidly "
      "and all testing carried out with no food or water restrictions. Lesion arm: hippocampal "
      "n=5, medial entorhinal cortex n=4, control n=9 plus ten additional unlesioned C57BL/6J "
      "mice, roughly 1 month in cage before lesioning and 2 months after. Classification "
      "accuracy 100 percent (5/5) for hippocampal lesions and 25 percent (1/4) for medial "
      "entorhinal lesions. Alzheimer arm: 5 AppNL-G-F knock-in and 3 age-matched controls "
      "tested for about 4.5 months, genotype predicted at 80 percent (4/5) against 60 percent "
      "(3/5) for standard T-maze, NOR and OPR"
    ),
    does_not_establish=(
      "Author-stated limitations. The study is underpowered: the number of mice per group is "
      "limited except for the control group, larger groups are conceded to be needed for the "
      "entorhinal and Alzheimer arms, and all experiments came from a single animal facility "
      "with no multi-site replication. The entorhinal result is a near-failure rather than a "
      "success -- 25 percent (1/4) correctly classified, the rest misclassified as controls -- "
      "so citing the system as discriminating hippocampal, entorhinal and sham lesions "
      "overclaims: it separates hippocampal lesions essentially perfectly and entorhinal "
      "lesions barely at all. It is not reproducible end to end, because the neural-network "
      "tracking training data is proprietary and cannot be released, so users must build their "
      "own. Recognition tasks were run only at inter-trial intervals up to a few minutes and "
      "the authors state longer intervals must be explored to reach the impairments predicted "
      "from standard tests, so no consolidated-memory claim is established. The cage tests one "
      "isolated mouse at a time, which the authors themselves call suboptimal for stress and "
      "low throughput, so it establishes nothing about group-housed or social phenotyping. The "
      "Alzheimer result is genotype prediction from behavioral clustering in one knock-in model "
      "and does not establish diagnostic utility, generalization to other models, or detection "
      "of onset timing"
    ),
    scope=Scope(
      summary="one isolated mouse per cage, one facility, small groups",
      material="C57BL/6J and AppNL-G-F knock-in mice, singly housed",
      duration_verbatim="about 4.5 months of continuous testing in the Alzheimer arm",
      continuous_hours=None,
      replicated=False,
      sustained=False,
      human_in_loop=(
        "lesioning and surgery are bench procedures, and users must build their own tracking "
        "training set because the authors' cannot be released"
      ),
    ),
    unverified=(
      "the composition of the 27/27 control cluster cannot be reconciled to a mouse count; "
      "named control groups total 19 unlesioned mice, so '27 control mice' is not stated",
      "the entorhinal breakdown is internally inconsistent -- 25 percent (1/4) implies three "
      "misclassified but the text says two remaining mice were misclassified as controls -- so "
      "only the headline 1/4 is stated",
      "whether 'continuously tested for ~4.5 months' means uninterrupted; one retrieval "
      "reported two testing periods separated by 8 months",
      "the total number of animals across the study, which is not stated in any single "
      "confirmable sentence, so no aggregate N is published here",
      "the paper's own system name is 'smart-Kage', and full text at cell.com and bioRxiv both "
      "returned HTTP 403, so verification rests on the PMC author manuscript",
    ),
  ),
  Evidence(
    key="homecage_multi",
    citation=(
      "Eswaraka, J., Gommet, C., Diomaiuta, D., Rigamonti, M., Rosati, G., Gaburro, S., Zwick, "
      "M., Begoud, L., Warot, X. & Doenlen, R. 'Enhanced health evaluation in mice using "
      "continuous home-cage monitoring and machine learning: a multicentric study.' Lab Animal "
      "55, 275-281 (2026). doi:10.1038/s41684-026-01745-2"
    ),
    url="https://www.nature.com/articles/s41684-026-01745-2",
    domain=Domain.IN_VIVO,
    kind=EvidenceKind.EMPIRICAL_DEMONSTRATION,
    year=2026,
    confidence=Confidence.CONFIRMED,
    shorthand="a retrospective analysis of 1,367 cages",
    demonstrates=(
      "Retrospective analysis of locomotion data from three institutions using the same "
      "capacitance-based under-cage sensor platform, with machine-learning models generating "
      "digital welfare alerts. A total of 1,367 cages across three sites over distinct study "
      "periods -- approximately 300 days each at two sites and over 1,000 days at the third -- "
      "yielding 90,540, 51,094 and 15,367 unique cage evaluations, 157,001 in total. The "
      "algorithm identified animals in distress 3 to 6 days before verifiable clinical signs or "
      "death were noticed, with accuracy of 66-80 percent at day -3 and 80-91 percent at day "
      "-6, against the institutions' own clinical records as comparator"
    ),
    does_not_establish=(
      "It does not establish that acting on the alerts improves welfare or outcomes. It is "
      "retrospective -- locomotion anomalies preceded already-recorded clinical events -- with "
      "no prospective or interventional validation that earlier intervention reduced suffering "
      "or mortality; the benefits are framed as what the findings suggest, not demonstrate. "
      "Author-stated limits: the algorithm missed 9-20 percent of verified clinical cases; more "
      "robust datasets are needed to increase accuracy; alerts are not delivered in real time, "
      "as welfare alerts are not reported to caretakers until the morning; the sample size of "
      "clinical cases per category is too small to draw conclusions on specific patterns; "
      "cross-site comparison is unreliable because sites recorded clinical cases in different "
      "categories; the technology cannot track individual animal locomotor activity in "
      "group-housed cages and therefore likely lacks the sensitivity to detect every "
      "spontaneous death; and it measures only locomotor activity, while not all clinical "
      "conditions affect locomotion. Scope is mice only, one proprietary vendor platform, and "
      "cage-level rather than animal-level resolution. The accuracy figures are inseparable "
      "from a tolerated false-positive rate -- the headline range corresponds to a model tuned "
      "to a 15 percent maximum false-positive threshold -- so quoting accuracy without the "
      "false-positive budget overclaims. Four co-authors are affiliated with the company that "
      "develops and sells the platform being evaluated"
    ),
    scope=Scope(
      summary="retrospective, cage-level, one vendor platform, no interventional arm",
      material="group-housed mice in ventilated cages",
      duration_verbatim="approximately 300 days at two sites and over 1,000 days at the third",
      continuous_hours=None,
      replicated=True,
      sustained=False,
      human_in_loop=(
        "the comparator is clinical records kept by staff, and alerts are not delivered to "
        "caretakers until the morning"
      ),
    ),
    unverified=(
      "per-institution clinical case counts of 229, 42 and 65, extracted from full text but "
      "not re-confirmable as a verbatim quote",
      "per-category detection rates including found-dead at 93/85/100 percent, hunched posture, "
      "eye issues and weight loss at 100 percent, injuries 73 percent, fighting 62 percent and "
      "skin issues 57 percent; the paper says these subgroups are too small to support "
      "conclusions, so none are stated",
      "day-0 accuracy of roughly 17.9-50.8 percent and the 5/15/30 percent false-positive "
      "thresholds separating the three models",
      "the exact number of individual mice, which the paper does not appear to state",
      "an 'over 50 percent' operational-efficiency figure in press coverage that could not be "
      "traced to any result in the paper",
    ),
  ),
  Evidence(
    key="arrive",
    citation=(
      "Percie du Sert, N. et al. 'The ARRIVE guidelines 2.0: Updated guidelines for reporting "
      "animal research.' PLOS Biology 18(7): e3000410 (2020). doi:10.1371/journal.pbio.3000410"
    ),
    url="https://doi.org/10.1371/journal.pbio.3000410",
    domain=Domain.IN_VIVO,
    kind=EvidenceKind.GUIDANCE,
    year=2020,
    confidence=Confidence.CONFIRMED,
    shorthand="the ARRIVE 2.0 reporting checklist",
    demonstrates=(
      "A reporting framework for in vivo experiments, structured as a 21-item checklist split "
      "by a Delphi prioritization exercise into the ARRIVE Essential 10 -- study design (1), "
      "sample size (2), inclusion and exclusion criteria (3), randomization (4), "
      "blinding/masking (5) and outcome measures (6) among them -- and an 11-item Recommended "
      "Set describing research context, which is where housing and husbandry (15) and animal "
      "care and monitoring (16) sit. Item 14 asks authors to name the ethical review committee "
      "that approved the study and any licence or protocol numbers, or to justify the absence "
      "of approval"
    ),
    does_not_establish=(
      "It governs what is reported in a manuscript, not how research is designed, conducted, "
      "approved, or whether it is acceptable. It is not ethical or welfare authorization of any "
      "kind: not an ethics review, not an institutional or regulatory licence, not a 3Rs "
      "assessment, and adherence confers no approval to perform any procedure -- item 14 only "
      "asks authors to name the committee that already approved the work. It does not establish "
      "that a study is methodologically sound: it is a reporting guideline, not a risk-of-bias "
      "or quality-assessment instrument, so full compliance means a study is transparently "
      "described, not that it is unbiased, adequately powered or valid; formal appraisal "
      "requires separate tools. It prescribes no experimental design, no husbandry standard, no "
      "humane endpoint and no monitoring frequency. It does not establish its own "
      "effectiveness: it is a consensus-derived checklist with no evidence presented that "
      "adopting it improves reporting quality, reproducibility or welfare outcomes. It carries "
      "no enforcement mechanism -- adoption is voluntary and mediated by journals. And because "
      "husbandry and monitoring sit in the Recommended Set, the ARRIVE minimum does not itself "
      "compel reporting them"
    ),
    scope=Scope(
      summary="what a manuscript must disclose about an animal experiment already performed",
      material="reported in vivo experiments, any species",
      duration_verbatim="not applicable",
      continuous_hours=None,
      replicated=False,
      sustained=False,
      human_in_loop="the entire instrument is a checklist completed by authors and journals",
    ),
    unverified=(
      "that the authors state in so many words that ARRIVE is not welfare approval or not a "
      "risk-of-bias tool; both readings follow directly from item 14 and the reporting-only "
      "framing, but no verbatim disclaimer sentence was located, so this is a characterization "
      "of the guideline's function and not an author-stated limitation",
      "Delphi process specifics -- round count and participant numbers or nationalities -- "
      "which are therefore not stated",
    ),
  ),
  Evidence(
    key="alabos",
    citation=(
      "Fei, Y.; Rendy, B.; Kumar, R.; Dartsi, O.; Sahasrabuddhe, H. P.; McDermott, M. J.; Wang, "
      "Z.; Szymanski, N. J.; Walters, L. N.; Milsted, D.; Zeng, Y.; Jain, A.; Ceder, G. "
      "'AlabOS: a Python-based reconfigurable workflow management framework for autonomous "
      "laboratories.' Digital Discovery, 2024, 3(11), 2275-2288. doi:10.1039/D4DD00129J"
    ),
    url="https://doi.org/10.1039/D4DD00129J",
    domain=Domain.ORCHESTRATION,
    kind=EvidenceKind.RESOURCE,
    year=2024,
    confidence=Confidence.CONFIRMED,
    shorthand="one prototype lab's workflow manager, ~3,500 samples over about 1.5 years",
    demonstrates=(
      "Orchestration middleware for an autonomous laboratory: a graph-based workflow model with "
      "tasks as nodes and dependencies as edges; a central resource manager that tracks device "
      "status and allocates resources per task so concurrent tasks cannot conflict, with task "
      "actors required to request occupancy of devices and sample positions before acting; "
      "sample-position tracking where a position holds one sample at a time, positions update "
      "as robots or humans move material, position is set to null on leaving the lab and full "
      "history is preserved; and a user-request module that asks for explicit human "
      "intervention through dashboard, chat bot or email, cited for robot-arm error recovery "
      "and consumable replacement. Around 3,500 samples were processed over about 1.5 years, "
      "with a peak daily throughput of 149 samples. Resource allocation is first-come-first-"
      "serve with task priority considered and no estimate of task duration"
    ),
    does_not_establish=(
      "The ~3,500 figure is a deployment usage statistic, not a scientific-success metric: it "
      "counts samples the software drove through synthesis and characterization, and does not "
      "mean 3,500 successful syntheses, novel materials or validated discoveries. Validation is "
      "single-lab and single-domain -- one prototype laboratory doing inorganic solid-state "
      "powder synthesis, with no multi-site deployment, no cross-domain evidence and no "
      "demonstration that the framework generalizes beyond the lab that built it. There is no "
      "controlled comparison or benchmark against other workflow managers on throughput, "
      "reliability or developer effort, so no claim of superiority is supported. It does no "
      "experiment design, active learning or discovery decision-making; the authors explicitly "
      "delegate that to external planning software. It is the layer beneath the science. "
      "Scheduling is deliberately simple and self-declared as non-optimal, with the authors "
      "stating that more sophisticated reservation techniques could be integrated to further "
      "optimize throughput -- that is future work, not a result. And autonomy here is not "
      "unattended operation: the human-intervention machinery is load-bearing, error recovery "
      "depends on pre-implemented routines, and the authors concede that failures from worn "
      "hardware or newly emerged software exceptions not caught in the soak test still require "
      "operators"
    ),
    scope=Scope(
      summary="one prototype laboratory, one synthesis domain, human-in-the-loop error recovery",
      material="inorganic solid-state powder synthesis samples",
      duration_verbatim="around 3,500 samples synthesized over 1.5 years",
      continuous_hours=None,
      replicated=False,
      sustained=False,
      human_in_loop=(
        "a dedicated module requests human intervention, and unanticipated hardware or software "
        "failures still require operators"
      ),
    ),
  ),
  Evidence(
    key="pylabrobot",
    citation=(
      "Wierenga, R. P., Golas, S. M., Ho, W., Coley, C. W., and Esvelt, K. M. (2023). "
      "'PyLabRobot: An open-source, hardware-agnostic interface for liquid-handling robots and "
      "accessories.' Device 1(4), 100111. doi:10.1016/j.device.2023.100111"
    ),
    url="https://doi.org/10.1016/j.device.2023.100111",
    domain=Domain.ABSTRACTION,
    kind=EvidenceKind.RESOURCE,
    year=2023,
    confidence=Confidence.PARTIAL,
    shorthand="a hardware-agnostic control interface over three robot families",
    demonstrates=(
      "An open-source, cross-platform Python interface capable of programming diverse "
      "liquid-handling robots: a single front-end layer over hardware-specific execution-layer "
      "backends, with a universal set of commands and representations for deck layout and "
      "labware. Hardware agnosticity is demonstrated rather than asserted -- labware "
      "definitions from three vendors were translated into the hardware-agnostic model, and "
      "liquid handler resources were used on an Opentrons robot and vice versa. Three robot families "
      "at publication -- liquid handler/STARLet, Tecan Freedom EVO, Opentrons OT-2 -- plus BMG "
      "plate readers as accessories. Operating-system coverage is asymmetric: the STAR backend "
      "was verified on Windows, macOS and Raspberry Pi OS, the EVO backend only on Windows and "
      "macOS. A browser-based simulator ships with the package"
    ),
    does_not_establish=(
      "No quantitative liquid-handling performance validation. The paper presents zero accuracy "
      "or precision data, no gravimetric validation, no coefficients of variation and no "
      "throughput benchmarks, and never compares PyLabRobot-driven pipetting against vendor "
      "software -- so it does not establish that protocols run through it match vendor-native "
      "accuracy. Testing stops at command generation rather than physical outcome: unit tests "
      "ensure that user input produces consistent machine-level commands and, where possible, "
      "that they are transmitted correctly, which is correctness at the firmware-string layer, "
      "not at the liquid-in-the-well layer. The simulator does not replace hardware, by the "
      "authors' own statement that some facets of development will require physical access to a "
      "robot. Backend parity is not established -- STAR and EVO use direct firmware command "
      "strings over USB while Opentrons goes through an HTTP API and must mirror a second deck "
      "model, so hardware-agnostic does not mean equivalent capability on every backend. "
      "Coverage is three robot families plus plate readers, not all liquid handlers. There is "
      "no claim of scheduling, protocol optimization, error recovery or closed-loop autonomy, "
      "and no user study, adoption metric or cross-lab reproducibility study"
    ),
    scope=Scope(
      summary="a control abstraction, validated at the command layer and not at the bench",
      material="none; the artifact is software",
      duration_verbatim="not applicable",
      continuous_hours=None,
      replicated=False,
      sustained=False,
      human_in_loop="a developer writes the protocol and, for a new robot, the backend",
    ),
    unverified=(
      "that simulation was demonstrated across multiple liquid-handler families. The paper "
      "makes an architectural assertion -- the simulator works with any robot for which a deck "
      "model exists -- and immediately qualifies it: a developer must still enforce "
      "machine-specific constraints such as pipetting-channel configuration. No run across all "
      "three families is reported, so the safe wording is a simulator designed to work with any "
      "robot for which a deck model exists",
      "any unit-test count or code-coverage percentage; the paper reports none, so any such "
      "figure attributed to it would be fabricated",
      "any pipetting accuracy, precision, throughput or timing number; the paper reports none",
      "verbatim body text was checked against the bioRxiv preprint on PMC because the version "
      "of record is paywalled, so preprint-to-record wording changes could not be ruled out",
    ),
  ),
  Evidence(
    key="iso23783",
    citation=(
      "ISO 23783-1:2022, Automated liquid handling systems -- Part 1: Vocabulary and general "
      "requirements (first edition, 2022-08; ISO/TC 48; 19 pp.); and ISO 23783-3:2022, "
      "Automated liquid handling systems -- Part 3: Determination, specification and reporting "
      "of volumetric performance (2022-08; ISO/TC 48; 21 pp.)"
    ),
    url="https://www.iso.org/standard/76952.html",
    domain=Domain.ABSTRACTION,
    kind=EvidenceKind.STANDARD,
    year=2022,
    confidence=Confidence.CONFIRMED,
    shorthand="the automated-liquid-handling volumetric standard",
    demonstrates=(
      "Part 1 defines terms relating to automated liquid handling systems and specifies general "
      "requirements for their use, describing system types, use requirements, settings, "
      "adjustments and environmental requirements. Part 3 covers collecting and examining "
      "volumetric performance data, indexing and tracking it, descriptive statistics for "
      "evaluating it, and reporting requirements. Both are the work of ISO/TC 48, and the "
      "series cancels and replaces IWA 15:2015"
    ),
    does_not_establish=(
      "The most load-bearing limit is what these two parts leave out. Part 2 holds the "
      "measurement procedures for determining volumetric performance, and Part 1 says so "
      "explicitly in a note to its own scope. Citing Parts 1 and 3 to support any claim about "
      "HOW volumetric performance is measured does not work -- Part 3 governs only what is done "
      "with data after it is collected. Applicability is narrow and stated in both scopes: "
      "complete, installed liquid handling devices including tips and other essential parts, "
      "performing liquid handling tasks without human intervention into labware. It therefore "
      "does not cover manual pipettes, incomplete or uninstalled devices, or operations "
      "requiring human intervention. Neither part establishes acceptance criteria, pass/fail "
      "tolerance limits or accuracy grades for any application or assay. The series certifies "
      "no instrument, vendor or protocol. ISO standards are voluntary, not regulatory "
      "requirements. Part 1 adds that the tests it establishes should be carried out by trained "
      "personnel. And the series addresses volumetric performance only -- trueness and "
      "precision of delivered volume -- not biological assay validity, contamination or "
      "carryover, sterility, throughput, or the scientific reproducibility of results"
    ),
    scope=Scope(
      summary="volumetric trueness and precision of installed automated liquid handlers",
      material="none; the artifact is a specification",
      duration_verbatim="not applicable",
      continuous_hours=None,
      replicated=False,
      sustained=False,
      human_in_loop="the standard directs that its tests be carried out by trained personnel",
    ),
    unverified=(
      "the normative content of Part 3, which is paywalled and had no retrievable free "
      "preview; verification rests on its official title as quoted inside the published Part 1, "
      "its catalogue metadata and its published abstract, so no specific requirement, formula "
      "or tolerance from Part 3 is stated here",
      "the edition statement for Part 3, inferred from the series structure rather than read "
      "off its cover page",
      "the substantive text of Part 1 clauses 6 and 7 on testing, calibration and specification "
      "of volumetric performance, which the free preview does not reach",
    ),
  ),
  Evidence(
    key="provo",
    citation=(
      "Lebo, T., Sahoo, S., McGuinness, D. (eds.). 'PROV-O: The PROV Ontology.' W3C "
      "Recommendation, 30 April 2013. World Wide Web Consortium. No DOI; the dated W3C URI is "
      "the canonical identifier"
    ),
    url="https://www.w3.org/TR/2013/REC-prov-o-20130430/",
    domain=Domain.PROVENANCE,
    kind=EvidenceKind.STANDARD,
    year=2013,
    confidence=Confidence.CONFIRMED,
    shorthand="the PROV-O provenance ontology",
    demonstrates=(
      "An OWL2 ontology providing classes, properties and restrictions to represent and "
      "interchange provenance information generated in different systems and under different "
      "contexts. The three starting-point classes are prov:Entity, prov:Activity and prov:Agent; "
      "generation, use, derivation and association each appear twice over, as an object property "
      "and as a qualified class -- prov:wasGeneratedBy / prov:Generation, prov:used / "
      "prov:Usage, prov:wasDerivedFrom / prov:Derivation, prov:wasAssociatedWith / "
      "prov:Association. The normative OWL file declares 30 classes, 44 object properties, 6 "
      "datatype properties and 17 annotation properties; the class count matches the document's "
      "own split of 3 starting-point, 7 expanded and 20 qualified terms"
    ),
    does_not_establish=(
      "PROV-O does not establish validity and enforces no constraints. The uniqueness, "
      "event-ordering, impossibility and type constraints that define a valid PROV instance "
      "live in the separate PROV-CONSTRAINTS Recommendation; PROV-O supports OWL2 entailments "
      "and does not check validity, so citing it as authority for provenance validation or "
      "consistency checking is an overclaim. It is also a category error to call it the "
      "provenance model: PROV-O, PROV-XML and PROV-N are serializations of a conceptual model "
      "that lives in PROV-DM. Exactly five of its axioms fall outside the OWL 2 RL profile, and "
      "the spec notes it cannot assume everybody is using OWL reasoning, so it does not "
      "guarantee reasoner-derived completeness. Bundles get no RDF encoding here. The inverse of "
      "prov:wasDerivedFrom is not defined; only recommended names are supplied, "
      "non-normatively. Location modeling is out of scope. Responsibility is not apportioned -- "
      "agents are responsible in some way without the ontology saying who bears it or to what "
      "degree. And provenance is not trust, quality or accuracy: a PROV record is an input to "
      "such an assessment, not a determination of it, validity means logical consistency rather "
      "than factual accuracy, and a fully valid instance can record a false history"
    ),
    scope=Scope(
      summary="an RDF/OWL vocabulary for exchanging provenance, with validity left elsewhere",
      material="none; the artifact is a vocabulary",
      duration_verbatim="not applicable",
      continuous_hours=None,
      replicated=False,
      sustained=False,
      human_in_loop="nothing collects or generates the provenance; that is out of scope",
    ),
    unverified=(
      "the exact starting-point property count, variously presented as 9, 10 or 11 depending on "
      "whether prov:type and prov:label are folded in, and the expanded/qualified property "
      "split, which does not cleanly reconcile with the parsed totals; no figure is stated",
    ),
  ),
  Evidence(
    key="fda_di",
    citation=(
      "U.S. Food and Drug Administration, 'Data Integrity and Compliance With Drug CGMP: "
      "Questions and Answers -- Guidance for Industry,' December 2018 (Final, Level 1). Docket "
      "No. FDA-2018-D-3984. Issued by CDER in cooperation with CBER, CVM and ORA. No DOI"
    ),
    url=(
      "https://www.fda.gov/regulatory-information/search-fda-guidance-documents/"
      "data-integrity-and-compliance-drug-cgmp-questions-and-answers"
    ),
    domain=Domain.PROVENANCE,
    kind=EvidenceKind.GUIDANCE,
    year=2018,
    confidence=Confidence.CONFIRMED,
    shorthand="the CGMP data-integrity questions and answers",
    demonstrates=(
      "Eighteen numbered questions across 17 pages setting out the agency's expectations for "
      "data integrity under 21 CFR parts 210, 211 and 212. Data are expected to be reliable and "
      "accurate, and data integrity is defined as attributable, legible, contemporaneously "
      "recorded, original or a true copy, and accurate. Metadata is the contextual information "
      "required to understand data and must be retained so a CGMP activity can be reconstructed. "
      "An audit trail is a secure, computer-generated, time-stamped electronic record allowing "
      "reconstruction of the creation, modification or deletion of an electronic record. The "
      "system administrator role, including rights to alter files and settings, should be "
      "assigned to personnel independent from those responsible for record content. Processes "
      "should be designed so that data cannot be modified without a record of the modification. "
      "A backup is a true copy maintained securely through the retention period and must be "
      "exact, complete and secure from alteration -- temporary copies do not satisfy this. "
      "Audit-trail review falls to the personnel responsible for CGMP record review"
    ),
    does_not_establish=(
      "The guidance is explicitly nonbinding and establishes no requirement of its own. Its own "
      "words: it represents the agency's current thinking, does not establish any rights for "
      "any person, is not binding on FDA or the public, and an alternative approach may be used "
      "if it satisfies the applicable statutes and regulations. Every page is headed 'Contains "
      "Nonbinding Recommendations'. The binding force lives in 21 CFR 210, 211 and 212, so any "
      "citation implying this document requires or mandates something overclaims. Product scope "
      "is drugs including biologics, specifically finished pharmaceuticals and PET drugs: it "
      "does not cover medical devices or the quality system regulation, does not cover good "
      "clinical practice trial data or nonclinical laboratory data, and does not directly cover "
      "active pharmaceutical ingredients. It does not establish or reinterpret 21 CFR part 11 "
      "electronic-records requirements, and expressly notes part 11 remains subject to the "
      "agency's reexamination. It deliberately declines to set fixed technical standards -- on "
      "audit-trail review frequency it prescribes no interval and defers to the firm's own "
      "knowledge of its processes and risk assessment -- so it establishes no mandated review "
      "frequency, retention technology or access-control implementation"
    ),
    scope=Scope(
      summary="nonbinding expectations for electronic records under drug CGMP",
      material="none; the artifact is agency guidance",
      duration_verbatim="not applicable",
      continuous_hours=None,
      replicated=False,
      sustained=False,
      human_in_loop="the quality unit reviews and approves production and control records",
    ),
  ),
  Evidence(
    key="labsafety",
    citation=(
      "Zhou, Y., Yang, J., Huang, Y., Guo, K., Emory, Z., Ghosh, B., Bedar, A., Shekar, S., "
      "Liang, Z., Chen, P.-Y., Gao, T., Geyer, W., Moniz, N., Chawla, N. V., & Zhang, X. "
      "(2026). 'Benchmarking large language models on safety risks in scientific "
      "laboratories.' Nature Machine Intelligence, 8, 20-31. doi:10.1038/s42256-025-01152-1"
    ),
    url="https://doi.org/10.1038/s42256-025-01152-1",
    domain=Domain.SAFETY,
    kind=EvidenceKind.BENCHMARK,
    year=2026,
    confidence=Confidence.PARTIAL,
    shorthand="a text benchmark of 19 models on constructed lab-safety questions",
    demonstrates=(
      "Nineteen models evaluated -- 8 proprietary and 7 open-weight language models plus 4 "
      "open-weight vision-language models -- against 765 multiple-choice questions (632 "
      "text-only, 133 with an image), 404 realistic laboratory scenarios and 3,128 open-ended "
      "tasks. The authors' headline finding is that no evaluated model surpasses 70 percent "
      "accuracy on the Hazards Identification Test. The contrast that makes it a finding: on "
      "the multiple-choice portion GPT-4o reached 86.55 percent text-only with zero-shot "
      "chain-of-thought and DeepSeek-R1 reached 84.49 percent. The structural result is the gap "
      "-- proprietary models do well on structured questions and show no clear advantage in "
      "open-ended reasoning"
    ),
    does_not_establish=(
      "The 70 percent figure is sub-task specific and is the biggest trap in this citation. It "
      "refers to the open-ended, scenario-based Hazards Identification Test only and is not "
      "overall model performance; writing 'no model exceeded 70 percent accuracy' without "
      "naming the sub-task invites the reader to conclude models score under 70 percent on lab "
      "safety generally, which the paper does not show. The benchmark measures text-based "
      "knowledge and reasoning on constructed questions and scenarios. It establishes nothing "
      "about real-world laboratory behavior, nothing about physical task execution, nothing "
      "about accident or injury rates, and it does not show that model use has caused any lab "
      "incident. Domain scope is biology, chemistry and physics at Biosafety Levels 1 to 3, with "
      "BSL-4 explicitly excluded, and the questions are aligned to US OSHA protocols, so results "
      "do not transfer automatically to other regulatory regimes. The human baseline is weak by "
      "the authors' own admission -- some participants were junior researchers who may not "
      "represent experienced experts -- so any 'outperforms humans' framing carried over from "
      "the preprint should be dropped. Model coverage is a late-2024 to early-2025 snapshot and "
      "says nothing about current frontier models. Note also that 'LabSafety Bench' is the "
      "benchmark's name and the preprint title, not the title of the published paper; pairing "
      "the preprint title with the Nature DOI is a mismatch, and the preprint's variant figures "
      "-- 520 scenarios, 4,090 open-ended questions, 'none above 75 percent' -- still circulate "
      "and contradict the published ones"
    ),
    scope=Scope(
      summary="constructed questions and scenarios scored offline; no laboratory was involved",
      material="none; the subjects are models, not material",
      duration_verbatim="not applicable",
      continuous_hours=None,
      replicated=False,
      sustained=False,
      human_in_loop="a human baseline was collected, and the authors call it weak",
    ),
    unverified=(
      "the per-model hazard-identification score table and the paper's full limitations "
      "section could not be inspected directly; the 70 percent figure is verified as the "
      "authors' abstract-level assertion and corroborated by press coverage, but the underlying "
      "per-model numbers were not independently checked",
      "the grading methodology for the 3,128 open-ended tasks -- human expert or model-as-judge "
      "-- which could not be confirmed from any source reached. This matters, because the 70 "
      "percent headline rests on however those free-text responses were scored",
      "a reported 5-10 percent gain from fine-tuning, which appears only in secondary press "
      "coverage and is not confirmed against the paper",
    ),
  ),
)


EVIDENCE_BY_KEY: Dict[str, Evidence] = {e.key: e for e in EVIDENCE}


def by_domain(domain: Domain) -> Tuple[Evidence, ...]:
  return tuple(e for e in EVIDENCE if e.domain is domain)


def partially_verified() -> Tuple[Evidence, ...]:
  """Entries where a number this module would otherwise state could not be confirmed."""
  return tuple(e for e in EVIDENCE if not e.verified)


# -- claim against literature ---------------------------------------------------


@dataclass(frozen=True)
class ScopeGap:
  """One cited work measured against one claim.

  `shortfalls` is a list rather than a verdict because the ways a citation falls short are
  not interchangeable. A work in the wrong domain needs a different citation. A work in the
  right domain that ran for fifteen hours needs a longer run. Collapsing both to "not
  supported" throws away the only part of the answer that tells anyone what to do next.
  """

  evidence: Evidence
  covers: bool
  shortfalls: Tuple[str, ...]
  reason: str


@dataclass(frozen=True)
class Support:
  """What the published field actually says about one claim.

  `speaks_to` is restricted to the claim's own domain. That is the harsh cut and it is the
  one that does the work: the citations that get misused most are not weak, they are strong
  evidence about a different kind of matter.
  """

  claim_domain: Domain
  scope: Scope
  speaks_to: Tuple[ScopeGap, ...]
  out_of_domain: Tuple[ScopeGap, ...]

  @property
  def supported(self) -> bool:
    """True only if some in-domain work demonstrated everything the claim asserts.

    An empty `speaks_to` is False, not vacuously True. A claim no cited work addresses is
    unsupported in the strongest sense available, and the natural implementation -- all() over
    an empty sequence -- returns True, which would report the least evidenced claims in the
    table as the best supported ones.
    """
    return any(g.covers for g in self.speaks_to)

  def gaps(self) -> Tuple[ScopeGap, ...]:
    return tuple(g for g in self.speaks_to if not g.covers)

  def reason(self) -> str:
    if self.supported:
      covering = ", ".join(g.evidence.key for g in self.speaks_to if g.covers)
      return f"demonstrated within scope by {covering}"
    field = self.claim_domain.value.replace("_", " ")
    if not self.speaks_to:
      return (
        f"no cited work operates in {field} at all; the claim rests on citations from "
        f"{', '.join(sorted({g.evidence.domain.value.replace('_', ' ') for g in self.out_of_domain}))}"
      )
    return "; ".join(g.reason for g in self.gaps())


# How each non-demonstration describes itself, for the one sentence that refuses it. A bare
# enum value reads as a category label rather than an answer, and this report is read by
# people deciding whether to keep citing something.
_KIND_PHRASE: Dict[EvidenceKind, str] = {
  EvidenceKind.BENCHMARK: "a benchmark for evaluating models or methods",
  EvidenceKind.GUIDANCE: "recommended practice",
  EvidenceKind.STANDARD: "a normative specification",
  EvidenceKind.RESOURCE: "a software or data artifact",
}


def _shortfalls(evidence: Evidence, scope: Scope) -> Tuple[str, ...]:
  """Every specific way one work falls short of one claimed scope.

  Kind is checked first and returns alone, because the remaining comparisons are only
  meaningful against something that ran. Measuring a duration gap, a replication gap and a
  human-in-the-loop gap against a reporting checklist would produce four grammatical
  sentences and one category error, and burying the real objection under three fabricated
  ones is how a report earns the right to be skimmed.
  """
  out: List[str] = []
  short = evidence.shorthand
  demo = evidence.scope

  if not evidence.kind.demonstrates_operation:
    return (
      f"{short} is {_KIND_PHRASE[evidence.kind]}, not a demonstration; it does not show a lab "
      "operating, so it cannot evidence an operating claim",
    )

  if scope.asserts_nothing_comparable:
    return (
      "the claim names no material, duration, replication or attendance, so there is nothing "
      f"to compare {short} against. Returning support here would mean an unwritten claim is "
      "the easiest kind to support, which is backwards. Write the scope out and ask again",
    )

  # Material is compared before anything else that ran, because a duration gap on the wrong
  # organism is a rounding error next to the organism. Comparison is exact-match and
  # deliberately crude: "primary human hepatocytes" and "immortalized human cell line" are
  # not machine-comparable, and a fuzzy match here would silently decide a transfer question
  # that is the whole content of the claim. Unequal strings therefore refuse rather than
  # guess, and say so.
  if scope.material.strip():
    claimed = scope.material.strip().lower()
    demonstrated = demo.material.strip().lower()
    if not demonstrated:
      out.append(
        f"{short} states no material, so nothing in it compares against the claim's "
        f"{scope.material}"
      )
    elif claimed != demonstrated:
      out.append(
        f"the claim is about {scope.material}; {short} ran on {demo.material}. Whether a "
        "result on one transfers to the other is exactly what a demonstration would have to "
        "show, and nothing in this entry does"
      )

  if scope.sustained and not demo.sustained:
    out.append(
      f"{short} is a single bounded campaign and does not reach sustained production"
    )

  if scope.continuous_hours is not None:
    if demo.continuous_hours is None:
      out.append(
        f"the claim asks for {scope.continuous_hours:g} h of continuous operation and {short} "
        f"states no duration that converts to a figure ({demo.duration_verbatim})"
      )
    elif demo.continuous_hours < scope.continuous_hours:
      out.append(
        f"{short} ran {demo.continuous_hours:g} h against the {scope.continuous_hours:g} h "
        "the claim asserts"
      )

  if scope.replicated and not demo.replicated:
    out.append(
      f"{short} was not replicated, so its numbers describe that run rather than a capability"
    )

  if scope.unattended and demo.human_in_loop:
    out.append(f"{short} kept a human in the loop: {demo.human_in_loop}")

  return tuple(out)


def support_for(claim_domain: Domain, scope: Scope) -> Support:
  """What the literature supports for a claim in one domain at one operating scope.

  Returns both halves deliberately. `speaks_to` is what an honest citation list would contain.
  `out_of_domain` is everything else, each carrying the reason it does not apply -- because
  the works that get miscited are already known to whoever is making the claim, and a report
  that silently omitted them would read as an oversight rather than as a refusal.
  """
  speaks: List[ScopeGap] = []
  outside: List[ScopeGap] = []

  for e in EVIDENCE:
    if e.domain is claim_domain:
      shortfalls = _shortfalls(e, scope)
      speaks.append(
        ScopeGap(
          evidence=e,
          covers=not shortfalls,
          shortfalls=shortfalls,
          reason="; ".join(shortfalls) if shortfalls else f"{e.shorthand} covers the claimed scope",
        )
      )
    else:
      field = claim_domain.value.replace("_", " ")
      crossing = (
        " -- living material contaminates, loses viability and changes state while it waits, "
        "and none of that has an analogue in the cited domain"
        if claim_domain.living and not e.domain.living
        else ""
      )
      outside.append(
        ScopeGap(
          evidence=e,
          covers=False,
          shortfalls=(),
          reason=(
            f"{e.shorthand} is {e.domain.value.replace('_', ' ')} work; it does not speak to a "
            f"{field} claim{crossing}"
          ),
        )
      )

  return Support(
    claim_domain=claim_domain,
    scope=scope,
    speaks_to=tuple(speaks),
    out_of_domain=tuple(outside),
  )


# -- what nothing here establishes ----------------------------------------------


@dataclass(frozen=True)
class UnsupportedClaim:
  """A claim made routinely that no work in this table establishes.

  `nearest` names the citations usually offered for it. That field is what makes the entry
  useful rather than merely negative: the argument is never "you have no evidence", it is
  "here is the evidence you meant, and here is where it stops". `would_establish_it` keeps the
  entry falsifiable and retirable, in the same spirit as `intelligence.Benchmark.how_to_measure`
  -- an objection with no stated remedy is a position, not a finding.
  """

  name: str
  claim: str
  why_unsupported: str
  nearest: Tuple[str, ...]
  would_establish_it: str


UNSUPPORTED: Tuple[UnsupportedClaim, ...] = (
  UnsupportedClaim(
    name="integrated_autonomy_at_production_rates",
    claim=(
      "an integrated autonomous laboratory runs a real workload end to end, without a human, "
      "at a production rate"
    ),
    why_unsupported=(
      "Every demonstration in this table stops short, and each stops in a different place. "
      "A-Lab is one 17-day campaign on one instrument, on inorganic powders, unreplicated, and "
      "the framework paper from the same group concedes that worn hardware and newly emerged "
      "software exceptions still require operators. Dai et al. ran almost four consecutive days "
      "and the one anomaly that mattered -- a cyclized isomer with the expected molecular mass "
      "-- was caught by human inspection of the NMR and confirmed by off-workflow "
      "single-crystal X-ray diffraction. RoboCulture ran 15 hours on a single plate with "
      "seeding done by hand and the subculturing split manually initiated. Coley et al. require "
      "an expert chemist to author a recipe file for every route. Nothing here demonstrates the "
      "integration, the duration and the absence of a human at the same time"
    ),
    nearest=("a_lab", "dai", "roboculture", "coley", "alabos"),
    would_establish_it=(
      "a replicated multi-week campaign in the claimed domain, on the claimed material, with "
      "the human interventions counted rather than described, and a denominator of attempted "
      "runs so the success rate is a rate"
    ),
  ),
  UnsupportedClaim(
    name="nominal_speed_as_biological_throughput",
    claim=(
      "an instrument's rated or nominal speed is the rate at which a lab produces biological "
      "results"
    ),
    why_unsupported=(
      "No cited work reports a throughput advantage over manual work, and two decline the "
      "framing outright. RoboCulture's authors position the system as operating more like an "
      "autonomous vehicle tailored to individual or small-group use than for high-throughput "
      "screening, and say it neither beats commercial liquid handlers on throughput nor claims "
      "to. Dai et al. claim only that the algorithmic decisions are effectively instantaneous, "
      "which is the decision step and not synthetic throughput. AlabOS's roughly 3,500 samples "
      "over about 1.5 years is a deployment usage statistic, not a count of successes, and its "
      "scheduler is first-come-first-serve with no task-duration modeling, which the authors "
      "call non-optimal and future work. Rated speed is a property of a motion; a biological "
      "result requires the incubation, the gate, and the rerun after the gate fails"
    ),
    nearest=("roboculture", "dai", "alabos"),
    would_establish_it=(
      "measured wall-clock time per completed, QC-passing result over a run long enough to "
      "include failures and reruns, compared against the manual baseline it claims to beat"
    ),
  ),
  UnsupportedClaim(
    name="simulation_as_qualification",
    claim="a protocol that runs correctly in simulation is qualified to run on real material",
    why_unsupported=(
      "PyLabRobot's own authors draw this line: unit tests ensure that user input produces "
      "consistent machine-level commands and that they are transmitted correctly, which is "
      "correctness at the firmware-string layer and not at the liquid-in-the-well layer, and "
      "they state plainly that some facets of development will require physical access to a "
      "robot. The paper reports no accuracy, precision or gravimetric data at all. The ISO "
      "series that does address volumetric performance applies to complete, installed devices "
      "and puts the measurement procedures in a part not cited here, while setting no "
      "acceptance criteria for any assay. The HTS guidance puts assay readiness behind "
      "plate-uniformity studies over 3 days and replicate-experiment studies on the instrument. "
      "A simulator establishes that the commands are the intended commands"
    ),
    nearest=("pylabrobot", "iso23783", "ncats"),
    would_establish_it=(
      "a gravimetric or dye-based volumetric measurement at the working volume with the tips "
      "actually used, followed by the plate-uniformity and replicate-experiment studies the "
      "assay guidance specifies"
    ),
  ),
  UnsupportedClaim(
    name="ai_fluency_as_hazard_competence",
    claim=(
      "a model that answers laboratory questions well is competent to judge laboratory hazards"
    ),
    why_unsupported=(
      "The one benchmark here that asks the question found the opposite, and found it as a gap "
      "rather than a level: no evaluated model surpassed 70 percent accuracy on the Hazards "
      "Identification Test while GPT-4o reached 86.55 percent on the multiple-choice portion. "
      "Structured recall and open-ended hazard reasoning came apart. And even the low number is "
      "the wrong kind of evidence for a bench claim: the benchmark measures text-based "
      "knowledge on constructed questions, establishes nothing about real-world laboratory "
      "behavior or physical task execution, covers Biosafety Levels 1 to 3 with BSL-4 excluded, "
      "and is aligned to one regulatory regime"
    ),
    nearest=("labsafety",),
    would_establish_it=(
      "measured hazard-identification performance on this lab's own materials and procedures, "
      "scored by someone qualified to sign off on them, with the miss rate reported rather than "
      "the accuracy"
    ),
  ),
  UnsupportedClaim(
    name="capital_as_capacity",
    claim="purchased instruments constitute laboratory capacity",
    why_unsupported=(
      "Nothing cited measures capacity as a function of spend, and in every demonstration the "
      "binding constraint was somewhere else. A-Lab's was analysis quality -- the senior author "
      "concedes a human can perform a higher-quality refinement -- and the validity of a blind "
      "target. RoboCulture's was a fiducial-tag calibration its authors call fragile and "
      "time-consuming to maintain, over a perception stack that does not generalize beyond well "
      "plates. AlabOS's was error-recovery routines that have to be implemented in advance. "
      "This repository makes the same point from the other side: six reverse-engineered "
      "instruments are physically present on the bench and 0 of 54 seeded commands are decoded, "
      "so the ledger reaches step 1 of 18 on an unattended run. The instruments were bought. "
      "The capacity was not"
    ),
    nearest=("a_lab", "roboculture", "alabos"),
    would_establish_it=(
      "a completed protocol on the purchased instruments with the decode, calibration, "
      "benchmarking and recovery work counted as part of the cost of the capacity"
    ),
  ),
)


def unsupported_claims() -> Tuple[UnsupportedClaim, ...]:
  """The standing list of things no work in this table establishes.

  Standing, not computed. These are not gaps that a scope comparison discovers; they are the
  five inferences this module was built after watching get made, and they stay in the table
  until a citation retires one. `support_for` answers a question somebody thought to ask, and
  this answers the ones nobody does.
  """
  return UNSUPPORTED


def summary() -> Dict[str, int]:
  """How much of the cited field is demonstration, and how much of it was fully checked."""
  return {
    "evidence": len(EVIDENCE),
    "demonstrations": sum(1 for e in EVIDENCE if e.kind.demonstrates_operation),
    "confirmed": sum(1 for e in EVIDENCE if e.verified),
    "partial": sum(1 for e in EVIDENCE if not e.verified),
    "entries_with_unverified_numbers": sum(1 for e in EVIDENCE if e.unverified),
    "domains_covered": len({e.domain for e in EVIDENCE}),
    "unsupported_claims": len(UNSUPPORTED),
  }


__all__ = [
  "EVIDENCE",
  "EVIDENCE_BY_KEY",
  "UNSUPPORTED",
  "Confidence",
  "Domain",
  "Evidence",
  "EvidenceKind",
  "Scope",
  "ScopeGap",
  "Support",
  "UnsupportedClaim",
  "by_domain",
  "partially_verified",
  "summary",
  "support_for",
  "unsupported_claims",
]
