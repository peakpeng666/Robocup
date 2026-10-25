"""Exercise the new platform boundary, including failures and byte preservation."""
from concurrent.futures import ThreadPoolExecutor
import json
import socket
import struct
import subprocess

import pytest

from forge import native_wire as wire, paths
from forge.official_application import audit_application, KICK, KICK_LAYOUT


@pytest.fixture(scope='module')
def app_peer(tmp_path_factory):
    directory = tmp_path_factory.mktemp('official-app-wire')
    source = directory / 'peer.cpp'
    source.write_text(r'''
#include "OfficialApplicationWire.h"
#include <sys/un.h>
#include <cstring>
#include <iostream>
int main(int argc, char** argv) {
  if(argc != 2) return 3;
  int fd = socket(AF_UNIX, SOCK_STREAM, 0);
  sockaddr_un address{}; address.sun_family = AF_UNIX;
  std::strcpy(address.sun_path, argv[1]);
  if(connect(fd, reinterpret_cast<sockaddr*>(&address), sizeof(address))) return 4;
  try {
    auto packet = OfficialApplication::receive(fd);
    OfficialApplication::send(fd, packet.data, packet.pixels);
  } catch(const std::exception& e) { std::cerr << e.what(); close(fd); return 2; }
  close(fd); return 0;
}
''')
    binary = directory / 'peer'
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-I',
                    str(paths.FORGE / 'native/simrobot'), str(source), '-o', str(binary)],
                   check=True, capture_output=True, text=True, timeout=45)
    return binary


@pytest.mark.parametrize('failure', [None, 'magic', 'zero_json', 'large_json', 'large_pixels', 'eof', 'json'])
def test_real_wire_fragmentation_and_invalid_input(app_peer, tmp_path, failure):
    endpoint = str(tmp_path / 'app.sock')
    body = json.dumps({'body': ' { "mode" : 1 }\n', 'step': 17}).encode()
    pixels = bytes(range(256)) * 300
    header = [0x41504746, len(body), len(pixels)]
    if failure == 'magic': header[0] = 0
    if failure == 'zero_json': header[1] = 0
    if failure == 'large_json': header[1] = 1048577
    if failure == 'large_pixels': header[2] = 16777217
    if failure == 'json': body = b'!' * len(body)
    message = struct.pack('<III', *header) + body + pixels
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(endpoint); server.listen(); server.settimeout(5)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(subprocess.run, [str(app_peer), endpoint], capture_output=True, timeout=10)
            conn, _ = server.accept()
            with conn:
                conn.settimeout(5)
                if failure:
                    if failure == 'eof': conn.sendall(message[:5])
                    else: conn.sendall(message[:12] + (body if failure == 'json' else b''))
                    conn.shutdown(socket.SHUT_WR)
                else:
                    for i in range(0, len(message), 17): conn.sendall(message[i:i+17])
                    received = bytearray()
                    expected = 12
                    while len(received) < expected:
                        chunk = conn.recv(8192)
                        assert chunk
                        received.extend(chunk)
                        if len(received) >= 12:
                            _, count, size = struct.unpack_from('<III', received)
                            expected = 12 + count + size
                    # The C++ JSON serializer removes whitespace outside strings.
                    _, count, size = struct.unpack_from('<III', received)
                    assert json.loads(received[12:12+count]) == json.loads(body)
                    assert size == len(pixels) and received[12+count:] == pixels
            result = future.result()
            assert result.returncode == (2 if failure else 0), result.stderr


