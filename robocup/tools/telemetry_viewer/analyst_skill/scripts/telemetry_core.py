#!/usr/bin/env python3
"""Shared helpers for RoboCup telemetry recording analysis."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlencode


Packet = dict[str, Any]
Row = dict[str, Any]


def viewer_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def default_recordings_dir() -> Path:
    return viewer_dir() / "recordings"


def default_analyses_dir() -> Path:
    return viewer_dir() / "analyses"


def load_jsonl(path: Path) -> tuple[dict[str, Any], list[Row]]:
    header: dict[str, Any] = {}
    rows: list[Row] = []
    with path.open(encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if obj.get("header"):
                header = obj
                continue
            if isinstance(obj.get("packet"), dict) and "t_ms" in obj:
                rows.append(obj)
    rows.sort(key=lambda row: float(row.get("t_ms", 0.0)))
    return header, rows


def organise(rows: list[Row]) -> dict[int, list[Row]]:
    by_robot: dict[int, list[Row]] = defaultdict(list)
    for row in rows:
        pid = int(row.get("packet", {}).get("player_id", 0) or 0)
        if pid > 0:
            by_robot[pid].append(row)
    for rrows in by_robot.values():
        rrows.sort(key=lambda row: float(row.get("t_ms", 0.0)))
    return dict(by_robot)


def t_ms(row: Row) -> float:
    return float(row.get("t_ms", 0.0))


def t_s(row: Row) -> float:
    return t_ms(row) / 1000.0


def fmt_s(seconds: float) -> str:
    return f"{seconds:.1f}s"


def fmt_ms(ms: float) -> str:
    if abs(ms - round(ms)) < 0.01:
        return str(int(round(ms)))
    return f"{ms:.1f}"


def replay_link(viewer_url: str, recording_name: str, at_ms: float, *, play: bool = False) -> str:
    base = viewer_url.rstrip("/") or "http://127.0.0.1:8090"
    query = {"replay": recording_name, "t": fmt_ms(max(0.0, at_ms))}
    if play:
        query["play"] = "1"
    return f"{base}/?{urlencode(query)}"


def linear_speed(pkt: Packet) -> float:
    motion = pkt.get("motion") or {}
    return math.hypot(float(motion.get("walk_vx", 0.0) or 0.0), float(motion.get("walk_vy", 0.0) or 0.0))


def angular_speed(pkt: Packet) -> float:
    motion = pkt.get("motion") or {}
    return abs(float(motion.get("walk_vtheta", 0.0) or 0.0))


def is_moving(pkt: Packet, lin_threshold: float = 0.05, ang_threshold: float = 0.05) -> bool:
    motion = pkt.get("motion") or {}
    return bool(motion.get("walk_command_valid")) and (
        linear_speed(pkt) > lin_threshold or angular_speed(pkt) > ang_threshold
    )


def dist2d(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.hypot(x2 - x1, y2 - y1)


def robot_xy(pkt: Packet) -> tuple[float, float] | None:
    robot = pkt.get("robot") or {}
    try:
        return float(robot["x"]), float(robot["y"])
    except (KeyError, TypeError, ValueError):
        return None


def pct(numerator: int, denominator: int) -> float:
    return numerator / denominator * 100.0 if denominator else 0.0

