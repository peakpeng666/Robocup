"""Compile and exercise the actual host transport against an independent peer."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import socket
import struct
import subprocess
import time

import pytest

from forge import native_wire as wire

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def executable(tmp_path_factory):
    output = tmp_path_factory.mktemp('native-session-build') / 'session'
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-I', str(ROOT / 'native'), str(ROOT / 'native/test_fw16_session.cpp'),
                    '-o', str(output)], capture_output=True, text=True, check=True)
    return output


def original_peer(directory, behavior):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(5)
    deadline = time.monotonic() + 5
    while True:
        try:
            sock.connect(str(directory / 'firmware.sock'))
            break
        except (FileNotFoundError, ConnectionRefusedError):
            if time.monotonic() > deadline:
                raise
            time.sleep(.005)
    ticks, requests, mode = [], [], 0
    with sock:
        while True:
            try:
                sensor = wire.receive(sock)
            except (EOFError, ConnectionResetError):
                return {'ticks': ticks, 'requests': requests, 'stopped': False}
            if sensor.kind == wire.STOP:
                sock.sendall(wire.Frame(wire.STOPPED, sensor.tick, sensor.time_ns,
                    bytes(wire.PAYLOAD_BYTES), controller_time_before=sensor.tick * .002,
                    controller_time_after=sensor.tick * .002, version=2).encode())
                return {'ticks': ticks, 'requests': requests, 'stopped': True}
            assert sensor.version == 2 and sensor.tick == len(ticks)
            ticks.append(sensor.tick)
            _, inputs = wire.decode_tlv(sensor.payload)
            motors = bytearray(22 * 96)
            for j in range(22):
                q = struct.unpack_from('<f', inputs[6], j * 96)[0]
                struct.pack_into('<f', motors, j * 96 + 32, q + .5)
                struct.pack_into('<f', motors, j * 96 + 72, -1. if behavior == 'negativegain' else 10.)
            rpc_response = None
            if wire.RPC_REQUEST in inputs:
                version, size, sequence, api, _ = wire.RPC_HEADER.unpack_from(inputs[wire.RPC_REQUEST])
                assert version == 1
                body = inputs[wire.RPC_REQUEST][32:32 + size]
                requests.append({'api': api, 'body': body.decode()})
                if api == 2000:
                    mode = 2 if behavior == 'gaitrefusal' else json.loads(body)['mode']
                response_body = (json.dumps({'current_mode': 999 if behavior == 'badstatus' else mode + (1 if behavior == 'transition' else 0),
                    'current_body_control': 2, 'current_actions': []}).encode() if api == 2018 else b'')
                status = 501 if ((behavior == 'gaitrefusal' and api == 2042) or
                                 (behavior.startswith('sdk') and api == 2038)) else 0
                rpc_response = struct.pack('<IIQqq', 1, len(response_body), sequence, api, status) + response_body + bytes(512 - len(response_body))
            items = {5: bytes(motors), 9: struct.pack('<i', mode),
                     wire.SERIAL_TORQUE_LIMITS: struct.pack('<22d', *([36.] * 22))}
            if rpc_response:
                items[wire.RPC_RESPONSE] = rpc_response
            if behavior.startswith('sdk'):
                samples = sensor.tick if behavior == 'sdkstalefeedback' else sensor.tick + 1
                header = struct.pack('<IIQ12f7d4i', 1, 1, samples, *([0.] * 12),
                                     .1, .2, .8, 0., 0., 0., 1., 0, 1, 2, 22)
                motors_feedback = struct.pack('<fffI', .1, .2, .3, 0) * 44
                items[0x46470002] = header + motors_feedback
            reply = wire.Frame(wire.ACTUATOR, sensor.tick, sensor.time_ns,
                wire.encode_tlv(items, invalid=0 if behavior == 'badmarker' else 1),
                controller_time_before=sensor.tick * .002, controller_time_after=(sensor.tick + 1) * .002,
                version=1 if behavior == 'wrongversion' else 2)
            try:
                sock.sendall(reply.encode())
            except BrokenPipeError:
                return {'ticks': ticks, 'requests': requests, 'stopped': False}


@pytest.mark.parametrize('behavior,error', [
    ('normal', None), ('roundedstep', None), ('damping', None), ('gaitrefusal', None), ('skip', 'physical tick skipped'), ('stale', 'stale high-level'),
    ('badclock', 'physical tick and time disagree'), ('negativegain', 'negative actuator'),
    ('wrongversion', 'incompatible'), ('badstatus', 'unsupported original status mode'), ('transition', None),
    ('badmarker', 'RsProtoData output marker'),
])
def test_actual_transport(executable, tmp_path, behavior, error):
    with ThreadPoolExecutor(max_workers=1) as pool:
        peer = pool.submit(original_peer, tmp_path, behavior)
        result = subprocess.run([str(executable), str(tmp_path), behavior],
                                capture_output=True, text=True, timeout=10)
        evidence = peer.result(timeout=6)
    if error is None:
        assert result.returncode == 0, result.stderr
        assert evidence['ticks'] == list(range(80 if behavior == 'gaitrefusal' else 4))
        assert evidence['stopped']
        assert evidence['requests'][0] == {'api': 2000, 'body': '{"mode":1}'}
        if behavior == 'damping':
            assert evidence['requests'][1] == {'api': 2000, 'body': '{"mode":0}'}
        else:
            assert any(r['api'] == 2018 for r in evidence['requests'])
        if behavior == 'gaitrefusal':
            assert sum(r['api'] == 2042 for r in evidence['requests']) == 1
    else:
        assert result.returncode == 2, result.stderr
        assert error in result.stderr
        assert not evidence['stopped']


def test_joint_mapping_matches_retained_sdk():
    import re
    text = (ROOT / 'tools/make_native_motion_patch.py').read_text()
    array = text.split('constexpr Joints::Joint mapping[22] = {', 1)[1].split('};', 1)[0]
    mapping = re.findall(r'Joints::([A-Za-z]+)', array)
    cfg = (ROOT.parent / 'bhuman/local-k1-validation-20261019/bhuman-local/Config/Robots/Default/K1/boosterProvider.cfg').read_text()
    expected = re.findall(r'[A-Za-z]+', cfg.split('jointMapping = [', 1)[1].split('];', 1)[0])
    assert len(mapping) == 22 and mapping == expected


@pytest.mark.parametrize('behavior,error', [
    ('sdk', None), ('sdkbadsequence', 'external SDK request identity'),
    ('sdkstalefeedback', 'invalid original application feedback'),
])
def test_sdk_bytes_refusals_and_native_feedback(executable, tmp_path, behavior, error):
    with ThreadPoolExecutor(max_workers=1) as pool:
        peer = pool.submit(original_peer, tmp_path, behavior)
        result = subprocess.run([str(executable), str(tmp_path), behavior],
                                capture_output=True, text=True, timeout=10)
        evidence = peer.result(timeout=6)
    if error:
        assert result.returncode == 2 and error in result.stderr
        assert not evidence['stopped']
    else:
        assert result.returncode == 0, result.stderr
        assert evidence['stopped'] and evidence['ticks'] == list(range(4))
        assert evidence['requests'] == [
            {'api': 2000, 'body': ' { "mode" : 1 }\n'},
            {'api': 2018, 'body': ''},
            {'api': 2038, 'body': '{"start":false}'},
        ]
