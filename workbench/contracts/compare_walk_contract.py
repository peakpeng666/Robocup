#!/usr/bin/env python3
"""Replay and check the production walking-policy I/O contract against a probe dump.

Reads $run/walk-probe.csv produced by the instrumented WalkingEngine.cpp
(workbench/contracts/walk-probe.patch, active only with BH_WALK_PROBE set) and
independently rebuilds, in pure stdlib Python:

  1. the 10x32 history ring buffer from RAW sensor records (quaternion gravity
     rotation, JointLimits clamping, init/zero fill rules) -> compare vs HIST,
  2. the 344-float network input vector from HIST+CTX -> compare vs IN,
  3. the decoded 12 joint targets + rawFrequency/frequency from the raw 13-dim
     network output -> compare vs OUT.

Writes compare-report.json and prints a summary. Exit code 0 = PASS, 3 = FAIL.
"""
import argparse
import json
import math
import os
import sys

HISTORY = 10
FRAME_DIM = 32
HIST_VALUES = 30  # dumped per ring entry: gravity 3 + gyro 3 + measuredAngles 12 + lastActions 12 (the 2 ball dummies exist only in the input encoding, not in HistoryData)
JOINTS = 12
INPUT_DIM = 344
OUTPUT_DIM = 13

# input layout segments: (name, begin, end)
SEGMENTS = [
    ("history", 0, 320),
    ("command", 320, 323),
    ("phase", 323, 325),
    ("velocity", 325, 337),
    ("rawFrequency", 337, 338),
    ("ballPlaceholder", 338, 344),
]

COVERED_FIELDS = [
    "history.gravity (orientation3D^-1 * (0,0,-1), quaternion wxyz)",
    "history.gyro (zero on init frames)",
    "history.measuredAngles (JointLimits-clamped, pre-offset)",
    "history.lastActions (zero when last action invalid)",
    "history ring order (oldest -> newest in input, index 0 = newest)",
    "resetHistoryData zero-pose and valid-sensor init branches",
    "input.command (step x/y mm -> m, rotation rad; zero when not walk)",
    "input.phase (cos/sin(2*pi*tBase); zero when not walk)",
    "input.velocity (lastMeasurement.velocity * velocityFactor)",
    "input.rawFrequency",
    "input.ballPlaceholder zeros",
    "decode.targets (clip(action, actionClipRange) + offset)",
    "decode.rawFrequency (clip(output[12], frequencyClipRange))",
    "decode.frequency (clip(rawFrequency) + frequencyBase)",
    "jointList order and offset table (META)",
]

UNCOVERED_FIELDS = [
    "kick policy branch (wasKicking path, ball/kick features, kick networks)",
    "ONNX Runtime numerics (network output is dumped, not recomputed)",
    "velocity estimator update rules (update(WalkGenerator&)); only its result is checked",
    "prepare-motion semantics beyond the type != walk zero-fill path",
    "ball position shifting/normalization (walk branch feeds constant zeros)",
    "waist joint path (useWaist=false configuration only)",
    "arm interpolation, stiffness, head joints",
    "real robot hardware (simulation only)",
]


def f32text(value):
    return "%.9g" % value


class Tracker:
    """Tracks max absolute error and first out-of-tolerance mismatch."""

    def __init__(self, abs_tol, rel_tol):
        self.abs_tol = abs_tol
        self.rel_tol = rel_tol
        self.max_abs_error = 0.0
        self.compared = 0
        self.first_mismatch = None
        self.nan_seen = False

    def close(self, expected, actual):
        return abs(expected - actual) <= max(self.abs_tol, self.rel_tol * max(abs(expected), abs(actual)))

    def check(self, expected, actual, where):
        self.compared += 1
        if math.isnan(expected) or math.isnan(actual):
            self.nan_seen = True
            if self.first_mismatch is None:
                self.first_mismatch = dict(where, expected=expected, actual=actual, nan=True)
            return False
        err = abs(expected - actual)
        self.max_abs_error = max(self.max_abs_error, err)
        if not self.close(expected, actual) and self.first_mismatch is None:
            self.first_mismatch = dict(where, expected=expected, actual=actual, abs_error=err)
            return False
        return True

    def ok(self):
        return self.first_mismatch is None and not self.nan_seen

    def report(self):
        return {
            "status": "PASS" if self.ok() else "FAIL",
            "compared": self.compared,
            "max_abs_error": self.max_abs_error,
            "first_mismatch": self.first_mismatch,
        }


