# Capture to policy

How to get from a camera pointed at a bench to an arm that performs a lab manipulation
task, and the one decision at the front that determines whether the rest is engineering or
research.

This guide assumes a bench scientist with a task worth automating, an arm on the bench or
on a quote, a camera, and the printer from `docs/PRINTED_FIXTURES.md`. It is opinionated,
because the failure mode here is not a wrong parameter -- it is spending four months
collecting the wrong kind of data.

Everything below carries where it came from. `[EXP]` means measured in a published
experiment on real hardware; `[EXP-1]` means the same, from a single fetch that was not
independently re-verified -- one confidence step lower; `[SIM]` means measured in
simulation only, which is a different claim and gets confused with the first one constantly;
`[DS]` means read directly out of a manufacturer document; `[VENDOR]` means a vendor or
third-party claim nobody independent has checked; `[ARITH]` means this guide computed it
from stated inputs and you can redo it; `[PRACTICE]` means engineering convention with no
measurement behind it. Numbers with no mark do not appear. Where a number would be useful
and does not exist, this guide says what measurement would produce it rather than filling
the hole.

Two refusals are in force throughout, and they are the reason several obvious sentences are
missing. **This guide states no success rate for any task you might attempt**, because none
has been published for a plate on a deck and extrapolating one from a paper about folding
shirts would be a fabricated number wearing a citation. And **it presents no demonstration
count as a requirement**, because the only controlled study of that question found the
count is not the variable that matters.

---

## 1. The capture decision

This is the first decision and the largest one. Everything in 2 through 8 is downstream of
it, and it is the one that gets made by accident -- usually by whoever already owns a
camera.

**Recommendation: capture with actions. Teleoperate the arm, or hand-guide it, and record
what the controller commanded. Do not plan to recover actions from third-person video of a
person.**

### What the two options actually are

A policy is a function from observation to action. Training one by imitation needs pairs.
The question is where the action column comes from.

*Capture with actions.* A person drives the arm -- a leader arm, a gamepad, a handheld
gripper, or a hand on the link with the brakes released -- and the system logs the
commanded action in the robot's own action space at the controller's rate, alongside the
images. The action column is recorded, not inferred. Every ambiguity about what the person
"meant" was resolved by the arm actually moving.

*Third-person video.* A camera watches a person do the task. The recording contains pixels.
It contains no actions at all, in the literal sense: there is no field in it that says what
joint command or end-effector delta produced the next frame. Getting one requires
estimating hand pose, mapping a human hand onto a robot gripper, and assuming the resulting
trajectory is something the arm can execute.

**That second step is not a conversion. It is an additional inference with its own error
and no validation on your task.** The distinction matters because "convert the video to
actions" is how the pipeline gets described, and a conversion sounds like a unit change.

### Why retargeting is a research step, not a preprocessing step

Three independent lines of evidence, of decreasing abstraction.

**It is not always possible, in principle.** The gap between learning from demonstrations
(state-action pairs) and learning from observation (states only) is exactly the disagreement
between the imitator's inverse dynamics model and the expert's, upper-bounded by a negative
causal entropy term `[EXP: NeurIPS 2019, arXiv:1910.04417]`. And an inverse dynamics model
is not well-defined at all unless the transition is injective -- unless no two actions can
produce the same next state from the same state `[arXiv:2102.10769]`. Where the dynamics are
non-injective the action is unrecoverable from video as a matter of mathematics, not of
model quality.

Read that against a lab bench, because the non-injective cases are the ones you care about:

- A redundant arm. A 7-DOF arm reaches one end-effector pose through a continuum of joint
  configurations. The video shows the pose; it does not determine the configuration.
- Force applied against a rigid constraint. Pressing a plate down into a nest at 5 N and at
  25 N produce the same next image. The plate is seated in both.
- Anything where the visible state does not change. Holding a seal, maintaining a grip,
  waiting for a magnet. The action is nonzero and the frames are identical.

Seating labware, retaining a plate, and holding a lid are the operations a lab fixture
exists to make repeatable, and they are precisely the ones video cannot label.

**The measured exchange rate.** Phantom (CoRL 2025, arXiv:2503.00779) trains policies from
human RGBD video with zero robot demonstrations, by extracting end-effector pose from hand
mesh estimation plus segmentation plus ICP against the depth cloud, then inpainting a
rendered robot over the human arm. On a sweeping task it reports a direct head-to-head
`[EXP]`:

| capture | episodes | reported success |
| --- | --- | --- |
| teleoperated | 50 | 52% |
| human video | 50 | 44% |
| teleoperated | 100 | 88% |
| human video | 300 | 84% |

Roughly 3x the human episodes to *approach*, not beat, the teleop number. This guide could
not confirm the trial count behind those four rows specifically; the paper's other per-task
rates are over 25 rollouts each, where one trial moves a rate by 4 percentage points
`[ARITH]`. Treat the ordering as the finding and the digits as coarse.

Note also what the numbers do to the cost argument, which is the usual reason people choose
video. Handheld-gripper capture in UMI (RSS 2024, arXiv:2402.10329) ran *faster* than
bare-hand human collection, which came in at 48% and 64% of the gripper's rate on two tasks
`[EXP]`. Cheap-to-collect is not the same as cheap-per-unit-of-policy.

**Hand pose quality is the binding constraint, and it is where "just use internet video"
fails.** A 2026 cotraining study (arXiv:2606.06627) injected calibrated Gaussian noise into
its triangulated hand labels and watched mean success fall from 48.3 +/- 19.6% to 30.0 +/-
13.1% at 0.5 sigma to 20.0 +/- 6.5% at 1.0 sigma. Substituting a real monocular hand
estimator for multi-view triangulation produced 185.67 mm mean per-joint position error and
dropped mean success from 41.5% to 24.7% `[EXP]`. Independently, Human2Sim2Robot (CoRL 2025,
arXiv:2504.12609) reports hand pose errors from human video "as large as 20-30 cm" `[EXP]`
and responds by discarding the human's actions entirely -- using only the object's 6D pose
trajectory as a reward and a single pre-manipulation hand pose to seed reinforcement
learning.

The multi-view rig, the depth camera, or the glasses are doing the work in every one of
these results. Monocular third-person video is the degraded case, and it is the case a lab
would actually have.

**Even a perfect estimate does not give you an executable trajectory.** Human2Sim2Robot
states that even with perfect pose estimates, direct retargeting "often results in
suboptimal robot trajectories due to morphological differences." DexMachina (arXiv:2505.24853)
puts it physically: across six dexterous hands, "kinematic retargeting can produce
human-like hand motions, but when we play the retargeting results in simulation, they are
not feasible for completing the task" `[SIM]`. A whole method (SPIDER, arXiv:2511.09484)
exists to repair exactly this gap.

**The one signal video cannot contain, isolated and measured.** UMI puts the actual robot
gripper in the human's hand so observation and action spaces match by construction.
Ablating relative inter-gripper proprioception dropped bimanual cloth folding from 70% to
30% success `[EXP]`. Proprioception is not in any video of anything.

### The honest counterweight

Human video is not useless, and the recommendation is not "never touch it." What the
measurements support is that it helps as *pretraining or cotraining*, and that its help
shrinks as your own action-labeled data grows.

- The 2026 cotraining study measured the gain against robot-only training as +29.7 points
  at 3 training environments, +21.1 at 5, and +12.5 at 10 -- where the last one is roughly
  one standard deviation of its own error bars `[EXP]`. The widely quoted "+29.7%" is the
  low-robot-data regime only.
- LAPA (ICLR 2025, arXiv:2410.11758) learns latent actions from video and pretrains on
  them, then *finetunes on action-labeled robot data*. Its own stated limitation is that it
  "underperforms compared to action pretraining when it comes to fine-grained motion
  generation tasks like grasping" `[EXP]` -- the residual deficit lands exactly on fine
  motor control, which is what a tip in a well is.
- Latent actions are not reliably identifiable from video alone: with action-correlated
  distractors present, supplying ground-truth actions for as few as 2.5% of the dataset
  improved downstream performance by 4.2x on average `[SIM: ICML 2025, arXiv:2502.00379]`.

And the summary that should settle the decision: **every published result this guide could
verify, in which a video-trained policy actually executes a real task, injects action
information somewhere.** Phantom derives explicit end-effector pose and gripper width from
RGBD plus a hand mesh. LAPA finetunes on action-labeled robot data. UMI and its successors
put real gripper or exoskeleton hardware on the human hand. Human2Sim2Robot discards the
human's actions and runs reinforcement learning in simulation. The cotraining study never
runs without robot demonstrations at all. A targeted search found no published case of a
useful manipulation policy trained with zero action information anywhere in the pipeline.
That is an absence of evidence rather than a proof of impossibility, and it is the state of
the field you would be betting against.

### What the recommendation buys, stated precisely

Choosing action-labeled capture does not make the task work. It moves the unsolved part of
the project from "recover actions from video" -- which is an open research problem with a
185 mm error bar on its input -- to "collect enough of the right data and evaluate it
honestly," which is 5 and 6 and is ordinary work.

Two caveats so the recommendation is not oversold.

*"Teleoperation has zero embodiment gap" is marketing.* That phrasing appears on
data-vendor pages, not in a peer-reviewed result `[VENDOR]`. It is true only in the narrow
sense that the recorded actions were executed on that robot by that controller. Teleop data
is still off-policy with respect to the states a learned policy visits on its own, which is
the classic behavior-cloning covariate shift: suboptimality compounds as O(eps * T^2) in
horizon for behavior cloning against O(eps * T) for an interactive reduction
`[AISTATS 2011, DAgger -- widely restated; this guide did not read the original theorem
statement]`. That is why 6 insists on autonomous rollouts from held-out starts.

*Hand-guiding puts a human in every frame.* If you capture kinesthetically, the images
contain an arm and two hands that will not be there at inference. Phantom's pipeline
inpaints a rendered robot over the human arm specifically to remove them `[EXP]`, which
tells you how the field treats a human limb in the observation. Whether this costs you
anything on a given setup is unmeasured here `[PRACTICE]`; the cheap mitigations are to
place the cameras so the operator's arm is out of frame, or to use a leader arm or gamepad
so the operator is not in the workspace at all.

