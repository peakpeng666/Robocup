#!/usr/bin/env python3
"""Behavioral tests for telemetry viewer match recording and replay."""
import json
import pathlib
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "telemetry_viewer"))

import viewer_server  # noqa: E402


def _post(url, payload=None):
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _get(url):
    try:
        with urllib.request.urlopen(url) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


class RecordReplayTest(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="telemetry_recordings_")
        viewer_server.RECORDINGS_DIR = self._tmp_dir

        viewer_server._robots.clear()
        viewer_server._stop_recording()
        viewer_server._replay_stop()

        self.server = HTTPServer(("127.0.0.1", 0), viewer_server._Handler)
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        self.replay_thread = threading.Thread(target=self._run_replay_ticks, daemon=True)
        self._stop_ticks = threading.Event()
        self.replay_thread.start()

    def _run_replay_ticks(self):
        # Drive the replay clock manually and quickly instead of real-time sleeps.
        while not self._stop_ticks.is_set():
            with viewer_server._replay_lock:
                session = viewer_server._replay_session
                if session is not None and session.state == "playing":
                    session.position_ms += 20.0 * session.speed
                    if session.position_ms >= session.duration_ms:
                        session.position_ms = session.duration_ms
                        session.state = "paused"
            time.sleep(0.01)

    def tearDown(self):
        self._stop_ticks.set()
        viewer_server._stop_recording()
        viewer_server._replay_stop()
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def _inject_packet(self, team_id, player_id, extra=None):
        packet = {"team_id": team_id, "player_id": player_id, "decision": "chase", "cost": 1.5}
        if extra:
            packet.update(extra)
        key = (team_id, player_id)
        with viewer_server._state_lock:
            viewer_server._robots[key] = {
                "data": packet,
                "recv_ms": viewer_server._now_ms(),
                "sender_ip": "127.0.0.1",
            }
        viewer_server._record_packet_if_active(packet, "127.0.0.1")

    def test_record_start_stop_writes_jsonl_file(self):
        status, body = _post(f"{self.base_url}/record/start")
        self.assertEqual(status, 200)
        self.assertTrue(body["recording"])
        filename = body["file"]

        self._inject_packet(1, 5)
        self._inject_packet(1, 6)
        time.sleep(0.05)

        status, stop_body = _post(f"{self.base_url}/record/stop")
        self.assertEqual(status, 200)
        self.assertFalse(stop_body["recording"])
        self.assertEqual(stop_body["packet_count"], 2)

        recorded_path = pathlib.Path(self._tmp_dir) / filename
        self.assertTrue(recorded_path.is_file())
        lines = recorded_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 3)  # header + 2 packets
        header = json.loads(lines[0])
        self.assertTrue(header["header"])
        first_packet = json.loads(lines[1])
        self.assertEqual(first_packet["packet"]["player_id"], 5)

    def test_record_start_is_idempotent_while_active(self):
        _, first = _post(f"{self.base_url}/record/start")
        _, second = _post(f"{self.base_url}/record/start")
        self.assertEqual(first["file"], second["file"])
        _post(f"{self.base_url}/record/stop")

    def test_replay_list_returns_recorded_files(self):
        _post(f"{self.base_url}/record/start")
        self._inject_packet(2, 1)
        _post(f"{self.base_url}/record/stop")

        status, body = _get(f"{self.base_url}/replay/list")
        self.assertEqual(status, 200)
        names = [r["name"] for r in body["recordings"]]
        self.assertEqual(len(names), 1)

    def test_replay_load_missing_file_returns_error(self):
        status, body = _post(f"{self.base_url}/replay/load", {"file": "nope.jsonl"})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_replay_load_rejects_path_traversal(self):
        status, body = _post(f"{self.base_url}/replay/load", {"file": "../../etc/passwd"})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_replay_play_pause_seek_cycle(self):
        _post(f"{self.base_url}/record/start")
        self._inject_packet(3, 1)
        time.sleep(0.05)
        self._inject_packet(3, 1, {"decision": "dribble"})
        time.sleep(0.05)
        _, stop_body = _post(f"{self.base_url}/record/stop")
        filename = stop_body["file"]

        recorded_path = pathlib.Path(self._tmp_dir) / filename
        packet_lines = [json.loads(line) for line in recorded_path.read_text(encoding="utf-8").splitlines()[1:]]
        second_packet_t_ms = packet_lines[1]["t_ms"]

        status, load_body = _post(f"{self.base_url}/replay/load", {"file": filename})
        self.assertEqual(status, 200)
        self.assertEqual(load_body["mode"], "replay")
        self.assertEqual(load_body["state"], "paused")

        _post(f"{self.base_url}/replay/seek", {"t_ms": second_packet_t_ms})
        status, state_body = _get(f"{self.base_url}/state")
        self.assertEqual(status, 200)
        self.assertEqual(len(state_body["robots"]), 1)
        self.assertEqual(state_body["robots"][0]["decision"], "dribble")

        _post(f"{self.base_url}/replay/seek", {"t_ms": 0})
        _post(f"{self.base_url}/replay/play")
        deadline = time.monotonic() + 2.0
        status_body = None
        while time.monotonic() < deadline:
            _, status_body = _post(f"{self.base_url}/replay/pause")
            if status_body["position_ms"] > 0:
                break
            _post(f"{self.base_url}/replay/play")
            time.sleep(0.02)
        self.assertIsNotNone(status_body)
        self.assertGreater(status_body["position_ms"], 0)

        status, seek_body = _post(f"{self.base_url}/replay/seek", {"t_ms": status_body["duration_ms"]})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(seek_body["position_ms"], status_body["duration_ms"], delta=1.0)

        status, state_body = _get(f"{self.base_url}/state")
        self.assertEqual(state_body["robots"][0]["decision"], "dribble")

        status, stop_body = _post(f"{self.base_url}/replay/stop")
        self.assertEqual(stop_body["mode"], "live")

    def test_replay_speed_is_clamped(self):
        _post(f"{self.base_url}/record/start")
        self._inject_packet(4, 1)
        _, stop_body = _post(f"{self.base_url}/record/stop")
        _post(f"{self.base_url}/replay/load", {"file": stop_body["file"]})

        _, body = _post(f"{self.base_url}/replay/speed", {"speed": 999})
        self.assertLessEqual(body["speed"], viewer_server.REPLAY_SPEED_MAX)

        _, body = _post(f"{self.base_url}/replay/speed", {"speed": -5})
        self.assertGreaterEqual(body["speed"], viewer_server.REPLAY_SPEED_MIN)


if __name__ == "__main__":
    unittest.main()
