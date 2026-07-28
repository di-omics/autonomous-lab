// =============================================================================
// tilt_module.scad -- a passive fixed-angle tilt fixture for a liquid handler
// deck. It holds one ANSI/SLAS-footprint plate or reservoir at a shallow angle
// so residual liquid pools at one side of each well and a tip can reach more of
// it. There is no hinge, no actuator, and no adjustment: the angle is a printed
// constant, which is the point. An adjustable angle is an angle nobody records.
//
// WHY THIS EXISTS
//
// On a bead cleanup, an elution, or a reservoir with 400 uL left in it, the last
// few microliters are the product. A flat plate on a flat deck leaves them
// spread across the whole well bottom in a film the tip cannot chase. Tilting
// the vessel concentrates the same volume into a smaller footprint at one edge.
// That is the entire mechanism. It is geometry, not chemistry.
//
// WHAT THIS FILE DOES NOT DO
//
// It does not tell you how much liquid you will recover. No number in this file
// is a recovery figure, and none should be added, because recovery depends on
// the well geometry, the liquid class, the tip, the aspiration profile, and the
// surface energy of a molded polymer this model knows nothing about. The only
// honest recovery number is one you weighed. hardware/README.md gives the
// acceptance test that produces it. Until that test has been run, this fixture
// is an untested idea with a part number.
//
// WHAT IT COMPUTES
//
// Everything derived here is a function, and every function echoes its result at
// render time (see report() at the bottom). Two of those numbers decide whether
// the fixture is usable at all before any liquid is involved:
//
//   tip_reach_delta_mm()  how much deeper the head must travel at the far corner
//   stack_top_mm()        how much taller the loaded deck position becomes
//
// Where an input has not been measured, the corresponding function returns
// nothing and the report says NOT COMPUTED. It does not substitute a plausible
// value. An unmeasured fixture is an unproven one, and a model that quietly
// invents the missing measurement makes that impossible to notice.
//
// SAFETY -- DECK CRASH
//
// A fixture that is not positively located on the deck is a crash. It is heavier
// and taller than the plate the deck position was built for, its center of mass
// is higher, and if it can slide, rotate, or walk under gantry acceleration then
// the head's taught coordinates point at where it used to be. A tip strike on a
// printed wedge does not stop a Z axis; it snaps tips, shears the fixture, or
// drives the head into the deck. This file therefore refuses to render the full
// fixture until deck_measured is set true (see the assert in tilt_fixture()).
// That refusal is deliberate. Print the coupon, measure your deck position, then
// come back. Also re-teach every affected labware position after installing the
// fixture -- the plate no longer sits where it sat, in any of three axes.
//
// SAFETY -- WHAT THIS MATERIAL MAY TOUCH
//
// This is a HOLDER. Nothing printed here is qualified to contact samples,
// reagents, cells, or media, and dimensional conformity to ANSI/SLAS is not
// evidence of fitness for contact -- those standards say nothing about material,
// leachables, cytotoxicity, sterility, or nuclease status. FDM parts carry 4-6%
// internal porosity even at 100% infill (Wang et al., Polymers 11(7):1154,
// 2019, X-ray CT, 4.05-6.32% across raster settings) and the voids connect to
// the outer surface, so they wick liquid in and cannot be reliably cleaned;
// vapor smoothing reduces roughness without sealing the part (Popescu et al.,
// Polymers 13(23):4249, 2021). Many photopolymer resins remain cytotoxic after
// full post-cure. Keep the certified consumable between this part and the
// sample: the plate is the barrier. Wipe-down of the fixture is housekeeping,
// not decontamination. Do not autoclave -- PLA, PETG, ABS and ASA all have a
// glass transition below 121 C and will relax printed-in stress and move.
//
// PRECEDENT
//
// Parameter-block style follows hardware/tube_nest.scad in the bay-hack repo:
// every dimension named at the top, nothing magic buried in the geometry, and a
// fit coupon printed before anything large.
// =============================================================================

$fa = 2;
$fs = 0.4;

// Which solid to emit. Print "coupon" first. Always.
part = "coupon";  // "coupon" | "fixture" | "both"


// =============================================================================
// 1. THE LABWARE BEING HELD
//
// Defaults are the ANSI/SLAS nominals. They are nominals: a conforming plate is
// allowed to differ from every one of them, and the tolerance that governs a
// pocket is not the one people quote.
// =============================================================================

// ANSI/SLAS 1-2004 (R2012) 4.1.1.1 nominal footprint. mm.
plate_len_mm = 127.76;
plate_wid_mm = 85.48;

// THE TOLERANCE THAT ACTUALLY SIZES THE POCKET. mm, applies to the overall
// dimension (not per side).
//
// SLAS 1 states TWO footprint tolerances and the commonly quoted one is the
// wrong one for this job. 4.1.1.1 gives +/- 0.25 mm, but only within 12.7 mm of
// the four outside corners. 4.1.1.2 gives +/- 0.5 mm anywhere else along the
// side. A conforming plate may bow outward by 0.5 mm at mid-side. A pocket cut
// to 127.76 +/- 0.25 jams a legal plate, and it jams it in the middle where you
// cannot see why. Use the loose figure.
plate_footprint_tol_mm = 0.5;

// SLAS 1 4.1.2.1 corner radius is 3.18 +/- 1.6 mm, a permitted range of 1.58 to
// 4.78 mm -- a 3x spread. A clearance feature cut to the 3.18 nominal binds on
// every plate at the top of the range. Use the maximum for anything the corner
// has to fit into. mm.
plate_corner_r_max_mm = 4.78;