---

## 2. What a usable capture contains

A "recording" that is missing any one of the following is not a demonstration, and the time
to discover that is before the first one, not after two hundred.

### The streams, and what each is for

| stream | what it is | why it is not optional |
| --- | --- | --- |
| action | what the controller was commanded, in the robot's own action space | the label. Without it there is no supervised pair (1) |
| proprioception | achieved joint positions, gripper width or force | commanded and achieved differ; the policy needs to know where the arm actually is. Ablating it cost 40 points on one bimanual task `[EXP: UMI]` |
| wrist camera | view from the end effector | moves with the gripper, so its relationship to the grasp is fixed by construction |
| scene camera | fixed view of the workspace | provides the context the wrist view loses at contact. Its pose is the fragile thing -- see below |
| timestamps | one clock, per frame and per action sample | the failure that silently destroys everything else |
| episode boundaries | start, end, and a success flag scored externally | an unsegmented log is not a dataset, and self-scored success is not success (6) |
| force, if it matters | six-axis wrench at the flange | the only stream that distinguishes "seated" from "crushed", and it is absent by default |

Note what is *not* on that list: a calibration matrix consumed by the policy. Standard
behavior-cloning visuomotor policies do not read one. That has consequences, below.

### Frame rate

The published real-robot datasets that people train on were collected at controller rates,
not video rates. ACT records at 50 Hz control, with episodes of 8-14 seconds giving 400-700
timesteps per demonstration `[EXP: RSS 2023, arXiv:2304.13705]`. The pi-0 pretraining
corpus spans control rates up to 50 Hz `[EXP: arXiv:2410.24164]`.

The rule that follows is not a number, it is a constraint: **the action stream's rate is set
by your controller, and the camera stream has to be timestamped against it rather than
assumed to line up.** Record the rate you used. The timestep count is the unit every
downstream quantity is expressed in, and a dataset that does not state its rate cannot be
compared to anything.

### Calibration, before the first demonstration

Two separate things get called calibration and only one of them is a matrix.

**Hand-eye calibration.** The classical formulation is AX=XB, where A is end-effector
motion, B is the corresponding camera motion, and X is the unknown rigid transform between
camera and hand (or camera and base). Three things about it are worth knowing before you
collect poses:

- **Observability is a hard requirement, not a quality knob.** A unique solution needs at
  least two motions whose rotation axes are non-parallel. If all rotation axes are parallel,
  the translation of X along the common axis is unobservable. If most are near-parallel the
  problem is ill-conditioned -- it still returns a unique-looking answer, just an inaccurate
  one `[EXP: IEEE T-RA 1989; restated arXiv:2308.06045]`.
- **Which poses you choose matters more than which solver you use.** Holding the algorithm
  fixed and changing only the pose-selection strategy moved translation error from 4.74 mm
  to 2.95 mm, a 37.7% reduction -- a larger swing than the spread between most AX=XB solvers
  in the same papers `[EXP: arXiv:2303.06766]`. There is also no single best solver:
  simultaneous methods resist rotation noise better, separated methods resist translation
  noise better, and the ranking flips with the noise profile `[EXP: PLOS ONE 2022]`.
- **The reported accuracy is a self-consistency residual, not error against truth.**
  Ground-truth hand-eye transform is not available with real data, stated outright by the
  authors who tested five solvers on 101 poses `[EXP: PLOS ONE 2022]`. A competently
  executed calibration on an industrial arm with a good camera lands roughly in the 0.5-3 mm
  and 0.1-1 deg band across the studies located `[EXP]`.

Two consequences that get missed. First, **a translation residual quoted without its
rotation residual and its working distance is close to meaningless.** Small-angle geometry:
a rotational error of d-theta contributes about (working distance) x d-theta to
end-effector position error. Taking one vendor's documented worked example of 0.83 deg =
0.0145 rad at the 600-1000 mm working distance that same documentation describes gives 8.7
to 14.5 mm from the rotation term alone, against its own 0.67 mm translation residual
`[ARITH -- this guide's calculation, not a published end-to-end measurement]`. Check this
on your own numbers; it is the kind of arithmetic that changes a decision.

Second, **hand-eye accuracy is bounded by the arm's own absolute accuracy**, because the A
matrices come from forward kinematics and the standard formulations do not model kinematic
error -- it accumulates into X. For magnitude: laser-tracker kinematic calibration of an
industrial arm moved mean and max absolute position error from 2.628 mm / 6.282 mm to
0.208 mm / 0.482 mm `[EXP]`. An uncalibrated arm contributes millimeters before the vision
system contributes anything. See 3, because this is the number people substitute the
datasheet repeatability figure for.

**Camera pose repeatability.** This is the other thing, and for a pixel-space policy it is
the one that matters.

### What happens to a trained policy when the camera is moved

Here is the reframe, and it is the single most useful sentence in this section:

> **Standard behavior-cloning visuomotor policies do not consume hand-eye extrinsics at
> all.** ACT, Diffusion Policy, OpenVLA and SmolVLA map pixels to actions end-to-end. A 2026
> paper presenting extrinsics conditioning as a novel contribution over exactly these
> baselines confirms the baselines lack it `[EXP: arXiv:2510.02268, ICRA 2026]`.

So the millimeter accuracy of your AX=XB solve is not what determines whether the policy
works. **Camera pose repeatability relative to the training distribution is.** And
recalibrating a moved camera does not restore a pixel-space policy, because the policy never
read the calibration. (No study located tests recalibrate-versus-not as an intervention; the
inference is from the fact that these architectures take no extrinsics input. Flagged in the
refusals.)

What moving the camera costs, measured:

- On a real robot, against its own training-condition baseline of 91.7%, the drops were:
  camera position **-45.9 points**, table texture -38.9, distractor objects -11.1, lighting
  -8.4, background -2.8. Camera pose was the hardest factor tested `[EXP: ICRA 2024,
  arXiv:2307.03659]`. Apply 6 before believing all of that: those rest on 12-36 trials each.
  Exact 95% Clopper-Pearson intervals from their own fractions put the training baseline
  (11/12) at [61.5%, 99.8%] and the new-camera condition (11/24) at [25.6%, 67.2%] -- the
  camera drop survives because the intervals do not overlap, while the lighting and
  distractor drops are not distinguishable from baseline at that trial count `[ARITH]`.
- In simulation, applying camera orientation perturbations of 2-10 deg -- **within the range
  of a sloppy remount** -- alongside distance and spherical-position changes, nine
  vision-language-action models dropped by between 19 and 91 points; several collapsed to
  near zero `[SIM: LIBERO-Plus, arXiv:2510.13626]`. The variance across models is enormous,
  so "VLAs are viewpoint-fragile" is only true on average.
- **Architecture decides sensitivity.** A 14-factor perturbation benchmark reports that 2D
  image-based models are affected by camera pose while 3D models operating on a voxel or
  point-cloud representation are robust to it, because they do not learn directly on the
  captured view `[EXP: RSS 2024, arXiv:2402.08191]`. If your policy consumes a
  reconstruction built from extrinsics, calibration accuracy matters and viewpoint does not.
  If it consumes raw pixels, the reverse.
- **The mechanism.** Policies without extrinsics infer camera pose from visual cues in
  static backgrounds, and that shortcut collapses when workspace geometry or camera placement
  shifts. Conditioning on extrinsics recovers much of the loss -- gains from +0.4 to +34.8
  points across six simulated tasks under randomized camera poses `[SIM: arXiv:2510.02268]`.

**Practical rules that follow.**

1. Bolt the camera. Positively locate it into deck features the way `docs/PRINTED_FIXTURES.md`
   5 says to locate a fixture: not tape, not friction, not a clamp somebody re-tightens.
   A mount that depends on putting it back in the same place is not a mount.
2. Measure and record the extrinsics anyway, even though the policy will not read them. It
   is the only way to later answer "did the camera move?", and it is what lets you switch to
   an extrinsics-conditioned or 3D architecture without recollecting.
3. Treat "the camera moved or was remounted" as an event that sends you back down the ladder
   in 8, not as a recalibration ticket.
4. Do not build a recalibration schedule out of drift fear. The only directly measured drift
   figure located is 1.49 pixels maximum thermal image drift across 5 C to 45 C, with 90
   minutes to reach equilibrium at each step `[EXP: Sensors 2022]` -- small, and not by
   itself a justification. Every recalibration-frequency figure in circulation (weekly,
   monthly, quarterly, seasonally) is vendor guidance with no measured basis `[VENDOR]`.
   Recalibrating after a collision or a physical change is a sensible precaution and is also
   unquantified `[PRACTICE]`.

One more that belongs here because it is a timestamp problem wearing a calibration costume.
The same flange-based study that reached 1.57 / -1.07 / -1.12 mm residuals in static mode
reached 18.89 / -44.90 / 6.22 mm when the camera captured while the arm was moving -- roughly
a 40x degradation -- and the authors attribute it to imprecise timestamp synchronization
between camera capture and robot pose, not to the AX=XB math `[EXP: Frontiers in Robotics
and AI 7:65, 2020]`. **Synchronization is not a detail of the capture. It is the thing most
likely to be wrong.**

---

## 3. The arm

### Confirmed specification

Read directly from the official xArm User Manual V2.0.0 (254 pp), Appendix 2, pp. 217-221
`[DS]`.

| | xArm 5 | xArm 6 | xArm 7 |
| --- | --- | --- | --- |
| DOF | 5 | 6 | 7 |
| payload | 3 kg | 5 kg | 3.5 kg |
| arm weight | 11.2 kg | 12.2 kg | 13.7 kg |

Shared across all three, from the manual's common-specifications table (p. 217) `[DS]`:
reach **700 mm**; repeatability **+/-0.1 mm**; max end-effector speed **1 m/s**; max joint
speed **180 deg/s**; Cartesian range X and Y +/-700 mm, Z -400 to 951.5 mm, roll/yaw/pitch
+/-180 deg; ISO Class 5 cleanroom; mounting "any"; tool flange DIN ISO 9409-1-A50/63 (M5*6);
input 24 V DC, 16.5 A; power min 8.4 W, typical 200 W, max 500 W.