@pytest.mark.parametrize('change', [None, 'body', 'uuid', 'refusal', 'kick', 'stranded'])
def test_application_audit_detects_semantic_changes(tmp_path, change):
    body = ' { "mode" : 1 }\n'
    request = {'event':'SDK_REQUEST', 'step':1, 'uuid':'original-uuid', 'api_id':2000,
               'body':body, 'origin':'official_brain'}
    reply = {'event':'SDK_REPLY', 'step':2, 'uuid':'original-uuid', 'api_id':2000,
             'sequence':1, 'status':400, 'body':'original refusal'}
    kick = {'event':'VISUAL_KICK_INPUT','step':1,'message':{'sec':0,'nanosec':2000000,
            'frame_id':'camera','values':[.1,.2,.3,4.,5.,.6,.7]}}
    events = [request, kick, reply]
    if change == 'uuid': reply['uuid'] = 'changed'
    if change == 'refusal': reply['status'] = 0
    if change == 'stranded': events.append(dict(request, uuid='lost'))
    record = tmp_path / 'events.jsonl'; record.write_text(''.join(json.dumps(e)+'\n' for e in events))
    raw = bytearray()
    for tick in range(2):
        inputs, outputs = {}, {}
        if tick == 1:
            command = (body.strip() if change == 'body' else body).encode()
            inputs[wire.RPC_REQUEST] = wire.RPC_HEADER.pack(1,len(command),1,2000,0)+command+bytes(512-len(command))
            values = kick['message']['values'].copy()
            if change == 'kick': values[3] += 1
            inputs[KICK] = KICK_LAYOUT.pack(1,0,2000000,6,2,*values,b'camera')
            result = b'original refusal'
            outputs[wire.RPC_RESPONSE] = struct.pack('<IIQqq',1,len(result),1,2000,400)+result+bytes(512-len(result))
        raw += wire.Frame(wire.SENSOR,tick,tick*wire.STEP_NS,wire.encode_tlv(inputs),version=2).encode()
        raw += wire.Frame(wire.ACTUATOR,tick,tick*wire.STEP_NS,wire.encode_tlv(outputs),
            controller_time_before=tick*.002,controller_time_after=(tick+1)*.002,version=2).encode()
    for kind in [wire.STOP, wire.STOPPED]:
        raw += wire.Frame(kind,2,2*wire.STEP_NS,bytes(wire.PAYLOAD_BYTES),
            controller_time_before=.004,controller_time_after=.004,version=2).encode()
    native = tmp_path / 'wire.bin'; native.write_bytes(raw)
    result = audit_application(record,native)
    assert result['status'] == ('PASS' if change is None else 'FAIL'), result
    if change is None:
        assert result['request_status_counts'] == {'400':1}
        assert result['brain_requests_dispatched'] == 1 and result['kick_inputs_dispatched'] == 1


def test_camera_info_and_image_have_distinct_types(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(paths.FORGE / 'tools'))
    from run_official_application import configuration
    import yaml
    variant = paths.VARIANTS / 'official-application-upstream-fa4f31c-20261023-a'
    directory = configuration(tmp_path,variant,'robot21',1)
    brain = yaml.safe_load((directory/'brain.yaml').read_text())['brain_node']['ros__parameters']
    vision = yaml.safe_load((directory/'vision.yaml').read_text())
    assert brain['vision']['image_camera_info_topic'] == vision['camera']['intrin_topic']
    assert vision['camera']['intrin_topic'] != vision['camera']['color_topic']
    assert brain['vision']['depth_image_topic'] == vision['camera']['depth_topic']
    geometry = json.loads((directory/'geometry.json').read_text())
    import numpy as np
    optical = np.array([[0,0,1],[-1,0,0],[0,-1,0]])
    extrinsic = np.array(geometry['extrin'])
    for rotation in [np.eye(3), np.array([[0,-1,0],[1,0,0],[0,0,1]]),
                     np.array([[1,0,0],[0,.8,-.6],[0,.6,.8]])]:
        point = rotation @ np.array(geometry['native_published_head_point'])
        camera = point + rotation @ extrinsic[:3,3]
        assert np.allclose(camera, rotation @ np.array(geometry['camera_mount_in_head_link']))
        assert np.allclose(rotation @ extrinsic[:3,:3], rotation @ optical)
    assert geometry['ball_radius'] == .095
    assert geometry['field'][:2] == pytest.approx([13.95,8.95])


