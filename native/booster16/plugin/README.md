# BoosterK1Policy: real SimRobot controller module (candidate)

This is a compiled C++17 `SimRobot::Module`, exported with `createModule`, using
Qt's native `QProcess` to invoke the real official CPU Python backend. There is no
QEMU and no fabricated controller. It is **not** a complete firmware 1.6 service,
not an in-process native model core, and not yet a qualified sim-to-real adapter.

## Current verified result

Actual SimRobot + patched Core3 + this native module + official Python model ran
**120 simulated seconds**,60000 physics steps and6001 policy frames with **clean
exit0**. Zero-command standing: min torso height0.43104m, max tilt6.99066deg,
net XY drift0.03309m; all trace samples finite, torque/declared-limit ratio<=1.
An actual544x448 CameraColor frame was rendered/read back and hashed. The first
5249 frames exactly match the earlier strict-reference run before its rejection;
the explicit finite-reference profile continues through13 such target references.
Evidence: `evidence/20261024T0156-standing-120s-pass/`.

This does not qualify walking speed, full soccer strategy, vision closed-loop,
real IMU realism, or firmware1.6 equivalence. Earlier graphics/target-guard/teardown
failures below are retained historical evidence, not the current standing result.

## Exclusive scene and runtime contract

The supported scene is named `OfficialK1`, with one B-Human K1 body named `K1`
directly below it. Its sole controller must be `BoosterK1Policy`, never
`SimulatedRobot`/`RoboCup`/B-Human `LocalConsole`. Do not load another motor-writing
module. The core must include our optional hybrid-actuator patch. Missing ports
or capability fail compilation rather than reverting to position PD.

Required environment variables, absolute paths:

- `BOOSTER_PYTHON`: CPU Python interpreter with torch and numpy.
- `BOOSTER_POLICY_SCRIPT`: `../official_policy/backend.py`.
- Optional `BOOSTER_TRACE_JSONL`: a **new** absolute file path for every inference
  input and accepted output. Existing files are rejected, not overwritten.

The module requires the verified profile's 0.002 s physics step and 0.02 s policy
period. `update()` performs inference every ten physics callbacks, holds all
hybrid fields in between, and refreshes all 22 actuator leases on every callback.
Simulation waits synchronously for inference; no realtime wall-clock claim is
made. Initial default velocity command is deliberately zero. There is currently
no strategy/motion-command UI. No hardware is contacted.

The backend starts once at module compilation and is reset with an epoch. A
scene reset/duplicate/skipped callback stops the session; reload the scene to
restart. Child exit, malformed/oversize JSON, stale output, invalid numbers,
wrong layouts, official safety stop and reply timeouts stop simulation, explicitly
disable acquired hybrid actuators and terminate the child. Destroying the module
stops the child without dereferencing potentially destroyed scene ports; the
one-step motor lease cannot remain active without refresh.

## Mapping and observations: explicitly provisional

`sceneNames` maps all 22 official real-robot joint names to B-Human's hinge names,
including elbow **pitch then yaw** in real order. Position and velocity sensor
values are used in SI directly. Pinned Core3's GUI labels say degrees, but
`ServoMotor::{PositionSensor,VelocitySensor}::updateValue` reads MuJoCo qpos/qvel
without degree conversion. `Gyroscope::updateValue` similarly returns raw rad/s.
The included K1 gyroscope has no rotation relative to the trunk.

Joint name and axis correspondence alone does not qualify zero offsets, initial
posture, contacts, inertia or dynamics. The map remains a candidate until scene
and perturbation tests qualify it. B-Human K1 defaults differ from the official
walking configuration. Do not call successful compilation locomotion validation.

Orientation is **explicit simulation body-pose ground truth**, not an IMU
estimator. `Body::getPose` supplies matrix columns; the module transposes that
array indexing into `QMatrix3x3`, then converts to a body-to-world wxyz quaternion.
It does not provide world translation, ball or opponent state to the policy.
This orientation oracle must be replaced with a validated sensor/estimator path
before claims about perception robustness or realistic transfer. Initial testing
of the controller transport may knowingly use this oracle.

Pinned source evidence:

- SimRobot `Src/SimRobotCore3/Simulation/Body.cpp`, `Body::getPose`.
- `Simulation/Motors/ServoMotor.cpp`, `registerObjects`, position/velocity sensors.
- `Simulation/Sensors/Gyroscope.cpp`, `registerObjects`, `updateValue`.
- B-Human commit `2e3374ba896da8288607f9a1881b876642fe18b8`,
  `Config/Scenes/Includes/K1/K1.rsi3`, all 22 hinge definitions and unrotated gyro.

## Build and transport test