def quat_inverse_transform(w, x, y, z, v):
    """Eigen Quaternionf::inverse() * v, mirroring QuaternionBase::_transformVector.

    q_inv = conjugate(q) / |q|^2, then v + wi*uv + vec_i x uv with uv = 2*(vec_i x v).
    Exact for unit quaternions; keeps Eigen's normalization behavior otherwise.
    """
    n2 = w * w + x * x + y * y + z * z
    wi, xi, yi, zi = w / n2, -x / n2, -y / n2, -z / n2
    uvx = 2.0 * (yi * v[2] - zi * v[1])
    uvy = 2.0 * (zi * v[0] - xi * v[2])
    uvz = 2.0 * (xi * v[1] - yi * v[0])
    return (
        v[0] + wi * uvx + (yi * uvz - zi * uvy),
        v[1] + wi * uvy + (zi * uvx - xi * uvz),
        v[2] + wi * uvz + (xi * uvy - yi * uvx),
    )


def clamp(value, lo, hi):
    return lo if value < lo else (hi if value > hi else value)


class Dump:
    def __init__(self):
        self.meta = {}
        self.limits = []  # per joint: (name, min, max)
        self.events = []  # (kind, fields) in file order
        self.line_count = 0

    @staticmethod
    def floats(fields):
        return [float(x) for x in fields]


def parse(path):
    dump = Dump()
    with open(path, "r", errors="replace") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            dump.line_count += 1
            parts = line.split(",")
            kind = parts[0]
            if kind == "META":
                dump.meta[parts[1]] = parts[2:]
            elif kind == "LIMITS":
                dump.limits.append((parts[2], float(parts[3]), float(parts[4])))
            elif kind in ("RESET", "RAW", "CTX", "HIST", "IN", "OUT"):
                dump.events.append((kind, parts))
            else:
                raise ValueError("unknown record kind %r at line %d" % (kind, dump.line_count))
    return dump


def meta_float(dump, key):
    return float(dump.meta[key][0])


def meta_pair(dump, key):
    return float(dump.meta[key][0]), float(dump.meta[key][1])


def field_name(index, joint_names):
    """Human-readable name of input vector element `index`."""
    if index < 320:
        slot = index // 32
        within = index % 32
        if within < 3:
            return "history[%d].gravity.%s" % (slot, "xyz"[within])
        if within < 6:
            return "history[%d].gyro.%s" % (slot, "xyz"[within - 3])
        if within < 18:
            return "history[%d].measuredAngles[%s]" % (slot, joint_names[within - 6])
        if within < 30:
            return "history[%d].lastActions[%s]" % (slot, joint_names[within - 18])
        return "history[%d].ballDummy%s" % (slot, "XY"[within - 30])
    if index < 323:
        return "command." + ("x_m", "y_m", "rotation_rad")[index - 320]
    if index < 325:
        return "phase." + ("cos", "sin")[index - 323]
    if index < 337:
        return "velocity[%s]" % joint_names[index - 325]
    if index < 338:
        return "rawFrequency"
    return "ballPlaceholder[%d]" % (index - 338)


