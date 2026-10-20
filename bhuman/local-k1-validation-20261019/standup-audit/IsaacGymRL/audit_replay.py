"""Passive per-episode tracing of the existing stand-up replay; no policy/config edits."""
import isaacgym
import json
import os
from pathlib import Path
from utils.runner import Runner
from envs.t1_stand_up import T1_Stand_Up

trace_path = Path(os.environ['BH_STANDUP_TRACE'])
trace_path.parent.mkdir(parents=True, exist_ok=True)
trace = trace_path.open('w')
original_reset = T1_Stand_Up._reset_idx
original_check = T1_Stand_Up._check_termination

def write(record):
    trace.write(json.dumps(record) + '\n')

def reset(self, env_ids):
    original_reset(self, env_ids)
    for env in env_ids.cpu().tolist():
        write({'event':'reset', 'step':int(self.common_step_counter), 'env':env,
               'direction':int(self.current_stand_up_info[env,0]),
               'start_keyframe':int(self.current_stand_up_info[env,1]),
               'root_xyz':self.root_states[env,:3].cpu().tolist(),
               'root_quat':self.root_states[env,3:7].cpu().tolist(),
               'dof_pos':self.dof_pos[env].cpu().tolist(),
               'delay_steps':int(self.delay_steps[env])})

def check(self):
    previous = self.fall_detected.clone()
    original_check(self)
    for env in range(self.num_envs):
        measured = self.env_torso_rot[env].cpu().tolist()
        target = self.current_target_pose[env,-3:-1].cpu().tolist()
        write({'event':'step', 'step':int(self.common_step_counter), 'env':env,
               'episode_step':int(self.episode_length_buf[env]),
               'direction':int(self.current_stand_up_info[env,0]),
               'keyframe':int(self.current_stand_up_info[env,1]),
               'gait_process':float(self.gait_process[env]),
               'measured_roll_pitch':measured, 'reference_roll_pitch':target,
               'error_roll_pitch':[measured[i]-target[i] for i in range(2)],
               'root_z':float(self.root_states[env,2]),
               'root_velocity_squared':float(self.root_states[env,7:13].square().sum()),
               'fall_onset':bool(self.fall_detected[env] and not previous[env]),
               'fall_latched':bool(self.fall_detected[env]),
               'terminate_counter':int(self.terminate_counter[env]),
               'reset':bool(self.reset_buf[env]), 'timeout':bool(self.time_out_buf[env]),
               'action_absmax':float(self.actions[env].abs().max())})

T1_Stand_Up._reset_idx = reset
T1_Stand_Up._check_termination = check
runner = None
try:
    runner = Runner(test=True)
    runner.play()
finally:
    trace.close()
    if runner is not None:
        runner.env.close()