// ANSI/SLAS 3-2004 bottom outside flange. FIVE mutually exclusive variants
// exist and a plate is required to declare which one it meets:
//   4.1 short 2.41   4.2 medium 6.10   4.3 tall 7.62
//   4.4 short with interruptions 2.41  4.5 dual 2.41 short sides / 7.62 long
// all +/- 0.38 mm from Datum A. "SBS compliant" on a vendor page does not tell
// you which. The retaining lip has to engage this flange and nothing above it,
// so this is a load-bearing input, not documentation. Set it from the plate's
// own datasheet. mm.
plate_flange_h_mm   = 6.10;
plate_flange_tol_mm = 0.38;

// Plate height from Datum A. ANSI/SLAS 2-2004 4.1.1.2 gives 14.35 +/- 0.76 mm
// overall -- but ONLY for a standard-height microplate. Deep-well plates,
// PCR plates and reservoirs keep the SLAS 1 footprint and abandon the SLAS 2
// height entirely; published deep-well products sit near 44 mm, which is a
// product spec and not a standard. If you are tilting a deep-well plate or a
// reservoir, put ITS measured height here, because this number and the tilt
// angle together set how much Z the fixture consumes. mm.
plate_height_mm = 14.35;

// Height of the loaded plate's center of mass above its own bottom face. mm.
// NOT SPECIFIED BY ANY SLAS STANDARD -- no standard gives plate mass or mass
// distribution, and a full deep-well plate is a different object from an empty
// one. Leave negative and the tip-over check reports NOT COMPUTED rather than
// inventing a number. Measure it if you care about the answer.
plate_cg_height_mm = -1;

// Well grid, ANSI/SLAS 4-2004 4.1 (96), 4.2 (384), 4.3 (1536). Used only to
// compute the span between the first and last well CENTERS, which is the span
// the tips actually have to cover. Offsets are from the outside edge and are
// listed for completeness; the reach math needs the pitch and the counts.
//   96:   offsets 14.38 / 11.24, pitch 9.0
//   384:  offsets 12.13 /  8.99, pitch 4.5
//   1536: offsets 11.005 / 7.865, pitch 2.25
well_cols       = 12;
well_rows       = 8;
well_pitch_mm   = 9.0;
well_a1_x_mm    = 14.38;
well_a1_y_mm    = 11.24;


// =============================================================================
// 2. THE ANGLE
// =============================================================================

// Tilt about the plate's SHORT axis: the +x end of the plate goes down, so
// liquid runs toward the column-12 end. deg.
//
// This is the single most expensive parameter in the file. Every millimeter of
// extra deck height and every millimeter of extra Z travel scales with it, and
// no amount of thinning the base buys any of that back (see stack_budget()).
// Shallow is not timid: at 7 deg the far well bottom is already 12 mm below the
// near one across a 96-well plate.
tilt_angle_deg = 7;

// Optional second tilt about the plate's LONG axis: the +y edge goes down.
// Nonzero turns the pooling point from an edge into a corner, at the cost of
// making the true slope steeper than either component (see max_slope_deg()).
// Default 0 -- single-axis tilt is easier to print, easier to seat, and easier
// to reason about, and most well geometries pool acceptably on one axis. deg.
cross_tilt_deg = 0;


// =============================================================================
// 3. CLEARANCE -- the parameter you tune, and the one nobody tunes enough
//
// The printed part is not the model. It comes out of the machine a different
// size, and the difference is not a constant you can look up:
//
//   - Shrinkage is material and grade dependent, and it is not published.
//     Filament technical data sheets generally do not carry a shrinkage figure
//     at all (checked directly on Polymaker PETG V2.0, Polymaker ASA, and
//     3DXTech 3DXMAX ABS -- none list one). Every per-material percentage
//     circulating online is a slicer default or a community measurement.
//   - Slicer defaults disagree with each other. OrcaSlicer ships filament_shrink
//     of 99.95% for one vendor's PLA, 99.85% PETG, 99.487% ABS and ASA, while
//     another vendor's profiles in the same repository ship 100% for all four.
//     That is a 0.5% disagreement on ABS between two profiles in one slicer.
//     0.5% of 127.76 mm is 0.64 mm, which is larger than the entire SLAS
//     footprint tolerance.
//   - Desktop FDM accuracy is quoted at about +/- 0.5% with a +/- 0.5 mm floor,
//     and tolerance scales with length, so a good calibration cube proves
//     nothing about a 128 mm pocket.
//   - The first layers are the least trustworthy region of the part. Squish
//     widens them; PrusaSlicer's own profiles ship 0.2 mm of elephant-foot
//     compensation for a 0.4 mm nozzle. The bottom of this fixture is exactly
//     where the registration feature lives.
//   - Repeatability is far better than accuracy -- a few hundredths of a
//     millimeter of run-to-run spread against tenths of accuracy error. That
//     asymmetry is what makes measure-and-compensate work: your printer
//     reproduces its own error reliably enough to cancel it.
//
// So: do not trust the nominal. Print the coupon, measure it with calipers
// against coupon_gauge_mm, and set the two clearances below from what you
// measured. Then reprint the coupon and confirm. That loop is the design
// process; the numbers below are only its starting point.
// =============================================================================

// Per side, between the plate and the pocket walls. This is a HOLE the plate
// drops into, and printers usually make holes undersize. mm.
clearance_mm = 0.35;

// Per side, between the fixture's registration skirt and the deck nest. This is
// a SHAFT going into someone else's hole, and printers usually make shafts
// oversize. Opposite sign of error, so it gets its own parameter. Do not slave
// it to clearance_mm even though the first-guess magnitude is similar. mm.
deck_clearance_mm = 0.30;


