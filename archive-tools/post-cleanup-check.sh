#!/usr/bin/env bash
set -euo pipefail
source /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/env.sh
output=/home/peakpeng/.cache/robocup-publish-20261020/repo/archive
"$BH_PY" -B -c 'import isaacgym; import torch,json,sys,importlib.metadata as m; x=torch.ones((16,16),device="cuda"); result=float((x@x).sum().item()); torch.cuda.synchronize(); assert result==4096.0; print("BHG_ENV_RESULT="+json.dumps({"python":sys.version.split()[0],"gym":m.version("isaacgym"),"torch":torch.__version__,"torch_cuda":torch.version.cuda,"gpu":torch.cuda.get_device_name(0),"native_gym_import":"PASS","tiny_cuda_matmul":"PASS"}))' > "$output/post-cleanup-bh-gym.log" 2>&1
/home/peakpeng/.local/bin/uv --no-cache pip check --python "$BH_PY" > "$output/post-cleanup-dependency-check.txt" 2>&1
python3 - <<'PY'
from pathlib import Path
import json,subprocess,shutil
b=Path('/home/peakpeng/.cache/robocup-publish-20261020');out=b/'repo/archive'
line=next(x for x in (out/'post-cleanup-bh-gym.log').read_text().splitlines() if x.startswith('BHG_ENV_RESULT='));r={'bh-gym':json.loads(line.split('=',1)[1]),'dependency_check':'PASS','other_existing_environments':{}}
code='import sys,json,importlib.metadata as m; print(json.dumps({"python":sys.version.split()[0],"packages":{n:m.version(n) for n in sys.argv[1:]}}))'
for name,packages in [('isaaclab',['isaaclab','isaacsim','torch']),('isaacsim-gui',['isaacsim','torch','mujoco'])]:
 p=Path('/home/peakpeng/.venvs')/name/'bin/python';r['other_existing_environments'][name]=json.loads(subprocess.check_output([str(p),'-B','-c',code,*packages],text=True))
required=['/home/peakpeng/Desktop/Robocup/bhuman/k1-training/third_party/isaacgym/python/isaacgym','/home/peakpeng/Desktop/Robocup/bhuman/k1-training/downloads','/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/runtime','/home/peakpeng/IsaacLab','/home/peakpeng/.local/share/robocup-archive/recovery-key.txt']
assert all(Path(p).exists() for p in required);r['required_dependency_paths_exist']=True;r['status']='PASS';r['disk_free_bytes_before_staging_removal']=shutil.disk_usage('/home/peakpeng/Desktop/Robocup').free
(out/'post-cleanup-environments.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
PY
