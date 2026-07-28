# Printed fixtures

How this lab uses a 3D printer, which printer to buy, and the one boundary that decides
everything downstream.

A printer is the cheapest deck hardware a lab will ever own and the easiest to misuse. It
is worth having. It is worth having for a narrower set of parts than most people assume,
and the narrowing is not a policy choice -- it falls out of how the parts are made.

Everything below carries where it came from. Figures are marked `[DS]` when this guide's
research opened the manufacturer datasheet directly, `[DS-2]` when the value came out of a
manufacturer document via search extraction rather than a direct read (one confidence step
lower -- re-verify against the PDF before you act on it), `[EXP]` when it was measured in a
peer-reviewed experiment, `[STD]` when it is clause text from a published standard, and
`[VENDOR]` when it is a vendor claim nobody independent has checked. Numbers with no mark
do not appear. Where a number would be useful and does not exist, this guide says what
measurement would produce it rather than filling the hole.

---

## 1. What printing is for here, and what it is not

**A printed part may hold labware. It may not be labware.**

Fixtures, adapters, nests, risers, guards, jigs, tip-box shims, camera mounts, cable
routing, the wedge in §6 -- parts whose entire job is to put a certified consumable in a
known place and keep it there. That is the permitted set, and it is a large and genuinely
useful set.

Anything a sample, a reagent, or a wash buffer sits in, flows through, or touches is
outside it. Not "discouraged". Outside it.

### The reason is the void network, not a regulation

Fused deposition parts are porous by construction, at every setting, including the one
everybody reaches for first.

- X-ray computed tomography of FDM PLA at **100% infill**, 0.2 mm layers, 210 C nozzle,
  measured porosity **4.05% to 6.32%** across raster angles and extrusion widths. No
  parameter set reached zero or near-zero. The authors fixed infill at 100% specifically
  "to ensure a dense structure" and got 4-6% voids anyway. `[EXP: Wang 2019]`
- The pore size distribution matters more than the percentage. Over **99% of pores were
  below 0.2 mm**; the smallest resolved was 38.8 um and the largest 3.60 mm. Critically,
  they concentrate in two places: between bonded layers, and **between the outer perimeter
  and the infill rasters**. `[EXP: Wang 2019]`

That second location is the whole argument. The void network is not a set of sealed
bubbles buried in the middle of the part. It is connected to the outside surface. Liquid
and organisms have a path in, and there is no line of sight, no mechanical access, and no
flow path to get them back out.

The consequences have been measured directly:

- Immersing FDM ABS parts in medical disinfectants across layer heights of 0.1 / 0.2 / 0.4
  mm and 1 / 2 / 3 perimeters, the authors concluded verbatim that **"no manufacturing
  settings can provide enough sealing against fluid intake."** Thinner layers absorbed
  less; none stopped it. Saturation was reached at 48 h with 1-2 perimeters and 72 h with
  3. `[EXP: Popescu 2021]`
- **Acetone vapor smoothing does not seal the part.** In the same study, 45 minutes of cold
  acetone vapor reduced open porosity, and methylene blue dye still stained the treated
  parts after 30 minutes of immersion. The treatment also degraded mechanical properties.
  Smoothing changes what you can see, not what you can clean. `[EXP: Popescu 2021]`
- Bacteria preferentially colonize the layer lines. Across eight PLA variants plus
  metal-filled, carbon-filled and wood-filled filaments, attachment after 2 h ran to
  6.5x10^6-1.9x10^7 CFU for *E. coli*, 3.6x10^7-6.15x10^7 for *P. aeruginosa*, and
  6.6x10^5-2.16x10^6 for *S. aureus*, with biofilms **thickest between the layers** and
  bacteria filling "the valleys" of the layer structure. `[EXP: Hall 2021]`
- Roughness on an FDM part is wildly anisotropic, which is why a quoted Ra can be
  meaningless. The same study measured Ra of roughly 0.64-1.15 um *along* the layers, and
  **over 100 um** across them. A sub-micron Ra on an FDM part is a measurement of the easy
  direction. `[EXP: Hall 2021]`

FDA's additive-manufacturing guidance does not prohibit any of this -- and reading it
carefully is more useful than a prohibition would be. It says complex additively
manufactured geometries are "expected to increase the difficulty in removing manufacturing
material residues (cleaning) and in sterilization due to the likelihood of increased
surface area", that "sterilization process validation should account for the complex
geometry of your device under worst-case conditions", and that worst case includes the
"combination of largest surface area, greatest porosity". `[STD: FDA 2017 §VI.E]`

The burden is validation, not prohibition. So: **this guide's research located no published
study validating an FDM-printed part as cleanable to any recognized standard** (ANSI/AAMI
ST98, ISO 17664, ISO 15883). That is absence of evidence from a targeted search rather than
proof that none exists -- but it is the crux, and it did not close. Until it does, the
defensible public claim about an FDM part is *porous by construction, not validated as
cleanable*, and this lab treats it accordingly.

### The three things people try instead, and what happened when they were tested

**"Autoclave it."** Surviving a cycle and being clean are different claims. Steam kills
organisms it reaches; it does not remove protein, endotoxin, nucleic acid, or chemical
residue, and it fixes protein onto surfaces. Whether steam penetrates the interior void
network of an FDM part at all is unvalidated -- no study located cultured the interior of
an autoclaved FDM part or ran biological indicators inside the voids. A part can be sterile
and still cross-contaminate the next sample. See §3 for what autoclaving does to the
dimensions, which is a separate disaster.

**"Coat it."** Vacuum epoxy infiltration is a vendor claim (airtight and watertight to 65
psi with one specific two-part resin) with no peer-reviewed validation of the coated part
as cleanable, and the same vendor sources concede that internal channels cannot be reached.
`[VENDOR]` A coating also introduces a second, uncharacterized contact material with its
own cure chemistry and leachables, and can trap existing bioburden underneath rather than
removing it. Barrier coatings do have one documented success: a 10 um parylene layer
restored a cytotoxic resin to 93%/85% cell viability -- **and it detached after 5-6 autoclave
cycles**. `[EXP: Kress 2020]` A coated part in a reusable workflow needs a defined
replacement interval, not indefinite reuse.

**"Use resin instead, it's smooth."** Smoothness is not the problem, chemistry is, and
resin's chemistry is worse. Two Formlabs resins **both marketed as ISO-certified
biocompatible dental materials** were tested in a mouse oocyte maturation assay. Dental LT
Clear caused complete oocyte degeneration in every condition tested, including after UV
post-cure and after oxygen-plasma treatment -- 37.4 +/- 21.3% degenerate at 1 hour, all of
them by 16 hours. Dental SG untreated did the same; plasma treatment rescued gross survival
(75.3 +/- 10.5% reaching MII against a 74.3% polystyrene control) while leaving **57.0 +/-
37.2% with abnormal chromosome morphology against 19.4 +/- 17.3% on control plastic**.
`[EXP: Rogers 2021]`

Two things in that result generalize. First, a material can pass a survival endpoint and be
genotoxic underneath it, so validating on viability alone misses a whole class of harm.
Second, the causative leachate was identified as **Tinuvin 292, a hindered amine light
stabilizer**, at roughly 50 ug/mL in the medium -- not a monomer and not a photoinitiator.
Post-curing cannot consume it, because it is not a polymerizable species. The standard
"just post-cure it harder" mental model does not cover the thing that actually did the
damage.

Certification also attaches to a workflow, not to a bottle. Formlabs' BioMed Clear
certification data are tied to a named printer, a 100 um layer height, a 20-minute wash in
**99%** isopropanol, and a 60-minute cure at 60 C. `[DS]` A part made on a different
printer, washed in reused hardware-store 91% IPA, or cured in a nail lamp is not the
article that was tested. And its ISO 10993-3 claim is "not mutagenic" only -- reproductive
and developmental toxicity are endpoints the standard's own risk logic never triggers for a
benchtop lab fixture, which is exactly the gap the oocyte study fell into.

