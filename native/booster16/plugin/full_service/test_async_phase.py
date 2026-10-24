"""Only fake time, fake ports and in-memory actual-codec peer; no LinuxIpc."""
import pathlib
import sys
import unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'motion_service_transport'))
from bridge import ServiceBridge
from codec import JointState
from test_bridge import FakeKernel, peer_write
from async_phase import AsyncPhase, STEP_NS

class Host:
    def __init__(self):
        self.now=0;self.paused=False;self.revoked=False;self.early=False
        self.events=[];self.applied=[]
    def wall_ns(self):return self.now
    def pause(self):self.paused=True;self.events.append('pause')
    def resume(self):self.paused=False;self.events.append('resume')
    def revoke(self):self.revoked=True
    def wait_until_wall_ns(self,target):
        if not self.early:self.now=max(self.now,target)
    def read_sensors(self):
        self.events.append('sensor')
        return dict(joints=[JointState(0,0,0)]*22,acc=(0,0,9.81),rpy=(0,0,0),omega=(0,0,0))
    def render_and_publish_image(self,tick):self.events.append(('image',tick))
    def submit_torque(self,torque):self.applied.append(torque)

def fixture():
    h=Host();b=ServiceBridge(FakeKernel(),[5.0]*22,epoch=0,max_age_ticks=3,
                          max_age_ns=10_000_000,startup_timeout_ns=20_000_000)
    b.open(0,run_token='async_fixture');return h,b,AsyncPhase(h,b)

class Tests(unittest.TestCase):
    def test_stock_no_echo_startup_holds_then_arms(self):
        h,b,s=fixture();s.start();self.assertFalse(s.pump_startup())
        self.assertTrue(h.paused);self.assertFalse(h.applied)
        peer_write(b,1);self.assertTrue(s.pump_startup());self.assertEqual(h.now,STEP_NS)
        self.assertIsNone(b.latest.causal_sensor_count);self.assertEqual(s.metrics['causal_acknowledgments'],0)
        self.assertEqual(h.applied,[(2.0,)*22]);self.assertFalse(h.paused)
    def test_held_torque_is_counted_and_expires(self):
        h,b,s=fixture();s.start();peer_write(b,1);s.pump_startup()
        s.after_physics(1,STEP_NS);s.after_physics(2,STEP_NS)
        self.assertEqual(b.metrics['stale_reuses'],2)
        with self.assertRaises(RuntimeError):s.after_physics(3,STEP_NS)
        self.assertTrue(h.paused and h.revoked)
    def test_stock_sequence_progress_not_causal(self):
        h,b,s=fixture();s.start();peer_write(b,1);s.pump_startup()
        for tick in range(1,101):
            peer_write(b,tick+1);s.after_physics(tick,STEP_NS)
        self.assertEqual(s.metrics['states'],101)
        self.assertEqual(s.metrics['completed_physics_steps'],100)
        self.assertEqual(b.metrics['command_reads'],101)
        self.assertIsNone(b.latest.causal_sensor_count)
        self.assertGreaterEqual(h.now,101*STEP_NS)
    def test_no_acceleration_by_early_wait(self):
        h,b,s=fixture();s.start();peer_write(b,1);h.early=True
        with self.assertRaises(RuntimeError):s.pump_startup()
        self.assertFalse(h.applied);self.assertTrue(h.revoked)
    def test_timeout_and_restart_owner(self):
        h,b,s=fixture();s.start();h.now=20_000_000
        with self.assertRaises(RuntimeError):s.pump_startup()
        self.assertTrue(h.paused and h.revoked);self.assertFalse(b.closed)
    def test_bad_phase_or_dt(self):
        for tick,dt in [(2,STEP_NS),(1,1_000_000)]:
            h,b,s=fixture();s.start();peer_write(b,1);s.pump_startup()
            with self.assertRaises(RuntimeError):s.after_physics(tick,dt)
            self.assertTrue(h.revoked)
    def test_stop_does_not_destroy_peer_resources(self):
        h,b,s=fixture();s.start();s.stop();self.assertTrue(h.revoked)
        self.assertFalse(b.closed);self.assertEqual(len(b.owned),4)

if __name__=='__main__':unittest.main()
