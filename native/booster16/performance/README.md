# SimRobot performance baseline, 2026-10-24 UTC

## Qualification

**Full official-Booster versus BHuman parity is NOT established.** The official branch currently implements walking control/physics, not the official demo vision, behavior/brain and SDK pipeline. Its control-only throughput must never be presented as a full-system speed win.

## Pristine BHuman Normal baseline

Pinned original BHuman2e3374ba and original SimRobot9deb6ae6; original vision, behavior, motion and model code unchanged. One K1, same existing full field/ball scene,2ms physics. Native color camera configuration544×448 at60Hz; actual executed work separately verified below. `st on` retained; benchmark appends `dt off` to remove only real-time wall-clock sleeping. No PNG/MP4 recording, no third-person camera, no per-step JSONL disk logging. A separate read-only observer stops after10000physics steps and writes one result.

| Repeat | Loop wall seconds | Loop RTF | Startup+teardown wall seconds | Inclusive RTF |
|---|---:|---:|---:|---:|
|1|74.974114|0.266759|76.076703|0.262893|
|2|77.079035|0.259474|78.174873|0.255837|
|3|71.170758|0.281014|72.340365|0.276471|

All three exit0 and advance20.00000095simulated seconds (float-parsed2ms ×10000). Median loopRTF0.266759; median inclusiveRTF0.262893. Exact values, sources and hashes are in results.json. This cloud CPU software-rendering baseline is slower than real time; do not generalize it to the user's machine/GPU.

## Actual workload verification and stage profile

Separate instrumented BHuman modules retain original operations and add only aggregate counters/steady-clock scopes. Original baseline binaries were not overwritten. A separate20s run confirms:

| Executed operation | Calls | Aggregate wall seconds |
|---|---:|---:|
|Physics including actuator/collision work|10000|0.656897|
|Actual camera batch render/readback, after cache check|1176|21.303698|
|Camera getImage including RGB conversion|1176|21.487788|
|RobotBallPerceptor neural inference|1168|97.204967|
|Walking neural inference|730|0.074193|
|Kicking neural inference|267|0.022030|

Actual render frequency58.8Hz over20simulated seconds, not simply an assumed60Hz. Vision inference58.4Hz. Physics500Hz. This confirms real camera rendering and neural perception execute; the scene is not a physics-only or ground-truth-perception shortcut.

These are inclusive wall intervals measured on asynchronous threads. Rendering is included in getImage, and vision overlaps rendering/physics; DO NOT add all rows or convert them into additive percentages. The profile loop took108.826540s, materially slower than the pristine~75s runs. The cause of this discrepancy is not established; profile RTF must not replace baseline throughput. Counts and coarse attribution indicate CPU neural vision, rather than physics or motion inference, is the dominant measured workload. Not every vision module or inter-thread transport path was instrumented.

## Current official walking branch: limited-layer measurement

Uses the same pinned K1 model and field/ball geometry,2ms physics, same cloud/QPA and CPU resource budget, but zero velocity command and no executed camera/vision/brain. BHuman plays soccer while this branch stands, so even contact/behavior work differs. It is not a matched functional full-stack comparison.

Three pristine current-build loopRTFs:16.099887,17.026120,16.713690; median16.713690. Inclusive medians5.864047; startup~1.7–2.4s matters for short runs. All exit0. These figures describe only the implemented control layer.

Separate control-stage profile:
-10000physics steps:0.320968s.
-1001TorchScript forward calls:0.108035s.
-Official observation+forward+postprocessing:0.275899s.
-Backend step including validation/mapping/policy:0.519917s.
-JSON pipe step roundtrip:0.741435s.
-Whole adapter inference:0.802092s.
-22actuator submissions×10001:0.004583s.
-Reset/model-startup pipe roundtrip:0.974635s, outside steady loop.

These values are nested, not additive. Roundtrip minus backend step includes transport, scheduling and JSON work outside the timed backend method; it is NOT an exclusive IPC measurement. There is no executed official vision stage to time. Rendering was not disabled in an existing official vision pipeline; that pipeline is absent. No claim of camera/vision parity is permitted.

## Logging and endpoint details

No per-frame image/video or per-tick trace was written in any throughput run. Final observer JSON is written after the loop endpoint and is included only in process-inclusive timing. Existing official-plugin periodic stderr progress messages remain; their exclusive cost was not isolated, so it is not reported as zero. Stage profiling writes aggregate diagnostics only.

Loop timing starts in observer.link after controller setup and ends after final physics step in observer.update, before downstream controller's final update in that same dispatch. Queued close then permits that final update. Therefore profiler counts can include initial/final policy calls beyond the loop boundary; process-inclusive timing covers the entire process. This small endpoint difference is disclosed rather than silently presenting exact whole-dispatch timing.

## Resources, fairness and reproducibility

Cloud reports AMD EPYC9V74; process CPU affinity0–8 (nine logical CPUs). Every run sets Mesa LP_NUM_THREADS4, OMP_NUM_THREADS1, OPENBLAS_NUM_THREADS1, MKL_NUM_THREADS1. Same allowed CPU budget does NOT mean identical internal thread architecture: BHuman peaks38–39parent threads; official parent14, with a separate Python child. Profiling reports PyTorch intra-op1/inter-op9. Parent thread sampling is at100ms and may miss brief peaks. Full process CPU includes reaped children; loop CPU is parent-only. No other heavy agent jobs ran during measurement windows.

Compiler difference is recorded, not hidden: BHuman is Clang19 Release-O3; current official plugin was built by GCC without an optimization build type, while Core3 is Release. This further prevents treating raw totals as a controlled full-stack ratio. A future same-workload Release build control is appropriate, but no speed gain has been assumed.

Original binaries, physics/vision settings, model assets and user computer were not modified. Instrumented objects/modules are isolated under profile/ and official-profile/. No debugger/ptrace, display sockets, device permission changes or Codex tasks were used.

## Next acceptance gate

1.Integrate the actual official demo camera/vision/brain/SDK path; keep declared orientation/oracle limitations visible.
2.Freeze identical field/robot/ball/task inputs, camera resolution and *executed* frame/inference cadence, physics2ms and contact configuration, compiler optimization policy and CPU/GPU resource budget.
3.Repeat≥3fixed-duration runs per implementation, include startup and steady-stateRTF plus correctness/tracking and actual workload counts. Separate camera encoding/storage from mandatory vision work.
4.Only then assess “at least BHuman speed.” No resolution reduction, timestep increase, dropped vision/inference, or altered physics may count as a speed optimization without explicit new scope.

Current evidence supports a measured BHuman baseline and isolated control-stage cost profile. The user's full functional speed acceptance remains open.

## Artifact layout

Evidence copies contain all eight run logs/results, actual counters, original input SHA-256 values and instrumentation patches. tools/ are snapshots of the cloud-workspace-specific commands and source helpers, not portable laptop deployment scripts. They deliberately retain verified absolute build/source paths. The complete working build helpers remain at /workspace/shared/benchmark-build; no binaries or upstream model assets were copied into this report folder. No commit/push/upload was performed by this worker.