For anything that would contact gametes or embryos, the applicable qualification is the
Mouse Embryo Assay on the actual finished parts from the actual build (1-cell format,
>=80% reaching expanded blastocyst at 96 h, per FDA guidance), not ISO 10993-5 and not a
vendor certificate. `[STD]` This guide's research found no commercially available
photopolymer resin advertising MEA testing.

### The line, written as this repo writes lines

Not shipped code -- nothing imports this. It is the vocabulary the rest of the guide uses,
in the shape the repo uses for boundaries that have to hold.

```python
class Contact(str, Enum):
  """How close a printed part is allowed to get to material. Ordered outward to inward.

  The load-bearing value is SAMPLE, and excluding it is a claim about the process rather
  than about any one filament. An FDM part's void network connects to its outer surface
  (Wang 2019), no print setting seals it (Popescu 2021), and nothing published validates
  such a part as cleanable. A better printer does not move this line. A more expensive
  polymer does not move it either -- PEEK survives the autoclave and is just as porous
  going in.
  """

  NONE = "none"  # structural; nowhere near the fluid path
  ADJACENT = "adjacent"  # holds certified labware; never wetted in normal operation
  SPLASH = "splash"  # a spill can reach it; must be wipeable and cheap to replace
  SAMPLE = "sample"  # sample, reagent, or buffer touches the printed surface

  @property
  def permitted_for_printed_parts(self) -> bool:
    return self is not Contact.SAMPLE
```

A printed nest holding a certified microplate is `ADJACENT` and fine. The same nest with a
well milled into it so a sample can sit directly in the print is `SAMPLE` and is not a
fixture, it is unvalidated labware wearing a fixture's name.

One more trap worth naming before it costs somebody a plate: **dimensional conformity is
not fitness for contact.** A part can hit every dimension in ANSI/SLAS 1 through 6 and be
entirely unfit to touch a sample. None of those standards says anything about material,
leachables, extractables, cytotoxicity, sterility, or nuclease-free status -- each one's
scope is confined to the single geometric feature in its title. `[STD]` "SBS compliant" is a
statement about a footprint.

---

## 2. Buying the printer

### The recommendation

**Buy an enclosed machine with an actively heated chamber and a hardened steel nozzle.**
Concretely: a **Bambu Lab X2D**, list **$649** (captured 2026-07-28). `[VENDOR: official
store spec table]`

Confirmed specification, from the manufacturer's own spec table:

| | X2D |
| --- | --- |
| build volume | 256 x 256 x 260 mm main nozzle; 235.5 x 256 x 256 mm dual |
| chamber | enclosed, **Active Chamber Heating supported, max 65 C** |
| nozzle | hardened steel, max **300 C** |
| bed | max **120 C** |
| filtration | G3 pre-filter + H12 HEPA + granulated coconut shell activated carbon |
| price | from $649.00 (captured 2026-07-28) |

The reasoning, axis by axis.

**Enclosed and actively heated is the axis that decides what you can print at all.** Every
material worth using for a load-bearing deck fixture -- ABS, ASA, PC -- warps at the sizes
deck fixtures actually are, and warp is driven by the maximum in-plane dimension (§5). A
microplate footprint is 127.76 x 85.48 mm `[STD: SLAS 1 §4.1.1.1]` before you add walls,
so a nest is already a large flat part on day one. A passive enclosure is a box that traps
some waste heat; an actively heated chamber is a controlled variable. Everything else on
the spec sheet is negotiable and this is not.

**Nozzle temperature is co-limiting, not decisive on its own.** This is the mistake the
spec tables invite. A Prusa CORE One+ with the announced HT hotend reaches 400 C -- higher
than the H2D's 350 C -- while running a 55 C chamber against the H2D's 65 C, which makes it
the *worse* machine for a large warp-prone PC part. Read chamber, bed, enclosure and nozzle
together or you will buy the wrong number.

**Hardened steel over brass, and this one is a contamination argument rather than a wear
argument.** The Prusa CORE One+ ships a brass nozzle (`High-flow Prusa Nozzle brass CHT -
0.4 mm`); brass alloys commonly contain lead. The X2D, P2S, H2D and QIDI Plus4 all ship
hardened steel. For a part that will sit on a deck next to open labware, that distinction
matters more than any temperature spec on the page.

**Filtration is an operator-exposure control and should be read as exactly that.** ABS, ASA
and PC printing emits styrene and ultrafine particles. HEPA and activated carbon reduce
what the person in the room breathes. They do **not** make the chamber a clean environment
and they are not a sterility control -- the parts are printed in ordinary room air and
carry bioburden from manufacture, which is precisely why FDA's guidance treats the
cleanliness of build material and build environment as the control for interiors that
cannot be flushed. Site the printer somewhere samples are not open, whatever filters it has.

### Alternatives, with the tradeoff stated

| machine | chamber | nozzle | bed | build volume | price (captured 2026-07-28) | why you would pick it |
| --- | --- | --- | --- | --- | --- | --- |
| **Bambu X2D** | enclosed, **active 65 C** | hardened steel, 300 C | 120 C | 256 x 256 x 260 | from $649 | the default: heated chamber, steel nozzle, HEPA + carbon, lowest verified price in the class |
| **QIDI Plus4** | enclosed, **active 65 C** (PTC + circulation fan) | 370 C | 120 C | 305 x 305 x 280 | $649 sale / **$799 list** | biggest envelope and highest nozzle ceiling of the affordable set. Pick it when a fixture will not fit in 256 mm |
| **Bambu H2D** | enclosed, **active 65 C** | hardened steel, 350 C | 120 C | 325 x 320 x 325 single-nozzle | $1,549 sale / **$1,749 list** | more envelope and 350 C. Note 1320 W at 110 V -- a real circuit-loading question on a shared bench -- and a 10-30 C stated working range that rules out some siting |
| **Prusa CORE One+** | enclosed, **active 55 C** | brass CHT 0.4, 290 C stock | 120 C | 250 x 220 x 270 | see price note | pick it when repairability dominates. Coolest chamber of the enclosed set and a brass nozzle out of the box |
| **Bambu P1S / P2S** | enclosed, **passive** | 300 C | 100 / 110 C | 256 x 256 x 256 | P1S $399 sale / $699 list; P2S from $549 | cheapest way into an enclosure. Buy only if PLA and PETG are genuinely all you will ever print |
| **Prusa MK4S** | **not enclosed** (add-on) | 290 C | 120 C | 250 x 210 x 220 | see price note | do not buy for this job without the enclosure. ABS, ASA and PA are conditioned on the add-on in Prusa's own material list |
| **Intamsys Funmat HT** | enclosed, **active 90 C** | 450 C | 160 C | 260 x 260 x 260 | quote only | the only machine here in PEEK/PEKK territory. See the PEI caution below |

Four cautions that will otherwise cost you money.

**The Bambu X1C is end-of-life.** Manufacturing and active sales ended 2026-03-31; firmware
feature updates run to 2027-05-31, security patches to 2029-05-31, spare parts and support
to 2031-03-31. The product page redirects to the general listing. It is still the machine
most third-party guides recommend. Do not buy one new, and treat every X1C figure you find
online as unverifiable legacy -- this guide could not retrieve a single X1C specification
from a Bambu-controlled source.

