#!/usr/bin/env python3
"""
THU RoboCup Telemetry Viewer Server

Receives UDP JSON packets from robots and serves them via HTTP for the browser UI.
Also supports recording the raw UDP packet stream to a JSONL file and replaying
a previously recorded file through the same /state endpoint.

Usage:
    python3 tools/telemetry_viewer/viewer_server.py [--http-host HOST] [--http-port PORT] \
        [--udp-host HOST] [--udp-port PORT]
"""

import argparse
import bisect
import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

ROBOT_TIMEOUT_MS = 2000.0
ROBOT_STALE_DROP_MS = 15000.0
REPLAY_TICK_S = 0.05
REPLAY_SPEED_MIN = 0.1
REPLAY_SPEED_MAX = 4.0

_script_dir = os.path.dirname(os.path.abspath(__file__))
RECORDINGS_DIR = os.path.join(_script_dir, "recordings")

_state_lock = threading.Lock()
_robots: dict = {}  # key: (team_id, player_id) -> {data, recv_ms}


def _now_ms() -> float:
    return time.monotonic() * 1000.0


# ── Recording ─────────────────────────────────────────────────────────────────
_record_lock = threading.Lock()
_record_file = None
_record_filename: Optional[str] = None
_record_start_ms: Optional[float] = None
_record_count = 0


def _record_status() -> dict:
    with _record_lock:
        active = _record_file is not None
        return {
            "recording": active,
            "file": _record_filename,
            "packet_count": _record_count,
            "duration_ms": round(_now_ms() - _record_start_ms, 1) if active else 0.0,
        }


