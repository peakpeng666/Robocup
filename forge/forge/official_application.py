"""Independent audit of actual application events against original ARM wire IO."""
from __future__ import annotations

from collections import Counter
import gzip
import json
import math
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET

from . import native_wire as wire

KICK = 0x46470003
KICK_LAYOUT = struct.Struct('<IiIIQ7d64s')


def read_depth_evidence(path: Path) -> bytes:
    """Restore the exact little-endian float bytes from any retained format."""
    # Completed runs may retain a verified lossless archive instead of the raw
    # duplicate. Keep the original logged paths usable without rewriting logs.
    if not path.exists() and path.name.endswith('.depth-f32'):
        archived = path.with_name(path.name+'-byteplanes.gz')
        if archived.exists(): path = archived
    raw = gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes()
    if path.name.endswith('.depth-f32-byteplanes.gz'):
        if len(raw) % 4: raise ValueError('truncated float byteplanes')
        count = len(raw)//4
        restored = bytearray(len(raw))
        for byte in range(4): restored[byte::4] = raw[byte*count:(byte+1)*count]
        return bytes(restored)
    return raw


def scene_geometry(model: Path, publisher_config: Path, ball_model: Path, field_config: Path) -> dict:
    """Calibrate against model/config files, never against hidden world state.

    The native publisher's RigidBodyIdentifier includes head_point. Its Pose is
    already at that point, not at the head_pitch_link origin. Extrinsics must
    subtract this fixed offset before composing the original published Pose.
    """
    camera = ET.parse(model).getroot().find(".//Camera[@name='CameraColor']")
    if camera is None or camera.find('Rotation') is not None:
        raise ValueError('unsupported physical camera mounting')
    translation = camera.find('Translation').attrib
    mount = [float(translation.get(axis, '0')) for axis in 'xyz']
    publisher = publisher_config.read_text().split('publisher = {', 1)[1].split('\n    },', 1)[0]
    if 'head_name = "head_pitch_link"' not in publisher:
        raise ValueError('native head publisher frame changed')
    point = [float(x) for x in re.search(r'head_point\s*=\s*\{([^}]+)\}', publisher)[1].split(',')]
    if len(point) != 3:
        raise ValueError('native head point must have three coordinates')
    width, height = int(camera.attrib['imageWidth']), int(camera.attrib['imageHeight'])
    angles = [float(camera.attrib[key].removesuffix('degree')) for key in ('angleX', 'angleY')]
    offset = [a-b for a, b in zip(mount, point)]
    radius = float(ET.parse(ball_model).getroot().find('.//SphereGeometry').attrib['radius'])
    text = field_config.read_text()
    def metres(key):
        return float(re.search(r'^' + re.escape(key) + r'\s*=\s*([\d.]+);', text, re.M)[1])/1000
    half_length, half_width = metres('xPosOpponentGoalLine'), metres('yPosLeftTouchline')
    return {'schema': 'forge.official-scene-geometry/1', 'width':width, 'height':height,
        'intrin': {'fx':width/(2*math.tan(math.radians(angles[0])/2)),
                  'fy':height/(2*math.tan(math.radians(angles[1])/2)), 'cx':width/2, 'cy':height/2},
        'camera_mount_in_head_link':mount, 'native_published_head_point':point,
        'extrin':[[0.,0.,1.,offset[0]],[-1.,0.,0.,offset[1]],[0.,-1.,0.,offset[2]],[0.,0.,0.,1.]],
        'ball_radius':radius,
        'field':[2*half_length,2*half_width,half_length-metres('xPosOpponentPenaltyMark'),
                 2*metres('yPosLeftGoal'),metres('centerCircleRadius'),
                 half_length-metres('xPosOpponentPenaltyArea'),2*metres('yPosLeftPenaltyArea'),
                 half_length-metres('xPosOpponentGoalArea'),2*metres('yPosLeftGoalArea')],
        'sources':[str(p.resolve()) for p in (model,publisher_config,ball_model,field_config)],
        'native_state_estimate_accuracy_qualified':False}


