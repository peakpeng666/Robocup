"""Stock service, wall-paced asynchronous shell. No launch or OS IPC is performed.
Host owns genuine Core3 ports/rendering and pause/resume, never this module.
"""
import time

STEP_NS = 2_000_000
IMAGE_PERIOD_NS = 17_000_000  # pinned BHuman nominal 60 Hz integer-ms schedule


class AsyncPhase:
    def __init__(self, host, bridge):
        self.host, self.bridge = host, bridge
        self.tick = 0
        self.next_image_ns = 0
        self.anchor_ns = None
        self.phase = 'new'
        self.metrics = dict(states=0, images=0, completed_physics_steps=0,
                            sensor_ns=0, render_ns=0, ipc_ns=0, submit_ns=0,
                            pace_ns=0, faults=0, causal_acknowledgments=0)

    def _timed(self, key, action):
        start = time.perf_counter_ns()
        try:
            return action()
        finally:
            self.metrics[key] += time.perf_counter_ns()-start

    def _fault(self, error):
        self.phase = 'fault'
        self.metrics['faults'] += 1
        try:
            self.host.pause()
        finally:
            self.host.revoke()
        raise RuntimeError(str(error)) from error

    def _publish(self):
        sample = self._timed('sensor_ns', self.host.read_sensors)
        # read_sensors returns the explicit codec fields; no implicit orientation oracle.
        self._timed('ipc_ns', lambda: self.bridge.send_state(
            sample['joints'], sample['acc'], sample['rpy'], sample['omega'],
            wall_ns=self.host.wall_ns(), sim_tick=self.tick))
        self.metrics['states'] += 1
        now = self.tick*STEP_NS
        if now >= self.next_image_ns:
            self._timed('render_ns', lambda: self.host.render_and_publish_image(self.tick))
            self.metrics['images'] += 1
            self.next_image_ns = (now if now-self.next_image_ns >= IMAGE_PERIOD_NS
                                  else self.next_image_ns)+IMAGE_PERIOD_NS

    def start(self):
        try:
            if self.phase != 'new':
                raise ValueError('construct a fresh phase/bridge for a new epoch')
            self.host.pause()
            self._publish()
            self.phase = 'waiting_first_command'
        except Exception as error:
            self._fault(error)

    def _arm(self):
        # Wait BEFORE reading latest torque and checking its lease. The wait is not
        # counted as a new sensor/command frame, and never alters simulated dt.
        target = self.anchor_ns+(self.tick+1)*STEP_NS
        self._timed('pace_ns', lambda: self.host.wait_until_wall_ns(target))
        now = self.host.wall_ns()
        if now < target:
            raise ValueError('wall pacing returned early; acceleration is not enabled')
        self._timed('ipc_ns', lambda: self.bridge.poll(wall_ns=now, sim_tick=self.tick))
        torque = self.bridge.torque_for_step(wall_ns=now, sim_tick=self.tick)
        if torque is None:
            raise ValueError('no bounded torque lease')
        self._timed('submit_ns', lambda: self.host.submit_torque(torque))
        self.phase = 'armed'
        self.host.resume()

    def pump_startup(self):
        """Call on the paused event loop; no physics step until first valid command."""
        try:
            if self.phase != 'waiting_first_command':
                raise ValueError('not waiting for startup')
            now = self.host.wall_ns()
            self._timed('ipc_ns', lambda: self.bridge.poll(wall_ns=now, sim_tick=0))
            # This is readiness, not an applied command. Check startup timeout
            # without counting a held torque use before _arm actually applies it.
            if self.bridge.latest is None:
                self.bridge.torque_for_step(wall_ns=now, sim_tick=0)
                return False
            self.anchor_ns = now
            self._arm()
            return True
        except Exception as error:
            self._fault(error)

    def after_physics(self, tick, step_ns):
        try:
            if self.phase != 'armed' or type(tick) is not int or tick != self.tick+1 or step_ns != STEP_NS:
                raise ValueError('unexpected Core3 callback phase/tick/timestep')
            self.host.pause()
            self.tick = tick
            self.metrics['completed_physics_steps'] += 1
            self._publish()
            self._arm()
        except Exception as error:
            self._fault(error)

    def stop(self):
        self.host.pause()
        self.host.revoke()
        self.phase = 'stopped'
        # Peer termination and bridge.close(peer_stopped=True) are explicit owner
        # operations. Never remove IPC while the peer may still use it.
