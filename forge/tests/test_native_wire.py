import socket
import struct
import threading

import pytest

from forge import native_wire as wire


def sensor(tick=0):
    return wire.Frame(wire.SENSOR, tick, tick * wire.STEP_NS, bytes(wire.PAYLOAD_BYTES))


def test_cross_language_wire_offsets():
    frame = sensor(7).encode()
    assert len(frame) == 4064
    assert frame[:4] == b"FG16"
    assert struct.unpack_from("<Q", frame, 16)[0] == 7
    assert struct.unpack_from("<Q", frame, 24)[0] == 14_000_000
    assert struct.unpack_from("<I", frame, 40)[0] == 22
    assert wire.Frame.decode(frame) == sensor(7)


def test_stream_fragmentation_and_eof():
    left, right = socket.socketpair()
    raw = sensor(3).encode()
    def sender():
        with left:
            for start in range(0, len(raw), 17):
                left.sendall(raw[start:start + 17])
    worker = threading.Thread(target=sender)
    worker.start()
    with right:
        assert wire.receive(right) == sensor(3)
        with pytest.raises(EOFError):
            wire.receive(right)
    worker.join(timeout=2)
    assert not worker.is_alive()


@pytest.mark.parametrize("offset,value", [(0, 0), (4, 9), (12, 0), (40, 20)])
def test_schema_mismatch(offset, value):
    raw = bytearray(sensor().encode())
    struct.pack_into("<I", raw, offset, value)
    with pytest.raises(ValueError, match="schema"):
        wire.Frame.decode(raw)


def test_reject_clock_mismatch_and_replay():
    request = sensor(5)
    good = wire.Frame(wire.ACTUATOR, 5, 10_000_000, request.payload,
                      controller_time_before=0.010, controller_time_after=0.012)
    wire.validate_reply(request, good)
    with pytest.raises(ValueError, match="stale"):
        wire.validate_reply(sensor(6), good)
    with pytest.raises(ValueError, match="timer"):
        wire.validate_reply(request, wire.Frame(wire.ACTUATOR, 5, 10_000_000,
                                               request.payload, controller_time_after=4))
    with pytest.raises(ValueError, match="disagree"):
        wire.Frame(wire.SENSOR, 5, 0, request.payload).encode()


def test_vendor_sensor_layout_from_dwarf():
    payload = wire.sensor_payload([0.1] * 22, [0.2] * 22, [0.3] * 22,
                                  acceleration=(0, 0, 9.81), rpy=(0, 0, 0),
                                  gyro=(0, 0, 0), count=7)
    assert struct.unpack_from("<I", payload)[0] == 2308
    invalid, items = wire.decode_tlv(payload)
    assert invalid == 0
    assert struct.unpack("<i", items[7])[0] == 22
    assert struct.unpack_from("<d", items[3], 16)[0] == 9.81
    assert struct.unpack_from("<i", items[3], 152)[0] == 7
    assert struct.unpack_from("<f", items[6], 21 * 96 + 12)[0] == pytest.approx(0.3)


def test_vendor_invalid_flag_is_preserved_and_not_invented_fault():
    payload = wire.encode_tlv({5: bytes(2112), 9: struct.pack("<i", 3)}, invalid=1)
    output = wire.actuator_payload(payload)
    assert output["vendor_invalid_flag"] == 1
    assert output["domain"] == "original_parallel_motors"
    assert output["mode"] == 3


def test_serial_domain_is_explicit_in_both_framing_and_torque_envelope():
    payload = wire.encode_tlv({5: bytes(2112), 9: struct.pack('<i', 0),
                               wire.SERIAL_TORQUE_LIMITS: struct.pack('<22d', *([36.] * 22))})
    sensor = wire.Frame(wire.SENSOR, 0, 0, bytes(4000), version=wire.SERIAL_VERSION)
    reply = wire.Frame(wire.ACTUATOR, 0, 0, payload, controller_time_after=.002, version=wire.SERIAL_VERSION)
    assert wire.Frame.decode(reply.encode()) == reply
    wire.validate_reply(sensor, reply)
    decoded = wire.actuator_payload(payload, version=wire.SERIAL_VERSION)
    assert decoded['domain'] == 'physical_serial_joints'
    assert decoded['torque_limits'] == [36.] * 22
    with pytest.raises(ValueError, match='domain'):
        wire.actuator_payload(payload)
    with pytest.raises(ValueError, match='domain'):
        wire.validate_reply(wire.Frame(wire.SENSOR, 0, 0, bytes(4000)), reply)


@pytest.mark.parametrize('limits', [b'', bytes(8), struct.pack('<22d', *([-1.] * 22)),
                                  struct.pack('<22d', *([float('nan')] * 22))])
def test_serial_actuation_requires_complete_finite_nonnegative_envelope(limits):
    payload = wire.encode_tlv({5: bytes(2112), 9: struct.pack('<i', 0), wire.SERIAL_TORQUE_LIMITS: limits})
    with pytest.raises(ValueError, match='torque limits'):
        wire.actuator_payload(payload, version=wire.SERIAL_VERSION)


@pytest.mark.parametrize("length", [0, 7, 4001])
def test_invalid_tlv_length(length):
    payload = bytearray(4000)
    struct.pack_into("<I", payload, 0, length)
    with pytest.raises(ValueError, match="length"):
        wire.decode_tlv(payload)


def test_negative_tlv_item_size():
    payload = bytearray(4000)
    struct.pack_into("<II", payload, 0, 16, 0)
    struct.pack_into("<Ii", payload, 8, 3, -1)
    with pytest.raises(ValueError, match="item"):
        wire.decode_tlv(payload)


def test_motion_rpc_identity_and_scope():
    payload = wire.encode_tlv({})
    packet = wire.with_motion_rpc(payload, sequence=8, api=2001, body={"vx": .1, "vy": 0, "vyaw": 0})
    _, items = wire.decode_tlv(packet)
    assert len(items[wire.RPC_REQUEST]) == 544
    assert struct.unpack_from("<IIQqQ", items[wire.RPC_REQUEST]) == (1, 26, 8, 2001, 0)
    with pytest.raises(ValueError, match="unsupported"):
        wire.with_motion_rpc(payload, sequence=9, api=9999, body={})
    with pytest.raises(ValueError, match="one motion"):
        wire.with_motion_rpc(packet, sequence=9, api=2001, body={})
    with pytest.raises(ValueError):
        wire.with_motion_rpc(payload, sequence=10, api=2001, body={"vx": float("nan")})
    response = struct.pack("<IIQqq", 1, 2, 8, 2001, -3) + b"{}" + bytes(510)
    reply = wire.motion_rpc_reply(wire.encode_tlv({wire.RPC_RESPONSE: response}), sequence=8, api=2001)
    assert reply["status"] == -3
    with pytest.raises(ValueError, match="identity"):
        wire.motion_rpc_reply(wire.encode_tlv({wire.RPC_RESPONSE: response}), sequence=9, api=2001)
