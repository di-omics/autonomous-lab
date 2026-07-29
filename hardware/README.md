# Plate tilt module

`tilt_module.scad` is a passive fixed-angle tilt fixture for a liquid handler deck. It
holds one ANSI/SLAS-footprint plate or reagent reservoir at a shallow angle so residual
liquid pools at one side of each well, where a tip can reach more of it. It is a base
plate that registers to a deck position, a solid wedge, and an upper platform with corner
retaining lips. No hinge, no adjustment, no moving parts.

It matters where the last few microliters are the product: bead cleanups, elutions, and
reservoir dead volume.

## What this repository will not tell you

**No recovery figure appears anywhere in this file or in the model.** Not a percentage,
not a microliter count, not a range. Recovery depends on the well geometry, the liquid
class, the tip, the aspiration profile, and the surface energy of a molded polymer that
neither the model nor this README knows anything about. The only honest recovery number is
one you weighed on your own plates with your own liquid. The acceptance test below is how
you get it. Until it has been run, this is an untested idea with a part number, and it
should be described that way in a method section.

The model applies the same rule to itself. Every derived quantity is a function that
echoes its result at render time, and any function whose input has not been measured
reports `NOT COMPUTED` and names the parameter rather than substituting a plausible value.
`tilt_module.scad` refuses to render the full fixture at all until `deck_measured = true`.

## Safety

### An unlocated fixture is a deck crash

This part is taller and heavier than the plate the deck position was designed for, and its
center of mass is higher. If it can slide, rotate, or walk under gantry acceleration, the
head's taught coordinates point at where it used to be. A tip strike on a printed wedge
does not stop a Z axis: it snaps tips, shears the fixture off its seat, or drives the head
into the deck.

Consequences:

- `tilt_module.scad` will not render `part = "fixture"` until `deck_measured` is set true
  and the registration dimensions are filled in. That refusal is the design, not a bug.
- `registration_style = "none"` prints a HAZARD line in the render report every time. It
  is only defensible when the fixture is clamped or bolted by other means.
- **Re-teach every affected labware position after installing the fixture.** The plate no
  longer sits where it sat, in any of the three axes, and it is no longer level.
- The body overhangs the SLAS footprint by roughly 4.3 mm per side in X and 4.8 mm per
  side in Y at the default parameters. The render report prints the exact figures. Check
  the neighboring deck positions and the head's travel path before you print, not after.
- Run the complete motion program dry, at production speed and acceleration, including any
  gripper moves, before any liquid is on the deck.

### What this material may touch

This is a **holder**. Nothing printed from this file is qualified to contact samples,
reagents, cells, or media. Keep the certified consumable between the printed part and the
sample: the plate is the barrier.

- Dimensional conformity to ANSI/SLAS is not evidence of fitness for contact. Those
  standards specify footprint, height, flange, well positions and a well-bottom-elevation
  test method, and say nothing about material, leachables, extractables, cytotoxicity,
  sterility, or nuclease status.
- FDM parts are porous by construction. X-ray CT of PLA printed at 100% infill measured
 4.05 to 6.32% internal porosity across raster settings, with pores concentrated at the
  shell-to-infill interface -- that is, connected to the outer surface (Wang et al.,
  *Polymers* 11(7):1154, 2019). Immersion testing of ABS found that no combination of
  layer height, perimeter count, or infill pattern sealed a part against fluid intake, and
  that acetone vapor smoothing left parts that still stained with dye after 30 minutes of
  immersion (Popescu et al., *Polymers* 13(23):4249, 2021).
- Bacteria preferentially colonize the layer lines. Biofilm was thickest in the grooves
  between printed layers on every polymer tested (Hall et al., *Front. Microbiol.*
 12:646303, 2021).
- Many photopolymer (SLA/DLP/MSLA) resins remain cytotoxic after full manufacturer
  post-cure, including resins carrying ISO 10993 biocompatibility certification, because
  the certification does not cover the exposure this fixture would represent and because
  non-polymerizable additives are not consumed by further UV exposure.
