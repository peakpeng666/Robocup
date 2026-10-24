# Full-service torque bridge, additive experiment

Files bridge.py,linux_ipc.py,test_bridge.py are independently written. They do not
replace the existing policy plugin, BHuman baseline or retained ARM/Forge route.
Firmware1.7 migration and older ARM simulation remain separate configurations and
run directories. The shared codec contract does not prove cross-version runtime
compatibility.

## API

ServiceBridge(kernel,22 physical torque limits,epoch,max_age_ticks,max_age_ns,
startup_timeout_ns) requires an explicit backend. No implicit OS calls occur.

- open(monotonic_ns) exclusively creates a fresh per-run/per-epoch namespace,
  returns the exact robot name that a separately managed motion peer must use.
- send_state(22 joints,acc,rpy,omega,wall_ns,sim_tick) serializes observed state,
  writes simulator→motion memory, then posts the corresponding semaphore.
- poll(wall_ns,sim_tick) drains at most255 queued command notifications, reads the
  latest record twice, rejects unstable/count-invalid/malformed data and stores
  final torque. It is nonblocking at the API level, no sleep or indefinite wait.
- torque_for_step returns None before initial readiness; caller must keep physics
  paused. It returns22 bounded torques after readiness. Startup/lease/fault raises
  BridgeFault; caller MUST disable actuators and pause, not continue previous ctrl.
- close(peer_stopped=True) tears down retained owned handles only. False is refused.
- restart requires confirmed old-peer exit and increasing epoch; old namespace is
  destroyed, a fresh name is created, cached command/counters are cleared.

ReceivedCommand includes local epoch, peer command count, local receipt wall time,
receipt sim tick and sensor count when observed. causal_sensor_count is ALWAYS
None because the official wire does not echo a request. strict_lockstep=True is
rejected. A local sensor count must never be reported as a service acknowledgment.

## Control semantics and limits

Output is TarJointTorque only. Target q/dq and wire gains are parsed but never added
as PD. Existing verified service simulation graph performs PD internally. Clamp
against the supplied scene/model physical bounds. All22 positions/velocities/torques
must be finite; truncated/extra joints, invalid validity bits and motor-error fields
fault the bridge. Mode numbers are not reinterpreted without a verified enum.

Sim-step and wall-time leases are BOTH enforced. Reuse within lease is explicitly
counted, not called a new inference. Duplicate/regressing command counters fault;
forward jumps and drained notifications are logged. Bounded draining addresses a
latest-value slot, not a queue of complete state snapshots. Two identical reads
only detect some torn writes; they are NOT proof of atomicity or causal pairing.

## Ownership and permission boundary

LinuxIpc uses standard-library ctypes with exclusive SystemV shmget and POSIX
sem_open,0600 permissions, recorded IDs and resource handles. It has NO attach-
existing mode, chmod, ipcrm, sudo, global process kill or external command launch.
Collision or permission denial is an error, not a reason to delete another object.
Partial construction cleans only successful creates. Cleanup errors retain handles
for investigation/retry; peer process lifetime is managed separately.

This backend must run only in a separately approved, verified private isolation
scope. The earlier private-namespace probe was denied by the environment; this
code is NOT authorization to bypass that denial using raw host IPC. Import is
inert; no LinuxIpc instance or actual IPC object was created in the fake-peer test.
Actual peer launch, middleware sockets and proprietary binaries are outside this
module. Prior environment results remain previous-execution evidence until the
original artifacts are recovered.

## Tests and actual limits

The fake peer is an in-memory kernel with byte buffers and integer semaphore
counters. It uses real codec bytes, not a fake success response from a motion
controller. Cases cover directions, counters, torque-only clamp, no causal claim,
startup timeout, both leases, stale reuse measurement, duplicate and dropped counts,
bounded drain, unstable reads, collisions, partial cleanup, required peer-exit,
new-epoch restart and two-robot isolation.

These tests do not exercise syscalls, memory ordering, multiprocess races, service
startup, native library loading, SDK commands, gait, kick/getup, camera/referee or
SimRobot physics. Real-service handshake must be a separate bounded run after
isolation and ELF/license/model/config audits permit it. Do not claim simulation
speed parity from in-memory unit-test throughput.