def test_official_entry_satisfies_original_localizer_prior_without_moving_baseline(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(paths.FORGE / 'tools'))
    from run_official_application import prepare_scenario
    import xml.etree.ElementTree as ET
    source = paths.BH_LOCAL / 'Config/Scenes/K1/BHumanLocalMatch.ros3'
    document = ET.parse(source)
    world = document.getroot().find('Scene')
    roster = world.find("Compound[@name='robots']")
    original_a = [ET.tostring(robot) for robot in list(roster)[:3]]
    official = ET.SubElement(world, 'Compound', name='officialRobots')
    for robot in list(roster)[3:]:
        roster.remove(robot); official.append(robot)
    scene = tmp_path / 'case.ros3'; document.write(scene)
    schedule = prepare_scenario(scene, 'official-visual-kick')
    world = ET.parse(scene).getroot().find('Scene')
    assert [ET.tostring(robot) for robot in world.find("Compound[@name='robots']")] == original_a
    # Original SelfLocateEnterField's left-entry prior from physical field dimensions.
    for robot in world.find("Compound[@name='officialRobots']"):
        translation = robot.find('Translation').attrib
        assert -13.95 / 2 <= float(translation['x']) <= -1.475
        assert 8.95 / 2 <= float(translation['y']) <= 8.95 / 2 + 1
        assert robot.find('Rotation').get('z') == '-90degree'
    assert '0 gc kickOff secondTeam\n' in schedule
    assert '6000 gc ready\n' in schedule and '22500 gc playing\n' in schedule
    assert '0 ar switchToSet switchToPlaying off\n' in schedule
    assert '22500 ar switchToSet switchToPlaying on\n' in schedule


@pytest.mark.parametrize('mode,body,recent,other_contact,expected', [
    (22,'RFoot',True,False,True), (20,'RFoot',True,False,False),
    (22,'Body',True,False,False), (22,'RFoot',False,False,False),
    (22,'RFoot',True,True,False)])
def test_kick_requires_native_visual_mode_and_isolated_physical_strike(mode,body,recent,other_contact,expected):
    from forge.official_application import qualify_visual_contacts
    contact = dict(robot='RoboCup.officialRobots.robot23',step='100',native_planner=str(mode),
                   body='RoboCup.officialRobots.robot23.'+body,x_m='0',y_m='0')
    contacts = [contact]
    if other_contact: contacts.append(dict(contact,robot='RoboCup.robots.robot3',step='102'))
    motion = [dict(step=95,vx=0,vy=0,x_m=0,y_m=0), dict(step=105,vx=2,vy=0,x_m=.02,y_m=0),
              dict(step=300,vx=1,vy=0,x_m=.5,y_m=0)]
    result=qualify_visual_contacts(contacts,motion,{'robot23':[-1]+[mode]*400},
                                  {'robot23':[60]},{'robot23':[90] if recent else []})
    assert result[0]['qualified'] is expected


def test_platform_workers_overlap_and_propagate_errors(tmp_path):
    source = tmp_path/'workers.cpp'
    source.write_text(r'''
#include "OfficialPlatformWorker.h"
#include <array>
#include <atomic>
#include <cassert>
#include <chrono>
int main() {
  std::array<OfficialApplication::PlatformWorker,3> workers;
  std::atomic<int> entered{0};
  std::atomic<bool> release{false};
  std::array<int,3> completed{};
  for(int i=0;i<3;++i) workers[i].begin([&,i]{
    ++entered; while(!release.load()) std::this_thread::yield(); completed[i]=1;
  });
  auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(2);
  while(entered != 3 && std::chrono::steady_clock::now() < deadline) std::this_thread::yield();
  bool overlapped=entered==3; release=true;
  for(auto& worker:workers) worker.wait();
  assert(overlapped && completed[0] && completed[1] && completed[2]);
  for(int step=0;step<100;++step) {
    for(int i=0;i<3;++i) workers[i].begin([&,i]{++completed[i];});
    for(auto& worker:workers) worker.wait();
    for(int count:completed) assert(count==step+2);
  }
  workers[0].begin([]{throw std::runtime_error("original IO failure");});
  try {workers[0].wait(); return 2;} catch(const std::runtime_error& e) {
    assert(std::string(e.what())=="original IO failure");
  }
}
''')
    binary = tmp_path/'workers'
    subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror','-pthread','-I',
        str(paths.FORGE/'native/simrobot'),str(source),'-o',str(binary)],check=True,capture_output=True,timeout=30)
    subprocess.run([str(binary)],check=True,capture_output=True,timeout=10)


