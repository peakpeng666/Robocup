"""Execute the real termination/reset methods on a tiny CPU boundary fixture."""
import argparse
import ast
import json
from pathlib import Path
import numpy as np
import torch

parser = argparse.ArgumentParser()
parser.add_argument('--expect-stale', action='store_true')
args = parser.parse_args()
path = Path(__file__).resolve().parents[1] / 'src/IsaacGymRL/envs/t1.py'
tree = ast.parse(path.read_text())
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
cls.bases = []
cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in ('_check_termination', '_reset_idx')]
scope = {'torch': torch, 'np': np}
exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(path), 'exec'), scope)
env = scope[cls.name].__new__(scope[cls.name])
env.cfg = {'rewards': {'terminate_vel':400., 'terminate_height':.2, 'terminate_time':.1, 'episode_length_s':30.}}
env.contact_forces = torch.zeros(2, 1, 3)
env.termination_contact_indices = torch.empty(0, dtype=torch.long)
env.root_states = torch.zeros(2, 13)
env.base_pos = torch.tensor([[0.,0.,.58],[0.,0.,.58]])
env.terrain = type('Terrain', (), {'terrain_heights': lambda self, p: torch.zeros(len(p))})()
env.dt = .02
env.terminate_counter = torch.zeros(2, dtype=torch.long)
env.time_out_buf = torch.zeros(2, dtype=torch.bool)
env.extras = {'time_outs': env.time_out_buf}
env.cmd_resample_time = torch.tensor([400, 500])
env.episode_length_buf = torch.tensor([400, 400])
env._check_termination()
env._reset_idx(env.reset_buf.nonzero().flatten())
assert env.time_out_buf.tolist() == [True, False]
assert not env.reset_buf.any(), 'Command resampling is a bootstrap boundary, not a physical reset.'
fresh = torch.equal(env.extras['time_outs'], env.time_out_buf)
print(json.dumps({'boundary':'command-resample-without-reset', 'environment_timeouts':env.time_out_buf.tolist(),
                  'returned_timeouts':env.extras['time_outs'].tolist(), 'fresh':fresh}))
assert fresh != args.expect_stale
if not args.expect_stale:
    env.episode_length_buf += 1
    env._check_termination()
    env._reset_idx(env.reset_buf.nonzero().flatten())
    assert not env.time_out_buf.any()
    assert torch.equal(env.extras['time_outs'], env.time_out_buf), 'Timeout must clear on the following step.'
    print('PASS: current boundary reported and cleared on next step')
