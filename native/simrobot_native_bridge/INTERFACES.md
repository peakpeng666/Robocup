# Interface contract: B-Human/SimRobot ⇄ native 1.7 core

Two columns: **B-Human side** (verified against the local sources listed
below) and **native core side** (to be filled from the verified evidence
package — items marked **TODO-PKG** name the package file that decides them;
they must not be assumed).

Local baselines: B-Human `2e3374` (runnable copy
`bhuman/local-k1-validation-20261019/bhuman-local`, which adds audit hooks:
`BH_AUDIT*`, `BH_PROFILE`, `BH_SIM_SCHEDULE`, `BH_SIM_CAPTURE*`, `BH_SIM_VIEW`,
ONNX Runtime rpath, SimRobot speed patches), SimRobot `9deb6ae6`.

## 1. Clock and stepping

| Aspect | B-Human side (verified) | Native core side |
|---|---|---|
| Physics step | 0.002 s — `stepLength="0.002"` in `Config/Scenes/K1/*.ros3` (e.g. `BHumanLocalMatch.ros3:7`) | **TODO-PKG**: policy/inference period (expected ≈20 ms = 10 physics steps, i.e. 50 Hz) — confirm in `official_motion_static/independent_nested_cpp/NestedPolicyMath.hpp` + `lifecycle/SustainedLifecycleTrial.cpp` |
| Motion frame | `motionCycleTime = 0.002f` (`Src/Libs/MathBase/Constants.h:28`); in simulation RoboCupCtrl creates Settings with the physics step, so the Motion thread runs one frame per physics step (500 Hz) | Core steps strictly once per 2 ms physics tick, in the physics-IO layer; inference at its own boundary per package |
| Sim time advance | `Time::addSimulatedTime(2ms)` after `gameController.update()` + per-robot `ControllerRobot::update()` (`Src/Libs/SimulatedRobot/RoboCupCtrl.cpp::update`) | Tick numbering: detect repeats, skips, and reset generations; state keyed by physics tick |
| Wall-clock throttling | optional `delayTime` in RoboCupCtrl (console `dt` cmd; official launcher `--unthrottled` disables) | Bridge runs unthrottled (sim-time driven); measure first, optimize later |
| Async boundary | Motion frames reach the robot thread via the debug queue; `JointRequest` returns asynchronously (`RobotConsole.cpp handleMessage` idJointRequest ~L649) and takes effect the **next** physics step — upper-layer commands are not hard-locked to the physics step | **TODO-PKG**: how the core treats command staleness (`nativeMotionState`-equivalent handshake) — `state_machine/NativeLifecycle.hpp` |

## 2. Per-robot data flow (B-Human side, verified)

`LocalConsole::update()` (`Src/Libs/SimulatedRobot/LocalConsole.cpp`) per
physics step: `getOdometryData` → `getSensorData(InertialSensorData)` →
`getAndSetJointData(jointRequest, jointSensorData, motorParameters)` →
`getTorsoMatrix`; cameras render at their configured frame rate. The Motion
frame content sent to the robot thread is JointSensorData,
InertialSensorData, GroundTruthOdometryData, TorsoMatrix.

## 3. Actuators

**B-Human legacy path (verified)**: `SimulatedRobot3D::getAndSetJointData`
(`Src/Libs/SimulatedRobot/SimulatedRobot3D.cpp` ~L275–306) reads joint
angle/velocity/torque sensors, then writes
`ActuatorPort::setValue(target + jointCalibration.offsets[i])` and
`setMotorParameters(stiffness·p, stiffness·d, maxTorque)` per joint; final PD
(with delay ring + velocity low-pass) lives in `Util/SimRobot/.../ServoMotor`.

**Bridge path (patched, verified compile pending build)**: SimRobot gets
`HybridActuatorPort` (patch `patches/simrobot-9deb6ae6-hybrid-actuator.patch`,
delay-ring fix applied first):