def _start_recording() -> dict:
    global _record_file, _record_filename, _record_start_ms, _record_count
    with _record_lock:
        if _record_file is not None:
            return {
                "recording": True,
                "file": _record_filename,
                "packet_count": _record_count,
                "duration_ms": round(_now_ms() - _record_start_ms, 1),
            }
        os.makedirs(RECORDINGS_DIR, exist_ok=True)
        filename = f"match_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
        path = os.path.join(RECORDINGS_DIR, filename)
        f = open(path, "w", encoding="utf-8")
        f.write(json.dumps({"header": True, "started_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
        f.flush()
        _record_file = f
        _record_filename = filename
        _record_start_ms = _now_ms()
        _record_count = 0
        return {"recording": True, "file": filename, "packet_count": 0, "duration_ms": 0.0}


def _stop_recording() -> dict:
    global _record_file, _record_filename, _record_start_ms, _record_count
    with _record_lock:
        if _record_file is None:
            return {"recording": False, "file": None, "packet_count": 0, "duration_ms": 0.0}
        summary = {
            "recording": False,
            "file": _record_filename,
            "packet_count": _record_count,
            "duration_ms": round(_now_ms() - _record_start_ms, 1),
        }
        _record_file.close()
        _record_file = None
        _record_filename = None
        _record_start_ms = None
        _record_count = 0
        return summary


def _record_packet_if_active(packet: dict, sender_ip: str) -> None:
    global _record_count
    with _record_lock:
        if _record_file is None:
            return
        line = {"t_ms": round(_now_ms() - _record_start_ms, 2), "sender_ip": sender_ip, "packet": packet}
        _record_file.write(json.dumps(line) + "\n")
        _record_file.flush()
        _record_count += 1


def _list_recordings() -> list:
    if not os.path.isdir(RECORDINGS_DIR):
        return []
    items = []
    for name in os.listdir(RECORDINGS_DIR):
        if not name.endswith(".jsonl"):
            continue
        path = os.path.join(RECORDINGS_DIR, name)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        items.append({"name": name, "size_bytes": stat.st_size, "mtime_ms": int(stat.st_mtime * 1000)})
    items.sort(key=lambda x: x["mtime_ms"], reverse=True)
    return items


# ── Replay ────────────────────────────────────────────────────────────────────
class ReplaySession:
    def __init__(self, filename: str, records: list):
        self.filename = filename
        self.state = "paused"  # "playing" | "paused"
        self.speed = 1.0
        self.position_ms = 0.0
        self.duration_ms = 0.0
        self._by_key: dict = {}  # key -> sorted list of (t_ms, packet, sender_ip)
        for rec in records:
            t_ms = float(rec.get("t_ms", 0.0))
            packet = rec.get("packet") or {}
            sender_ip = rec.get("sender_ip", "")
            key = (packet.get("team_id", 0), packet.get("player_id", 0))
            self._by_key.setdefault(key, []).append((t_ms, packet, sender_ip))
            self.duration_ms = max(self.duration_ms, t_ms)
        for entries in self._by_key.values():
            entries.sort(key=lambda e: e[0])

    def get_robots(self, position_ms: float) -> list:
        result = []
        for key, entries in self._by_key.items():
            times = [e[0] for e in entries]
            idx = bisect.bisect_right(times, position_ms) - 1
            if idx < 0:
                continue
            t_ms, packet, sender_ip = entries[idx]
            age_ms = position_ms - t_ms
            if age_ms > ROBOT_STALE_DROP_MS:
                continue
            robot = dict(packet)
            robot["_online"] = age_ms < ROBOT_TIMEOUT_MS
            robot["_latency_ms"] = round(age_ms, 1)
            robot["_sender_ip"] = sender_ip
            result.append(robot)
        result.sort(key=lambda r: (r.get("team_id", 0), r.get("player_id", 0)))
        return result


_replay_lock = threading.Lock()
_replay_session: Optional[ReplaySession] = None
_view_mode = "live"  # "live" | "replay"


def _load_replay(filename: str) -> dict:
    global _replay_session, _view_mode
    safe_name = os.path.basename(filename or "")
    path = os.path.join(RECORDINGS_DIR, safe_name)
    if not safe_name or not os.path.isfile(path):
        return {"error": f"recording not found: {safe_name}"}
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("header"):
                continue
            records.append(obj)
    session = ReplaySession(safe_name, records)
    with _replay_lock:
        _replay_session = session
        _view_mode = "replay"
    return _replay_status()


def _replay_status() -> dict:
    with _replay_lock:
        if _replay_session is None:
            return {"mode": _view_mode, "file": None, "state": "stopped",
                    "position_ms": 0.0, "duration_ms": 0.0, "speed": 1.0}
        s = _replay_session
        return {"mode": _view_mode, "file": s.filename, "state": s.state,
                "position_ms": s.position_ms, "duration_ms": s.duration_ms,
                "speed": s.speed}


def _replay_play() -> dict:
    with _replay_lock:
        if _replay_session is not None:
            if _replay_session.position_ms >= _replay_session.duration_ms:
                _replay_session.position_ms = 0.0
            _replay_session.state = "playing"
    return _replay_status()


def _replay_pause() -> dict:
    with _replay_lock:
        if _replay_session is not None:
            _replay_session.state = "paused"
    return _replay_status()


def _replay_stop() -> dict:
    global _replay_session, _view_mode
    with _replay_lock:
        _replay_session = None
        _view_mode = "live"
    return _replay_status()


def _replay_seek(t_ms) -> dict:
    with _replay_lock:
        if _replay_session is not None:
            try:
                t = float(t_ms)
            except (TypeError, ValueError):
                t = 0.0
            _replay_session.position_ms = max(0.0, min(_replay_session.duration_ms, t))
    return _replay_status()


def _replay_set_speed(speed) -> dict:
    with _replay_lock:
        if _replay_session is not None:
            try:
                sp = float(speed)
            except (TypeError, ValueError):
                sp = 1.0
            _replay_session.speed = max(REPLAY_SPEED_MIN, min(REPLAY_SPEED_MAX, sp))
    return _replay_status()


def _replay_loop() -> None:
    last_wall = time.monotonic()
    while True:
        time.sleep(REPLAY_TICK_S)
        now_wall = time.monotonic()
        dt = now_wall - last_wall
        last_wall = now_wall
        with _replay_lock:
            session = _replay_session
            if session is None or session.state != "playing":
                continue
            session.position_ms += dt * 1000.0 * session.speed
            if session.position_ms >= session.duration_ms:
                session.position_ms = session.duration_ms
                session.state = "paused"


def _udp_listener(host: str, port: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    print(f"[UDP] Listening on {host}:{port}")
    while True:
        try:
            data, addr = sock.recvfrom(65535)
            packet = json.loads(data.decode("utf-8"))
            key = (packet.get("team_id", 0), packet.get("player_id", 0))
            recv_ms = _now_ms()
            with _state_lock:
                _robots[key] = {"data": packet, "recv_ms": recv_ms, "sender_ip": addr[0]}
            _record_packet_if_active(packet, addr[0])
        except Exception:
            pass


def _get_state() -> dict:
    with _replay_lock:
        session = _replay_session if _view_mode == "replay" else None
    if session is not None:
        return {"robots": session.get_robots(session.position_ms), "server_time_ms": _now_ms()}

    now = _now_ms()
    result = []
    with _state_lock:
        stale_keys = [k for k, v in _robots.items() if now - v["recv_ms"] > ROBOT_STALE_DROP_MS]
        for k in stale_keys:
            del _robots[k]
        for key, entry in _robots.items():
            age_ms = now - entry["recv_ms"]
            robot = dict(entry["data"])
            robot["_online"] = age_ms < ROBOT_TIMEOUT_MS
            robot["_latency_ms"] = round(age_ms, 1)
            robot["_sender_ip"] = entry["sender_ip"]
            result.append(robot)
    result.sort(key=lambda r: (r.get("team_id", 0), r.get("player_id", 0)))
    return {"robots": result, "server_time_ms": now}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress access log

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._serve_file("index.html", "text/html; charset=utf-8")
        elif path == "/state":
            self._send_json(_get_state())
        elif path == "/record/status":
            self._send_json(_record_status())
        elif path == "/replay/status":
            self._send_json(_replay_status())
        elif path == "/replay/list":
            self._send_json({"recordings": _list_recordings()})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = self.path.split("?")[0]
        routes = {
            "/record/start": lambda body: _start_recording(),
            "/record/stop": lambda body: _stop_recording(),
            "/replay/load": lambda body: _load_replay(body.get("file", "")),
            "/replay/play": lambda body: _replay_play(),
            "/replay/pause": lambda body: _replay_pause(),
            "/replay/stop": lambda body: _replay_stop(),
            "/replay/seek": lambda body: _replay_seek(body.get("t_ms", 0)),
            "/replay/speed": lambda body: _replay_set_speed(body.get("speed", 1.0)),
        }
        handler = routes.get(path)
        if handler is None:
            self.send_response(404)
            self.end_headers()
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            body = {}
        result = handler(body)
        status = 400 if isinstance(result, dict) and result.get("error") else 200
        self._send_json(result, status=status)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, filename: str, content_type: str) -> None:
        filepath = os.path.join(_script_dir, filename)
        try:
            with open(filepath, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()


def main() -> None:
    parser = argparse.ArgumentParser(description="THU RoboCup Telemetry Viewer Server")
    parser.add_argument("--http-host", default="127.0.0.1")
    parser.add_argument("--http-port", type=int, default=8090)
    parser.add_argument("--udp-host", default="0.0.0.0")
    parser.add_argument("--udp-port", type=int, default=15000)
    args = parser.parse_args()

    udp_thread = threading.Thread(target=_udp_listener, args=(args.udp_host, args.udp_port), daemon=True)
    udp_thread.start()

    replay_thread = threading.Thread(target=_replay_loop, daemon=True)
    replay_thread.start()

    server = HTTPServer((args.http_host, args.http_port), _Handler)
    print(f"[HTTP] Serving at http://{args.http_host}:{args.http_port}")
    print(f"[HTTP] Open http://{args.http_host}:{args.http_port} in your browser")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        _stop_recording()


if __name__ == "__main__":
    main()