def test_actual_compatibility_methods_wait_for_firmware_and_track_near_ball(tmp_path, monkeypatch):
    """Compile the patched upstream methods, exercise delayed/rejected transitions."""
    import shutil
    monkeypatch.syspath_prepend(str(paths.FORGE / 'tools'))
    from build_official_application import firmware16_compatibility, BASE
    for name in ['robot_client.cpp','brain.cpp','brain_tree.cpp']:
        dest=tmp_path/'src/brain/src'/name; dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(BASE/'src/brain/src'/name,dest)
    firmware16_compatibility(tmp_path)
    tree=(tmp_path/'src/brain/src/brain_tree.cpp').read_text()
    methods=tree[tree.index('rclcpp::Time RLVisionKick::_lastExitTime'):tree.index('NodeStatus StandStill::onStart()')]
    brain=(tmp_path/'src/brain/src/brain.cpp').read_text()
    import re
    pitch=re.findall(r'obj\.pitchToRobot = ([^;]+);',brain)
    assert len(pitch)==2
    source=tmp_path/'compat.cpp'
    source.write_text(r'''
#include <cassert>
#include <cmath>
constexpr int RCL_ROS_TIME=1;
namespace rclcpp {struct Time {long long ns; Time(long long n=0,int=1):ns(n){} Time(int s,int n,int):ns(s*1000000000LL+n){} long long nanoseconds() const{return ns;}};}
enum class NodeStatus {RUNNING,SUCCESS,FAILURE};
struct Data {bool shouldExitRLVisionKick=false,tmImInVisualKick=true,ballDetected=true,lose_ball=false; struct {double range=1;} ball; double tmMyCost=1; int currentRobotModeIndex=20;};
struct Client {int starts=0,walks=0,heads=0; double pitch=0; void robocupWalk(){++walks;} void RLVisionKick(){++starts;} void moveHead(double p,double){++heads;pitch=p;} void setVelocity(double,double,double){};};
struct Tree {bool out=false; template<class T>T getEntry(const char*){return out;}};
struct Clock {long long ms=100; rclcpp::Time now(){return rclcpp::Time(ms*1000000);}};
struct Brain {Data d;Client c;Tree t;Clock clock;Data* data=&d;Client* client=&c;Tree* tree=&t;Clock* get_clock(){return &clock;} double msecsSince(rclcpp::Time t){return (clock.now().ns-t.ns)/1000000.;}};
struct RLVisionKick {
 Brain* brain; rclcpp::Time _startTime,_headScanStartTime,_decelStartTime;
 bool _isDecelerating=false,_visionKickStarted=false,_pendingRobocupWalk=false;double _decelDurationMs=500;
 static rclcpp::Time _lastExitTime;
 struct Input {double value(){return 1500.;}};template<class T>Input getInput(const char*){return {};}
 NodeStatus onStart();NodeStatus onRunning();void onHalted();static bool isMinIntervalSatisfied(double);void recordExitTime();void startDecelerate(double);bool stepDecelerate();
};
'''+methods+r'''
int main(){
 Brain b;RLVisionKick kick{&b};assert(kick.onStart()==NodeStatus::RUNNING);
 b.clock.ms=600;kick.onRunning();assert(b.c.starts==1 && b.c.heads==0);
 b.clock.ms=1600;kick.onRunning();assert(b.c.heads==0 && b.c.walks==0);
 b.d.currentRobotModeIndex=22;b.clock.ms=1800;kick.onRunning();assert(b.c.heads==1 && b.c.pitch==.4);
 b.clock.ms=2110;kick.onRunning();assert(b.c.pitch==.7);
 b.d.lose_ball=true;b.clock.ms=2500;kick.onRunning();b.clock.ms=3000;
 assert(kick.onRunning()==NodeStatus::RUNNING && b.c.walks==1);
 b.clock.ms=3500;assert(kick.onRunning()==NodeStatus::RUNNING && b.c.walks==1);
 // A second instance cannot mistake the outgoing visual mode for a new start.
 RLVisionKick stale{&b};assert(stale.onStart()==NodeStatus::FAILURE && b.c.starts==1);
 b.d.currentRobotModeIndex=20;b.clock.ms=4010;
 assert(kick.onRunning()==NodeStatus::SUCCESS && b.c.walks==1 && !b.d.tmImInVisualKick);
 Brain stuck;RLVisionKick exitTimeout{&stuck};exitTimeout.onStart();
 stuck.clock.ms=600;exitTimeout.onRunning();stuck.d.currentRobotModeIndex=22;
 stuck.clock.ms=1800;exitTimeout.onRunning();stuck.d.lose_ball=true;
 stuck.clock.ms=2000;exitTimeout.onRunning();stuck.clock.ms=2500;exitTimeout.onRunning();
 stuck.clock.ms=6100;assert(exitTimeout.onRunning()==NodeStatus::FAILURE && stuck.c.walks==1);
 Brain dropped;RLVisionKick lostMode{&dropped};lostMode.onStart();
 dropped.clock.ms=600;lostMode.onRunning();dropped.d.currentRobotModeIndex=22;
 dropped.clock.ms=1800;lostMode.onRunning();dropped.d.currentRobotModeIndex=20;
 dropped.clock.ms=2000;assert(lostMode.onRunning()==NodeStatus::FAILURE && !dropped.d.tmImInVisualKick);
 Brain rejected;RLVisionKick second{&rejected};second.onStart();rejected.clock.ms=600;second.onRunning();
 rejected.clock.ms=3700;assert(second.onRunning()==NodeStatus::SUCCESS);
 assert(rejected.c.heads==0 && rejected.c.walks==1 && !rejected.d.tmImInVisualKick);
 struct Config {double get_robot_height(){return .8;}} cfg;auto* config=&cfg;
 struct {double range,pitchToRobot;} obj;
 for(double range:{0.,.2,.8,2.}) {obj.range=range;
'''+''.join('obj.pitchToRobot = '+p+';assert(std::isfinite(obj.pitchToRobot));\n' for p in pitch)+r'''
 assert(std::abs(obj.pitchToRobot-std::atan2(.8,range))<1e-12);}
}
''')
    # initializer_list is needed only by this test's range table.
    source.write_text('#include <initializer_list>\n'+source.read_text())
    binary=tmp_path/'compat'
    subprocess.run(['c++','-std=c++17',str(source),'-o',str(binary)],check=True,capture_output=True,timeout=30)
    subprocess.run([str(binary)],check=True,capture_output=True,timeout=10)