```sh
cmake -S native/booster16/plugin -B /tmp/booster-plugin \
  -DSIMROBOT_SOURCE=/path/to/pinned-patched-SimRobot \
  -DCMAKE_PREFIX_PATH=/path/to/Qt6
cmake --build /tmp/booster-plugin
/tmp/booster-plugin/booster_policy_process_test /absolute/python /absolute/backend.py
```

Copy the resulting module next to the SimRobot executable when running the
exclusive scene. The process test uses the actual model backend, then temporary
transport fixtures for fragmented JSON, timeout, malformed JSON, child exit and
oversize reply. It does not fake the scene controller or count those fixtures as
locomotion. The actual Qt6 build and all eight transport checks passed in the
cloud; physical scene results are separate evidence, not implied by this test.

## Dedicated scene assets and attribution

`scenes/OfficialK1.ros3` is an authored integration scene with a flat test floor,
not an official match scene. Its robot definition and 23 mesh include files in
`scenes/vendor/bhuman/` are verbatim copies from pinned B-Human 2026; the source
manifest records every origin path and SHA256. The scene follows upstream
`Config/Scenes/Includes/K1/1vsDummies.rsi3` for TeamColor=skin and initial body
height0.537m, and otherwise preserves upstream robot joint initialization.
No physics parameter tuning or silent mesh replacement is applied.