Joint ranges differ per model (pp. 219-221) `[DS]`. All three share J2 at -118 to 120 deg.
xArm 5 and xArm 6 both carry J3 at -225 to 11 deg; xArm 7's corresponding joint is J4 at -11
to 225 deg, which is the mirrored range and not the same limit. Read the per-model table for
the arm you buy rather than carrying one model's numbers across.

**Two flags on that table.** Reach and repeatability come from the *shared* table; the
per-model tables for xArm 5 and xArm 7 list payload, DOF and weight and do not restate
repeatability. And payload as a flat number is a simplification -- the manual's own
"Maximum Payload" section states that maximum allowed payload depends on the center of
gravity offset from the flange, and the derating curve is published only as an image
`[DS]`. A gripper plus a wrist camera plus a full deep-well plate on a bracket is exactly
the case where the flat rating stops holding.

### What makes it usable for capture

The Python SDK is first-party and genuinely open: package `xarm-python-sdk`, repository
`xArm-Developer/xArm-Python-SDK`, version 1.18.4 released 2026-05-21, declared support
Python 3.5 through 3.13, licensed BSD 3-Clause `[DS]`. One `XArmAPI` surface covers xArm
5/6/7 plus the 850 and Lite 6, and exposes motion (`set_position`, `set_position_aa`,
`set_servo_angle`), kinematics (`get_forward_kinematics`, `get_inverse_kinematics`),
state/mode, grippers, controller and tool GPIO including analog, Modbus RS485 and TCP
passthrough, and safety configuration `[DS]`.

That is what makes action-labeled capture cheap on this arm: you can read state and command
poses from the same process that writes your dataset. The manual also documents
**hand-teaching with its own teach sensitivity, levels 1-5** `[DS]`, which is the
kinesthetic capture path from 1 with no extra hardware at all.

A first-party six-axis force/torque sensor exists as a flange accessory, compatible with
xArm 5/6/7 and 850. From its official manual, Section 5 `[DS]`: load capacity Fx, Fy =
**150 N**, Fz = **200 N**, Tx/Ty/Tz = **4 Nm**; resolution 100 mN (Fx, Fy), 150 mN (Fz),
5 mNm (torque); hysteresis 2.5% FS (Fx, Fy) and 1% FS (Fz, torque); crosstalk 3% FS;
overload 150%, and for Fz 150% positive / 300% negative; weight 445 g. It is exposed
through the SDK (`ft_sensor_enable`, `ft_sensor_set_zero`, `get_ft_sensor_data`,
`ft_ext_force`, `ft_raw_force`, plus admittance control, force control, and FT-based
collision detection with rebound) `[DS]`.

**Correct one thing before you spec it.** The figures circulating as this sensor's *range*
-- +/-225 N, +300/-600 N, +/-6 Nm -- are the **overload** values, i.e. 150%/300% of the load
capacities. One reseller listing of "400 N / 20 Nm" matches no figure in the official manual
at all `[VENDOR]`. Use 150 N / 200 N / 4 Nm as the working spec.

### Repeatability versus accuracy, and why +/-0.1 mm is not the number

**Repeatability** is how closely the arm returns to the same commanded pose across
repetitions. **Accuracy** is how close the pose it reaches is to the pose the coordinate
actually names. They are different quantities, they differ by roughly an order of magnitude
on industrial arms, and the datasheet publishes only the first one.

The +/-0.1 mm figure is a vendor-declared number with no stated measurement standard. The
string "9283" -- ISO 9283, the robot performance test standard -- appears **zero times** in
the 254-page manual, and no test load, speed, temperature or pose set is given `[DS]`. It is
not a published measured result, and real-world figures will depend on payload, speed,
thermal state and pose.

**The number that decides whether a tip lands in a well is a stack, and repeatability is
one small term in it.** Going from the arm outward:

1. The arm's absolute accuracy in the frame you taught in. Unpublished by this vendor and by
   most others. Magnitude anchor: laser-tracker kinematic calibration of an industrial arm
   moved mean/max absolute position error from 2.628 / 6.282 mm to 0.208 / 0.482 mm `[EXP]`
   -- millimeters before calibration, an order of magnitude above the datasheet
   repeatability. ("Absolute accuracy is about 20x repeatability" is a widely repeated rule
   of thumb; the phenomenon is real and the specific multiplier is not measured `[PRACTICE]`.)
2. The hand-eye residual, if vision is in the loop: 0.5-3 mm and 0.1-1 deg for a competent
   calibration, with the rotation term amplified by working distance (2).
3. Where the fixture actually is, which is a printed-part question and lives in
   `docs/PRINTED_FIXTURES.md` 5.
4. The plate's own tolerance. ANSI/SLAS 1 allows +/-0.25 mm only within 12.7 mm of the four
   outside corners and **+/-0.5 mm** elsewhere along the side, and corner radius is 3.18 mm
   +/-1.6 mm -- a 1.58 to 4.78 mm permitted range `[STD, via the sibling guide]`.
5. Thermal state. Printed polymers move far more than molded ones, and SLAS dimensions are
   specified at 20 C while its own test method for one part of the family is at 25 C +/- 2 C.

Terms 3, 4 and 5 are frequently larger than terms 1 and 2. **A guide that answers "will the
tip land in the well?" with the arm's repeatability figure has answered a different
question.**

There is no published figure for the end-to-end stack on a lab deck, and this guide will
not compose one out of the terms above -- they do not add independently and their signs are
not known. **The measurement that produces it** is direct: with the fixture located and the
plate seated, drive the arm to the taught pose and measure the tip's actual offset from the
well center, at the working temperature, over enough repeats to state a range rather than a
value (`autonomous_lab/teaching.py` sets that floor at `MIN_DEMONSTRATIONS = 3` and refuses
a tolerance below it). Repeat after any event in 8's demotion list.

### Choosing the DOF

This is the only arm choice this guide will make an argument about, and it is kinematics
rather than a benchmark.

- **5 DOF cannot reach an arbitrary 6-DOF pose.** A full pose is three positions and three
  orientations. With five joints the reachable set is constrained, and the constraint bites
  the moment a fixture presents labware at an angle it did not anticipate -- which is
  exactly what the tilt module in `hardware/tilt_module.scad` does.
- **6 DOF is the general case** and is the smallest arm that can put the flange anywhere in
  its workspace at any orientation. It also carries the largest payload of the three (5 kg),
  and it is the only model for which this manual documents a CE certification (below).
- **7 DOF adds a redundant joint.** That buys obstacle avoidance and joint-limit avoidance
  around a fixed end-effector pose. It also means one end-effector pose corresponds to a
  continuum of joint configurations -- which is the non-injective case from 1, and it makes
  video retargeting strictly worse while making teleoperation mapping ambiguous. Redundancy
  is a feature you should want deliberately, not by default.

### What could not be confirmed about this arm

Kept here rather than in the refusals list because it is buying advice.

- **No independent metrology.** Every accuracy, repeatability and payload figure above
  traces to UFACTORY's own documentation or storefront. No third-party study was located.
- **Price is inconsistent across the vendor's own US web properties.** Individual product
  pages returned $6,000 (xArm 5), $9,500 (xArm 6), $11,000 (xArm 7); an aggregate fetch of
  the same site returned $5,799 and $10,499 for two of them. The force/torque sensor lists
  at $3,500 on a page that omits its force ranges entirely. These could not be reconciled.
  **Get a quote.** Which control box, cables and region are included at each figure is not
  determinable from the public pages.
- **F/T sensor accuracy** (as distinct from resolution and hysteresis) and its data rate are
  not in the official specification table. The commonly cited 200 Hz comes from reseller
  pages `[VENDOR]`.
- **"Collaborative robot" is reseller framing.** The word does not appear in the manual's
  specification or safety sections. See 7.
- **Firmware and controller software are not open.** Only the Python SDK, C++ SDK and ROS
  packages are confirmed BSD-3-Clause. Assume the motion and kinematics core is closed.
- **24/7 duty-cycle suitability** is a product-page claim `[VENDOR]`, while the manual itself
  warns to reduce temperature for continuous high-speed operation in a 0-50 C ambient range
  `[DS]`.

---

## 4. Where the printed fixture earns its place

The argument for a printed fixture in a learning pipeline is one sentence: **it removes
degrees of freedom from what has to be learned.** A plate that can be anywhere in a
40 x 40 cm region is a pose the policy must infer from pixels every episode. A plate in a
nest is a pose the policy can assume.

That argument is correct in direction. The honest accounting of how correct, and of how
much, is below -- and the second half of this section is the trap, which is worse than most
people expect.

### What is published evidence

**Nothing published uses a physical fixture as the manipulated variable.** This guide's
research located no study that fixtures a part, runs an unfixtured control, and measures
demonstrations required to reach a target success rate. Every quantified source substitutes
something for the fixture: a simulated randomization range, a simulated reset distribution,
or software pose canonicalization. Everything below is therefore evidence *about pose
variance*, which is what a fixture removes -- not evidence about fixtures.

**The scaling law.** ManiBox (arXiv:2411.01850) measured trajectories needed to reach 80%
grasp success as a function of the volume over which the object's position was randomized,
in simulation `[SIM]`:

| randomization volume | trajectories to 80% |
| --- | --- |
| 1 cm3 (effectively a fixed point) | 728 |
| 125 cm3 (5 x 5 x 5 cm) | 1,951 |
| 1,000 cm3 (10 x 10 x 10 cm) | 8,098 |
| 8,000 cm3 (20 x 20 x 20 cm) | 14,638 |
| 34,400 cm3 (41 x 30 x 28 cm, about full reach) | 24,005 |

Fitted: data = 640.32 x volume^0.35. Fixed point to full workspace is 33x in the raw
measured points, and the authors compute 34,400^0.35 = 38x from the fit.

**Now do the arithmetic that changes the design decision** `[ARITH, on their fit]`. An
exponent of 0.35 on *volume* is about L^1.05 in *linear extent*, since (L^3)^0.35 = L^1.05.
So required data is roughly **linear in the linear span** of the placement region, not in
its volume:

```
  halving tolerance on each axis   = 8x less volume    = 8^0.35   = about 2.1x less data
  +/-20 mm scatter to +/-2 mm      = 1000x less volume = 1000^0.35 = about 11x less data
```

A fixture that cuts placement scatter by an order of magnitude in each axis predicts roughly
10x less data, **not 1000x**. That is a large and worthwhile win and it is not the win people
describe when they say a fixture "makes it trivial."

Caveats that must travel with those numbers: the fit is good at 1,000 / 8,000 / 34,400 cm3
(predicted 7,186 / 14,853 / 24,332 against measured 8,098 / 14,638 / 24,005) and **poor at
125 cm3** (predicted 3,471 against measured 1,951). It is simulation, one grasping task
family, a bounding-box state representation, simulated trajectories rather than human
demonstrations, and **3-DoF translation only** -- orientation variance is not in the volume
term at all. The authors call it "preliminary verification."

**Fixed budget, varying pose spread.** MimicGen (CoRL 2023, arXiv:2310.17596) holds the
demonstration budget at 1,000, holds the architecture fixed, runs 3 seeds, and changes only
the object reset distribution. Its D0 condition has the receptacle **rigidly fixed** -- a
fixture in all but name -- while D1 and D2 unfix it and D2 adds free rotation `[SIM]`:

| task | D0 (receptacle fixed) | drop at D1 | drop at D2 |
| --- | --- | --- | --- |
| Square | 90.7 +/- 1.9% | -17.4 pts | -41.4 pts |
| Threading | 98.0 +/- 1.6% | -37.3 pts | -60.0 pts |
| Three Piece Assembly | 82.0 +/- 1.6% | -19.3 pts | -68.7 pts |
| Coffee | 100.0 +/- 0.0% | -9.3 pts | -22.7 pts |
| Nut-and-Bolt (Factory) | 92.7% | -11.4 pts | -20.0 pts |
| Gear Assembly (Factory) | 98.7% | -24.7 pts | -42.0 pts |
| Frame Assembly (Factory) | 82.0% | -13.3 pts | -45.3 pts |
| **Stack** | **100.0 +/- 0.0%** | **-0.7 pts** | -- |

**Read the last row.** Widening the placement region from 16 x 16 cm to 40 x 40 cm -- 6.25x
the area -- cost 0.7 points on Stack. Constraining pose bought essentially nothing on an
easy, low-precision task. **The benefit is not task-independent.** It is large on
contact-rich, high-precision and long-horizon tasks and near zero on coarse ones. Which of
those your task is decides whether the fixture is a data-efficiency measure or just a
tidiness measure.

The same paper also carries the negative result that kills the usual fantasy. Its 10 real
human source demonstrations, **evaluated in the same narrow fixtured D0 region they were
collected in**, scored 11.3% (Square), 19.3% (Threading), 1.3% (Three Piece Assembly) and
26.0% (Stack) in simulation; on the real robot the 10-demo source agents scored **0% on
Stack and 0% on Coffee** (94% pod grasp, 0% insertion) `[EXP]`. Reaching the D0 numbers in
the table took 1,000 demonstrations. **A fixture shifts the data curve. It does not collapse
the requirement to a handful of demonstrations.**

Pose spread also costs you at collection time, not only at training time: MimicGen's own
rate of attempts yielding a usable demonstration fell from 73.7% to 48.9% to 31.8% (Square)
and 51.0% to 39.2% to 21.6% (Threading) across D0/D1/D2, which is 2.3-2.4x more attempts to
bank the same 1,000 usable demonstrations `[SIM]`.

**Software isolates pose as the cause.** Two results remove pose variance in the
representation rather than the world and get the same shape of win, which is what makes the
causal story credible. An oriented-affordance-frame method needed 305 image-based
demonstrations to match what its frame-canonicalized policy reached from 10 -- the authors
call it 30x -- and ablating just the *orientation* component of the frame nearly halved
success at 10 demonstrations `[EXP: CoRL 2025, arXiv:2410.12124]`. An SO(2)-equivariant
diffusion policy averaged its result at 100 demonstrations above all baselines trained with
1,000, across 12 tasks `[SIM: IJRR 2026, DOI 10.1177/02783649261424445]`.

### What is engineering practice

- The **3-2-1 locating principle** -- three locators for the primary datum, two for the
  secondary, one for the tertiary, constraining six degrees of freedom with minimum contacts
  -- is the textbook justification for jigs and fixtures. No publication quantifies its
  effect on demonstration count for a learned policy `[PRACTICE]`.
- **"Fixture it and hard-code the waypoints, skip learning entirely."** This is the dominant
  approach in laboratory automation and it is often the right answer. Published lab-robotics
  work uses fiducials on statically mounted labware and teach-pendant reference points and
  reports no demonstration-count comparison against an unfixtured baseline `[PRACTICE]`. If
  your task is a fixed pick-and-place between two known positions, a policy is the wrong
  tool and this guide's honest advice is to teach waypoints.
- **Any multiplier of the form "a nest cuts demonstrations by N x" for a lab workcell.** No
  such published figure exists. The defensible numbers -- 33-38x fixed-point-to-full-workspace,
  30x for frame canonicalization, 2.3-2.4x collection overhead -- come from tabletop grasping
  and assembly in other domains, mostly in simulation, and applying them to labware handling
  is extrapolation `[PRACTICE]`.

### The trap: the fixture is part of what the policy learned

A hard-coded waypoint program depends on the fixture's *geometry*. A learned policy depends
on the fixture's **appearance and position in every training frame**. Its color, its layer
lines, its shadow, where its edge falls in the image, and where the plate ends up because of
it are all training signal, and none of it is recorded anywhere unless you record it.

**So a reprint can invalidate the demonstrations.** Concretely, from
`docs/PRINTED_FIXTURES.md` 5:

- Filament manufacturers largely **do not publish shrinkage**; three datasheets were opened
  and none listed a figure `[DS]`. Every per-material percentage in circulation is a slicer
  default or a community measurement.
- Inside one slicer's shipped profiles, one vendor's compensation implies measured shrinkage
  of PLA 0.05%, PETG 0.15%, ABS 0.513%, ASA 0.513%, PC-CF 0.15%, while a different vendor in
  the *same repository* ships zero compensation for PLA, PETG, ABS and ASA. Two vendors, one
  slicer, a 0.5% disagreement on ABS `[shipped code, read directly]`.
- Across the 127.76 mm long dimension of a plate footprint, 0.513% is **0.66 mm** -- larger
  than the entire ANSI/SLAS 1 corner-zone tolerance band of +/-0.25 mm `[ARITH + STD]`.

A change of that size moves where the plate sits. For a waypoint program you re-teach the
point. For a policy, the demonstrations were collected against a fixture that no longer
exists, and nothing in the dataset says so.

This is the same distinction the code already draws. `autonomous_lab/printed.py` keeps
`DimensionState.DESIGNED` and `DimensionState.MEASURED` apart precisely because a designed
dimension is a number in millimeters in a document that reads exactly like a measurement and
is a fact about a model. **A fixture whose registering features are DESIGNED has not
established that the plate is where the demonstrations put it.** The sibling guide's rule
applies verbatim here: *a part reprinted from a different spool is a different part until it
has been measured again.*

**The tilt module is the worked case.** `hardware/tilt_module.scad` and
`docs/PRINTED_FIXTURES.md` 6 describe a wedge that presents a plate at a fixed angle. Today
it reaches `MEASURED` at best, and it is instructive for a policy pipeline because it changes
several things the policy would have learned at once:

- the well bottom is no longer perpendicular to the approach;
- the clearance to the plate's high side shrinks;
- the stack height rises by the wedge, and the sibling guide computes 39.38 mm above the
  deck datum against 14.35 mm flat;
- it introduces a retention failure the flat nest did not have -- a lip too shallow to hold
  the plate at angle -- for which there is no friction coefficient and therefore no formula,
  only a direct measurement of the angle at which the loaded plate moves, per flange variant.

Every one of those is inside the policy's observation and action distribution. A tilt module
reprinted at a different shrinkage is not a cosmetic change to the deck; it is a change to
the dataset, applied retroactively, silently.

### What to do about it

1. **Version the fixture with the dataset.** Filament, spool and lot, slicer profile,
   compensation values, print date, and the *measured* registering dimensions with the
   instrument named. A dataset whose fixture provenance is unrecorded cannot be diagnosed
   when success drops after a reprint -- you will not be able to tell a reprint from a camera
   nudge from a bad training run.
2. **Treat a reprint as a demotion event** (8). It sends the part back to `MEASURED` in the
   sibling guide's ladder and sends the policy back to a fixture-with-no-material rung.
   Re-run the dry run: a printed fixture that moves under arm contact is **silent by
   construction** -- nothing in a printed part reports its own position, and the first
   evidence is the collision.
3. **Locate it positively.** Bolt, key, or capture it between deck rails. A registration that
   depends on somebody putting it back in the same place is not a registration, and for a
   policy it is also a slow corruption of the training distribution.
4. **Or deliberately train across fixture variation**, which converts the problem into the
   diversity lever in 5. That costs demonstrations across variants and **there is no
   published number for how many.** The measurement that would produce one: print the fixture
   n times across the lots you will actually use, measure the registering features on each,
   collect demonstrations against each, and evaluate on a held-out reprint per 6.

### A note on the apparent contradiction with 5

Section 5 reports that the only controlled study of demonstration counts found *diversity*
dominates raw count. This section says to *remove* variance. Both are right, and the
resolution is that they are about different variance:

- Pose variance within a fixed task is variance the policy must **solve**. Removing it
  reduces what has to be learned for the task you have (ManiBox, MimicGen).
- Environment and object diversity is variance that makes a policy **transfer** to
  situations you did not collect. Adding it buys generalization (Lin et al.).

Pinning the plate does not stop you varying lighting, consumable lot, plate vendor, liquid,
operator, time of day, or -- per the point above -- the fixture reprint itself. Fixture the
thing whose pose you want assumed; diversify everything you want survived.

---

## 5. How many demonstrations

There is no answer to this question, and the useful thing this section can do is show you
exactly how absent the answer is, then tell you what actually determines it.

### The published per-task counts, with methods and tasks named