- **Do not autoclave.** PLA, PETG, ABS and ASA all have a glass transition below 121 C.
  Printed parts contain frozen-in extrusion stress that relaxes as soon as the polymer
  passes Tg, so the part moves with no load applied at all. Wipe-down with 70% IPA is
  housekeeping, not decontamination, and the part will absorb some of what you wipe it
  with.

Treat the fixture as a non-sample-contacting fixture with a defined replacement interval,
or as single-use if it is ever splashed.

## Files

| file | what it is |
| --- | --- |
| `tilt_module.scad` | the parametric model, the computed report, and the test coupon |
| `README.md` | this file |

Render with OpenSCAD 2019.05 or later (`assert()` is required):

```
openscad -o coupon.stl  -D 'part="coupon"'  tilt_module.scad
openscad -o fixture.stl -D 'part="fixture"' tilt_module.scad   # refuses until measured
```

The echoed report goes to stderr on the command line and to the console pane in the GUI.
Read it every time. It is where the numbers that decide feasibility appear.

## Parameters

Every dimension is a named parameter at the top of the file with its units and its reason.
The groups below are the ones you will actually change.

### The labware being held

| parameter | default | note |
| --- | --- | --- |
| `plate_len_mm`, `plate_wid_mm` | 127.76, 85.48 | ANSI/SLAS 1-2004 4.1.1.1 nominals |
| `plate_footprint_tol_mm` | 0.5 | the 4.1.1.2 mid-side tolerance, not the 4.1.1.1 corner one. See below. |
| `plate_corner_r_max_mm` | 4.78 | 4.1.2.1 is 3.18 +/- 1.6 mm. Use the maximum for a clearance feature. |
| `plate_flange_h_mm`, `plate_flange_tol_mm` | 6.10, 0.38 | ANSI/SLAS 3-2004 4.2 medium. Five incompatible variants exist. |
| `plate_height_mm` | 14.35 | ANSI/SLAS 2-2004, and **only** for a standard-height microplate |
| `plate_cg_height_mm` | -1 | unmeasured sentinel; no SLAS standard gives plate mass |
| `well_cols`, `well_rows`, `well_pitch_mm` | 12, 8, 9.0 | ANSI/SLAS 4-2004 4.1 (96-well) |

Three of these are traps worth stating plainly:

**There are two footprint tolerances, not one.** SLAS 1 4.1.1.1 gives +/- 0.25 mm, but only
within 12.7 mm of the four outside corners. 4.1.1.2 gives +/- 0.5 mm anywhere else along
the side. A conforming plate may bow outward by 0.5 mm at mid-side. A pocket cut to the
commonly quoted +/- 0.25 mm jams legal plates, in the middle, where it is not obvious why.
The model uses the loose figure.

**The flange variant is a required input.** SLAS 3 offers five mutually exclusive variants
(short 2.41, medium 6.10, tall 7.62, short-with-interruptions 2.41, dual 2.41/7.62 mm, all
+/- 0.38) and requires a plate to declare which one it meets. "SBS compliant" on a vendor
page does not tell you. The retaining lip has to engage the flange and nothing above it,
so this parameter sizes the lip. On a short-flange plate the default 3.0 mm lip is too
tall and the render report says `FAIL`.

**Height is standardized only for standard-height plates.** Deep-well plates, PCR plates
and reservoirs keep the SLAS 1 footprint and abandon the SLAS 2 height. Published deep-well
products sit near 44 mm, but that is a product spec, not a standard, and other vendors
differ. If you are tilting one, measure it and put the measurement in.

### The angle

| parameter | default | note |
| --- | --- | --- |
| `tilt_angle_deg` | 7 | about the plate's short axis; the column-12 end goes down |
| `cross_tilt_deg` | 0 | optional second tilt; turns an edge pool into a corner pool |

