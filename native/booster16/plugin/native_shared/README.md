# BoosterK1Native: actual shared-process policy module

This is a compiled, exercised SimRobot module, not another service/scheduler shell.
It embeds **CPython/PyTorch** and calls the existing pinned official walking backend
inside SimRobot. It is **not a fully native C++ inference implementation**, the
complete firmware1.7 skill graph, or demonstrated full-BHuman performance parity.
The original `BoosterK1Policy` subprocess module remains the default. ARM/Forge and
all existing models/gains/strategies remain unchanged.

## What changed

`../BoosterK1Policy.cpp` has an opt-in `BOOSTER_NATIVE_SHARED` compilation branch.
The existing named sensor mapping, phase clock, safety lifecycle, command schedule,
22-joint output validation, camera diagnostics and one-step actuator leases are
reused, not copied into a divergent controller. The separate library is
`libBoosterK1Native.so`; select `../scenes/OfficialK1Native.ros3`. That scene differs
from `OfficialK1.ros3` only in its controller name.

`EmbeddedPolicy.hpp` replaces QProcess with direct CPython C API calls to the
unchanged `official_policy/backend.py` class. Qt JSON **value objects** still form
the reusable adapter's value tree, converted directly to Python dict/list objects;
there is no JSON serialization, pipe, subprocess, DDS, RPC or motion service in
this computation path. Existing backend source/model hash checks remain active.
The approved official actor, history, filtering, gains and safety are unchanged.
The supplied model's hash is
`2d860167ed827e8d44cd65abd4c27f474904352bcb98c0cfa97c078f63e2fea5`.
No model bytes are added to this source change.

## BHuman mechanism used as the concrete reference

Pinned BHuman `2e3374ba896da8288607f9a1881b876642fe18b8`:

1. `LocalConsole.cpp:147-239` in `Src/Libs/SimulatedRobot` samples actual simulation
   sensors and exchanges joint data. Its console thread sends timestamped Motion
   frames at lines69-143, not a hardware-service simulation request.
2. The shared Motion execution unit runs normal modules. `MotionEngine.cpp:43`
   updates JointRequest; lines192-218 calculate the active phase's joints and
   combine them. `WalkingEngine.cpp:822,934` invokes compiled policy inference;
   `WalkPhase::calcJoints` starts at964.
3. `RobotConsole.cpp:649-653` receives `idJointRequest` in the same application's
   module/message framework. `SimulatedRobot3D.cpp:275-307` reads joint sensors,
   writes requested angles and motor gains/torque limits to actual Core3 ports.
4. Pinned SimRobot9deb6ae6 updates modules in load order; Core3 advances physics
   before the controller update. Our compile initializes the first official
   action before physics; every subsequent2ms step renews its actuator lease,
   and every20ms simulated interval computes a new official actor action.

We reuse this **simulator-hosted computation and simulated-time ownership** idea,
not BHuman's policy outputs, motion strategy or proprietary-equivalence claims.
BHuman has its own threaded execution/message scheduling; this initial adapter
executes the official actor synchronously on the simulation thread instead.

## Interpreter, memory and failure lifecycle

- One backend owns one robot's tensors/history. Calls must remain on its owning
  simulation thread; foreign-thread calls are rejected. GIL acquisition covers
  Python access; per-robot references are released on stop.
- The module initializes an isolated matching CPython runtime using the explicitly
  selected `BOOSTER_PYTHON` executable path. It rejects an already active foreign
  interpreter/runtime. On Linux it retains the already-linked libpython globally
  so PyTorch extension symbols resolve under Qt's plugin loader.
- CPython is deliberately **not finalized during plugin unload**. Its extension
  runtime lives until process exit. A new backend can restart while this module
  remains loaded; unloading/reloading the module in an already initialized host
  is not supported and must fail closed. Use a fresh SimRobot process.
- Inference errors, invalid output, stale ticks and official fall-stop propagate
  through the existing simulator stop/revoke path. No legacy PD resumes on fault.
- The execution budget is a **soft post-return overrun check**, not preemption.
  An indefinitely blocked in-process call cannot safely be killed; it also prevents
  the simulation thread from advancing physics. No hard cancellation guarantee.
- Simulation orientation still uses the explicitly disclosed body-pose oracle.
  Diagnostic camera images are real but not fed to a vision controller.