def test_rgbd_ground_assumption_rejects_elevated_heads_but_preserves_missing_depth(tmp_path):
    source=tmp_path/'depth.cpp'
    source.write_text(r'''
#include "GroundBallDepthCheck.h"
#include <cassert>
int main() {
  std::vector<float> depth(10000,1.8f);
  double r[9]={1,0,0,0,0,0,0,-std::cos(.3),-std::sin(.3)},t[3]={0,0,.8};
  auto check=[&](int ymin,int ymax){return OfficialVision::checkGroundBall(depth.data(),100,100,100,
    45,ymin,55,ymax,100,100,50,50,r,t,.51,5.8,-.15,.345);};
  auto ball=check(55,65);assert(ball.observed && ball.consistent && ball.height>.05 && ball.height<.15);
  std::fill(depth.begin(),depth.end(),2.4f);auto head=check(15,25);
  assert(head.observed && !head.consistent && head.height>.7);
  for(float unavailable:{0.f,6.f,NAN}) {
    std::fill(depth.begin(),depth.end(),unavailable);auto missing=check(15,25);
    assert(!missing.observed && missing.consistent);
  }
}
''')
    binary=tmp_path/'depth'
    subprocess.run(['c++','-std=c++17','-I',str(paths.FORGE/'native'),str(source),'-o',str(binary)],
                   check=True,capture_output=True,timeout=30)
    subprocess.run([str(binary)],check=True,capture_output=True,timeout=10)


