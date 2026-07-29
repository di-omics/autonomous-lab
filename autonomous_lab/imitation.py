"""Whether a captured demonstration can train an arm, and whether the policy may touch material.

Three layers in this package each hold a piece of this question and none of them states it.
`vision` says what a camera can see and what a visual check needs before it is a check
rather than an aspiration. `printed` says whether a fixture may be used for a purpose, and
refuses a part whose dimensions were never measured. `teaching` says what an expert
demonstrated and refuses to state a tolerance under three demonstrations. What nobody
composes is the sentence that sells the whole idea to a lab: record the expert once on
video, train the arm from the recording, print a fixture to make the task easy enough to
learn. This module computes whether that sentence holds for a particular capture, and the
answer turns on three distinctions the sentence elides.

A VIDEO IS NOT A DEMONSTRATION. A policy needs ACTIONS, and pixels are not actions. A
teleoperated or hand-guided capture records the robot's own joint states at controller rate,
so the action stream is MEASURED -- it is what the machine did, in the machine's own action
space, with its gripper width and its proprioception alongside. A third-person human video
contains no joint states at any resolution. Getting actions out of it takes hand pose
estimation and then retargeting across an embodiment gap, and BOTH of those are steps that
can be wrong, rather than a format conversion that cannot. The measured cost of pretending
otherwise: injecting calibrated noise into triangulated hand labels moved mean success from
48.3 percent to 30.0 percent at half a sigma and to 20.0 percent at one sigma, and swapping
multi-view triangulation for a real monocular estimator produced 185.67 mm mean per-joint
error and dropped mean success from 41.5 to 24.7 percent. A second group reports 3D hand
pose errors from video "as large as 20-30 cm" and responds by discarding the human's actions
entirely. There is also a case where no estimator helps: recovering an action from an
observed state transition needs the dynamics to be injective, and a redundant arm posture or
a force pressed against a rigid constraint changes no visible state at all, so the action is
unrecoverable in principle rather than in practice. The honest head-to-head number, from the
one work that ran it, is an exchange rate and not an equivalence: on the same sweeping task,
50 teleoperated episodes reached 52 percent and 50 human-video episodes reached 44 percent,
while 100 teleoperated reached 88 percent and it took 300 human-video episodes to reach 84.
So `Modality.measured_action_stream` names which captures carry actions rather than
estimates of actions, and `equivalent_to_teleop` returns False for every retargeted capture
no matter how good the pipeline is, because the pipeline is the thing that was never
measured here.

THE FIXTURE IS PART OF THE POLICY'S WORLD, AND THAT CUTS BOTH WAYS. This is the connection
to `printed` and it is the non-obvious one. A nest that constrains an object's pose removes
degrees of freedom the policy would otherwise have to learn from data, and there is real
published evidence for the direction of that effect -- see `FixtureCoupling`, which is also
careful about how much of the usual claim the evidence actually supports. The part nobody
says out loud is the other direction: the demonstrations were collected against a SPECIFIC
fixture, so the fixture is inside the policy's observation and inside its action
distribution. Reprint that fixture with a tuned clearance, a new spool, a different machine
or a different shrinkage and the policy is now running against a world it never saw, with
every demonstration behind it collected against the old one. Nothing in the run reports
this. The arm moves to the same taught coordinates, the plate is a millimetre high in the
pocket, and the policy is confidently doing the wrong thing. So `FixtureCoupling` carries
the revision the captures were taken against and `fixture_coupled` computes whether a
proposed run is still coupled to it -- and it will not accept a matching revision STRING as
proof, because a revision names a model file, `printed` refuses to estimate shrinkage for a
material at all, and two prints of one file are not established to be one geometry until
somebody puts an instrument on both.

A POLICY IS UNTRUSTED UNTIL MEASURED ON HELD-OUT TRIALS, AGAINST AN EXTERNAL CRITERION. Two
different numbers get reported as success rates and neither one is one. The first is a rate
computed on the initial conditions the demonstrations were collected from, which is
structurally optimistic: behavior cloning is trained on the expert's state distribution and
its own errors carry it off that distribution, with suboptimality compounding as the square
of the horizon rather than linearly, and the effect only appears when the policy is rolled
out from starts nobody demonstrated. The measured version of that gap: 11 of 12 on training conditions against 11 of 24 at a new camera position (95 percent intervals 61.5 to 99.8 and 25.6 to 67.2), which
is the only one of the reported shifts distinguishable from baseline at that trial count. A new
table texture. The second is any criterion that reads the policy's own state. A policy
reporting high confidence on a transfer that failed is precisely the silent destructive
failure `coverage` is built around -- a number arrives, the check passes, and the material is
already gone -- and offline loss is barely better as a proxy, at a measured Pearson r of
0.308 against real-world ranking where a visual-matching simulator reached 0.924. So `Trust`
has exactly one trusted state and it requires held-out trials AND a criterion that does not
read the policy. Underneath it, `success_rate` refuses a point estimate below a declared
trial floor and reports an exact interval rather than a bare percentage where it reports
anything, because at 20 trials one trial is 5 percentage points and a 90 percent observation
carries a 95 percent interval of 68.3 to 98.8 -- which does not distinguish a policy that
works from one that fails one attempt in three.

WHAT THIS MODULE WILL NOT DO. It returns no demonstration count for a new task, no exchange
rate between a human video and a teleoperated episode, no success rate from a handful of
trials, and no probability that the next attempt works. `demonstrations_needed` is the
sharpest case: the published real-robot per-task counts span 20 to 8,658, a spread of more
than two orders of magnitude, and the only controlled study of the question found that
environment and object DIVERSITY dominates raw count -- so a single number would be a
convention dressed as a measurement. `NOT_ESTIMATED` names each refusal and what would lift
it, in the form `durability` uses, and reuses that module's `Refusal` rather than defining a
second dataclass with the same three fields.

AUTHORITY, IN PROSE. A learned policy PROPOSES a motion; a deterministic interlock DISPOSES.
Workspace, speed and force belong to something that does not read the policy's output, has
no confidence to be wrong about, and cannot be argued out of a limit by a fluent one. That
boundary is not modelled here and is deliberately not imported: see `INTERLOCK_NOTE` for
what such a layer has to be, and for why the vendor features usually pointed at -- a reduced
mode, a Cartesian safety boundary, current-and-model collision detection on dimensionless
sensitivity levels -- are documented conveniences rather than rated safety functions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .durability import Refusal
from .printed import Fixture
from .qc import Basis
from .vision import VisionRequirement


# -- how a capture carries actions -------------------------------------------------


class Modality(str, Enum):
  """How a demonstration was captured, ordered by how directly it carries actions.

  The ordering is the argument. At the top the action stream is a recording of what a
  machine did; at the bottom it is the output of an estimator run over pixels, and every
  member in between trades some of the first thing for some of the convenience of the
  second. Nothing here says the bottom of the list does not work -- a video-only pipeline
  reached 92 percent on pick-and-place of a book and 64 percent on tying a rope, which is
  a working policy by any standard. It says the bottom of the list is not the top of it,
  and that a module which stores both in one field will eventually compare them as though
  they were.

  MONOCULAR_HUMAN_VIDEO is the member the pitch usually means by "just record it on your
  phone", and it is the one with a measured penalty rather than a suspected one: the study
  that swapped multi-view triangulation for a real monocular hand estimator measured 185.67
  mm mean per-joint position error and mean success falling from 41.5 to 24.7 percent.
  """

  TELEOPERATION = "teleoperation"  # leader-follower or jog; the robot executed it
  KINESTHETIC = "kinesthetic"  # hand-guided on the arm itself; its own encoders recorded it
  HANDHELD_GRIPPER = "handheld_gripper"  # real gripper hardware in the human's hand
  INSTRUMENTED_HUMAN_VIDEO = "instrumented_human_video"  # RGBD or multi-view; pose estimated
  MONOCULAR_HUMAN_VIDEO = "monocular_human_video"  # one third-person camera, no depth

  @property
  def measured_action_stream(self) -> bool:
    """Whether the action was RECORDED by an instrument rather than estimated from pixels.

    True for the three hardware-in-the-loop captures and false for both video ones. The line
    is not "human versus robot" and not "cheap versus expensive": it is whether an estimator
    with an unmeasured error sits between the capture and the action label. A handheld
    gripper clears it because the jaw width is read off the device and the end-effector pose
    comes from on-device geometry with a stated trajectory error of 6.1 mm and 3.5 deg,
    which is a measurement of the capture rather than a hope about it.
    """
    return self in (
      Modality.TELEOPERATION,
      Modality.KINESTHETIC,
      Modality.HANDHELD_GRIPPER,
    )

  @property
  def on_the_robots_own_kinematics(self) -> bool:
    """Whether the recorded action is in the action space of the robot that will replay it.

    The stricter line, and the one `equivalent_to_teleop` keys off. A handheld gripper
    matches the OBSERVATION space by construction and still hands the controller a pose
    recorded by a device with different mass, different reach and no joint limits -- both
    failures in the one twenty-trial cross-embodiment transfer counted here were joint limit
    violations. It also cannot measure force: grasp force is inferred from finger deformation,
    and the one clean ablation of the signal a video physically cannot contain -- relative
    inter-gripper proprioception -- took bimanual cloth folding from 70 to 30 percent.
    """
    return self in (Modality.TELEOPERATION, Modality.KINESTHETIC)


MODALITY_EVIDENCE: Dict[Modality, str] = {
  Modality.TELEOPERATION: (
    "actions are recorded in the robot's own action space at controller rate, with "
    "proprioception, gripper width and joint configuration alongside. This is what the "
    "frontier models are still built on: one generalist policy is pretrained on roughly "
    "10,000 hours of teleoperated data across 68 tasks and 7 robot configurations. What the "
    "usual phrase 'zero embodiment gap' overstates is that teleoperated data is still "
    "OFF-POLICY with respect to the state distribution a trained policy visits, which is the "
    "covariate-shift problem behavior cloning has had since it was named"
  ),
  Modality.KINESTHETIC: (
    "hand-guiding records the same joint states as teleoperation, on the arm that will "
    "replay them, and adds the constraint that a human hand was inside the envelope while it "
    "happened. No published comparison of kinesthetic against teleoperated data was located "
    "here, so the two are treated as one class on the grounds that both read the robot's own "
    "encoders -- which is an argument from mechanism and not a measurement"
  ),
  Modality.HANDHELD_GRIPPER: (
    "the real gripper in the human's hand, so observation and action spaces match by "
    "construction. Measured capture precision is 6.1 mm and 3.5 deg mean absolute trajectory "
    "error, 10.1 mm and 0.8 deg inter-gripper relative pose. Task rates from 250 to 305 "
    "episodes: cup arrangement 20 of 20, dynamic tossing 105 of 120, bimanual cloth folding "
    "14 of 20, dish washing 14 of 20. It does not measure force -- grasp force is inferred "
    "from finger deformation -- and bare-hand collection, the thing this replaces, runs at "
    "only 48 to 64 percent of the handheld device's own collection speed, so the cost "
    "argument for going further down this list is weaker than it sounds"
  ),
  Modality.INSTRUMENTED_HUMAN_VIDEO: (
    "RGBD or multi-view capture with hand pose estimation and retargeting. This is the "
    "configuration behind every human-video result that actually executes a task, and it is "
    "not action-free -- it is action-INFERRED, with explicit end-effector pose and gripper "
    "width derived from depth and a hand mesh. Head to head against teleoperation on one "
    "sweeping task: 50 teleoperated 52 percent, 50 human-video 44 percent, 100 teleoperated "
    "88 percent, 300 human-video 84 percent. Stated scope limits from the same work: pinch "
    "grasps only, quasi-static tasks only, and it works only where the robot can follow the "
    "same strategy the human did"
  ),
  Modality.MONOCULAR_HUMAN_VIDEO: (
    "one third-person camera and no depth, which is what 'internet-scale video' actually "
    "means. It is the measured degraded case rather than the suspected one: substituting a "
    "real monocular hand estimator for multi-view triangulation gave 185.67 mm mean "
    "per-joint position error and took mean success from 41.5 to 24.7 percent. No published "
    "policy trained with zero action information anywhere in the pipeline was located here "
    "that performs a real manipulation task at useful rates -- an absence of evidence from "
    "this search rather than a proof of impossibility, and worth stating as the first, "
    "because it is the claim the pitch rests on"
  ),
}


@dataclass(frozen=True)
class Retargeting:
  """The step that turns a human's hand into a robot's action, and what measured it.

  Carried as its own object because the alternative is a boolean on `Capture` reading
  `retargeted=True`, and a boolean invites the reading that retargeting is a conversion
  somebody performed rather than a model somebody fitted. It is the second of two estimators
  in series -- hand pose, then the map onto a gripper that has different kinematics -- and
  each has its own error.

  `error_measured_mm` is the field that is almost never filled in. No verified millimetre
  figure for human-to-robot retargeting error was located here at all: the work that defines
  the right metrics reports them only as unlabelled bar charts. The two magnitudes that ARE
  published belong to the hand-pose stage, at 185.67 mm mean per-joint error for a monocular
  estimator and 3D errors "as large as 20-30 cm" from another group, so an unmeasured
  retargeting is not a small unknown. Kinematic validity is also not the end of it: hands
  retargeted to six dexterous robot hands produced human-like motions that were "not
  feasible for completing the task" when replayed in simulation.

  `basis` is `qc.Basis` and `validated` demands IN_HOUSE for the same reason a threshold
  does. A retargeting error measured on somebody else's arm, hand and camera is evidence
  about their pipeline.

  A measured error must be a positive distance. Zero and negative are refused at
  construction rather than reported as an unusually good pipeline, because both are the
  signature of a value that was defaulted or sign-flipped rather than measured, and this
  field's whole job is to be the one number nobody filled in.
  """

  method: str = ""
  depth_or_multiview: bool = False
  error_measured_mm: Optional[float] = None
  basis: Basis = Basis.INTUITION
  note: str = ""

  def __post_init__(self) -> None:
    if self.error_measured_mm is not None and self.error_measured_mm <= 0:
      raise ValueError(
        f"a retargeting error of {self.error_measured_mm} mm is not a measurement. An error "
        "is a positive distance; zero and negative are the signature of a defaulted or "
        "sign-flipped value, and this field exists precisely because it is the one nobody "
        "fills in. Leave it None if it was not measured"
      )

  @property
  def declared(self) -> bool:
    return bool(self.method)

  @property
  def validated(self) -> bool:
    return self.declared and self.error_measured_mm is not None and self.basis.validated

  def missing(self) -> Tuple[str, ...]:
    """Exactly what stands between this pipeline and `validated`, and nothing else.

    The monocular caveat is deliberately not in this list. Being monocular is a property of
    the capture rather than a gap in the validation, and a measured error on a monocular rig
    is still a measurement -- it is reported where it belongs, next to the refusal that uses
    it, rather than here where it would read as a requirement nobody can meet after the fact.
    """
    out: List[str] = []
    if not self.declared:
      out.append("no retargeting method is named")
    if self.error_measured_mm is None:
      out.append("no retargeting error was measured on this capture")
    elif not self.basis.validated:
      out.append(
        f"the retargeting error rests on {self.basis.value}, which is evidence about somebody "
        "else's pipeline"
      )
    return tuple(out)


# -- the capture -------------------------------------------------------------------


@dataclass(frozen=True)
class Capture:
  """One recording somebody hopes to train from, with every field at its untrusted value.

  Constructible with no arguments, and a capture constructed that way trains nothing. That
  is the test this dataclass exists to pass, and it is the same discipline `printed.Fixture`
  applies: a default that reads as a pass turns a recording nobody checked into a training
  set.

  `episodes` counts recordings, not usable ones, and nothing here converts a count into a
  sufficiency claim -- see `demonstrations_needed`, which refuses to.

  `coupling` is on the capture rather than on the policy because the fixture is a property
  of the session that was recorded, and a policy trained on two sessions against two fixture
  revisions is coupled to neither. `Policy.training_coupling` enforces exactly that, in the
  way `teaching.Envelope` refuses to pool two sets of conditions into one range.
  """

  name: str = ""
  modality: Optional[Modality] = None
  episodes: int = 0
  retargeting: Retargeting = field(default_factory=Retargeting)
  timestamps_synchronized: bool = False
  camera_calibrated: bool = False
  gripper_state_recorded: bool = False
  coupling: Optional["FixtureCoupling"] = None
  note: str = ""

  def __post_init__(self) -> None:
    if self.episodes < 0:
      raise ValueError(f"capture '{self.name or 'unnamed'}' declares {self.episodes} episodes")
    measured = self.modality is not None and self.modality.measured_action_stream
    if measured and self.retargeting.declared:
      raise ValueError(
        f"capture '{self.name or 'unnamed'}' is {self.modality.value}, which records the "
        "action directly, and also declares a retargeting method. One capture cannot both "
        "measure its actions and estimate them, and a record that claims both will be read "
        "as whichever is more convenient"
      )

  @property
  def carries_actions(self) -> bool:
    """Whether an action stream exists at all, measured or inferred.

    An inferred one counts here and does not count in `equivalent_to_teleop`. Those are
    different questions: whether there is anything to train on, and whether what there is
    can stand in for the thing it is being compared to.
    """
    if self.modality is None:
      return False
    return self.modality.measured_action_stream or self.retargeting.declared


# -- what stands between a capture and a training set --------------------------------


class Trainable(str, Enum):
  """Whether a capture can train a policy, and if not, what specifically is missing.

  USABLE is a member of the same enum as the refusals, following `printed.Fitness`, because
  usability is the absence of every refusal rather than a state of its own. No field sets it.

  `needs_recapture` is the line worth acting on. Some of these are cleared by doing work on
  data that already exists -- write down the modality, calibrate the camera that has not
  moved, measure the retargeting error. The rest are cleared only by recording the session
  again, because the missing signal was never written to disk and no processing recovers it.
  A report that mixes the two sends a lab to reprocess a dataset that has to be recollected.
  """

  MODALITY_UNDECLARED = "modality_undeclared"
  NO_EPISODES = "no_episodes"
  NO_ACTION_STREAM = "no_action_stream"
  RETARGETING_UNVALIDATED = "retargeting_unvalidated"
  TIMESTAMPS_UNSYNCHRONIZED = "timestamps_unsynchronized"
  CAMERA_UNCALIBRATED = "camera_uncalibrated"
  GRIPPER_STATE_MISSING = "gripper_state_missing"
  USABLE = "usable"

  @property
  def usable(self) -> bool:
    return self is Trainable.USABLE

  @property
  def needs_recapture(self) -> bool:
    return self in (
      Trainable.NO_EPISODES,
      Trainable.NO_ACTION_STREAM,
      Trainable.TIMESTAMPS_UNSYNCHRONIZED,
      Trainable.GRIPPER_STATE_MISSING,
    )


# Reported in this order. USABLE is not in it: it is what is left when nothing else applies.
_MISSING_ORDER: Tuple[Trainable, ...] = (
  Trainable.MODALITY_UNDECLARED,
  Trainable.NO_EPISODES,
  Trainable.NO_ACTION_STREAM,
  Trainable.RETARGETING_UNVALIDATED,
  Trainable.TIMESTAMPS_UNSYNCHRONIZED,
  Trainable.CAMERA_UNCALIBRATED,
  Trainable.GRIPPER_STATE_MISSING,
)


@dataclass(frozen=True)
class Missing:
  """One thing a capture lacks, named specifically enough to go and get."""

  reason: Trainable
  detail: str


@dataclass(frozen=True)
class Usability:
  """One capture, costed against what training actually requires.

  Carries every refusal rather than returning on the first, for the reason
  `printed.Assessment` does: a capture is usually short of more than one thing, and a report
  showing only the headline sends somebody to fix that and rediscover the next one after a
  week of reprocessing.
  """

  capture: Capture
  missing: Tuple[Missing, ...]

  @property
  def usable(self) -> bool:
    return not self.missing

  @property
  def verdict(self) -> Trainable:
    return self.missing[0].reason if self.missing else Trainable.USABLE

  def reasons(self) -> Tuple[Trainable, ...]:
    return tuple(m.reason for m in self.missing)

  def details(self) -> Tuple[str, ...]:
    return tuple(m.detail for m in self.missing)

  @property
  def needs_recapture(self) -> bool:
    return any(m.reason.needs_recapture for m in self.missing)

  @property
  def reason(self) -> str:
    if self.missing:
      return self.missing[0].detail
    return (
      f"'{self.capture.name or 'this capture'}' carries an action stream, synchronized "
      "timestamps, a calibrated camera and a gripper state. That is a training set and not a "
      "trained policy, and it says nothing about what the policy will do"
    )


def usable_for_training(capture: Capture) -> Usability:
  """Everything standing between this recording and a training set.

  Every check runs. Nothing shortcuts on a missing modality, because a capture with no
  declared modality still either has synchronized timestamps or does not, and a report that
  hid the rest behind the first refusal would understate the work by four items.
  """
  found: List[Missing] = []

  if capture.modality is None:
    found.append(
      Missing(
        Trainable.MODALITY_UNDECLARED,
        "no modality is declared, so whether the action stream was recorded or estimated "
        "cannot be resolved, and that is the distinction the whole question turns on. An "
        "undeclared capture is not a neutral one: it will be read as whichever modality the "
        "reader was hoping for",
      )
    )

  if capture.episodes <= 0:
    found.append(
      Missing(
        Trainable.NO_EPISODES,
        "the capture holds no episodes. A session that was configured and never recorded "
        "looks identical in a manifest to one that was recorded, which is why the count is "
        "checked rather than assumed from the record existing",
      )
    )

  if not capture.carries_actions:
    found.append(
      Missing(
        Trainable.NO_ACTION_STREAM,
        "there is no action stream: the modality does not record one and no retargeting is "
        "declared to infer one. A policy is a map from observation to ACTION, and pixels are "
        "the observation half. Recovering the missing half from video needs the dynamics to "
        "be injective, and a redundant arm posture or a force pressed against a rigid "
        "constraint changes no visible state at all, so for those the action is unrecoverable "
        "in principle and not merely unrecovered here",
      )
    )
  elif capture.modality is not None and not capture.modality.measured_action_stream:
    if not capture.retargeting.validated:
      detail = (
        "the action stream is inferred by a retargeting pipeline that nobody measured here: "
        + "; ".join(capture.retargeting.missing())
        + ". Retargeting is an additional fitted step, not a format conversion. Calibrated "
        "noise on hand labels moved mean success from 48.3 to 30.0 percent at half a sigma "
        "and to 20.0 at one sigma, and supplying ground-truth actions for as little as 2.5 "
        "percent of a dataset improved downstream performance 4.2-fold -- which is a "
        "measurement of what action labels buy that video cannot supply"
      )
      if not capture.retargeting.depth_or_multiview:
        detail += (
          ". The capture is also monocular, which is the configuration that measured 185.67 mm "
          "mean per-joint error and mean success falling from 41.5 to 24.7 percent"
        )
      found.append(Missing(Trainable.RETARGETING_UNVALIDATED, detail))

  if not capture.timestamps_synchronized:
    found.append(
      Missing(
        Trainable.TIMESTAMPS_UNSYNCHRONIZED,
        "camera frames and the action stream are not synchronized to a common clock, so every "
        "training pair is an observation matched with an action from an unknown time offset. "
        "The magnitude is not subtle: in a hand-eye study the same calibration procedure gave "
        "1.57 mm of residual error in static mode and 18.89 mm in motion mode, and the authors "
        "attributed the roughly fortyfold degradation to imprecise timestamp synchronization "
        "rather than to the mathematics. A constant offset teaches the policy to act late; a "
        "varying one teaches it noise",
      )
    )

  if not capture.camera_calibrated:
    found.append(
      Missing(
        Trainable.CAMERA_UNCALIBRATED,
        "the camera pose is not calibrated or recorded -- the requirement `vision` already "
        f"names as {VisionRequirement.POSE.value}. Two separate things need it. Retargeting "
        "human video into the robot's frame is impossible without metric camera geometry. And "
        "a pixel-space policy, which is what the standard architectures are, never reads the "
        "extrinsics at all: it infers the viewpoint from the scene and silently encodes it, so "
        "what the calibration buys is the ability to REPRODUCE the training viewpoint at "
        "rollout. Camera pose is the measured-hardest shift there is -- 11 of 12 on training conditions against 11 of 24 at a new camera position (95 percent intervals 61.5 to 99.8 and 25.6 to 67.2). "
        "Separately and in SIMULATION, orientation "
        "perturbations of 2 to 10 deg, which is a sloppy remount, collapsed one model from "
        "perturbations of 2 to 10 deg dropped nine models by between 19 and 91 points, a "
        "spread wider than the effect for several of them",
      )
    )

  if not capture.gripper_state_recorded:
    found.append(
      Missing(
        Trainable.GRIPPER_STATE_MISSING,
        "no gripper state is recorded, so the capture cannot say when the hand closed. Every "
        "pick is a reach the policy can imitate and a grasp it cannot, and the failure this "
        "produces is specific and known: the reported failure modes on the worst task in the "
        "reference set were the gripper closing too early and imprecise insertion. Estimating "
        "the width from a thumb-to-fingertip distance is the standard heuristic and is "
        "convention rather than a validated mapping -- the work that uses it restricts itself "
        "to pinch grasps precisely because of it",
      )
    )

  by_reason = {m.reason: m for m in found}
  ordered = tuple(by_reason[r] for r in _MISSING_ORDER if r in by_reason)
  return Usability(capture=capture, missing=ordered)


def equivalent_to_teleop(capture: Capture) -> Tuple[bool, str]:
  """Does this capture stand in for a teleoperated one, episode for episode?

  Answers no for everything that is not recorded on the robot's own kinematics, including a
  fully validated retargeting pipeline and including a handheld gripper. The refusal is not
  a judgment about quality. It is that the one published head-to-head exchange measured
  roughly three human-video episodes to approach -- not beat -- what one teleoperated
  episode bought, on a quasi-static sweeping task with pinch grasps, which is the friendliest
  possible setting for the comparison. Treating the two as interchangeable turns that
  exchange rate into a silent multiplier on every count downstream.
  """
  if capture.modality is None:
    return False, (
      "no modality is declared, so this capture is not established to be equivalent to "
      "anything. An undeclared capture defaults to untrusted here for the same reason an "
      "unbenchmarked operation does in `intelligence.trusted_for`"
    )
  if capture.modality.on_the_robots_own_kinematics:
    return True, (
      f"{capture.modality.value} records the robot's own joint states at controller rate, so "
      "the action stream is what the machine did. This is equivalence of FORMAT and not of "
      "quality: teleoperated data is still off-policy with respect to the distribution the "
      "trained policy will visit"
    )
  if capture.modality is Modality.HANDHELD_GRIPPER:
    return False, (
      "a handheld gripper matches the observation and action spaces by construction and is "
      "still not a teleoperated episode: the pose is recorded by a device with different mass "
      "and reach and no joint limits, force is inferred from finger deformation rather than "
      "measured, and the one clean ablation of relative inter-gripper proprioception -- a "
      "signal this capture has and a video does not -- took bimanual cloth folding from 70 to "
      "30 percent success"
    )
  detail = (
    f"{capture.modality.value} carries no measured action stream. The published exchange rate "
    "on the one head-to-head comparison located here is roughly 3 human-video episodes to "
    "approach what 1 teleoperated episode buys -- 50 teleoperated 52 percent against 50 "
    "human-video 44, and 100 teleoperated 88 against 300 human-video 84 -- inside stated "
    "limits of pinch grasps and quasi-static tasks"
  )
  if capture.retargeting.validated:
    return False, (
      detail
      + ". This capture's retargeting IS measured, which makes it usable for training and "
      "does not make it teleoperation: a measured estimator is still an estimator, and the "
      "exchange rate was measured against pipelines at least this good"
    )
  return False, (
    detail
    + ". This capture's retargeting is also unmeasured, so the exchange rate above is an "
    "optimistic bound on it rather than a description of it"
  )


# -- the fixture the demonstrations were collected against ----------------------------


class Coupling(str, Enum):
  """Whether a proposed run faces the fixture the policy learned against.

  `holds` is true for exactly one member, and UNVERIFIED is the member that makes the enum
  worth having. Two parts printed from one revision of one file are not established to be
  one geometry: `printed` refuses to estimate shrinkage for a material at all, on the
  grounds that no filament datasheet checked there publishes one and two vendors' slicer
  profiles disagree by 0.5 percent on the same polymer. A revision string is a fact about a
  file. The policy was trained against a part.
  """

  COUPLED = "coupled"  # same fixture, same revision, and both parts were measured
  UNVERIFIED = "unverified"  # revision strings match and at least one part was never measured
  REVISED = "revised"  # same fixture, different revision
  DIFFERENT_FIXTURE = "different_fixture"
  MIXED = "mixed"  # the captures were collected against more than one fixture revision
  UNIDENTIFIED = "unidentified"  # a side names no fixture, or names one with no revision

  @property
  def holds(self) -> bool:
    return self is Coupling.COUPLED


@dataclass(frozen=True)
class FixtureCoupling:
  """The fixture a set of demonstrations was collected against, and the revision of it.

  WHAT THE EVIDENCE SUPPORTS, since the variance-reduction claim is usually stated far more
  strongly than it has been measured. The direction is real and measured twice. A simulated
  grasping study fitted required data against the volume the object's position was randomized
  over and got an exponent of 0.35 on volume, with measured points running 728 trajectories
  at a fixed point up to 24,005 over a 41 by 30 by 28 cm space. A generation study held the
  demonstration budget fixed at 1,000 and varied only the reset distribution: with the
  receptacle rigidly fixed -- a fixture in all but name -- square-peg assembly reached 90.7
  percent, and with both objects free it fell to 49.3; three-piece assembly went 82.0 to 13.3.

  WHAT THE SAME EVIDENCE COSTS THE CLAIM. That 0.35 exponent on VOLUME is about 1.05 in
  linear extent, so cutting placement scatter by a factor of two in each axis -- eight times
  less volume -- buys roughly two times less data, not eight. In the same fixed-budget table,
  block stacking went from 100.0 percent in a 16 cm region to 99.3 in a 40 cm one: on an easy
  low-precision task, constraining pose bought seven tenths of a point. And the strongest
  version of the pitch is contradicted outright -- agents trained on the 10 human source
  demonstrations and evaluated INSIDE the narrow fixtured region they were collected in
  scored 11.3 and 19.3 and 1.3 percent in simulation, and 0 percent on the real robot. A
  fixture shifts the data curve. It does not collapse the requirement to a handful of
  demonstrations.

  WHAT IS ENGINEERING PRACTICE AND NOT EVIDENCE. The 3-2-1 locating principle, which is the
  textbook justification for every jig ever cut, has no publication behind it that quantifies
  its effect on a learned policy's demonstration count. Neither does any figure of the form
  "a nest cuts demonstrations by N times" for a laboratory workcell. Every quantified source
  located here substitutes something for the physical fixture -- a randomization range in
  simulation, a reset distribution at a fixed budget, or software pose canonicalization,
  where anchoring the frame to the object reached with 10 demonstrations what an image-based
  policy needed 305 to match. No study manipulates a PHYSICAL fixture with an unfixtured
  control and counts human demonstrations. That study does not exist in this evidence set.

  `fixture` is the `printed.Fixture` itself where a caller has one, so the question of
  whether the part was ever measured resolves in the module that owns it rather than being
  re-asserted here with a boolean that can drift.
  """

  fixture_name: str = ""
  revision: str = ""
  fixture: Optional[Fixture] = None
  constrains: Tuple[str, ...] = ()  # which degrees of freedom the part removes, in plain words
  note: str = ""

  @property
  def identified(self) -> bool:
    """A fixture with no revision is not identified. A revision is what changes underneath."""
    return bool(self.fixture_name) and bool(self.revision)

  @property
  def anchored(self) -> bool:
    """Whether the revision names a part somebody measured, rather than only a model file.

    Resolved through `printed.Fixture.dimensions_measured`, which already refuses the vacuous
    pass where a part declaring no critical dimensions reads as fully measured.
    """
    return self.fixture is not None and self.fixture.dimensions_measured()

  def key(self) -> Tuple[str, str]:
    return (self.fixture_name, self.revision)

  def describe(self) -> str:
    if not self.identified:
      return "an unidentified fixture"
    return f"'{self.fixture_name}' rev {self.revision}"


@dataclass(frozen=True)
class CouplingCheck:
  """One policy's training fixture against the fixture a proposed run would face."""

  training: Optional[FixtureCoupling]
  proposed: Optional[FixtureCoupling]
  state: Coupling
  reason: str

  @property
  def holds(self) -> bool:
    return self.state.holds


