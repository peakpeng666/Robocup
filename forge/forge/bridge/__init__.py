"""K1 motion bridge (运控桥): one low-level contract between every controller and every backend.

B-Human bridges its motion stack to SimRobot (``SimulatedRobot3D``: actuator target + PD
parameters) and to the Booster robot (``BoosterProvider``: ``rt/joint_ctrl`` LowCmd /
``rt/low_state``) through the same per-joint semantics (target, kp, kd, torque limit).
Booster's open-source ``booster_deploy`` does the same with ``MujocoController`` and
``BoosterRobotPortal`` (ROS 2 ``/low_state``, ``joint_ctrl``, ``booster_rpc_service``).

This package is the control-plane side (no torch / MuJoCo):

* ``lowlevel`` -- the public K1 interface: joint table, message schemas, modes, RPC ids and
  the firmware facts read from plaintext configuration;
* ``contract`` -- machine audit of joint order, gains, limits and messages across B-Human,
  booster_deploy, the MuJoCo model and firmware 1.6 configuration;
* ``analysis`` / ``runner`` -- verdicts over Virtual K1 runs (``sim/vk1.py``);
* ``lessons`` -- the experience ledger.
"""