**Bambu's own site contradicts itself on the P series.** The store's buying-guide prose says
"an enclosed chamber with active heating (P series or X2D)". The P2S product page's own FAQ
says verbatim: "The P2S does not have an active chamber heating function." The P1S spec
table has no chamber-heating row at all, only a regulator fan and a carbon filter. The FAQ
and the spec tables are right and the buying guide is wrong. The marketing phrase "50 C
Chamber Ready" carries no test conditions, no tolerance and no ambient reference, and Bambu
publishes no chamber temperature for the P1S at all -- so any specific passive chamber
number, including one you might be tempted to write into a design note, would be invented.

**"PEI plate" is not "prints PEI", and this collision will produce a real error.** On Bambu
and Prusa pages, "Textured PEI Plate" and "PEI spring steel sheet" name the polyetherimide
*build surface* the part is printed on. PEI/ULTEM as a printable engineering polymer needs
roughly 360-420 C at the nozzle plus a hot chamber. **No consumer or prosumer machine here
reaches it.** Confirmed chamber ceilings: P1S none (passive), P2S none (passive), X2D 65 C,
H2D 65 C, H2C 65 C, MK4S none as standard, CORE One+ 55 C, CORE One L 60 C, QIDI Plus4
65 C. Only the Funmat-class machine (90 C chamber, 450 C nozzle) is in that territory --
and Intamsys' own material list on its product page names PEEK, PEKK, PC, PPS, PPA and PA
variants and **does not name PEI or ULTEM**. Reseller copy asserts ULTEM capability.
Reseller copy is not a specification.

**The Prusa HT hotend is announced, not in hand.** The CORE One+ page labels it "Up to
400 C (Coming Soon)" and the product page says "Estimated to ship this summer" at $184.26.
Do not build a purchase case on a 400 C capability nobody has yet received.

### Price note, and why this guide will not print a total

Prices captured 2026-07-28, and several are promotional -- the P1S at $399 against a $699
list is a 43% discount, and Bambu advertises 30-day price protection, which implies active
price movement. Use list prices with the capture date. Sale prices in a document are stale
within weeks and read as a specification later.

Prusa's figures did not resolve cleanly and are reported both ways rather than averaged.
Prusa's own comparison table gives assembled prices of **CORE One+ from $1,299**, **MK4S
from $999**, **CORE One L from $1,799**. A text render of the same pages returned CORE One+
assembled **$1,202.78** / kit **$925**, and MK4S assembled **$925** / kit **$657.40**.
Whether the lower set is a live promotion, a VAT-excluded view, or a currency artifact could
not be determined. Do not pick one and do not split the difference.

Also check voltage: the units above are the 100-120 VAC US variants, and Bambu explicitly
warns to buy the version matching your region.

**The first-year requisition.** The printer is the only line on it this guide can price
honestly, and it is not the line that decides whether you get qualified parts.

```
  printer                 $649 list (X2D) / $799 list (QIDI Plus4)   [sourced, 2026-07-28]
  filament                by the kilogram, several materials         PRICE LOCALLY
  spare hardened nozzles  consumable; buy before you need one        PRICE LOCALLY
  drybox + desiccant      not optional -- see below                  PRICE LOCALLY
  metrology               calipers at minimum; NOT OPTIONAL          PRICE LOCALLY
  spare build sheet       consumable                                 PRICE LOCALLY
```

This guide does not publish a first-year total, and the reason is the same rule the rest of
the repo runs on: every non-printer figure it could have written is one it did not verify,
and an unmeasured number that reaches a document becomes a budget nobody measured. Price
those five lines on the day you order and put the **sum** on the requisition. What this
guide will assert is which lines cannot be dropped:

- **Metrology is not optional and it is not an accessory.** The qualification ladder in §4
  has a MEASURED rung, and a lab with a printer and no measuring instrument physically
  cannot reach it. It can only produce objects. Calipers are the floor; gauge pins or
  blocks for the features that actually register are better.
- **The drybox is not optional either, and the datasheets say why.** Saturation water
  absorption: PETG 0.51% max `[DS]`, PEEK 0.45% at 23 C and 0.55% at 100 C `[DS]`, ULTEM
  1010 1.25% `[DS]`. Nylon is worse -- strongly hygroscopic, and moisture both swells the
  part and plasticizes the polymer, dropping its Tg. (This guide's research did not obtain a
  numeric moisture-uptake figure for a PA filament, so the mechanism is stated and the
  number is not.) Wet filament prints badly and prints *differently* on different days,
  which quietly destroys the repeatability that §5 depends on.

### The two axes this guide could not source

The brief for this section named four decisive axes. Two of them -- **reliability and the
time cost of fussing**, and **repairability** -- have no verifiable public numbers, and the
recommendation above rests only on the two that do. Saying so is more useful than
laundering a forum consensus into a specification.

What would settle them:

- **Fuss.** Your own maintenance log. Hours of intervention per successful part over the
  first fifty parts, recorded as it happens. Nobody else's log transfers, because it is
  dominated by the material mix and the part geometry you personally print.
- **Repairability.** Two things a buyer can check before ordering, both of which are vendor
  behavior rather than opinion: does the vendor publish spare-part availability with dates,
  and does it publish part drawings and firmware. Both vendors here have a concrete data
  point on record. Bambu published a dated end-of-support schedule for the X1 series with
  spare parts guaranteed to 2031-03-31. Prusa offers a **$10** upgrade kit to take a CORE
  One to CORE One+ spec, or the upgrade parts as files you print yourself. Weigh those as
  evidence of intent; neither is a reliability measurement.

---

## 3. Materials

Read the polymer-class column last. **Grade names are not material specifications.**
"ULTEM" spans 9085 at Tg 177 C and 1010 at Tg 210-217 C -- a 33-40 C spread under one trade
name. "PC" spans unfilled resin near Tg 147 C and a printable PC Blend at HDT 93 C under
1.8 MPa. "PP" spans homopolymer and a copolymer melting at 137 C. Check the specific
product's datasheet, every time.

### The gate is Tg, not HDT

Heat deflection temperature measures 0.25 mm of deflection in a standard bar under an
applied load of 0.45 or 1.8 MPa. An autoclaved fixture usually carries no external load, so
the natural inference is that it can safely exceed its HDT. **That inference fails for
printed parts specifically.** An FDM part contains frozen-in extrusion stresses that relax
the moment the polymer passes its glass transition, so it shrinks and warps with zero load
applied. Use Tg as the conservative gate. This is why PLA was observed warping from
approximately 70 C in a curved-beam geometry `[EXP: Chiscop 2025]` despite HDT figures near
57 C being quoted for it.

Two further corrections to how these numbers get read. **Orientation changes the answer** --
one manufacturer's TMA data on printed ULTEM 9085 shows dimensional reversal beginning at
~175.9 C upright versus ~193.4 C flat, a 17 C spread from print orientation alone on one
material. `[DS]` And **fillers inflate HDT without raising the polymer's temperature limit**
-- carbon-fiber nylons show HDT sitting 100-140 C above Tg because the fiber and the
crystalline phase carry the load, not because the matrix became more thermally stable.
Chemical resistance, hydrolysis behavior and creep still track the base polymer.

### The table

Autoclave columns compare each polymer's Tg against the cycle. 121 C cycles typically run
15-30 min; 132-134 C cycles typically 3-4 min. Exposure time matters for creep, so a
pass/fail is only meaningful next to a cycle.