def fixture_coupled(policy: "Policy", proposed: Optional[FixtureCoupling]) -> CouplingCheck:
  """Is a proposed run still coupled to the fixture the policy learned on?

  Refuses in five distinguishable ways rather than returning a boolean, because the five cost
  different work: recollect, reprint to the old revision, measure both parts, name the
  fixture, or split the training set. A boolean would send every one of them to the same
  place.
  """
  training = policy.training_coupling()

  if training is None:
    if len(policy.distinct_couplings()) > 1:
      names = "; ".join(c.describe() for c in policy.distinct_couplings())
      return CouplingCheck(
        None,
        proposed,
        Coupling.MIXED,
        f"this policy's captures were collected against {len(policy.distinct_couplings())} "
        f"different fixture revisions ({names}), so it is coupled to none of them. Pooling "
        "them is the same error `teaching.Envelope` refuses when it will not put two sets of "
        "conditions in one range: the union is wider than either, and wide is not the safe "
        "direction here -- it hides which part the policy actually learned against",
      )
    return CouplingCheck(
      None,
      proposed,
      Coupling.UNIDENTIFIED,
      "no capture behind this policy names the fixture it was collected against. The fixture "
      "is inside the policy's observations whether or not anybody wrote it down, so an "
      "unrecorded one cannot be reproduced and cannot be shown to have changed",
    )

  if proposed is None or not proposed.identified:
    return CouplingCheck(
      training,
      proposed,
      Coupling.UNIDENTIFIED,
      f"the policy was trained against {training.describe()} and the proposed run names no "
      "identified fixture. An unnamed part is not the same part; it is an unknown one",
    )

  if not training.identified:
    return CouplingCheck(
      training,
      proposed,
      Coupling.UNIDENTIFIED,
      f"the captures name '{training.fixture_name or 'no fixture'}' with no revision, so there "
      "is nothing for the proposed run to match. A fixture without a revision cannot be shown "
      "to be unchanged, which is the only thing this check can establish",
    )

  if training.fixture_name != proposed.fixture_name:
    return CouplingCheck(
      training,
      proposed,
      Coupling.DIFFERENT_FIXTURE,
      f"the policy learned against {training.describe()} and the run proposes "
      f"{proposed.describe()}. This is not a degraded coupling, it is a different world",
    )

  if training.revision != proposed.revision:
    return CouplingCheck(
      training,
      proposed,
      Coupling.REVISED,
      f"the policy learned against {training.describe()} and the run proposes revision "
      f"{proposed.revision}. Every demonstration behind this policy was collected against the "
      "old part, and a reprint changes clearance, shrinkage and first-layer width together -- "
      "`printed` will not estimate shrinkage for a material at all, and quotes desktop "
      "tolerance at plus or minus 0.5 percent with a floor of plus or minus 0.5 mm, scaling "
      "with length. Nothing in the run reports this: the arm moves to the same taught "
      "coordinates and the pose it was trained to expect is somewhere else",
    )

  if not (training.anchored and proposed.anchored):
    unmeasured = []
    if not training.anchored:
      unmeasured.append("the part the captures were taken against")
    if not proposed.anchored:
      unmeasured.append("the part the run would use")
    return CouplingCheck(
      training,
      proposed,
      Coupling.UNVERIFIED,
      f"both sides name {training.describe()} and no measurement anchors that to a part: "
      f"{' and '.join(unmeasured)} carries no measured critical dimension. A revision is a "
      "fact about a model file. Two prints of one file are not established to be one geometry, "
      "which is why `printed.DimensionState` keeps DESIGNED and MEASURED apart -- and this is "
      "cleared by a caliper rather than by a different part",
    )

  return CouplingCheck(
    training,
    proposed,
    Coupling.COUPLED,
    f"the run faces {proposed.describe()}, the revision the demonstrations were collected "
    "against, and both parts carry measured critical dimensions. This says the world the "
    "policy learned is the world it will meet. It says nothing about whether it learned it",
  )


