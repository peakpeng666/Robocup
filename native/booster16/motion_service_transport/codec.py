"""Independently authored observed simulator IPC contract, bytes only.
Recovered from this task's prior implementation after workspace replacement.
No vendor imports, process execution or IPC operations.
"""
from dataclasses import dataclass
import math
import re
import struct

CAPACITY=4096
MAX_WRITE=4000
JOINT_SIZE=96
IMU_SIZE=156

@dataclass(frozen=True)
class JointState:
    position: float
    velocity: float
    torque: float

@dataclass(frozen=True)
class JointCommand:
    position: float
    velocity: float
    torque: float
    mode: int
    kp: float
    ki: float
    kd: float
    motor_error: int


def _finite(values):
    if not all(math.isfinite(v) for v in values):raise ValueError('nonfinite field')


def ipc_identity(name):
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',name):
        raise ValueError('invalid IPC identity')
    def key(suffix):
        value=0
        for b in (name+suffix).encode('ascii'):value=(131*value+b)%(1<<32)
        value%=0x7fffffff
        if not value:raise ValueError('IPC_PRIVATE key disallowed')
        return value
    return dict(state_key=key('_send_shm'),command_key=key('_recv_shm'),
                state_ready_sem=name+'_write_sem',command_ready_sem=name+'_read_sem')


def encode_tlvs(items,padded_size=MAX_WRITE):
    payload=bytearray();seen=set()
    for tag,data in items:
        if not 0<tag<1<<32 or tag in seen or not data:raise ValueError('invalid/duplicate TLV')
        seen.add(tag);payload+=struct.pack('<II',tag,len(data))+data
    size=8+len(payload)
    if not size<=padded_size<=MAX_WRITE:raise ValueError('unsafe transport length')
    return struct.pack('<II',len(payload),1)+payload+bytes(padded_size-size)


def decode_tlvs(packet):
    if not 8<=len(packet)<=CAPACITY:raise ValueError('invalid packet size')
    size,valid=struct.unpack_from('<II',packet);end=8+size
    if valid!=1 or end>len(packet):raise ValueError('invalid/truncated protocol')
    result={};pos=8
    while pos<end:
        if end-pos<8:raise ValueError('truncated TLV header')
        tag,length=struct.unpack_from('<II',packet,pos);pos+=8
        if not tag or not length or tag in result or length>end-pos:raise ValueError('invalid TLV')
        result[tag]=packet[pos:pos+length];pos+=length
    return result


def encode_sensor_packet(joints,acceleration,rpy,angular_velocity):
    if not 1<=len(joints)<=39:raise ValueError('unsafe joint count')
    raw=bytearray(JOINT_SIZE*len(joints))
    for i,j in enumerate(joints):
        _finite((j.position,j.velocity,j.torque))
        struct.pack_into('<ff',raw,i*96,j.position,j.velocity)
        struct.pack_into('<f',raw,i*96+12,j.torque)
    if any(len(v)!=3 for v in (acceleration,rpy,angular_velocity)):raise ValueError('IMU vector size')
    v=tuple(acceleration)+tuple(rpy)+tuple(angular_velocity);_finite(v)
    imu=struct.pack('<19di',*(v+(0.0,)*10),0)
    return encode_tlvs(((7,struct.pack('<i',len(joints))),(6,bytes(raw)),(3,imu)))


def decode_commands(packet,expected_joints):
    if not 1<=expected_joints<=41:raise ValueError('invalid expected count')
    fields=decode_tlvs(packet)
    if 7 in fields and fields[7]!=struct.pack('<i',expected_joints):raise ValueError('joint count mismatch')
    raw=fields.get(5,b'')
    if len(raw)!=expected_joints*96:raise ValueError('missing/truncated/extra commands')
    out=[]
    for offset in range(0,len(raw),96):
        v=struct.unpack_from('<11fi11fi',raw,offset);_finite(v[:11]+v[12:23])
        out.append(JointCommand(v[8],v[9],v[10],v[11],v[18],v[19],v[20],v[23]))
    return tuple(out)


def encode_shm_record(packet,count):
    if not 0<count<=0x7fffffff or not 8<=len(packet)<=MAX_WRITE:raise ValueError('outer bounds')
    decode_tlvs(packet)
    return struct.pack('<iii',0,count,len(packet))+packet


def decode_shm_record(record):
    if not 12<=len(record)<=12+CAPACITY:raise ValueError('outer record size')
    flag,count,length=struct.unpack_from('<iii',record)
    if flag!=0 or count<=0 or not 8<=length<=CAPACITY or length>len(record)-12:
        raise ValueError('invalid outer header')
    packet=record[12:12+length];decode_tlvs(packet)
    return count,packet
