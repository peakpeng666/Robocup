"""One local simulation lock for CLI, HTTP configuration writes and whole series.

Nested calls on the owning thread reuse the lock. Other threads and processes
fail immediately instead of changing a configuration while it is in use.
"""
import fcntl
import threading
from contextlib import contextmanager
from functools import wraps

from . import paths

_mutex = threading.RLock()
_owner = threading.local()


@contextmanager
def simulation_lock(error_type=RuntimeError):
    message = "本机仿真或配置写入正在进行（共享 .bhuman-sim.lock），请稍后重试"
    if not _mutex.acquire(blocking=False):
        raise error_type(message)
    try:
        if getattr(_owner, "depth", 0):
            _owner.depth += 1
            try:
                yield
            finally:
                _owner.depth -= 1
        else:
            with paths.BH_SIM_LOCK.open("a") as stream:
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise error_type(message) from None
                _owner.depth = 1
                try:
                    yield
                finally:
                    _owner.depth = 0
                    fcntl.flock(stream, fcntl.LOCK_UN)
    finally:
        _mutex.release()


def exclusive_simulation(error_type=RuntimeError):
    def decorate(function):
        @wraps(function)
        def run(*args, **kwargs):
            with simulation_lock(error_type):
                return function(*args, **kwargs)
        return run
    return decorate
