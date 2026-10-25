"""Exercise our IO interposer with an authored fake library, never vendor code."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import tempfile
import unittest

from forge.native_wire import Frame, SENSOR, STEP_NS, STOP, STOPPED, actuator_payload, receive, sensor_payload


FAKE = r'''
#include "booster_fw16_wire.h"
#include <cstring>
#include <cstdlib>
extern "C" unsigned char buf[4000] __asm__("_ZN12rs_sdk_utils17shared_mem_bufferE");
unsigned char buf[4000];
struct Clock { void* vptr; double seconds; } clockValue{};
struct Handle { void* object; void* control; ~Handle() {} };
extern "C" Handle getTimer() __asm__("_ZN12rs_sdk_utils8GetTimerEv");
Handle getTimer() { return {&clockValue, nullptr}; }
extern "C" void release(void*) __asm__("_ZNSt10shared_ptrIN5utils5timer15SimulationTimerEED1Ev");
void release(void*) {}
extern "C" double getTime(const void*) __asm__("_ZNK5utils5timer15SimulationTimer7GetTimeEv");
double getTime(const void* p) { return static_cast<const Clock*>(p)->seconds; }
extern "C" void timer(int) __asm__("_ZN12rs_sdk_utils11UpdateTimerEi");
void timer(int ms) { if(!std::getenv("FAKE_STOP_CLOCK")) clockValue.seconds += ms * .001; }
float position;
extern "C" void output(void*) __asm__("_ZN6module16rs_sdk_interface11RsSdkOutput6UpdateEv");
void output(void*) {
  unsigned at=8,total;
  std::memcpy(&total,buf,4);
  while(at<total) {
    unsigned key,size;
    std::memcpy(&key,buf+at,4); std::memcpy(&size,buf+at+4,4);
    if(key==6) std::memcpy(&position,buf+at+8,4);
    at += 8+size;
  }
}
extern "C" void input(void*) __asm__("_ZN6module16rs_sdk_interface10RsSdkInput6UpdateEv");
void input(void*) {
  std::memset(buf,0,sizeof(buf));
  unsigned words[]={2140,1,5,2112};
  std::memcpy(buf,words,sizeof(words));
  for(unsigned i=0;i<22;++i) {
    ForgeFw16Motor motor{};
    motor.target_position=position+1+i; motor.kp=30; motor.kd=2;
    std::memcpy(buf+16+i*sizeof(motor),&motor,sizeof(motor));
  }
  unsigned mode[]={9,4,7}; std::memcpy(buf+2128,mode,sizeof(mode));
  timer(std::getenv("FAKE_BAD_STEP") ? 4 : 2);
}
'''

RUNNER = r'''
#include <dlfcn.h>
#include <cstdlib>
int main(int argc,char** argv) {
  if(argc!=3 || !dlopen(argv[1],RTLD_NOW|RTLD_GLOBAL)) return 90;
  using Fn=void(*)(void*);
  auto output=reinterpret_cast<Fn>(dlsym(RTLD_DEFAULT,"_ZN6module16rs_sdk_interface11RsSdkOutput6UpdateEv"));
  auto input=reinterpret_cast<Fn>(dlsym(RTLD_DEFAULT,"_ZN6module16rs_sdk_interface10RsSdkInput6UpdateEv"));
  if(!output || !input) return 91;
  for(int i=0;i<std::atoi(argv[2]);++i) {output(nullptr);input(nullptr);}
}
'''

PHYSICS = r'''
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <cstddef>
bool pending=false;
uint8_t* item(uint8_t* p,uint32_t key) {
  uint32_t length;std::memcpy(&length,p,4);
  for(uint32_t i=8;i<length;) {
    uint32_t k,n;std::memcpy(&k,p+i,4);std::memcpy(&n,p+i+4,4);
    if(k==key)return p+i+8;i+=8+n;
  }
  return nullptr;
}
extern "C" bool forgePhysicsSensors(uint8_t* p,size_t n) {
  if(n!=4000||pending||std::getenv("FAKE_PHYSICS_FAIL"))return false;
  auto q=item(p,6);if(!q)return false;
  float value;std::memcpy(&value,q,4);value+=10;std::memcpy(q,&value,4);
  pending=true;return true;
}
extern "C" bool forgePhysicsActuators(uint8_t* p,size_t n) {
  if(n!=4000||!pending)return false;
  auto q=item(p,5);if(!q)return false;
  float value;std::memcpy(&value,q+32,4);value-=10;std::memcpy(q+32,&value,4);
  uint32_t length;std::memcpy(&length,p,4);
  uint32_t tag=0x46500002,size=176,next=length+184;
  std::memcpy(p+length,&tag,4);std::memcpy(p+length+4,&size,4);
  for(unsigned i=0;i<22;++i){double limit=36;std::memcpy(p+length+8+i*8,&limit,8);}
  std::memcpy(p,&next,4);pending=false;return true;
}
extern "C" const char* forgePhysicsGetError(){return "authored physics hook failure";}
'''


@unittest.skipUnless(shutil.which("g++"), "native test compiler unavailable")
class NativeInterposerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="fw16-bridge-test-")
        cls.work = Path(cls.temp.name)
        native = Path(__file__).resolve().parents[1] / "native"
        (cls.work / "fake.cpp").write_text(FAKE)
        (cls.work / "runner.cpp").write_text(RUNNER)
        (cls.work / "physics.cpp").write_text(PHYSICS)
        cls.lib = cls.work / "libbridge.so"
        cls.fake = cls.work / "libfake.so"
        cls.runner = cls.work / "runner"
        cls.physics = cls.work / "libphysics.so"
        for source, out, shared in (
            (native / "booster_fw16_interposer.cpp", cls.lib, True),
            (cls.work / "fake.cpp", cls.fake, True),
            (cls.work / "runner.cpp", cls.runner, False),
            (cls.work / "physics.cpp", cls.physics, True),
        ):
            command = ["g++", "-std=c++17", "-I", str(native), str(source), "-o", str(out), "-ldl"]
            if shared:
                command += ["-shared", "-fPIC"]
            subprocess.run(command, check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.path = str(self.work / (self._testMethodName + ".sock"))
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.path)
        self.server.listen(1)
        self.server.settimeout(3)

    def tearDown(self):
        self.server.close()
        Path(self.path).unlink(missing_ok=True)

    def launch(self, ticks=1, **extra):
        env = {**os.environ, "LD_PRELOAD": str(self.lib), "FORGE_BOOSTER_SOCKET": self.path,
               "FORGE_BOOSTER_RS_LIBRARY": str(self.fake), "FORGE_BOOSTER_TIMEOUT_MS": "1000", **extra}
        proc = subprocess.Popen([str(self.runner), str(self.fake), str(ticks)], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        peer, _ = self.server.accept()
        peer.settimeout(3)
        return proc, peer

    def frame(self, tick=0):
        payload = sensor_payload([.125]*22, [0.]*22, [0.]*22, acceleration=(0,0,9.81),
                                 rpy=(0,0,0), gyro=(0,0,0), count=tick)
        return Frame(SENSOR, tick, tick * STEP_NS, payload)

    def test_two_original_updates_and_actual_clock_with_fragmentation(self):
        proc, peer = self.launch(2)
        with peer:
            for tick in range(2):
                raw = self.frame(tick).encode()
                for begin in range(0, len(raw), 37):
                    peer.sendall(raw[begin:begin+37])
                reply = receive(peer)
                self.assertEqual(reply.tick, tick)
                self.assertAlmostEqual(reply.controller_time_before, tick * .002)
                self.assertAlmostEqual(reply.controller_time_after, (tick+1) * .002)
                output = actuator_payload(reply.payload)
                self.assertEqual(output["mode"], 7)
                self.assertEqual(output["q_target"], [1.125+i for i in range(22)])
        _, err = proc.communicate(timeout=3)
        self.assertEqual(proc.returncode, 0, err.decode())

    def test_rejects_replayed_tick(self):
        proc, peer = self.launch(2)
        with peer:
            peer.sendall(self.frame().encode())
            receive(peer)
            peer.sendall(self.frame().encode())
        _, err = proc.communicate(timeout=3)
        self.assertEqual(proc.returncode, 70)
        self.assertIn(b"sensor header/tick/time mismatch", err)

    def test_serial_wire_requires_explicit_domain_selection(self):
        proc,peer=self.launch()
        frame=self.frame()
        with peer:
            peer.sendall(Frame(SENSOR,frame.tick,frame.time_ns,frame.payload,version=2).encode())
        _,err=proc.communicate(timeout=3)
        self.assertEqual(proc.returncode,70)
        self.assertIn(b"sensor header/tick/time mismatch",err)

    def test_serial_wire_calls_both_conversion_hooks_at_the_native_boundary(self):
        proc,peer=self.launch(LD_PRELOAD=f'{self.lib}:{self.physics}',FORGE_BOOSTER_SERIAL_IO='1')
        frame=self.frame()
        with peer:
            peer.sendall(Frame(SENSOR,0,0,frame.payload,version=2).encode())
            reply=receive(peer)
            self.assertEqual(reply.version,2)
            result=actuator_payload(reply.payload,version=2)
            self.assertAlmostEqual(result['q_target'][0],1.125)
            self.assertEqual(result['torque_limits'],[36.]*22)
        _,err=proc.communicate(timeout=3)
        self.assertEqual(proc.returncode,0,err.decode())

    def test_serial_conversion_failure_cannot_send_actuator_output(self):
        proc,peer=self.launch(LD_PRELOAD=f'{self.lib}:{self.physics}',FORGE_BOOSTER_SERIAL_IO='1',FAKE_PHYSICS_FAIL='1')
        frame=self.frame()
        with peer:
            peer.sendall(Frame(SENSOR,0,0,frame.payload,version=2).encode())
            self.assertEqual(peer.recv(1),b'')
        _,err=proc.communicate(timeout=3)
        self.assertEqual(proc.returncode,70)
        self.assertIn(b"authored physics hook failure",err)

    def test_serial_mode_cannot_start_without_the_complete_adapter(self):
        result=subprocess.run([str(self.runner),str(self.fake),'1'],capture_output=True,timeout=3,
                              env={**os.environ,'LD_PRELOAD':str(self.lib),'FORGE_BOOSTER_SERIAL_IO':'1'})
        self.assertEqual(result.returncode,70)
        self.assertIn(b"requires the complete explicit physics adapter",result.stderr)

    def test_acknowledged_stop_without_an_extra_native_update(self):
        proc, peer = self.launch(10)
        with peer:
            peer.sendall(self.frame().encode())
            receive(peer)
            peer.sendall(Frame(STOP, 1, STEP_NS, bytes(4000)).encode())
            reply = receive(peer)
            self.assertEqual(reply.kind, STOPPED)
            self.assertEqual(reply.controller_time_before, .002)
            self.assertEqual(reply.controller_time_after, .002)
        _, err = proc.communicate(timeout=3)
        self.assertEqual(proc.returncode, 0, err.decode())
        self.assertIn(b"BRIDGE_STOPPED tick=1", err)

    def test_stop_with_hidden_payload_is_rejected(self):
        proc, peer = self.launch(10)
        with peer:
            peer.sendall(Frame(STOP, 0, 0, self.frame().payload).encode())
        _, err = proc.communicate(timeout=3)
        self.assertEqual(proc.returncode, 70)
        self.assertIn(b"STOP packet must not carry", err)

    def test_rejects_wrong_native_timer_step(self):
        proc, peer = self.launch(FAKE_BAD_STEP="1")
        with peer:
            peer.sendall(self.frame().encode())
        _, err = proc.communicate(timeout=3)
        self.assertEqual(proc.returncode, 70)
        self.assertIn(b"outside one 2ms physical tick", err)

    def test_detects_original_clock_did_not_advance(self):
        proc, peer = self.launch(FAKE_STOP_CLOCK="1")
        with peer:
            peer.sendall(self.frame().encode())
        _, err = proc.communicate(timeout=3)
        self.assertEqual(proc.returncode, 70)
        self.assertIn(b"native timer actual time disagrees", err)

    def test_rejects_truncated_required_motor_array(self):
        proc, peer = self.launch()
        raw = bytearray(self.frame().encode())
        # Third item ID6 follows IMU(168 bytes) and joint count(12 bytes).
        struct.pack_into("<i", raw, 64 + 8 + 168 + 12 + 4, 2111)
        with peer:
            peer.sendall(raw)
        _, err = proc.communicate(timeout=3)
        self.assertEqual(proc.returncode, 70)
        self.assertIn(b"TLV", err)


if __name__ == "__main__":
    unittest.main()
