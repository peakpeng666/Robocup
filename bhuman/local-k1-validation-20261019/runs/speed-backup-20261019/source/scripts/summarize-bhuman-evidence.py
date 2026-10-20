#!/usr/bin/env python3
"""Recheck completed local B-Human runs without changing their original logs/results."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

BASE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("local_bhuman", BASE / "scripts/run-bhuman-k1.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def check_run(run, mode):
    run = run.resolve()
    launch = json.loads((run / "launch.json").read_text())
    execution = json.loads((run / "execution.json").read_text())
    assert launch["mode"] == mode
    with tempfile.TemporaryDirectory(prefix="bhuman-evidence-") as temporary:
        temporary = Path(temporary)
        shutil.copy2(run / "console.log", temporary / "console.log")
        result = runner.summarize(temporary, mode, launch["seconds"] * 500, execution["exit_code"])
    video = run / ("bhuman-k1-" + mode + ".mp4")
    if video.exists():
        probe = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=width,height,nb_frames,r_frame_rate,duration", "-of", "json", str(video)
        ], text=True))["streams"][0]
        result["checks"]["encoded_video_complete"] = (
            int(probe["nb_frames"]) == launch["seconds"] * 10
            and abs(float(probe["duration"]) - launch["seconds"]) < 0.01
            and probe["r_frame_rate"] == "10/1")
        result["video"] = {"path": str(video), "sha256": runner.digest(video), **probe}
    else:
        result["checks"]["encoded_video_complete"] = False
    result["checks"]["tested_controller_unchanged"] = runner.digest(runner.SIM.parent / "libSimulatedRobot.so") == launch["controller_sha256"]
    result["checks"]["tested_simulator_unchanged"] = runner.digest(runner.SIM) == launch["simulator_sha256"]
    result["checks"]["tested_scene_unchanged"] = runner.digest(Path(launch["command"][-1])) == launch["scene_sha256"]
    records = defaultdict(list)
    for line in (run / "console.log").read_text().splitlines():
        match = re.match(r"AUDIT (\w+) (.*)", line)
        if match:
            records[match[1]].append(dict(re.findall(r"(\w+)=([^\s]+)", match[2])))
    transitions = []
    last = None
    for row in records["game"]:
        state = (row["state"], row["score_a"], row["score_b"])
        if state != last:
            transitions.append({**row, "sim_s": int(row["tick"]) / 500})
            last = state
    result["game_transitions"] = transitions
    result["last_motion"] = {f"{row['team']}:{row['player']}": row for row in records["motion"]}
    result["wall_s"] = execution["wall_s"]
    result["status"] = "PASS" if all(result["checks"].values()) else "FAIL"
    result["evaluator_sha256"] = runner.digest(BASE / "scripts/run-bhuman-k1.py")
    result["collection_script_sha256"] = runner.digest(Path(__file__))
    result["original_result_retained"] = str(run / "result.json")
    (run / "postcheck.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    shutil.copy2(BASE / "scripts/run-bhuman-k1.py", run / "postcheck-evaluator.py")
    return {"run_dir": str(run), "status": result["status"], "postcheck_sha256": runner.digest(run / "postcheck.json"),
            "console_sha256": runner.digest(run / "console.log"), "checks": result["checks"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gait", type=Path, required=True)
    parser.add_argument("--match", type=Path, required=True)
    args = parser.parse_args()
    result = {"time_utc": datetime.now(timezone.utc).isoformat(), "public_contract_sha256": runner.model_contract(),
              "gait": check_run(args.gait, "gait"), "match": check_run(args.match, "match")}
    result["status"] = "PASS" if result["gait"]["status"] == result["match"]["status"] == "PASS" else "FAIL"
    (BASE / "reviews/bhuman-deployment-acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