# -- measuring a policy ---------------------------------------------------------------


class SuccessCriterion(str, Enum):
  """What counted as a success, which is the part of a success rate nobody writes down.

  `external` is the load-bearing line and it is drawn at whether the criterion reads the
  policy's own state. TRAINING_LOSS is on the wrong side of it and belongs in the enum
  because it is the most respectable-looking way to land there: offline validation error
  against real-world policy ranking measured a Pearson r of 0.308, where a visual-matching
  simulator on the same comparison reached 0.924.

  OPERATOR_SCORED clears the line and is the weakest thing that does. It is a human, and a
  human is outside the policy, which is the whole requirement. It is not free of error: a
  quality audit of 27 percent of roughly 2,700 rollouts in the most careful published
  campaign found a 2.31 percent discrepancy on the success label itself.
  """

  POLICY_CONFIDENCE = "policy_confidence"  # the policy grading its own rollout
  TRAINING_LOSS = "training_loss"  # offline error standing in for real success
  OPERATOR_SCORED = "operator_scored"  # a person watching the rollout and calling it
  EXTERNAL_MEASUREMENT = "external_measurement"  # an instrument or assay outside the policy

  @property
  def external(self) -> bool:
    return self in (SuccessCriterion.OPERATOR_SCORED, SuccessCriterion.EXTERNAL_MEASUREMENT)


