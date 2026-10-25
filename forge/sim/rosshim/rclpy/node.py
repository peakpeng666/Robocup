"""rclpy.node shim: publishers, subscriptions and service clients on ``forge_bus``."""
from __future__ import annotations

import threading

import forge_bus


class Future:
    def __init__(self):
        self._event = threading.Event()
        self._result = None
        self._exception = None

    def set_result(self, value):
        self._result = value
        self._event.set()

    def set_exception(self, exc):
        self._exception = exc
        self._event.set()

    def done(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout=None):
        self._event.wait(timeout)

    def result(self):
        if self._exception is not None:
            raise self._exception
        return self._result


class Publisher:
    def __init__(self, msg_type, topic, qos):
        self.msg_type, self.topic, self.qos = msg_type, forge_bus.normalize_topic(topic), qos

    def publish(self, msg):
        forge_bus.bus().publish(self.topic, msg)

    def get_subscription_count(self) -> int:
        return forge_bus.bus().subscription_count(self.topic)

    def destroy(self):
        pass


class Subscription:
    def __init__(self, msg_type, topic, callback, qos):
        self.msg_type, self.topic, self.callback, self.qos = msg_type, forge_bus.normalize_topic(topic), callback, qos
        self._pending = None
        self._lock = threading.Lock()
        self._socket = None
        forge_bus.bus().subscribe(self)

    def _offer(self, msg):  # in-process delivery, depth 1
        with self._lock:
            self._pending = msg

    def take(self, timeout):
        bus = forge_bus.bus()
        if bus.kind == "uds":
            return bus.receive_latest(self, timeout)
        with self._lock:
            msg, self._pending = self._pending, None
        return msg

    def destroy(self):
        forge_bus.bus().unsubscribe(self)


class Client:
    def __init__(self, srv_type, name):
        self.srv_type, self.name = srv_type, name

    def wait_for_service(self, timeout_sec=None) -> bool:
        return forge_bus.bus().service_available(self.name, timeout_sec)

    def service_is_ready(self) -> bool:
        return forge_bus.bus().service_available(self.name, 0.0)

    def call_async(self, request) -> Future:
        future = Future()
        try:
            future.set_result(forge_bus.bus().call(self.name, request))
        except Exception as exc:  # surfaced through future.result(), as in rclpy
            future.set_exception(exc)
        return future

    def call(self, request):
        return self.call_async(request).result()


class Node:
    def __init__(self, name: str):
        self.name = name
        self.subscriptions: list[Subscription] = []
        self.publishers: list[Publisher] = []

    def get_name(self) -> str:
        return self.name

    def create_publisher(self, msg_type, topic, qos, **kwargs) -> Publisher:
        publisher = Publisher(msg_type, topic, qos)
        self.publishers.append(publisher)
        return publisher

    def create_subscription(self, msg_type, topic, callback, qos, **kwargs) -> Subscription:
        subscription = Subscription(msg_type, topic, callback, qos)
        self.subscriptions.append(subscription)
        return subscription

    def create_client(self, srv_type, srv_name, **kwargs) -> Client:
        return Client(srv_type, srv_name)

    def get_logger(self):
        import logging
        return logging.getLogger(self.name)

    def destroy_node(self):
        for subscription in self.subscriptions:
            subscription.destroy()
        self.subscriptions.clear()
