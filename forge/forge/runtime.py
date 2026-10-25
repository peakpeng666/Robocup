"""Bounded log streaming, including when a child stops producing output."""
import os
import selectors
import signal
import subprocess
import threading
import time
from contextlib import contextmanager


@contextmanager
def interrupt_on_termination():
    """Let CLI validation flush its interrupted report on scheduler cancellation."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = signal.getsignal(signal.SIGTERM)

    def terminate(_signal, _frame):
        # The scheduler may signal both the PID and its process group.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise KeyboardInterrupt("Validation interrupted by SIGTERM")

    signal.signal(signal.SIGTERM, terminate)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def stream_process(command, *, cwd, env, directory, timeout, on_line=None):
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, start_new_session=True)
    (directory / "pid.txt").write_text(f"{process.pid}\n")
    timed_out = False
    pending = b""
    with (directory / "console.log").open("wb") as log, selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            while selector.get_map():
                if time.monotonic() - started > timeout:
                    timed_out = True
                    break
                for key, _ in selector.select(timeout=0.2):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    log.write(chunk)
                    log.flush()
                    if on_line:
                        pending += chunk
                        while b"\n" in pending:
                            line, pending = pending.split(b"\n", 1)
                            on_line(line.decode(errors="replace") + "\n")
            if not timed_out:
                process.wait(timeout=max(0.1, timeout - (time.monotonic() - started)))
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
                except ProcessLookupError:
                    process.wait(timeout=5)
            process.stdout.close()
        if on_line and pending:
            on_line(pending.decode(errors="replace"))
    return {"exit_code": 124 if timed_out else process.returncode, "wall_s": time.monotonic() - started,
            "timeout_s": timeout, "timed_out": timed_out}