# How much a single trial is allowed to move the reported number, in percentage points. This
# is a convention and is stated rather than buried: no published result establishes any
# minimum trial count, one careful group states outright that the required N depends on the
# true performance gap and so cannot be fixed in advance, and the canonical
# unreported-variance paper explicitly declines to name a number. What the convention buys is
# that the arithmetic stops being absurd -- at 5 trials one trial is 20 points, which is the
# published row where "40 percent" is 2 successes out of 5. Raising this would be defensible.
# Having no floor is not.
MAX_TRIAL_WEIGHT_PP = 5.0

# The floor that follows from it, computed rather than picked: one trial is 100/n points.
MIN_HELDOUT_TRIALS = int(math.ceil(100.0 / MAX_TRIAL_WEIGHT_PP))

# Field practice, for calibration rather than as a target: the modal real-robot evaluation in
# the papers surveyed here runs 10 to 20 trials per condition, and the reference works run 25,
# 20 and 20. This floor sits at the top of that range and is still wide enough to be
# uninformative about a 5 point difference -- separating 85 percent from 90 percent at
# conventional power needs 686 trials per policy, which is not a number any of them ran.

# The coverage every interval in this module is reported at.
CONFIDENCE = 0.95


def _log_choose(n: int, k: int) -> float:
  return math.lgamma(n + 1.0) - math.lgamma(k + 1.0) - math.lgamma(n - k + 1.0)