**ACT / ALOHA** (RSS 2023, arXiv:2304.13705), 6 real bimanual tasks on a roughly USD 20k
platform, verbatim: "We record 50 demonstrations for each task, except for Thread Velcro
which has 100." Episodes 8-14 s at 50 Hz control = 400-700 timesteps. "The total amount for
demonstrations is thus around 10-20 minutes of data for each task, and 30-60 minutes in
wall-clock time because of resets and teleoperator mistakes." `[EXP]`

Per-task final success on real hardware, 1 seed x **25 evaluations** per task: Slide Ziploc
88%, Slot Battery 96%, Open Cup 84%, Thread Velcro 20%, Prep Tape 64%, Put On Shoe 92%
`[EXP]`. At 25 trials one success is 4 percentage points `[ARITH]`; these are coarse
estimates.

Three things about that paper matter more than the 50:

- **Its own abstract is selective against its own table.** "80-90% success with only 10
  minutes worth of demonstrations" describes four of six tasks (84-96%). Prep Tape is 64%
  and Thread Velcro is 20%.
- **Thread Velcro got twice the demonstrations and produced the worst result.** The paper
  attributes this to perception and precision, not data volume -- success roughly halved at
  each stage, "from 92% success at the first stage to 20% final success," with failures from
  the gripper closing too early and imprecise insertion. **Demonstration count was not the
  binding constraint on the hardest task in the paper.**
- **ACT contains no ablation over number of demonstrations at all.** Its Figure 8(a) x-axis
  values (1, 10, 100, 200, 400) are action-chunk size k, not demonstration count. This is a
  very easy misread and it is the origin of a lot of confident advice.

**Diffusion Policy** (RSS 2023 and the extended IJRR version, arXiv:2303.04137v5), real
robot, Table 3: Push-T **136** proficient-human demonstrations; Mug Flip **250**; 6DoF Pour
**90**; Periodic Spread **90**. The journal version's bimanual tasks: Egg Beater **210**
demonstrations for 55% success over 20 trials; Mat Unrolling **162** for 75% over 20; Shirt
Folding **284** for 75% over 20 `[EXP]`. All real-robot evaluations use 20 trials, so one
trial is 5 percentage points `[ARITH]`.

Two traps. The paper **contradicts itself** on the sauce tasks -- Table 3 lists 90
proficient-human demonstrations while Appendix C.2.1 states "50 demonstrations are
collected, and 90% are used for training for each task." Unresolved; both are reported here.
And its **simulation** counts (200 proficient-human + 300 multi-human for several Robomimic
tasks, 200 for simulated Push-T, 1,000 scripted for BlockPush) are routinely quoted as if
they were the real-robot counts.

**Mobile ALOHA** (CoRL 2024, arXiv:2401.02117) uses "50 in-domain demonstrations, or 20 in
the case of High Five" (Cook Shrimp also 20) `[EXP]`. **The caveat is load-bearing and it is
usually dropped: the 50 only holds with co-training on a large static-ALOHA dataset.**
Table 4 gives Wipe Wine at 95% with co-training against 50% without; Call Elevator goes from
roughly 0% to 95%. Without the auxiliary dataset, 50 is not sufficient for several of these
tasks.

Its Figure 4 is the cleanest real-hardware demonstration-count ablation in this set (Wipe
Wine, ACT, 25/35/50 demonstrations, 20 trials each): "With co-training, the policy trained
with 35 in-domain demonstrations can outperform the no co-training policy trained with 50
in-domain demonstrations, by 20% (70% vs. 50%)." `[EXP]`

The same paper contains the cleanest evidence that **the requirement is method-dependent,
not only task-dependent**: at an identical 50 demonstrations on Wipe Wine, ACT reaches 95%
and Diffusion Policy reaches 65%.

**DP3 / 3D Diffusion Policy** (RSS 2024, arXiv:2403.03954). The frequently repeated "10
demonstrations" is a **simulation** result across 72 simulated tasks `[SIM]`. On real
hardware the paper used **40 demonstrations per task** across 4 tasks, averaging 85.0 +/-
11.2% `[EXP]`.

**ALOHA Unleashed** (CoRL 2024, arXiv:2410.13126) is the decisive counterexample to the
whole "50 demos" framing: same hardware lineage, per-task counts three orders of magnitude
larger. Over **26,000** real demonstrations across 5 tasks, collected on 10 robots over
eight months -- ShirtEasy/Messy 8,658; LaceEasy/Messy 5,133; FingerReplace 5,247; GearInsert
4,005; RandomKitchen 3,198 `[EXP-1]`. And even at thousands per task the results are **not
saturated**: 75% / 70% on shirts, 40% on the harder lace variant, 40% on the third gear
insert, and a kitchen task degrading from 95% with one object to 65% with two and 25% with
three. **Demonstration count buys task difficulty and robustness, not a march to 100%.**
(This one rests on a single HTML fetch and was not re-extracted from the PDF -- re-verify
before quoting.)

**Frontier VLAs changed the unit of account**, which breaks direct comparison. pi-0
(arXiv:2410.24164) reports **hours**: "the simplest of the tasks necessitating only 5 hours
and the most complex tasks using 100 or more hours of data," and abandons binary success for
a normalized score averaged over 10 episodes per task. pi-0.5 (arXiv:2504.16054) reports
"about 400 hours of data of mobile manipulators performing household tasks in about 100
different home environments," with no per-task breakdown at all `[EXP]`.

Consequently: **any per-task demonstration count attributed to pi-0 or pi-0.5 comes from
outside the papers.** The figures in circulation ("100-200 to fine-tune pi-0 to a new task";
"200-500 for pi-0.5 single-task adaptation, 1,000-5,000 across 5-20 tasks for a new robot")
surfaced only on a commercial third-party model-documentation site `[VENDOR, unverified
provenance]`.

### The one work that actually measures the question

Data Scaling Laws in Imitation Learning (ICLR 2025, arXiv:2410.18647), over 40,000
demonstrations and more than 15,000 real-world rollouts. Headline finding, verbatim: "the
diversity of environments and objects is far more important than the absolute number of
demonstrations; once the number of demonstrations per environment or object reaches a certain
threshold, additional demonstrations have minimal effect." `[EXP]`

Concretely: roughly 50 demonstrations per environment-object pair, across 32 distinct pairs,
totalling about 1,600, reached around 90% success in novel environments with unseen objects
-- measured on 2 tasks only. Reported plateaus at 400 / 800 / 1,600 total demonstrations for
8 / 16 / 32 pairs. Generalization follows a roughly power-law relationship with the number of
environments and objects, **not with raw demonstration count**; with environments and objects
held fixed there was no clear power law between count and generalization at all (correlation
coefficients -0.62 and -0.79 for the two tasks).

### The synthesis, and the refusal

The published real-robot range spans **20 demonstrations** (Mobile ALOHA High Five, with
co-training) to **8,658** (ALOHA Unleashed shirt) -- about a 400x spread, across tasks that
are all more similar to each other than any of them is to a lab bench.

**The number for a new task is not knowable in advance.** What the measurements say
determines it:

1. **Task precision and horizon.** The strongest single signal in the set: Thread Velcro at
   2x the demonstrations and the worst result, with the paper's own diagnosis being precision
   and perception.
2. **Whether auxiliary or pre-training data is used.** The same 50 demonstrations mean
   different things with and without co-training, by up to 95 points on one task.
3. **Environment and object diversity**, which is the only factor a controlled study found
   dominant.
4. **The method.** ACT and Diffusion Policy differ by 30 points at identical count on the
   same task.

Notably absent from that list: a threshold.

**What is repeated as evidence and is not** `[PRACTICE]`:

- *"50 per task is the standard starting budget."* This generalizes one collection choice in
  one paper into a sufficiency threshold. ACT collected 50 for all six tasks and ran no
  ablation; its own Thread Velcro at 100 shows the number does not carry that meaning.
- *"Diffusion Policy needs roughly 250+."* Directionally consistent with its own real-robot
  counts (136-284), but as a rule it traces to a **hypothesis sentence** in Mobile ALOHA
  about prior practice, not to a controlled measurement.
- *"DP3 only needs 10."* Simulation-only. The real-robot experiments used 40.
- *"Start at 50, scale to a few hundred for long-horizon or contact-rich, thousands for
  deformables."* A sensible heuristic that happens to match the spread, and no paper measures
  those as thresholds. It is pattern-matching across papers with different robots, tasks,
  success criteria and trial counts.
- *"Success improves smoothly with count, so collect until it plateaus."* The only two
  real-hardware curves measured (Lin et al.; Mobile ALOHA Fig. 4) find closer to the
  opposite: per-pair count saturates quickly and diversity carries the gains.

### What to do instead

Treat the count as something you **measure on your task**, not something you look up.

- Collect in blocks. Freeze a checkpoint. Evaluate under the protocol in 6. Add a block.
  Re-evaluate.
- **Recognize that this is a sequential comparison and that the naive version is invalid.**
  Extending a fixed-batch test with a few more trials "constitute[s] p-hacking that
  invalidates statistical assurances" `[EXP: RSS 2025, arXiv:2503.10966]`. Either pre-commit
  the batch size or use a procedure designed for sequential stopping.
- Budget wall-clock honestly. ACT's own accounting is 10-20 minutes of *data* per task
  against 30-60 minutes of *wall clock*, "because of resets and teleoperator mistakes"
  `[EXP]` -- roughly a 2-3x overhead. That ratio is about collection, not about outcomes, and
  it is the most transferable number in this section.
- Spend the marginal hour on diversity before spending it on count, because that is the only
  place a controlled study found the gains.

---

## 6. Evaluation

A success rate is a point estimate of a Bernoulli parameter. Almost everything that goes
wrong in this section comes from forgetting that sentence.

### Held-out trials, rolled out autonomously

Two separate requirements that get collapsed.

**Held out.** Evaluate from initial conditions the policy was not trained on -- object poses,
lighting, lot, operator, plate instance, time of day. There is no standard taxonomy for what
counts as held out; each lab picks its own factors and its own seen/unseen boundary
`[PRACTICE]`. Pick yours before you evaluate and write it down, because the boundary is what
the number means.

