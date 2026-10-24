# Timing-only wrapper; original verified module and vendor functions still execute.
import importlib.util,time,sys,json
path='/workspace/shared/robocup-native-adapt/native/booster16/official_policy/backend.py'
spec=importlib.util.spec_from_file_location('original_official_backend',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
stats={}
def timed(name,fn):
 def call(*a,**kw):
  start=time.perf_counter_ns()
  try:return fn(*a,**kw)
  finally:
   x=stats.setdefault(name,[0,0]);x[0]+=1;x[1]+=time.perf_counter_ns()-start
 return call
m.LocomotionPolicy._forward_model=timed('official_torchscript_forward',m.LocomotionPolicy._forward_model)
m.LocomotionPolicy.inference=timed('official_policy_inference_obs_forward_postprocess',m.LocomotionPolicy.inference)
original=m.OfficialK1Backend.step
wrapped=timed('official_backend_step_validation_mapping_policy',original)
def step(*a,**kw):
 value=wrapped(*a,**kw)
 if stats['official_backend_step_validation_mapping_policy'][0] in (1000,1001):
  print('PERF_PYTHON '+json.dumps({'stages':stats,'torch_num_threads':m.torch.get_num_threads(),'torch_interop_threads':m.torch.get_num_interop_threads()}),file=sys.stderr,flush=True)
 return value
m.OfficialK1Backend.step=step
m.main()