Compound tilt is steeper than it sounds. Two 6-degree components make an 8.5-degree plane.
`max_slope_deg()` computes the true slope and the report prints it.

### Clearance

| parameter | default | note |
| --- | --- | --- |
| `clearance_mm` | 0.35 | per side, plate into pocket -- a hole |
| `deck_clearance_mm` | 0.30 | per side, skirt into deck nest -- a shaft |

**Clearance is the parameter you tune after measuring a test print, not the one you trust
from the model.** The printed part is not the model:

- Shrinkage is material and grade dependent and generally not published. Filament technical
  data sheets checked directly (Polymaker PETG V2.0, Polymaker ASA, 3DXTech 3DXMAX ABS)
  carry no shrinkage figure at all. Every per-material percentage circulating online is a
  slicer default or a community measurement.
- Slicer defaults disagree with each other. OrcaSlicer ships `filament_shrink` of 99.95%
  for one vendor's PLA, 99.85% PETG, and 99.487% for ABS and ASA, while another vendor's
  profiles in the same repository ship 100% for all four. A 0.5% disagreement on ABS is
 0.64 mm across 127.76 mm -- larger than the entire SLAS footprint tolerance.
- Desktop FDM accuracy is quoted at about +/- 0.5% with a +/- 0.5 mm floor, and it scales with
  length. A good calibration cube proves nothing about a 129 mm pocket.
- The first layers are the least trustworthy part of the print. PrusaSlicer's own profiles
  ship 0.2 mm of elephant-foot compensation for a 0.4 mm nozzle, and the bottom of this
  fixture is exactly where the registration feature lives.
- Repeatability is far better than accuracy: hundredths of a millimeter of run-to-run
  spread against tenths of accuracy error. That asymmetry is why measure-and-compensate
  works -- your printer reproduces its own error reliably enough to cancel it.

Two clearances, not one, because a hole and a shaft err in opposite directions on the same
machine. Do not slave one to the other.

### Lips, base, and registration

| parameter | default | note |
| --- | --- | --- |
| `lip_style` | `"corners"` | `"corners"` or `"full"` |
| `lip_height_mm`, `lip_height_uphill_mm` | 3.0, 3.0 | above the seat plane |
| `lip_thickness_mm` | 2.4 | at the lip top; 6 walls at a 0.4 mm nozzle |
| `lip_fillet_mm` | 1.2 | extra thickness at the root, tapered outward face |
| `lip_arm_mm` | 24.0 | length of each corner-lip arm |
| `base_thickness_mm` | 4.0 | flat slab spanning the whole footprint |
| `min_lift_mm` | 2.0 | minimum wedge thickness at the low corner |
| `platform_thickness_mm` | 3.0 | slab under the seat |
| `wall_mm` | 2.4 | registration skirt wall, and the minimum wall anywhere |
| `registration_style` | `"slas_skirt"` | `"slas_skirt"`, `"post"`, or `"none"` |
| `deck_nest_depth_mm` | -1 | **MEASURE.** Unmeasured sentinel. |
| `deck_nest_rim_w_mm` | -1 | **MEASURE.** Unmeasured sentinel. |
| `seats_on` | `"nest_floor"` | which surface carries the weight; see below |
| `reg_post_*` | -1 | **MEASURE.** Only for `registration_style = "post"`. |
| `deck_measured` | `false` | the gate on rendering the fixture |

### How the retaining lips hold the plate

The plate on a tilted seat wants to slide downhill. **Whether friction alone would hold it
is not computed anywhere, and cannot be**: the static coefficient between a printed lip and
a molded polypropylene skirt is unpublished, changes with layer orientation and surface
finish, and drops further when either surface is wet with buffer or ethanol. Design as if
friction is zero. The lips are the only thing holding the plate.

