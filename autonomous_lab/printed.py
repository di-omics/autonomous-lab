"""Whether a printed part may be used for a particular purpose, and every reason it may not.

The argument this package makes is that a lab does not need a vendor to ship AI-native
labware. The instruments are already on the bench, the missing pieces are fixtures, and a
fixture can be printed in an afternoon. That argument is only honest if the printed part is
held to the standard everything else here is held to, because a printed fixture is untested
hardware, made in-house, with no lot number, sitting on a deck inside the working envelope
of a moving arm and sometimes within splash distance of a reagent. It is exactly the kind of
object this package refuses to trust by default.

So this module computes fitness for a use. It is not a print guide. Nothing here tells
anybody what layer height to run, and the numbers it holds are thresholds for deciding, not
settings for making.

Four ideas carry the module.

POROSITY IS A PROPERTY OF THE PROCESS, NOT OF THE PRINT QUALITY. Fused deposition parts
carry an internal void network that survives every setting anybody has tried. It has been
measured by X-ray computed tomography at 4.05 to 6.32 percent BY VOLUME with infill fixed at
100 percent, over raster angles and extrusion widths, and no configuration approached zero.
Over 99 percent of those pores are under 0.2 mm, and they concentrate between the outer
perimeter and the infill -- which is to say the void network is connected to the outside
surface. Fluid gets in. A separate immersion study concluded in as many words that no
manufacturing settings provide adequate sealing against fluid intake, and that a part given
45 minutes of cold acetone vapor was still stained through by dye after 30 minutes of
immersion. Bacteria attach preferentially in the grooves between layers, where biofilm is
thickest. None of this is a calibration problem. A better printer prints a better-looking
porous part. So `Process.cleanable_in_principle` is a claim about the process and it is the
gate most of this module hangs from.

The corollary matters as much as the fact: the fixes people reach for are not fixes. Vapor
smoothing reduces surface roughness by up to 90 percent and leaves the part permeable, which
changes what a person can see and not what a person can clean. Epoxy infiltration is claimed
airtight by vendors of epoxy, has no peer-reviewed cleaning validation behind it, and by
those same vendors' admission cannot reach internal channels. Parylene coating is the one
barrier with a real measurement behind it -- it restored cell viability on a cytotoxic resin
and held for days -- and it detached after five to six autoclave cycles. So
`PostProcess.closes_the_fluid_path` returns False for every member, and that uniform answer
is a measured result rather than a conservative stub.

TG IS THE GATE FOR AN AUTOCLAVE, NOT HDT, AND THAT IS SPECIFICALLY A PRINTED-PART RULE.
Heat deflection temperature measures a standard bar deflecting 0.25 mm under an applied load.
A part in an autoclave usually carries no external load, so the intuitive reading is that
exceeding HDT is safe. For a printed part that reasoning fails, because the part contains
frozen-in extrusion stresses that relax the moment the polymer passes its glass transition:
it moves with zero load applied. The gap is not academic. One carbon-fiber nylon has a
published HDT of 170 to 194 C sitting on top of a glass transition of 70 C, because the
filler carries the load the matrix no longer can. Gate that material on HDT and a 121 C
cycle looks like a wide margin. Gate it on Tg and the part is 51 C past the line. So
`Material.survives` reads Tg and only Tg, `hdt` is carried and never consulted, and a
material with no Tg on record fails the check rather than skipping it.

CERTIFICATION ATTACHES TO A WORKFLOW, NOT TO A BOTTLE. The photopolymer story is the
opposite shape from the fused-deposition one. Photopolymer parts are dense, so porosity is
not the objection; residual chemistry is. Typical formulations contain more than twenty
compounds and manufacturers disclose only the hazard-classified ones. Six splint materials
that all started at 1.0 to 1.47 percent photoinitiator differed by three orders of magnitude
in extractable initiator after cure, from 44.0 to 42,083.5 ng/mL, so leachate load cannot be
read off a formulation. Post-curing helps enormously -- one resin moved from 48.5 percent
cell viability at a short low-temperature cure to 89.5 percent at a long hot one -- and it
cannot help at all with the species that are not polymerizable, which is why a light
stabilizer identified at roughly 50 ug/mL in culture medium destroyed every oocyte it was
put near, after UV post-cure and after plasma treatment. Both resins in that study were
certified biocompatible at the time. That is the reason `ResinQualification` requires the
certified resin, the certified workflow, and a validated post-cure as three separate
conditions: a certification is measured on one printer at one layer height with one wash
time and one cure, and a part made outside that is not the article that was tested.

Read the last point carefully before using this module for anything living. Reproductive and
developmental toxicity is an endpoint the biocompatibility standards do not trigger for a
benchtop fixture, so a resin can hold a full certification and have never been tested against
the thing a lab actually wants to put in it. CULTURE_CONTACT is the strictest level this
module knows and it is still not clearance for gametes or embryos; that qualification is a
mouse embryo assay run on parts from the actual build, and this module does not model it.

UNMEASURED IS UNTRUSTED, AND A DESIGNED DIMENSION IS NOT A MEASURED ONE. This is the same
convention `intelligence.trusted_for` applies to an unbenchmarked operation and `qc.evaluate`
applies to an absent measurement, and it bites hardest on dimensions because a designed
dimension LOOKS like a measurement -- it is a number, with units, in a document. It is a
number about a model. Desktop tolerance is quoted at plus or minus 0.5 percent with a floor
of plus or minus 0.5 mm, scaling with length, so a calibration cube says nothing about a 200
mm nest. Shrinkage is not published on any filament datasheet checked here, and the values
shipped inside slicers disagree with each other by 0.5 percent on the same polymer between
two vendors. Layer quantization forces total height to a multiple of the layer height. The
first layer is squished wider than the model by roughly the 0.2 mm of compensation the
slicer applies by default. All of that is recoverable by measuring the part, and none of it
is recoverable by reading the model. `DimensionState` keeps DESIGNED and MEASURED apart for
that reason, and `unqualified` defaults to listing everything, because a new print has
demonstrated nothing at all.

WHAT THIS MODULE WILL NOT DO. It returns no predicted part lifetime, no autoclave cycle
count, no leachable concentration, and no probability that a part is fine. Every specific
cycle-count claim located for the high-temperature polymers traced back to commercial
aggregator pages rather than to a study or a manufacturer document, and a number of that
shape is exactly the kind that gets quoted into a specification with no author attached.
`NOT_ESTIMATED` names each refusal and what it would take to lift it, in the same form
`durability` uses -- and reuses that module's `Refusal`, because a second dataclass with the
same three fields would be a second definition of one discipline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .durability import Refusal
from .qc import Basis


# -- processes ------------------------------------------------------------------


class Process(str, Enum):
  """How the part was made, which decides whether it can ever be cleaned.

  The split here is not about quality or cost. It is about whether the finished part has an
  internal void network by construction, because that single physical property decides most
  of what follows: whether a fluid path is permissible, whether a cleaning validation could
  in principle be written, and whether a sterilization cycle that the material survives
  means anything about the part being sterile.

  SLS sits in the list without a material behind it, and that is deliberate rather than an
  omission. This repo holds no porosity measurement for powder-bed parts at all, so the
  process cannot earn a fluid path here -- not because it is known to be porous, but because
  nobody in this evidence set measured it. An uncharacterized process and a measured-porous
  one are refused by different grounds, because they cost different things to clear: one
  needs a different part, the other needs a measurement.
  """

  FDM = "fdm"  # fused deposition; measured 4.05-6.32 percent porosity at 100 percent infill
  SLA_DLP = "sla_dlp"  # vat photopolymer; dense parts, and the objection is chemical instead
  SLS = "sls"  # powder bed fusion; no porosity measurement is held here
  MACHINED = "machined"  # cut from moulded or extruded stock, so the stock's datasheet governs

  @property
  def cleanable_in_principle(self) -> bool:
    """Whether parts are non-porous enough that a cleaning validation could be written.

    True does not mean clean. It means the part has no construction-inherent void network,
    so removing a residue from it is a procedure somebody could validate rather than a
    claim about a volume nothing reaches. False for FDM on measured evidence, and false for
    SLS because this repo holds no evidence either way -- absence of a measurement is not
    evidence of density, in exactly the way an absent QC measurement is not a passing gate.
    """
    return self in (Process.SLA_DLP, Process.MACHINED)

  @property
  def porosity_characterized(self) -> bool:
    """Whether anybody has measured this process's void fraction in this evidence set.

    Separates the two ways `cleanable_in_principle` returns False. FDM is characterized and
    fails; SLS is simply unmeasured. Collapsing them would send a lab to buy a different
    printer when the honest next step is a computed-tomography scan of the part it has.
    """
    return self is not Process.SLS


class PostProcess(str, Enum):
  """A treatment applied after printing, and what it was actually shown to do.

  The members are the things labs reach for when told a printed part cannot be cleaned. None
  of them is recorded here as a solution, and the module is careful to say WHY per member
  rather than dismissing them as a class -- see POST_PROCESS_EVIDENCE. Two of them have real
  measurements behind them and neither measurement is about sealing a porous part.
  """

  VAPOR_SMOOTHING = "vapor_smoothing"
  EPOXY_INFILTRATION = "epoxy_infiltration"
  PARYLENE_COATING = "parylene_coating"
  ANNEALING = "annealing"
  EXTENDED_POST_CURE = "extended_post_cure"
  SOLVENT_EXTRACTION = "solvent_extraction"

  @property
  def closes_the_fluid_path(self) -> bool:
    """Whether this treatment has been SHOWN to make a porous part cleanable.

    False for every member, and that uniformity is a measured result rather than a
    conservative default. An acetone-vapor-treated part was still stained through by dye
    after 30 minutes of immersion in the one study that tested exactly this; epoxy
    infiltration has vendor claims and no peer-reviewed cleaning validation, and cannot
    reach internal channels by those vendors' own admission; a parylene barrier that did
    restore cell viability detached after five to six autoclave cycles. A property that can
    only return False is worth keeping as a property, because the alternative is a caller
    reading the member list and assuming one of them counts.
    """
    return False

  @property
  def moves_dimensions(self) -> bool:
    """Whether applying this invalidates a measurement taken before it.

    Solvent extraction and extended post-cure are excluded not because they are gentle but
    because no dimensional change has been measured for them here. Everything else on the
    list either removes material, adds a layer, or takes the part through its own glass
    transition, and an annealing study measured changes of -2.50 to +2.10 percent that were
    anisotropic -- height grew while width shrank -- so this is percent-level movement with
    a sign that depends on the axis.
    """
    return self in (
      PostProcess.VAPOR_SMOOTHING,
      PostProcess.EPOXY_INFILTRATION,
      PostProcess.PARYLENE_COATING,
      PostProcess.ANNEALING,
    )


POST_PROCESS_EVIDENCE: Dict[PostProcess, str] = {
  PostProcess.VAPOR_SMOOTHING: (
    "reduces surface roughness substantially and does not seal the part. In the study that "
    "immersed treated parts in disinfectant, dye still penetrated a part given 45 minutes of "
    "cold acetone vapor, and mechanical properties fell"
  ),
  PostProcess.EPOXY_INFILTRATION: (
    "claimed airtight and watertight to 65 psi by vendors of the epoxy, with no peer-reviewed "
    "cleaning validation located, and conceded by those same sources to be unable to reach "
    "internal channels. It also introduces a second uncharacterized contact material and can "
    "seal existing bioburden underneath itself"
  ),
  PostProcess.PARYLENE_COATING: (
    "the one barrier with a measurement behind it: a 10 um coating restored a severely "
    "cytotoxic resin to 93 and 85 percent viability on two assays and held for four days. It "
    "detached after five to six autoclave cycles, so a coated part in a reusable workflow "
    "needs a defined replacement interval rather than indefinite reuse"
  ),
  PostProcess.ANNEALING: (
    "demonstrated thermal survival and nothing else. An annealed part came through a 134 C "
    "cycle with its shape and function, in a study whose authors measured no porosity, no "
    "cleanability, no sterility and explicitly no crystallinity. Dimensional cost in the best "
    "case was +0.47 percent on diameter and -1.43 percent on one bar width"
  ),
  PostProcess.EXTENDED_POST_CURE: (
    "moves photopolymer cytotoxicity a long way and cannot move all of it. Longer and hotter "
    "cure took one resin from 48.5 to 89.5 percent viability, still short of control, and it "
    "consumes only the polymerizable fraction -- residual initiator and light stabilizers are "
    "not consumed by further irradiation at all"
  ),
  PostProcess.SOLVENT_EXTRACTION: (
    "the mechanism that can in principle remove non-polymerizable leachates, since post-cure "
    "cannot. No protocol with verifiable parameters was located here, so a lab applying it is "
    "doing something reasonable and unquantified"
  ),
}


# -- contact levels -------------------------------------------------------------


class Contact(str, Enum):
  """How close to the science the part is trusted, ordered by how much each level costs.

  The ordering is the point and each level must be earned rather than assumed. NONE and
  INCIDENTAL are structural claims about geometry: the part holds something, or sits near
  something, and no fluid path passes through it. SAMPLE_CONTACT and CULTURE_CONTACT are
  materials claims, and they are a different kind of question that no amount of dimensional
  work answers. A part can hit every dimension in the microplate standards and be entirely
  unfit to touch a sample, because the standards say nothing about material, leachables,
  cytotoxicity, sterility or biocompatibility -- each one's scope is confined to the single
  feature in its title.

  CULTURE_CONTACT is the strictest level here and is still not the strictest level that
  exists. Gamete and embryo contact is qualified by a mouse embryo assay on parts from the
  actual build, which this module does not model and which no photopolymer resin located here
  advertises.
  """

  NONE = "none"  # structural only; no fluid path, no line of sight to the sample
  INCIDENTAL = "incidental"  # splash or aerosol reach, with no intended contact
  SAMPLE_CONTACT = "sample_contact"  # the sample or its buffer touches the part
  CULTURE_CONTACT = "culture_contact"  # cells or media, at 37 C, for hours to days

  @property
  def in_the_fluid_path(self) -> bool:
    """True where a residue or a leachate reaches the sample by design rather than by accident.

    This is the line the porosity gate is drawn on. INCIDENTAL sits below it deliberately:
    splash contact is a real exposure and it is bounded, transient, and not the geometry
    that makes an unrecoverable void network matter.
    """
    return self in (Contact.SAMPLE_CONTACT, Contact.CULTURE_CONTACT)

  @property
  def rank(self) -> int:
    return _CONTACT_ORDER.index(self)


# Strictest last, so a numeric comparison reads the same direction as the prose.
_CONTACT_ORDER: Tuple[Contact, ...] = (
  Contact.NONE,
  Contact.INCIDENTAL,
  Contact.SAMPLE_CONTACT,
  Contact.CULTURE_CONTACT,
)


# -- sterilization --------------------------------------------------------------


class Sterilization(str, Enum):
  """How the part is decontaminated between uses.

  SINGLE_USE is a real answer and frequently the right one for a printed part: it removes
  the cleaning validation question entirely rather than answering it badly. It is not a
  weaker choice than autoclaving, and a module that ordered these by rigor would imply that
  it is.

  The two steam cycles are kept apart because 13 C separates several materials' verdicts,
  and because the cycles differ in more than temperature -- the higher one runs at roughly
  2.1 bar, which deforms unvented internal cavities on its own, independently of how
  thermally capable the polymer is.
  """

  NONE = "none"  # nothing is done; the part is reused as-is
  SINGLE_USE = "single_use"  # printed, used once, discarded
  IPA_WIPE = "ipa_wipe"  # 70 percent isopropanol on the surface
  AUTOCLAVE_121 = "autoclave_121"  # roughly 15-30 minutes at 121 C
  AUTOCLAVE_134 = "autoclave_134"  # roughly 3-4 minutes at 134 C, around 2.1 bar

  @property
  def cycle_c(self) -> Optional[float]:
    """The temperature the part is taken to, or None where no thermal load is applied."""
    if self is Sterilization.AUTOCLAVE_121:
      return 121.0
    if self is Sterilization.AUTOCLAVE_134:
      return 134.0
    return None

  @property
  def thermal(self) -> bool:
    return self.cycle_c is not None


# -- thermal thresholds, with the method and the provenance that produced them ---


@dataclass(frozen=True)
class Thermal:
  """A temperature threshold as the evidence actually states it: a range and a method.

  A single number is the wrong shape for every value in this domain and publishing one is
  how a guide misleads. Four grades of one polymer from ONE manufacturer span 7 C of glass
  transition. Two manufacturers of nominally the same polymer differ by about 8 C. The same
  polymer measured by two standard test methods on differently produced bars differs by 15
  to 20 C. Print orientation alone moved the onset of dimensional change by 17 C on one
  material. So the range is stored, `conservative()` returns its low end, and the method is
  carried alongside every figure because the method is part of the number.

  `basis` is `qc.Basis`, reused rather than mirrored for the same reason `durability` reuses
  it: a manufacturer's datasheet figure is real evidence and it is not evidence about a part
  printed on your machine at your layer height in your orientation. Datasheet values are
  measured on moulded or specially printed test bars, and both of the high-temperature
  datasheets read here carry explicit disclaimers to that effect. VENDOR is the honest basis
  for almost everything in this module, and IN_HOUSE is what a lab would have to earn.
  """

  low_c: float
  high_c: float
  method: str
  basis: Basis
  note: str = ""

  def __post_init__(self) -> None:
    if self.high_c < self.low_c:
      raise ValueError(
        f"thermal range has high {self.high_c} C below low {self.low_c} C"
      )

  @property
  def spread_c(self) -> float:
    return self.high_c - self.low_c

  def conservative(self) -> float:
    """The low end, which is the only end a gate may use.

    The spread is not measurement noise. It is grade, manufacturer, test method and print
    orientation, and the part in somebody's hand is one unidentified draw from it. Gating on
    the middle of the range means half the possible parts are past the line.
    """
    return self.low_c

  def describe(self) -> str:
    if self.low_c == self.high_c:
      return f"{self.low_c} C ({self.method})"
    return f"{self.low_c}-{self.high_c} C ({self.method})"


# -- materials ------------------------------------------------------------------


@dataclass(frozen=True)
class Material:
  """One polymer as one process makes it, with the contact level it may reach.

  `tg` and `hdt` are both carried and only one of them is ever consulted. That asymmetry is
  the module's sharpest single rule and it is enforced in `survives` rather than documented
  and forgotten: a printed part relaxes its frozen-in extrusion stresses at the glass
  transition with zero applied load, so heat deflection temperature -- which is measured
  under load, on a moulded bar -- describes a situation the part is not in. Where a filler
  carries load above Tg the two numbers can be 100 C or more apart, and reading the higher
  one is how a part goes into a cycle it cannot survive.

  `ceiling` is the highest `Contact` this material may reach on the evidence held here. It is
  a materials judgment and it is deliberately independent of the process porosity gate, so a
  material and a process can refuse the same use for two different reasons. Both get
  reported. A high-temperature engineering polymer that comfortably survives steam still
  carries an FDM ceiling, because surviving a cycle says nothing about whether soil trapped
  in a 4 to 6 percent void network was removed before it -- and steam does not remove
  protein, it fixes it.
  """

  name: str
  process: Process
  ceiling: Contact
  tg: Optional[Thermal] = None
  hdt: Optional[Thermal] = None
  melt: Optional[Thermal] = None
  chemistry: str = ""
  note: str = ""

  def survives(self, method: Sterilization) -> Tuple[Optional[bool], str]:
    """Does the material clear this cycle on thermal grounds? None means nobody can say.

    Three-valued on purpose. True and False are answers; None is the state of a material
    whose glass transition is not on record, which is common -- one polycarbonate blend's
    sheet publishes heat deflection at two loads and no Tg at all, and one polypropylene
    copolymer's sheet publishes neither, only a melting point. Returning False for those
    would be right by accident and wrong in reasoning; returning True would be the vacuous
    pass this package exists to refuse. Returning None makes the caller decide what to do
    about not knowing, which is the honest position.

    Note what a True never claims. It is a statement about softening and nothing else. It is
    not dimensional retention -- the only measured numbers located for any polymer through a
    steam cycle still moved 0.2 to 1.4 percent in the best case, so a function depending on
    a tolerance tighter than about one percent is not answered by this at all. It is not
    hydrolytic stability, which is a separate failure mode that leaves shape intact while
    molecular weight falls. And it is not sterility: whether steam penetrates the interior
    void network of a porous part to a validated assurance level is unmeasured here.
    """
    cycle = method.cycle_c
    if cycle is None:
      return True, f"{method.value} applies no thermal load to the part"
    if self.tg is None:
      carried = f"; heat deflection is on record at {self.hdt.describe()}" if self.hdt else ""
      return None, (
        f"no glass transition is on record for {self.name}, so nothing here can be compared "
        f"against a {cycle:.0f} C cycle{carried}. Heat deflection does not answer this "
        "question for a printed part: it is measured under load on a moulded bar, and a "
        "printed part moves at Tg under no load at all"
      )
    tg = self.tg.conservative()
    if tg <= cycle:
      return False, (
        f"{self.name} has a glass transition from {self.tg.describe()}; the conservative end "
        f"{tg:.0f} C is at or below the {cycle:.0f} C cycle, so the part relaxes its "
        "frozen-in extrusion stresses and moves with nothing applied to it"
      )
    return True, (
      f"{self.name} has a glass transition from {self.tg.describe()}, clearing a "
      f"{cycle:.0f} C cycle by {tg - cycle:.0f} C at the conservative end. That is a "
      "statement about softening only, not about dimensional retention, hydrolysis, or "
      "whether the part came out sterile"
    )


# The materials this repo holds evidence about. Every figure carries the method that produced
# it, and every one is VENDOR or LITERATURE basis -- which is to say nobody here has measured
# any of them on a part from their own machine. That is the normal state and it is the reason
# Basis is on the record at all.

MATERIALS: Dict[str, Material] = {
  "pla_fdm": Material(
    name="PLA (FDM)",
    process=Process.FDM,
    ceiling=Contact.INCIDENTAL,
    tg=Thermal(
      54.0,
      61.0,
      "DSC 10 C/min",
      Basis.VENDOR,
      "four grades from a single manufacturer span 7 C; the colorant and additive package "
      "moves this number, so the spool decides and not the polymer name",
    ),
    hdt=Thermal(52.0, 61.0, "ISO 75 at 1.8 and 0.45 MPa", Basis.VENDOR),
    chemistry=(
      "ester backbone, so it is attacked by water at elevated temperature; a part can hold "
      "its shape through a wet cycle and still lose molecular weight and embrittle"
    ),
    note=(
      "visible warping was observed from approximately 70 C for a curved-beam geometry in "
      "the one annealing study read here, well under the heat deflection figure. Annealed "
      "parts did come through a 134 C cycle functional, which establishes thermal survival "
      "and explicitly not porosity, cleanability or sterility"
    ),
  ),
  "petg_fdm": Material(
    name="PETG (FDM)",
    process=Process.FDM,
    ceiling=Contact.INCIDENTAL,
    tg=Thermal(
      69.0,
      77.0,
      "DSC 10 C/min and ISO 11357",
      Basis.VENDOR,
      "about 8 C between two manufacturers of nominally the same polymer",
    ),
    hdt=Thermal(68.0, 76.0, "ISO 75 at 1.8 and 0.455 MPa", Basis.VENDOR),
    chemistry="ester linkages; hydrolysis-sensitive in wet heat",
    note=(
      "one preprint flags this polymer as cytotoxic while a peer-reviewed stem-cell study "
      "cleared it. Cytotoxicity results are brand and lot specific and do not transfer "
      "between spools of nominally identical polymer, because colorants, plasticizers and "
      "processing aids are not disclosed on consumer filament"
    ),
  ),
  "abs_fdm": Material(
    name="ABS (FDM)",
    process=Process.FDM,
    ceiling=Contact.INCIDENTAL,
    tg=Thermal(
      105.2,
      105.2,
      "ASTM D7426, inflection point",
      Basis.VENDOR,
      "one industrial grade's figure; one desktop manufacturer's sheet for its own ABS lists "
      "Tg as not available, so this single number does not describe the class",
    ),
    hdt=Thermal(
      84.0,
      104.4,
      "ASTM D648 Method B and ISO 75",
      Basis.VENDOR,
      "a 20 C gap between an industrial and a desktop grade, and it is the gap that decides "
      "a 121 C question",
    ),
    note=(
      "a housing in the annealing study deformed at 121 C to the point of being unusable, "
      "which corroborates the datasheet prediction experimentally. The vendor selling a "
      "medical-grade ABS claims gamma and ethylene oxide sterilization for it and not steam"
    ),
  ),
  "asa_fdm": Material(
    name="ASA (FDM)",
    process=Process.FDM,
    ceiling=Contact.INCIDENTAL,
    tg=Thermal(
      104.0,
      104.0,
      "ASTM D7426",
      Basis.VENDOR,
      "one industrial grade; a widely used desktop grade's datasheet gives no Tg at all",
    ),
    hdt=Thermal(86.0, 103.0, "ISO 75 and ASTM D648 Method B", Basis.VENDOR),
    note="the most defensible general-purpose choice here for a structural deck part off the fluid path",
  ),
  "pc_blend_fdm": Material(
    name="PC blend (FDM)",
    process=Process.FDM,
    ceiling=Contact.INCIDENTAL,
    tg=None,
    hdt=Thermal(93.0, 113.0, "ISO 75 at 1.8 and 0.45 MPa", Basis.VENDOR),
    chemistry="carbonate linkages; hydrolysis-sensitive in wet heat",
    note=(
      "the entry where a polymer name does the most damage. The blend's own datasheet "
      "publishes no glass transition. Unfilled bisphenol-A resin is quoted near 147 C, and "
      "this blend sits roughly 30 C below that resin at 1.8 MPa, so quoting the resin's "
      "figure for this material would be about 37 C optimistic"
    ),
  ),
  "pp_copolymer_fdm": Material(
    name="PP copolymer (FDM)",
    process=Process.FDM,
    ceiling=Contact.INCIDENTAL,
    tg=None,
    hdt=None,
    melt=Thermal(137.0, 137.0, "ASTM D3418", Basis.VENDOR),
    note=(
      "the datasheet gives a melting temperature and neither a glass transition nor a heat "
      "deflection figure. A 134 C cycle runs 3 C below that melting point. The reputation of "
      "moulded polypropylene labware, which is routinely autoclaved, does not carry over to "
      "this filament: homopolymer melts higher, and the grade decides whether a 134 C cycle "
      "is marginal or catastrophic"
    ),
  ),
  "pa_cf_fdm": Material(
    name="Carbon-fiber nylon (FDM)",
    process=Process.FDM,
    ceiling=Contact.INCIDENTAL,
    tg=Thermal(70.0, 70.0, "DSC 10 C/min", Basis.VENDOR),
    hdt=Thermal(170.0, 194.0, "ISO 75 at 1.8 and 0.45 MPa", Basis.VENDOR),
    chemistry=(
      "amide linkages and strongly hygroscopic. A steam cycle drives it toward saturation, "
      "which swells the part and plasticizes the matrix, dropping the transition further"
    ),
    note=(
      "the material that makes the Tg-versus-HDT rule concrete: heat deflection sits 100 to "
      "124 C above the glass transition purely because carbon fiber carries the load the "
      "matrix no longer can. Read the HDT column and a 121 C cycle looks like a wide margin; "
      "read Tg and the part is 51 C past the line"
    ),
  ),
  "pei_9085_fdm": Material(
    name="PEI 9085 (FDM)",
    process=Process.FDM,
    ceiling=Contact.INCIDENTAL,
    tg=Thermal(177.3, 177.3, "ASTM D7426, inflection point", Basis.VENDOR),
    hdt=Thermal(170.2, 178.4, "ASTM D648 Method B, printed, XY and XZ", Basis.VENDOR),
    note=(
      "clears both steam cycles thermally and reaches no further up the contact ladder than "
      "any other FDM material, because the void network is the same. The same datasheet's "
      "thermomechanical curves show dimensional reversal beginning at about 175.9 C upright "
      "against about 193.4 C flat, so orientation is worth 17 C on one material"
    ),
  ),
  "pei_1010_fdm": Material(
    name="PEI 1010 (FDM)",
    process=Process.FDM,
    ceiling=Contact.INCIDENTAL,
    tg=Thermal(
      210.0,
      217.0,
      "ASTM D7426 printed and ISO 11357 moulded",
      Basis.VENDOR,
      "the same polymer 7 C apart because the tests and the bars differ",
    ),
    hdt=Thermal(190.0, 215.0, "ISO 75 and ASTM D648 Method B", Basis.VENDOR),
    note=(
      "one trade name spans this material and PEI 9085 with 33 to 40 C between their glass "
      "transitions, which is why a grade name is not a material specification"
    ),
  ),
  "peek_fdm": Material(
    name="PEEK (FDM)",
    process=Process.FDM,
    ceiling=Contact.INCIDENTAL,
    tg=Thermal(
      143.0,
      150.0,
      "ISO 11357-2, onset and midpoint",
      Basis.VENDOR,
      "measured on injection-moulding granules, not on a printed part",
    ),
    hdt=Thermal(152.0, 152.0, "ISO 75-2/Af, unannealed", Basis.VENDOR),
    melt=Thermal(343.0, 343.0, "ISO 11357-3", Basis.VENDOR),
    note=(
      "the margin at 134 C is thinner than the numbers suggest: the transition onset is 9 C "
      "above the cycle, and the material tolerates it because its crystalline phase carries "
      "load above the transition. As-printed material from a machine without adequate chamber "
      "temperature can be substantially amorphous, in which case it is not the article the "
      "datasheet describes. The manufacturer's steam-sterilization statement is about moulded "
      "granules"
    ),
  ),
  "photopolymer_uncertified": Material(
    name="Photopolymer, uncertified",
    process=Process.SLA_DLP,
    ceiling=Contact.INCIDENTAL,
    tg=None,
    hdt=None,
    chemistry=(
      "typical formulations contain more than twenty compounds and manufacturers disclose "
      "only the hazard-classified ones. Documented cytotoxic leachates span crosslinkers, "
      "monomers, photoinitiators and light stabilizers, and only the first three are "
      "polymerizable, so post-cure cannot reach the fourth"
    ),
    note=(
      "three consumer resins fell into the 0-25 percent viability band on two assays after "
      "the full manufacturer workflow including sterilization. Parts from a vat printer were "
      "measurably more toxic to fish embryos than parts from a fused-deposition printer in "
      "the one study that compared them directly"
    ),
  ),
  "photopolymer_certified": Material(
    name="Photopolymer, certified biocompatible",
    process=Process.SLA_DLP,
    ceiling=Contact.CULTURE_CONTACT,
    tg=None,
    hdt=Thermal(54.0, 67.0, "ASTM D648-18 Method B at 1.8 and 0.45 MPa", Basis.VENDOR),
    chemistry=(
      "the certification covers a named list of endpoints -- cytotoxicity, mutagenicity, "
      "irritation, sensitization, systemic toxicity, pyrogenicity -- and not reproductive or "
      "developmental toxicity, which the standard's own risk logic does not trigger for a "
      "benchtop fixture"
    ),
    note=(
      "reaching this ceiling requires the resin, the workflow and the cure together; see "
      "ResinQualification. Both heat deflection figures sit far below any steam cycle even "
      "where the resin's chemistry is validated for one, so chemical clearance for a cycle "
      "and dimensional survival of it are separate questions and this material answers only "
      "the first. No glass transition is published, so this module refuses the autoclave "
      "check for it rather than guessing"
    ),
  ),
  "machined_stock": Material(
    name="Machined from moulded or extruded stock",
    process=Process.MACHINED,
    ceiling=Contact.SAMPLE_CONTACT,
    tg=None,
    hdt=None,
    note=(
      "the defensible route for a reused sample-contacting part, and the reason the process "
      "enum includes something that is not printed at all. A machined part inherits the "
      "stock's datasheet, which has to be obtained per grade -- so no thermal figure is "
      "asserted here and the autoclave check refuses until somebody supplies one. The "
      "ceiling stops below culture contact because culture contact needs its own materials "
      "qualification that this repo holds for no stock"
    ),
  ),
}


def materials_reaching(contact: Contact) -> Tuple[Material, ...]:
  """Every material whose ceiling permits this contact level.

  Permits, not clears. A material at or above the level still has to get past the process
  porosity gate, the resin qualification gate where one applies, and everything `fitness`
  checks about the fixture itself.
  """
  return tuple(m for m in MATERIALS.values() if m.ceiling.rank >= contact.rank)


def materials_surviving(method: Sterilization) -> Tuple[Material, ...]:
  """Every material whose glass transition clears this cycle.

  A material with no Tg on record is not in the result, which is the same convention as
  everywhere else here: the absence of a threshold is not a threshold that passes.
  """
  return tuple(m for m in MATERIALS.values() if m.survives(method)[0] is True)


# -- what a photopolymer part has actually had established about it ---------------


@dataclass(frozen=True)
class ResinQualification:
  """What is established about a specific photopolymer part, defaulting to nothing.

  Three fields rather than one because a certification is three claims and losing any of
  them loses the certification. The resin carries a file of endpoint results. The
  certification data were measured on one printer, at one layer height, washed for a stated
  time in isopropanol of a stated purity, and cured at a stated temperature for a stated
  duration -- a part made on different hardware, or washed in reused solvent, or cured in
  something else, is not the article that was tested. And the cure this lab actually ran is
  a separate question again from the cure the certification names, because cure energy is
  the largest single lever on residual cytotoxicity and nobody outside the lab can verify
  it was applied.

  None of the three, together, is clearance for gametes or embryos. Both resins that
  destroyed every oocyte in the study that tested them were certified biocompatible at the
  time, and the causative leachate identified there was a light stabilizer -- not a monomer
  and not an initiator -- which no amount of further irradiation consumes.
  """

  certified_biocompatible: bool = False
  workflow_as_certified: bool = False
  post_cure_validated: bool = False

  @property
  def cleared_for_culture(self) -> bool:
    return (
      self.certified_biocompatible and self.workflow_as_certified and self.post_cure_validated
    )

  def missing(self) -> Tuple[str, ...]:
    """Which of the three conditions is absent, named so a report can list them."""
    out: List[str] = []
    if not self.certified_biocompatible:
      out.append("no certified biocompatible resin")
    if not self.workflow_as_certified:
      out.append("the part was not made by the workflow the certification was measured on")
    if not self.post_cure_validated:
      out.append("no validated post-cure")
    return tuple(out)


# -- dimensions -----------------------------------------------------------------


class DimensionState(str, Enum):
  """Where a dimension's number came from.

  DESIGNED is the dangerous member and the reason this is an enum rather than a boolean. A
  designed dimension is a number, in millimeters, in a document, and it reads exactly like a
  measurement -- but it is a fact about a model. Desktop tolerance is quoted at plus or minus
  0.5 percent with a floor of plus or minus 0.5 mm and it scales with length, so a
  well-behaved calibration cube establishes nothing about a 200 mm part. Shrinkage is not
  published on the filament datasheets checked here at all, and the compensation values
  shipped inside slicers disagree between two vendors by 0.5 percent on the same polymer.

  UNCHECKED is more honest than DESIGNED and less common, because somebody always has the
  model.
  """

  UNCHECKED = "unchecked"  # nobody has looked at the printed part
  DESIGNED = "designed"  # the number in the model; a fact about the file
  MEASURED = "measured"  # somebody put an instrument on the part that came out

  @property
  def measured(self) -> bool:
    return self is DimensionState.MEASURED


@dataclass(frozen=True)
class CriticalDimension:
  """One dimension the part's function depends on, and where its number came from.

  Refuses three incoherent states at construction rather than carrying them into a report. A
  MEASURED dimension with no measured value is the vacuous pass in its purest form: a state
  flag that says a measurement happened, with no measurement. A non-MEASURED dimension
  carrying a measured value is the same ambiguity from the other side. And a measurement with
  no instrument named is an assertion, held to the same standard `qc.Criterion` holds a
  threshold to when it requires a rationale and a basis.

  `measured_after_processing` exists because the order of operations decides whether a
  measurement still describes the part. Annealing, smoothing, coating and steam cycles all
  move dimensions by percent, anisotropically -- one study measured height growing while
  width shrank in the same part -- so a caliper reading taken before any of those is a
  reading of a part that no longer exists.
  """

  name: str
  nominal_mm: float
  state: DimensionState = DimensionState.DESIGNED
  measured_mm: Optional[float] = None
  measured_after_processing: bool = False
  instrument: str = ""

  def __post_init__(self) -> None:
    if self.state.measured:
      if self.measured_mm is None:
        raise ValueError(
          f"dimension '{self.name}' claims MEASURED and carries no measured value; a state "
          "flag is not a measurement"
        )
      if not self.instrument:
        raise ValueError(
          f"dimension '{self.name}' claims MEASURED and names no instrument; an unattributed "
          "measurement is an assertion"
        )
    else:
      if self.measured_mm is not None:
        raise ValueError(
          f"dimension '{self.name}' is {self.state.value} and carries a measured value; that "
          "ambiguity is how a designed number comes to read as a measured one"
        )
      if self.measured_after_processing:
        raise ValueError(
          f"dimension '{self.name}' is {self.state.value} and claims it was measured after "
          "processing; nothing was measured at all"
        )

  def deviation_mm(self) -> Optional[float]:
    """How far the part came out from the model, or None where nobody measured it.

    None rather than zero. Zero is a finding and would be the most misleading possible
    default here, since the whole point of the distinction is that an unmeasured part is not
    a part that came out on size.
    """
    if self.measured_mm is None:
      return None
    return self.measured_mm - self.nominal_mm

  def deviation_percent(self) -> Optional[float]:
    dev = self.deviation_mm()
    if dev is None or self.nominal_mm == 0:
      return None
    return 100.0 * dev / self.nominal_mm


# -- the claimed benefit --------------------------------------------------------


@dataclass(frozen=True)
class Benefit:
  """What the fixture is claimed to buy, and whether anybody measured it.

  The question a printed fixture rarely gets asked. A part that saves nothing measurable is
  a part on a deck for no reason, adding a crash surface, a cleaning obligation and an
  uncharacterized material to a workcell that had none of them. `quantified` requires an
  in-house basis specifically: a vendor's or a forum's claim about what a fixture buys is not
  a measurement of what THIS fixture buys on THIS deck, which is the identical distinction
  `qc.Basis` draws about a threshold.
  """

  claim: str
  measured: Optional[str] = None
  basis: Basis = Basis.INTUITION

  @property
  def quantified(self) -> bool:
    return self.measured is not None and self.basis.validated


# -- the fixture ----------------------------------------------------------------


@dataclass(frozen=True)
class Fixture:
  """A specific printed part, with every field defaulting to its untrusted value.

  Constructible with no arguments, and a fixture constructed that way is never fit for
  anything. That is not a convenience -- it is the test the rest of the module is built
  around. A default that reads as a pass is the failure mode this package hunts everywhere
  else, and a fixture dataclass whose defaults were `positively_located=True` and
  `dimensions=()` would report a part nobody has built as ready for a deck.

  `process` is a property reading the material rather than a field of its own, because two
  fields that can disagree eventually will, and a fixture claiming FDM while carrying a
  photopolymer would be refused by one gate and cleared by another.
  """

  name: str = ""
  material: Optional[Material] = None
  built_for: Contact = Contact.NONE
  dimensions: Tuple[CriticalDimension, ...] = ()
  positively_located: bool = False
  benefit: Optional[Benefit] = None
  post_processing: Tuple[PostProcess, ...] = ()
  resin: ResinQualification = field(default_factory=ResinQualification)
  demonstrated: Tuple["Qualification", ...] = ()
  note: str = ""

  @property
  def process(self) -> Optional[Process]:
    return None if self.material is None else self.material.process

  def dimensions_measured(self) -> bool:
    """True only where at least one critical dimension is declared and every one was measured.

    The leading truthiness check is the whole method. `all()` over an empty tuple is True, so
    the natural one-liner reports a fixture that declares no dimensions at all as fully
    measured -- a check that passes when handed nothing, which is the exact shape of vacuous
    pass this package refuses in `qc.evaluate` and again here.
    """
    return bool(self.dimensions) and all(d.state.measured for d in self.dimensions)

  def dimension_changing_processes(self) -> Tuple[PostProcess, ...]:
    return tuple(p for p in self.post_processing if p.moves_dimensions)

  def stale_dimensions(self, thermally_cycled: bool = False) -> Tuple[CriticalDimension, ...]:
    """Measured dimensions whose measurement predates something that moved them.

    Returns nothing when nothing moved them, so this cannot manufacture a finding out of a
    part that was simply printed and measured.
    """
    if not self.dimension_changing_processes() and not thermally_cycled:
      return ()
    return tuple(
      d for d in self.dimensions if d.state.measured and not d.measured_after_processing
    )


# -- what has not been demonstrated ----------------------------------------------


class Qualification(str, Enum):
  """Something that could be demonstrated about a printed part, and usually has not been.

  The list is the standing backlog for one part. Four of the eight cannot be cleared by
  anything in this module's own fields and have to be recorded by a lab that actually did the
  work, because they are wet-bench results rather than facts about the build: cleanability to
  a stated residue limit, a leachables characterization, sterility of the interior rather
  than the surface, and a thermal measurement on a part from this machine instead of a
  datasheet figure about a moulded bar.

  No published study located here has validated a fused-deposition part as cleanable to a
  recognized standard. That is absence of evidence from this search rather than proof none
  exists, and it is the crux of the question, so the qualification stays on the list rather
  than being quietly assumed either way.
  """

  MATERIAL_DECLARED = "material_declared"
  DIMENSIONS_MEASURED = "dimensions_measured"
  POSITIVE_LOCATION = "positive_location"
  BENEFIT = "benefit"
  CLEANABILITY = "cleanability"
  LEACHABLES = "leachables"
  STERILITY = "sterility"
  THERMAL_ON_THIS_PART = "thermal_on_this_part"


def unqualified(fixture: Fixture) -> Tuple[Qualification, ...]:
  """Everything that has not been demonstrated about this fixture.

  Defaults to everything, in the order the enum declares. A new print is untrusted in exactly
  the way an unbenchmarked operation is untrusted in `intelligence.trusted_for` -- and for a
  stronger reason, since an operation at least has a script somebody wrote and read, while a
  fresh print has a shape somebody hoped for.

  Four of the eight are read off the fixture's own fields, and the other four can only be
  cleared by a caller recording them in `demonstrated`. That asymmetry is deliberate: this
  module can see whether a dimension was measured and cannot see whether a residue limit was
  met, and inventing a way to infer the second from the first is precisely the move this
  package exists to refuse.
  """
  held = set(fixture.demonstrated)
  if fixture.material is not None:
    held.add(Qualification.MATERIAL_DECLARED)
  if fixture.dimensions_measured():
    held.add(Qualification.DIMENSIONS_MEASURED)
  if fixture.positively_located:
    held.add(Qualification.POSITIVE_LOCATION)
  if fixture.benefit is not None and fixture.benefit.quantified:
    held.add(Qualification.BENEFIT)
  return tuple(q for q in Qualification if q not in held)


# -- the use ---------------------------------------------------------------------


@dataclass(frozen=True)
class Use:
  """What the part is being asked to do, stated by the caller.

  `contact` has no default and must be named. Every other field defaults to the demanding
  case, because a deck fixture sits inside an arm's sweep and gets registered against unless
  somebody establishes otherwise, and a default that assumed the safe geometry would let an
  under-specified use clear checks it never faced.

  `robot_registers_to_it` covers both halves of the same requirement -- a gripper closing on
  the part and a tip having to reach a position defined by it -- because they fail on the
  same missing evidence. Both need the printed part's real dimension rather than the model's,
  and neither is helped by knowing the model's.
  """

  name: str
  contact: Contact
  robot_registers_to_it: bool = True
  inside_moving_envelope: bool = True
  sterilization: Sterilization = Sterilization.NONE
  note: str = ""


# -- the verdict -----------------------------------------------------------------


class Fitness(str, Enum):
  """Whether a printed part may be used for a purpose, and if not, which refusal comes first.

  FIT is a member of the same enum as the refusals, following `feedback.Closable`, because
  fitness is the absence of every refusal rather than a state of its own. There is no field
  anywhere that sets it.

  `structural` draws the line the reporting order is built on. Two of these name something no
  measurement, procedure or purchase clears for the part as built -- the only thing that
  clears them is a different part, made a different way or out of a different polymer.
  Everything else names work: measure the dimension, bolt the fixture down, certify the
  resin, quantify what the thing buys. Reporting a cheap refusal ahead of a structural one
  sends a lab to do work that will not matter.
  """

  MATERIAL_UNDECLARED = "material_undeclared"
  POROUS_PROCESS_IN_FLUID_PATH = "porous_process_in_fluid_path"
  CYTOTOXICITY_UNCLEARED = "cytotoxicity_uncleared"
  SOFTENS_IN_THE_CYCLE = "softens_in_the_cycle"
  UNCHARACTERIZED_PROCESS = "uncharacterized_process"
  THERMAL_LIMIT_UNKNOWN = "thermal_limit_unknown"
  ABOVE_MATERIAL_CEILING = "above_material_ceiling"
  ABOVE_DECLARED_CONTACT = "above_declared_contact"
  NOT_POSITIVELY_LOCATED = "not_positively_located"
  DIMENSION_NOT_MEASURED = "dimension_not_measured"
  DIMENSION_STALE_AFTER_CYCLE = "dimension_stale_after_cycle"
  BENEFIT_NOT_QUANTIFIED = "benefit_not_quantified"
  FIT = "fit"

  @property
  def usable(self) -> bool:
    return self is Fitness.FIT

  @property
  def structural(self) -> bool:
    return self in (Fitness.POROUS_PROCESS_IN_FLUID_PATH, Fitness.SOFTENS_IN_THE_CYCLE)


# Reported in this order. FIT is not in it: it is what is left when nothing else applies.
_REFUSAL_ORDER: Tuple[Fitness, ...] = (
  Fitness.MATERIAL_UNDECLARED,
  Fitness.POROUS_PROCESS_IN_FLUID_PATH,
  Fitness.CYTOTOXICITY_UNCLEARED,
  Fitness.SOFTENS_IN_THE_CYCLE,
  Fitness.UNCHARACTERIZED_PROCESS,
  Fitness.THERMAL_LIMIT_UNKNOWN,
  Fitness.ABOVE_MATERIAL_CEILING,
  Fitness.ABOVE_DECLARED_CONTACT,
  Fitness.NOT_POSITIVELY_LOCATED,
  Fitness.DIMENSION_NOT_MEASURED,
  Fitness.DIMENSION_STALE_AFTER_CYCLE,
  Fitness.BENEFIT_NOT_QUANTIFIED,
)


@dataclass(frozen=True)
class Objection:
  """One reason a part may not be used for a purpose, with the specific thing that is wrong."""

  reason: Fitness
  detail: str


@dataclass(frozen=True)
class Assessment:
  """One part costed against one use.

  `objections` is every refusal the pairing earned, in reporting order, and the verdict is
  the first of them. Carrying all of them rather than returning on the first is the same
  choice `feedback.Closure` makes and for the same reason: a printed part is usually wrong in
  more than one way, and a report showing only the headline sends somebody to fix that and
  rediscover the next one after the fix.
  """

  fixture: Fixture
  use: Use
  objections: Tuple[Objection, ...]

  @property
  def verdict(self) -> Fitness:
    return self.objections[0].reason if self.objections else Fitness.FIT

  @property
  def fit(self) -> bool:
    return not self.objections

  @property
  def needs_a_different_part(self) -> bool:
    """True where at least one refusal is structural, so no amount of work on this part helps."""
    return any(o.reason.structural for o in self.objections)

  def refusals(self) -> Tuple[Fitness, ...]:
    return tuple(o.reason for o in self.objections)

  def all_reasons(self) -> Tuple[str, ...]:
    return tuple(o.detail for o in self.objections)

  @property
  def reason(self) -> str:
    if self.objections:
      return self.objections[0].detail
    return (
      f"'{self.fixture.name or 'this part'}' clears every refusal for '{self.use.name}' and "
      "for no other use; fitness is computed per purpose and does not transfer"
    )


def _porosity_detail(fixture: Fixture, use: Use) -> str:
  applied = fixture.post_processing
  base = (
    f"{use.contact.value} puts a {Process.FDM.value} part in the fluid path. Fused deposition "
    "parts were measured by computed tomography at 4.05 to 6.32 percent porosity with infill "
    "fixed at 100 percent, across raster angles and extrusion widths, and the voids "
    "concentrate between the outer perimeter and the infill -- so the network is connected to "
    "the outside surface, fluid enters it, and nothing reaches in to remove what enters. The "
    "immersion study that tested this concluded that no manufacturing settings provide "
    "adequate sealing, and bacteria attach preferentially in the grooves between layers"
  )
  if not applied:
    return base
  claims = "; ".join(f"{p.value}: {POST_PROCESS_EVIDENCE[p]}" for p in applied)
  return (
    base
    + ". Post-processing is applied and none of it is a demonstrated fix for this -- "
    + claims
  )


def fitness(fixture: Fixture, use: Use) -> Assessment:
  """Whether this part may be used for this purpose, with every refusal it earns.

  Every check runs. The function does not return on the first refusal, and it does not
  shortcut the fixture-level checks when the material is missing, because a part with no
  declared material still sits somewhere on a deck and still either is or is not bolted down.

  Fitness is computed per use and never cached on the fixture. The same part is fit as a
  bracket and unfit as a reservoir, and a fixture carrying a fitness field would let the
  first answer be read as the second.
  """
  found: List[Objection] = []
  mat = fixture.material

  if mat is None:
    found.append(
      Objection(
        Fitness.MATERIAL_UNDECLARED,
        "no material is declared, so no thermal limit, no contact ceiling and no process "
        "porosity claim can be resolved. Nothing about the material is refused here because "
        "nothing about it is known, which is a worse position than a bad material honestly "
        "named",
      )
    )
  else:
    if use.contact.in_the_fluid_path and not mat.process.cleanable_in_principle:
      if mat.process.porosity_characterized:
        found.append(Objection(Fitness.POROUS_PROCESS_IN_FLUID_PATH, _porosity_detail(fixture, use)))
      else:
        found.append(
          Objection(
            Fitness.UNCHARACTERIZED_PROCESS,
            f"{use.contact.value} needs a process whose void fraction somebody measured, and "
            f"this repo holds no porosity measurement for {mat.process.value} at all. This is "
            "not a finding that the process is porous; it is the absence of a finding either "
            "way, and it is cleared by a measurement rather than by a different part",
          )
        )

    if use.contact is Contact.CULTURE_CONTACT and mat.process is Process.SLA_DLP:
      if not fixture.resin.cleared_for_culture:
        missing = "; ".join(fixture.resin.missing())
        found.append(
          Objection(
            Fitness.CYTOTOXICITY_UNCLEARED,
            f"culture contact with a photopolymer part requires a certified biocompatible "
            f"resin, the workflow the certification was measured on, and a validated "
            f"post-cure. Missing: {missing}. Incompletely cured resin is cytotoxic, and the "
            "part of it that post-curing cannot reach is the non-polymerizable fraction -- "
            "the leachate identified in the oocyte study was a light stabilizer at roughly "
            "50 ug/mL, which further irradiation does not consume",
          )
        )

    if use.contact.rank > mat.ceiling.rank:
      found.append(
        Objection(
          Fitness.ABOVE_MATERIAL_CEILING,
          f"'{mat.name}' reaches {mat.ceiling.value} on the evidence held here and this use "
          f"asks for {use.contact.value}",
        )
      )

    if use.sterilization.thermal:
      ok, why = mat.survives(use.sterilization)
      if ok is None:
        found.append(Objection(Fitness.THERMAL_LIMIT_UNKNOWN, why))
      elif not ok:
        found.append(Objection(Fitness.SOFTENS_IN_THE_CYCLE, why))

  if use.contact.rank > fixture.built_for.rank:
    found.append(
      Objection(
        Fitness.ABOVE_DECLARED_CONTACT,
        f"the part was built for {fixture.built_for.value} and this use asks for "
        f"{use.contact.value}. A fixture promoted up the ladder after the fact was designed, "
        "printed and finished against a weaker requirement than the one it is now being held "
        "to",
      )
    )

  if use.inside_moving_envelope and not fixture.positively_located:
    found.append(
      Objection(
        Fitness.NOT_POSITIVELY_LOCATED,
        "the part sits inside a moving arm's envelope and nothing positively locates it. An "
        "unlocated fixture is a crash waiting for the first knock: it needs no operator error "
        "to move, and once it has moved every taught position that references it is wrong "
        "with nothing reporting that anything changed",
      )
    )

  if use.robot_registers_to_it:
    if not fixture.dimensions_measured():
      declared = len(fixture.dimensions)
      unmeasured = tuple(d.name for d in fixture.dimensions if not d.state.measured)
      if declared == 0:
        detail = (
          "a robot grips this part or a tip must reach a position it defines, and no critical "
          "dimension is declared at all"
        )
      else:
        detail = (
          "a robot grips this part or a tip must reach a position it defines, and these "
          f"dimensions were never measured on the printed part: {', '.join(unmeasured)}"
        )
      found.append(
        Objection(
          Fitness.DIMENSION_NOT_MEASURED,
          detail
          + ". A designed dimension is a fact about the model. Desktop tolerance is quoted at "
          "plus or minus 0.5 percent with a floor of plus or minus 0.5 mm and it scales with "
          "length, shrinkage is material and vendor specific and is not published on the "
          "filament datasheets checked here, and the first layer comes out wider than the "
          "model by roughly the 0.2 mm of compensation a slicer applies by default",
        )
      )
    else:
      stale = fixture.stale_dimensions(use.sterilization.thermal)
      if stale:
        movers = [p.value for p in fixture.dimension_changing_processes()]
        if use.sterilization.thermal:
          movers.append(use.sterilization.value)
        found.append(
          Objection(
            Fitness.DIMENSION_STALE_AFTER_CYCLE,
            f"these dimensions were measured before {', '.join(movers)}: "
            f"{', '.join(d.name for d in stale)}. Thermal and coating steps move printed parts "
            "by percent rather than by microns, and anisotropically -- one annealing study "
            "measured height growing while width shrank in the same part, with best-case "
            "changes of +0.47 and -1.43 percent. A measurement taken before them describes a "
            "part that no longer exists",
          )
        )

  if fixture.benefit is None or not fixture.benefit.quantified:
    if fixture.benefit is None:
      detail = "nothing states what this part is for"
    elif fixture.benefit.measured is None:
      detail = f"the claim is '{fixture.benefit.claim}' and nobody measured it"
    else:
      detail = (
        f"the claim is '{fixture.benefit.claim}' and the measurement behind it rests on "
        f"{fixture.benefit.basis.value}, which is not a measurement of what this part buys on "
        "this deck"
      )
    found.append(
      Objection(
        Fitness.BENEFIT_NOT_QUANTIFIED,
        detail
        + ". An unquantified fixture is a net addition of a crash surface, a cleaning "
        "obligation and an uncharacterized material to a workcell that had none of them",
      )
    )

  by_reason = {o.reason: o for o in found}
  ordered = tuple(by_reason[r] for r in _REFUSAL_ORDER if r in by_reason)
  return Assessment(fixture=fixture, use=use, objections=ordered)


# -- the microplate envelope a printed nest has to clear -------------------------
# Included because the plate nest is the canonical printed fixture and because the number
# everybody quotes for it is the wrong one. Nothing in this section is evidence about contact
# fitness: dimensional conformity and fitness to touch a sample are independent questions, and
# the standards themselves say nothing at all about material, leachables, cytotoxicity,
# sterility or biocompatibility.


class Flange(str, Enum):
  """Which bottom-flange variant a plate declares, of the five that are mutually exclusive.

  The standard requires a plate to state which one it meets, and a vendor page saying only
  that a plate is footprint-compliant does not state it. UNDECLARED is therefore a real and
  common state rather than a placeholder, and it is the state in which a printed nest cannot
  be dimensioned -- a nest built around a tall flange will not reliably hold a short-flange
  plate, and the difference between the extremes is over 5 mm.
  """

  SHORT = "short"  # 2.41 mm +/- 0.38
  MEDIUM = "medium"  # 6.10 mm +/- 0.38
  TALL = "tall"  # 7.62 mm +/- 0.38
  SHORT_INTERRUPTED = "short_interrupted"  # 2.41 mm +/- 0.38, one interruption per long side
  DUAL = "dual"  # 2.41 mm on the short sides, 7.62 mm on the long sides
  UNDECLARED = "undeclared"

  @property
  def declared(self) -> bool:
    return self is not Flange.UNDECLARED


# Nominal footprint, and the two tolerances that apply to it. Both are real and only one of
# them is famous.
FOOTPRINT_LENGTH_MM = 127.76
FOOTPRINT_WIDTH_MM = 85.48
CORNER_ZONE_TOLERANCE_MM = 0.25  # applies only within 12.7 mm of the four outside corners
MID_SIDE_TOLERANCE_MM = 0.5  # applies anywhere else along the side
CORNER_RADIUS_MM = 3.18
CORNER_RADIUS_TOLERANCE_MM = 1.6  # a permitted range of 1.58 to 4.78 mm, a threefold spread
TYPICAL_HEIGHT_MM = 14.35
TYPICAL_HEIGHT_TOLERANCE_MM = 0.76  # overall plate height, Datum A to maximum protrusion

_FLANGE_NOMINAL: Dict[Flange, Tuple[float, float]] = {
  Flange.SHORT: (2.41, 2.41),
  Flange.MEDIUM: (6.10, 6.10),
  Flange.TALL: (7.62, 7.62),
  Flange.SHORT_INTERRUPTED: (2.41, 2.41),
  Flange.DUAL: (2.41, 7.62),
}
_FLANGE_TOLERANCE_MM = 0.38


@dataclass(frozen=True)
class PlateEnvelope:
  """The largest a conforming plate may actually be, which is what a nest has to clear.

  Every figure here is a maximum rather than a nominal, and that is the point of computing it
  instead of copying the headline. A nest cut to the nominal footprint with the famous
  tolerance jams a plate that bowed to the mid-side limit and still conforms. A nest cut to
  the nominal corner radius binds on a plate at the upper end of a range that spans 1.58 to
  4.78 mm. Neither plate is out of specification.

  `max_height_mm` is None unless the caller states the plate is a standard-height microplate,
  because height is standardized only for that format. Deep-well, PCR and reservoir plates
  keep the footprint and abandon the height, and the heights they use are individual product
  specifications rather than a standard, so no figure is emitted for them.
  """

  max_length_mm: float
  max_width_mm: float
  max_corner_radius_mm: float
  flange_low_mm: Optional[float]
  flange_high_mm: Optional[float]
  max_height_mm: Optional[float]
  note: str

  @property
  def flange_known(self) -> bool:
    return self.flange_low_mm is not None and self.flange_high_mm is not None


DRAFT_NOTE = (
  "the standards state that their dimensions and tolerances exclude draft. Moulded plates "
  "carry draft angles the numbers here do not describe, and those angles are not published "
  "anywhere in the standards, so a printed nest modelled on nominals with vertical walls does "
  "not have the same cross-section as the plate it is meant to seat. Dimensional conformity "
  "is also not evidence of fitness for contact with cells, media or samples -- the standards "
  "say nothing about material, leachables, cytotoxicity, sterility or biocompatibility"
)


def plate_envelope(
  flange: Flange = Flange.UNDECLARED, typical_height: bool = False
) -> PlateEnvelope:
  """The maxima a printed nest has to clear for a plate that conforms.

  Refuses to emit flange numbers for an undeclared variant rather than picking the common one.
  The variants are mutually exclusive by the standard's own text, the standard requires the
  plate to declare which it meets, and guessing produces a nest that holds some plates and
  drops others -- which is worse than a nest that was never built, because the failure is
  intermittent.
  """
  if flange.declared:
    low, high = _FLANGE_NOMINAL[flange]
    flange_low: Optional[float] = low - _FLANGE_TOLERANCE_MM
    flange_high: Optional[float] = high + _FLANGE_TOLERANCE_MM
    if flange is Flange.DUAL:
      note = (
        "the two flange figures are different SIDES of one plate, not a tolerance band: the "
        "short sides and the long sides differ by over 5 mm. " + DRAFT_NOTE
      )
    else:
      note = DRAFT_NOTE
  else:
    flange_low = None
    flange_high = None
    note = (
      "no flange variant is declared, so no flange height is emitted. Five mutually exclusive "
      "variants exist, they span 2.41 to 7.62 mm nominal, and the standard requires a plate to "
      "state which one it meets. A nest dimensioned around a guess holds some conforming "
      "plates and drops others. " + DRAFT_NOTE
    )
  return PlateEnvelope(
    max_length_mm=FOOTPRINT_LENGTH_MM + MID_SIDE_TOLERANCE_MM,
    max_width_mm=FOOTPRINT_WIDTH_MM + MID_SIDE_TOLERANCE_MM,
    max_corner_radius_mm=CORNER_RADIUS_MM + CORNER_RADIUS_TOLERANCE_MM,
    flange_low_mm=flange_low,
    flange_high_mm=flange_high,
    max_height_mm=(TYPICAL_HEIGHT_MM + TYPICAL_HEIGHT_TOLERANCE_MM) if typical_height else None,
    note=note,
  )


# -- reference fixtures and uses --------------------------------------------------
# Three parts a lab actually prints, in the state a lab actually prints them in. The first is
# the honest default: designed, printed, put on the deck. The last is what it costs to get one
# part to FIT for one use.

FIXTURES: Dict[str, Fixture] = {
  "plate_nest_as_printed": Fixture(
    name="plate_nest_as_printed",
    material=MATERIALS["pla_fdm"],
    built_for=Contact.NONE,
    dimensions=(
      CriticalDimension(name="pocket_length", nominal_mm=128.5),
      CriticalDimension(name="pocket_width", nominal_mm=86.2),
      CriticalDimension(name="corner_relief_radius", nominal_mm=4.8),
    ),
    positively_located=False,
    benefit=None,
    note=(
      "the state every printed fixture starts in and most stay in: modelled, printed, set on "
      "the deck. Nothing about it is measured and nothing holds it down"
    ),
  ),
  "reagent_trough_petg": Fixture(
    name="reagent_trough_petg",
    material=MATERIALS["petg_fdm"],
    built_for=Contact.SAMPLE_CONTACT,
    dimensions=(
      CriticalDimension(
        name="trough_floor_depth",
        nominal_mm=12.0,
        state=DimensionState.MEASURED,
        measured_mm=11.82,
        measured_after_processing=True,
        instrument="digital caliper, three positions",
      ),
    ),
    positively_located=True,
    post_processing=(PostProcess.VAPOR_SMOOTHING,),
    benefit=Benefit(
      claim="holds a shared reagent volume no commercial trough matches",
      measured="dead volume 1.1 mL against 4.0 mL for the commercial trough, measured over six fills",
      basis=Basis.IN_HOUSE,
    ),
    note=(
      "the part that is well built and still refused. Everything a lab controls has been done "
      "here -- located, measured after processing, benefit quantified, surface smoothed -- and "
      "the refusal is the process, which is why it is structural"
    ),
  ),
  "sensor_bracket_asa": Fixture(
    name="sensor_bracket_asa",
    material=MATERIALS["asa_fdm"],
    built_for=Contact.NONE,
    dimensions=(
      CriticalDimension(
        name="mount_hole_pitch",
        nominal_mm=40.0,
        state=DimensionState.MEASURED,
        measured_mm=39.86,
        measured_after_processing=True,
        instrument="digital caliper, five repeats",
      ),
      CriticalDimension(
        name="face_to_deck_offset",
        nominal_mm=22.0,
        state=DimensionState.MEASURED,
        measured_mm=21.94,
        measured_after_processing=True,
        instrument="height gauge against the deck datum",
      ),
    ),
    positively_located=True,
    benefit=Benefit(
      claim="puts a sensor where no vendor bracket reaches",
      measured="removes one manual repositioning per run, timed at 40 s over eight runs",
      basis=Basis.IN_HOUSE,
    ),
    note="structural, off the fluid path, bolted down, and measured after it came off the bed",
  ),
}


USES: Dict[str, Use] = {
  "deck_bracket": Use(
    name="deck_bracket",
    contact=Contact.NONE,
    robot_registers_to_it=True,
    inside_moving_envelope=True,
    sterilization=Sterilization.NONE,
    note="holds a sensor near the deck; the arm sweeps past it and a taught position depends on it",
  ),
  "plate_nest": Use(
    name="plate_nest",
    contact=Contact.INCIDENTAL,
    robot_registers_to_it=True,
    inside_moving_envelope=True,
    sterilization=Sterilization.IPA_WIPE,
    note="a gripper places a plate into it, so the pocket dimension is the whole function",
  ),
  "shared_reagent_trough": Use(
    name="shared_reagent_trough",
    contact=Contact.SAMPLE_CONTACT,
    robot_registers_to_it=True,
    inside_moving_envelope=True,
    sterilization=Sterilization.AUTOCLAVE_121,
    note="tips enter it and buffer sits in it; the fluid path runs through the printed surface",
  ),
  "culture_insert": Use(
    name="culture_insert",
    contact=Contact.CULTURE_CONTACT,
    robot_registers_to_it=True,
    inside_moving_envelope=True,
    sterilization=Sterilization.AUTOCLAVE_121,
    note="cells and media sit against the printed surface at 37 C for days",
  ),
}


def survey() -> Dict[str, int]:
  """How much of this catalog reaches how far, for the report.

  The number worth looking at is `autoclavable_and_sample_contact`, and it is zero. No
  material here both clears a steam cycle on its glass transition and reaches sample contact
  on its process and materials evidence -- the polymers that survive steam are all made by the
  process that cannot be validated as cleanable, and the one material that reaches sample
  contact is not printed and inherits a datasheet nobody has supplied.
  """
  autoclavable = set(m.name for m in materials_surviving(Sterilization.AUTOCLAVE_121))
  sample = set(m.name for m in materials_reaching(Contact.SAMPLE_CONTACT))
  return {
    "materials": len(MATERIALS),
    "fdm": sum(1 for m in MATERIALS.values() if m.process is Process.FDM),
    "with_tg_on_record": sum(1 for m in MATERIALS.values() if m.tg is not None),
    "validated_thresholds": sum(
      1 for m in MATERIALS.values() if m.tg is not None and m.tg.basis.validated
    ),
    "reaching_sample_contact": len(sample),
    "reaching_culture_contact": len(materials_reaching(Contact.CULTURE_CONTACT)),
    "autoclavable_121": len(autoclavable),
    "autoclavable_and_sample_contact": len(autoclavable & sample),
  }


# -- what this module will not estimate -------------------------------------------


NOT_ESTIMATED: Tuple[Refusal, ...] = (
  Refusal(
    quantity="part service life",
    why=(
      "a lifetime is a distribution fitted to units that failed. This module has one of each "
      "part, no failure history, and a wear mechanism that differs with every geometry, "
      "orientation and duty cycle. A figure computed from a part that has not broken yet is "
      "arithmetic on nothing"
    ),
    what_it_would_take=(
      "failure and censoring times across many parts of the same design, printed on the same "
      "machine, in the same service -- which is a fleet operator's dataset and not one lab's"
    ),
  ),
  Refusal(
    quantity="autoclave cycles survived",
    why=(
      "every specific cycle-count claim located for the high-temperature polymers traced back "
      "to commercial aggregator pages rather than to a study or a manufacturer document, and "
      "the manufacturer documents themselves state repeated steam compatibility without a "
      "number. Repeated cycling is a cumulative creep and hydrolysis problem, so a count is "
      "not an extrapolation from a single cycle"
    ),
    what_it_would_take=(
      "dimensional and mechanical measurement of this part across a cycle series on this "
      "sterilizer, which is a study a lab can run and nobody in this evidence set has"
    ),
  ),
  Refusal(
    quantity="leachable release rate or concentration",
    why=(
      "release depends on the polymer, the additive package that is not disclosed on consumer "
      "filament or in a resin's safety data, the cure state, the surface-area-to-volume ratio "
      "of the specific geometry, the medium, and the time at temperature. Six materials that "
      "started at essentially identical photoinitiator content differed by three orders of "
      "magnitude in extractable initiator after cure"
    ),
    what_it_would_take=(
      "an extraction study on parts from this build in the actual medium at the actual "
      "temperature and duration, analyzed by mass spectrometry"
    ),
  ),
  Refusal(
    quantity="cytotoxicity of a specific printed part",
    why=(
      "results are material, brand and lot specific and do not transfer between spools or "
      "bottles of nominally identical polymer. Two standard assays disagreed by 23 percentage "
      "points on the same material in one study, so even a measured number needs more than one "
      "method behind it"
    ),
    what_it_would_take=(
      "an assay on parts from this build, by more than one method, against the cells that will "
      "actually be exposed -- and for gametes or embryos, a mouse embryo assay, which no resin "
      "located here advertises"
    ),
  ),
  Refusal(
    quantity="shrinkage percentage for a material",
    why=(
      "no filament datasheet checked here publishes one, so every figure in circulation is a "
      "slicer default or a community measurement. Two vendors shipping profiles inside the same "
      "slicer differ by 0.5 percent on the same polymer, and the widely repeated figure of up "
      "to 11 percent for one of them is wrong by more than an order of magnitude against the "
      "compensation that slicer actually applies"
    ),
    what_it_would_take=(
      "printing and measuring a test artifact on this machine with this spool, which is the "
      "measurement that turns a DESIGNED dimension into a MEASURED one and is the whole reason "
      "the distinction exists"
    ),
  ),
  Refusal(
    quantity="sterility assurance level for a porous part",
    why=(
      "surviving the heat and being sterile are different claims. No study located here "
      "cultured the interior of an autoclaved fused-deposition part or ran a biological "
      "indicator inside its void network, so whether steam penetrates that network to a "
      "validated level is unmeasured rather than established either way"
    ),
    what_it_would_take=(
      "biological indicators placed in the worst-case interior geometry, which the medical "
      "device guidance on additive manufacturing already defines as the greatest surface area "
      "and greatest porosity configuration"
    ),
  ),
  Refusal(
    quantity="a probability that an unqualified part is fine",
    why=(
      "there is no population to draw it from and no prior anybody measured. A number of this "
      "shape reaches a report with no author attached to it and is then quoted as though "
      "somebody had computed it"
    ),
    what_it_would_take=(
      "the qualifications `unqualified` already lists, performed rather than estimated. Every "
      "one of them is a piece of work, and none of them is a number this module can supply"
    ),
  ),
)


def refusals() -> Tuple[Refusal, ...]:
  """The estimates this module declines to make, with what each would require.

  Returned rather than only documented so the refusal is checkable. A module that says in its
  docstring that it predicts no lifetimes and then exposes a remaining-life helper has
  documented a discipline it does not have.
  """
  return NOT_ESTIMATED


__all__ = [
  "Assessment",
  "Benefit",
  "Contact",
  "CriticalDimension",
  "DimensionState",
  "FIXTURES",
  "Fitness",
  "Fixture",
  "Flange",
  "MATERIALS",
  "Material",
  "NOT_ESTIMATED",
  "Objection",
  "POST_PROCESS_EVIDENCE",
  "PlateEnvelope",
  "PostProcess",
  "Process",
  "Qualification",
  "ResinQualification",
  "Sterilization",
  "Thermal",
  "USES",
  "Use",
  "fitness",
  "materials_reaching",
  "materials_surviving",
  "plate_envelope",
  "refusals",
  "survey",
  "unqualified",
]