// =============================================================================
// 4. PLATFORM AND RETAINING LIPS
//
// LIP GEOMETRY -- what holds the plate, and what it is holding against
//
// The plate on the tilted seat wants to slide downhill. Whether friction alone
// would hold it is NOT COMPUTED anywhere in this file, and cannot be: the static
// coefficient between a printed lip and a molded polypropylene skirt is not
// published, changes with layer orientation and surface finish, and drops
// further when either surface is wet with buffer or ethanol. Design as if
// friction is zero. The lips are the only thing holding the plate.
//
// The plate therefore does not center itself in the pocket. It slides until it
// touches the two DOWNHILL corner lips, and those lips are the datum. Every
// reach number in this file is referenced to that seated position, not to a
// centered one.
//
// The lip height has a window, and both ends of it are real:
//
//   lower bound  the lip must stand proud enough to engage the flange face
//                rather than the plate's bottom edge break. SLAS figure Note 4
//                in all four dimensional standards states "Dimensions and
//                tolerances do not include draft" -- molded plates carry draft
//                angles the standard excludes and does not publish, so the
//                flange face is not vertical and the exact contact height
//                cannot be computed from the standard. A lip shorter than about
//                1.2 mm is contacting whatever the draft leaves it, which is
//                not a designed contact.
//
//   upper bound  the lip must stay BELOW the minimum flange height for the
//                declared variant, or it stops pushing on the flange and starts
//                pushing on the plate body -- into gripper jaw travel, into a
//                skirt chamfer that will cam the plate upward, or into the well
//                region. Minimum flange height is nominal minus 0.38 mm.
//
// lip_window_ok() checks that window against the declared variant and the
// report prints PASS or FAIL. On a SLAS 3 4.1 short-flange plate (2.41 nominal,
// 2.03 minimum) the default 3.0 mm lip FAILS, correctly -- short-flange plates
// need a shorter lip and there is not much window left.
//
// Corner lips rather than continuous rails, for three reasons:
//   1. SLAS 3 4.4 permits a single interruption on center of each long side.
//      A continuous long-side rail can land on that interruption; a corner lip
//      cannot, because the interruption edges are at least 47.8 mm from the
//      nearest part edge.
//   2. The mid-side gaps are where a gripper puts its jaws.
//   3. The downhill mid-side gap is the drain path for anything spilled.
//
// The lip is loaded as a transverse cantilever, and its root is a layer
// interface -- the weakest direction in an FDM part. That is why lip_thickness
// is generous and why the outer face tapers: the section modulus is highest
// exactly where the bending moment is. See README for the orientation argument.
// =============================================================================

// Corner lips are the default and the argued-for choice above. "full" exists
// because some reservoirs have no flange worth catching at a corner, and it
// keeps its own downhill drain slot.
lip_style = "corners";  // "corners" | "full"

lip_height_mm        = 3.0;   // downhill and side lips, above the seat plane, mm
lip_height_uphill_mm = 3.0;   // uphill lips -- reduce for gripper clearance, mm
lip_thickness_mm     = 2.4;   // at the lip top; 6 walls at a 0.4 mm nozzle, mm
lip_fillet_mm        = 1.2;   // extra thickness at the lip root, tapered, mm
lip_arm_mm           = 24.0;  // length of each corner-lip arm along the side, mm
lip_lead_in_mm       = 1.0;   // chamfer at the lip top inner edge, guides entry, mm
lip_min_engage_mm    = 1.2;   // lower bound of the lip height window, mm
lip_flange_margin_mm = 0.5;   // how far the lip stays below the minimum flange, mm

// Platform slab under the seat. Thin enough not to waste Z, thick enough that
// the seat is not a drum. mm.
platform_thickness_mm = 3.0;

// The seat is relieved in the middle so the plate lands on a perimeter band
// rather than on whatever high spot the print left. A printed plane cannot be
// flatter than the bed it was printed on, mesh leveling conforms the first layer
// TO the bed rather than correcting it, and a 128 mm seat that bulges 0.2 mm in
// the middle makes the plate rock. A relieved center converts an unknown
// flatness into a known three-sided contact. mm.
seat_band_mm         = 12.0;
seat_relief_depth_mm = 0.6;

// Drain channel from the relieved center out through the downhill edge. A spill
// that pools under a plate in a deck nest is both a contamination problem and a
// seating problem -- the plate floats on the film and stops sitting where it was
// taught. Liquid must have somewhere to go that is not "under the plate". mm.
drain_slot_w_mm = 8.0;


// =============================================================================
// 5. BASE AND DECK REGISTRATION
//
// UNMEASURED IS UNTRUSTED. deck_measured stays false until you have put calipers
// on your own deck position, and tilt_fixture() will not render until you flip
// it. See the SAFETY -- DECK CRASH note in the header for why this is a hard
// stop and not a warning.
// =============================================================================

deck_measured = false;

// "slas_skirt" -- the fixture's own base carries an ANSI/SLAS-1 footprint skirt
//                 and drops into the deck nest exactly the way a plate does.
//                 Preferred: it reuses location the deck already provides, and
//                 needs one measurement (the nest depth) rather than a hole
//                 pattern.
// "post"       -- locating posts drop into measured holes in the deck.
// "none"       -- NOTHING LOCATES THE FIXTURE. Only defensible when the fixture
//                 is clamped or bolted by other means. The report says so out
//                 loud every render.
registration_style = "slas_skirt";

// MEASURE. Depth from the deck nest rim down to the surface a plate's own
// footprint rests on. Negative means unmeasured. mm.
deck_nest_depth_mm = -1;

// MEASURE. Width of the nest rim, if the fixture is to rest on it. Negative
// means unmeasured. mm.
deck_nest_rim_w_mm = -1;

// Which surface carries the fixture's weight. These are mutually exclusive and
// a fixture that is unsure which one it is will rock, because both cannot be in
// contact at once on a printed part.
//   "nest_floor" -- the skirt runs deeper than the nest and the body shoulder
//                   floats clear of the rim by seat_relief_mm.
//   "nest_rim"   -- the skirt runs shallower and the body shoulder lands on the
//                   rim, with the skirt bottom floating.
seats_on       = "nest_floor";
seat_relief_mm = 0.4;  // the deliberate gap on whichever surface is NOT carrying, mm

