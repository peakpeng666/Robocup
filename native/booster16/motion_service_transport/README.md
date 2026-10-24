# Independent full motion-service transport

Current restored-cloud execution:23 tests PASS (18 lifecycle/fake-peer integration,
5 wire fixtures). These are in-memory tests, not an official service handshake.
The Linux IPC backend is implemented but UNEXECUTED. No vendor code is copied,
imported or launched by the test suite.

Run:

    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s native/booster16/motion_service_transport -v

Files:
- codec.py: independently recovered observed little-endian bytes contract.
- bridge.py: bounded lifecycle,22-joint torque-only path, local freshness metrics.
- linux_ipc.py: exclusive-owner SystemV/POSIX implementation, no fallback/attach.
- test_bridge.py: isolated in-memory fake peer and fault/ownership scenarios.
- test_codec.py: fixed hexadecimal/offset fixtures, not captured vendor packets.
- BRIDGE_STATUS.md: API and critical safety/validation boundaries.

The earlier transport directory was not present in the recovered public commit
fc49429904f8802cd0c2dd44b8c13712ed0b0e48. codec.py was independently recovered from
this task's prior authored implementation and revalidated here. Prior13-test results
and runtime/source audits remain earlier-execution evidence, not a newly recovered
service run. Do not add the previous and current counts as if one suite ran.

## Observed wire contract

State direction: NAME_send_shm with NAME_write_sem. Command direction:
NAME_recv_shm with NAME_read_sem. Name hash uses multiplier131,32-bit wrapping,
then modulo0x7fffffff. Outer segment4108 bytes: signed int32 flag/count/length then
4096 bytes. Codec writes at most4000 payload bytes and refuses truncation.
Inner header:uint32 TLV payload length,uint32 validity=1; then tag,length,data.
State tags7(count),6(joint records),3(IMU); command tag5(joint records).

Joint record96 bytes: actual q/dq/torque at0/4/12, target q/dq/torque at32/36/40,
mode i32 at44, gains P/I/D at72/76/80, motor error i32 at92. Other fields are
preserved by parsing validity checks but not used to synthesize control.
IMU156 bytes:19 doubles followed by int32 count; acceleration[3],RPY[3],omega[3]
occupy first72 bytes, then raw heading and three backup vectors. State writer zeros
nonessential fields. Rotational units rad,rad/s,Nm; RPY radians; acceleration m/s².
Studio's inspected compatibility path uses gravity-projected acceleration, not full
accelerometer dynamics. Actual runtime model/site alignment remains a separate gate.

The prior inspected official1.7 runtime's simulation graph performs MIT PD inside
motion service and exports final torques. Therefore this bridge NEVER adds PD from
received targets/gains. No claim of firmware1.6 compatibility follows from the
shared bytes layout. Keep retained ARM/Forge1.6, ARM1.7 migration and native1.7
service experiments distinct; this work deletes/replaces none of them.

No timestamp, epoch, echoed sensor sequence or policy tick exists in this observed
wire format. Local command freshness is measured, not causality. Strict lockstep
is deliberately refused, and no speed-parity or complete football claim is made.