def audit_application(events_path: Path, wire_path: Path) -> dict:
    report = {'schema': 'forge.official-application-wire-audit/1', 'status': 'FAIL',
              'requests_dispatched': 0, 'kick_inputs_dispatched': 0}
    try:
        events = [json.loads(line) for line in events_path.read_text().splitlines()]
        requests = [e for e in events if e['event'] == 'SDK_REQUEST']
        replies = [e for e in events if e['event'] == 'SDK_REPLY']
        kicks = [e for e in events if e['event'] == 'VISUAL_KICK_INPUT']
        index = kick_index = ticks = 0
        statuses = Counter()
        with wire_path.open('rb') as stream:
            while True:
                sensor = wire.Frame.decode(stream.read(wire.FRAME_BYTES))
                response = wire.Frame.decode(stream.read(wire.FRAME_BYTES))
                if sensor.tick != ticks:
                    raise ValueError('native sequence changed')
                if sensor.kind == wire.STOP:
                    if response.kind != wire.STOPPED or response.tick != ticks or stream.read(1):
                        raise ValueError('missing final native STOP acknowledgment')
                    break
                wire.validate_reply(sensor, response)
                _, inputs = wire.decode_tlv(sensor.payload)
                if wire.RPC_REQUEST in inputs:
                    raw = inputs[wire.RPC_REQUEST]
                    version, size, sequence, api, reserved = wire.RPC_HEADER.unpack_from(raw)
                    request, delivered = requests[index], replies[index]
                    if (version != 1 or reserved or sequence != index + 1 or size > 512 or
                            api != request['api_id'] or raw[32:32 + size] != request['body'].encode()):
                        raise ValueError('original SDK bytes/order changed before native dispatch')
                    if request['step'] > ticks or delivered['step'] != ticks + 1:
                        raise ValueError('SDK dispatch or feedback crossed the wrong physics boundary')
                    native = wire.motion_rpc_reply(response.payload, sequence=sequence, api=api)
                    if delivered['uuid'] != request['uuid'] or any(delivered[key] != value
                            for key, value in [('sequence', sequence), ('api_id', api),
                                               ('status', native['status']), ('body', native['body'])]):
                        raise ValueError('original SDK response/UUID changed before application delivery')
                    statuses[str(native['status'])] += 1
                    index += 1
                if KICK in inputs:
                    version, sec, nanosec, length, sequence, *tail = KICK_LAYOUT.unpack(inputs[KICK])
                    event = kicks[kick_index]
                    message = event['message']
                    if (version != 1 or sequence != ticks + 1 or event['step'] != ticks or
                            sec != message['sec'] or nanosec != message['nanosec'] or
                            tail[:7] != message['values'] or length > 64 or
                            tail[7][:length] != message['frame_id'].encode()):
                        raise ValueError('original visual kick input changed before native handler')
                    kick_index += 1
                ticks += 1
        if index != len(replies):
            raise ValueError('application logged a reply absent from native evidence')
        pending = requests[index:]
        if any(e['step'] != ticks for e in pending) or any(e['step'] != ticks for e in kicks[kick_index:]):
            raise ValueError('commands were stranded before the final simulation boundary')
        report.update(status='PASS', steps=ticks, requests_dispatched=index,
            request_status_counts=dict(statuses), request_api_counts=dict(Counter(e['api_id'] for e in requests[:index])),
            brain_requests_dispatched=sum(e['origin'] == 'official_brain' for e in requests[:index]),
            kick_inputs_dispatched=kick_index, final_boundary_requests_pending=len(pending),
            final_boundary_kick_pending=len(kicks)-kick_index)
    except (OSError, ValueError, KeyError, IndexError, struct.error) as error:
        report['error'] = f'{type(error).__name__}: {error}'
    return report


def native_planners(wire_path: Path) -> tuple[list[int], list[dict]]:
    """Read actual publisher modes, independent of Brain flags and SDK acceptance."""
    modes, changes = [-1], []
    with wire_path.open('rb') as stream:
        while True:
            sensor = wire.Frame.decode(stream.read(wire.FRAME_BYTES))
            response = wire.Frame.decode(stream.read(wire.FRAME_BYTES))
            if sensor.kind == wire.STOP:
                if response.kind != wire.STOPPED or stream.read(1):
                    raise ValueError('missing final mode evidence acknowledgment')
                break
            wire.validate_reply(sensor, response)
            _, items = wire.decode_tlv(response.payload)
            data = items[0x46470002]
            if len(data) != 840 or struct.unpack_from('<IIQ', data) != (1, 1, len(modes)):
                raise ValueError('invalid native mode feedback sequence')
            mode = struct.unpack_from('<i', data, 128)[0]
            if mode != modes[-1]:
                changes.append({'step': len(modes), 'seconds': len(modes)*.002, 'planner': mode})
            modes.append(mode)
    return modes, changes