// Registration skirt wall. Also the minimum wall anywhere in the part. mm.
wall_mm = 2.4;

// Post registration, if registration_style is "post". All MEASURED off your
// deck. Negative means unmeasured and the model will refuse. mm.
//
// TWO posts, not four. Four posts in four holes over-constrain the part: with
// desktop FDM positional error on a 100 mm span, at least one post binds and the
// fixture seats on three of them, rocking. Two posts locate position and
// rotation, which is all that is needed. If the deck offers four holes, use two
// and leave the others empty; if you must use more, one hole has to become a
// slot, and this model does not cut slots for you.
reg_post_d_mm       = -1;
reg_post_pitch_x_mm = -1;
reg_post_h_mm       = -1;

// How deep the registration feature engages the deck. Derived for the skirt
// case, explicit for posts. Reported so it can be sanity-checked against the
// deck: a 1 mm engagement is decoration, not registration. mm.
reg_engage_min_mm = 2.0;

// Flat slab spanning the whole footprint, under the wedge. Takes the
// registration loads and gives the wedge something continuous to sit on. mm.
base_thickness_mm = 4.0;

// Minimum wedge thickness at the LOW corner, above the base slab. Without it the
// wedge tapers to a knife edge that will not print and will not survive being
// picked up. mm.
min_lift_mm = 2.0;

// Extra footprint on the body beyond the projected platform, so the wedge walls
// slope slightly inward going up and never overhang. mm.
body_margin_mm = 0.6;


// =============================================================================
// 6. LOW PROFILE
//
// Why total stack height matters, and what it is actually made of.
//
// Raising the plate spends three budgets at once:
//   - the head's Z envelope. The tip has to reach the bottom of the LOWEST well
//     while the head still has travel left, and the head has to clear the
//     HIGHEST point of the plate on every move in and out.
//   - the gripper's approach. A plate mover taught to grab a plate at deck
//     height will now find it 25 mm higher and tilted. The jaws must still close
//     on the flange, and the approach path must clear the lips.
//   - the neighbors. This body is wider than the plate it holds. Check the
//     adjacent deck positions before you print, not after.
//
// The load-bearing fact is in stack_budget(): the fixed part of the stack (base,
// lift, platform slab) is a few millimeters, and the angle-driven part is the
// plate length times sin(tilt). At 7 degrees across a 128 mm pocket that is
// about 15.7 mm, and low_profile does not touch it. You cannot thin your way
// out of the angle. If the stack does not fit, the angle comes down or the
// fixture does not get used.
// =============================================================================

low_profile = false;

low_profile_base_thickness_mm     = 2.4;
low_profile_min_lift_mm           = 1.2;
low_profile_platform_thickness_mm = 2.0;


// =============================================================================
// 7. TEST COUPON
//
// A 90 x 55 mm part that carries the registration skirt corner, one downhill
// corner lip cut from the real geometry, and a caliper witness block. It prints
// in minutes instead of hours and it is the only thing standing between a wrong
// clearance and a wasted afternoon.
//
// The coupon validates FEATURES, not the whole-footprint fit. It tells you what
// your printer did to a wall thickness, a corner radius, a vertical face and a
// 20 mm nominal. It cannot tell you whether a 127.76 mm skirt fits your nest,
// because it is not 127.76 mm long. Measure the gauge, compute your machine's
// actual scale error, apply it to the full length, and only then print the
// fixture.
// =============================================================================

coupon_gauge_mm    = 20.0;  // nominal witness block in X and Y. Measure both. mm
coupon_gauge_z_mm  = 10.3;  // deliberately not a multiple of a common layer height, mm
coupon_pad_t_mm    = 2.0;   // common pad so the pieces stay together, mm
coupon_sample_mm   = 34.0;  // how much of each real corner to keep, mm


// =============================================================================
// 8. DERIVED GEOMETRY -- functions, never stored constants
// =============================================================================

function r2(v) = round(v * 100) / 100;

// Low-profile substitutions.
function base_t()  = low_profile ? low_profile_base_thickness_mm : base_thickness_mm;
function lift()    = low_profile ? low_profile_min_lift_mm : min_lift_mm;
function plat_t()  = low_profile ? low_profile_platform_thickness_mm : platform_thickness_mm;

// The pocket. The footprint tolerance is on the OVERALL dimension so it is added
// once; the clearance is per side so it is added twice. Conflating the two is
// the most common way to get this wrong by half a millimeter.
function pocket_len() = plate_len_mm + plate_footprint_tol_mm + 2 * clearance_mm;
function pocket_wid() = plate_wid_mm + plate_footprint_tol_mm + 2 * clearance_mm;
function pocket_r()   = plate_corner_r_max_mm + clearance_mm;

// The platform carrying the pocket and the lips, measured IN the seat plane.
function plat_len() = pocket_len() + 2 * (lip_thickness_mm + lip_fillet_mm);
function plat_wid() = pocket_wid() + 2 * (lip_thickness_mm + lip_fillet_mm);
function plat_r()   = pocket_r() + lip_thickness_mm + lip_fillet_mm;

// Unit normal of the seat plane, z component. Everything vertical scales by it.
function seat_nz() = cos(cross_tilt_deg) * cos(tilt_angle_deg);

// TRUE slope of the seat plane. With both tilts nonzero this is steeper than
// either component, which is the trap in compound tilt: two comfortable-sounding
// 6 degree tilts make an 8.5 degree plane.
function max_slope_deg() = acos(seat_nz());

