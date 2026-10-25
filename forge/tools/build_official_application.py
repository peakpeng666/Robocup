#!/usr/bin/env python3
"""Build a simulator platform entry around pinned, already-built official sources.

Reuse unchanged algorithm objects. Recompile only platform transport seams and
the entry point. The original hardware executables and source baseline survive.
"""
from __future__ import annotations
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
from datetime import datetime

FORGE = Path(__file__).resolve().parents[1]
CHECKPOINT = FORGE / 'runs/full-native-integration/20261023_174356_314369_two-independent-teams'
BASE = FORGE / 'variants/official-application-upstream-fa4f31c-20261023-a'


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f'expected one platform seam: {old[:100]!r}')
    return text.replace(old, new)


def adapt(root):
    changes = {}
    def edit(name, transform):
        path = root / name
        before = path.read_text()
        after = transform(before)
        path.write_text(after)
        changes[name] = ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
            fromfile='a/' + name, tofile='b/' + name))
    edit('src/brain/src/robot_client.cpp', lambda s: replace(s,
        '    publisher->publish(message);',
        '    extern void forge_application_sdk(const booster_msgs::msg::RpcReqMsg&);\n    forge_application_sdk(message);'))
    edit('src/brain/src/brain.cpp', lambda s: replace(s,
        '    pubKickBall->publish(kickMsg);',
        '    extern void forge_application_kick(const brain::msg::Kick&);\n    forge_application_kick(kickMsg);'))
    edit('src/vision/src/vision_node.cpp', lambda s: replace(s,
        '    data_logger_->LogYAML(node, "vision_local.yaml");',
        '    if(data_logger_) data_logger_->LogYAML(node, "vision_local.yaml");'))
    edit('src/brain/include/brain_communication.h', lambda s: replace(s,
        '    bool isTeamChanged();', '    bool isTeamChanged();\n'
        '    std::vector<unsigned char> forgeTeamPacket();\n'
        '    void forgeReceiveTeamPacket(const std::vector<unsigned char>& packet);'))
    original = (root / 'src/brain/src/brain_communication.cpp').read_text()
    # Reuse the actual upstream packet generation and state-update statements.
    # Only the surrounding UDP threads/receive loop become clock-driven IO.
    sender = original.split('void BrainCommunication::unicastCommunication()', 1)[1]
    sender = sender[sender.index('        TeamCommunicationMsg msg;'):sender.index('        std::lock_guard<std::mutex> lock(_teammate_addresses_mutex);')]
    sender = sender.replace('TeamCommunicationMsg msg;', 'TeamCommunicationMsg msg{};')
    receiver = original.split('void BrainCommunication::spinCommunicationReceiver()', 1)[1]
    receiver = receiver[receiver.index('        if (msg.validation'):receiver.index('\n    }\n}')]
    receiver = receiver.replace('continue;', 'return;')
    methods = '''
// Simulation network backend: original packet fields and receiver semantics,
// scheduled at the original 100 ms interval by the shared physics clock.
std::vector<unsigned char> BrainCommunication::forgeTeamPacket() {
    auto log = [this](string message) { brain->log->debug("sendMsg", message); };
'''+sender+'''
    std::vector<unsigned char> result(sizeof(msg));
    std::memcpy(result.data(), &msg, sizeof(msg));
    return result;
}
void BrainCommunication::forgeReceiveTeamPacket(const std::vector<unsigned char>& packet) {
    if(packet.size() != sizeof(TeamCommunicationMsg)) throw std::runtime_error("invalid official team packet size");
    TeamCommunicationMsg msg{};
    std::memcpy(&msg, packet.data(), sizeof(msg));
    auto log = [this](string message) { brain->log->debug("receiveMsg", message); };
'''+receiver+'\n}\n'
    def communication(s):
        s = replace(s, 'BrainCommunication::~BrainCommunication()\n{',
            'BrainCommunication::~BrainCommunication()\n{\n    if(std::getenv("FORGE_APPLICATION_SOCKET")) return;')
        s = replace(s, 'void BrainCommunication::initCommunication()\n{',
            'void BrainCommunication::initCommunication()\n{\n'
            '    if(std::getenv("FORGE_APPLICATION_SOCKET")) {\n'
            '        _discovery_udp_port = 20000 + brain->config->get_team_id();\n'
            '        _unicast_udp_port = 30000 + brain->config->get_team_id();\n'
            '        return;\n    }')
        return '#include <cstring>\n#include <cstdlib>\n' + s + methods
    edit('src/brain/src/brain_communication.cpp', communication)
    (root / 'platform.patch').write_text(''.join(changes.values()))
    return changes