- Modes `disabled | torque | hybrid`; SI units (hinge: rad, rad/s, N·m).
- A successful `setHybridCommand` is a **one-physics-step lease**: the adapter
  must refresh all 22 leases every 2 ms step; a rejected/missing command
  yields zero output — never a stale command and never a fallback to the
  legacy PD.
- PD (`kp·(q*−q) + kd·(dq*−dq) + τ_ff`, clamped by
  `min(torque_limit, compiledLimit)`) is computed **once**, inside
  `ServoMotor::act` — the adapter supplies targets/gains/limits only.
- `validHybridCommand` rejects non-finite values, negative gains and
  mode-inconsistent fields; hybrid targets must lie within the mechanical
  range unless the caller explicitly selects `finiteReference` policy.
- Bridge failure policy: any rejection or anomaly → disable all joints and
  stop the simulation (implemented in the adapter, `src/`).

**Native core side**: **TODO-PKG** — output convention per
`official_motion_static/independent_nested_cpp/SerialMotorOutput.hpp`:
series vs parallel ankle treatment, MIT-mode field layout, per-joint
limits/clip order; map directly onto `HybridCommand` without re-deriving PD.

## 4. Joint enumeration (B-Human side, verified)

`Src/Libs/RobotParts/Joints.h` order: headYaw, headPitch, lShoulderPitch,
lShoulderRoll, lElbowPitch, lElbowYaw, rShoulderPitch, rShoulderRoll,
rElbowPitch, rElbowYaw, waistYaw (T1 only, absent on K1), lHipPitch, lHipRoll,
lHipYaw, lKneePitch, lAnklePitch, lAnkleRoll, rHipPitch … rAnkleRoll. The
official K1 22-joint order matches B-Human's minus `waistYaw` (forge mapping
table agrees with the cloud sceneNames).

**Must be verified per joint, not assumed (TODO-PKG + scene check)**: sign
conventions, zero poses, and the ankle's serial-equivalent vs parallel-motor
difference (the simulated K1 model may expose parallel ankle roll/pitch
motors that need series-equivalent conversion).

## 5. IMU / frames

**B-Human side (verified)**: `SimulatedRobot3D::getSensorData` — gyro and
accelerometer with white noise; `InertialSensorData.angle` is the B-Human
inclination vector derived from the body pose, **not** Euler angles. forge's
ARM route instead computes ZYX RPY from `Body::getPose` column matrices and
maps official-FRD → SimRobot-FLU signs (assembly-corrected).

**Native core side**: **TODO-PKG** — the 1.7 core's IMU convention (frame,
signs, units, gyro bias handling) from `skill_contracts` and the harness `fk`
directory; do not reuse the 1.6 mapping without checking.

## 6. Motion thread (B-Human side, verified)

`Config/Scenarios/Default/K1/threads.cfg`, Motion thread: `JointRequest`,
`MotionInfo`, `OdometryData`, `ArmMotionInfo`, `HeadMotionInfo` are provided
by `MotionEngine`; generators include WalkingEngine,
WalkToBallAndKickEngine, GetUpEngine, RestrictiveFallEngine, PrepareEngine,
HeadMotionEngine; `FallDownState` ← FallDownStateProvider;
`OdometryDataPreview` ← OdometryDataPreviewProvider. In simulation
`JointSensorData`/`InertialSensorData`/`FrameInfo` come from the console data
stream (provider `BoosterProvider` in the scenario config).

**Bridge plan**: on explicitly selected robots/scenarios only,
`BoosterNative17MotionProvider` replaces exactly the five MotionEngine-provided
representations. Vision, localization and behavior are unchanged.

## 7. Upper-layer request & feedback (B-Human side, verified)