// ---------------------------------------------------------------------------
// tip_reach_delta_mm()
//
// THE number that decides whether the tips can still bottom out.
//
// Two well bottoms separated by dx along the plate's long axis and dy along its
// short axis are separated vertically, once the plate is tilted, by
//
//     dz = dx * sin(tilt) + dy * sin(cross) * cos(tilt)
//
// sin, not tan: the wells are separated by dx measured ALONG the plate, which is
// now the hypotenuse rather than the deck projection. Using tan overstates the
// drop, and at shallow angles the two differ by less than a percent, which is
// exactly the kind of error that survives review.
//
// The plate seats against the DOWNHILL corner lips, so the near corner is the A1
// end and the far corner is the last well of the last column. The head has to
// travel tip_reach_delta_mm() further down at the far corner than at the near
// one, on top of whatever the fixture already added. If the head is near the end
// of its Z stroke at the near corner -- which is where a deep-well plate on a
// tall fixture puts it -- the far corner is where it runs out.
//
// Span is between well CENTERS, from SLAS 4: (cols - 1) * pitch by
// (rows - 1) * pitch. For a 96-well plate that is 99.0 x 63.0 mm, not the
// 127.76 x 85.48 footprint. Using the footprint overstates the drop by about
// 30%, which sounds conservative until it talks somebody out of a workable
// angle.
// ---------------------------------------------------------------------------
function well_span_x_mm() = (well_cols - 1) * well_pitch_mm;
function well_span_y_mm() = (well_rows - 1) * well_pitch_mm;

function drop_along_seat_mm(dx, dy) =
  dx * sin(tilt_angle_deg) + dy * sin(cross_tilt_deg) * cos(tilt_angle_deg);

function tip_reach_delta_mm() =
  drop_along_seat_mm(well_span_x_mm(), well_span_y_mm());

// Same computation across the plate footprint rather than the well grid. This is
// the one that matters for the plate's own corners and for the lips.
function footprint_drop_mm() = drop_along_seat_mm(pocket_len(), pocket_wid());

// Height of the seat plane under a given well center, in the deck frame. The
// plate seats against the DOWNHILL lips, so a well's height is set by how far it
// sits from the downhill edges -- which is where the SLAS 4 first-well offsets
// stop being trivia and start being the thing that positions the tip. Column and
// row are 1-based; column 1 is the A1 end, which is uphill.
function well_dist_from_downhill_x_mm(col) =
  plate_len_mm - (well_a1_x_mm + (col - 1) * well_pitch_mm);
function well_dist_from_downhill_y_mm(row) =
  plate_wid_mm - (well_a1_y_mm + (row - 1) * well_pitch_mm);

function well_seat_z_mm(col, row) =
  plate_low_seat_z()
  + drop_along_seat_mm(well_dist_from_downhill_x_mm(col),
                       well_dist_from_downhill_y_mm(row));

// ---------------------------------------------------------------------------
// Vertical stack, referenced to the plane a plate's own footprint would rest on
// in this deck position -- so a plate sitting flat has its bottom at z = 0 and
// every number below is directly comparable to "no fixture".
// ---------------------------------------------------------------------------

// How far the registration feature engages the deck, and where the body starts.
function skirt_h_mm() =
  registration_style != "slas_skirt" ? 0
  : deck_nest_depth_mm < 0 ? 0
  : seats_on == "nest_floor" ? deck_nest_depth_mm + seat_relief_mm
  : deck_nest_depth_mm - seat_relief_mm;

function body_bottom_z() = registration_style == "slas_skirt" ? skirt_h_mm() : 0;
function body_top_z()    = body_bottom_z() + base_t();

// Seat plane at the low (downhill) corner of the PLATFORM.
function seat_low_z() = body_top_z() + lift() + plat_t() * seat_nz();

// Seat plane under the plate's own low and high corners. The plate is inset from
// the platform edge by one lip thickness plus its fillet, so its low corner sits
// a hair above the platform's.
function plate_low_seat_z() =
  seat_low_z() + drop_along_seat_mm(lip_thickness_mm + lip_fillet_mm,
                                    lip_thickness_mm + lip_fillet_mm);

function plate_high_seat_z() = plate_low_seat_z() + footprint_drop_mm();

// Highest point of the loaded plate above the deck datum. Valid only if
// plate_height_mm is this plate's real height -- see the SLAS 2 note in section 1.
function stack_top_mm() = plate_high_seat_z() + plate_height_mm * seat_nz();

// What the stack is made of. Returns [fixed, angle_driven, plate].
function stack_budget() = [
  seat_low_z(),                       // skirt + base + lift + platform slab
  footprint_drop_mm(),                // set by the angle alone
  plate_height_mm * seat_nz()         // the plate itself
];

// How much taller this deck position became versus a plate sitting flat.
function stack_penalty_mm() = stack_top_mm() - plate_height_mm;

// Body footprint. Sized from the projection of the tilted platform plus a
// margin, so the wedge walls lean inward going up and never overhang.
function body_len() = plat_len() * cos(tilt_angle_deg) + 2 * body_margin_mm;
function body_wid() = plat_wid() * cos(cross_tilt_deg) + 2 * body_margin_mm;
function body_r()   = plat_r();

// How far the body overhangs the SLAS skirt on each side. This is what collides
// with the next deck position.
function overhang_x_mm() = (body_len() - plate_len_mm) / 2;
function overhang_y_mm() = (body_wid() - plate_wid_mm) / 2;

// Registration skirt outline: an SLAS footprint minus clearance, so it drops
// into a nest built for a plate.
function skirt_len() = plate_len_mm - 2 * deck_clearance_mm;
function skirt_wid() = plate_wid_mm - 2 * deck_clearance_mm;
function skirt_r()   = 3.18;  // SLAS 1 nominal; a shaft wants the SMALL radius

// The lip height window, from the declared flange variant.
function flange_min_mm() = plate_flange_h_mm - plate_flange_tol_mm;
function lip_max_mm()    = flange_min_mm() - lip_flange_margin_mm;
function lip_window_ok() =
  lip_height_mm >= lip_min_engage_mm && lip_height_mm <= lip_max_mm();

