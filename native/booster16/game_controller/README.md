# BHuman 2026 referee / Booster demo compatibility seam

Status: explicit v20 serializer and official-header wire tests only. No live UDP
publisher, ROS node, GameController GUI, SDK, or SimRobot match has run here.
Existing BHuman source and the earlier hybrid patch are untouched.

## Source pins and actual findings

BHuman: https://github.com/bhuman/BHumanCodeRelease/tree/2e3374ba896da8288607f9a1881b876642fe18b8
SimRobot: https://github.com/bhuman/SimRobot/tree/9deb6ae6b2a553211612affb757490736f96bfb3
Booster demo branch `sandbox/support_2026_game_controller`:
https://github.com/BoosterRobotics/robocup_demo/tree/45b0e16889c25a6f01ec43952bcec685c303ba62
These are integration source pins, NOT a validated official SimRobot deployment bundle.
SDK/firmware selection and the official motion core are separately verified work;
GC version compatibility does not establish motion/SDK compatibility.

- BHuman `Util/GameController/include/RoboCupGameControlData.h`: RGme v20,
  158 bytes, 20 players/team, 3-byte player entries; RGrt v4, 32 bytes.
  Ports are UDP 3838 data /3939 return. State 0..4 means initial/ready/set/playing/
  finished. `stopped` is independent, setPlay 0..6, kickingTeam=255 means none.
- BHuman `Src/Libs/SimulatedRobot/LocalConsole.cpp`: update calls internal
  `gameController.getGameControllerData`; main sends idGameControllerData via
  debug message queue into Cognition. This is not a GC UDP broadcast.
- BHuman real `GameControllerDataProvider.cpp`: validates size/header/version/team,
  replies to accepted source IP on3939; actual fallen, pose(mm/rad), ball age(s),
  relative ball(mm). Do not memcpy a derived GameControllerData containing local
  timestamps/true-state metadata onto the wire.
- Booster `src/game_controller/src/game_controller_node.cpp`: accepts v19/198
  bytes and v20/158 bytes, publishes absolute `/robocup/game_controller`.
  v20 penalties become v19 semantic values but msg.version remains20. Notably
  motion-in-stop3 becomes motion-in-set2, caution11 becomes pushing9; warnings=0,
  cautions retained. Do not normalize again downstream. Raw v20 and normalized
  ROS messages are distinct contracts, despite the retained version field.
- Booster `src/game_controller/launch/launch.py` enables IP whitelist containing
  only192.168.30.170: loopback simulation must explicitly override it.
- Booster `src/brain/src/brain_communication.cpp`: return sender is in brain,
  not receiver. It sends to configured game_control_ip:3939 every500ms WALL time;
  fallen is always0 and pose/ball use constructor fallback values. This is alive
  reporting, not equivalent to BHuman return telemetry. Its team protocol on
  10000+team_id is not BHuman team messaging.
- Booster `Brain::gameControlCallback` maps teams by team ID, players by playerId-1,
  sent-off into substitute; match/team identity must be checked before any state
  mutation. Current callback updates some game state before rejecting unknown teams.
  Validate player ID bounds at launch, not merely playerId>0.

## Why not just select the old simulation branch?

`sandbox/support_sim` @7965dbe3a2f610b12b6d0fa252a3fb7a2ba5e90c still has
GC v12, RGrt v2,11 players and different secondary-state layouts. It is NOT wire
compatible with this BHuman pin. Its `src/sim_detection_bridge` converts MarkerArray
from `/booster/detections/<robot>_rgbd_camera` to detection messages with confidence1.
This is an oracle-style detection path, not proof of rendered vision or a SimRobot
motion plugin. `sim_stable` / `sandbox/support_sim_vision_model`
@0579259d5b4a6beb8c3a0ae912fec5ad41575d99 launches vision with sim:=true.
Reuse selected launch/camera/client pieces only after comparison; do not overwrite
2026 GC headers, ROS interfaces, or brain state handling with the old sim branch.

## Implemented seam and tests

`encode_v20.hpp` serializes the actual BHuman-compatible base fields into explicit
little-endian bytes, preserves all v20 penalties, handles BHuman's Color spelling
aliases, rejects invalid match/state metadata. It neither transports nor schedules.
A future publisher must call it on the same snapshot delivered to BHuman robots;
never leak internal true-state timing earlier than BHuman's permitted packet.

`test_official_headers.cpp` compiles both exact official protocol headers in
separate namespaces, with BHuman's spelling aliases. Tests 14 penalty values,
last player of second team, negative int16 clocks, message budget, packet255,
header/version, and malformed metadata. Actual run2026-10-24:62 checks pass with
C++17 -O2 -DNDEBUG -Wall -Wextra -Werror -pedantic using official headers fetched
at pins. ROS receiver normalization function itself is not executed by these tests.

Repeat using checkouts containing the pinned objects:

    ./native/booster16/game_controller/verify_headers.sh /path/BHuman /path/demo

The script extracts pinned originals into temporary files, never edits either repo.
Current test uses host little-endian decoding as the official parser does; no claim
of supporting an unmodified official parser on big-endian hosts.

## Concrete next changes and acceptance gates