So the plate does not center itself in the pocket. It slides until it touches the two
downhill corner lips, and **those lips are the datum**. Every reach number in the model is
referenced to that seated position.

The lip height has a window and both ends are real:

- **Lower bound**, `lip_min_engage_mm` = 1.2 mm. The lip must stand proud enough to engage
  the flange face rather than the plate's bottom edge break. SLAS figure Note 4 in all four
  dimensional standards states that dimensions and tolerances do not include draft. Molded
  plates carry draft angles the standard excludes and does not publish, so the flange face
  is not vertical and the exact contact height cannot be computed from the standard. A
  shorter lip is contacting whatever the draft leaves it, which is not a designed contact.
- **Upper bound**, minimum flange height minus `lip_flange_margin_mm`. Above the flange the
  lip stops pushing on the flange and starts pushing on the plate body -- into gripper jaw
  travel, into a skirt chamfer that will cam the plate upward, or into the well region.
  Minimum flange height is nominal minus 0.38 mm: 5.72 mm for a medium flange, 2.03 mm for
  a short one.

`lip_window_ok()` checks the window and the report prints `PASS` or `FAIL` with the reason.

Corner lips rather than continuous rails, for three reasons. SLAS 3 4.4 permits a single
interruption on center of each long side; a continuous long-side rail can land on that
interruption, but a corner lip cannot, because the interruption edges are at least 47.8 mm
from the nearest part edge. The mid-side gaps are also where a gripper puts its jaws. And
the downhill mid-side gap is the drain path for anything spilled.

Tipping is not the failure mode. `tip_over_angle_deg()` computes the angle at which the
plate's center of mass passes over the downhill lip contact line, and it reports
`NOT COMPUTED` until you supply `plate_cg_height_mm` -- but for any plausible CG height the
answer is far above any usable tilt. The lip's job is purely to arrest sliding. That means
lip **thickness and root strength** matter, not lip height. The lip load itself is also
`NOT COMPUTED`: no SLAS standard specifies plate mass, so weigh your loaded plate if you
want a number.

### Deck registration and the two seating conditions

`registration_style = "slas_skirt"` gives the fixture's own base an ANSI/SLAS-1 footprint
skirt so it drops into the deck nest the way a plate does. This reuses location the deck
already provides and needs one measurement (the nest depth) instead of a hole pattern. The
skirt is continuous and uninterrupted around the base, as SLAS 1 4.1.1.3 requires of a
plate footprint, and for the same reason -- a gap snags a nest.

The fixture body is wider than the skirt, so its shoulder sits above the nest rim. Only one
of those two surfaces can carry the weight, and a fixture that is unsure which one will
rock:

- `seats_on = "nest_floor"` runs the skirt `seat_relief_mm` deeper than the nest, so the
  skirt bottom lands on the nest floor and the shoulder floats clear of the rim.
- `seats_on = "nest_rim"` runs the skirt shallower, so the shoulder lands on the rim and
  the skirt bottom floats. This needs `deck_nest_rim_w_mm` to be wide enough to carry the
  shoulder.

Pick one. Do not size both to zero clearance and hope.

`registration_style = "post"` uses **two** posts on the long axis, not four. Four posts in
four holes over-constrain the part: with desktop FDM positional error across a 100 mm span,
at least one post binds and the fixture seats on three, rocking. Two posts fix position and
rotation, which is all that is needed.

## The two numbers that decide feasibility

Both are echoed on every render. At the default parameters (96-well, 7 degrees, no cross
tilt, `registration_style` engagement excluded because it depends on your measured nest):

### `tip_reach_delta_mm()` -- 12.07 mm

How much further down the head must travel at the far corner than at the near one.

Two well bottoms separated by `dx` along the plate's long axis and `dy` along its short
axis are separated vertically, once tilted, by

```
dz = dx * sin(tilt) + dy * sin(cross) * cos(tilt)
```