def test_lossless_float_byteplanes_restore_all_bits(tmp_path):
    import gzip
    from forge.official_application import read_depth_evidence
    raw=bytes(range(256))*100
    planes=b''.join(raw[i::4] for i in range(4))
    path=tmp_path/'sample.depth-f32-byteplanes.gz';path.write_bytes(gzip.compress(planes))
    assert read_depth_evidence(path)==raw
    assert read_depth_evidence(tmp_path/'sample.depth-f32')==raw
    # A retained raw frame takes precedence, and a missing frame fails loudly.
    (tmp_path/'sample.depth-f32').write_bytes(b'original raw')
    assert read_depth_evidence(tmp_path/'sample.depth-f32')==b'original raw'
    with pytest.raises(FileNotFoundError): read_depth_evidence(tmp_path/'missing.depth-f32')


@pytest.mark.parametrize('mode_at_end,qualified', [(22,True),(20,False)])
def test_continuous_contact_counts_once_and_requires_mode_throughout(mode_at_end,qualified):
    from forge.official_application import qualify_visual_contacts
    contact=dict(robot='RoboCup.officialRobots.robot23',step='100',native_planner='22',
                 body='RoboCup.officialRobots.robot23.RFoot',x_m='0',y_m='0')
    contacts=[dict(contact,step=str(step)) for step in (100,100,103,106)]
    motion=[dict(step=95,vx=0,vy=0,x_m=0,y_m=0),dict(step=110,vx=2,vy=0,x_m=.02,y_m=0),
            dict(step=300,vx=1,vy=0,x_m=.5,y_m=0)]
    modes=[22]*401; modes[105]=mode_at_end
    result=qualify_visual_contacts(contacts,motion,{'robot23':modes},{'robot23':[60]},{'robot23':[90]})
    assert len(result)==1 and result[0]['end_step']==106
    assert result[0]['qualified'] is qualified
    if not qualified: assert 'visual_controller_did_not_cover_whole_contact' in result[0]['reasons']


def test_authenticity_inventory_merges_and_rejects_conflicting_hashes(tmp_path):
    from tools.audit_official_authenticity import load_inventory
    entries=[dict(path='./booster/bin/mck',sha256='original',size=12),
             dict(path='./booster/lib/motion/native.so',sha256='module',size=34)]
    paths=[]
    for i,entry in enumerate(entries):
        path=tmp_path/f'{i}.jsonl'; path.write_text(json.dumps(entry)+'\n'); paths.append(path)
    assert set(load_inventory(paths))=={'bin/mck','lib/motion/native.so'}
    assert load_inventory(paths+[paths[0]])['bin/mck']['sha256']=='original'
    entries[1].update(path='./booster/bin/mck',sha256='changed',size=12)
    paths[1].write_text(json.dumps(entries[1])+'\n')
    with pytest.raises(ValueError,match='conflicting'): load_inventory(paths)
