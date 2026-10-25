"""Transport behind the ROS 2 API shim used to run booster_deploy against the Virtual K1.

This is NOT DDS.  It reproduces the ROS 2 *API* that booster_deploy's real-robot controller
uses (topics ``/low_state``, ``/joint_ctrl``, ``/remote_controller_state`` and the
``booster_rpc_service`` service) so that Booster's own controller code runs unmodified.

Two buses, selected by ``FORGE_ROS_SHIM_BUS``:

* ``inproc`` (default) -- in-process hooks for deterministic lockstep runs;
* ``uds:<directory>`` -- Unix sockets to a Virtual K1 real-time server (``sim/bridge_server.py``).
  Datagram topics with depth-1 KEEP_LAST delivery; a stream socket for RPC.  The sockets work
  across ``fork`` (booster_deploy publishes from a forked inference process).

Messages travel in a fixed binary layout (``encode``/``decode``), identical on both ends.
"""
from __future__ import annotations

import itertools
import json
import os
import select
import socket
import struct
import time

MOTORS = 22
_STATE_HEAD = struct.Struct("<4sIdI")          # magic, seq, sim_time, motors
_IMU = struct.Struct("<9f")
_MOTOR_STATE = struct.Struct("<b4fbI2I")      # mode, q, dq, ddq, tau_est, temperature, lost, reserve[2]
_CMD_HEAD = struct.Struct("<4sIbI")            # magic, seq, cmd_type, motors
_MOTOR_CMD = struct.Struct("<b6f")             # mode, q, dq, tau, kp, kd, weight
_TOPIC_TAG = {"/low_state": b"S", "/joint_ctrl": b"C", "/remote_controller_state": b"R"}
_TAG_TOPIC = {v: k for k, v in _TOPIC_TAG.items()}
REMOTE_FIELDS = ("event", "lx", "ly", "rx", "ry", "a", "b", "x", "y", "lb", "rb", "lt", "rt", "ls", "rs", "back",
                 "start", "hat_c", "hat_u", "hat_d", "hat_l", "hat_r", "hat_lu", "hat_ld", "hat_ru", "hat_rd", "hat_pos")


def normalize_topic(topic: str) -> str:
    return topic if topic.startswith("/") else "/" + topic


# ------------------------------------------------------------------ codecs
def encode_low_state(msg, seq: int = 0, sim_time: float = 0.0) -> bytes:
    imu = msg.imu_state
    parts = [_STATE_HEAD.pack(b"K1LS", seq & 0xFFFFFFFF, sim_time, len(msg.motor_state_serial)),
             _IMU.pack(*imu.rpy, *imu.gyro, *imu.acc)]
    for group in (msg.motor_state_serial, msg.motor_state_parallel):
        for m in group:
            parts.append(_MOTOR_STATE.pack(int(m.mode), m.q, m.dq, m.ddq, m.tau_est, int(m.temperature), int(m.lost),
                                           *m.reserve))
    return b"".join(parts)


def decode_low_state(raw: bytes):
    from booster_interface.msg import LowState, MotorState
    magic, seq, sim_time, n = _STATE_HEAD.unpack_from(raw)
    if magic != b"K1LS":
        raise ValueError("not a LowState frame")
    msg = LowState()
    values = _IMU.unpack_from(raw, _STATE_HEAD.size)
    msg.imu_state.rpy, msg.imu_state.gyro, msg.imu_state.acc = list(values[:3]), list(values[3:6]), list(values[6:])
    offset = _STATE_HEAD.size + _IMU.size
    for group in ("motor_state_serial", "motor_state_parallel"):
        motors = []
        for _ in range(n):
            mode, q, dq, ddq, tau, temp, lost, r0, r1 = _MOTOR_STATE.unpack_from(raw, offset)
            offset += _MOTOR_STATE.size
            motors.append(MotorState(mode=mode, q=q, dq=dq, ddq=ddq, tau_est=tau, temperature=temp, lost=lost,
                                     reserve=[r0, r1]))
        setattr(msg, group, motors)
    msg._forge_seq, msg._forge_sim_time = seq, sim_time
    return msg


def encode_low_cmd(msg, seq: int = 0) -> bytes:
    parts = [_CMD_HEAD.pack(b"K1LC", seq & 0xFFFFFFFF, int(msg.cmd_type), len(msg.motor_cmd))]
    for m in msg.motor_cmd:
        parts.append(_MOTOR_CMD.pack(int(m.mode), m.q, m.dq, m.tau, m.kp, m.kd, m.weight))
    return b"".join(parts)


def decode_low_cmd(raw: bytes):
    from booster_interface.msg import LowCmd, MotorCmd
    magic, seq, cmd_type, n = _CMD_HEAD.unpack_from(raw)
    if magic != b"K1LC":
        raise ValueError("not a LowCmd frame")
    msg = LowCmd()
    msg.cmd_type = cmd_type
    offset = _CMD_HEAD.size
    for _ in range(n):
        mode, q, dq, tau, kp, kd, weight = _MOTOR_CMD.unpack_from(raw, offset)
        offset += _MOTOR_CMD.size
        msg.motor_cmd.append(MotorCmd(mode=mode, q=q, dq=dq, tau=tau, kp=kp, kd=kd, weight=weight))
    msg._forge_seq = seq
    return msg


def encode_remote(msg) -> bytes:
    return json.dumps({k: getattr(msg, k) for k in REMOTE_FIELDS}).encode()