def firmware16_compatibility(root):
    """Apply the same SDK serialization fix to either hardware or sim builds.

    1.6.0.10 rejects the Demo's handwritten {start:true} with status 400:
    its official VisualKickParameter requires the numeric version field.
    Keep the SDK default V1. Wait for the published controller mode before
    starting its head scan; the 1.6 transition rejects head commands meanwhile.
    """
    name = 'src/brain/src/robot_client.cpp'
    path = root / name
    before = path.read_text()
    old = ('    nlohmann::json body;\n'
           '    body["start"] = start;  // Add start parameter to indicate whether to enter VisualKick mode\n'
           '    msg.body = body.dump();')
    new = ('    // Use the SDK serializer: FW 1.6 requires both start and version.\n'
           '    msg.body = booster::robot::b1::VisualKickParameter(start).ToJson().dump();')
    after = replace(before, old, new)
    path.write_text(after)
    patch = ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
        fromfile='a/' + name, tofile='b/' + name))
    changes = {name: hashlib.sha256(after.encode()).hexdigest()}
    def edit(name, transform):
        nonlocal patch
        path = root / name
        before = path.read_text()
        after = transform(before)
        path.write_text(after)
        patch += ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
            fromfile='a/' + name, tofile='b/' + name))
        changes[name] = hashlib.sha256(after.encode()).hexdigest()
    def ground_pitch(s):
        old = 'obj.pitchToRobot = asin(config->get_robot_height() / obj.range);'
        if s.count(old) != 2:
            raise ValueError('upstream ground-range pitch expressions changed')
        return s.replace(old, 'obj.pitchToRobot = atan2(config->get_robot_height(), obj.range);')
    edit('src/brain/src/brain.cpp', ground_pitch)
    def visual_transition(s):
        s = replace(s, 'NodeStatus RLVisionKick::onStart()\n{', '''NodeStatus RLVisionKick::onStart()
{
    // A previous asynchronous exit must finish before accepting a new start.
    const int planner = brain->data->currentRobotModeIndex;
    if (planner != 10 && planner != 20) {
        brain->data->tmImInVisualKick = false;
        recordExitTime();
        return NodeStatus::FAILURE;
    }''')
        s = replace(s, '                brain->config->get_enable_auto_visual_kick() &&',
            '                brain->config->get_enable_auto_visual_kick() &&\n'
            '                (brain->data->currentRobotModeIndex == 10 || brain->data->currentRobotModeIndex == 20) &&')
        s = replace(s, '                _headScanStartTime = brain->get_clock()->now();',
            '                _headScanStartTime = rclcpp::Time(0, 0, RCL_ROS_TIME);')
        s = replace(s, '                _pendingRobocupWalk = false;\n                return NodeStatus::SUCCESS;',
            '                _decelStartTime = brain->get_clock()->now();\n'
            '                return NodeStatus::RUNNING;')
        s = replace(s, '    // Handle deceleration phase\n    if (_isDecelerating) {', '''    // Completion of the RPC is not completion of the native controller change.
    if (_pendingRobocupWalk && !_isDecelerating) {
        const int planner = brain->data->currentRobotModeIndex;
        if (planner == 10 || planner == 20) {
            _pendingRobocupWalk = false;
            brain->data->tmImInVisualKick = false;
            recordExitTime();
            return NodeStatus::SUCCESS;
        }
        if (brain->msecsSince(_decelStartTime) > 3500.0) {
            _pendingRobocupWalk = false;
            brain->data->tmImInVisualKick = false;
            recordExitTime();
            return NodeStatus::FAILURE;
        }
        return NodeStatus::RUNNING;
    }

    // Handle deceleration phase
    if (_isDecelerating) {''')
        s = replace(s, '    if (_visionKickStarted) {\n        double headMsec', '''    if (_visionKickStarted && _headScanStartTime.nanoseconds() == 0) {
        // SDK acceptance precedes the actual 1.6 controller transition.
        const int planner = brain->data->currentRobotModeIndex;
        if (planner != 12 && planner != 22) {
            if (brain->msecsSince(_startTime) > 3500.0) {
                brain->client->robocupWalk();
                brain->data->tmImInVisualKick = false;
                recordExitTime();
                return NodeStatus::SUCCESS;
            }
            return NodeStatus::RUNNING;
        }
        _headScanStartTime = brain->get_clock()->now();
    }
    if (_visionKickStarted && brain->data->currentRobotModeIndex != 12 &&
        brain->data->currentRobotModeIndex != 22) {
        brain->data->tmImInVisualKick = false;
        recordExitTime();
        return NodeStatus::FAILURE;
    }
    if (_visionKickStarted) {
        double headMsec''')
        start = s.index('NodeStatus RLVisionKick::onRunning()')
        end = s.index('void RLVisionKick::onHalted()', start)
        block = replace(s[start:end], 'double elapsed = brain->msecsSince(_startTime);',
            'double elapsed = brain->msecsSince(_headScanStartTime);')
        return s[:start] + block + s[end:]
    edit('src/brain/src/brain_tree.cpp', visual_transition)
    (root / 'firmware16-compatibility.patch').write_text(patch)
    return changes


