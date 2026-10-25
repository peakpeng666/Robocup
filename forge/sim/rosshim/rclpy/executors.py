"""rclpy.executors shim: one-shot spinning over the subscriptions of added nodes."""
from __future__ import annotations

import time


class ExternalShutdownException(Exception):
    pass


class SingleThreadedExecutor:
    def __init__(self, context=None):
        self.nodes = []
        self._shutdown = False

    def add_node(self, node) -> bool:
        self.nodes.append(node)
        return True

    def spin_once(self, timeout_sec=None):
        if self._shutdown:
            return
        subscriptions = [s for node in self.nodes for s in node.subscriptions]
        if not subscriptions:
            time.sleep(timeout_sec or 0)
            return
        deadline = time.monotonic() + (timeout_sec or 0)
        while True:
            share = 0.0 if len(subscriptions) > 1 else max(0.0, deadline - time.monotonic())
            for subscription in subscriptions:
                msg = subscription.take(share)
                if msg is not None:
                    subscription.callback(msg)
                    return
            if time.monotonic() >= deadline:
                return
            if len(subscriptions) > 1:
                time.sleep(0.001)

    def spin(self):
        while not self._shutdown:
            self.spin_once(0.1)

    def shutdown(self, timeout_sec=None) -> bool:
        self._shutdown = True
        return True