def decode_remote(raw: bytes):
    from booster_interface.msg import RemoteControllerState
    return RemoteControllerState(**json.loads(raw.decode()))


CODECS = {"/low_state": (encode_low_state, decode_low_state), "/joint_ctrl": (encode_low_cmd, decode_low_cmd),
          "/remote_controller_state": (encode_remote, decode_remote)}


def encode(topic: str, msg) -> bytes:
    return CODECS[topic][0](msg)


def decode(topic: str, raw: bytes):
    return CODECS[topic][1](raw)


# ------------------------------------------------------------------ in-process bus
class InProcBus:
    """Lockstep harness: publish/RPC call registered Python hooks synchronously."""

    kind = "inproc"

    def __init__(self):
        self.hooks: dict[str, callable] = {}
        self.services: dict[str, callable] = {}
        self.subscriptions: dict[str, list] = {}

    def publish(self, topic, msg):
        hook = self.hooks.get(topic)
        if hook is not None:
            hook(msg)
        for sub in self.subscriptions.get(topic, []):
            sub._offer(msg)

    def subscribe(self, sub):
        self.subscriptions.setdefault(sub.topic, []).append(sub)

    def unsubscribe(self, sub):
        if sub in self.subscriptions.get(sub.topic, []):
            self.subscriptions[sub.topic].remove(sub)

    def subscription_count(self, topic) -> int:
        return int(topic in self.hooks) + len(self.subscriptions.get(topic, []))

    def service_available(self, name, timeout) -> bool:
        return name in self.services

    def call(self, name, request):
        return self.services[name](request)

    def close(self):
        pass


# ------------------------------------------------------------------ Unix-socket bus (client side)
class UdsBus:
    """Client of the Virtual K1 real-time server; safe to use from forked children."""

    kind = "uds"
    _ids = itertools.count()

    def __init__(self, directory: str):
        self.directory = directory
        self.server_topics = os.path.join(directory, "topics.sock")
        self.server_rpc = os.path.join(directory, "rpc.sock")
        self._send = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self._seq = 0

    def publish(self, topic, msg):
        # No lock: booster_deploy publishes from a forked child, and a lock held by another
        # thread at fork time would deadlock it.  The sequence number is informational only.
        self._seq += 1
        payload = _TOPIC_TAG[topic] + (encode_low_cmd(msg, self._seq) if topic == "/joint_ctrl" else encode(topic, msg))
        try:
            self._send.sendto(payload, self.server_topics)
        except (FileNotFoundError, ConnectionRefusedError, OSError):
            pass  # like DDS: a publisher without a reachable reader silently drops

    def subscribe(self, sub):
        path = os.path.join(self.directory, f"sub-{os.getpid()}-{next(self._ids)}.sock")
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.bind(path)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        sub._socket, sub._path = sock, path
        self._control({"op": "subscribe", "topic": sub.topic, "path": path})

    def unsubscribe(self, sub):
        if getattr(sub, "_socket", None) is not None:
            try:
                self._control({"op": "unsubscribe", "topic": sub.topic, "path": sub._path})
            except OSError:
                pass
            sub._socket.close()
            try:
                os.unlink(sub._path)
            except OSError:
                pass
            sub._socket = None

    def _control(self, request: dict, timeout: float = 5.0) -> dict:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(self.server_rpc)
            sock.sendall(json.dumps(request).encode() + b"\n")
            data = b""
            while not data.endswith(b"\n"):
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
        return json.loads(data.decode())

    def subscription_count(self, topic) -> int:
        try:
            return int(self._control({"op": "count", "topic": topic})["count"])
        except OSError:
            return 0

    def service_available(self, name, timeout) -> bool:
        deadline = time.monotonic() + (timeout if timeout is not None else 1e9)
        while True:
            try:
                return bool(self._control({"op": "has_service", "name": name}, timeout=1.0).get("ok"))
            except OSError:
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.05)

    def call(self, name, request):
        from booster_interface.srv import RpcService
        reply = self._control({"op": "rpc", "name": name, "api_id": int(request.msg.api_id), "body": request.msg.body})
        response = RpcService.Response()
        response.msg.status, response.msg.body = int(reply["status"]), reply["body"]
        return response

    @staticmethod
    def receive_latest(sub, timeout: float | None):
        """Depth-1 KEEP_LAST: drain the socket and keep only the newest sample."""
        sock = sub._socket
        if sock is None:
            return None
        ready, _, _ = select.select([sock], [], [], timeout or 0)
        if not ready:
            return None
        latest = None
        while True:
            try:
                latest = sock.recv(1 << 16, socket.MSG_DONTWAIT)
            except BlockingIOError:
                break
        return None if latest is None else decode(sub.topic, latest[1:])

    def close(self):
        self._send.close()


_BUS = None
_BUS_PID = None


def bus():
    """Process-wide bus; re-created lazily after fork only for socket-owning state."""
    global _BUS, _BUS_PID
    if _BUS is None:
        spec = os.environ.get("FORGE_ROS_SHIM_BUS", "inproc")
        _BUS = UdsBus(spec.split(":", 1)[1]) if spec.startswith("uds:") else InProcBus()
        _BUS_PID = os.getpid()
    return _BUS


def set_bus(new_bus):
    global _BUS, _BUS_PID
    _BUS, _BUS_PID = new_bus, os.getpid()
    return new_bus