| material | Tg | HDT (load, method) | 121 C | 134 C | chemical and process notes | contact |
| --- | --- | --- | --- | --- | --- | --- |
| **PLA** | 54-61 C `[DS]` across four grades from one maker (Basic 60, Matte 61, Translucent 54, Tough+ 61) | 52-58 C @1.8 MPa; 57-61 C @0.45 MPa, ISO 75 `[DS]` | **FAIL** | **FAIL** | Ester backbone -- hydrolyzes in wet heat. Warps from ~70 C in curved geometries `[EXP]`. Do not publish a single PLA figure; the 7 C spread across one maker's own grades is the honest measure of what colorant packages do | `NONE`, `ADJACENT` |
| **PETG** | 69-77 C (69 C one maker `[DS]`, 71.24 C another `[DS]`, 77.4 C a third `[DS-2]`) | 68 C @1.8, 71 C @0.45 `[DS]`; 65 C @1.8, 69 C @0.45 `[DS]`; 76.2 +/- 0.8 C @0.455 `[DS-2]` | **FAIL** | **FAIL** | ~8 C maker-to-maker gap on nominally the same polymer. Ester backbone, hydrolysis-sensitive. Max water absorption 0.51% `[DS]` | `NONE`, `ADJACENT`, `SPLASH` |
| **ABS** | ~105 C (105 C `[DS]`, 105.2 C `[DS-2]`); one maker lists Tg as "N/A" | 84-104 C depending entirely on grade: 104.4 C @66 psi industrial `[DS-2]` vs 84 C @1.8 MPa desktop `[DS-2]` vs 95 C @0.45 MPa `[DS]` | **FAIL** | **FAIL** | The ~20 C industrial-vs-desktop HDT gap is real and decides nothing good. An ABS housing was independently observed to deform at 121 C "to the extent that it can no longer be used" `[EXP]`. Note the maker of a biocompatible medical ABS claims gamma and EtO sterilization and **not** steam | `NONE`, `ADJACENT`, `SPLASH` |
| **ASA** | 98 C `[DS]`; ~104 C `[DS-2]`; a third datasheet gives none | 86 C @1.8, 93 C @0.45 `[DS]`; 100 C @1.8, 103 C @0.45 `[DS]`; 98.2/103 C @264/66 psi `[DS-2]` | **FAIL** | **FAIL** | The practical choice for deck fixtures that see UV or long service. Better outdoor stability than ABS, similar thermal ceiling | `NONE`, `ADJACENT`, `SPLASH` |
| **PC (printable blend)** | not given on the blend datasheet | **113 C @0.45, 93 C @1.8** `[DS]` | **MARGINAL** | **FAIL** | This is the row that misleads. A guide quoting "PC: HDT 130 C" is about 37 C optimistic for the blend somebody will actually buy | `NONE`, `ADJACENT`, `SPLASH` |
| **PC (unfilled resin)** | ~147 C `[DS-2]` | ~124-126 C @1.80, ISO 75 `[DS-2]`; Vicat B/50 ~147 C | pass on thermal grounds | pass on thermal grounds | Grade-specific figures must come from the specific grade sheet -- the source pages for these returned 404/500. Carbonate linkages hydrolyze in wet heat; the molecular-weight-loss and crazing mechanism is well known in device practice and this guide could not source it properly, so it is flagged rather than asserted | `NONE`, `ADJACENT` |
| **PP** | not on any filament datasheet reached. PP's Tg is below room temperature but no manufacturer source confirmed it -- leave it out rather than guess | none published on the filament TDS | **MARGINAL** | **DO NOT** | The single most dangerous row. One PP copolymer filament has **Tm 137 C** `[DS]` -- a 134 C cycle runs 3 C below its melting point. Homopolymer melts ~160-165 C. Do not carry the reputation of molded PP labware, which is routinely autoclaved, onto PP filament without checking that grade's Tm | `NONE`, `ADJACENT` |
| **PA / nylon (CF-filled)** | 70 C (PAHT-CF), 85 C (PPA-CF) `[DS-2]` | 170 C @1.8 / 194 C @0.45 (PAHT-CF); 196/227 C (PPA-CF) `[DS-2]` | see notes | see notes | **The HDT column is a trap here.** It sits 100-140 C above Tg because carbon fiber carries the load. Separately, PA is strongly hygroscopic and a steam cycle drives it toward saturation -- moisture swells the part *and* plasticizes the polymer, dropping unfilled nylon's Tg substantially. It will move even if it never softens | `NONE`, `ADJACENT` |
| **PEI / ULTEM 9085** | **177.3 C** `[DS]` | printed 178.2 C (XY) / 178.4 C (XZ) @66 psi; 170.2 / 172.6 @264 psi `[DS]` | pass | pass | Not printable on any machine in §2. TMA reversal at ~175.9 C upright vs ~193.4 C flat -- print orientation, not polymer, sets deformation onset | `NONE`, `ADJACENT` |
| **PEI / ULTEM 1010** | **210 C** printed `[DS-2]` / **217 C** molded `[DS]` | 200 C @0.45, 190 C @1.8 (ISO 75) `[DS]`; 215/210 C @66/264 psi (ASTM D648) `[DS-2]` | pass | pass | The ISO-versus-ASTM gap of 15-20 C on nominally identical material is why every figure here carries its method. Water absorption 1.25% at saturation `[DS]` | `NONE`, `ADJACENT` |
| **PEEK** | onset **143 C**, midpoint 150 C `[DS]` | DTUL **152 C** @1.8 MPa unannealed `[DS]`; Tm 343 C | pass | pass, thinly | Margin at 134 C is 9 C on Tg onset. It passes because the **crystalline phase** carries load above Tg -- and as-printed PEEK from a machine without adequate chamber temperature can be substantially amorphous, in which case it is not the material the datasheet describes. The maker's "suitable for steam sterilisation" statement covers injection-molded granules, not printed parts | `NONE`, `ADJACENT` |

### What the autoclave column does not mean

**"Survives the cycle" is a much weaker claim than "holds its dimensions."** The only
measured dimensional data this guide's research located for any polymer on that table is
for annealed PLA at 134 C for 60 min: after annealing at 120 C for 60 min encapsulated in
silicone, a hollow cylinder moved +0.47% on outer and inner diameter and +0.18% on height,
and a rectangular bar moved +0.64% height, **-1.43% width**, +0.12% length. Salt-encapsulated
annealing was markedly worse -- up to -2.50% on inner diameter and +2.10% on bar height.
`[EXP: Chiscop 2025]`

Read that correctly. It supports *annealed PLA can survive a cycle*. It does not support
*PLA autoclaves without dimensional change* -- the best case still moved 0.2-1.4%, and the
movement is anisotropic, with Z growing while XY shrinks. **If a fixture's function depends
on a tolerance tighter than roughly 1%, no datasheet Tg or HDT will tell you whether it
survives.** That has to be measured on the part.

The same paper explicitly did not measure crystallinity, porosity, cleanability or
sterility. It establishes thermal survival and nothing else.

### Four more things not to write down

- **No cycle count.** Every specific claim located about how many autoclave cycles PEEK or
  PEI survives -- "1,000+ cycles", "<0.5% over 3000 cycles", "+/-0.2% for 50+ cycles" --
  traced to content-marketing or AI-generated aggregator pages, not to a study or a
  manufacturer document. Repeated cycling is a cumulative creep-and-hydrolysis problem. The
  honest statement is that per-cycle data exists and multi-cycle data was not located.
- **Pressurized cycles need vented geometry.** A 134 C cycle runs at roughly 2.1 bar. Sealed
  or trapped-volume prints -- closed hollows, capped tubes, any unvented internal cavity --
  can deform or collapse from the pressure differential, especially during exhaust,
  regardless of the polymer's thermal capability.
- **Datasheet values describe molded or specially-printed test bars, not your part.** Both
  the PEEK and the ULTEM 1010 figures above describe injection-molded material and carry
  explicit disclaimers that real properties depend on geometry and processing.