## What actually ran

Build: Debian13, GCC14.2, Qt6.8.2, CPython3.12, CPU PyTorch2.6.0, pinned SimRobot
with the existing approved hybrid-actuator/delay patches and MuJoCo3.3.5.
Official source/model and missing K1 assets were restored from public pinned
repositories and verified against their existing manifests. User-prefix build
packages were extracted without system installation or privilege changes.

- Actual module compilation and `createModule` export succeeded.
- C++ `native_core_test` executed100 real official model frames in-process, exactly
  equal to independently executed backend-reference outputs on synthetic sensor
  inputs. Stale/thread/fall/latch/restart checks passed. This test is not physics.
- Actual standing scene:1001 policy frames,10000 Core3 steps,20 simulated seconds,
  clean exit0; height0.537–0.550m, maxlean6.23°,4.16mm planar drift.
- Actual5s stand/10s forward0.5m/s/5s stop and corresponding yaw0.3rad/s episodes
  both exited0 with monotonic stamps and bounded torque telemetry. Steady means
  were0.453m/s and0.314rad/s. **Both are NOT_QUALIFIED under the existing strict
  tracking criteria**, owing to lateral/yaw oscillation checks. No criteria or
  gains were relaxed. Clean execution is not full gait acceptance.
- Core3 bounds torque at every2ms actuation; trace telemetry samples every20ms.
  Observed sampled torque/limit ratios did not exceed1.0. Do not misstate this as
  a measurement of every intermediate500Hz torque sample.
- Stock offscreen first failed with SIGSEGV before inference. The failed record is
  retained. A cloud-only Qt QPA helper then used genuine Mesa/EGL surfaceless
  OpenGL4.5, verified64×48 framebuffer readback and real544×448 camera capture.
  No physics/rendering bypass, display-server socket, ptrace or vendor service
  was used. The helper/build dependencies are not part of this source publication.

## Matched comparison, not a full-pipeline benchmark

Three paired20s forward-schedule episodes used the same2ms scene/body, actor,
CPU affinity0–8, OMP/BLAS1, llvmpipe4,1001 trace writes and one diagnostic camera
capture. Pair order was native/legacy, legacy/native, native/legacy. All six exited0;
**all paired physical traces and camera images are byte-identical**.

Startup-inclusive elapsed seconds:

| Pair | Embedded CPython | Existing QProcess |
|---|---:|---:|
|1|3.283800|3.824607|
|2|3.677594|3.526703|
|3|3.374002|3.529866|

Median3.374s versus3.530s, about4.4% lower elapsed, but one native run was slower.
This is a small variable sample, not a robust speedup promise. Startup-inclusive
RTF5.93 versus5.67 is only this **walking/physics/diagnostic-camera/trace** workload.
There is no separately measured loop-only RTF here. These numbers must not be
compared with BHuman's full normal-vision workload or interpreted as full skills
or visual-pipeline parity. The concrete milestone is actual shared-process
computation with preserved behavior, not a large proven performance improvement.

## Build and reproduce

CMake project in this directory declares the separate module and native core test;
provide the matching Python development runtime, Qt6 development packages and
`-DSIMROBOT_SOURCE=<pinned patched source>`. The cloud milestone was compiled with
explicit GCC include/link arguments; the CMake recipe is provided but was not
independently exercised in this run. Use an ABI-matched Python runtime, not an
arbitrary Python executable from another version.

For inference parity, first restore the manifest-verified official model in the
existing vendor model path, then run with the matching Python environment:

    python create_reference.py /absolute/path/official_policy/backend.py /new/reference.json
    native_core_test /absolute/venv/bin/python /absolute/path/official_policy/backend.py /new/reference.json

For an actual scene, place the module beside the patched SimRobot executable and
set existing BOOSTER_PYTHON/BOOSTER_POLICY_SCRIPT variables. Select the new native
scene explicitly. Use a genuine supported OpenGL platform. Existing
BOOSTER_MAX_POLICY_TICKS, BOOSTER_TRACE_JSONL and BOOSTER_COMMAND_SCHEDULE_JSON
retain their documented meaning. Trace/camera outputs must use new paths.

Public evidence here contains summarized measured outcomes, raw run logs and
cryptographic hashes, not model/dependency binaries, private contracts or raw
assistant records. Full raw traces remain retained in the cloud run directory.
