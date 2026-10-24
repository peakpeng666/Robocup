"""Independent literal wire fixtures for recovered codec, no vendor imports."""
import struct
import unittest
from codec import *

class CodecFixtures(unittest.TestCase):
    def test_key_fixture(self):
        x=ipc_identity('robot1')
        self.assertEqual((x['state_key'],x['command_key']),(169270670,2147004739))
    def test_sensor_literal_hex(self):
        p=encode_sensor_packet([JointState(1.5,-2.5,3.5)]*22,(1,2,9.81),(.1,.2,.3),(4,5,6))
        self.assertEqual(len(p),4000);self.assertEqual(p[:8],bytes.fromhex('f808000001000000'))
        f=decode_tlvs(p);self.assertEqual(f[6][:16],bytes.fromhex('0000c03f000020c00000000000006040'))
        self.assertEqual(len(f[3]),156);self.assertEqual(f[3][72:],bytes(84))
    def test_invalid_tlv(self):
        e=struct.pack('<IIi',7,4,22)
        for p in (bytes(7),struct.pack('<II',100,1),struct.pack('<II',0,0),struct.pack('<II',24,1)+e+e):
            with self.subTest(p=p),self.assertRaises(ValueError):decode_tlvs(p)
    def test_command_offsets(self):
        r=bytearray(96);struct.pack_into('<fff',r,32,.25,-.5,3)
        struct.pack_into('<i',r,44,17);struct.pack_into('<fff',r,72,10,11,12)
        c=decode_commands(encode_tlvs([(5,bytes(r))]),1)[0]
        self.assertEqual((c.position,c.velocity,c.torque,c.mode,c.kp,c.ki,c.kd),(.25,-.5,3,17,10,11,12))
    def test_no_truncation_nan_or_bad_count(self):
        with self.assertRaises(ValueError):encode_tlvs([(5,bytes(4000))])
        with self.assertRaises(ValueError):encode_sensor_packet([JointState(float('nan'),0,0)],(0,0,0),(0,0,0),(0,0,0))
        with self.assertRaises(ValueError):encode_shm_record(encode_tlvs([(7,struct.pack('<i',22))]),0)
if __name__=='__main__':unittest.main()