- **Exclude filled, metal-filled, wood-filled and antimicrobial filaments** from anything
  near labware. They are worse on every axis that matters here: higher roughness,
  filler-matrix interfaces, additional leachable species. Copper and silver antimicrobial
  filaments are not a cleanability control -- they leach metal ions, which is a direct
  problem for cell culture and for any assay sensitive to divalent cations, and bacteria
  attached to metal-filled PLA at the same 10^6-10^7 CFU order as plain PLA. `[EXP: Hall
  2021]`

One genuinely favorable finding, recorded because omitting it would be its own dishonesty:
plain FDM thermoplastics are generally **not** cytotoxic in cell contact. ABS, PETG, PLA and
Nylon 12 did not reduce human iPSC viability against control in one study, while two SLA
resins reduced it by roughly 60% and 90%. `[EXP]` That is real, and it does not license
sample contact, because cytotoxicity was never the reason for the boundary in §1 -- porosity
was. It is also not uniform: a preprint reports significant cytotoxicity for PETG and PC,
and colorants, plasticizers and processing aids differ between spools of nominally identical
polymer and are not disclosed on consumer filament.

---

## 4. The qualification ladder

The repo already refuses to let an instrument's reputation transfer to a step: a federated
step is supervised only when a run card for *that step* has been proven, and an
unbenchmarked operation is untrusted by default. A printed part gets the same treatment,
for the same reason.

```python
class Rung(str, Enum):
  """How far a printed fixture has been qualified. Ordered weakest to strongest.

  NO RUNG IMPLIES THE ONE ABOVE IT. That is the whole content of this enum and it is not
  a formality -- each rung tests a different physical claim, and the claims are
  independent. A model that compiles says nothing about a print. A print says nothing
  about its dimensions, because nobody measured them. Dimensions say nothing about fit,
  because the plate has tolerances of its own. Fit says nothing about the arm.

  The last of those is the one that hurts, so `qualified_for_arm` is a property rather
  than a comment. A hand is compliant and adaptive: it feels a part binding and stops. An
  arm is neither. It goes to a commanded position at a commanded force and finds out what
  is there afterwards. A part that fits by hand has been qualified for a hand.
  """

  MODELED = "modeled"  # the source compiles and renders; no object exists
  PRINTED = "printed"  # an object exists; nobody has measured it
  MEASURED = "measured"  # the registering features were measured, at the working temperature
  FITTED = "fitted"  # it seats on the deck with the real plate, robot powered down
  DRY_RUN = "dry_run"  # the arm ran the motion against it at reduced speed, no material
  IN_USE = "in_use"  # it has run with material, and the run was recorded

  @property
  def qualified_for_arm(self) -> bool:
    return self in (Rung.DRY_RUN, Rung.IN_USE)

  @property
  def measured(self) -> bool:
    """False for MODELED and PRINTED. An unmeasured part is untrusted, matching how an
    unbenchmarked operation is untrusted: the absence of a measurement is not evidence
    of adequacy."""
    return self is not Rung.MODELED and self is not Rung.PRINTED
```

### What each rung actually requires

**MODELED.** The `.scad` compiles. Record the parameter values, because the next print will
not be from the same source unless you do.

**PRINTED.** An object exists. This is the rung everybody stops at, and it carries no
information about the object beyond "the printer did not fail".

**MEASURED.** The features that *register* -- the ones that decide where the plate ends up
-- were measured with a real instrument and written down against the model's nominals. Four
requirements that are easy to skip:

- *Measure at the temperature the part will work at.* SLAS dimensions are specified at
  20 C `[STD: SLAS 1-4 §1.2]`, and ANSI/SLAS 6's test method at 25 C +/- 2 C -- so there is
  not even one temperature across the standard family. Printed polymers have far higher
  thermal expansion and lower creep resistance than molded PP or PS. A part in tolerance on
  the bench can be out of tolerance at 37 C in an incubator.
- *Do not trust the bottom face.* The first layer is squished against the bed and comes out
  wider than modeled -- PrusaSlicer ships `elefant_foot_compensation = 0.2` in several of
  its own profiles, and Prusa's documentation puts values around 0.2 mm as typical for a
  0.4 mm nozzle. The bottom few layers are the least dimensionally trustworthy region of
  the part, and they are also the region that seats on the deck. Put registration datums
  somewhere else, or account for it explicitly.
- *A calibration cube proves nothing about a nest.* Tolerance scales with length in every
  formulation anyone publishes. Desktop FDM is quoted at **+/-0.5% with a +/-0.5 mm floor**,
  industrial FDM at +/-0.15% with a +/-0.2 mm floor. `[VENDOR: Protolabs Network]` An
  industrial machine's own spec sheet reads "+/- .200 mm (.008 in), or +/- .002 mm/mm,
  whichever is greater" -- a +/-0.2 mm floor rising to +/-0.4 mm across a 200 mm feature.
  `[DS]` Express any tolerance you claim as +/-(floor) or +/-(percent x dimension),
  whichever is larger, and state the reference length.
- *Exploit repeatability, which is far better than accuracy.* One study of 35 printed
  cuboids reported repeatability standard deviations in the few-hundredths-of-a-millimeter
  range. `[EXP, low confidence -- retrieved via search snippet; the full text was
  unreachable, so treat the order of magnitude as indicative and the digits as unverified]`
  The practical consequence is real either way: an FDM printer reproduces its own error
  consistently, so **measure and compensate** works even when out-of-the-box accuracy is
  5-10x worse than repeatability. That loop is the only route to a part that registers
  properly, and it needs the calipers from §2.

**FITTED.** The real plate -- the one from the lot you will actually run, not a
dimensionally different one from a different vendor -- seats in the part, on the deck, in
its real position, with the robot powered down. Check it seats fully, releases without
binding, and does not rock. Then check it with the plate at working mass, full of liquid,
because an empty plate and a loaded plate sit differently.

**DRY_RUN.** The arm executes the real motion against the part at reduced speed, with no
material anywhere. This is a distinct rung because everything the hand did for you in
FITTED is now absent: approach vector, clearance to the gripper jaw or the pipetting head,
what happens when the plate is a half-millimeter off nominal, whether the part moves when
the arm nudges it. Reduced speed exists so a collision is a scrape rather than a repair.

**IN_USE.** It has run with material and the run was recorded. Recorded means an event with
an attestation, in the sense the repo already uses: an instrument confirmed it, or a human
witnessed it. Software having sent the command is `asserted` and is a log line about intent.

### The refusal

Do not report a part at a rung it has not reached, and in particular do not let FITTED read
as DRY_RUN. **A part that fits by hand has not been qualified for an arm.** The failure mode
in §5 that puts an instrument at risk -- a part shifting mid-run -- is invisible from every
rung below DRY_RUN, and a printed fixture is exactly the kind of hardware that gets promoted
straight from "I fitted it, looks great" to a production run.

---

## 5. The failure modes

Six concrete ways a printed fixture fails, each with what it does and what would catch it.

### Warp on a large flat part, so the base rocks

Warp is driven by the maximum in-plane dimension and by the temperature gradient during the
build -- non-uniform cooling and differential volumetric shrinkage of the extruded polymer,
plus poor bed adhesion. `[VENDOR: Protolabs Network; EXP: warpage study]` A microplate
footprint is 127.76 x 85.48 mm before you add anything `[STD]`, so a nest is a large flat
part by default.

The magnitude is millimeters, not microns. One study printing ABS with the bed at 110 C
reported warpage "around 3.7 mm" before optimization and "around 0.8 mm after improvement".
`[EXP]` **Those numbers cannot be scaled to your part** -- the retrievable text does not
state the specimen dimensions or the measurement instrument -- so use them for the order of
magnitude and nothing else. A general "warp per 100 mm of length" rule does not exist in any
dataset this guide's research located, and anything of that form would be an estimate
dressed as a finding.

