"""In-memory fake peer only. Never imports or instantiates LinuxIpc."""
import struct
import unittest
from bridge import ServiceBridge, BridgeFault
from codec import JointState, encode_tlvs, encode_shm_record, decode_shm_record, decode_tlvs


class FakeKernel:
    def __init__(self):
        self.mem={};self.sem={};self.removed=[];self.unstable=False;self.reads=0
    def create_memory(self,key,size):
        if key in self.mem:raise FileExistsError('collision')
        self.mem[key]=bytearray(size);return key
    def create_semaphore(self,name):
        if name in self.sem:raise FileExistsError('collision')
        self.sem[name]=0;return name
    def write(self,h,data):self.mem[h][:len(data)]=data
    def read(self,h,size):
        self.reads+=1
        data=bytes(self.mem[h][:size])
        if self.unstable and self.reads%2==0:data=data[:-1]+bytes([data[-1]^1])
        return data
    def post(self,h):self.sem[h]+=1
    def try_wait(self,h):
        if self.sem[h]:self.sem[h]-=1;return True
        return False
    def destroy_memory(self,h):del self.mem[h];self.removed.append(h)
    def destroy_semaphore(self,h):del self.sem[h];self.removed.append(h)


def bridge(kernel=None,epoch=0,token='test'):
    b=ServiceBridge(kernel or FakeKernel(),[5.0]*22,epoch=epoch,max_age_ticks=3,
                    max_age_ns=100,startup_timeout_ns=200)
    b.open(0,run_token=token)
    return b


def peer_write(b,count,torque=2.0):
    raw=bytearray(22*96)
    for i in range(22):
        # Huge qtarget/kp prove these fields are NOT applied as another PD.
        struct.pack_into('<f',raw,i*96+32,1000)
        struct.pack_into('<f',raw,i*96+40,torque)
        struct.pack_into('<f',raw,i*96+72,1000)
    packet=encode_tlvs([(5,bytes(raw))])
    b.kernel.write(b.command,encode_shm_record(packet,count))
    b.kernel.post(b.command_ready)


