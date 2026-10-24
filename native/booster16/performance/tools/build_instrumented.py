import pathlib,json,shlex,subprocess,os,difflib
root=pathlib.Path('/workspace/shared/benchmark-build/profile');build=pathlib.Path('/workspace/shared/bhuman-build/build');entries=json.loads((build/'compile_commands.json').read_text());mapping={};patches=[]
jobs={
 '/Simulation/Simulation.cpp': [('void Simulation::doSimulationStep()\n{','void Simulation::doSimulationStep()\n{\n  BENCH_SCOPE("physics_step_including_actuator_collision");')],
 '/Simulation/Sensors/Camera.cpp': [('void Camera::CameraSensor::updateValue()\n{','void Camera::CameraSensor::updateValue()\n{\n  BENCH_SCOPE("camera_direct_render_readback");'),('  // allocate buffer\n  const unsigned int imageWidth = camera->imageWidth;', '  // allocate buffer\n  const unsigned int imageWidth = camera->imageWidth;')],
 '/SimulatedRobot3D.cpp':[('void SimulatedRobot3D::getImage(CameraImage& cameraImage, CameraInfo& cameraInfo)\n{','void SimulatedRobot3D::getImage(CameraImage& cameraImage, CameraInfo& cameraInfo)\n{\n  BENCH_SCOPE("camera_getImage_including_rgb_conversion");')],
 '/RobotBallPerceptor.cpp':[('compiled.apply();','{ BENCH_SCOPE("vision_robot_ball_nn_apply"); compiled.apply(); }')],
 '/WalkingEngine.cpp':[('engine.walkPolicy.apply();','{ BENCH_SCOPE("motion_walk_nn_apply"); engine.walkPolicy.apply(); }'),('policy.apply();','{ BENCH_SCOPE("motion_kick_nn_apply"); policy.apply(); }')],
}
env=os.environ.copy();env['LD_LIBRARY_PATH']='/workspace/shared/build-deps/root/usr/lib/x86_64-linux-gnu';env['PATH']='/workspace/shared/build-deps/root/usr/bin:'+env['PATH']
for suffix,edits in jobs.items():
 item=next(e for e in entries if e['file'].endswith(suffix));src=pathlib.Path(item['file']);old=src.read_text();s=old
 for a,b in edits:
  if a not in s:raise RuntimeError('missing '+a)
  s=s.replace(a,b,1)
 if suffix.endswith('/Camera.cpp'):
  a='  if(lastSimulationStep == Simulation::simulation->simulationStep)\n    return true;';s=s.replace(a,a+'\n  BENCH_SCOPE("camera_batch_render_readback_actual");',1)
 s='#include "/workspace/shared/benchmark-build/profile/source/BenchStage.h"\n'+s
 out=root/'source'/src.name;out.write_text(s);patches.extend(difflib.unified_diff(old.splitlines(True),s.splitlines(True),fromfile=str(src),tofile=str(out)))
 args=shlex.split(item['command']);obj=root/'obj'/(src.name+'.o');args[args.index('-o')+1]=str(obj);args[args.index('-c')+1]=str(out);args.extend(['-iquote',str(src.parent)])
 print('compile',src.name,flush=True);subprocess.run(args,cwd=build,env=env,check=True);mapping[item['output']]=str(obj)
(root/'instrumentation.patch').write_text(''.join(patches))
for target in ['SimRobotCore3','SimulatedRobot']:
 args=shlex.split((build/f'CMakeFiles/{target}.dir/link.txt').read_text());oldout=args[args.index('-o')+1];args[args.index('-o')+1]=str(root/'bin'/pathlib.Path(oldout).name)
 args=[mapping.get(a,a) for a in args]
 for i,a in enumerate(args):
  if a.startswith('--dependency-file='):args[i]='--dependency-file='+str(root/(target+'-link.d'))
 print('link',target,flush=True);subprocess.run(args,cwd=build,env=env,check=True)
orig=pathlib.Path('/workspace/shared/bhuman-build/source/Build/Linux/SimRobot/Release')
for p in orig.iterdir():
 dest=root/'bin'/p.name
 if not dest.exists():dest.symlink_to(p)
print('PROFILE_BUILD_COMPLETE',flush=True)