There is also a floor you cannot design under: **a printed plate cannot be flatter than the
bed it was printed on.** Mesh bed leveling conforms the first layer *to* the bed's shape
rather than correcting it, so bed non-flatness transfers into the part's bottom face. One
measurement project reports peak-to-valley bed variation of a quarter of a millimeter --
more than two layers at 0.1 mm. `[single anecdote, printer unspecified]` No manufacturer bed
flatness specification for the machines in §2 could be confirmed; a "0.10 mm" figure
circulating for one of them traced to forum discussion, not to a spec sheet.

*What it does:* the base rocks, so the plate's true position depends on which corner is
loaded. *Catches it:* MEASURED, if you measure flatness rather than only length and width;
FITTED, if you check for rock with the plate at working mass. Nothing below that.
*Mitigations that are actually supported:* heated bed, rafts, radii at sharp corners
`[VENDOR]`; lower-shrinkage material (see below); and designing the part so the registering
surface is not a large unbroken flat.

### Shrinkage moves a registration feature out of tolerance

Filament manufacturers largely **do not publish shrinkage**. This guide's research opened
three technical datasheets -- a PETG, an ASA, and an ABS -- and none of them lists a
shrinkage figure at all. `[DS]` So every per-material shrinkage percentage circulating
online is a slicer default or a community measurement, not a manufacturer specification.

What can be sourced is what the slicers ship. In one slicer's repository, one filament
vendor's profiles set compensation implying measured shrinkage of **PLA 0.05%, PETG 0.15%,
ABS 0.513%, ASA 0.513%, PC-CF 0.15%**. In the *same repository*, a different vendor ships
100% -- zero compensation -- for PLA, PETG, ABS and ASA, and 99.8% for PC-CF. Two vendors,
one slicer, a 0.5% disagreement on ABS. `[shipped code, read directly]` Independent
knowledge-base material puts FDM shrinkage in the **0.2-1%** range `[VENDOR]`, consistent at
the low end.

The arithmetic is what makes this a design problem rather than a curiosity. Across the
127.76 mm long dimension of a plate footprint:

```
  PLA   0.05%  x 127.76 mm  =  0.06 mm
  PETG  0.15%  x 127.76 mm  =  0.19 mm
  ABS   0.513% x 127.76 mm  =  0.66 mm
```

That last figure is larger than the entire SLAS 1 corner-zone tolerance band of +/-0.25 mm.
An ABS nest modeled at nominal, printed without shrink compensation, is out of the plate
standard's tolerance before the plate arrives.

Reject two figures you will find repeated everywhere: "ABS shrinks up to 11%" and "PLA 0.2%
to 3%". Neither is supported by any manufacturer datasheet or slicer default located, and
11% is off by more than an order of magnitude from the 0.513% a real shipped profile
compensates for. They appear to conflate free volumetric contraction and injection-molding
shrink with printed-part shrink.

*What it does:* a pin, slot or shoulder ends up outside the clearance you designed, and the
plate either binds or floats. *Catches it:* MEASURED, on the registering feature
specifically -- overall dimensions can be right while a feature is not. *Mitigation:*
measure and compensate, exploiting repeatability, and re-measure after any filament, color
or lot change, because the additive package moves the number.

### The part shifts mid-run and causes a crash

A fixture that is friction-held or double-sided-taped will eventually move: an arm nudge,
a thermal cycle, a wipe-down with solvent. When it moves, the deck position the robot was
taught no longer describes where the plate is.

*What it does:* severity is **mechanical** -- the instrument itself is at risk, which puts
it in a different class from every other failure here. It is also **silent by construction**:
nothing in a printed part reports its own position, and the arm has no way to know the
fixture is not where it was taught. The first evidence is the collision.

*Catches it:* DRY_RUN catches a fixture that moves under arm contact, which is exactly why
that rung exists. Nothing else does, and in particular a camera does not, unless a validated
check with a known pose and measured sensitivity exists -- which in this workcell it does
not, for any condition.

*Mitigation is design, not procedure:* positively locate the fixture into existing deck
features -- bolt it, key it, capture it between rails. A registration that depends on
somebody putting it back in the same place is not a registration. And re-run DRY_RUN after
any event that could have moved it.

### Static

Printed thermoplastics are insulators. Charge builds and then does things you did not plan:
lightweight labware sticks or jumps, tips cling, powders migrate, and on a bad day an
electrostatic discharge reaches something that minds.

**This guide has no measured figure for it and will not invent one.** What would produce one
is a surface and volume resistivity measurement, per a named test method, **on the printed
part in its printed orientation** rather than on the pellet -- and consumer filament
datasheets do not carry that value.

Two things are worth saying without a number. Humidity control changes the behavior
substantially, and the drybox you bought in §2 is already half of that story. And the obvious
fix -- carbon-filled "ESD-safe" filament -- is excluded here for the reasons in §3: filled
grades bring higher roughness, filler-matrix interfaces and extra leachable species to a
part that sits next to open labware.

### A lip too shallow to retain the plate at angle

This is the failure that ends §6's worked example if the design is careless, and it is a
standards problem more than a geometry problem.

**The flange the lip grips is not one thing.** ANSI/SLAS 3-2004 offers **five mutually
exclusive variants**, and requires the plate to declare which one it meets: §4.1 Short =
2.41 mm +/- 0.38, §4.2 Medium = 6.10 mm +/- 0.38, §4.3 Tall = 7.62 mm +/- 0.38, §4.4 Short
with interruptions = 2.41 mm +/- 0.38, §4.5 Dual = 2.41 mm on the short sides and 7.62 mm on
the long sides. `[STD]` A lip sized against a tall 7.62 mm flange will not reliably retain a
2.41 mm short-flange plate. "SBS compliant" on a vendor page does not tell you which variant
you are getting.

*What it does:* the plate slides, tips, or lifts off the nest at angle, which at best aborts
the step and at worst puts liquid on the deck and a plate under an arm.

*Catches it:* not a calculation. This guide has no friction coefficients for a printed
surface against a molded plate base, so any formula for required lip height as a function of
angle would be a fabricated number wearing an equation. **The measurement that settles it**
is the direct one: the actual plate, at the actual maximum angle, at working mass with
liquid in it, on the actual printed surface, tilted past the design angle until it moves.
Record the angle at which it moves. Do that for every plate type and every flange variant
the fixture is supposed to hold, and repeat it after any material change, because surface
finish drives friction and finish varies by filament and by layer height.

### A stack height that puts the plate out of Z range

A riser adds its height to the plate's, and the plate's height is not the number most people
have in their head.

- ANSI/SLAS 2-2004 specifies **14.35 mm +/- 0.25 mm** from the resting plane to the maximum
  protrusion of the perimeter wells, and 14.35 mm +/- 0.76 mm overall -- **for a typical
  microplate**. `[STD]` (Note the standard's own Figure 1 misprints the inch equivalent as
  0.56560 in against the correct 0.5650 in in the clause text. Use the metric value.)
- Plate types that are not typical microplates simply do not comply with SLAS 2 while still
  complying with SLAS 1, 3 and 4. A 96-well 1000 uL deep-well plate is documented at length
  127.8 mm and width 85.5 mm -- SLAS 1 conformant -- with a height of **44.1 mm**, roughly
  3x the SLAS 2 figure. Another vendor's 2.2 mL deep-well plate lists 44 mm and advertises
  only an "ANSI-SBS Footprint". `[DS]`

So the accurate framing is: **height is standardized only for standard-height microplates;
other formats keep the footprint and abandon the height.** Saying flatly that height is not
standardized is wrong, and so is assuming 14.35 mm. And ~44 mm is not a standard value
either -- those are two individual products' specifications, and other vendors will differ.

*What it does:* the pipetting head or gripper cannot reach the well bottom, or cannot clear
the plate top, or the deck position is simply outside the Z envelope. Discovered during
DRY_RUN if you are careful and during production if you are not.

