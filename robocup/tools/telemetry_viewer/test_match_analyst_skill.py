#!/usr/bin/env python3
"""Tests for the RoboCup telemetry analyst skill scripts."""

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "telemetry_viewer" / "analyst_skill" / "scripts" / "match_analyst.py"


def _packet(player_id, t_ms, *, role="striker", decision="", recovery="IS_READY", x=0.0, y=0.0):
    return {
        "ts": t_ms,
        "team_id": 1,
        "player_id": player_id,
        "role": role,
        "decision": decision,
        "goalie_mode": "",
        "recovery": recovery,
        "preferred_foot": "right",
        "odom_calibrated": True,
        "is_lead": decision in ("chase", "shoot", "pass"),
        "cost": 12.5,
        "game": {"state": "PLAY", "sub_state_type": "", "sub_state": "", "is_kickoff_side": True},
        "freekick": {"phase": "NONE", "wait_for_opponent_restart": False},
        "field": {
            "length": 14.0,
            "width": 9.0,
            "goal_width": 2.6,
            "goal_area_length": 1.0,
            "goal_area_width": 3.0,
            "penalty_area_length": 2.0,
            "penalty_area_width": 5.0,
            "circle_radius": 1.5,
        },
        "robot": {"x": x, "y": y, "theta": 0.0},
        "ball": {"detected": decision == "chase", "x": 1.0, "y": 0.0, "confidence": 80.0, "age_ms": 0.0},
        "team_ball": {"valid": True, "x": 1.0, "y": 0.0, "vx": 0.0, "vy": 0.0, "support_count": 1, "age_ms": 0.0},
        "motion": {
            "dribble_dir": 0.0,
            "pass_dir": 0.0,
            "dribble_speed": 0.0,
            "pass_speed": 0.0,
            "walk_command_valid": True,
            "walk_vx": 0.2 if decision else 0.0,
            "walk_vy": 0.0,
            "walk_vtheta": 0.0,
            "kick_type": "shoot",
        },
        "obstacles": [],
        "teammates": [{"player_id": 3, "x": x + 0.25, "y": y, "alive": True, "ball_detected": False}],
    }


def _write_recording(path):
    rows = [
        {"header": True, "started_at_iso": "2026-07-03T12:00:00"},
        {"t_ms": 0.0, "sender_ip": "127.0.0.1", "packet": _packet(2, 0, decision="chase", x=0.0, y=0.0)},
        {"t_ms": 1000.0, "sender_ip": "127.0.0.1", "packet": _packet(2, 1000, decision="chase", recovery="FALLING", x=0.1, y=0.0)},
        {"t_ms": 2000.0, "sender_ip": "127.0.0.1", "packet": _packet(2, 2000, decision="", recovery="IS_READY", x=0.2, y=0.0)},
        {"t_ms": 3000.0, "sender_ip": "127.0.0.1", "packet": _packet(3, 3000, decision="assist", x=0.35, y=0.0)},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


class MatchAnalystSkillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="match_analyst_skill_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_single_recording_generates_evidence_and_chinese_llm_brief(self):
        recording = self.tmp / "tiny_match.jsonl"
        out_dir = self.tmp / "analyses"
        _write_recording(recording)

        subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(recording),
                "--out-dir",
                str(out_dir),
                "--viewer-url",
                "http://viewer.local",
            ],
            check=True,
            cwd=ROOT,
        )

        evidence_path = out_dir / "tiny_match_evidence.json"
        brief_path = out_dir / "tiny_match_brief.md"
        html_path = out_dir / "tiny_match_evidence.html"
        self.assertTrue(evidence_path.is_file())
        self.assertTrue(brief_path.is_file())
        self.assertTrue(html_path.is_file())

        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        self.assertEqual(evidence["language"], "zh-CN")
        self.assertEqual(evidence["recording"]["file"], "tiny_match.jsonl")
        self.assertTrue(any(event["type"] == "fall_segment" for event in evidence["events"]))
        self.assertTrue(any(event["type"] == "close_teammate" for event in evidence["events"]))

        brief = brief_path.read_text(encoding="utf-8")
        self.assertIn("# 赛后证据简报", brief)
        self.assertIn("请用中文撰写最终赛后分析报告", brief)
        self.assertIn("http://viewer.local/?replay=tiny_match.jsonl&t=1000", brief)

        html = html_path.read_text(encoding="utf-8")
        self.assertIn('<html lang="zh-CN">', html)
        self.assertIn("关键事件", html)
        self.assertIn("http://viewer.local/?replay=tiny_match.jsonl&amp;t=1000", html)

    def test_all_mode_uses_recordings_dir_and_skips_existing_outputs_unless_forced(self):
        recordings_dir = self.tmp / "recordings"
        out_dir = self.tmp / "analyses"
        recordings_dir.mkdir()
        _write_recording(recordings_dir / "all_match.jsonl")

        subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--all",
                "--recordings-dir",
                str(recordings_dir),
                "--out-dir",
                str(out_dir),
            ],
            check=True,
            cwd=ROOT,
        )
        evidence_path = out_dir / "all_match_evidence.json"
        self.assertTrue(evidence_path.is_file())

        first = evidence_path.read_text(encoding="utf-8")
        evidence_path.write_text('{"kept": true}', encoding="utf-8")
        subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--all",
                "--recordings-dir",
                str(recordings_dir),
                "--out-dir",
                str(out_dir),
            ],
            check=True,
            cwd=ROOT,
        )
        self.assertNotEqual(first, '{"kept": true}')
        self.assertEqual(evidence_path.read_text(encoding="utf-8"), '{"kept": true}')


if __name__ == "__main__":
    unittest.main()
