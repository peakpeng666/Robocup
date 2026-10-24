# Booster 1.6 adapter contract foundation

This directory does **not** contain Booster's official controller, models, ABI,
mode machine, or a locomotion implementation. `MissingOfficialController` throws
explicitly. Passing the tests proves only this foundation, never vendor parity.

## Integration API

`controller.hpp` is dependency-free C++17. Each robot owns one
`ControllerSession`, which owns one `IController` implementation. Supply an
explicit `ClockConfig{servo_period_ns, policy_period_ns}`, a nonempty joint-layout
identifier and a joint count. No official control frequency is assumed.

Call `reset(new_epoch, origin_ns)` then `advance(sensor, command)` for tick zero
at the origin and consecutively increasing ticks. The timestamp must exactly be
`origin + tick * servo_period_ns`. Epochs strictly increase at reset. Skips,
duplicates, stale epochs, off-grid timestamps and arithmetic overflow are errors.
Policy period must be a positive integer multiple of servo period. Both periods
must fit positive signed 64-bit nanoseconds. Tick zero is policy-due.

A backend receives `StepContext.policy_due`; it is responsible for holding its
policy action between due ticks while executing its verified servo-rate logic.
The foundation does not invent vendor filters, gait phases, or observations.
The backend must reset all its FSM, filter, history, action, phase and model
state. If initialization needs measurements, consume the first validated frame
at tick zero; do not carry measurements over from an old epoch. Backend-specific
initial-state contracts may be added only after the vendor interface is verified.

All input validation occurs before invoking the backend. A backend exception or
invalid output poisons the session until explicit reset. Adapters must catch
failures and inhibit actuator commands; they must not keep sending stale effort.
The session is single-threaded, not a thread-safe callback sink. SDK callbacks
must assemble timestamp-aligned snapshots and transfer them to one owner.

## Units and conventions

The layout identifier is a caller-owned versioned joint-order/axis/zero mapping,
not a guessed Booster joint order. Angles are radians, rates radians/second,
linear velocity metres/second, torque newton-metres. IMU vectors are body-frame;
the unit quaternion is body-to-world in w,x,y,z order. Adapters must transform
actual vendor conventions explicitly. Zero/NaN quaternions are rejected, not
silently normalized. MotionCommand is an expiring velocity request only; it does
not claim to cover vendor mode switching or the whole football skill vocabulary.

## Actuation ownership

- Disabled: exactly zero effort; nonzero gains/feedforward are rejected.
- Torque: feedforward torque with zero gains, final symmetric torque clamp.
- Hybrid: `kp*(q_target-q) + kd*(dq_target-dq) + tau_ff`, final symmetric clamp.
  Damping is Hybrid with kp=0, dq_target=0, tau_ff=0 and nonnegative kd.

`evaluateTorque` belongs ONLY at a pure-torque simulation actuator. If an SDK
accepts hybrid fields, forward those fields and do not evaluate the PD law again.
The command limit is not a robot safety certification: adapter/model/hardware
limits must also be enforced, using the most restrictive bound. Joint position
and speed envelopes remain model-specific and are not fabricated here.

When the physics tick is faster than the servo tick, refresh the held actuation
at each physics step if the actuator API uses a one-step lease. Do not call the
controller again merely to renew that lease. No wall-clock catch-up or implicit
history advancement occurs in this foundation.

## Tests

From any directory run `native/booster16/tests/run_core_tests.sh` using its full
path if necessary. It compiles and runs both debug and `-O2 -DNDEBUG` with g++,
uses exceptions/non-assert checks, and removes only its own temporary binaries.
The counter backend exists only inside tests. Tests include deterministic replay,
integer decimation, epochs, reset, isolated instances, bad values, saturation,
unknown modes, duplicate/skipped timestamps, overflow and unavailable backend.

Not yet tested or supplied: official 1.6 behavior, model inference, SimRobot
physics integration, vendor SDK ABI, camera loop, robot deployment, real-time
scheduling guarantees, or full match operation. Do not connect a robot on the
basis of these tests.