def flags(build, component):
    path = build / ('CMakeFiles/brain_node.dir/flags.make' if component == 'brain' else 'src/CMakeFiles/vision_node.dir/flags.make')
    values = {}
    for line in path.read_text().splitlines():
        if line.startswith(('CXX_DEFINES =', 'CXX_INCLUDES =', 'CXX_FLAGS =')):
            key, value = line.split(' = ', 1)
            values[key] = shlex.split(value)
    return [item for key in ['CXX_DEFINES', 'CXX_INCLUDES', 'CXX_FLAGS'] for item in values[key]]


def depth_consistency_profile(root):
    """Optional shared RGB-D profile, separate from firmware compatibility.

    Ground-plane projection cannot distinguish an elevated robot head from a
    ground ball. Validate that assumption with real camera depth and head FK.
    The profile is explicitly selected; upstream detection weights stay intact.
    """
    header='src/vision/include/booster_vision/GroundBallDepthCheck.h'
    content=(FORGE/'native/GroundBallDepthCheck.h').read_text()
    (root/header).write_text(content)
    name='src/vision/src/vision_node.cpp';path=root/name;before=path.read_text()
    after='#include "booster_vision/GroundBallDepthCheck.h"\n'+before
    after=replace(after, '        auto pose_estimator = get_estimator(detection.class_name);', '''        if (detection.class_name == "Ball" &&
            as_or<bool>(config_node_["ground_ball_depth_check"]["enabled"], false) && !depth_float.empty()) {
            const auto checkConfig = config_node_["ground_ball_depth_check"];
            auto matrix = p_eye2base.toCVMat();
            double rotation[9], translation[3];
            for (int r = 0; r < 3; ++r) {
                translation[r] = matrix.at<float>(r, 3);
                for (int c = 0; c < 3; ++c) rotation[r*3+c] = matrix.at<float>(r, c);
            }
            const auto check = OfficialVision::checkGroundBall(depth_float.ptr<float>(),
                depth_float.cols, depth_float.rows, depth_float.step1(), detection.bbox.x,
                detection.bbox.y, detection.bbox.x+detection.bbox.width,
                detection.bbox.y+detection.bbox.height,
                config_node_["camera"]["intrin"]["fx"].as<double>(),
                config_node_["camera"]["intrin"]["fy"].as<double>(),
                config_node_["camera"]["intrin"]["cx"].as<double>(),
                config_node_["camera"]["intrin"]["cy"].as<double>(), rotation, translation,
                checkConfig["minimum_depth"].as<double>(), checkConfig["maximum_depth"].as<double>(),
                checkConfig["minimum_height"].as<double>(), checkConfig["maximum_height"].as<double>());
            if (check.observed && !check.consistent) {
                std::cout << "GROUND_BALL_DEPTH_REJECT height=" << check.height << std::endl;
                continue;
            }
        }
        auto pose_estimator = get_estimator(detection.class_name);''')
    path.write_text(after)
    patch=''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/'+name,tofile='b/'+name))
    patch+=''.join(difflib.unified_diff([],content.splitlines(True),fromfile='/dev/null',tofile='b/'+header))
    (root/'depth-ball-consistency.patch').write_text(patch)
    return {'patch':str(root/'depth-ball-consistency.patch'),'enabled_by_default':False,
            'scope':'optional grounded-ball RGB-D geometry; no world-state input; airborne tracking not qualified'}


def link_inputs(build, component):
    path = build / ('CMakeFiles/brain_node.dir/link.txt' if component == 'brain' else 'src/CMakeFiles/vision_node.dir/link.txt')
    words = shlex.split(path.read_text())[1:]
    result, skip = [], False
    for word in words:
        if skip:
            skip = False
        elif word == '-o':
            skip = True
        else:
            candidate = (build / 'src' if component == 'vision' else build) / word
            result.append(str(candidate.resolve()) if not word.startswith('-') and candidate.is_file() else word)
    return result


