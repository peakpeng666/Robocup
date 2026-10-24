"""Headless official K1 policy adapter. No ROS, DDS, hardware or physics backend."""
from __future__ import annotations
import contextlib
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import torch

PROFILE = 'official-k1-walk-7bb1462'
VENDOR = Path(__file__).resolve().parents[1] / 'vendor' / 'booster_deploy'
MODEL_SHA256 = '2d860167ed827e8d44cd65abd4c27f474904352bcb98c0cfa97c078f63e2fea5'

def verify_vendor():
    manifest = json.loads((VENDOR / 'SOURCE_MANIFEST.json').read_text())
    for name, expected in manifest['files_sha256'].items():
        if hashlib.sha256((VENDOR / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Vendored source hash mismatch: ' + name)
    model = VENDOR / 'tasks/locomotion/robots/k1/models/k1_walk.pt'
    if hashlib.sha256(model.read_bytes()).hexdigest() != MODEL_SHA256:
        raise RuntimeError('Pinned model hash mismatch')
    return model

verify_vendor()
sys.path.insert(0, str(VENDOR))
from booster_deploy.controllers.base_controller import BoosterRobot, VelocityCommand
from tasks.locomotion.locomotion import LocomotionPolicy
from tasks.locomotion.robots.k1 import K1WalkTaskCfg
# Fail closed if another pre-imported checkout shadows the pinned implementation.
for name in ('tasks.locomotion.locomotion', 'tasks.locomotion.robots.k1',
             'booster_deploy.controllers.base_controller'):
    if not Path(sys.modules[name].__file__).resolve().is_relative_to(VENDOR):
        raise RuntimeError('Foreign official module already imported: ' + name)

class PolicyStopped(RuntimeError):
    pass

def _integer(value, name):
    if type(value) is not int or value < 0 or value > 2**63 - 1:
        raise ValueError(name + ' must be a nonnegative int64')
    return value

def _tensor(value, length, name):
    tensor = torch.as_tensor(value, dtype=torch.float32, device='cpu')
    if tensor.shape != (length,) or not torch.isfinite(tensor).all().item():
        raise ValueError(name + ' must contain finite values in the exact shape')
    return tensor

class OfficialK1Backend:
    """One instance per robot, one owner thread; call only on policy ticks.

    Input uses real K1 joint order and SI units, quaternion body-to-world wxyz.
    Reset clears official observation history, last action, and target filter.
    Output is hybrid fields, NOT a torque command or a simulation result.
    """
    def __init__(self):
        self.cfg = K1WalkTaskCfg()
        self.cfg.policy.device = 'cpu'
        self.cfg.policy.checkpoint_path = str(verify_vendor())
        self.robot = BoosterRobot(self.cfg.robot)
        self.vel_command = VelocityCommand(self.cfg.vel_command)
        self.policy = LocomotionPolicy(self.cfg.policy, self)
        self.period_ns = round(self.cfg.policy_dt * 1_000_000_000)
        self.epoch = None
        self.next_tick = 0
        self.origin_ns = 0
        self.ready = False

    def stop(self):
        self.ready = False
        raise PolicyStopped('Official safety fallback stopped this replay session')

    def reset(self, epoch, origin_ns=0):
        epoch = _integer(epoch, 'epoch')
        origin_ns = _integer(origin_ns, 'origin_ns')
        if self.epoch is not None and epoch <= self.epoch:
            raise ValueError('reset requires a strictly increasing epoch')
        self.policy.reset()
        self.vel_command = VelocityCommand(self.cfg.vel_command)
        self.epoch, self.origin_ns, self.next_tick = epoch, origin_ns, 0
        self.ready = True
        return self.describe()

    def describe(self):
        return dict(profile=PROFILE, policy_period_ns=self.period_ns,
                    joint_names=list(self.cfg.robot.joint_names), model_sha256=MODEL_SHA256,
                    observation_shape=[10,69], action_count=20, target_count=22,
                    firmware_1_6_equivalence='unverified')

    def step(self, frame):
        if not self.ready:
            raise RuntimeError('reset required before inference')
        epoch = _integer(frame['epoch'], 'epoch')
        tick = _integer(frame['tick'], 'tick')
        stamp = _integer(frame['time_ns'], 'time_ns')
        if (epoch, tick, stamp) != (self.epoch, self.next_tick,
                                    self.origin_ns + self.next_tick*self.period_ns):
            raise ValueError('stale, skipped, wrong epoch or off-grid policy frame')
        if frame['joint_names'] != self.cfg.robot.joint_names:
            raise ValueError('joint_names must exactly match the declared K1 layout')
        q = _tensor(frame['q_rad'],22,'q_rad')
        dq = _tensor(frame['dq_rad_s'],22,'dq_rad_s')
        quat = _tensor(frame['orientation_wxyz'],4,'orientation_wxyz')
        gyro = _tensor(frame['gyro_rad_s'],3,'gyro_rad_s')
        cmd = _tensor(frame['velocity_command'],3,'velocity_command')
        if abs(torch.linalg.vector_norm(quat).item()-1) > 1e-4:
            raise ValueError('quaternion must be unit length; no silent normalization')
        limits = self.cfg.vel_command
        if not (-limits.vx_backward_max <= cmd[0] <= limits.vx_forward_max and
                abs(cmd[1]) <= limits.vy_max and abs(cmd[2]) <= limits.vyaw_max):
            raise ValueError('velocity command exceeds official configured range')
        self.robot.data.joint_pos.copy_(q)
        self.robot.data.joint_vel.copy_(dq)
        self.robot.data.root_quat_w.copy_(quat)
        self.robot.data.root_ang_vel_b.copy_(gyro)
        (self.vel_command.lin_vel_x,self.vel_command.lin_vel_y,
         self.vel_command.ang_vel_yaw) = cmd.tolist()
        try:
            # Official safety prints go to stderr, preserving JSON-lines stdout.
            with contextlib.redirect_stdout(sys.stderr):
                target = self.policy.inference()
            if target.shape != (22,) or not torch.isfinite(target).all().item():
                raise RuntimeError('Official policy produced invalid targets')
        except Exception:
            self.ready = False
            raise
        self.next_tick += 1
        return dict(profile=PROFILE,epoch=epoch,tick=tick,time_ns=stamp,
                    joint_names=list(self.cfg.robot.joint_names),
                    joints=[dict(mode='Hybrid',q_target_rad=float(target[i]),
                                 dq_target_rad_s=0.,kp=float(self.robot.joint_stiffness[i]),
                                 kd=float(self.robot.joint_damping[i]),tau_ff_nm=0.,
                                 torque_limit_nm=float(self.robot.effort_limit[i]))
                            for i in range(22)])

def main():
    """Local stdin/stdout replay bridge; caller owns cadence and actuator leases."""
    sessions = {}
    for line in sys.stdin:
        try:
            request = json.loads(line)
            robot = request['robot_id']
            if not isinstance(robot,str) or not robot or len(robot)>128:
                raise ValueError('robot_id must be a nonempty string <=128 characters')
            operation = request['op']
            if robot not in sessions:
                if operation != 'reset':
                    raise ValueError('unknown robot requires reset')
                sessions[robot] = OfficialK1Backend()
            session = sessions[robot]
            if operation == 'reset':
                result = session.reset(request['epoch'],request.get('origin_ns',0))
            elif operation == 'step':
                result = session.step(request['frame'])
            else:
                raise ValueError('op must be reset or step')
            response = dict(ok=True,robot_id=robot,result=result)
        except Exception as error:
            response = dict(ok=False,error=type(error).__name__,message=str(error))
        print(json.dumps(response,allow_nan=False),flush=True)

if __name__ == '__main__':
    main()