`sin`, not `tan`: the wells are separated by `dx` measured **along the plate**, which is
now the hypotenuse rather than the deck projection. Using `tan` overstates the drop, and at
shallow angles the two differ by under a percent -- exactly the kind of error that survives
review.

The span is between well **centers**, from SLAS 4: `(cols - 1) * pitch` by
`(rows - 1) * pitch`, which is 99.0 x 63.0 mm for a 96-well plate, not the 127.76 x 85.48
footprint. Using the footprint overstates the drop by about 30%, which sounds conservative
until it talks somebody out of a workable angle.

If the head is near the end of its Z stroke at the near corner -- which is where a
deep-well plate on a tall fixture puts it -- the far corner is where it runs out. Confirm
the commanded Z at the far corner is inside the head's envelope before running liquid.

### `stack_top_mm()` -- 39.38 mm above the deck datum, versus 14.35 mm flat

25.03 mm of extra Z consumed, decomposed by `stack_budget()`:

| contribution | mm | reducible? |
| --- | --- | --- |
| fixed: base slab + min lift + platform slab | 8.98 | yes, `low_profile` takes it to 5.59 |
| angle-driven: pocket length x sin(tilt) | 15.72 | **no** |
| the plate itself | 14.24 | no |

`low_profile = true` thins the base slab, the lift, and the platform slab, and saves
3.40 mm out of 25.03. **The angle-driven term is untouchable.** You cannot thin your way
out of the angle. If the stack does not fit the head envelope or the gripper approach, the
angle comes down or the fixture does not get used.

Add your measured `deck_nest_depth_mm` on top of all of this if the skirt seats on the nest
floor.

## Print settings that matter

Material-dependent settings are marked. Everything else is geometry.

| setting | value | why |
| --- | --- | --- |
| layer height | 0.15 to 0.2 mm | finer layers reduce fluid ingress at the surface, but do not seal the part |
| perimeters / walls | 5 or more | the lip is a cantilever loaded across the layers; walls carry that load, infill does not |
| top / bottom layers | 5 or more | the seat is a functional surface |
| infill | 15 to 25% gyroid | **do not model internal voids.** An enclosed cavity in a fixture that gets wiped cannot be dried. Let the slicer make the sparse structure so it drains and dries through the walls. |
| elephant-foot compensation | as your profile normally uses | the registration skirt is on the first layers; if you disable it, the skirt is oversize |
| brim | only if adhesion fails, and **remove it completely** | SLAS 1 4.1.1.3 requires a continuous uninterrupted footprint. Brim and elephant-foot remnants on the skirt snag deck nests and gripper jaws. |
| supports | see below | |
| nozzle | steel, not brass | **material-adjacent.** Brass alloys commonly contain lead. Even for a non-contacting fixture this is the cheaper choice to make correctly. |

Material choice is yours, with these constraints:

- **Nothing here is autoclavable.** PLA (Tg roughly 54 to 61 C across four grades from one
  manufacturer), PETG (Tg roughly 69 to 77 C, with an 8 C spread between manufacturers on
  nominally the same polymer), ABS (HDT 84 to 104 C between desktop and industrial grades)
  and ASA (HDT 86 to 103 C) are all below a 121 C cycle. For a printed part Tg is the
  correct gate, not HDT: an autoclaved fixture carries no external load, but it does carry
  frozen-in extrusion stress that relaxes above Tg and moves the part with zero load
  applied.
- PLA warps at bench-relevant temperatures. One study observed visible warping of an
  as-printed PLA curved beam from approximately 70 C. A fixture that lives near a heated
  block or in a warm room is a PLA problem.
- Shrinkage differs by material **and by grade and vendor within a material** (see
  Clearance above). If you change filament, reprint the coupon. The clearance you
  calibrated does not transfer.

## Orientation and supports

**Print base down, seat up, wedge as printed.** The part is modeled sitting on the deck; it
prints in that same orientation with no rotation.