def build(name, reuse=None):
    root = FORGE / 'variants' / name
    if root.exists():
        raise FileExistsError(root)
    shutil.copytree(BASE, root, symlinks=True)
    compatibility = firmware16_compatibility(root)
    depth_profile = depth_consistency_profile(root)
    changes = adapt(root)
    out = root / 'sim-build'
    out.mkdir()
    (root / 'platform').mkdir()
    shutil.copyfile(FORGE / 'native/official_application_main.cpp', root / 'platform/official_application_main.cpp')
    shutil.copyfile(FORGE / 'native/simrobot/OfficialApplicationWire.h', root / 'platform/OfficialApplicationWire.h')
    shutil.copyfile(FORGE / 'native/simrobot/OfficialGameState.h', root / 'platform/OfficialGameState.h')
    shutil.copyfile(FORGE / 'native/simrobot/OfficialPortContract.h', root / 'platform/OfficialPortContract.h')
    brain_build, vision_build = CHECKPOINT / 'upstream-app-build/brain', CHECKPOINT / 'upstream-app-build/vision'
    brain_flags, vision_flags = flags(brain_build, 'brain'), flags(vision_build, 'vision')
    common = ['-I' + str(root / 'src/brain/include'), '-I' + str(root / 'src/vision/include'),
              '-I' + str(root / 'platform')]
    commands, objects = [], []
    reused_compilation = {}
    sources = [root / 'src/brain/src' / name for name in ['robot_client.cpp', 'brain.cpp', 'brain_communication.cpp', 'brain_tree.cpp']]
    sources += [root / 'src/vision/src/vision_node.cpp', root / 'platform/official_application_main.cpp']
    for i, source in enumerate(sources):
        obj = out / (source.stem + '.o')
        if reuse and source.name != 'official_application_main.cpp':
            prior = FORGE / 'variants' / reuse
            prior_source = prior / source.relative_to(root)
            header_folders = ['src/vision/include'] if source.name == 'vision_node.cpp' else ['src/brain/include']
            same_headers = all((prior / p.relative_to(root)).is_file() and
                (prior / p.relative_to(root)).read_bytes() == p.read_bytes()
                for folder in header_folders for p in (root / folder).rglob('*') if p.is_file())
            prior_obj = prior / 'sim-build' / obj.name
            if same_headers and prior_obj.is_file() and prior_source.read_bytes() == source.read_bytes():
                shutil.copy2(prior_obj, obj)
                reused_compilation[str(obj)] = {'source_object': str(prior_obj), 'sha256': hashlib.sha256(obj.read_bytes()).hexdigest()}
                objects.append(str(obj))
                continue
        selected = vision_flags if source.name == 'vision_node.cpp' else brain_flags
        if source.name == 'official_application_main.cpp':
            # flags.make uses separate -isystem arguments; include all original
            # vision flags as a second complete set to retain those paths.
            selected = brain_flags + vision_flags
        command = ['/usr/bin/c++', *common, *selected, '-c', str(source), '-o', str(obj)]
        commands.append(command)
        with (out / f'compile-{i}.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        objects.append(str(obj))
    original_inputs = link_inputs(brain_build, 'brain') + link_inputs(vision_build, 'vision')
    replaced = {'main.cpp.o', 'robot_client.cpp.o', 'brain.cpp.o', 'brain_communication.cpp.o', 'brain_tree.cpp.o', 'vision_node.cpp.o'}
    inputs = []
    for value in original_inputs:
        if value.endswith('.o') and Path(value).name in replaced:
            continue
        if value not in inputs:
            inputs.append(value)
    binary = out / 'official_application'
    command = ['/usr/bin/c++', *objects, '-Wl,--start-group', *inputs, '-Wl,--end-group', '-lz', '-o', str(binary)]
    commands.append(command)
    with (out / 'link.log').open('w') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    receipt = {'schema': 'forge.official-application-build/1', 'created_at': datetime.now().astimezone().isoformat(),
               'source_upstream': 'fa4f31ccb4428a9e60e90b4f54eb80499caeb0ca', 'platform_variant': str(root),
               'platform_files': list(changes), 'binary': str(binary), 'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
               'shared_hardware_sim_compatibility': compatibility,
               'optional_sensor_profile': depth_profile,
               'compatibility_patch': str(root / 'firmware16-compatibility.patch'),
               'commands': commands, 'reused_objects': {v: hashlib.sha256(Path(v).read_bytes()).hexdigest() for v in inputs if v.endswith('.o')},
               'reused_platform_objects': reused_compilation,
               'robot_connected': False, 'runtime_verified': False}
    (out / 'build.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return binary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name')
    parser.add_argument('--reuse')
    args = parser.parse_args()
    print(build(args.name, args.reuse))
