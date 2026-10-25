"""evdev shim: the Virtual K1 harness exposes no input devices.

booster_deploy then falls back to the ``/remote_controller_state`` topic, which the
harness drives with a scripted operator (X = Custom mode, A = RL gait, sticks = velocity).
"""


class ecodes:  # noqa: N801 - mirrors the evdev module attribute name
    EV_KEY, EV_ABS = 1, 3
    ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ = 0, 1, 2, 3, 4, 5
    BTN_A, BTN_B, BTN_X, BTN_Y = 304, 305, 307, 308


def list_devices():
    return []


class InputDevice:
    def __init__(self, path):
        raise OSError(f"no input device {path!r} in the Virtual K1 harness")