*Mitigation:* compute the stack rather than assuming it. Riser height + the specific plate's
measured height + tip length + the clearance the head needs above the plate, against the
instrument's stated Z range, for every plate format that will ever sit on that fixture. If a
deep-well plate can land there, size for the deep-well plate.

### The plate is not the nominal plate

Four more clauses that will bite a nest designed to nominal dimensions.

- **There are two footprint tolerances, not one.** +/-0.25 mm applies **only** within 12.7 mm
  of the four outside corners `[STD: SLAS 1 §4.1.1.1]`. Anywhere else along the side the
  tolerance is **+/-0.5 mm** `[STD: §4.1.1.2]`. A nest cut to "127.76 x 85.48 +/- 0.25" as a
  flat statement will jam real plates that bow mid-side and remain fully conformant.
- **Corner radius is 3.18 mm +/- 1.6 mm** -- a permitted range of 1.58 to 4.78 mm, a 3x
  spread, scoped to the bottom flange corners specifically. `[STD: §4.1.2.1]` Design
  clearance features against the **maximum** 4.78 mm, not the nominal, or you will bind on
  plates at the top of the range.
- **Draft is excluded from the standard's numbers.** Every figure note states "Dimensions
  and tolerances do not include draft." `[STD]` Molded plates carry draft angles the
  standard's dimensions do not describe, and the actual angles are not published anywhere in
  it. A printed nest with vertical walls cut to nominals does not have the same real
  cross-section as the molded plate it is supposed to seat.
- **SLAS 2 has two alternative compliance parts** and a plate must declare which. §4.1 adds
  a minimum 1 mm clearance from the resting plane to the bottom external surface of the
  wells; §4.2 does not. `[STD]` If a fixture assumes 1 mm of clearance under the wells -- for
  bottom-reading optics, or a heat block -- a §4.2-compliant plate is not required to give
  it to you.

And one that saves a wasted investigation: **ANSI/SLAS 6-2012 sets no limits at all.** Its
§7 states that the standard "specifies definitions and a test method only" and that it is
"not the intent of this standard to state a limit" for well bottom elevation or its
variation. `[STD]` "SLAS 6 compliant" conveys no flatness or bottom-thickness guarantee
whatsoever. For any optical path, the instrument's own specification is the requirement.

One FDM-specific conformity note worth designing around: SLAS 1 §4.1.1.3 requires the
footprint be "continuous and uninterrupted around the base of the plate." Brim remnants,
elephant-foot bulges and support scars on a printed part's base are the same class of defect
in reverse -- they snag stage nests and gripper jaws.

---

## 6. Worked example: `hardware/tilt_module.scad`

A printed wedge that presents a plate at a fixed angle on the deck, so that residual liquid
pools toward one side of each well and more of it comes out at the aspiration step. It is
`ADJACENT`: it holds a certified plate and nothing touches it.

**This guide states no recovery-improvement figure for the tilt module, because none has
been measured.** The module's design intent is that recovery improves. Intent is not
evidence. In the repo's own vocabulary, "the tilt module improves recovery" currently rests
on basis `intuition` -- a scientist believes it, nothing is written down -- and it stays
there until the experiment below is run and recorded. It cannot become `in_house` any other
way.

### What the ladder says about it today

At best it reaches **MEASURED**. The wedge angle and the lip that retains the plate can be
measured against the model. Everything above that is unproven:

- **FITTED** needs the real plate, at working mass, at the design angle, checked for rock
  and checked for retention -- and per §5 that check has to be done separately for each
  flange variant it will hold.
- **DRY_RUN** needs the arm to run the real aspiration approach against a tilted plate,
  at reduced speed. Tilting changes the geometry the head was taught: the well bottom is no
  longer perpendicular to the approach, the clearance to the plate's high side shrinks, and
  the stack height went up by the wedge. Every one of those is a fresh collision opportunity
  and none of them is visible from FITTED.
- **IN_USE** needs a recorded run with material.

The wedge also creates its own new failure mode, which the flat nest did not have: it puts
the plate at an angle where a shallow lip stops retaining. That is §5's lip failure, and it
is not hypothetical for this part -- it is the part's defining feature.

### The acceptance test

The claim is a **difference between two conditions**, so the design is paired and the control
is the identical protocol without the wedge. Nine requirements, each of which exists because
skipping it produces a number that looks like an answer and is not.

**1. Endpoint must be a quantity, not an impression.** "The wells look drier" is not a
result. The natural endpoint is residual volume, measured **gravimetrically** -- weigh the
plate before and after the aspiration step on a balance whose resolution and repeatability
are adequate for the residual volume in question, and state both. If they are not adequate,
the experiment does not exist yet and buying a balance is the first step, not the wedge.

**2. Do not route the endpoint through the plate reader.** This workcell's absorbance read
is BROKEN -- written, run on the instrument, and it times out deterministically -- so an
optical recovery endpoint is not evaluable here at all. Even repaired, A260 does not
discriminate library from primer, carrier or free nucleotide, and at low input those
dominate the signal. A gate reading that number passes an empty well confidently. Gravimetry
or an orthogonal spike-and-recover, not OD.

**3. Measure per well, before any pooling.** The loss the wedge is supposed to reduce is a
per-well loss. A measurement taken after pooling reads 96 wells as one number, and a
single-well effect moves that number by about a ninety-sixth -- which is exactly why the
recovery layer already calls single-well loss silent. Measure while the material is still
`ADDRESSED`.

**4. n >= 3 paired runs before any tolerance is stated.** This repo sets
`MIN_DEMONSTRATIONS = 3` for stating a spread at all, and the same arithmetic applies here:
two points have one degree of freedom, so the interval they imply *is* the two points and
nothing in them can say whether either is an outlier. One paired plate produces a value and
no tolerance.

**5. Report the observed range, not mean plus k sigma.** The min and max of what happened is
a fact. Mean plus k standard deviations is a fact plus a k somebody chose, and k is exactly
the kind of number that reaches a report with no author attached to it.

**6. Judge on the worst observation, not the mean.** A mean lets one excellent plate pay for
a bad one. At the bench, the bad plate is the one that costs the sample.

**7. Randomize position, and never put wedge and control on different sides of the deck.**
Failures that appear column-wise are hardware, not biology -- biology fails randomly across
a plate and hardware fails geometrically. A wedge that occupies one deck position for the
whole experiment has confounded treatment with position, and the effect you measure may be
the position.

**8. Hold everything else constant and say so.** Same session, same instrument, same
consumable lot, same filament lot for the wedge itself. A wedge reprinted from a different
spool is a different part until it has been measured again (§5, shrinkage).

**9. Pre-register the threshold and record its basis.** Decide before the run what
improvement would make the wedge worth keeping, and record where that target came from. It
is `intuition` or `vendor` until this experiment runs; only afterward is there an `in_house`
number, and only for this plate type, this liquid, this volume and this aspiration height.

### What the test cannot show

It cannot show the wedge is safe for the arm. That is DRY_RUN, it is a separate
qualification, and a recovery result does not substitute for it in either direction -- a
wedge that improves recovery by hand and crashes the head is a worse part than no wedge.

And a bench result obtained by a person pipetting does not transfer to the arm. The
aspiration height, the approach angle and the compliance are all different. If the wedge is
for the robot, the paired experiment has to be run by the robot, after DRY_RUN, or the
number belongs to a hand.

---

## What this guide refuses to tell you

Kept as a list rather than buried, because the gaps are the part most likely to get filled
in by somebody's search results.

- **Whether any FDM part has ever been validated as cleanable to a recognized standard.** A
  targeted search found none. That is the crux of §1 and it did not close.
