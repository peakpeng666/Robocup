import os,sys,time,json,subprocess,pathlib,resource,hashlib,statistics
root=pathlib.Path('/workspace/shared/benchmark-build');binary=pathlib.Path('/workspace/shared/benchmark-build/official-profile/bin/SimRobot');source=root/'source';env=os.environ.copy();env.update(LD_LIBRARY_PATH='/workspace/shared/build-deps/root/usr/lib/x86_64-linux-gnu',QT_QPA_PLATFORM='surfaceless',QT_PLUGIN_PATH='/workspace/shared/simrobot-build/qpa/build',QT_QPA_PLATFORM_PLUGIN_PATH='/workspace/shared/build-deps/root/usr/lib/x86_64-linux-gnu/qt6/plugins/platforms',EGL_PLATFORM='surfaceless',LIBGL_ALWAYS_SOFTWARE='1',LP_NUM_THREADS='4',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',ALSA_CONFIG_PATH='/workspace/shared/robocup-native-adapt/native/booster16/video/alsa-null.conf',BENCH_CONTROLLER='BoosterK1Policy',BENCH_SCENE_ROOT='OfficialK1',BOOSTER_PYTHON='/workspace/shared/booster-native-venv/bin/python',BOOSTER_POLICY_SCRIPT='/workspace/shared/benchmark-build/official-profile/profile_backend.py',BOOSTER_VELOCITY_COMMAND_JSON='[0,0,0]',BENCH_STEPS='10000')
for key in ['BOOSTER_TRACE_JSONL','BOOSTER_CAMERA_PNG','BOOSTER_MAX_POLICY_TICKS','BOOSTER_COMMAND_SCHEDULE_JSON']:
 env.pop(key,None)
for i in range(1,2):
 d=root/'runs'/f'official-profiled-{i}';d.mkdir();(d/'Config').symlink_to('/workspace/shared/bhuman-upstream/Config');(d/'scene').mkdir()
 for ext in ('ros3',):(d/'scene'/f'OfficialControl.{ext}').write_bytes((source/f'OfficialControl.{ext}').read_bytes())
 env.update(XDG_CONFIG_HOME=str(d/'config'),XDG_CACHE_HOME=str(d/'cache'),BENCH_RESULT=str(d/'metrics.json'))
 m={'run':i,'nominal_camera_width':544,'nominal_camera_height':448,'nominal_camera_fps':0,'actual_camera_count_not_instrumented':True,'cpu_affinity':sorted(os.sched_getaffinity(0)),'environment':{k:env[k] for k in ['LP_NUM_THREADS','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','LIBGL_ALWAYS_SOFTWARE']},'realtime_throttle':'dt off','policy_stack':'Official K1 walking control only; camera/vision/brain absent, NOT full-pipeline comparable','disk_frame_capture':False,'third_person_camera':False}
 m['input_sha256']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [binary,binary.parent/'libBoosterK1Policy.so',binary.parent/'libSimRobotCore3.so',binary.parent/'libBenchmarkObserver.so',d/'scene'/'OfficialControl.ros3']}
 start=time.monotonic();u0=resource.getrusage(resource.RUSAGE_CHILDREN)
 with (d/'run.log').open('w') as f:
  p=subprocess.Popen([str(binary),'-noWindow',str(d/'scene'/'OfficialControl.ros3')],cwd=binary.parent,env=env,stdout=f,stderr=subprocess.STDOUT);peak=0
  while p.poll() is None:
   try:peak=max(peak,len(list(pathlib.Path(f'/proc/{p.pid}/task').iterdir())))
   except FileNotFoundError:pass
   if time.monotonic()-start>180:p.terminate();time.sleep(2);p.kill() if p.poll() is None else None
   time.sleep(.1)
 u1=resource.getrusage(resource.RUSAGE_CHILDREN);end=time.monotonic();m.update(exit_code=p.returncode,process_wall_seconds=end-start,process_cpu_seconds=(u1.ru_utime+u1.ru_stime-u0.ru_utime-u0.ru_stime),peak_parent_threads=peak,process_start_monotonic_s=start)
 if (d/'metrics.json').exists():
  b=json.loads((d/'metrics.json').read_text());m.update(b);m.update(rtf_including_startup_and_teardown=b['simulated_seconds']/(end-start),startup_to_loop_seconds=b['loop_begin_monotonic_s']-start)
 (d/'result.json').write_text(json.dumps(m,indent=2));print(json.dumps(m),flush=True)
 if p.returncode!=0:raise RuntimeError('baseline failure, stop')