// Tip-over about the downhill lip contact line. Refuses without a measured CG.
function tip_over_angle_deg() =
  plate_cg_height_mm <= 0 ? undef
  : atan((plate_len_mm / 2) / plate_cg_height_mm);

// Pivot height for the platform rotation, chosen so the platform's bottom-face
// low corner lands exactly lift() above the base slab.
function pivot_z() =
  body_top_z() + lift()
  + (plat_len() / 2) * sin(tilt_angle_deg)
  + (plat_wid() / 2) * sin(cross_tilt_deg) * cos(tilt_angle_deg)
  + plat_t() * seat_nz();


// =============================================================================
// 9. REPORT
//
// Printed on every render, including the coupon. Anything that depends on an
// unmeasured input says NOT COMPUTED and names the parameter.
// =============================================================================

module report() {
  echo("");
  echo("=== tilt_module.scad ===");
  echo(str("part                    : ", part,
           low_profile ? "  (low profile)" : ""));
  echo("");
  echo("--- angle ---");
  echo(str("tilt / cross            : ", tilt_angle_deg, " / ", cross_tilt_deg, " deg"));
  echo(str("true seat plane slope   : ", r2(max_slope_deg()), " deg"));
  echo("");
  echo("--- reach ---");
  echo(str("well grid               : ", well_cols, " x ", well_rows,
           " at ", well_pitch_mm, " mm pitch"));
  echo(str("well center span        : ", r2(well_span_x_mm()), " x ",
           r2(well_span_y_mm()), " mm"));
  echo(str("TIP REACH DELTA         : ", r2(tip_reach_delta_mm()),
           " mm extra Z at the far corner"));
  echo(str("seat under first well   : ", r2(well_seat_z_mm(1, 1)),
           " mm above the deck datum  (uphill, shallowest)"));
  echo(str("seat under last well    : ", r2(well_seat_z_mm(well_cols, well_rows)),
           " mm above the deck datum  (downhill, deepest)"));
  echo(str("plate corner drop       : ", r2(footprint_drop_mm()), " mm"));
  echo("");
  echo("--- vertical stack, versus a plate sitting flat ---");
  echo(str("  fixed  (base+lift+slab): ", r2(stack_budget()[0]), " mm"));
  echo(str("  angle  (irreducible)   : ", r2(stack_budget()[1]), " mm"));
  echo(str("  plate                  : ", r2(stack_budget()[2]), " mm"));
  echo(str("top of plate above datum : ", r2(stack_top_mm()), " mm"));
  echo(str("EXTRA Z CONSUMED         : ", r2(stack_penalty_mm()),
           " mm -- head envelope and gripper approach must both still clear"));
  echo(str("plate height basis       : ", plate_height_mm == 14.35
           ? "SLAS 2 standard-height nominal -- WRONG for deep-well/PCR/reservoir"
           : "operator supplied"));
  echo("");
  echo("--- footprint ---");
  echo(str("pocket                  : ", r2(pocket_len()), " x ", r2(pocket_wid()),
           " mm  (tol once, clearance twice)"));
  echo(str("body                    : ", r2(body_len()), " x ", r2(body_wid()), " mm"));
  echo(str("overhang beyond SLAS     : ", r2(overhang_x_mm()), " mm per side in X, ",
           r2(overhang_y_mm()), " mm per side in Y -- CHECK NEIGHBORING DECK POSITIONS"));
  echo("");
  echo("--- lips ---");
  echo(str("flange variant declared : ", plate_flange_h_mm, " +/- ", plate_flange_tol_mm,
           " mm  (minimum ", r2(flange_min_mm()), ")"));
  echo(str("lip height window       : ", lip_min_engage_mm, " to ", r2(lip_max_mm()), " mm"));
  echo(str("lip height ", lip_height_mm, " mm       : ",
           lip_window_ok() ? "PASS"
           : lip_height_mm < lip_min_engage_mm
             ? "FAIL -- too short to engage the flange face"
             : "FAIL -- taller than the minimum flange, will push on the plate body"));
  echo(str("static hold without lips: NOT COMPUTED -- friction coefficient between a ",
           "printed lip and a molded skirt is unpublished and changes when wet. ",
           "Design as if it is zero."));
  echo(str("lip load                : NOT COMPUTED -- no SLAS standard specifies ",
           "plate mass. Weigh your loaded plate."));
  echo(str("tip-over angle          : ",
           plate_cg_height_mm <= 0
             ? "NOT COMPUTED -- set plate_cg_height_mm from a measurement"
             : str(r2(tip_over_angle_deg()), " deg, versus ", r2(max_slope_deg()),
                   " deg of tilt")));
  echo("");
  echo("--- deck registration ---");
  echo(str("style                   : ", registration_style));
  echo(str("deck measured           : ", deck_measured ? "yes" : "NO"));
  echo(str("nest depth              : ", deck_nest_depth_mm < 0
           ? "NOT MEASURED" : str(deck_nest_depth_mm, " mm")));
  echo(str("skirt engagement        : ", skirt_h_mm() <= 0
           ? "NOT COMPUTED"
           : str(r2(skirt_h_mm()), " mm",
                 skirt_h_mm() < reg_engage_min_mm
                   ? "  -- BELOW reg_engage_min_mm, this is decoration not registration"
                   : "")));
  echo(str("carried by              : ", seats_on));
  echo(str("shoulder on rim         : ",
           seats_on != "nest_rim" ? "n/a -- shoulder floats by seat_relief_mm"
           : deck_nest_rim_w_mm < 0
             ? "NOT COMPUTED -- set deck_nest_rim_w_mm from a measurement"
             : str(r2(min(overhang_x_mm(), overhang_y_mm())), " mm of shoulder over a ",
                   deck_nest_rim_w_mm, " mm rim: ",
                   min(overhang_x_mm(), overhang_y_mm()) <= deck_nest_rim_w_mm
                     ? "PASS" : "FAIL -- shoulder overhangs the rim and will rock")));
  if (registration_style == "none")
    echo("HAZARD                  : registration_style is none. Nothing locates this fixture. A fixture that can move under gantry acceleration is a deck crash and a re-teach.");
  echo("");
  echo("--- what is not modeled ---");
  echo("recovery improvement    : NOT MODELED. Weigh it. See hardware/README.md.");
  echo("sample contact          : NOT QUALIFIED. This is a holder; the plate is the barrier.");
  echo("");
}