def qualify_visual_contacts(contacts, motion, modes, starts, visual_inputs):
    """Conservative observed foot-strike gate; never qualifies a complete match.

    A start request alone cannot pass. Require original controller mode, recent
    original visual input, a physical foot contact and subsequent ball motion
    before any other robot touches it. Thresholds are explicit test criteria.
    """
    # A foot can remain in contact for dozens of 2 ms solver steps. Count the
    # continuous episode once, rather than reporting each callback as a kick.
    episodes, last = [], {}
    for contact in contacts:
        key = (contact['robot'],contact['body'])
        step = int(contact['step'])
        if key in last and 0 <= step-last[key]['end_step'] <= 5:
            last[key]['end_step'] = step
        else:
            episode = dict(contact,end_step=step)
            episodes.append(episode); last[key] = episode
    outcomes = []
    for contact in episodes:
        robot, step = contact['robot'].split('.')[-1], int(contact['step'])
        if robot not in modes:
            continue
        sequence = modes[robot]
        actual = sequence[step] if 0 <= step < len(sequence) else -1
        reasons = []
        if actual not in (12, 22): reasons.append('native_controller_was_not_visual_kick')
        if any(m not in (12,22) for m in sequence[step:int(contact['end_step'])+1]):
            reasons.append('visual_controller_did_not_cover_whole_contact')
        if int(contact['native_planner']) != actual: reasons.append('contact_and_native_mode_evidence_disagree')
        if not any(part in contact['body'].split('.') for part in ('LFoot', 'RFoot')):
            reasons.append('contact_was_not_a_foot')
        if not any(0 <= step - s <= 15000 for s in starts.get(robot, [])):
            reasons.append('no_recent_accepted_official_brain_start')
        if not any(0 <= step - s <= 100 for s in visual_inputs.get(robot, [])):
            reasons.append('no_recent_original_visual_input')
        before = [m for m in motion if step-25 <= int(m['step']) <= step]
        horizon = min([step+500] + [int(c['step']) for c in contacts
            if int(c['step']) > step and c['robot'] != contact['robot']])
        after = [m for m in motion if step < int(m['step']) < horizon]
        speed_before = max((math.hypot(float(m['vx']),float(m['vy'])) for m in before), default=0.)
        speed_after = max((math.hypot(float(m['vx']),float(m['vy'])) for m in after), default=0.)
        travel = max((math.hypot(float(m['x_m'])-float(contact['x_m']),
                               float(m['y_m'])-float(contact['y_m'])) for m in after), default=0.)
        if not before or not after: reasons.append('incomplete_ball_motion_evidence')
        if speed_after < 1.5 or speed_after-speed_before < .8 or travel < .3:
            reasons.append('insufficient_isolated_ball_acceleration_or_travel')
        outcomes.append({'robot': robot, 'step': step, 'end_step':contact['end_step'], 'seconds': step*.002, 'native_planner': actual,
            'body': contact['body'], 'qualified': not reasons, 'reasons': reasons,
            'ball_speed_before_m_s':speed_before, 'ball_speed_after_m_s':speed_after,
            'isolated_ball_travel_m':travel})
    return outcomes


def audit_visual_kicks(run: Path, native_processes: dict) -> dict:
    report = {'schema':'forge.official-visual-kick-action-audit/2', 'status':'FAIL',
              'full_real2sim_qualified':False,
              'criteria':{'minimum_ball_speed_m_s':1.5, 'minimum_speed_gain_m_s':.8,
                          'minimum_isolated_travel_m':.3, 'visual_input_max_age_s':.2}}
    try:
        modes, timelines, starts, visual_inputs = {}, {}, {}, {}
        for robot, info in native_processes['robots'].items():
            modes[robot], timelines[robot] = native_planners(Path(info['work'])/'output/simrobot-wire.bin')
            events = [json.loads(line) for line in (run/robot/'application.jsonl').read_text().splitlines()]
            requests = {e['uuid']:e for e in events if e['event']=='SDK_REQUEST'}
            starts[robot] = [e['step'] for e in events if e['event']=='SDK_REPLY' and e['api_id']==2038
                and e['status']==0 and requests[e['uuid']]['origin']=='official_brain'
                and json.loads(requests[e['uuid']]['body']).get('start') is True]
            visual_inputs[robot] = [e['step'] for e in events if e['event']=='VISUAL_KICK_INPUT']
        contacts, motion = [], []
        for line in (run/'console.log').read_text(errors='replace').splitlines():
            if 'AUDIT ball_contact ' in line:
                contacts.append(dict(re.findall(r'(\w+)=([^\s]+)', line)))
            elif 'AUDIT ball_motion ' in line:
                motion.append(dict(re.findall(r'(\w+)=([^\s]+)', line)))
        outcomes = qualify_visual_contacts(contacts, motion, modes, starts, visual_inputs)
        report.update(status='PASS' if any(c['qualified'] for c in outcomes) else 'FAIL',
            native_planner_timelines=timelines, accepted_brain_start_steps=starts,
            contacts=outcomes, observed_visual_foot_strikes=sum(c['qualified'] for c in outcomes),
            ball_motion_samples=len(motion))
        if not motion: report['limitation']='This run predates physical foot-contact/ball-motion instrumentation.'
    except (OSError, ValueError, KeyError, IndexError, struct.error) as error:
        report['error'] = f'{type(error).__name__}: {error}'
    return report
