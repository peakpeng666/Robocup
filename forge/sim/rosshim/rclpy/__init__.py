"""Minimal rclpy API surface used by booster_deploy, over ``forge_bus`` (not DDS).

Implemented: init/ok/shutdown, create_node, Node.create_publisher/create_subscription/
create_client/destroy_node, Publisher.publish/get_subscription_count, Client.wait_for_service/
call_async, spin_until_future_complete, executors.SingleThreadedExecutor.spin_once.
QoS objects are accepted and recorded; delivery is depth-1 KEEP_LAST on every topic.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import forge_bus  # noqa: E402

from .node import Node  # noqa: E402

_initialized = False


def init(args=None, context=None):
    global _initialized
    forge_bus.bus()
    _initialized = True


def ok(context=None) -> bool:
    return _initialized


def shutdown(context=None):
    global _initialized
    _initialized = False


def create_node(node_name: str, **kwargs) -> Node:
    return Node(node_name)


def spin_until_future_complete(node, future, executor=None, timeout_sec=None):
    future.wait(timeout_sec)


def spin_once(node, executor=None, timeout_sec=None):
    from .executors import SingleThreadedExecutor
    ex = SingleThreadedExecutor()
    ex.add_node(node)
    ex.spin_once(timeout_sec)