Why:

- The registration skirt and the base slab are the datum surfaces of the whole fixture, and
  they end up flat on the bed. That is the most dimensionally repeatable orientation
  available, and the one where the skirt walls are vertical rather than stepped.
- The seat plane becomes a shallow top surface at the tilt angle. At 7 degrees it needs no
  support, and it comes out as an ironed-quality top rather than a support-scarred
  underside. The seat is the surface the plate registers against, so it should not be the
  supported one.
- The lips end up as vertical walls printed as walls, so their thickness comes from
  perimeters and not from infill.
- The wedge's outer faces lean **inward** going up (the body footprint is deliberately
  larger than the platform's projection by `body_margin_mm`), so there are no overhangs
  anywhere on the exterior.

Supports: **none required** at the default parameters. Check the preview if you raise
`tilt_angle_deg` past roughly 45 degrees, which is not a sensible tilt for this application
anyway, or if you widen `lip_arm_mm` so far that the corner lips bridge.

Where the layer lines end up relative to load, and what to do about it:

The layer lines run horizontally, parallel to the deck. The plate pushes the downhill lip
sideways, so the lip is a transverse cantilever and the tensile stress at its root acts
**across** the layer interfaces. That is the weakest direction in an FDM part, and it is
where this fixture will fail if it fails.

Rotating the part to fix that would put layer lines the right way for the lip and the wrong
way for everything else: the registration skirt would print as stepped walls, the seat would
need support, and the base would lose its flatness reference. The skirt and the seat matter
more, because a lip that flexes lets a plate creep, while a skirt that is out of round lets
the whole fixture sit wrong. So the orientation stays, and the lip is compensated
geometrically instead:

- `lip_thickness_mm` = 2.4 mm at the tip, which is 6 perimeters at a 0.4 mm nozzle.
- `lip_fillet_mm` = 1.2 mm of extra thickness at the root, with the outer face tapered so
  the section modulus is highest exactly where the bending moment is.
- The inner face stays vertical. That is the plate contact and it should be a face, not a
  slope.
- Push the coupon's lip hard with a thumb, sideways, before you print the fixture. If it
  creaks or whitens at the root, add perimeters or thickness. This is the one place the
  coupon tests strength rather than fit.

## The test coupon: print this first

```
openscad -o coupon.stl -D 'part="coupon"' tilt_module.scad
```

The coupon is a small pad carrying three things:

1. **The downhill corner of the real fixture**, cut out of the same `upper_solid()` module
   the fixture uses -- the corner lip, its root fillet, its lead-in chamfer, the pocket
   corner radius, and the seat at the design angle. It is not a re-modeled approximation. A
   coupon built from its own geometry only validates the coupon.
2. **A corner of the registration skirt** at its real wall thickness and corner radius.
3. **A witness block**, 20.0 mm nominal in X and Y, 10.3 mm in Z.

What to do with it:

- Measure the witness block on all three axes. X and Y give your printer's actual in-plane
  scale error, which is what `clearance_mm` and `deck_clearance_mm` exist to cancel. Z is
  different in kind: it is layer quantization plus first-layer squish, which is a constant
  offset on total height rather than a percentage, so do not convert it to a percent and
  apply it to lengths. The Z nominal is 10.3 mm on purpose -- it is not a multiple of any
  common layer height, and total height is forced to `first_layer + n * layer`, so a
  nominal that lands between two layers is the only one that shows you the quantization at
  all. A 20.0 mm gauge at a 0.2 mm layer hides it completely.
- Offer a real plate corner to the lip. It should drop in past the lead-in without force
  and sit flat, and it should not be able to lift over the lip.
- Push the lip sideways, hard.
- Drop the skirt corner into the corresponding corner of your deck nest.

**What the coupon cannot tell you.** It validates features, not the whole-footprint fit,
because it is not 127.76 mm long. Take your measured scale error from the witness block,
apply it to the full length, and only then commit to printing the fixture. If you change
filament, spool, or printer, the coupon is invalidated and you print it again.

