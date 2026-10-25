"""Test command ingress against an authored C++ RPC double, never vendor code."""
from __future__ import annotations
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from forge.native_wire import decode_tlv, encode_tlv

REQUEST = 0x46470001
REPLY = 0x46478001
RPC = struct.Struct("<IIQqq512s")
FAKE = r'''
#include <booster/robot/rpc/request.hpp>
#include <booster/robot/rpc/response.hpp>
using namespace booster::robot;
bool initialized=false;
extern "C" void init(void*,const void*,const void*) __asm__("_ZN6module3rsm19BoosterApiRpcServer4InitERKSt10shared_ptrINS0_11ModeManagerEERKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE");
void init(void*,const void*,const void*) {initialized=true;}
extern "C" Response handle(void*,const Request&) __asm__("_ZN6module3rsm19BoosterApiRpcServer13HandleRequestERKN7booster5robot7RequestE");
Response handle(void*,const Request& request) {
  return Response(ResponseHeader(initialized ? (request.GetHeader().GetApiId()==2000?503:0) : 999),request.GetBody());
}
'''
RUNNER = r'''
#include <dlfcn.h>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <cstdlib>
int main(int argc,char** argv) {
  if(argc!=2 || !dlopen(argv[1],RTLD_NOW|(std::getenv("FAKE_RPC_LOCAL")?RTLD_LOCAL:RTLD_GLOBAL))) return 90;
  auto init=reinterpret_cast<void(*)(void*,const void*,const void*)>(dlsym(RTLD_DEFAULT,"_ZN6module3rsm19BoosterApiRpcServer4InitERKSt10shared_ptrINS0_11ModeManagerEERKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE"));
  auto sensor=reinterpret_cast<int(*)(const uint8_t*,size_t,uint64_t)>(dlsym(RTLD_DEFAULT,"forge_fw16_rpc_sensor"));
  auto actuator=reinterpret_cast<int(*)(uint8_t*,size_t)>(dlsym(RTLD_DEFAULT,"forge_fw16_rpc_actuator"));
  int instance;
  if(!init||!sensor||!actuator) return 91;
  init(&instance,nullptr,nullptr);
  uint8_t data[4000];
  for(uint64_t tick=0;std::fread(data,1,sizeof(data),stdin)==sizeof(data);++tick) {
    if(sensor(data,sizeof(data),tick)) return 72;
    std::memset(data,0,sizeof(data)); unsigned length=8; std::memcpy(data,&length,4);
    if(actuator(data,sizeof(data))) return 73;
    if(std::fwrite(data,1,sizeof(data),stdout)!=sizeof(data)) return 74;
  }
}
'''

@unittest.skipUnless(shutil.which("g++"), "native test compiler unavailable")
class NativeRpcTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="fw16-rpc-test-")
        cls.work = Path(cls.temp.name)
        forge = Path(__file__).resolve().parents[1]
        include = forge.parent / "booster/booster_robotics_sdk/include"
        (cls.work / "fake.cpp").write_text(FAKE)
        (cls.work / "runner.cpp").write_text(RUNNER)
        cls.lib, cls.fake, cls.runner = [cls.work / name for name in ("librpc.so", "libfake.so", "runner")]
        for source,out,shared in [(forge/"native/booster_fw16_rpc.cpp",cls.lib,True),
                                  (cls.work/"fake.cpp",cls.fake,True),(cls.work/"runner.cpp",cls.runner,False)]:
            command = ["g++","-std=c++17","-I",str(include),str(source),"-o",str(out),"-ldl"]
            if shared:
                command += ["-shared","-fPIC"]
            subprocess.run(command,check=True,capture_output=True,text=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_payload(self, raw, *, local=False, library=None):
        env = {**os.environ,"LD_PRELOAD":str(self.lib)}
        if local:
            env.update(FAKE_RPC_LOCAL="1",FORGE_BOOSTER_RPC_LIBRARY=str(library or self.fake))
        return subprocess.run([str(self.runner),str(self.fake)], input=raw,
                              env=env,capture_output=True,timeout=5)

    def test_original_rpc_loaded_in_a_local_scope_is_resolved_explicitly(self):
        result=self.run_payload(self.command(2017),local=True)
        self.assertEqual(result.returncode,0,result.stderr.decode())
        _,items=decode_tlv(result.stdout)
        self.assertEqual(RPC.unpack(items[REPLY])[4],0)
        self.assertIn(b"original_handle_request=1",result.stderr)

    def test_explicit_rpc_library_must_already_be_loaded(self):
        result=self.run_payload(self.command(2017),local=True,library=self.work/"missing.so")
        self.assertEqual(result.returncode,71)
        self.assertIn(b"not already loaded",result.stderr)

    def command(self,api,body=b"",sequence=1):
        return encode_tlv({REQUEST:RPC.pack(1,len(body),sequence,api,0,body)})

    def test_original_request_response_abi_preserves_body_and_refusal(self):
        first=b'{"mode":1}'
        second=b'{"vx":0.2,"vy":0,"vyaw":-0.1}'
        result=self.run_payload(self.command(2000,first)+self.command(2001,second,2))
        self.assertEqual(result.returncode,0,result.stderr.decode())
        for i,(api,body,status) in enumerate([(2000,first,503),(2001,second,0)]):
            _,items=decode_tlv(result.stdout[i*4000:(i+1)*4000])
            version,size,sequence,actual_api,actual_status,actual_body=RPC.unpack(items[REPLY])
            self.assertEqual((version,size,sequence,actual_api,actual_status),(1,len(body),i+1,api,status))
            self.assertEqual(actual_body[:size],body)

    def test_no_command_no_rpc_reply(self):
        result=self.run_payload(encode_tlv({}))
        self.assertEqual(result.returncode,0,result.stderr.decode())
        self.assertEqual(decode_tlv(result.stdout),(0,{}))

    def test_replay_is_not_dispatched_twice(self):
        result=self.run_payload(self.command(2008)+self.command(2008))
        self.assertEqual(result.returncode,72)
        self.assertEqual(len(result.stdout),4000)
        self.assertIn(b"sequence mismatch",result.stderr)

    def test_unknown_api_and_malformed_parameters_rejected_before_dispatch(self):
        for api,body in [(2020,b'{}'),(2001,b'{"vx":1}'),(2000,b'{"mode":3}'),
                         (2042,b'{"gait_type":9}'),(2004,b'{"pitch":"NaN","yaw":0}')]:
            with self.subTest(api=api,body=body):
                result=self.run_payload(self.command(api,body))
                self.assertEqual(result.returncode,72)
                self.assertEqual(result.stdout,b"")

    def test_audited_modes_gaits_and_head_dispatch(self):
        bodies=[(2000,b'{"mode":4}'),(2004,b'{"pitch":0.1,"yaw":-0.2}'),
                (2042,b'{"gait_type":2}'),(2038,b'{"start":true,"version":1}'),(2025,b'{"mode":2}')]
        result=self.run_payload(b''.join(self.command(api,body,i+1) for i,(api,body) in enumerate(bodies)))
        self.assertEqual(result.returncode,0,result.stderr.decode())
        self.assertEqual(len(result.stdout),4000*len(bodies))

if __name__=="__main__":
    unittest.main()