Request `Src/Representations/MotionControl/MotionRequest.h`:
`motion ∈ {playDead, stand, walkAtAbsoluteSpeed, walkAtRelativeSpeed,
walkToPose, walkToBallAndKick, dribble, fallRequest, prepare}`; fields
`walkSpeed` (mm/s for absolute; ratio otherwise), `walkTarget`, `targetDirection`,
`kickType` (e.g. rlKickDynamic/rlKickStrong), `kickLength` (mm),
`alignPrecisely`, `ballEstimate`, `ballEstimateTimestamp`,
`ballTimeWhenLastSeen`.

Feedback `MotionInfo`: `executedPhase`, `isMotionStable`, `speed`,
`isWalkPhaseInWalkKick`, `lastMotionPhaseStarted`, `lastKickTimestamp`,
`lastKickType`, `getUpTryCounter`, `odometryAtLastPhaseSwitch`. `OdometryData`
is `Pose2f` in mm.

**Adapter mapping (to implement in `src/`)**: walk requests → native gait
command (approach, alignment, then trigger native kick/pass for
`walkToBallAndKick` — the forge ARM route's proportional approximation is
*not* good enough and must not be copied silently; improve and label as
adapter logic); fallen/supine → native get-up; feedback back-filled into
`MotionInfo` + odometry (choice: native odometry output vs
`OdometryDataPreview` — **TODO-PKG** depending on what the core exports).

## 8. Version isolation

- 1.7 fields/reps are named `native17Command` / `native17State` (or
  equivalent) — distinct from forge ARM's `nativeMotionCommand` /
  `nativeMotionState` (`JointRequest`/`JointSensorData` extensions of the
  fw16 route). Selection is explicit (scenario/robot config or env var);
  both routes can never be active on the same robot.
- SimRobot patches are shared (both routes need hybrid actuation), applied
  per-variant, never in bhuman-local.

## 9. Open questions to answer from the package (reading order)

1. `native_harness_restore/README.md` + `restore_sources_and_tools.py` —
   review for cloud-absolute paths and network downloads; rewrite to local
   path config, never execute as-is.
2. `lifecycle/SustainedLifecycleTrial.cpp` — tick/step/reset semantics.
3. `getup_trial/GetupRecoveryTrial.cpp` — get-up triggers and success
   criteria.
4. `official_motion_static/independent_nested_cpp/NestedPolicyMath.hpp`,
   `SerialMotorOutput.hpp` — policy I/O, output convention.
5. `independent_kick_cpp/ReconstructedKick.hpp` — kick/pass request API.
6. `state_machine/NativeLifecycle.hpp` (+ get-up / motion-takeover impls) —
   state machine API.
7. `independent_getup_cpp`, `skill_contracts`, `native_harness_restore/fk` —
   get-up, contracts, forward kinematics/URDF question (the local 1.6
   `selected-payload/booster/Gait/configs/K1/robot.urdf` may only be reused
   for 1.7 fk after item-by-item comparison; training URDFs live in
   `bhuman/k1-training/src/IsaacGymRL/resources/K1/`).
8. Weight file format & provenance for the nested policy.

## 10. Source files backing the B-Human-side facts

- `bhuman-local/Src/Libs/SimulatedRobot/RoboCupCtrl.cpp` (update order)
- `bhuman-local/Src/Libs/SimulatedRobot/LocalConsole.cpp` (per-step flow)
- `bhuman-local/Src/Libs/SimulatedRobot/SimulatedRobot3D.cpp` (joint IO, IMU)
- `bhuman-local/Src/Representations/MotionControl/MotionRequest.h`,
  `MotionInfo.h`
- `bhuman-local/Src/Libs/RobotParts/Joints.h`
- `bhuman-local/Config/Scenarios/Default/K1/threads.cfg`,
  `Config/Scenes/K1/*.ros3`
- `bhuman-local/Src/Libs/MathBase/Constants.h`
- `bhuman-local/Make/CMake/CMakeLists.txt` (OUTPUT_PREFIX = variant root;
  clang default on UNIX)
