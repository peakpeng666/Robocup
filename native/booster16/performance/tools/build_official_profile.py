import pathlib,shlex,os,subprocess
r=pathlib.Path('/workspace/shared/benchmark-build/official-profile');env=os.environ.copy();env['LD_LIBRARY_PATH']='/workspace/shared/build-deps/root/usr/lib/x86_64-linux-gnu';env['PATH']='/workspace/shared/build-deps/root/usr/bin:'+env['PATH']
def flags(build,target):
 d={}
 for line in (build/f'CMakeFiles/{target}.dir/flags.make').read_text().splitlines():
  if ' = ' in line:k,v=line.split(' = ',1);d[k]=shlex.split(v)
 return d['CXX_DEFINES']+d['CXX_INCLUDES']+d['CXX_FLAGS']
b=pathlib.Path('/workspace/shared/simrobot-build/build');mapping={}
for rel,marker,label in [('Simulation/Simulation.cpp','void Simulation::doSimulationStep()\n{','official_physics_including_actuator_collision'),('Simulation/Sensors/Camera.cpp','void Camera::CameraSensor::updateValue()\n{','official_camera_direct_render_readback')]:
 src=pathlib.Path('/workspace/shared/simrobot-build/source/Src/SimRobotCore3')/rel;s=src.read_text();s='#include "/workspace/shared/benchmark-build/profile/source/BenchStage.h"\n'+s.replace(marker,marker+'\n BENCH_SCOPE("'+label+'");',1);out=r/'obj'/src.name;out.write_text(s);obj=out.with_suffix('.o');args=['g++']+flags(b,'SimRobotCore3')+['-include',str(b/'CMakeFiles/SimRobotCore3.dir/cmake_pch.hxx'),'-iquote',str(src.parent),'-c',str(out),'-o',str(obj)];subprocess.run(args,cwd=b,env=env,check=True);mapping['CMakeFiles/SimRobotCore3.dir/workspace/shared/simrobot-build/source/Src/SimRobotCore3/'+rel+'.o']=str(obj)
args=shlex.split((b/'CMakeFiles/SimRobotCore3.dir/link.txt').read_text());args[args.index('-o')+1]=str(r/'bin/libSimRobotCore3.so');args=[mapping.get(a,a) for a in args];args=[a.replace('CMakeFiles/SimRobotCore3.dir/link.d',str(r/'core-link.d')) for a in args];subprocess.run(args,cwd=b,env=env,check=True)
b=pathlib.Path('/workspace/shared/simrobot-build/plugin');obj=r/'obj/BoosterK1Policy.o';subprocess.run(['g++']+flags(b,'BoosterK1Policy')+['-c',str(r/'plugin/BoosterK1Policy.cpp'),'-o',str(obj)],cwd=b,env=env,check=True)
args=shlex.split((b/'CMakeFiles/BoosterK1Policy.dir/link.txt').read_text());args[args.index('-o')+1]=str(r/'bin/libBoosterK1Policy.so');args=[str(obj) if a=='CMakeFiles/BoosterK1Policy.dir/BoosterK1Policy.cpp.o' else a for a in args];args=[a.replace('CMakeFiles/BoosterK1Policy.dir/link.d',str(r/'plugin-link.d')) for a in args];subprocess.run(args,cwd=b,env=env,check=True)
orig=pathlib.Path('/workspace/shared/simrobot-build/source/Build/Linux/SimRobot/Release')
for p in orig.iterdir():
 dest=r/'bin'/p.name
 if p.name=='SimRobot':dest.write_bytes(p.read_bytes());dest.chmod(0o755)
 elif not dest.exists():dest.symlink_to(p)
print('OFFICIAL_PROFILE_BUILD_COMPLETE')
