# Read-only dynamics comparison and matched official controls

These diagnostics explain what has and has not been isolated after the actual
SimRobot walking tests. No gait/model/PD tuning was applied to the deployed
plugin or recording scene. The official profile remains
`official-k1-walk-7bb1462`; firmware1.6 identity is unverified.

## Findings

1. Frozen actual sensor traces reproduce all4004 original targets exactly through
   the unchanged official policy, and commands reach observation/history exactly.
   Missing commands or substituted model processing do not explain those tests.
2. The untouched official controller plus official body also undertracks low
   forward and lateral commands under the same5s stand/10s command/5s stop
   schedule. Exact MuJoCo3.3.5 gives0.003932m/s for requested forward0.2 and
   0.00007666m/s for requested lateral0.1. Version3.17 has the same qualitative
   failures. Thus this is not solely a new SimRobot adapter fault or a library
   version mismatch. Forward0.5 moves in both official references.
3. A separately labelled initial-state-only control on official3.3.5 copied
   B-Human's observed initial root height and22 angles. Forward0.2 rose to
   0.017503m/s but remained far below command; lateral remained approximately
   0.0000778m/s. Initial state matters but does not remove the under-response.
   The alternate initial pose had a larger startup excursion; it was NOT made
   the deployed default.
4. Nominally identical hardware does not mean these two simulation descriptions
   contain identical parameters. The mass sum is19.666kg in both and all22
   effective policy torque caps match, but inertias, armature, initialization,
   selected dimensions and contact/solver settings differ. These are measured
   differences, not an established root-cause attribution.

## Parameter evidence

`compare_model_parameters.py` reads the pinned B-Human RSI, official K1 MJCF and
unchanged task configuration. `model_parameter_diff.json` contains every mapped
joint, source hashes,22 initial positions, mass/COM/inertia tensors, armatures,
joint ranges and effective torque bounds.

High-signal examples:
- Trunk body-frame Ixx:0.0961590 vs0.1237414kg*m² (official vs B-Human).
- Trunk Iyy:0.0895120 vs0.1172120kg*m².
- Head armature:0.002 vs0.01; arm joint armature:0.001 vs0.01.
- Head yaw mount z:0.2149 vs0.2479m.
- Initial root height: official0.6m versus B-Human test scene0.537m, with different
  starting arm/leg angles retained in each baseline.
- Official compiled solver: Newton/Euler,100 iterations, impratio10. Core3 source
  explicitly chooses50 iterations and does not override default impratio.
- Official observed foot contact: dim3, friction[1,1,.005,.0001,.0001],
  solref[.001,1], solimp[.9,.95,.001,.5,2]. It is incorrect to infer effective
  sliding friction solely from the ground XML's0.4 value; contact mixing matters.
- Core3 geometry source sets condim3 and friction[1,0,0] absent a Material override,
  with MuJoCo default contact softness. No contact parameters were adjusted here.

The official quaternion/diagonal inertia was transformed into the body frame
before comparison. Merely comparing diagonal entries in unlike frames would be
invalid. These source-level comparisons are not complete collision-geometry or
compiled-plant equivalence proofs.

## Full reference experiments

See `official_reference/REPORT.md`, `comparison.json`, per-case model/contact
snapshots and raw traces. Both package and actual MuJoCo shared-library versions
were checked. Version3.3.5 was installed into an isolated user-only diagnostic
folder; the shared video/backend environment was not changed. The new callback
harness was crosschecked against the older unchanged official reference runner:
all1000 xyz/tilt samples matched exactly on3.3.5.

Source/controller/model choices and initial overrides are explicit; no gains,
friction, action scales, filters, model weights or qualification thresholds were
optimized. This evidence does not distinguish a unique policy-vs-training-vs-
contact root cause, certify real-robot behavior, or establish firmware equivalence.