def _binom_at_most(k: int, n: int, p: float) -> float:
  """P(X <= k) for X ~ Binomial(n, p), summed in log space so large n does not overflow."""
  if p <= 0.0:
    return 1.0
  if p >= 1.0:
    return 1.0 if k >= n else 0.0
  lp = math.log(p)
  lq = math.log1p(-p)
  total = 0.0
  for i in range(0, k + 1):
    total += math.exp(_log_choose(n, i) + i * lp + (n - i) * lq)
  return min(1.0, total)


def _binom_at_least(k: int, n: int, p: float) -> float:
  """P(X >= k) for X ~ Binomial(n, p)."""
  if p <= 0.0:
    return 1.0 if k <= 0 else 0.0
  if p >= 1.0:
    return 1.0
  lp = math.log(p)
  lq = math.log1p(-p)
  total = 0.0
  for i in range(k, n + 1):
    total += math.exp(_log_choose(n, i) + i * lp + (n - i) * lq)
  return min(1.0, total)


def _bisect(fn, target: float, decreasing: bool) -> float:
  lo, hi = 0.0, 1.0
  for _ in range(80):
    mid = 0.5 * (lo + hi)
    value = fn(mid)
    if (value > target) == decreasing:
      lo = mid
    else:
      hi = mid
  return 0.5 * (lo + hi)


def success_interval(
  successes: int, trials: int, confidence: float = CONFIDENCE
) -> Tuple[float, float]:
  """The exact Clopper-Pearson interval on an observed rate, as fractions.

  Exact rather than normal-approximate because every trial count in this domain is small
  enough for the approximation to be the wrong tool, and conservative rather than
  average-coverage because the direction of the error matters here: this module exists to
  stop a policy being trusted with material, so an interval that is slightly too wide fails
  in the safe direction and one that is slightly too narrow does not. That choice is a
  convention -- a statistical one this evidence set does not adjudicate -- and it is stated
  rather than implied.
  """
  if trials <= 0:
    raise ValueError("an interval needs at least one trial; there is nothing to bound")
  if successes < 0 or successes > trials:
    raise ValueError(f"{successes} successes in {trials} trials is not an observation")
  alpha = (1.0 - confidence) / 2.0
  low = 0.0 if successes == 0 else _bisect(
    lambda p: _binom_at_least(successes, trials, p), alpha, decreasing=False
  )
  high = 1.0 if successes == trials else _bisect(
    lambda p: _binom_at_most(successes, trials, p), alpha, decreasing=True
  )
  return low, high


@dataclass(frozen=True)
class Evaluation:
  """Rollouts of a trained policy, and what counted as a success.

  Every default is the untrusted one. `held_out` defaults False because the natural thing to
  do with a trained policy is run it from the setups that were demonstrated, and that number
  is the one that gets quoted; `criterion` defaults to the policy grading itself because that
  is the reading a script produces with no extra work.

  `blinded` is recorded and is NOT required for trust. Blind, interleaved evaluation is
  advocated everywhere and no published robotics study located here measures the size of the
  bias non-blind scoring introduces, so requiring it would be inventing a threshold out of
  hygiene. Reporting it is free; demanding it on this evidence would be the same overreach
  this module refuses elsewhere.
  """

  trials: int = 0
  successes: int = 0
  held_out: bool = False
  criterion: SuccessCriterion = SuccessCriterion.POLICY_CONFIDENCE
  blinded: bool = False
  note: str = ""

  def __post_init__(self) -> None:
    if self.trials < 0:
      raise ValueError(f"an evaluation cannot have {self.trials} trials")
    if self.successes < 0:
      raise ValueError(f"an evaluation cannot have {self.successes} successes")
    if self.successes > self.trials:
      raise ValueError(
        f"{self.successes} successes in {self.trials} trials is not an observation; a rate "
        "above 1 is the arithmetic telling you the two numbers came from different places"
      )


@dataclass(frozen=True)
class RateReport:
  """A success rate with its interval, or the refusal to state one.

  `point` is None wherever the rate is refused, never 0.0 and never the raw fraction with a
  warning attached, for the reason `printed.CriticalDimension.deviation_mm` returns None
  rather than zero: a number in the field will be read, and any string beside it will not.
  """

  evaluation: Evaluation
  stated: bool
  point: Optional[float]
  low: Optional[float]
  high: Optional[float]
  reason: str

  @property
  def width_pp(self) -> Optional[float]:
    if self.low is None or self.high is None:
      return None
    return 100.0 * (self.high - self.low)

  def describe(self) -> str:
    if not self.stated or self.point is None:
      return f"no rate: {self.reason}"
    return (
      f"{self.evaluation.successes} of {self.evaluation.trials} "
      f"({100.0 * self.point:.1f} percent, 95 percent interval "
      f"{100.0 * (self.low or 0.0):.1f} to {100.0 * (self.high or 0.0):.1f})"
    )


def success_rate(evaluation: Evaluation) -> RateReport:
  """A rate, or a refusal, with the raw counts either way.

  Four things are refused before any arithmetic happens, and the order is from cheapest to
  most expensive to fix. No trials at all. A rate computed on the conditions the
  demonstrations came from, which is not a success rate: behavior cloning is trained on the
  expert's state distribution and its own errors carry it off that distribution, with
  suboptimality compounding as the square of the horizon rather than linearly, and the gap
  only shows up from starts nobody demonstrated -- measured at 11 of 12 on training conditions against 11 of 24 at a new camera position (95 percent intervals 61.5 to 99.8 and 25.6 to 67.2).
  A criterion that reads the policy's own
  state. And too few trials to say anything, which is a refusal of the POINT ESTIMATE
  specifically: the counts and the interval are the honest report, and the percentage is the
  thing that gets quoted without them.
  """
  ev = evaluation
  if ev.trials <= 0:
    return RateReport(
      ev,
      False,
      None,
      None,
      None,
      "no rollout happened. A policy nobody ran has no rate, and the absence is not a zero or "
      "a pending value -- it is the untrusted default this package applies to every unmeasured "
      "thing",
    )

  if not ev.held_out:
    return RateReport(
      ev,
      False,
      None,
      None,
      None,
      f"{ev.successes} of {ev.trials} were scored on the conditions the demonstrations were "
      "collected from, which is not a success rate. The policy's own errors are what carry it "
      "off the demonstrated state distribution, and that effect is invisible from a start the "
      "expert also started from. Measured elsewhere at 11 of 12 on training conditions against 11 of 24 at a new camera position (95 percent intervals 61.5 to 99.8 and 25.6 to 67.2). The reported "
      "table-texture and lighting drops are not distinguishable from baseline at that trial "
      "count and are not quoted here",
    )

  if not ev.criterion.external:
    return RateReport(
      ev,
      False,
      None,
      None,
      None,
      f"success was scored by {ev.criterion.value}, which reads the policy's own state. A "
      "policy reporting high confidence on a transfer that failed is the silent destructive "
      "failure `coverage` is built around: a number arrives, the check passes, and the "
      "material is already gone. Offline loss is not the safer version of this -- validation "
      "error against real-world policy ranking measured a Pearson r of 0.308",
    )

  point = ev.successes / ev.trials
  low, high = success_interval(ev.successes, ev.trials)

  if ev.trials < MIN_HELDOUT_TRIALS:
    weight = 100.0 / ev.trials
    return RateReport(
      ev,
      False,
      None,
      None,
      None,
      f"{ev.successes} of {ev.trials} held-out trials: one trial is {weight:.1f} percentage "
      f"points, above the declared ceiling of {MAX_TRIAL_WEIGHT_PP:.1f}, and the exact 95 "
      f"percent interval spans {100.0 * low:.1f} to {100.0 * high:.1f} percent. A point "
      "estimate off this many trials is a number that will be quoted without its interval. The "
      "counts are reported instead, which is what lets a reader reconstruct the interval "
      "themselves. No published result establishes a minimum trial count -- the floor here is "
      "a stated convention, not a measured threshold",
    )

  return RateReport(
    ev,
    True,
    point,
    low,
    high,
    f"{ev.successes} of {ev.trials} held-out trials scored by {ev.criterion.value}"
    + ("" if ev.blinded else ", unblinded")
    + f". The interval is {100.0 * (high - low):.1f} percentage points wide; narrowing it is "
    "roughly fifteen times the rollouts for a fivefold narrowing, so this width is a budget "
    "decision that was already made when the trial count was chosen",
  )