def compare(csv_path, report_path, abs_tol, rel_tol):
    dump = parse(csv_path)
    errors = []

    joint_names = dump.meta.get("jointList", [])
    offsets = [float(x) for x in dump.meta.get("offsets", [])]
    structural = {
        "meta_complete": all(k in dump.meta for k in (
            "jointList", "offsets", "velocityFactor", "actionClipRange",
            "frequencyClipRange", "frequencyBase", "numInput", "numOutput",
            "historyCapacity", "quaternionConvention")),
        "joint_count_12": len(joint_names) == JOINTS and len(offsets) == JOINTS,
        "limits_count_12": len(dump.limits) == JOINTS,
        "numInput_344": dump.meta.get("numInput") == [str(INPUT_DIM)],
        "numOutput_13": dump.meta.get("numOutput") == [str(OUTPUT_DIM)],
        "historyCapacity_10": dump.meta.get("historyCapacity") == [str(HISTORY)],
    }
    if not all(structural.values()):
        errors.append("structural META checks failed: %s" % structural)

    velocity_factor = meta_float(dump, "velocityFactor") if "velocityFactor" in dump.meta else 0.0
    action_min, action_max = meta_pair(dump, "actionClipRange") if "actionClipRange" in dump.meta else (0.0, 0.0)
    freq_min, freq_max = meta_pair(dump, "frequencyClipRange") if "frequencyClipRange" in dump.meta else (0.0, 0.0)
    freq_base = meta_float(dump, "frequencyBase") if "frequencyBase" in dump.meta else 0.0
    limits_by_joint = {name: (lo, hi) for name, lo, hi in dump.limits}

    zero_frame = {"gravity": (0.0, 0.0, -1.0), "gyro": (0.0, 0.0, 0.0),
                  "measured": [0.0] * JOINTS, "actions": [0.0] * JOINTS}
    buffer = []
    hist_tracker = Tracker(abs_tol, rel_tol)
    seg_trackers = {name: Tracker(abs_tol, rel_tol) for name, _, _ in SEGMENTS}
    out_trackers = {name: Tracker(abs_tol, rel_tol) for name in ("targets", "rawFrequency", "frequency")}
    groups = {}  # id -> {"ctx":..., "hist": {idx: values}, "in":..., "out":...}
    group_order = []
    counts = {"RESET_zero": 0, "RESET_valid": 0, "RAW": 0, "policy_calls": 0, "walk_calls": 0, "stand_or_other_calls": 0}

    def current_group(call_id, frame):
        if call_id not in groups:
            groups[call_id] = {"frame": frame, "ctx": None, "hist": {}, "in": None, "out": None}
            group_order.append(call_id)
        return groups[call_id]

    def finish_group(call_id):
        """Run all per-frame comparisons once the IN record closes the input group."""
        group = groups[call_id]
        frame = group["frame"]
        ctx = group["ctx"]
        if ctx is None or len(group["hist"]) != HISTORY or group["in"] is None:
            errors.append("incomplete policy group id=%s (ctx=%s hist=%d in=%s)" % (
                call_id, ctx is not None, len(group["hist"]), group["in"] is not None))
            return
        counts["policy_calls"] += 1
        if ctx["is_walk"]:
            counts["walk_calls"] += 1
        else:
            counts["stand_or_other_calls"] += 1

        # 1. history reconstruction: model buffer vs dumped HIST lines
        if len(buffer) < HISTORY:
            errors.append("model history buffer holds %d < %d entries at id=%s" % (len(buffer), HISTORY, call_id))
            return
        for idx in range(HISTORY):
            model = buffer[idx]
            values = group["hist"][idx]
            dumped = {"gravity": tuple(values[0:3]), "gyro": tuple(values[3:6]),
                      "measured": values[6:18], "actions": values[18:30]}
            for category in ("gravity", "gyro"):
                for axis in range(3):
                    hist_tracker.check(model[category][axis], dumped[category][axis],
                                       {"frame": frame, "id": call_id, "ring_index": idx,
                                        "field": "%s.%s" % (category, "xyz"[axis])})
            for category in ("measured", "actions"):
                for j in range(JOINTS):
                    hist_tracker.check(model[category][j], dumped[category][j],
                                       {"frame": frame, "id": call_id, "ring_index": idx,
                                        "field": "%s[%s]" % (category, joint_names[j])})

        # 2. input encoding: rebuild the 344-float vector from HIST + CTX
        expected = []
        for slot in range(HISTORY - 1, -1, -1):  # oldest -> newest
            values = group["hist"][slot]
            for k in range(3):
                expected.append(values[k])                      # gravity
            for k in range(3):
                expected.append(values[3 + k])                  # gyro
            for j in range(JOINTS):
                expected.append(values[6 + j] - offsets[j])     # measuredAngles - offset
            for j in range(JOINTS):
                expected.append(values[18 + j] - offsets[j])    # lastActions - offset
            expected.extend((0.0, 0.0))                          # ball dummy
        if ctx["is_walk"]:
            expected.extend((ctx["step_x"] / 1000.0, ctx["step_y"] / 1000.0, ctx["rotation"]))
            expected.extend((math.cos(2.0 * math.pi * ctx["tBase"]), math.sin(2.0 * math.pi * ctx["tBase"])))
        else:
            expected.extend((0.0, 0.0, 0.0))
            expected.extend((0.0, 0.0))
        for j in range(JOINTS):
            expected.append(ctx["velocity"][j] * velocity_factor)
        expected.append(ctx["raw_frequency"])
        expected.extend((0.0,) * 6)
        if len(expected) != INPUT_DIM:
            errors.append("internal: rebuilt input has %d != %d elements" % (len(expected), INPUT_DIM))
            return
        actual = group["in"]
        if len(actual) != INPUT_DIM:
            errors.append("IN record id=%s has %d != %d values" % (call_id, len(actual), INPUT_DIM))
            return
        for name, begin, end in SEGMENTS:
            tracker = seg_trackers[name]
            for index in range(begin, end):
                tracker.check(expected[index], actual[index],
                              {"frame": frame, "id": call_id, "index": index,
                               "field": field_name(index, joint_names)})

    # ---- replay events in file order ----
    for kind, parts in dump.events:
        if kind == "RESET":
            mode = parts[3]
            if mode == "zero":
                buffer = [dict(zero_frame) for _ in range(HISTORY)]
                counts["RESET_zero"] += 1
            elif mode == "valid":
                buffer = []
                counts["RESET_valid"] += 1
            else:
                errors.append("unknown RESET mode %r" % mode)
        elif kind == "RAW":
            counts["RAW"] += 1
            frame_time, call_id, init = int(parts[1]), int(parts[2]), int(parts[3]) != 0
            qw, qx, qy, qz = (float(v) for v in parts[4:8])
            gyro = tuple(float(v) for v in parts[8:11])
            angles_valid = int(parts[11]) != 0
            raw_angles = [float(v) for v in parts[12:12 + JOINTS]]
            action_valid = int(parts[12 + JOINTS]) != 0
            raw_actions = [float(v) for v in parts[13 + JOINTS:13 + 2 * JOINTS]]
            gravity = quat_inverse_transform(qw, qx, qy, qz, (0.0, 0.0, -1.0))
            if angles_valid:
                measured = [clamp(raw_angles[j], *limits_by_joint[joint_names[j]]) for j in range(JOINTS)]
            else:
                measured = [0.0] * JOINTS
            actions = list(raw_actions) if action_valid else [0.0] * JOINTS
            buffer.insert(0, {"gravity": gravity, "gyro": (0.0, 0.0, 0.0) if init else gyro,
                              "measured": measured, "actions": actions})
            del buffer[HISTORY:]
        elif kind == "CTX":
            frame_time, call_id = int(parts[1]), int(parts[2])
            group = current_group(call_id, frame_time)
            group["ctx"] = {
                "is_walk": int(parts[3]) != 0,
                "step_x": float(parts[4]), "step_y": float(parts[5]), "rotation": float(parts[6]),
                "tBase": float(parts[7]), "raw_frequency": float(parts[8]),
                "velocity": [float(v) for v in parts[9:9 + JOINTS]],
            }
        elif kind == "HIST":
            call_id, idx = int(parts[2]), int(parts[3])
            if not (0 <= idx < HISTORY):
                errors.append("HIST ring index %d out of range" % idx)
                continue
            values = [float(v) for v in parts[4:4 + HIST_VALUES]]
            if len(values) != HIST_VALUES:
                errors.append("HIST id=%d idx=%d has %d != %d values" % (call_id, idx, len(values), HIST_VALUES))
                continue
            current_group(call_id, int(parts[1]))["hist"][idx] = values
        elif kind == "IN":
            call_id = int(parts[2])
            group = current_group(call_id, int(parts[1]))
            group["in"] = [float(v) for v in parts[3:]]
            finish_group(call_id)
        elif kind == "OUT":
            call_id = int(parts[2])
            group = current_group(call_id, int(parts[1]))
            group["out"] = [float(v) for v in parts[3:]]

    # ---- output decoding (needs META, so run after the replay loop) ----
    decoded_calls = 0
    for call_id in group_order:
        group = groups[call_id]
        values = group["out"]
        if values is None:
            continue
        if len(values) != OUTPUT_DIM + JOINTS + 2:
            errors.append("OUT record id=%d has %d != %d values" % (call_id, len(values), OUTPUT_DIM + JOINTS + 2))
            continue
        decoded_calls += 1
        raw_out, dumped_targets = values[:OUTPUT_DIM], values[OUTPUT_DIM:OUTPUT_DIM + JOINTS]
        dumped_raw_freq, dumped_freq = values[OUTPUT_DIM + JOINTS], values[OUTPUT_DIM + JOINTS + 1]
        for j in range(JOINTS):
            expected = clamp(raw_out[j], action_min, action_max) + offsets[j]
            out_trackers["targets"].check(expected, dumped_targets[j],
                                          {"frame": group["frame"], "id": call_id,
                                           "field": "target[%s]" % joint_names[j]})
        expected_raw_freq = clamp(raw_out[OUTPUT_DIM - 1], freq_min, freq_max)
        expected_freq = clamp(expected_raw_freq, freq_min, freq_max) + freq_base
        out_trackers["rawFrequency"].check(expected_raw_freq, dumped_raw_freq,
                                           {"frame": group["frame"], "id": call_id, "field": "rawFrequency"})
        out_trackers["frequency"].check(expected_freq, dumped_freq,
                                        {"frame": group["frame"], "id": call_id, "field": "frequency"})

    checks = {
        "structural": {"status": "PASS" if all(structural.values()) else "FAIL", "items": structural},
        "history_reconstruction": hist_tracker.report(),
        "input_encoding": {name: seg_trackers[name].report() for name, _, _ in SEGMENTS},
        "output_decoding": {name: out_trackers[name].report() for name in out_trackers},
    }
    if counts["policy_calls"] < 500 or counts["walk_calls"] == 0 or decoded_calls != counts["policy_calls"]:
        errors.append("insufficient/incomplete coverage: need >=500 calls, walk calls, and one OUT per input")
    verdict = "PASS" if (not errors
                         and hist_tracker.ok()
                         and all(t.ok() for t in seg_trackers.values())
                         and all(t.ok() for t in out_trackers.values())
                         and all(structural.values())) else "FAIL"
    report = {
        "verdict": verdict,
        "csv": os.path.abspath(csv_path),
        "tolerances": {"abs": abs_tol, "rel": rel_tol},
        "counts": dict(counts, decoded_calls=decoded_calls, lines=dump.line_count),
        "checks": checks,
        "errors": errors[:50],
        "covered_fields": COVERED_FIELDS,
        "uncovered_fields": UNCOVERED_FIELDS,
    }
    with open(report_path, "w") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")

    print("verdict: %s (%d policy calls, %d walk, %d stand/other; %d RESET zero/%d valid)" % (
        verdict, counts["policy_calls"], counts["walk_calls"], counts["stand_or_other_calls"],
        counts["RESET_zero"], counts["RESET_valid"]))
    print("history_reconstruction: %s max_abs_error=%.3g compared=%d" % (
        checks["history_reconstruction"]["status"], hist_tracker.max_abs_error, hist_tracker.compared))
    for name, _, _ in SEGMENTS:
        rep = checks["input_encoding"][name]
        print("input_encoding.%-16s %s max_abs_error=%.3g compared=%d%s" % (
            name, rep["status"], rep["max_abs_error"], rep["compared"],
            "" if rep["first_mismatch"] is None else " first_mismatch=%s" % rep["first_mismatch"]))
    for name in ("targets", "rawFrequency", "frequency"):
        rep = checks["output_decoding"][name]
        print("output_decoding.%-16s %s max_abs_error=%.3g compared=%d%s" % (
            name, rep["status"], rep["max_abs_error"], rep["compared"],
            "" if rep["first_mismatch"] is None else " first_mismatch=%s" % rep["first_mismatch"]))
    for error in errors[:10]:
        print("error:", error)
    print("report: %s" % report_path)
    return 0 if verdict == "PASS" else 3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", help="walk-probe.csv from a probe run")
    parser.add_argument("-o", "--output", help="compare-report.json path (default: next to the CSV)")
    parser.add_argument("--abs-tol", type=float, default=1e-5)
    parser.add_argument("--rel-tol", type=float, default=1e-4)
    args = parser.parse_args()
    report_path = args.output or os.path.join(os.path.dirname(os.path.abspath(args.csv)), "compare-report.json")
    return compare(args.csv, report_path, args.abs_tol, args.rel_tol)


if __name__ == "__main__":
    sys.exit(main())