**Autonomous.** The policy must drive the whole episode from its own states. Behavior cloning
trained i.i.d. on expert states incurs cost that compounds quadratically in horizon --
O(eps * T^2) against O(eps * T) for an interactive reduction -- because the policy's own
errors move it off the training distribution, and that effect only appears under autonomous
rollout `[DAgger, AISTATS 2011; standard and widely restated, primary theorem statement not
read here]`. **Success measured from training initial conditions is structurally
optimistic**, and the structure is known.

Related, and directly measured: the distribution shifts you will actually hit are not equal.
Against a 91.7% training-condition baseline on a real robot, camera position cost 45.9
points, table texture 38.9, distractors 11.1, lighting 8.4, background 2.8 `[EXP:
arXiv:2307.03659]`. In simulation, increasing training environment configurations from 5 to
100 shrank the maximum generalization gap from 0.40 to under 0.10 `[SIM, same paper]` --
which is 5's diversity lever, measured on the evaluation side.

### An external success criterion, not the policy's confidence

**Offline loss barely predicts real-world performance.** Across roughly 1,500 paired
simulation-and-real evaluation episodes on 2 embodiments, a behavior-cloning "validation
MSE" baseline scored Pearson r = **0.308** as a predictor of real-world policy ranking,
against r = 0.924 for a visual-matching simulator `[EXP: CoRL 2024, arXiv:2405.05941]`. A
training curve is not an evaluation and a validation loss is not a success rate.

So the criterion has to be a physical outcome, read by something that is not the policy. In
a lab that is the assay, which is the top rung in 8. Three requirements on it:

- **It must be defined before the run.** Written down, with the pass condition explicit.
- **It should be scored by someone who does not know which policy ran.** The most rigorous
  published campaign used fully blind evaluation with randomized policy ordering and initial
  conditions matched by image overlay `[EXP: arXiv:2507.05331]`. Note honestly that **no
  published robotics study measures how much bias non-blind evaluation introduces**, so this
  is hygiene borrowed from clinical trials rather than a quantified correction `[PRACTICE]`.
- **Expect label noise even so.** A quality audit of 27% of about 2,700 rollouts in that same
  campaign found a **2.31%** discrepancy in success-rate labelling and **6.25%** on
  rubric questions `[EXP]`. Careful human scoring carries a couple of points of noise.

### The trial count needed for a meaningful interval

This is arithmetic, so it is available even though the robotics literature declines to name a
threshold. Exact Clopper-Pearson 95% intervals `[ARITH]`:

| trials | interval at observed 90% | width | interval at observed 50% |
| --- | --- | --- | --- |
| 10 | [55.5%, 99.7%] | 44.2 pts | [18.7%, 81.3%] |
| 20 | [68.3%, 98.8%] | 30.5 pts | [27.2%, 72.8%] |
| 50 | [78.2%, 96.7%] | 18.5 pts | [35.5%, 64.5%] |
| 100 | [82.4%, 95.1%] | 12.7 pts | [39.8%, 60.2%] |
| 200 | [85.0%, 93.8%] | 8.8 pts | -- |
| 1000 | [88.0%, 91.8%] | 3.8 pts | -- |

The consequence in one line: **a 10-trial evaluation cannot distinguish a 60% policy from a
95% one.** A vendor engineering blog independently reports 80.5-95.9% at 70 rollouts and
88.0-91.8% at 1,030, and notes that going from a 10-point interval to a 2-point interval
takes about 15x more rollouts; the 1,000-row above reproduces its figure exactly `[VENDOR,
arithmetic independently verified]`.

**Comparing two policies is much more expensive than measuring one.** Two-proportion normal
approximation, two-sided alpha = 0.05, 80% power, trials **per policy** `[ARITH]`:

| comparison | trials per policy |
| --- | --- |
| 50% vs 80% | 39 |
| 50% vs 70% | 93 |
| 80% vs 90% | 199 |
| 70% vs 80% | 294 |
| 85% vs 90% | 686 |

Inverted, against a 50% baseline: 20 trials per arm detects only about a 40-point difference;
50 detects about 27; 100 detects about 19. **That is the quantitative reason a 20-trial A/B
cannot support a claimed 5-point improvement**, which is the size of improvement most
comparisons claim.

For calibration against what the field does: the modal per-condition trial count in a
13-paper convenience sample of recent real-robot VLA papers is **10-20**, and none of the 13
reported confidence intervals or paired tests `[EXP, single-author preprint, convenience
sample -- treat as illustrative, not representative]`. Recent benchmarks use 10 rollouts per
task; the scale in them comes from task count, not trials per cell. The exception is the
large-behavior-model campaign at roughly 1,800 controlled real trials with 50 rollouts per
task per policy per condition `[EXP]`.

**This guide names no minimum trial count**, and the reason is that no published result
establishes one. The required n depends on the unknown true performance gap, which is not
knowable before the experiment; one widely cited methods paper explicitly declines to name a
number `[EXP]`. The table above is offered instead of a threshold: pick the interval width
you need to make your decision, read across, and that is your n.

### Why a rate without its interval or its trial count is not a result

Because it is unfalsifiable and uninterpretable at the same time. Read the table above
sideways: an observed "90%" is compatible with [55.5%, 99.7%] and with [88.0%, 91.8%]. Same
point estimate, and the two support opposite decisions. The trial count is not metadata about
the number; it is half of the number.

The critique from the field, near-verbatim: evaluation "often solely focuses on success rate
with little description of the experimental conditions, number of evaluations, success
criteria, performance, failure modes, and typically without any statistical analysis"
`[EXP: arXiv:2409.09491]`.

**Report k out of n, not a percentage.** The raw counts let a reader reconstruct the interval;
a percentage destroys the information irreversibly. Report the success criterion, the
held-out factors, who scored it and whether they were blind, and the failure modes.

Three more disciplines with real evidence behind them:

- **Freeze the checkpoint before evaluation begins.** Do not select the best-performing
  checkpoint by evaluation success rate. Top-N trial selection is documented as a real problem
  in reinforcement learning `[EXP: AAAI 2018, arXiv:1709.06560]`; the inflation it causes on
  robot hardware is unmeasured `[PRACTICE]`.
- **Seeds alone can make an algorithm look better than itself.** Ten trials of one
  configuration, varying only the random seed, split into two groups of five, produced
  learning curves that "do not fall within the same distribution at all" `[EXP, same paper]`.
- **Do not extend a finished batch.** Use a pre-committed batch with an exact test, or a
  sequential procedure built for it -- published sequential methods report up to 32% fewer
  trials than batch baselines, and a 2026 follow-up using anytime-valid inference reports up
  to 70% versus batch and up to 50% versus binary-outcome sequential methods, while also
  finding that **policies separate faster on fine-grained task-progress scores than on binary
  success** `[EXP: arXiv:2503.10966; arXiv:2603.13616]`. In a lab, a graded score is often
  free: residual volume, recovery fraction, and fraction of wells addressed are all continuous.

### The lab-specific part

The assay is the external criterion, and it has its own n and its own basis. Two rules from
the repo apply unchanged:

- `autonomous_lab/teaching.py` refuses to state a tolerance below `MIN_DEMONSTRATIONS = 3`,
  and judges parity on the **worst** observation rather than the mean, because a mean lets one
  excellent run pay for a bad one and at the bench the bad plate is the one that costs the
  sample. A policy that ran once, well, is `Attainment.INDISTINGUISHABLE_FROM_UNMEASURED` --
  the numbers exist and cannot yet be told from luck.
- The acceptance-test design in `hardware/README.md` applies to a policy exactly as it applies
  to a wedge: paired against a control, endpoint a quantity rather than an impression,
  measured per well before pooling, positions randomized so treatment is not confounded with
  deck position, threshold pre-registered with its basis recorded, and the observed range
  reported rather than mean plus k sigma.

And note what your assay is *not* allowed to be here: this workcell's absorbance read is
BROKEN, and even repaired, A260 does not discriminate library from primer, carrier or free
nucleotide `[repo: qc.py]`. A gate reading that number passes an empty well confidently.

---

## 7. The safety boundary

**A learned policy has no guarantees.** It is a function fit to data. Nothing in training
bounds what it can output, nothing in it detects that it is out of distribution, and its
confidence is not a safety signal (6: validation loss correlates with real performance at
r = 0.308). Under a distribution shift as small as a 2-10 deg camera remount, published
models have gone to near-zero success `[SIM]` -- and "near-zero success" describes the
outcome, not the trajectory the arm took getting there.

**So the policy proposes. Deterministic interlocks dispose.** Everything below must be
enforced outside the policy, by something the policy cannot write to. A limit that the
policy's own process sets is a limit the policy can remove.

### What must be bounded outside the policy

**Workspace.** A Cartesian limit enforced by the controller, not a region the policy learned
to stay inside. The xArm firmware documents a **Safety Boundary** that stops motion when the
TCP exceeds a configured Cartesian boundary `[DS]`. Configure it to the smallest box that
contains the task, and set it before the first autonomous rollout, not after the first
surprise.

**Speed.** The arm's documented maxima are 1 m/s at the end effector and 180 deg/s per joint
`[DS]` -- those are what an unbounded policy can command. **Reduced Mode** limits max
Cartesian linear speed, max joint speed and joint range `[DS]`. Rung 2 and rung 3 of the
ladder in 8 run in it.

**Force and contact.** Collision detection exists with sensitivity levels 0-5, where **0
disables it** `[DS]`. Understand what it is before relying on it: UFACTORY's own support
documentation states that "by comparing the theoretical current and actual current of each
joint, the system determines whether a collision has occurred," with the expected current
predicted from a dynamic model using joint position, speed, acceleration, load weight, center
of mass, mounting direction and friction parameters. The vendor documents its own failure
modes: wrong payload mass or center of gravity, wrong mounting direction, and friction
parameter mismatch after a controller replacement all cause false triggers or missed
detection, and **dynamic payloads must be reported to the controller during pick-and-place**
`[DS]`.

That last clause is the lab case exactly. A plate that is empty on the way in and full on the
way out is a payload change mid-task, and a collision detector running on the wrong mass is a
detector with an unknown threshold.