// =============================================================================
// 10. GEOMETRY
// =============================================================================

// Rounded rectangle, centered. Radius is clamped so a small part cannot produce
// a degenerate profile.
module rrect(l, w, r) {
  rr = min(r, l / 2 - 0.01, w / 2 - 0.01);
  offset(r = rr) square([l - 2 * rr, w - 2 * rr], center = true);
}

// Places children from the seat-plane frame (origin at the platform center, seat
// plane at z = 0, +x downhill) into the deck frame.
module tilt_place() {
  translate([0, 0, pivot_z()])
    rotate([-cross_tilt_deg, tilt_angle_deg, 0])
      children();
}

// The platform slab. Seat surface is its top face, at z = 0 in the seat frame.
module platform_slab() {
  translate([0, 0, -plat_t()])
    linear_extrude(height = plat_t())
      rrect(plat_len(), plat_wid(), plat_r());
}

// Full lip ring at height h, outer face tapering inward going up so the root is
// thicker than the tip. The inner face stays vertical: that is the plate contact
// and it should be a face, not a slope.
module lip_ring(h) {
  difference() {
    linear_extrude(height = h,
                   scale = [(plat_len() - 2 * lip_fillet_mm) / plat_len(),
                            (plat_wid() - 2 * lip_fillet_mm) / plat_wid()])
      rrect(plat_len(), plat_wid(), plat_r());
    translate([0, 0, -1])
      linear_extrude(height = h + 2)
        rrect(pocket_len(), pocket_wid(), pocket_r());
  }
}

// Lead-in chamfer at the top inner edge of a lip of height h. Cut per lip rather
// than once globally, because the uphill lips may be shorter and a single cut at
// one height would either miss them or take a second bite out of the tall ones.
module lip_lead_in_cut(h) {
  translate([0, 0, h - lip_lead_in_mm])
    linear_extrude(height = lip_lead_in_mm + 0.1,
                   scale = [(pocket_len() + 2 * lip_lead_in_mm) / pocket_len(),
                            (pocket_wid() + 2 * lip_lead_in_mm) / pocket_wid()])
      rrect(pocket_len(), pocket_wid(), pocket_r());
}

// One corner lip, in the (+x, +y) quadrant, cut out of the full ring so its
// cross-section and corner radius are exactly the ring's.
module lip_corner_pp(h) {
  ox = plat_len() / 2;
  oy = plat_wid() / 2;
  band = lip_thickness_mm + lip_fillet_mm;
  intersection() {
    difference() {
      lip_ring(h);
      lip_lead_in_cut(h);
    }
    union() {
      translate([ox - lip_arm_mm, oy - band - 1, -1])
        cube([lip_arm_mm + 1, band + 2, h + 2]);
      translate([ox - band - 1, oy - lip_arm_mm, -1])
        cube([band + 2, lip_arm_mm + 1, h + 2]);
    }
  }
}

// Four corner lips. Downhill corners (+x) get lip_height_mm; uphill corners get
// lip_height_uphill_mm, which can be dropped for gripper clearance because the
// uphill lip only does work during transport and placement.
module lips_all() {
  if (lip_style_is_corners()) {
    lip_corner_pp(lip_height_mm);                                        // +x +y downhill
    mirror([0, 1, 0]) lip_corner_pp(lip_height_mm);                      // +x -y downhill
    mirror([1, 0, 0]) lip_corner_pp(lip_height_uphill_mm);               // -x +y uphill
    mirror([1, 0, 0]) mirror([0, 1, 0])
      lip_corner_pp(lip_height_uphill_mm);                               // -x -y uphill
  } else {
    difference() {
      lip_ring(lip_height_mm);
      lip_lead_in_cut(lip_height_mm);
      // Keep the downhill mid-side drain open even on a continuous ring.
      translate([plat_len() / 2 - 20, -drain_slot_w_mm / 2, -1])
        cube([40, drain_slot_w_mm, lip_height_mm + 2]);
    }
  }
}

function lip_style_is_corners() = lip_style == "corners";

// Relieved seat center plus the downhill drain channel.
module seat_relief_cut() {
  translate([0, 0, -seat_relief_depth_mm])
    linear_extrude(height = seat_relief_depth_mm + 1)
      union() {
        rrect(pocket_len() - 2 * seat_band_mm,
              pocket_wid() - 2 * seat_band_mm,
              max(pocket_r() - seat_band_mm, 1));
        // channel out through the downhill edge
        translate([plat_len() / 4, 0])
          square([plat_len() / 2 + 2, drain_slot_w_mm], center = true);
      }
}

// Flat slab spanning the whole footprint.
module body_slab() {
  translate([0, 0, body_bottom_z()])
    linear_extrude(height = base_t())
      rrect(body_len(), body_wid(), body_r());
}

// The wedge: a hull from the body slab top to the tilted platform's bottom face.
module wedge() {
  hull() {
    tilt_place()
      translate([0, 0, -plat_t()])
        linear_extrude(height = 0.01)
          rrect(plat_len(), plat_wid(), plat_r());
    translate([0, 0, body_top_z() - 0.01])
      linear_extrude(height = 0.01)
        rrect(body_len(), body_wid(), body_r());
  }
}

