"""rclpy.qos shim: profiles are recorded, delivery is depth-1 KEEP_LAST on every topic."""
from __future__ import annotations

import enum


class ReliabilityPolicy(enum.IntEnum):
    SYSTEM_DEFAULT = 0
    RELIABLE = 1
    BEST_EFFORT = 2


class HistoryPolicy(enum.IntEnum):
    SYSTEM_DEFAULT = 0
    KEEP_LAST = 1
    KEEP_ALL = 2


class QoSProfile:
    def __init__(self, depth=10, reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST, **kwargs):
        self.depth, self.reliability, self.history = depth, reliability, history
        self.extra = kwargs

    def __repr__(self):
        return f"QoSProfile(depth={self.depth}, reliability={self.reliability.name}, history={self.history.name})"