class Trust(str, Enum):
  """Whether a trained policy may be handed material, and if not, what is missing.

  Ordered by how far the evidence gets. Only MEASURED is trusted, and it requires BOTH a
  held-out trial count at or above the declared floor AND a criterion that does not read the
  policy's own state. Neither condition substitutes for the other, which is why they are two
  conditions: a thousand trials scored by the policy's own confidence measure the policy's
  confidence, and one external measurement on one rollout is an anecdote with an instrument
  attached.

  MEASURED does not mean good. It means a number exists with an interval around it and an
  outside criterion behind it, and the number can perfectly well be 20 percent -- which is
  what the hardest task in the reference set actually scored, on twice the demonstrations of
  any other.
  """

  UNEVALUATED = "unevaluated"  # no rollouts at all
  TRAINING_SET_ONLY = "training_set_only"  # rolled out from the conditions it was trained on
  SELF_SCORED = "self_scored"  # the criterion reads the policy's own state
  UNDERPOWERED = "underpowered"  # held out and externally scored, too few trials to state a rate
  MEASURED = "measured"  # held out, external criterion, at or above the declared floor

  @property
  def evidence_complete(self) -> bool:
    """The evaluation was done properly. NOT a statement that the policy works.

    Named for what it is, because the previous name was `trusted` and returned True for a
    policy that succeeded in zero of twenty held-out trials. Every word in this enum's
    docstring said MEASURED does not mean good, and the boolean said the opposite to anyone
    who read it instead of the prose. A property that contradicts its own docstring is worse
    than an absent one: it is an authorization-shaped answer to a question nobody asked.
    """
    return self is Trust.MEASURED


@dataclass(frozen=True)
class TrustAssessment:
  """One policy's standing, with the rate report that produced it."""

  policy: "Policy"
  verdict: Trust
  rate: RateReport
  reason: str
  # The rate this task was declared to tolerate, and whether the interval's lower bound
  # cleared it. Both are None/False unless a caller supplied a threshold, because whether a
  # rate is good enough is a property of the task rather than of the evaluation.
  acceptable_rate: Optional[float] = None
  clears: bool = False

  @property
  def evidence_complete(self) -> bool:
    """The evaluation was run properly. Says nothing about whether the policy works."""
    return self.verdict.evidence_complete

  @property
  def trusted(self) -> bool:
    """Properly evaluated AND measured against a declared acceptance rate that it cleared.

    Both halves are required. The first without the second returns False, which is the whole
    fix: this used to be `verdict.trusted`, and a policy that succeeded in zero of twenty
    held-out trials came back True because the evaluation had been conducted correctly.
    """
    return self.evidence_complete and self.clears


def trusted_with_material(
  policy: "Policy", acceptable_rate: Optional[float] = None
) -> TrustAssessment:
  """Has this policy earned an unattended run on real material?

  A missing evaluation is not a pass, in exactly the way `intelligence.trusted_for` refuses an
  operation nobody benchmarked and `qc.evaluate` refuses a gate whose measurement never
  arrived. The default is untrusted and the burden is on the measurement.

  `acceptable_rate` is required for a trusted answer and has no default, because what rate is
  acceptable is a property of the TASK and not of this module. A tolerable failure rate for a
  tip pickup that a retry fixes is not a tolerable failure rate for a transfer that consumes
  the last of a sample. Defaulting it would be this package answering, on the caller's behalf
  and invisibly, the only question in the function that requires knowing what the robot is
  holding.

  It is compared against the LOWER bound of the interval rather than the point estimate. A
  point estimate is what the policy did on those trials; the lower bound is what the trials
  support saying about the next one, and the gap between them is the entire reason the trial
  count is in the report.
  """
  ev = policy.evaluation
  if ev is None or ev.trials <= 0:
    report = success_rate(ev if ev is not None else Evaluation())
    return TrustAssessment(
      policy,
      Trust.UNEVALUATED,
      report,
      f"'{policy.name or 'this policy'}' has never been rolled out. Training converged is not "
      "a result; it is a statement about a loss curve, and offline loss against real-world "
      "ranking measured a Pearson r of 0.308",
    )

  report = success_rate(ev)
  if not ev.held_out:
    return TrustAssessment(policy, Trust.TRAINING_SET_ONLY, report, report.reason)
  if not ev.criterion.external:
    return TrustAssessment(policy, Trust.SELF_SCORED, report, report.reason)
  if ev.trials < MIN_HELDOUT_TRIALS:
    return TrustAssessment(policy, Trust.UNDERPOWERED, report, report.reason)
  if acceptable_rate is None:
    return TrustAssessment(
      policy,
      Trust.MEASURED,
      report,
      f"{report.describe()}. The evaluation is complete and nothing here says whether that "
      "is good enough, because no acceptable rate was declared. State the rate this task "
      "tolerates and ask again",
      acceptable_rate=None,
      clears=False,
    )
  if report.low is None or report.low < acceptable_rate:
    shown = "no interval" if report.low is None else f"{100.0 * report.low:.1f} percent"
    return TrustAssessment(
      policy,
      Trust.MEASURED,
      report,
      f"{report.describe()}. The interval's lower bound is {shown}, below the "
      f"{100.0 * acceptable_rate:.1f} percent this task was declared to tolerate. The trials "
      "do not support running it unattended on material",
      acceptable_rate=acceptable_rate,
      clears=False,
    )
  return TrustAssessment(
    policy,
    Trust.MEASURED,
    report,
    f"{report.describe()}. This is a measured rate on held-out trials against an outside "
    "criterion, which is the most this module can say. It is a statement about this task, this "
    "fixture revision and this bench, and it does not transfer to another of any of them",
    acceptable_rate=acceptable_rate,
    clears=True,
  )


# -- the policy -----------------------------------------------------------------------


@dataclass(frozen=True)
class Policy:
  """A trained policy, its captures, and its evaluation if it has one.

  `method` is carried because the demonstration requirement is method-dependent and not only
  task-dependent: at an identical 50 demonstrations on one task, one architecture reached 95
  percent where another reached 65, and the paper's own explanation was that 50 is not enough
  for the more expressive model. A record that stores a count without the method has thrown
  away half of what the count meant.

  Everything derived is a method rather than a field, so nothing here can disagree with the
  captures it was derived from.
  """

  name: str = ""
  method: str = ""
  captures: Tuple[Capture, ...] = ()
  evaluation: Optional[Evaluation] = None
  note: str = ""

  def episodes(self) -> int:
    return sum(c.episodes for c in self.captures)

  def usability(self) -> Tuple[Usability, ...]:
    return tuple(usable_for_training(c) for c in self.captures)

  def unusable(self) -> Tuple[Usability, ...]:
    return tuple(u for u in self.usability() if not u.usable)

  def trainable(self) -> bool:
    """True only where at least one capture exists and every one of them is usable.

    The leading truthiness check is the method. `all()` over an empty tuple is True, so the
    one-liner reports a policy with no captures at all as trained on flawless data.
    """
    return bool(self.captures) and all(u.usable for u in self.usability())

  def distinct_couplings(self) -> Tuple[FixtureCoupling, ...]:
    seen: List[FixtureCoupling] = []
    keys = set()
    for c in self.captures:
      if c.coupling is None:
        continue
      if c.coupling.key() in keys:
        continue
      keys.add(c.coupling.key())
      seen.append(c.coupling)
    return tuple(seen)

  def training_coupling(self) -> Optional[FixtureCoupling]:
    """The one fixture revision every capture was collected against, or None.

    None for zero, None for two, and None when ANY capture recorded no fixture at all.

    That last case is the one that was wrong. `distinct_couplings` skips a capture whose
    coupling is None, so a policy trained on one fixtured session and two unrecorded ones
    reported a single clean coupling and a run against that fixture was permitted. Two thirds
    of the training data had been collected against a world nobody wrote down, and the report
    said COUPLED. An unrecorded fixture is not an absent one: the part was physically there
    and is inside the policy's observations whether or not it was named, so it cannot be
    reproduced and cannot be shown to have changed.
    """
    if any(c.coupling is None for c in self.captures):
      return None
    couplings = self.distinct_couplings()
    return couplings[0] if len(couplings) == 1 else None


@dataclass(frozen=True)
class Interlock:
  """A bound enforced outside the policy, by something that cannot learn.

  This is the leg the module was missing, and its absence is why a policy with no
  demonstrated capability could return an authorization-shaped permitted=True. A learned
  policy carries no guarantee about what it will do on an input it has not seen, so the
  bound on what it can physically reach, how fast, and how hard cannot come from the policy
  and cannot come from a model checking the policy. It comes from a coded limit, a
  controller setting, or a mechanical stop.

  `miss_rate_measured` is the load-bearing field and follows `vision`'s rule for detectors:
  a bound whose failure rate nobody measured is not a safety device, it is a belief about
  one. Measuring it means deliberately driving the violation and counting what the interlock
  actually stops, not observing that nothing bad happened during normal operation.
  """

  workspace_bounded: bool = False
  speed_bounded: bool = False
  force_bounded: bool = False
  enforced_by: str = ""  # what enforces it, outside the policy
  miss_rate_measured: bool = False

  @property
  def complete(self) -> bool:
    return (
      self.workspace_bounded
      and self.speed_bounded
      and self.force_bounded
      and bool(self.enforced_by.strip())
      and self.miss_rate_measured
    )

  def missing(self) -> Tuple[str, ...]:
    out: List[str] = []
    if not self.workspace_bounded:
      out.append("no workspace bound")
    if not self.speed_bounded:
      out.append("no speed bound")
    if not self.force_bounded:
      out.append("no force bound")
    if not self.enforced_by.strip():
      out.append("nothing named as enforcing the bounds outside the policy")
    if not self.miss_rate_measured:
      out.append("the interlock's own miss rate has never been measured against a driven violation")
    return tuple(out)