// SLAS-footprint registration skirt: a continuous hollow wall under the body.
// SLAS 1 4.1.1.3 requires the footprint be continuous and uninterrupted around
// the base. So does this one, for the same reason -- a gap snags a nest.
module skirt() {
  h = skirt_h_mm();
  if (h > 0)
    linear_extrude(height = h)
      difference() {
        rrect(skirt_len(), skirt_wid(), skirt_r());
        rrect(skirt_len() - 2 * wall_mm, skirt_wid() - 2 * wall_mm,
              max(skirt_r() - wall_mm, 0.5));
      }
}

// Locating posts, when the deck offers holes rather than a nest. Two, on the
// long axis. See the reg_post_* comment for why not four.
module posts() {
  if (registration_style == "post" && reg_post_d_mm > 0)
    for (sx = [-1, 1])
      translate([sx * reg_post_pitch_x_mm / 2, 0, -reg_post_h_mm])
        cylinder(h = reg_post_h_mm + 0.01,
                 d = reg_post_d_mm - 2 * deck_clearance_mm);
}

module registration_feature() {
  if (registration_style == "slas_skirt") skirt();
  else if (registration_style == "post") posts();
}

// Everything above the deck, without the registration feature. Factored out so
// the coupon can cut a corner from the identical geometry rather than a
// re-derivation of it -- a coupon that models the feature separately validates
// the coupon, not the fixture.
module upper_solid() {
  difference() {
    union() {
      body_slab();
      wedge();
      tilt_place() union() {
        platform_slab();
        lips_all();
      }
    }
    tilt_place() seat_relief_cut();
  }
}

module tilt_fixture() {
  assert(deck_measured,
         "REFUSING TO RENDER: deck_measured is false. An unlocated fixture is a deck crash. Put calipers on the deck position, set deck_nest_depth_mm (or the reg_post_* values), then set deck_measured = true. Render part=\"coupon\" first -- it has no such requirement.");
  assert(registration_style != "slas_skirt" || deck_nest_depth_mm > 0,
         "REFUSING TO RENDER: registration_style is \"slas_skirt\" but deck_nest_depth_mm is unmeasured.");
  assert(registration_style != "post" ||
         (reg_post_d_mm > 0 && reg_post_pitch_x_mm > 0 && reg_post_h_mm > 0),
         "REFUSING TO RENDER: registration_style is \"post\" but one or more reg_post_* values are unmeasured.");

  difference() {
    union() {
      registration_feature();
      upper_solid();
    }
    // Trim anything that strayed below the registration datum.
    translate([-400, -400, -400 + min(0, -reg_post_h_mm)])
      cube([800, 800, 400]);
  }
}


// =============================================================================
// 11. TEST COUPON
// =============================================================================

// The downhill (+x, +y) corner of the real fixture, trimmed to a printable pad.
// Cut from upper_solid() rather than re-modeled, so what you measure on the
// coupon is what the fixture will do. A coupon built from its own geometry
// validates the coupon.
module coupon_seat_corner() {
  s = coupon_sample_mm;
  z0 = body_bottom_z();
  ztop = seat_low_z() + lip_height_mm + 2;
  translate([-(body_len() / 2 - s), -(body_wid() / 2 - s), -z0])
    intersection() {
      upper_solid();
      translate([body_len() / 2 - s, body_wid() / 2 - s, z0 - 0.01])
        cube([s + 2, s + 2, ztop - z0 + 1]);
    }
}

// A corner of the registration skirt at its real wall thickness and radius.
module coupon_skirt_corner() {
  s = coupon_sample_mm;
  h = max(skirt_h_mm(), 4.0);  // if the nest is unmeasured, print a 4 mm sample
  translate([-(skirt_len() / 2 - s), -(skirt_wid() / 2 - s), 0])
    intersection() {
      linear_extrude(height = h)
        difference() {
          rrect(skirt_len(), skirt_wid(), skirt_r());
          rrect(skirt_len() - 2 * wall_mm, skirt_wid() - 2 * wall_mm,
                max(skirt_r() - wall_mm, 0.5));
        }
      translate([skirt_len() / 2 - s, skirt_wid() / 2 - s, -1])
        cube([s + 2, s + 2, h + 2]);
    }
}

// Witness block. Measure all three axes with calipers. X and Y give the printer's
// in-plane scale error, which is what clearance_mm and deck_clearance_mm are
// compensating for. Z gives layer quantization plus first-layer squish, which is
// a constant offset on total height rather than a percentage, so do not convert
// the Z error to a percent and apply it to a length.
//
// coupon_gauge_z_mm is deliberately NOT a multiple of any common layer height.
// A 20.0 mm tall gauge at a 0.2 mm layer is an exact multiple and hides the
// quantization entirely; total height is forced to first_layer + n * layer, so a
// height that lands between two layers is the only one that shows you the error.
module coupon_gauge() {
  cube([coupon_gauge_mm, coupon_gauge_mm, coupon_gauge_z_mm]);
}

module test_coupon() {
  s     = coupon_sample_mm + 2;
  pad_l = 2 * s + coupon_gauge_mm + 22;
  pad_w = s + 8;
  difference() {
    union() {
      cube([pad_l, pad_w, coupon_pad_t_mm]);
      translate([4, 4, coupon_pad_t_mm]) coupon_seat_corner();
      translate([s + 10, 4, coupon_pad_t_mm]) coupon_skirt_corner();
      translate([2 * s + 16, 4, coupon_pad_t_mm]) coupon_gauge();
    }
    // Nothing below the pad.
    translate([-10, -10, -20]) cube([pad_l + 20, pad_w + 20, 20]);
  }
}


// =============================================================================
// 12. TOP LEVEL
// =============================================================================

report();

if (part == "fixture" || part == "both") tilt_fixture();
if (part == "coupon" || part == "both")
  translate([part == "both" ? body_len() / 2 + 30 : 0, 0, 0]) test_coupon();
