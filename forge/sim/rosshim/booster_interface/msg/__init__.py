"""booster_interface.msg -- plain Python message classes with the ROS 2 field layout."""
from __future__ import annotations


class _Message:
    __slots__ = ()
    _defaults: dict = {}

    def __init__(self, **values):
        for name, default in self._defaults.items():
            object.__setattr__(self, name, values.pop(name) if name in values else _copy(default))
        if values:
            raise TypeError(f"{type(self).__name__} has no fields {sorted(values)}")

    def __repr__(self):
        return f"{type(self).__name__}({', '.join(f'{k}={getattr(self, k)!r}' for k in self._defaults)})"


def _copy(value):
    if isinstance(value, list):
        return list(value)
    if isinstance(value, type) and issubclass(value, _Message):
        return value()
    return value


class MotorCmd(_Message):
    __slots__ = ("mode", "q", "dq", "tau", "kp", "kd", "weight")
    _defaults = {"mode": 0, "q": 0.0, "dq": 0.0, "tau": 0.0, "kp": 0.0, "kd": 0.0, "weight": 0.0}


class LowCmd(_Message):
    CMD_TYPE_PARALLEL = 0
    CMD_TYPE_SERIAL = 1
    __slots__ = ("cmd_type", "motor_cmd", "_forge_seq")
    _defaults = {"cmd_type": 0, "motor_cmd": [], "_forge_seq": 0}


class MotorState(_Message):
    __slots__ = ("mode", "q", "dq", "ddq", "tau_est", "temperature", "lost", "reserve")
    _defaults = {"mode": 0, "q": 0.0, "dq": 0.0, "ddq": 0.0, "tau_est": 0.0, "temperature": 0, "lost": 0,
                 "reserve": [0, 0]}


class ImuState(_Message):
    __slots__ = ("rpy", "gyro", "acc")
    _defaults = {"rpy": [0.0, 0.0, 0.0], "gyro": [0.0, 0.0, 0.0], "acc": [0.0, 0.0, 0.0]}


class LowState(_Message):
    __slots__ = ("imu_state", "motor_state_parallel", "motor_state_serial", "_forge_seq", "_forge_sim_time")
    _defaults = {"imu_state": ImuState, "motor_state_parallel": [], "motor_state_serial": [], "_forge_seq": 0,
                 "_forge_sim_time": 0.0}


class RemoteControllerState(_Message):
    __slots__ = ("event", "lx", "ly", "rx", "ry", "a", "b", "x", "y", "lb", "rb", "lt", "rt", "ls", "rs", "back",
                 "start", "hat_c", "hat_u", "hat_d", "hat_l", "hat_r", "hat_lu", "hat_ld", "hat_ru", "hat_rd",
                 "hat_pos")
    _defaults = {"event": 0, "lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0, **{k: False for k in (
        "a", "b", "x", "y", "lb", "rb", "lt", "rt", "ls", "rs", "back", "start", "hat_c", "hat_u", "hat_d", "hat_l",
        "hat_r", "hat_lu", "hat_ld", "hat_ru", "hat_rd")}, "hat_pos": 0}


class BoosterApiReqMsg(_Message):
    __slots__ = ("api_id", "body")
    _defaults = {"api_id": 0, "body": ""}


class BoosterApiRespMsg(_Message):
    __slots__ = ("status", "body")
    _defaults = {"status": 0, "body": ""}