- **Whether steam penetrates and sterilizes the interior voids of an FDM part.** No located
  study cultured the interior of an autoclaved FDM part or ran biological indicators inside
  the void network. Surviving the heat and being sterile are different claims.
- **How many autoclave cycles any high-temperature polymer survives.** Every specific count
  traced to commercial aggregator pages.
- **A shrinkage percentage from any filament manufacturer.** Three datasheets were opened;
  none published one. The slicer defaults in §5 are the best available and they disagree
  with each other.
- **A warp-per-unit-length rule for large flat parts.** No dataset located measures flatness
  across a range of part sizes. The 3.7 mm / 0.8 mm figures cannot be scaled because the
  specimen dimensions were not stated.
- **A manufacturer bed-flatness specification** for any machine in §2.
- **Coefficients of thermal expansion** for ASA and PC. Conflicting values circulate for ABS
  (90e-6 /C versus 120e-6 /C) and the PLA and PETG figures found came from a retailer blog.
  None are printed here.
- **A static-dissipation figure** for any printable material, printed or otherwise.
- **The dimension callouts inside the SLAS engineering drawings.** Those figures are raster
  images. The clause text and the figure notes were read; anything appearing only on a
  drawing is not captured here.
- **Whether the SLAS standards were reaffirmed after June 2017.** The published copies remain
  (R2012) revisions and the standards page still carries forward-looking text about a
  reaffirmation. No ANSI record of a later action was found, so no current reaffirmation year
  is asserted. There is also no ANSI/SLAS 5 in the published set (1, 2, 3, 4, 6) and no
  authoritative statement explaining the gap -- do not speculate about it in print.
- **Whether the standards copies consulted are the controlling versions.** They are the
  copies the standards body itself publishes, dated 2011. For anything that goes to print,
  check the purchased controlled copies.
- **Any manufacturer claim of biocompatibility, cytotoxicity testing, autoclavability, or
  sample-contact suitability for any printer or stock filament in §2.** There is none on any
  official page read. "Supported filament" lists are printability ratings -- one vendor
  literally grades them "Ideal" and "Capable" -- meaning will-it-extrude-without-clogging.
  Treat the absence as absence, and never read a spec-table material list as a
  fitness-for-contact statement.

---

## Sources

Standards and regulatory
- ANSI/SLAS 1-2004 (R2012) Footprint Dimensions; 2-2004 (R2012) Height Dimensions; 3-2004
  (R2012) Bottom Outside Flange Dimensions; 4-2004 (R2012) Well Positions; 6-2012 Well
  Bottom Elevation. Clause text read directly from the standards body's published PDFs.
- ASME Y14.5M-1994, the drawing standard those five invoke normatively.
- ISO/ASTM 52902:2023, Additive manufacturing -- Test artefacts -- Geometric capability
  assessment. Paywalled; title, scope and edition status confirmed only. This is the citable
  route to a defensible in-house accuracy claim, rather than quoting a vendor number.
- ANSI/AAMI ST98:2022 cleaning validation (superseded AAMI TIR30). Confirmed acceptance
  criteria: TOC <= 12 ug/cm^2, ATP <= 22 fmol/cm^2. The widely quoted 6.4 ug/cm^2 protein
  criterion could not be confirmed and is not printed here.
- US FDA, *Technical Considerations for Additive Manufactured Medical Devices*, issued
  2017-12-05, §VI.E.
- US FDA guidance on the Mouse Embryo Assay for assisted reproduction devices.

Peer-reviewed
- Wang X, Zhao L, Fuh JYH, Lee HP (2019). *Polymers* 11(7):1154. doi:10.3390/polym11071154.
  Porosity at 100% infill by X-ray CT; pore size distribution and location.
- Popescu D, Baciu F, Amza CG, Cotrut CM, Marinescu R (2021). *Polymers* 13(23):4249.
  doi:10.3390/polym13234249. No print setting seals against fluid intake; vapor-smoothed
  parts still penetrated by dye.
- Hall DC Jr, Palmer P, Ji H-F, Ehrlich GD, Krol JE (2021). *Front Microbiol* 12:646303.
  doi:10.3389/fmicb.2021.646303. Biofilm in the layer lines; anisotropic Ra.
- Chiscop F, Cazacu C-C, Cazacu D-A, Cotet CE (2025). *J Funct Biomater* 16(9):334.
  doi:10.3390/jfb16090334. Annealed PLA through a 134 C / 60 min cycle, with dimensional
  penalties.
- Rogers HB, Zhou LT, Kusuhara A, Zaniker E, Shafaie S, Owen BC, Duncan FE, Woodruff TK
  (2021). *Chemosphere* 270:129003. ISO-certified dental resins release ovo-toxic leachates.
- Kress S, Schaller-Ammann R, Feiel J, Priedl J, Kasper C, Egger D (2020). *Materials*
  13(13):3011. doi:10.3390/ma13133011. Cytotoxicity of stereolithography photopolymers;
  parylene barrier and its detachment after 5-6 autoclave cycles.
- Oskui SM et al. (2016). *Environ Sci Technol Lett*. doi:10.1021/acs.estlett.5b00249. Both
  FDM and SLA parts toxic to zebrafish embryos; SLA significantly more so.

Manufacturer datasheets read directly
- Bambu Lab PETG Basic TDS V3.0; Victrex PEEK 450G TDS (rev. March 2026); SABIC ULTEM Resin
  1010 TDS (Europe, rev. 20170620); Stratasys ULTEM 9085 MDS (2025); Prusament ASA TDS v1.1;
  Prusament PC Blend TDS v1.1; PPprint P-filament TDS v1.001; Polymaker PETG TDS V2.0
  (2025-11-17); Polymaker ASA TDS; 3DXTech 3DXMAX ABS TDS Rev 3.0; Formlabs BioMed Clear TDS
  (doc 2001432-TDS-ENUS-0, rev 04); Stratasys F123 series product specification.
- Values for PLA grades, ABS-M30, Stratasys ASA, Bambu PC, PA grades and FDM ULTEM 1010 came
  from search extraction of manufacturer PDFs rather than direct reads and are marked
  `[DS-2]` throughout. One known problem: a Bambu PC datasheet surfaced HDT 117 C @1.8 MPa
  against 112 C @0.45 MPa, which is inverted relative to every other sheet read -- HDT at the
  higher load should be the lower number. Those two look transposed. Do not publish that pair
  until somebody opens the PDF.

Vendor pages, captured 2026-07-28
- Bambu Lab US store product pages for P1S, P2S, X2D, H2D, H2C and the 3D Printers category
  listing; the X1-series end-of-life announcement.
- Prusa Research product pages for MK4S, CORE One+ and the HT hotend upgrade.
- QIDI Tech US store Plus4 product and technical-specification pages. Note the Plus4
  marketing page carries a comparison graphic reading "Hot bed 100 / Nozzle 360 / Chamber
  55" -- those are previous-generation figures shown for contrast, not the Plus4's. An
  automated scrape of that page pulls the wrong three numbers.
- Intamsys Funmat HT product page.
- Protolabs Network (Hubs) knowledge base, dimensional accuracy of 3D printed parts.

Shipped code, read directly
- OrcaSlicer repository: `resources/profiles/*/filament/*.json` (`filament_shrink` values) and
  `src/libslic3r/PrintConfig.cpp` (the tooltip defining what those values mean).
- PrusaSlicer repository: `resources/profiles/PrusaResearch.ini`
  (`elefant_foot_compensation`).
- Prusa-Firmware: `Firmware/variants/MK3S.h`, for the Z-axis step geometry behind layer-height
  quantization. That granularity is (leadscrew lead)/(full steps per revolution) and must be
  recomputed per machine rather than assumed.
