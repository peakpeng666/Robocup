"""Bounded three-arm reset comparison; all variants use identical diagnostics."""
import ast
import hashlib
import json
import os
from pathlib import Path
import runpy
import isaacgym
import envs.t1_stand_up as module

mode = os.environ['BH_RESET_VARIANT']
if mode not in ('baseline', 'cache', 'fixed'):
    raise ValueError('Unknown reset variant')
source_root = Path(__file__).resolve().parent
snapshot = source_root.parent / 'baseline/t1_stand_up.py'
candidate = source_root.parent / 'baseline/t1_stand_up.cache_candidate.py'
expected = '790337313d479055f8196ef775b7a5eb4e490831432cf0b138b4a31e6db2b2c9'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
if sha(snapshot) != expected:
    raise ValueError('Baseline changed; refuse comparison')
if sha(candidate) != '18aeef9ad94185ad4f604baa5452ea86f00731ab09fddf47f227ce2321affd28':
    raise ValueError('Cache-only snapshot changed; refuse comparison')

def restore_method(path, name):
    tree = ast.parse(path.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'T1_Stand_Up')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace = dict(module.__dict__)
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
    setattr(module.T1_Stand_Up, name, namespace[name])

if mode in ('baseline', 'cache'):
    restore_method(snapshot, '_reset_idx')
    restore_method(snapshot if mode == 'baseline' else candidate, '_reset_root_states')

original_root_reset = module.T1_Stand_Up._reset_root_states
original_observations = module.T1_Stand_Up._compute_observations
cache_samples, observation_samples = [], []

def observe_root_reset(self, env_ids):
    old_min = self.body_states[env_ids, :, 2].min(dim=1).values.detach().clone()
    initial_dof = self.dof_pos[env_ids].detach().clone()
    keyframes = self.current_stand_up_info[env_ids, :2].detach().clone()
    rng = module.torch.cuda.get_rng_state(self.device).clone()
    original_root_reset(self, env_ids)
    cache_samples.append({
        'step': int(self.common_step_counter), 'env_ids': env_ids.detach().clone(),
        'cached_min_z_before_reset': old_min,
        'min_z_used_for_clearance': self.body_states[env_ids, :, 2].min(dim=1).values.detach().clone(),
        'root_state_after_writeback': self.root_states[env_ids].detach().clone(),
        'initial_dof_before_probe': initial_dof, 'direction_keyframe': keyframes,
        'rng_before_root_reset': rng, 'spawn_height_offset': self.spawn_height_offset.detach().clone(),
    })

def observe_observations(self):
    result = original_observations(self)
    ids = (self.episode_length_buf == 0).nonzero(as_tuple=False).flatten()
    if len(ids):
        q = self.root_states[ids, 3:7]
        gravity = module.quat_rotate_inverse(q, self.gravity_vec[ids])
        angular = module.quat_rotate_inverse(q, self.root_states[ids, 10:13])
        observation_samples.append({
            'step': int(self.common_step_counter), 'env_ids': ids.detach().clone(),
            'gravity_error': (self.projected_gravity[ids] - gravity).abs().max(dim=1).values.detach().clone(),
            'angular_velocity_error': (self.base_ang_vel[ids] - angular).abs().max(dim=1).values.detach().clone(),
            'dof_history_error': (self.prev_dof_pos[ids] - self.dof_pos[ids]).abs().max(dim=1).values.detach().clone(),
            'custom_dof_velocity_absmax': self.custom_dof_vel[ids].abs().max(dim=1).values.detach().clone(),
        })
    return result

module.T1_Stand_Up._reset_root_states = observe_root_reset
module.T1_Stand_Up._compute_observations = observe_observations
out = Path(os.environ['BH_STANDUP_TRACE']).parent
out.mkdir(parents=True, exist_ok=True)
(out / 'comparison-manifest.json').write_text(json.dumps({
    'variant': mode, 'baseline_sha256': expected, 'cache_candidate_sha256': sha(candidate),
    'fixed_sha256': sha(source_root/'envs/t1_stand_up.py'),
    'policy_sha256': sha(source_root/'pre-trained/GetUp/K1_stand_up.pt'),
    'config_sha256': sha(source_root/'envs/K1_Stand_Up.yaml'),
    'diagnostic_sha256': sha(Path(__file__)),
    'observation': 'Same tracer and instrumentation in all arms; probe advances all actors; no claim of nonintrusive timing or long-term success.',
}, indent=2)+'\n')

def plain(row):
    return {k: (v.cpu().tolist() if hasattr(v, 'cpu') else v) for k,v in row.items()}

completed = False
try:
    runpy.run_path(str(source_root / 'audit_replay.py'), run_name='__main__')
    completed = True
finally:
    for filename, samples in [('reset-cache.jsonl', cache_samples), ('reset-observation.jsonl', observation_samples)]:
        with (out / filename).open('w') as stream:
            for sample in samples:
                row = plain(sample)
                if 'rng_before_root_reset' in row:
                    row['rng_before_root_reset_sha256'] = hashlib.sha256(bytes(row.pop('rng_before_root_reset'))).hexdigest()
                row['variant'] = mode
                stream.write(json.dumps(row)+'\n')
    errors = {key: max((float(row[key].max().cpu()) for row in observation_samples), default=0.0)
              for key in ('gravity_error', 'angular_velocity_error', 'dof_history_error')}
    summary = {'variant': mode, 'completed': completed, 'reset_batches': len(observation_samples),
               'max_reset_input_errors': errors, 'consistent': bool(observation_samples) and all(v <= 1e-5 for v in errors.values())}
    (out/'reset-observation-summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print('[reset-observation] '+json.dumps(summary))
if mode == 'fixed' and not summary['consistent']:
    raise AssertionError('Fixed reset returned inconsistent policy inputs')
