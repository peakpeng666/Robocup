"""Fixed SimRobot test cases using the existing public console protocol."""
from __future__ import annotations

import math

MOTION_ID = "motion-basic-v1"
SKILLS = ("none", "stand", "walk", "shoot", "pass", "dribble", "block", "mark", "observe", "clear", "waitShoot")
MOTION_SEGMENTS = (("forward", 1000, 5000), ("left", 5000, 8000), ("turn", 8000, 12000), ("settled_stop", 13000, 15000))


def motion_command(motion, x=0, y=0, rotation=0):
    # The official MotionRequest layout, also used by the retained validated launcher.
    return (f"set representation:MotionRequest motion = {motion}; "
            f"walkSpeed = {{ rotation = {rotation}; translation = {{ x = {x}; y = {y}; }}; }}; "
            "walkTarget = { rotation = 0deg; translation = { x = 0; y = 0; }; }; "
            "keepTargetRotation = false; obstacleAvoidance = { avoidance = { x = 0; y = 0; }; path = []; }; "
            "targetOfInterest = []; sideWalkingRequest = allowed; shouldInterceptBall = false; "
            "shouldWalkOutOfBallLine = false; targetDirection = 0deg; kickType = rlKickDynamic; "
            "kickLength = 0; alignPrecisely = normal; odometryData = { rotation = 0; translation = { x = 0; y = 0; }; }; "
            "ballEstimate = { position = { x = 4000; y = 0; }; velocity = { x = 0; y = 0; }; radius = 50; "
            "covariance = { cols = [ { elems = [ 1, 0 ]; }, { elems = [ 0, 1 ]; } ]; }; }; "
            "ballEstimateTimestamp = 0; ballTimeWhenLastSeen = 0;")


def motion_plan():
    return [(0, "robot robot5"), (0, motion_command("stand")),
            (1000, motion_command("walkAtRelativeSpeed", x=0.35)),
            (5000, motion_command("walkAtRelativeSpeed", y=0.3)),
            (8000, motion_command("walkAtRelativeSpeed", rotation=0.25)), (12000, motion_command("stand"))]


def motion_metrics(trajectory: list) -> dict:
    out = {}
    for label, start, end in MOTION_SEGMENTS:
        part = [p for p in trajectory if start <= p[0] <= end]
        forward = left = yaw = 0.0
        for a, b in zip(part, part[1:]):
            dx, dy = (b[1] - a[1]) / 1000, (b[2] - a[2]) / 1000
            forward += math.cos(a[3]) * dx + math.sin(a[3]) * dy
            left += -math.sin(a[3]) * dx + math.cos(a[3]) * dy
            yaw += math.remainder(b[3] - a[3], 2 * math.pi)
        elapsed = (part[-1][0] - part[0][0]) * 0.002 if len(part) > 1 else 0
        out[label] = {"samples": len(part), "forward_m": forward, "left_m": left, "yaw_change_rad": yaw,
                      "mean_vx_m_s": forward / elapsed if elapsed else None,
                      "mean_vy_m_s": left / elapsed if elapsed else None,
                      "mean_wz_rad_s": yaw / elapsed if elapsed else None,
                      "net_displacement_m": math.hypot(part[-1][1] - part[0][1], part[-1][2] - part[0][2]) / 1000 if elapsed else None}
    return out


def motion_checks(result: dict, commands: list[dict]) -> dict:
    robot = result["robots"]["robot5"]
    segments = motion_metrics(robot["trajectory"])
    result["motion_segments"] = segments
    dispatched = {(int(row["tick"]), row.get("text")) for row in commands}
    return {"all_motion_commands_dispatched": all((t, c) in dispatched for t, c in motion_plan()),
            "no_fall_or_getup": robot["fall_frames"] == robot["getup_frames"] == 0,
            "forward_response_over_1m": segments["forward"]["forward_m"] > 1.0,
            "side_response_over_30cm": segments["left"]["left_m"] > 0.3,
            "turn_response_over_03rad": segments["turn"]["yaw_change_rad"] > 0.3,
            "settled_stop_under_10cm": segments["settled_stop"]["net_displacement_m"] is not None
                                       and segments["settled_stop"]["net_displacement_m"] < 0.1}
