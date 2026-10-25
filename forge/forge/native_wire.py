"""Strict framing for the isolated, original Booster 1.6 controller bridge.

Wire v1 is the vendor's parallel-actuator TLV buffer. Explicit wire v2 uses
physical serial joints and requires torque envelopes from the native converter.

``vendor_invalid_flag`` retains the original RsProtoData field name. The pinned
RsSdkInput unconditionally writes 1 to that field on every normal output. It is
not the outer frame/RPC error status and must not be treated as a nonzero error.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import json
import socket
import struct

MAGIC = 0x36314746
VERSION = 1
SERIAL_VERSION = 2
SENSOR = 1
ACTUATOR = 2
ERROR = 3
STOP = 4
STOPPED = 5
MOTORS = 22
STEP_NS = 2_000_000
PAYLOAD_BYTES = 4000
HEADER = struct.Struct("<IIIIQQQIIdd")
FRAME_BYTES = HEADER.size + PAYLOAD_BYTES
MOTOR_BYTES = 96
IMU_BYTES = 160
RPC_REQUEST = 0x46470001
RPC_RESPONSE = 0x46478001
RPC_HEADER = struct.Struct("<IIQqQ")
MOTION_APIS = frozenset((2000, 2001, 2004, 2008, 2017, 2018, 2024, 2025, 2038, 2042))
ARGUMENTLESS_APIS = frozenset((2008, 2017, 2018, 2024))
SERIAL_TORQUE_LIMITS = 0x46500002


@dataclass(frozen=True)
class Frame:
    kind: int
    tick: int
    time_ns: int
    payload: bytes
    step_ns: int = STEP_NS
    status: int = 0
    controller_time_before: float = 0.0
    controller_time_after: float = 0.0
    version: int = VERSION

    def validate(self) -> None:
        if self.version not in (VERSION, SERIAL_VERSION):
            raise ValueError("native frame schema mismatch")
        if self.kind not in (SENSOR, ACTUATOR, ERROR, STOP, STOPPED):
            raise ValueError("unknown frame kind")
        if len(self.payload) != PAYLOAD_BYTES:
            raise ValueError("vendor TLV buffer must be exactly 4000 bytes")
        if self.step_ns != STEP_NS:
            raise ValueError("the audited firmware controller uses a 2 ms tick")
        if self.tick < 0 or self.time_ns < 0 or self.time_ns != self.tick * self.step_ns:
            raise ValueError("physics tick and time disagree")
        if not all(math.isfinite(x) for x in (self.controller_time_before, self.controller_time_after)):
            raise ValueError("nonfinite controller clock")

    def encode(self) -> bytes:
        self.validate()
        return HEADER.pack(MAGIC, self.version, self.kind, PAYLOAD_BYTES, self.tick,
                           self.time_ns, self.step_ns, MOTORS, self.status,
                           self.controller_time_before, self.controller_time_after) + self.payload

    @classmethod
    def decode(cls, raw: bytes) -> Frame:
        if len(raw) != FRAME_BYTES:
            raise ValueError("truncated or oversized native frame")
        magic, version, kind, size, tick, time_ns, step_ns, motors, status, before, after = HEADER.unpack_from(raw)
        if (magic, size, motors) != (MAGIC, PAYLOAD_BYTES, MOTORS) or version not in (VERSION, SERIAL_VERSION):
            raise ValueError("native frame schema mismatch")
        frame = cls(kind, tick, time_ns, raw[HEADER.size:], step_ns, status, before, after, version)
        frame.validate()
        return frame


def receive(sock: socket.socket) -> Frame:
    remaining = FRAME_BYTES
    parts = []
    while remaining:
        part = sock.recv(remaining)
        if not part:
            raise EOFError("controller disconnected before a complete frame")
        parts.append(part)
        remaining -= len(part)
    return Frame.decode(b"".join(parts))


def validate_reply(sensor: Frame, reply: Frame) -> None:
    sensor.validate()
    reply.validate()
    if sensor.kind != SENSOR or reply.kind != ACTUATOR or reply.status != 0:
        raise ValueError("controller did not return a successful actuator frame")
    if sensor.version != reply.version:
        raise ValueError("reply actuator domain/version mismatch")
    if (reply.tick, reply.time_ns, reply.step_ns) != (sensor.tick, sensor.time_ns, sensor.step_ns):
        raise ValueError("stale or future controller reply")
    # The native UpdateTimer accepts milliseconds; SimulationTimer::GetTime
    # and the wire return seconds. Both clocks must agree with the physics tick.
    if not math.isclose(reply.controller_time_after - reply.controller_time_before,
                        STEP_NS / 1_000_000_000, rel_tol=0, abs_tol=1e-9):
        raise ValueError("controller timer did not advance by exactly one physics tick")
    if not math.isclose(reply.controller_time_before, sensor.time_ns / 1e9,
                        rel_tol=0, abs_tol=1e-8):
        raise ValueError("native and physical clocks disagree")


def encode_tlv(items: dict[int, bytes], *, invalid: int = 0) -> bytes:
    content = b"".join(struct.pack("<Ii", key, len(value)) + value for key, value in items.items())
    length = 8 + len(content)
    if length > PAYLOAD_BYTES:
        raise ValueError("vendor TLV buffer overflow")
    return struct.pack("<II", length, invalid) + content + bytes(PAYLOAD_BYTES - length)


def decode_tlv(payload: bytes) -> tuple[int, dict[int, bytes]]:
    if len(payload) != PAYLOAD_BYTES:
        raise ValueError("invalid vendor TLV buffer size")
    length, invalid = struct.unpack_from("<II", payload)
    if not 8 <= length <= PAYLOAD_BYTES:
        raise ValueError("invalid vendor TLV total length")
    offset, items = 8, {}
    while offset < length:
        if offset + 8 > length:
            raise ValueError("truncated vendor TLV header")
        key, size = struct.unpack_from("<Ii", payload, offset)
        offset += 8
        if size < 0 or offset + size > length or key in items:
            raise ValueError("invalid, duplicate, or truncated vendor TLV item")
        items[key] = payload[offset:offset + size]
        offset += size
    return invalid, items


def sensor_payload(q: list[float], dq: list[float], tau: list[float], *,
                   acceleration: tuple[float, float, float],
                   rpy: tuple[float, float, float], gyro: tuple[float, float, float],
                   count: int) -> bytes:
    """Original index order and SI units; v2 is physical FLU, v1 is raw Rs sensor frame."""
    if any(len(v) != MOTORS for v in (q, dq, tau)):
        raise ValueError("expected 22 original motor states")
    values = [*q, *dq, *tau, *acceleration, *rpy, *gyro]
    if not all(math.isfinite(v) for v in values):
        raise ValueError("nonfinite sensor state")
    imu = bytearray(IMU_BYTES)
    struct.pack_into("<9d", imu, 0, *acceleration, *rpy, *gyro)
    struct.pack_into("<i", imu, 152, count)
    motors = bytearray(MOTOR_BYTES * MOTORS)
    for i in range(MOTORS):
        struct.pack_into("<ff", motors, i * MOTOR_BYTES, q[i], dq[i])
        struct.pack_into("<f", motors, i * MOTOR_BYTES + 12, tau[i])
        struct.pack_into("<f", motors, i * MOTOR_BYTES + 84, 25.0)
    return encode_tlv({3: bytes(imu), 7: struct.pack("<i", MOTORS), 6: bytes(motors)})


def actuator_payload(payload: bytes, *, version: int = VERSION) -> dict:
    invalid, items = decode_tlv(payload)
    if len(items.get(5, b"")) != MOTOR_BYTES * MOTORS or len(items.get(9, b"")) != 4:
        raise ValueError("missing complete motor commands or controller mode")
    fields = {"q_target": 32, "qd_target": 36, "tau_ff": 40, "kp": 72, "kd": 80}
    commands = {name: [struct.unpack_from("<f", items[5], i * MOTOR_BYTES + offset)[0]
                      for i in range(MOTORS)] for name, offset in fields.items()}
    if not all(math.isfinite(v) for row in commands.values() for v in row):
        raise ValueError("nonfinite original actuator command")
    if any(v < 0 for field in ("kp", "kd") for v in commands[field]):
        raise ValueError("negative original controller gain")
    result = {"domain": "original_parallel_motors", "mode": struct.unpack("<i", items[9])[0],
              "vendor_invalid_flag": invalid, **commands}
    limits = items.get(SERIAL_TORQUE_LIMITS)
    if version == SERIAL_VERSION:
        if limits is None or len(limits) != MOTORS * 8:
            raise ValueError("serial actuator frame requires 22 physical torque limits")
        values = list(struct.unpack('<22d', limits))
        if not all(math.isfinite(v) and v >= 0 for v in values):
            raise ValueError("invalid physical torque limits")
        result.update(domain='physical_serial_joints', torque_limits=values)
    elif version != VERSION or limits is not None:
        raise ValueError("actuator domain/version mismatch")
    return result


def with_motion_rpc(payload: bytes, *, sequence: int, api: int, body: dict | None) -> bytes:
    """Only audited motion APIs of the original in-process RPC handler."""
    if api not in MOTION_APIS or not 1 <= sequence < 2**64:
        raise ValueError("unsupported motion RPC or sequence")
    if api in ARGUMENTLESS_APIS and body is not None:
        raise ValueError("argumentless original API requires body=None")
    if api not in ARGUMENTLESS_APIS and not isinstance(body, dict):
        raise ValueError("motion RPC body must be an object")
    encoded = b"" if body is None else json.dumps(body, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > 512:
        raise ValueError("motion RPC body exceeds 512 bytes")
    invalid, items = decode_tlv(payload)
    if RPC_REQUEST in items:
        raise ValueError("only one motion RPC is allowed per physics tick")
    items[RPC_REQUEST] = RPC_HEADER.pack(1, len(encoded), sequence, api, 0) + encoded + bytes(512 - len(encoded))
    return encode_tlv(items, invalid=invalid)


def motion_rpc_reply(payload: bytes, *, sequence: int, api: int) -> dict:
    _, items = decode_tlv(payload)
    data = items.get(RPC_RESPONSE, b"")
    if len(data) != 544:
        raise ValueError("missing original motion RPC response")
    version, size, actual_sequence, actual_api, status = struct.unpack_from("<IIQqq", data)
    if version != 1 or size > 512 or (actual_sequence, actual_api) != (sequence, api):
        raise ValueError("motion RPC response identity mismatch")
    body = data[32:32 + size].decode("utf-8", errors="strict")
    return {"sequence": sequence, "api": api, "status": status, "body": body}
