# SimRobot Core3 hybrid actuation seam

Status: real upstream source patch and tested C++17 command/lease/adapter helpers.
NOT a complete controller plugin, NOT Booster's official 1.6 implementation,
NOT an executed K1 simulation. No replacement gait or synthetic policy is supplied.

## Pinned dependency and files

Upstream: https://github.com/bhuman/SimRobot/tree/9deb6ae6b2a553211612affb757490736f96bfb3
This is B-Human CodeRelease2026's pinned SimRobot. Preserve its MIT LICENSE and
source attribution. New integration helper code here implements a transport/
actuation contract, not recovered or reimplemented vendor controller code.

`../patches/simrobot-9deb6ae6-hybrid-actuator.patch` changes exactly:
- `Src/SimRobotCore3/SimRobotHybridActuator.h` (new optional capability + math + lease)
- `Src/SimRobotCore3/Simulation/Motors/ServoMotor.h`
- `Src/SimRobotCore3/Simulation/Motors/ServoMotor.cpp`

The local `SimRobotHybridActuator.h` is byte-identical to the new patched upstream
header; `verify_patch.sh` checks this to prevent contract drift. The separate
capability does not add virtual functions to existing ActuatorPort. Core3 and all
consumers must nevertheless be rebuilt together; no binary compatibility is claimed.

## Actuation behavior

Default ServoMotor stays on its existing legacy PD path. No parser change or scene
motor substitution is required. A controller explicitly cross-casts its resolved
`SimRobotCore3::ActuatorPort*` to `SimRobotCore3::HybridActuatorPort*`; null means
unsupported, not permission to use position setValue as a torque channel.

`setHybridCommand` latches hybrid mode. Supported hinge-only modes:
- disabled: zero effort; nonzero gains/feedforward rejected;
- torque: feedforward only; nonzero PD gains rejected;
- hybrid: kp*(q_target-q) + kd*(dq_target-dq) + tau_ff.

Fields use rad, rad/s and Nm. Gains and limits must be finite and nonnegative.
Nonfinite state/arithmetic is rejected into zero effort. Hybrid target positions
with positive kp outside the scene deflection limits are rejected. No vendor
serial/parallel conversion is implied; mapping must be verified separately.

Output is bounded by the minimum of command torque_limit, current maxForce and
compiled MuJoCo actuator ctrlrange. No larger limit is silently granted. Hybrid
uses raw q/qvel and does NOT inherit legacy position-target delay or velocity
low-pass. This is an explicit implementation choice, not proof of vendor equivalence.
Disabled means zero applied control, NOT true-robot safe braking/damping.

Every accepted command is valid for ONE physics step only. Invalid commands clear
any queued command, and stale commands produce zero control while remaining in
hybrid mode. They never resume legacy PD. `useLegacyControl()` is the only opt-out;
it clears old delayed targets and begins from the current measured pose. Puppet
mode cannot execute a hybrid command. This API is simulation-thread-only; no locks
are provided for SDK callback threads.

## Decimation and scheduling

Distinguish physics period, servo period and policy period. A 50Hz policy at a
2ms physics period is ONLY an example until the real vendor rate is verified.
If an action is held for ten physics steps, the adapter must resubmit the held
command on ALL TEN steps. If servo period exceeds physics period, session.advance
runs only on servo ticks, but the physics adapter still refreshes the lease every
physics step. Do not invent new core timestamps to disguise holding a prior action.
A real plugin must bound that hold by an explicit expiry and clear it on reset/fault.
The provided command_adapter applies fresh frames and is not a hold scheduler.

Normal scene loading places Core3 before its controller in MainWindow's update
list: physics advances, then controller computes the next action. Initialize the
first command after compile/link, and trace exactly which state produced which
next-step action. Never call mj_step a second time from the controller. No full
plugin scheduling code is supplied here while official core integration is missing.

`command_adapter.hpp` validates/stages complete core frames before port writes. A
rejection attempts to disable every available port and rethrows the original error.
Cleanup is noexcept and continues past individual throwing ports; a throwing or
rejecting port is NOT guaranteed disabled. The caller must stop physics on failure.
All writes must occur on the
simulation thread with no physics advancement between them. The adapter does not
compute torque itself: doing so as well as the actuator PD would double-control.

## Validate and apply

Read-only upstream check (temporary copies only):

    ./native/booster16/simrobot/verify_patch.sh /path/to/SimRobot

Actual application, only in a separate intended experiment checkout at the pin:

    git apply --check /path/to/simrobot-9deb6ae6-hybrid-actuator.patch
    git apply /path/to/simrobot-9deb6ae6-hybrid-actuator.patch

Build Core3 and the future controller against the same patched headers with the
upstream-supported Qt6/MuJoCo toolchain. Do not mix release binaries and this header.
No build/install or real-robot deployment is performed by verify_patch.sh.

## Actual verification record

On 2026-10-24, own cloud workspace:
- clean patch application against original files at exact pinned commit: PASS;
- patch header/local header byte parity: PASS;
- g++ C++17, -O2 -DNDEBUG, -Wall -Wextra -Werror -pedantic: PASS, 55 checks;
- AddressSanitizer + UBSan: PASS, 55 checks, with leak detection disabled;
- initial LeakSanitizer attempt failed because the environment uses ptrace. Leak
  checking was NOT completed; it was not counted as a passing test;
- Qt6Core development package absent: full Core3 compilation NOT RUN;
- dynamic_cast against real Core3, actual actuator ctrl writes, rendering, K1
  dynamics, plugin lifecycle, gait quality and official1.6 equivalence: NOT RUN.

Tests execute the exact lease/math header used by the patch. Port fanout tests use
an explicitly labeled test double, not a fake claim to run ServoMotor. They cover
hybrid/feedforward/damping math, clamp, finite/overflow checks, stale lease,
ten-step refresh, rejection clearing, frame stamp rejection, best-effort all-port disabling, cleanup exceptions, and
preservation of the original write error.

## Remaining blocker and upstream observation

The official1.6 backend has not yet been integrated into this seam. Discovery and
verification of the official source are separate ongoing work; this is not a claim
that no open backend exists. End-to-end execution still requires verified ABI/state
ownership, clock, mapping and policy pre/post-processing.

The pinned legacy ServoMotor loop contains `if(searchIndex > targetSize)` after
incrementing the index, whereas valid indices are `< targetSize`. This appears to
allow an out-of-bounds read in the legacy delay ring. This patch intentionally does
not silently alter the baseline legacy PD path; the issue needs a separate reviewed
fix and real regression test before legacy/re-entry runtime validation. The hybrid
path returns before that legacy loop, but this is not a claim that upstream is
otherwise free of defects.

## Explicit target-reference semantics

`TargetReferencePolicy::withinMechanicalRange` remains the default. The verified
public K1 profile may opt into `finiteReference` because upstream PD uses raw
finite desired positions, not target clipping to physical joint range. This does
not remove model joint constraints or actuator torque limits. Invalid enum values
fail. Tests include the recorded RAnkleRoll boundary/reference case and unchanged
torque saturation. Rebuild Core3 and every client using the optional command
struct together; do not mix old/new hybrid capability binaries.