class BridgeTests(unittest.TestCase):
    def test_sensor_direction_and_counter(self):
        b=bridge()
        b.send_state([JointState(0,0,0)]*22,(0,0,9.81),(0,0,0),(0,0,0),wall_ns=1,sim_tick=0)
        count,packet=decode_shm_record(bytes(b.kernel.mem[b.state]))
        self.assertEqual(count,1);self.assertIn(6,decode_tlvs(packet))
        self.assertEqual(b.kernel.sem[b.state_ready],1)
        self.assertEqual(b.kernel.sem[b.command_ready],0)

    def test_torque_only_clamp_and_no_causal_claim(self):
        b=bridge();peer_write(b,1,12)
        self.assertTrue(b.poll(wall_ns=1,sim_tick=0))
        self.assertEqual(b.torque_for_step(wall_ns=2,sim_tick=0),(5.0,)*22)
        self.assertIsNone(b.latest.causal_sensor_count)
        self.assertEqual(b.metrics['clipped_joints'],22)

    def test_startup_bound(self):
        b=bridge()
        self.assertIsNone(b.torque_for_step(wall_ns=199,sim_tick=0))
        with self.assertRaises(BridgeFault):b.torque_for_step(wall_ns=200,sim_tick=0)
        self.assertIsNone(b.latest)

    def test_held_action_lease(self):
        b=bridge();peer_write(b,1);b.poll(wall_ns=1,sim_tick=0)
        for tick in range(3):self.assertEqual(b.torque_for_step(wall_ns=tick+2,sim_tick=tick),(2.0,)*22)
        self.assertEqual(b.metrics['stale_reuses'],2)
        with self.assertRaises(BridgeFault):b.torque_for_step(wall_ns=5,sim_tick=3)

    def test_wall_lease_even_if_paused(self):
        b=bridge();peer_write(b,1);b.poll(wall_ns=1,sim_tick=0)
        with self.assertRaises(BridgeFault):b.torque_for_step(wall_ns=101,sim_tick=0)

    def test_counter_duplicates_fault(self):
        b=bridge();peer_write(b,1);b.poll(wall_ns=1,sim_tick=0);peer_write(b,1)
        with self.assertRaises(BridgeFault):b.poll(wall_ns=2,sim_tick=0)
        self.assertIsNone(b.latest)

    def test_latest_slot_backlog_measured(self):
        b=bridge();peer_write(b,1);b.poll(wall_ns=1,sim_tick=0)
        peer_write(b,2);peer_write(b,3);b.poll(wall_ns=2,sim_tick=1)
        self.assertEqual(b.latest.command_count,3)
        self.assertEqual(b.metrics['dropped_counts'],1)
        self.assertEqual(b.metrics['semaphore_posts_drained'],3)

    def test_no_unbounded_drain(self):
        b=bridge();b.kernel.sem[b.command_ready]=256
        with self.assertRaises(BridgeFault):b.poll(wall_ns=1,sim_tick=0)

    def test_unstable_read_fault(self):
        b=bridge();peer_write(b,1);b.kernel.unstable=True
        with self.assertRaises(BridgeFault):b.poll(wall_ns=1,sim_tick=0)

    def test_collision_does_not_remove_foreign(self):
        b=bridge();original=set(b.kernel.mem);other=ServiceBridge(b.kernel,[5]*22,epoch=0,max_age_ticks=1,max_age_ns=1,startup_timeout_ns=1)
        with self.assertRaises(FileExistsError):other.open(0,run_token='test')
        self.assertEqual(set(b.kernel.mem),original);self.assertEqual(b.kernel.removed,[])

    def test_partial_create_cleanup(self):
        k=FakeKernel();k.sem['bsim_test_e0_write_sem']=19
        with self.assertRaises(FileExistsError):bridge(k)
        self.assertEqual(k.mem,{})
        self.assertEqual(k.sem,{'bsim_test_e0_write_sem':19})

    def test_close_needs_peer_exit(self):
        b=bridge()
        with self.assertRaises(BridgeFault):b.close(peer_stopped=False)
        self.assertEqual(len(b.kernel.mem),2)
        b.close(peer_stopped=True);self.assertFalse(b.kernel.mem);self.assertFalse(b.kernel.sem)

    def test_restart_is_new_namespace_epoch_and_no_command(self):
        b=bridge();peer_write(b,1);b.poll(wall_ns=1,sim_tick=0)
        c=b.restart(peer_stopped=True,new_epoch=1,wall_ns=100,run_token='test')
        self.assertNotEqual(b.name,c.name);self.assertIsNone(c.latest);self.assertEqual(c.command_count,0)
        with self.assertRaises(BridgeFault):b.torque_for_step(wall_ns=101,sim_tick=0)
        with self.assertRaises(ValueError):c.restart(peer_stopped=True,new_epoch=1,wall_ns=100)

    def test_strict_lockstep_refused(self):
        with self.assertRaises(ValueError):ServiceBridge(FakeKernel(),[5]*22,epoch=0,max_age_ticks=1,max_age_ns=1,startup_timeout_ns=1,strict_lockstep=True)

    def test_clock_regression(self):
        b=bridge();b.poll(wall_ns=10,sim_tick=5)
        with self.assertRaises(BridgeFault):b.poll(wall_ns=11,sim_tick=4)

    def test_noninteger_time_and_unbounded_lease_refused(self):
        for bad in (float('nan'),float('inf'),1.5,True):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                ServiceBridge(FakeKernel(),[5]*22,epoch=0,max_age_ticks=bad,max_age_ns=1,startup_timeout_ns=1)
        b=bridge()
        with self.assertRaises(BridgeFault):b.poll(wall_ns=float('nan'),sim_tick=0)

    def test_cleanup_continues_and_retains_failed_handle(self):
        b=bridge();original=b.kernel.destroy_semaphore;failed=b.command_ready
        def destroy(h):
            if h==failed:raise RuntimeError('cleanup denied')
            return original(h)
        b.kernel.destroy_semaphore=destroy
        with self.assertRaises(BridgeFault):b.close(peer_stopped=True)
        self.assertEqual(b.owned,[('semaphore',failed)])
        self.assertEqual(b.kernel.mem,{})
        b.kernel.destroy_semaphore=original;b.close(peer_stopped=True)
        self.assertEqual(b.kernel.sem,{})

    def test_two_robots_do_not_cross_deliver(self):
        k=FakeKernel();a=bridge(k,token='one');b=bridge(k,token='two')
        peer_write(a,1)
        self.assertFalse(b.poll(wall_ns=1,sim_tick=0));self.assertTrue(a.poll(wall_ns=1,sim_tick=0))
        a.close(peer_stopped=True);self.assertEqual(len(k.mem),2)


if __name__=='__main__':unittest.main()