This product includes software developed by B-Human (http://www.b-human.de).
See the retained B-Human `License.md`, including its RoboCup competition use
conditions. This license is distinct from Booster's Apache/IsaacLab licenses.

### Historical initial cloud scene attempt (superseded graphics path)

The actual dedicated scene launch, after applying the official skin macro and
initial height, exited139 before producing a policy trace in the cloud's Qt
offscreen environment. This is **FAILED**, not a successful physics validation.
The initial pre-correction attempt timed out at20s; both records are preserved
under `evidence/`. Compilation, transport tests and the 22-joint local-axis audit
still pass, but that initial attempt did not run the SimRobot inference/physics loop. Subsequent surfaceless graphics runs described below do execute the real loop.
`audit_joint_map.py /path/to/K1_22dof.xml` checks the explicit source tables against
both model definitions, without claiming a full kinematic or dynamic proof.
An independent Qt OpenGL3.3 core probe returned context_created=0,
context_valid=0, surface_valid=1, make_current=0. This establishes that the tested
cloud offscreen path cannot provide the required graphics context. It does not
constitute a crash backtrace: debugger tracing was denied by the sandbox and was
not bypassed. The later cloud-only surfaceless Qt/EGL helper provides a real graphics context; those separate results supersede this environment limitation. No camera/perception result is inferred from this initial failed probe.

### First-step lifecycle and failure cleanup correction

Policy tick0 now runs during `compile()` after Core3 has built the initial model
and before its first physics advance. All22 hybrid leases must be accepted or
compilation fails. Pinned Sensor::Port initializes its cached step to0xffffffff,
so initial step0 samples are refreshed; Core3 has already called mj_kinematics
for the body pose. The initial scene is stationary (initial gyro zero). The
controller requires scene step0 at initialization. After each completed physics
step, its integer phase tracker validates strict continuity, with policy tick1
computed after step10. Thus no first step silently uses legacy position PD.

On faults, simulation stop is attempted **before** actuator cleanup. Cleanup is
noexcept, catches each port independently (including non-standard exceptions),
and always attempts child shutdown and reporting. The exact production cleanup
and phase helpers have97 non-assert checks passing in normal and NDEBUG builds;
all8 real QProcess tests still pass. These are lifecycle/transport tests, not a
successful rerun of the OpenGL-blocked physical scene. Updated evidence is in
`evidence/20261024T014510Z/`.

### Official reference semantics correction (explicit profile only)

The original strict-target scene run reached104.96 simulated seconds, then
rejected RAnkleRoll desired position0.3469239175rad outside[-0.345,+0.345]. This
was an **adapter semantic mismatch**, not proof of an unsafe torque request:
actual q=0.3641327024, dq=0.1622705162, kp65/kd1 gave restoring torque
-1.2808415294Nm, well within15Nm. The official MuJoCo controller uses the raw PD
reference and clips torque, not desired position. Both models declare the same
ankle-roll joint range. Its complete failed trace is retained compressed under
`evidence/20261024T0149-strict-reference-failure/`.

The optional hybrid capability now has an explicit target-reference policy.
Default `withinMechanicalRange` keeps the original strict behavior. Only the
verified `official-k1-walk-7bb1462` plugin profile selects `finiteReference`.
All fields must remain finite, gains nonnegative, and effort still saturates at
the minimum configured/controller/compiled actuator bound. Model joint limits
are unchanged (MuJoCo constraints, not a new desired-position clamp). Unknown
profiles or enum values fail. Core3 and this module must be rebuilt together
because the optional command struct changed; do not mix binary versions.

New optional diagnostics:
- `BOOSTER_CAMERA_PNG`: new absolute PNG path; one real CameraColor sensor render
  is read after policy tick1 and saved with dimensions/hash JSON. It is **not**
  fed to policy and is not closed-loop soccer vision validation.
- `BOOSTER_MAX_POLICY_TICKS`:2..1000000;1001 yields20s,6001 yields120s. Stops
  simulation and backend, disables motors, then exits cleanly after the final
  validated command. Omit for interactive use.
- `BOOSTER_VELOCITY_COMMAND_JSON`: explicit SI JSON array, e.g.`[0.2,0,0]`.
  Default remains zero. Backend enforces official configured command ranges.

Trace diagnostics now include actual body world position, actual physics step,
and actual joint torque sensor readings (MuJoCo actuator_force). These diagnostic
world positions are never added to the policy observation. Standing tests with
zero velocity must not be described as commanded walking tests.

## Explicit scheduled motion validation

Default remains zero velocity. `BOOSTER_COMMAND_SCHEDULE_JSON` is an opt-in array
of objects, with exclusive integer `end_tick` and three SI `velocity` values:

```json
[{"end_tick":250,"velocity":[0,0,0]},
 {"end_tick":750,"velocity":[0.2,0,0]},
 {"end_tick":1001,"velocity":[0,0,0]}]
```

Set `BOOSTER_MAX_POLICY_TICKS=1001` and **unset**
`BOOSTER_VELOCITY_COMMAND_JSON`; the two inputs are mutually exclusive. This
protocol is5s standing,10s commanded motion,5s stopping. Segment ends must be
strictly increasing, the final end must equal the bounded episode length, and
commands must satisfy the pinned official limits: forward[-0.3,1.6]m/s,
lateral±0.3m/s, yaw±1.8rad/s. Unknown/malformed/nonfinite/out-of-range inputs fail
before inference; no silent command scaling.1021 schedule checks pass in normal
and NDEBUG builds, covering every selected tick and negative cases.

`TRACKING_CRITERIA.json` was fixed before these scheduled episodes. Measurements
use world displacement projected into midpoint heading coordinates; full body
rotated velocity is also reported. `evaluate_tracking.py` evaluates the fixed
windows and tolerances. Three labelled synthetic metric fixtures verify ideal
tracking passes, clean-exit failure fails, and stationary commanded motion fails;
these fixtures are not simulation evidence.

Actual cloud results, all20s/1001frames, clean exit0:

| Motion command | Steady primary response,10–15s | Overall predefined tracking result |
|---|---:|---|
| Forward0.2m/s |0.091612m/s| NOT_QUALIFIED: low-speed error and lateral oscillation criterion |
| Forward0.5m/s |0.453180m/s| NOT_QUALIFIED: lateral/yaw oscillation criteria; primary speed passes |
| Yaw0.3rad/s |0.314100rad/s| NOT_QUALIFIED: lateral oscillation criterion; primary yaw passes |
| Lateral0.1m/s |-0.000192m/s| NOT_QUALIFIED: lateral under-response |

Every episode passed finite data, chronology, declared torque bounds, minimum
height, maximum tilt, and final-stop checks. Final2s mean planar speed was below
0.002m/s for all episodes. The forward0.5 command phase travelled4.35063m in world
X. The yaw episode accumulated3.14190rad overall heading change.

The zero-command cross-axis thresholds use **mean absolute instantaneous torso
velocity**, so gait-cycle sway contributes even when signed mean drift is small.
For example, forward0.5 had lateral signed mean0.01034m/s but mean absolute
0.13222m/s. This strict sway gate was not relaxed after seeing results. A failure
of that gate is not by itself proof of a joint mapping bug or a universal gait
failure. Low-speed and lateral under-response are genuine observed response
limitations of this tested stack and remain unresolved.

All4004 measured sensor frames were replayed through the unchanged official
model: target positions were exactly identical (max error0), and every command
was verified in the official observation history's command slice. This rules out
missing commands, schedule drift and substituted pre/post-processing in these
runs. It does **not** prove dynamics equivalence with the separate official
MuJoCo model, general robustness or firmware1.6 equivalence. No algorithm, gains,
weights, friction or thresholds were tuned to hide the results.

All traces (gzip), schedules, logs, camera frames, hashes, replay reports and
predeclared criteria are retained at
`evidence/20261024T0204-scheduled-motion/`.
