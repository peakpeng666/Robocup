import subprocess
from forge import paths


def test_actual_v20_to_v12_projection_preserves_restart_movement_permissions(tmp_path):
    source=tmp_path/'referee.cpp'
    source.write_text(r'''
#include "OfficialGameState.h"
#include "OfficialPortContract.h"
#include <cassert>
using OfficialApplication::projectGameState;
int main() {
  for(int type=1;type<=6;++type) {
    const auto own=projectGameState(3,0,false,type,70,70);
    const auto opponent=projectGameState(3,0,false,type,5,70);
    assert(own.state==3 && own.secondary==0 && own.ownActiveRestart);
    assert(opponent.state==3 && opponent.secondary>=4 && opponent.phase==1 && !opponent.ownActiveRestart);
    // STOP/SET remain genuine standstill; READY allows original positioning.
    assert(projectGameState(3,0,true,type,70,70).phase==0);
    assert(projectGameState(1,0,false,type,70,70).phase==1);
    assert(projectGameState(2,0,false,type,70,70).phase==2);
  }
  for(int state=0;state<=4;++state) {
    const auto normal=projectGameState(state,0,false,0,70,70);
    assert(normal.state==state && normal.secondary==0 && !normal.ownActiveRestart);
  }
  assert(projectGameState(3,0,true,0,70,70).secondary==3);
  assert(projectGameState(3,3,false,0,70,70).secondary==3);
  bool failed=false;try{projectGameState(3,0,false,7,70,70);}catch(...){failed=true;}
  assert(failed);
  const auto normalized=OfficialApplication::normalizeGcV20(3,0,false,6,5);
  assert(normalized.at("execution")=="active" && normalized.at("restart")=="corner");
  // A future source adapter can supply the same semantic input without v20 fields.
  auto projected=OfficialApplication::projectDemoHlV12(normalized,70);
  assert(projected.phase==1 && projected.secondary==7);
  auto contract=OfficialApplication::portContract();
  OfficialApplication::requirePortContract(contract);
  contract["clock"]["step_ns"]=10000000;
  failed=false;try{OfficialApplication::requirePortContract(contract);}catch(...){failed=true;}
  assert(failed);
}
''')
    binary=tmp_path/'referee'
    subprocess.run(['c++','-std=c++17','-I',str(paths.FORGE/'native/simrobot'),str(source),'-o',str(binary)],
                   check=True,capture_output=True,timeout=30)
    subprocess.run([str(binary)],check=True,capture_output=True,timeout=10)