@dataclass(frozen=True)
class RunStanding:
  """One policy against one proposed run: may it move, and what stops it.

  The composition is the point, in the way `coverage` composes vision and gates. Each of the
  three questions is answerable and none of them is the question a lab asks. Trained on
  usable data, measured on held-out trials, and still facing the fixture it learned on --
  all three, or the run is not permitted.
  """

  policy: "Policy"
  proposed: Optional[FixtureCoupling]
  trust: TrustAssessment
  coupling: CouplingCheck
  captures: Tuple[Usability, ...]
  interlock: Interlock = field(default_factory=Interlock)

  @property
  def permitted(self) -> bool:
    return (
      bool(self.captures)
      and all(u.usable for u in self.captures)
      and self.trust.trusted
      and self.coupling.holds
      and self.interlock.complete
    )

  def blockers(self) -> Tuple[str, ...]:
    out: List[str] = []
    if not self.captures:
      out.append("this policy declares no captures at all, so nothing trained it")
    for u in self.captures:
      if not u.usable:
        out.append(
          f"capture '{u.capture.name or 'unnamed'}' is not usable for training: {u.reason}"
        )
    if not self.trust.trusted:
      out.append(f"trust is {self.trust.verdict.value}: {self.trust.reason}")
    if not self.coupling.holds:
      out.append(f"fixture coupling is {self.coupling.state.value}: {self.coupling.reason}")
    if not self.interlock.complete:
      out.append(
        "no complete interlock stands outside this policy: "
        + "; ".join(self.interlock.missing())
      )
    return tuple(out)


def may_run(
  policy: Policy,
  proposed: Optional[FixtureCoupling] = None,
  acceptable_rate: Optional[float] = None,
  interlock: Optional[Interlock] = None,
) -> RunStanding:
  """Compose the three questions into the one a lab actually asks.

  Nothing is re-derived here. Every arm is a report computed by the function that owns it, so
  this cannot disagree with any of them -- the same construction `intelligence.loop_closure`
  uses, and for the same reason.
  """
  return RunStanding(
    policy=policy,
    proposed=proposed,
    trust=trusted_with_material(policy, acceptable_rate),
    coupling=fixture_coupled(policy, proposed),
    captures=policy.usability(),
    interlock=interlock if interlock is not None else Interlock(),
  )


# -- how many demonstrations ------------------------------------------------------------


@dataclass(frozen=True)
class PublishedCount:
  """One published per-task demonstration count, with the method, task and trial count named.

  `trials` is beside `success` deliberately. Every success rate in this table came off 5 to 25
  rollouts, so the third digit of any of them is decoration: at 25 evaluations one trial is 4
  percentage points, at 20 it is 5, and at 5 it is 20. None of the source papers reports a
  confidence interval on a real-robot success rate.
  """

  system: str
  task: str
  demonstrations: Optional[int]
  trials: Optional[int]
  success: Optional[float]
  source: str
  note: str = ""


# The published real-robot per-task counts, with their tasks and methods named. The point of
# the table is its spread rather than any row in it.
PUBLISHED_COUNTS: Tuple[PublishedCount, ...] = (
  PublishedCount(
    "ACT on a bimanual low-cost platform", "Slide Ziploc", 50, 25, 0.88, "arXiv:2304.13705"
  ),
  PublishedCount(
    "ACT on a bimanual low-cost platform", "Slot Battery", 50, 25, 0.96, "arXiv:2304.13705"
  ),
  PublishedCount(
    "ACT on a bimanual low-cost platform", "Open Cup", 50, 25, 0.84, "arXiv:2304.13705"
  ),
  PublishedCount(
    "ACT on a bimanual low-cost platform",
    "Thread Velcro",
    100,
    25,
    0.20,
    "arXiv:2304.13705",
    note=(
      "the counter-evidence inside the reference paper itself: twice the demonstrations of "
      "every other task and the worst result of any. The authors attribute it to perception "
      "and precision rather than data volume, with success roughly halving at each stage from "
      "92 percent at the first to 20 final"
    ),
  ),
  PublishedCount(
    "ACT on a bimanual low-cost platform", "Prep Tape", 50, 25, 0.64, "arXiv:2304.13705"
  ),
  PublishedCount(
    "ACT on a bimanual low-cost platform", "Put On Shoe", 50, 25, 0.92, "arXiv:2304.13705"
  ),
  PublishedCount(
    "Diffusion Policy, real robot",
    "Push-T",
    136,
    None,
    0.95,
    "arXiv:2303.04137",
    note="proficient-human demonstrations; baselines on the same task scored 0 and 20 percent",
  ),
  PublishedCount("Diffusion Policy, real robot", "Mug Flip", 250, 20, 0.90, "arXiv:2303.04137"),
  PublishedCount(
    "Diffusion Policy, real robot",
    "Sauce Pour",
    None,
    None,
    0.79,
    "arXiv:2303.04137",
    note=(
      "the count is unresolved and reported as unresolved: the table lists 90 "
      "proficient-human demonstrations and the appendix says 50 were collected with 90 percent "
      "used for training. The paper contradicts itself in both versions"
    ),
  ),
  PublishedCount(
    "Diffusion Policy, bimanual", "Egg Beater", 210, 20, 0.55, "arXiv:2303.04137"
  ),
  PublishedCount(
    "Diffusion Policy, bimanual", "Mat Unrolling", 162, 20, 0.75, "arXiv:2303.04137"
  ),
  PublishedCount(
    "Diffusion Policy, bimanual", "Shirt Folding", 284, 20, 0.75, "arXiv:2303.04137"
  ),
  PublishedCount(
    "Mobile ALOHA with co-training",
    "Wipe Wine",
    50,
    20,
    0.95,
    "arXiv:2401.02117",
    note=(
      "the same 50 demonstrations WITHOUT co-training on a large auxiliary dataset scored 50 "
      "percent. The widely quoted 50-demo figure holds only with the auxiliary data, and 35 "
      "demonstrations with co-training beat 50 without, 70 percent against 50"
    ),
  ),
  PublishedCount(
    "Mobile ALOHA with co-training", "High Five", 20, 20, 0.85, "arXiv:2401.02117"
  ),
  PublishedCount(
    "Mobile ALOHA with co-training",
    "Cook Shrimp",
    20,
    5,
    0.40,
    "arXiv:2401.02117",
    note="40 percent of 5 trials is 2 successes, which is essentially uninformative",
  ),
  PublishedCount(
    "3D Diffusion Policy, real robot",
    "4-task average",
    40,
    None,
    0.85,
    "arXiv:2403.03954",
    note=(
      "the frequently repeated 10-demonstration figure from this work is a SIMULATION result "
      "across 72 sim tasks. On real hardware it used 40 per task"
    ),
  ),
  PublishedCount(
    "ALOHA Unleashed",
    "Shirt (easy)",
    8658,
    None,
    0.75,
    "arXiv:2410.13126",
    note=(
      "over 26,000 real demonstrations across 5 tasks, collected on 10 robots over eight "
      "months, on the same hardware lineage as the 50-demonstration rows above"
    ),
  ),
  PublishedCount("ALOHA Unleashed", "Lace (messy)", 5133, None, 0.40, "arXiv:2410.13126"),
  PublishedCount(
    "ALOHA Unleashed",
    "Gear insert",
    4005,
    None,
    0.95,
    "arXiv:2410.13126",
    note=(
      "95 percent for one gear, 75 for two, 40 for three. Demonstration count buys task "
      "difficulty and robustness rather than a march to 100 percent"
    ),
  ),
  PublishedCount(
    "Data-scaling study, real robot",
    "Fold Towels / Unplug Charger",
    1600,
    None,
    0.90,
    "arXiv:2410.18647",
    note=(
      "roughly 50 demonstrations per environment-object pair across 32 pairs. The measured "
      "finding is that diversity dominates: with environments and objects held fixed there was "
      "no clear relationship between demonstration count and generalization"
    ),
  ),
  PublishedCount(
    "A frontier vision-language-action model",
    "per task",
    None,
    10,
    None,
    "arXiv:2410.24164",
    note=(
      "reports HOURS rather than demonstration counts -- 5 hours for the simplest task and 100 "
      "or more for the most complex -- and scores a normalized score over 10 episodes rather "
      "than binary success. The unit of account changed, so these do not compare with the rows "
      "above at all"
    ),
  ),
)


# What the count actually depends on, each with the measurement behind it. Ordered by how
# large the measured effect was, not by how often the factor is mentioned.
DETERMINANTS: Tuple[str, ...] = (
  "environment and object DIVERSITY, which the only controlled real-robot study of the "
  "question found dominates raw count: performance plateaued at 400, 800 and 1,600 total "
  "demonstrations for 8, 16 and 32 environment-object pairs, and with those held fixed there "
  "was no clear relationship between count and generalization at all",
  "whether auxiliary or pre-training data is used. Co-training moved one task from roughly 0 "
  "to 95 percent at the same demonstration count, and 35 demonstrations with it beat 50 "
  "without",
  "task precision and horizon. The task that received twice the demonstrations of any other in "
  "the reference set produced the worst result of any, at 20 percent, and the failure was "
  "attributed to perception and precision rather than to data volume",
  "the method. At an identical 50 demonstrations on one task, one architecture reached 95 "
  "percent and another reached 65, with the paper's own explanation being that 50 is not "
  "enough for the more expressive model",
  "how much pose variance the setup leaves in, which is where a fixture enters. At a fixed "
  "1,000-demonstration budget, rigidly fixing the receptacle moved square-peg assembly from "
  "49.3 to 90.7 percent -- and moved an easy stacking task by seven tenths of one point",
)


@dataclass(frozen=True)
class DemonstrationEstimate:
  """The answer to "how many demonstrations", which is not a number.

  `estimate` is always None and the field exists so a caller cannot read the absence as an
  oversight. The refusal is carried as data for the same reason `printed.NOT_ESTIMATED` is:
  a module that declines a number in its docstring and exposes a helper returning one has
  documented a discipline it does not have.
  """

  task: str
  estimate: Optional[int]
  published: Tuple[PublishedCount, ...]
  determinants: Tuple[str, ...]
  refusal: Refusal

  def span(self) -> Tuple[int, int]:
    counts = [p.demonstrations for p in self.published if p.demonstrations is not None]
    return (min(counts), max(counts))

  def describe(self) -> str:
    low, high = self.span()
    return (
      f"no count for '{self.task}'. The published real-robot per-task counts located here span "
      f"{low} to {high} demonstrations, a factor of {high / low:.0f}, and both ends are real "
      f"results on working hardware. {self.refusal.why}"
    )