An independent limit is better: the first-party F/T sensor (150 N Fx/Fy, 200 N Fz, 4 Nm,
7) exposes FT-based collision detection with configurable thresholds and rebound through the
SDK `[DS]`. Use it as a bound the policy cannot see, not as an input the policy learns to
game.

**Stop paths.** An emergency stop button on the control box, plus a protective stop input.
Documented behavioural difference: on E-stop the program stops and reset is manual; on
protective stop the program suspends and reset can be automatic or manual `[DS]`. Timing:
pressing the control box E-stop sends a software deceleration command, clears cached
commands, and "the power supply for the robotic arm will be removed within 300ms" `[DS]`.
Safety I/O exists in redundant pairs which "must be kept in two separate branches. A single
I/O failure should not result in the loss of safety features." `[DS]` A three-position
enabling switch is documented as an accessory `[DS]`.

Print the vendor's own caveat above the bench: **"The emergency stop should not be used as a
risk reduction measure."** `[DS]` It is what you press when the bounding already failed.

### What is not established, and must not be assumed

- **ISO/TS 15066** -- the technical specification governing collaborative power-and-force
  limiting -- is **not referenced anywhere in the manual**: zero hits for "15066", zero for
  "ISO/TS". No power-and-force-limiting validation for any xArm model could be confirmed
  `[DS]`.
- **EN ISO 10218-1:2011 is listed under "Applied Standards" for CE purposes only.** Zero hits
  for "PL d", "Category 3" or "safety-rated" in the manual. **Do not assume the E-stop,
  protective stop, reduced mode or safety boundary are rated safety functions** `[DS]`.
- **The CE statement names xArm 6 only** (models XI1300-XI1305, certified and tested by SGS).
  No equivalent certification statement for xArm 5 or xArm 7 was located in that manual
  `[DS]`.
- **Collision detection sensitivity 0-5 are dimensionless levels.** There is no published
  force in newtons, no pressure, and no stopping-distance or stopping-time data anywhere in
  the documentation. Treating it as an operator-safety function is engineering practice, not a
  validated safety result `[PRACTICE]`.
- **"Cobot" is reseller and community framing.** The word "collaborative" appears essentially
  nowhere in the manual's specification or safety sections `[DS]`. Do not let the label do
  risk-assessment work.
- **The vendor assigns application-level safety to you.** From the F/T sensor manual: the
  robot, sensor and all other equipment "must be evaluated with a risk assessment. The robot
  integrator must ensure that all local safety measures and regulations are respected."
  `[DS]` In a lab, the integrator is the person reading this.

### The lab-specific interlocks no datasheet covers

- **No autonomous motion while a person is inside the envelope.** Physical guarding or a
  presence interlock. Not a policy behavior, not a convention, not a sign.
- **Nothing moves over an open reagent, a sample rack, or a scarce input** unless a dropped or
  swept plate landing there is acceptable. This is a layout decision made once.
- **Payload reported to the controller on every state change**, per the collision-detection
  failure modes above.
- **An interlock whose miss rate nobody has measured is not an interlock.** This is
  `autonomous_lab/vision.py`'s rule verbatim: a detector whose sensitivity has not been
  measured on held-out real failures "is not a safety device. It is a source of false
  confidence, and installing one makes a lab less safe than having none, because the operator
  stops looking." That applies to an F/T threshold and a camera-based guard identically. Set
  the threshold, then **test it against the actual failure** -- drive the arm into the
  condition deliberately, at reduced speed, and record whether the interlock fired.
- **The fixture is inside the safety argument.** A printed fixture that shifts mid-run puts
  the instrument at risk and is silent by construction -- nothing in it reports its own
  position, and the first evidence is the collision `[repo: PRINTED_FIXTURES 5]`.

---

## 8. The order to do it in

A ladder, in the shape `autonomous_lab/printed.py` already uses for printed parts, and with
the same rule stated first because it is the whole content:

> **NO RUNG IMPLIES THE ONE ABOVE IT.** Each rung tests a different physical claim and the
> claims are independent. Simulation success says nothing about the arm. The arm moving
> safely over an empty deck says nothing about contact. Contact with a dry fixture says
> nothing about material. And material moving says nothing about the experiment working,
> because nobody measured the outcome.

### Rung 1 -- simulation

*What it establishes.* The code path runs end to end. Observation and action shapes are what
you think. The training loop converges to something. Gross failures -- inverted axes,
mis-scaled actions, a gripper command in the wrong units -- surface here for free.

*What it does not establish.* Real performance. A visual-matching simulator correlated with
real-world policy ranking at r = 0.924 for specific embodiments and tasks `[EXP:
arXiv:2405.05941]`, which is a genuinely encouraging number and is not a licence to
generalize: a controlled re-evaluation states that "common simulation benchmarks are not a
reliable proxy for real world performance" `[EXP: CoRL 2023, arXiv:2310.09289]`, and
sim-screen-then-hardware-confirm on a new setup is an engineering bet rather than an
established result `[PRACTICE]`.

*The specific trap at this rung.* Simulation numbers get quoted as hardware numbers. DP3's
"10 demonstrations" and Diffusion Policy's 200/300 counts are both simulation figures that
circulate as real-robot capability claims (5).

### Rung 2 -- empty deck, reduced speed

*What it establishes.* The policy's commanded trajectory stays inside the envelope, does not
drive into the deck, and does not saturate a joint. This is `Rung.DRY_RUN` from the printed
guide, applied to a policy instead of a part.

*Preconditions.* Safety Boundary configured to the task box. Reduced Mode on. Collision
detection at a sensitivity you chose deliberately and not at 0. Payload configured for what is
actually on the flange. E-stop in reach of a hand that is on it. All of 7 in place before the
first autonomous step, because this is the first time nobody is driving.

*What it does not establish.* Anything about contact. Nothing is there to contact.

### Rung 3 -- fixture and labware, no material

*What it establishes.* The policy's trajectory against real geometry. This is where the
printed fixture earns or loses its `FITTED` and `DRY_RUN` rungs from
`docs/PRINTED_FIXTURES.md` 4, and where a set of failures becomes available that rung 2 could
not reach:

- the plate is not the nominal plate (SLAS footprint tolerance is +/-0.25 mm only near the
  corners and +/-0.5 mm elsewhere; corner radius spans 1.58 to 4.78 mm);
- the lip does not retain the plate at angle, if a wedge is involved;
- the stack height puts the plate outside the Z envelope;
- the part shifts under arm contact -- the failure that puts the instrument at risk and that
  no rung below this one can see.

*And a policy-specific one:* if the fixture was not in the demonstrations, its appearance in
frame is now out of distribution, and the policy has never seen this image. That is a rung-3
discovery and it is cheap here and expensive later.

*What it does not establish.* Anything about material. A dry plate weighs differently and
spills nothing.

### Rung 4 -- material, with an assay reading the outcome

*What it establishes.* Whether the task was accomplished, as opposed to whether the arm moved.
The assay is the external criterion from 6, and it is what turns a run into a
`teaching.MachineObservation` -- a value with a metric, units, conditions, and evidence you can
go back to. Without it you have a recording of motion.

*Requirements, which are 6 restated as a checklist.* Criterion defined and pre-registered.
Scored by someone blind to which policy ran, where that is possible. Reported as k out of n,
with the held-out factors named. Trial count chosen from the interval table, against the
decision you actually need to make. Checkpoint frozen before the first trial. Batch
pre-committed or a sequential procedure used. Judged on the worst observation, not the mean.

*What it still does not establish.* That the result transfers to a different plate type, a
different liquid, a different volume, a different aspiration height, or a reprinted fixture.
Each of those is its own condition, in the sense `teaching.Envelope` refuses to pool: an
envelope is a range over **one** experiment, and pooling two widens it past the failure it
existed to catch.

### The demotion rule

Any of these sends the system back down, and the rung it goes back to is the one that first
tested the thing that changed:

| event | back to |
| --- | --- |
| camera moved, remounted, or refocused | rung 2, and re-evaluate at rung 4 -- the policy did not read the calibration (2) |
| fixture reprinted, or filament/spool/lot changed | rung 3 -- it is a different part until measured again (4) |
| gripper, wrist camera, or payload changed | rung 2 -- collision detection depends on the dynamic model (7) |
| arm remounted, re-zeroed, or controller replaced | rung 2 -- friction parameters and mounting direction feed the same model |
| plate vendor or labware lot changed | rung 3 -- tolerances are per-product, not per-standard |
| new checkpoint | rung 4, with a fresh frozen checkpoint and a fresh trial batch |

None of these is paranoia. Each names a variable that is inside the training distribution and
is not recorded anywhere unless you record it.

---

## What this guide refuses to tell you

Kept as a list rather than buried, because the gaps are the part most likely to get filled in
by somebody's search results.

- **A success rate for any lab manipulation task.** None has been published. Every figure
  quoted above is bound to the paper, task, hardware and trial count it came from, and none of
  those is a plate on a deck.
- **A number of demonstrations for a new task.** Not knowable in advance. The published
  real-robot range spans about 400x, the only controlled study finds diversity dominates count,
  and the most-quoted paper ran no ablation on the question at all.
- **A demonstration-count multiplier for a physical fixture.** No study uses a physical fixture
  as the manipulated variable against an unfixtured control. The measurement that would produce
  one is a paired collection with and without the nest, on the same task, evaluated per 6.
- **A controlled measurement of the third-person viewpoint penalty specifically.** Searched
  for; not found. Most successful video-to-action results use egocentric capture, depth, or
  multi-view triangulation, so the third-person monocular case is the one with the least
  evidence and the most enthusiasm.
- **A millimeter figure for human-to-robot-hand retargeting error.** One paper defines exactly
  the right metrics and reports them only as bar charts with no numeric values in the text
  reached.
- **A mapping from N mm of hand-eye calibration error to M mm of end-effector error on a
  manipulation task.** Searched for specifically; not found. Papers analyze reprojection error,
  or robot kinematic error, or policy success rate, and nothing closes that loop. The
  small-angle amplification arithmetic in 2 is this guide's own calculation, offered as a check
  to run rather than a published result.