1. BHuman controller-owned publisher: after `getGameControllerData` snapshot,
   serialize once per match update; deliver only to configured loopback endpoints.
   Keep internal BHuman injection unchanged. Opt-in disabled by default. No separate
   autonomous referee must simultaneously overwrite match state. Implement periodic
   publication in simulation time and explicit epoch reset; packet number wraps255→0.
2. Demo receiver: override whitelist with loopback; remap the absolute GC topic.
   One receiver per match fans out to robots; separate matches need distinct ports
   and ROS domains/remaps, not namespaces alone. Reject unrelated teams before brain
   mutation, stale epochs, invalid player IDs and timed-out data; inhibit locomotion
   on fault. Avoid repeated port3838 binds without a deliberate fanout design.
3. Return channel: configurable loopback sink collects v4 packets; wire identity
   (team,player) must be bound to robot instance. Use estimated pose/ball for fair
   tests, not oracle truth. Replace wall sleeps with sim-time scheduling when testing
   accelerated matches. Internal BHuman referee is not a UDP return consumer as-is;
   first record/validate returns rather than inventing rules triggered by them.
4. Test actual official receiver with golden v19/v20 packets, exact/short/oversized
   lengths, versions12/19/20, all penalties, both team orderings, stopped/free kicks,
   whitelist rejection, duplicate/wrapped/out-of-order packets, reset and timeout.
   Then real ROS subscriber/brain stop gates, two robots plus two isolated matches,
   pause and10x speed, and v4 identity/units. Header tests alone do not satisfy these.
5. Only after BHuman unchanged baseline passes, connect official motion/SDK and
   rendered camera path independently. Retain an explicit oracle test mode, never
   report it as the full strategy/vision acceptance run.

## Implemented optional BHuman binding (2026-10-24 follow-on)

`../patches/bhuman-2e3374-referee-frame-export.patch` now binds the real pinned
source, rather than leaving the codec unattached:

- `RoboCupCtrl::update`: after its single `gameController.update()`, before the
  loop calling every robot's update, calls `exportRefereeFrame`. No per-robot
  publisher, no reversed team copies, no duplicate socket bind.
- `GameController::exportRefereeFrame`: calls the existing public
  `getGameControllerData(visibleData)` so its delayed state/score masking is
  preserved. The internal injection and automatic-referee logic are unchanged.
- Two copied helper headers under `Src/Libs/SimulatedRobot/BoosterGameController`
  implement encoding, simulation-time throttling and file transport. The patch
  does not depend on external include paths or change CMake source lists.

Activation is explicit and disabled when BHUMAN_GC_FRAME_FILE is unset/empty.
Set that environment variable to a new or empty file path before launching patched
BHuman SimRobot. Nonempty files are rejected, preserving previous run evidence.
This is a file-frame sink, NOT a UDP publisher. It appends and flushes one184-byte
record per200ms of simulated time; the first record is at0. It never broadcasts,
changes network settings, or launches a robot/service. Separate runs need separate
files. Internal BHuman reset recreates controller state, so reusing a nonempty file
is intentionally refused rather than silently mixing reset epochs.

Time advances by the exact same integer-millisecond rounded simStepLength used by
pinned `Time::addSimulatedTime`, converted to integer nanoseconds. No wall clock,
sleep, or floating accumulation is added. Pause produces no new calls. Skipped
intervals emit only the current snapshot, not catch-up bursts. Generic publisher
supports explicit increasing epoch reset; regressions, invalid data, sink failures
and counter overflow latch failure and throw. The binding does not catch and
ignore errors. The host must treat such errors as a failed run; no claim that an
exception alone implements physical robot safety. Packet numbers remain those of
the underlying BHuman snapshot and can skip between200ms exports.

`inspect_frames.py FILE` is the implemented offline consumer. It checks frame
length/envelope, monotonic epoch/time, protocol20, team metadata and all player
penalties, then outputs decoded JSON without normalizing the v20 penalties.
It does not impersonate the ROS receiver. BGCF envelope is documented in
frame_publisher.hpp; source packet is the ordinary158-byte RGme payload.

`return_v4.hpp` now encodes/decodes the actual32-byte RGrt format with explicit LE
float32 bit conversion. It checks exact length, signature/version, known expected
team, player1..configured maximum<=20, fallen0/1, finite pose/ball and ballAge=-1
or nonnegative. Pose/ball are mm, angle rad, age seconds. Return packets do not
carry an epoch, so a future receiver must bind them to the current match/session
and authorized endpoint; this codec does not solve replay or sender authentication.
No return packets have been sent to a network or fed into referee decisions.

Verification follow-on:
-88 official-header C++ checks PASS, including enabled/disabled publisher,
  sim-time cadence/duplicate suppression, reset/regression/fault/overflow, sink
  error latching, return identity/length/version/NaN and nonempty-file rejection.
- Actual C++ file sink wrote two frames;6 Python consumer tests PASS, including
  decoded second-team last-player penalty and timestamps, truncated/duplicate/
  wrong-version/wrong-team/invalid-penalty rejection.
- Binding patch applies to pristine exact-pin source files and embedded helper
  bytes match the native originals: PASS. `verify_binding.sh` repeats this from a
  BHuman checkout containing the pinned commit. Source originals for this check
  were fetched from official GitHub at the pin, not a modified working tree.
- Full patched BHuman compilation and a real GUI match using this sink: NOT RUN.
  No UDP round-trip, official ROS receiver execution, or full-match acceptance.