def demonstrations_needed(task: str) -> DemonstrationEstimate:
  """How many demonstrations a new task needs, which nobody can state in advance.

  Returns the published range with its tasks and methods named, the determinants, and an
  explicit refusal -- never a number. The refusal is not caution. It is the shape of the
  evidence: the counts that exist run from 20 demonstrations at 85 percent to 8,658 at 75
  percent, the one controlled study found diversity rather than count carries the gains, the
  frontier work changed the unit to hours and stopped reporting counts at all, and the single
  work in the set with an internal demonstration-count comparison found the task with twice
  the data scoring worst. A number produced from that would be a convention with a citation
  stapled to it.

  What a lab can do instead is the thing the evidence supports: collect, measure on held-out
  trials, and watch the interval. That is `success_rate`, and it is the reason it exists in
  this module rather than in a notebook.
  """
  return DemonstrationEstimate(
    task=task,
    estimate=None,
    published=PUBLISHED_COUNTS,
    determinants=DETERMINANTS,
    refusal=Refusal(
      quantity=f"demonstrations required for '{task}'",
      why=(
        "the count for a NEW task is not knowable in advance from any published result. The "
        "real-robot per-task counts span more than two orders of magnitude on comparable "
        "hardware, the widely repeated 50-demonstration figure is a data-collection budget "
        "from one paper that ran no ablation over demonstration count, and the only controlled "
        "study measured environment and object diversity -- not count -- as the thing that "
        "carries generalization. What determines it is measurable only on the task itself"
      ),
      what_it_would_take=(
        "collecting for this task on this bench and measuring success on held-out trials as "
        "the count grows, which is the demonstration-count ablation that exactly two of the "
        "works surveyed here ran on real hardware. The measurement is cheap in equipment and "
        "expensive in rollouts, and there is no way to buy it with a citation"
      ),
    ),
  )


def published_span() -> Tuple[int, int]:
  """The measured spread of published per-task counts, computed from the table.

  Computed rather than asserted so the sentence in the docstring cannot drift from the data
  under it.
  """
  counts = [p.demonstrations for p in PUBLISHED_COUNTS if p.demonstrations is not None]
  return (min(counts), max(counts))


# -- authority, in prose ------------------------------------------------------------------


INTERLOCK_NOTE = (
  "A learned policy PROPOSES a motion and a deterministic interlock DISPOSES. Workspace, "
  "speed and force are bounded by something that does not read the policy's output, has no "
  "confidence to be wrong about, and cannot be talked out of a limit by a fluent one -- which "
  "is the same separation this package draws everywhere between a thing that suggests and a "
  "thing that permits. The concept is referenced here and deliberately not imported, so "
  "nothing in this module depends on a layer that may not have landed. Two honest cautions "
  "about what such an interlock is usually built from. First, the arm-side features that get "
  "pointed at -- a reduced mode limiting Cartesian and joint speed and joint range, a "
  "Cartesian safety boundary that stops motion when the tool centre point leaves it, and "
  "collision detection on dimensionless sensitivity levels -- are vendor-documented "
  "conveniences: the common implementation compares modelled joint current against measured "
  "current, so a wrong payload mass, a wrong mounting direction or a stale friction parameter "
  "degrades it, and one manual carries no power-and-force-limiting validation and states in "
  "as many words that the emergency stop should not be used as a risk reduction measure. "
  "Second, an interlock that reads the policy's own confidence is not an interlock. It is the "
  "policy again, wearing a second name"
)


# -- what this module will not estimate ----------------------------------------------------


NOT_ESTIMATED: Tuple[Refusal, ...] = (
  Refusal(
    quantity="demonstrations required for a new task",
    why=(
      "the published real-robot per-task counts span 20 to 8,658 demonstrations on comparable "
      "hardware, the canonical 50-demonstration figure is a collection budget from a paper "
      "with no demonstration-count ablation in it, and the only controlled study of the "
      "question found environment and object diversity rather than count carrying the gains"
    ),
    what_it_would_take=(
      "the ablation on this task and this bench: collect, evaluate on held-out trials, and "
      "watch the interval rather than the point estimate"
    ),
  ),
  Refusal(
    quantity="the exchange rate between a human video and a teleoperated episode",
    why=(
      "one head-to-head comparison exists and it measured roughly 3 to 1 on a quasi-static "
      "sweeping task with pinch grasps, inside a pipeline using depth and a hand mesh. Its own "
      "authors bound it to that setting: no dexterity, no contact-rich work, and only where "
      "the robot can follow the same strategy the human did. A ratio quoted outside those "
      "bounds is a number with the caveats removed"
    ),
    what_it_would_take=(
      "the same head-to-head on this task and this arm, both arms of it collected and both "
      "evaluated on the same held-out conditions"
    ),
  ),
  Refusal(
    quantity="a success rate from fewer than the declared trial floor",
    why=(
      "the point estimate is what gets quoted and the interval is what carries the "
      "information. At 10 trials a 90 percent observation carries a 95 percent interval from "
      "55.5 to 99.7 percent, which cannot distinguish a policy that works from one that fails "
      "one attempt in three"
    ),
    what_it_would_take=(
      "more rollouts, and the arithmetic is unforgiving: narrowing a 10-point interval to 2 "
      "points takes roughly fifteen times the trials, and separating 85 percent from 90 at "
      "conventional power takes 686 per policy"
    ),
  ),
  Refusal(
    quantity="the probability that a policy succeeds on the next attempt",
    why=(
      "a rate measured on held-out trials describes the distribution those trials were drawn "
      "from. The next attempt is on this bench, at this hour, against this fixture revision, "
      "with whatever the last run left on the deck, and none of those were sampled. This is "
      "the same refusal `printed` makes about the probability that an unqualified part is fine"
    ),
    what_it_would_take=(
      "trials drawn from the conditions the run will actually face, which for a lab means the "
      "evaluation is a rehearsal of the run rather than a benchmark of the policy"
    ),
  ),
  Refusal(
    quantity="retargeting error in millimetres for a human-to-robot mapping",
    why=(
      "no verified figure was located here. The work that defines the right metrics -- "
      "fingertip position error in the global frame, relative to the wrist, relative to the "
      "thumb, and fingertip orientation error -- reports them only as unlabelled bar charts. "
      "The magnitudes that ARE published belong to the hand-pose stage upstream of "
      "retargeting, at 185.67 mm mean per-joint error for a monocular estimator and 3D errors "
      "as large as 20 to 30 cm"
    ),
    what_it_would_take=(
      "measuring the retargeted end-effector pose against a tracked ground truth on this "
      "capture rig, which is `Retargeting.error_measured_mm` and is almost never filled in"
    ),
  ),
  Refusal(
    quantity="how many demonstrations a printed fixture saves",
    why=(
      "no study located here manipulates a PHYSICAL fixture with an unfixtured control and "
      "counts human demonstrations. Every quantified source substitutes something for the "
      "fixture: a randomization range in simulation, a reset distribution at a fixed budget, "
      "or software pose canonicalization. The multipliers in circulation -- 30-fold, 38-fold "
      "-- come from those substitutes and would be an extrapolation onto a lab bench"
    ),
    what_it_would_take=(
      "the experiment nobody has run: the same task, the same arm, demonstrations collected "
      "with and without the nest, both evaluated on held-out trials to the same success target"
    ),
  ),
)


def refusals() -> Tuple[Refusal, ...]:
  """The estimates this module declines to make, with what each would require.

  Returned rather than only documented so the refusal is checkable, following `printed` and
  `durability`.
  """
  return NOT_ESTIMATED


def summary() -> Dict[str, int]:
  """Counts for the report, computed from this module's own tables.

  `published_task_rows_with_a_count` is smaller than `published_task_rows` on purpose: two of
  the rows report hours instead of demonstrations and one reports a count its own paper
  contradicts, and a summary that quietly dropped them would report a cleaner literature than
  the one that exists.
  """
  with_count = [p for p in PUBLISHED_COUNTS if p.demonstrations is not None]
  low, high = published_span()
  return {
    "modalities": len(Modality),
    "modalities_with_a_measured_action_stream": sum(
      1 for m in Modality if m.measured_action_stream
    ),
    "modalities_on_the_robots_own_kinematics": sum(
      1 for m in Modality if m.on_the_robots_own_kinematics
    ),
    "published_task_rows": len(PUBLISHED_COUNTS),
    "published_task_rows_with_a_count": len(with_count),
    "published_lowest_count": low,
    "published_highest_count": high,
    "min_heldout_trials": MIN_HELDOUT_TRIALS,
    "refusals": len(NOT_ESTIMATED),
  }


__all__ = [
  "CONFIDENCE",
  "Capture",
  "Coupling",
  "CouplingCheck",
  "DETERMINANTS",
  "DemonstrationEstimate",
  "Evaluation",
  "FixtureCoupling",
  "Interlock",
  "INTERLOCK_NOTE",
  "MAX_TRIAL_WEIGHT_PP",
  "MIN_HELDOUT_TRIALS",
  "MODALITY_EVIDENCE",
  "Missing",
  "Modality",
  "NOT_ESTIMATED",
  "PUBLISHED_COUNTS",
  "Policy",
  "PublishedCount",
  "RateReport",
  "Retargeting",
  "RunStanding",
  "SuccessCriterion",
  "Trainable",
  "Trust",
  "TrustAssessment",
  "Usability",
  "demonstrations_needed",
  "equivalent_to_teleop",
  "fixture_coupled",
  "may_run",
  "published_span",
  "refusals",
  "success_interval",
  "success_rate",
  "summary",
  "trusted_with_material",
  "usable_for_training",
]