- **How fast a hand-eye calibration drifts out of tolerance in a working cell.** No published
  study. Every recalibration-frequency figure located is vendor guidance.
- **Whether recalibrating a moved camera restores a policy.** No study runs that experiment.
  The inference that it does not, for pixel-space policies, rests on those architectures taking
  no extrinsics input -- which is confirmed, but is not the same as the experiment.
- **Any independently measured accuracy, repeatability or payload validation for xArm 5/6/7.**
  Everything traces to UFACTORY documentation or its own storefront.
- **A price for the arm.** Two of the vendor's own US web properties disagree. Get a quote.
- **Whether the arm's safety functions carry a Performance Level or Category rating**, and
  whether any power-and-force-limiting validation exists. Zero hits for 15066, PL d, Category 3
  or safety-rated in a 254-page manual.
- **Per-task demonstration counts for pi-0 and pi-0.5.** They do not exist in the papers, which
  report hours. Any per-task number attributed to them is from outside them.
- **Whether any published policy trained with zero action information anywhere in the pipeline
  performs a real manipulation task at useful rates.** Searched; not found. Absence of evidence
  from a targeted search, not proof of impossibility.
- **Whether any of the published success rates quoted here are statistically distinguishable
  from each other.** Real-robot trial counts are small throughout -- 25, 20, and in one case 5
  -- and none of these papers reports confidence intervals on real-robot success except one
  standard deviation across tasks in DP3.

---

## Sources

Capture, retargeting, and what video does not carry
- *Phantom: Training Robots Without Robots Using Only Human Videos*, CoRL 2025,
  arXiv:2503.00779 -- teleop-vs-video exchange rate, per-task rates, and the paper's own scope
  limits (pinch grasps only, quasi-static only, capped by the hand pose estimator).
- *What Matters When Cotraining Robot Manipulation Policies on Everyday Human Videos?*,
  arXiv:2606.06627 (4 Jun 2026) -- cotraining gain versus robot-data scale; hand-pose noise
  injection; monocular estimator substitution. Dated seven weeks before this writing and not
  independently replicated.
- *Human2Sim2Robot*, CoRL 2025, arXiv:2504.12609 -- 20-30 cm hand pose errors; morphological
  argument against direct retargeting.
- *LAPA: Latent Action Pretraining from Videos*, ICLR 2025, arXiv:2410.11758 -- action-free
  pretraining, action-labeled finetuning, and the fine-motor deficit.
- *Latent Action Learning Requires Supervision in the Presence of Distractors*, ICML 2025,
  arXiv:2502.00379 -- 2.5% action supervision, 4.2x downstream improvement.
- *UMI: Universal Manipulation Interface*, RSS 2024, arXiv:2402.10329 -- proprioception
  ablation, capture precision, collection-rate comparison against bare hands.
- *DexMachina*, arXiv:2505.24853 and *SPIDER*, arXiv:2511.09484 -- kinematic retargeting is not
  dynamically feasible, and the machinery built to repair it.
- Learning-from-observation theory: NeurIPS 2019, arXiv:1910.04417 (inverse-dynamics
  disagreement bound); arXiv:2102.10769 (injectivity requirement).
- *Open X-Embodiment*, arXiv:2310.08864 -- cross-embodiment cotraining as a low-data rescue
  that can be a tax on data-rich embodiments.

Calibration and viewpoint
- IEEE Transactions on Robotics and Automation, 1989 -- AX=XB formulation and the
  non-parallel-axis requirement. Accuracy figures from the original were not verified.
- PLOS ONE 2022, *Accuracy evaluation of hand-eye calibration techniques for vision-guided
  robots* -- noise-dependent solver ranking; explicit statement that real-data ground truth is
  unavailable.
- Frontiers in Robotics and AI 7:65 (2020) -- static versus motion-mode residuals and the
  timestamp-synchronization attribution.
- arXiv:2303.06766 -- next-best-view pose selection; 4.74 to 2.95 mm with the algorithm fixed.
- Sensors 24(1):113 (2024) -- solver comparison and reprojection-error optimization.
- Sensors 22(24):9997 (2022) -- 1.49 px maximum thermal image drift, 5 to 45 C.
- *Decomposing the Generalization Gap in Imitation Learning for Visual Robotic Manipulation*,
  ICRA 2024, arXiv:2307.03659 -- real-robot factor ranking, camera pose hardest.
- *LIBERO-Plus*, arXiv:2510.13626 -- camera perturbation collapse across nine VLAs (simulation).
- *THE COLOSSEUM*, RSS 2024, arXiv:2402.08191 -- 2D versus 3D model sensitivity to camera pose.
  Its perturbation units could not be confirmed and are not reproduced here.
- *Do You Know Where Your Camera Is? View-Invariant Policy Learning with Camera Conditioning*,
  ICRA 2026, arXiv:2510.02268 -- the shortcut mechanism, and confirmation that the standard
  baselines take no extrinsics input.

Demonstration counts
- ACT / ALOHA, RSS 2023, arXiv:2304.13705. Verified by direct PDF text extraction (counts,
  Tables I and II).
- Diffusion Policy, RSS 2023 and arXiv:2303.04137v5 (IJRR extended). Verified by direct PDF
  text extraction (Table 3, Section 7, Appendix C). Table 3 and Appendix C.2.1 contradict each
  other on the sauce tasks.
- Mobile ALOHA, CoRL 2024, arXiv:2401.02117. Verified by direct PDF text extraction (Section
  6.1, Figure 4, Tables 3 and 4).
- DP3 / 3D Diffusion Policy, RSS 2024, arXiv:2403.03954.
- ALOHA Unleashed, CoRL 2024, arXiv:2410.13126 -- **single HTML fetch, not re-verified against
  the PDF.**
- *Data Scaling Laws in Imitation Learning for Robotic Manipulation*, ICLR 2025,
  arXiv:2410.18647.
- pi-0, arXiv:2410.24164; pi-0.5, arXiv:2504.16054 -- both report hours, not per-task counts.

Fixtures and pose variance
- *ManiBox*, arXiv:2411.01850 -- spatial scaling law and its five measured points (simulation).
- *MimicGen*, CoRL 2023, arXiv:2310.17596 -- D0/D1/D2 reset distributions at fixed budget;
  generation rates; the 10-demonstration source-agent results including 0% on real hardware.
- *Learning from 10 Demos: Generalisable and Sample-Efficient Policy Learning with Oriented
  Affordance Frames*, CoRL 2025, arXiv:2410.12124.
- *Equivariant Diffusion Policy*, IJRR 2026, DOI 10.1177/02783649261424445.
- Discrete analogue only: NeurIPS 2020, *Toward the Fundamental Limits of Imitation Learning*
  -- tabular BC bound linear in state-space size. Cited as an analogue, not as support for a
  continuous-pose claim.

Evaluation
- *Robot Learning as an Empirical Science: Best Practices for Policy Evaluation*,
  arXiv:2409.09491 (Sept 2024).
- *A Careful Examination of Large Behavior Models for Multitask Dexterous Manipulation*,
  arXiv:2507.05331 (July 2025; also Science Robotics) -- blind protocol, roughly 1,800 real
  trials, the 27% QA audit.
- *Is Your Imitation Learning Policy Better than Mine? Policy Comparison with Near-Optimal
  Stopping*, RSS 2025, arXiv:2503.10966 -- the p-hacking warning; STEP.
- *Beyond Binary Success*, arXiv:2603.13616 (March 2026) -- anytime-valid inference; graded
  scores separate policies faster.
- *Evaluating Real-World Robot Manipulation Policies in Simulation* (SIMPLER), CoRL 2024,
  arXiv:2405.05941 -- validation MSE at Pearson r = 0.308.
- *Deep Reinforcement Learning that Matters*, AAAI 2018, arXiv:1709.06560 -- seed variance;
  explicit refusal to name a minimum trial count.
- *RoboArena*, CoRL 2025, arXiv:2506.18123 -- distributed double-blind pairwise evaluation as a
  check on single-lab distributions.
- *PhAIL*, arXiv:2605.29710 -- the 13-paper survey of trial counts. Single-author preprint,
  convenience sample.
- CoRL 2023, arXiv:2310.09289 -- pretraining image distribution matters more than scale, and
  simulation benchmarks are not a reliable proxy for real-world performance. Full text was not
  reachable; abstract- and summary-level claims only.
- A GPU vendor's engineering blog, 2026-07-11, on evaluating general-purpose robot policies --
  used only for its Clopper-Pearson figures, which were independently reproduced here. Its
  benchmark details were not verified.

Arm documentation, read directly
- xArm User Manual V2.0.0 (254 pp), text extracted locally. Appendix 2 Technical Specifications
  pp. 217-221; E-stop p. 23; Dedicated Safety I/O p. 52; Maximum Payload p. 237; Appendix 7
  Applied Standards pp. 231-233.
- UFACTORY 6 Axis Force Torque Sensor manual V2.5.2. Section 5 Technical Specifications p. 12;
  Section 3.1 SDK control p. 9; Section 1.2 overload values and risk assessment p. 3.
- UFACTORY support article on current- and dynamic-model-based collision detection.
- `xArm-Developer/xArm-Python-SDK` -- BSD 3-Clause LICENSE and `doc/api/xarm_api.md`.

Repo cross-references
- `docs/PRINTED_FIXTURES.md` -- 1 the contact boundary, 4 the qualification ladder, 5 shrinkage
  and the failure modes, 6 the tilt module and its acceptance test.
- `hardware/README.md`, `hardware/tilt_module.scad` -- the worked fixture, its parameters, and
  the replicate design this guide's rung 4 reuses.
- `autonomous_lab/printed.py` -- `Rung`, `DimensionState`, `Contact`, and the refusal table.
- `autonomous_lab/teaching.py` -- `MIN_DEMONSTRATIONS`, `Envelope`, `Attainment`, and the rule
  that one good machine run is not parity.
- `autonomous_lab/vision.py` -- `VisionRequirement.VALIDATION`, and why an unmeasured detector
  makes a lab less safe than none.
- `autonomous_lab/qc.py` -- `Basis`, and the broken absorbance read that disqualifies an optical
  endpoint here.