## Fitting the fixture to your deck

1. Print and check the coupon. Set `clearance_mm` and `deck_clearance_mm` from what you
   measured.
2. Measure the deck position: nest depth to the surface a plate's own footprint rests on,
   and rim width if you intend to seat on the rim. Set `deck_nest_depth_mm`,
   `deck_nest_rim_w_mm`, and `seats_on`.
3. Set `plate_flange_h_mm` from your plate's declared SLAS 3 variant and confirm the
   report says the lip window is `PASS`.
4. Set `plate_height_mm` to your plate's real height if it is not a standard-height
   microplate.
5. Read `tip_reach_delta_mm()` and `stack_top_mm()` from the report and check both against
   the head's Z envelope and the gripper's approach. Do this before printing, not after.
6. Set `deck_measured = true` and render.
7. Install it, then re-teach every affected labware position.
8. Run the full motion program dry at production speed and acceleration.
9. Only then run the acceptance test.

## Acceptance test

**An unmeasured fixture is an unproven one.** The claim being tested is that the fixture
reduces residual volume. That claim is gravimetric, not visual, and it has to be measured
against the same protocol without the fixture.

### What to measure

Residual volume: the mass of liquid remaining in the vessel after a defined recovery
aspiration, converted to volume using the density of the actual liquid at the measured
temperature.

Use a balance with 0.1 mg readability or better. At the density of water, 0.1 mg is
approximately 0.1 uL, which is the resolution the question deserves. A 1 mg balance cannot
answer it.

### Procedure, per plate

1. Weigh the empty, dry plate. `m_empty`.
2. Dispense a defined starting volume into a defined set of wells with the liquid handler,
   using the same tips, liquid class, and aspiration profile you will use in production.
3. Weigh. `m_filled`. The delivered volume is `(m_filled - m_empty) / density`, and this
   also tells you whether the dispense itself was in spec.
4. Run the recovery aspiration program.
5. Weigh. `m_after`. Residual mass is `m_after - m_empty`.

### The control most people skip

Run an **evaporation control plate** in parallel: filled identically, weighed on the same
schedule, never aspirated. At microliter scale over a several-minute program, evaporative
loss is comparable in magnitude to the effect being measured. Subtract it. Without this
control, a slow protocol looks like a good recovery.

Record ambient temperature and humidity with each run. Use the density of your actual
liquid at that temperature, not water at 20 C, unless the liquid is water.

### Replicates, and what the replicate is

**The experimental unit is the plate or the run, not the well.** The fixture is applied per
plate, so wells within one plate are pseudo-replicates for the fixture effect: they share
the plate, the seating, the tip box, and the moment in time. Averaging 96 wells and
reporting n = 96 overstates the precision by roughly an order of magnitude.

Minimum defensible design:

- **At least 3 independent runs per arm, on at least 2 different days**, so between-day
  variation is inside the estimate rather than hidden by it.
- **Paired and interleaved**: within each run, alternate fixture and no-fixture plates
  rather than doing all of one arm then all of the other. Tip lots, room temperature, and
  operator technique all drift.
- Compute the mean residual across wells **within** a plate, then treat those plate means as
  the replicates.
- Report per-well residuals too, as a distribution. A fixture that lowers the mean while
  widening the spread has traded one problem for another, and the mean alone hides it.
- Randomize or counterbalance plate positions and which physical plates go in which arm.

### Pre-register the threshold

Decide, **before running**, the smallest reduction in residual volume that would change
what you do. That is a scientific judgment about your assay, not a statistical one, and
writing it down afterward is how a null result becomes a positive one.

Adopt the fixture only if all of the following hold:

1. The paired mean reduction in residual volume exceeds your pre-stated minimum useful
   difference, and the 95% confidence interval on the paired difference excludes it.
