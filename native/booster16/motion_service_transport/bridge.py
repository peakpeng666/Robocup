"""Independent simulator-side lifecycle and torque bridge. No implicit OS backend.
Local freshness is NOT sensor->command causality. Caller owns simulation and peer.
"""
from dataclasses import dataclass
import math
import secrets

from codec import (ipc_identity, encode_sensor_packet, encode_shm_record,
                   decode_shm_record, decode_commands)


@dataclass(frozen=True)
class ReceivedCommand:
    epoch: int
    command_count: int
    received_wall_ns: int
    received_sim_tick: int
    sensor_count_when_observed: int
    torque_nm: tuple
    causal_sensor_count: object = None  # Stock service does not echo one.


class BridgeFault(RuntimeError):
    pass


class ServiceBridge:
    def __init__(self, kernel, torque_limits, *, epoch, max_age_ticks,
                 max_age_ns, startup_timeout_ns, strict_lockstep=False):
        if strict_lockstep:
            raise ValueError('stock service has no verified sensor acknowledgment')
        if len(torque_limits) != 22 or any(not math.isfinite(x) or x <= 0 for x in torque_limits):
            raise ValueError('22 finite positive physical torque limits required')
        if (type(epoch) is not int or epoch < 0 or
                any(type(v) is not int or v <= 0 for v in
                    (max_age_ticks,max_age_ns,startup_timeout_ns))):
            raise ValueError('epoch and explicit finite leases required')
        self.kernel = kernel
        self.limits = tuple(torque_limits)
        self.epoch = epoch
        self.max_age_ticks = max_age_ticks
        self.max_age_ns = max_age_ns
        self.startup_timeout_ns = startup_timeout_ns
        self.name = None
        self.owned = []
        self.started_ns = None
        self.last_wall_ns = None
        self.last_tick = None
        self.sensor_count = 0
        self.command_count = 0
        self.latest = None
        self.fault = None
        self.closed = False
        self.metrics = dict(sensor_writes=0, command_reads=0, dropped_counts=0,
                            semaphore_posts_drained=0, stale_reuses=0, clipped_joints=0)
        self.last_applied_count = None

    def _fail(self, reason):
        self.fault = str(reason)
        self.latest = None
        raise BridgeFault(self.fault)

    def _time(self, wall_ns, tick):
        if self.closed or self.fault:
            raise BridgeFault(self.fault or 'bridge closed')
        if type(wall_ns) is not int or type(tick) is not int:
            self._fail('integer wall nanoseconds and simulation ticks required')
        if wall_ns < 0 or tick < 0 or (self.last_wall_ns is not None and
                (wall_ns < self.last_wall_ns or tick < self.last_tick)):
            self._fail('local clock regressed; restart with new epoch and IPC identity')
        self.last_wall_ns, self.last_tick = wall_ns, tick

    def open(self, wall_ns, *, run_token=None):
        if self.name is not None or self.closed:
            raise BridgeFault('bridge may only open once')
        token = run_token if run_token is not None else secrets.token_hex(8)
        self.name = f'bsim_{token}_e{self.epoch}'
        identity = ipc_identity(self.name)
        try:
            self.state = self.kernel.create_memory(identity['state_key'], 4108)
            self.owned.append(('memory', self.state))
            self.command = self.kernel.create_memory(identity['command_key'], 4108)
            self.owned.append(('memory', self.command))
            self.state_ready = self.kernel.create_semaphore(identity['state_ready_sem'])
            self.owned.append(('semaphore', self.state_ready))
            self.command_ready = self.kernel.create_semaphore(identity['command_ready_sem'])
            self.owned.append(('semaphore', self.command_ready))
            self._time(wall_ns, 0)
            self.started_ns = wall_ns
        except Exception:
            # No peer has been handed the identity yet; clean only successful creates.
            self._cleanup()
            self.closed = True
            raise
        return self.name

    def send_state(self, joints, acc, rpy, omega, *, wall_ns, sim_tick):
        self._time(wall_ns, sim_tick)
        if self.started_ns is None:
            self._fail('bridge not opened')
        try:
            if len(joints) != 22 or self.sensor_count == 0x7fffffff:
                raise ValueError('invalid joint count or exhausted send counter')
            packet = encode_sensor_packet(joints, acc, rpy, omega)
            count = self.sensor_count + 1
            self.kernel.write(self.state, encode_shm_record(packet, count))
            self.kernel.post(self.state_ready)
            self.sensor_count = count
            self.metrics['sensor_writes'] += 1
            return count
        except Exception as error:
            self._fail(error)

    def poll(self, *, wall_ns, sim_tick):
        self._time(wall_ns, sim_tick)
        try:
            wakes = 0
            # Bounded drain: a constantly posting peer cannot hang the physics thread.
            for _ in range(256):
                if not self.kernel.try_wait(self.command_ready):
                    break
                wakes += 1
            else:
                raise ValueError('command semaphore backlog exceeds bounded drain')
            if not wakes:
                return False
            self.metrics['semaphore_posts_drained'] += wakes
            first = self.kernel.read(self.command, 4108)
            second = self.kernel.read(self.command, 4108)
            if first != second:
                raise ValueError('unstable shared record; no atomic snapshot guaranteed')
            count, packet = decode_shm_record(first)
            if count <= self.command_count:
                raise ValueError('duplicate/regressed command counter')
            commands = decode_commands(packet, 22)
            if any(c.motor_error for c in commands):
                raise ValueError('nonzero command motor-error field')
            torques = tuple(max(-limit, min(limit, c.torque)) for c,limit in zip(commands,self.limits))
            self.metrics['clipped_joints'] += sum(t != c.torque for t,c in zip(torques,commands))
            if self.command_count:
                self.metrics['dropped_counts'] += count-self.command_count-1
            self.command_count = count
            self.latest = ReceivedCommand(self.epoch,count,wall_ns,sim_tick,self.sensor_count,torques)
            self.metrics['command_reads'] += 1
            return True
        except Exception as error:
            self._fail(error)

    def torque_for_step(self, *, wall_ns, sim_tick):
        self._time(wall_ns, sim_tick)
        if self.started_ns is None:
            self._fail('bridge not opened')
        if self.latest is None:
            if wall_ns-self.started_ns >= self.startup_timeout_ns:
                self._fail('first-command timeout')
            return None  # Not ready: caller MUST keep simulation paused, not claim stand.
        if (wall_ns-self.latest.received_wall_ns >= self.max_age_ns or
                sim_tick-self.latest.received_sim_tick >= self.max_age_ticks):
            self._fail('command lease expired')
        if self.last_applied_count == self.latest.command_count:
            self.metrics['stale_reuses'] += 1  # Held, within lease, not a new response.
        self.last_applied_count = self.latest.command_count
        return self.latest.torque_nm

    def _cleanup(self):
        errors=[]
        failed=[]
        for kind, handle in reversed(self.owned):
            try:
                getattr(self.kernel, 'destroy_'+kind)(handle)
            except Exception as error:
                errors.append(str(error))
                failed.append((kind,handle))
        self.owned=list(reversed(failed))
        return errors

    def close(self, *, peer_stopped):
        if not peer_stopped:
            raise BridgeFault('peer exit must be confirmed before IPC teardown')
        self.latest=None
        errors=self._cleanup()
        self.closed=True
        if errors:
            raise BridgeFault('owned-resource cleanup incomplete: '+'; '.join(errors))

    def restart(self, *, peer_stopped, new_epoch, wall_ns, run_token=None):
        if type(new_epoch) is not int or new_epoch <= self.epoch:
            raise ValueError('restart requires strictly increasing local epoch')
        self.close(peer_stopped=peer_stopped)
        successor=ServiceBridge(self.kernel,self.limits,epoch=new_epoch,
            max_age_ticks=self.max_age_ticks,max_age_ns=self.max_age_ns,
            startup_timeout_ns=self.startup_timeout_ns)
        successor.open(wall_ns,run_token=run_token)
        return successor