2. The coefficient of variation of recovered volume is not worse with the fixture than
   without.
3. Zero collisions, zero mispicks, and zero plate movements across the full test, including
   every gripper move.
4. The plate is in the same position at the end of the run as at the start. Mark the plate
   and the fixture, and check.
5. The commanded Z at the far corner stayed inside the head's envelope, with margin.

Any of 3, 4, or 5 failing is disqualifying regardless of how good the recovery number is. A
fixture that recovers more liquid and occasionally crashes is worse than no fixture.

### Reporting

Report the measured reduction with its confidence interval, the replicate count as **runs**
(not wells), the balance readability, the liquid and its density basis, the evaporation
correction, the plate type and its declared SLAS 3 flange variant, the tilt angle, and the
print material and printer. A recovery figure without the liquid, the plate, and the tip is
not transferable to anyone else's bench, including your own next month.

If the result does not clear your threshold, say so and leave the fixture out. That is a
result.

## Verification status of this file

The model was checked for syntactic balance and for undefined function and module
references by static analysis. **It has not been rendered**: `openscad` is not installed on
the machine where this was written, so no F5 preview, no F6 render, no STL, and no
manifold check has been performed. Render it yourself before printing, read the echoed
report, and treat any geometry surprise as a bug in this file rather than in your setup.

## Sources

Dimensional standards, clause text read directly:

- ANSI/SLAS 1-2004 (R2012) Microplates -- Footprint Dimensions
- ANSI/SLAS 2-2004 (R2012) Microplates -- Height Dimensions
- ANSI/SLAS 3-2004 (R2012) Microplates -- Bottom Outside Flange Dimensions
- ANSI/SLAS 4-2004 (R2012) Microplates -- Well Positions
- ANSI/SLAS 6-2012 Microplates -- Well Bottom Elevation (defines a test method and sets no
  limits: 7 states explicitly that it is not the intent of the standard to state a limit)

All five are published by SLAS at `slas.org`. Dimensions in SLAS 1 through 4 apply at 20 C;
SLAS 6's test method specifies 25 +/- 2 C. Do not quote a single temperature for the family.
Before publishing anything that depends on these clauses, check the purchased ANSI copies.

Porosity, cleanability, and material behavior:

- Wang X, Zhao L, Fuh JYH, Lee HP (2019). *Polymers* 11(7):1154. doi:10.3390/polym11071154
- Popescu D, Baciu F, Amza CG, Cotrut CM, Marinescu R (2021). *Polymers* 13(23):4249.
  doi:10.3390/polym13234249
- Hall DC Jr, Palmer P, Ji H-F, Ehrlich GD, Krol JE (2021). *Front. Microbiol.* 12:646303.
  doi:10.3389/fmicb.2021.646303
- Chiscop F, Cazacu C-C, Cazacu D-A, Cotet CE (2025). *J. Funct. Biomater.* 16(9):334.
  doi:10.3390/jfb16090334
- US FDA (2017). *Technical Considerations for Additive Manufactured Medical Devices*,
  Section VI.E, on validating cleaning and sterilization against the worst-case
  configuration.

Dimensional accuracy and shrinkage:

- Protolabs Network (Hubs) knowledge base, dimensional accuracy of 3D printed parts
- OrcaSlicer, `resources/profiles/*/filament/*.json` (`filament_shrink`) and
  `src/libslic3r/PrintConfig.cpp` (its definition)
- PrusaSlicer, `resources/profiles/PrusaResearch.ini` (`elefant_foot_compensation`)
- Polymaker PETG V2.0, Polymaker ASA, and 3DXTech 3DXMAX ABS technical data sheets, checked
  directly for a shrinkage figure and found to carry none

Style precedent: `hardware/tube_nest.scad` in the `di-omics/bay-hack` repository -- every
dimension a named parameter at the top, and a fit coupon before anything large.
