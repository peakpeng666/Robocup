#!/usr/bin/env python3
"""Player-side HSL protocol probe. Passive by default; it never drives motors.

Status transmission requires --status-file, --source-ip, and --gc-ip together.
That file must contain fresh estimated robot state, not simulator ground truth.
Do not run a second player client beside an active B-Human process on one IP.
"""

import argparse
from dataclasses import asdict
import ipaddress
import json
from pathlib import Path
import socket
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from k1lab.gc2026 import CONTROL_PORT, RETURN_PORT, PacketSequence, ProtocolError, RobotStatus, decode_control, diagnostic_gate, encode_status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--team", type=int, required=True)
    parser.add_argument("--player", type=int, required=True)
    parser.add_argument("--listen-ip", default="0.0.0.0")
    parser.add_argument("--gc-ip", help="accept only this IPv4 source; mandatory when returning status")
    parser.add_argument("--source-ip", help="this virtual/physical robot's own IPv4 address")
    parser.add_argument("--status-file", type=Path)
    parser.add_argument("--seconds", type=float, default=30)
    args = parser.parse_args()
    if not 1 <= args.player <= 20 or not 0 <= args.team <= 255 or args.seconds <= 0:
        parser.error("invalid team, player or duration")
    if args.status_file and not (args.gc_ip and args.source_ip):
        parser.error("status sending requires both --gc-ip and --source-ip")
    for address in (args.listen_ip, args.gc_ip, args.source_ip):
        if address is not None:
            ipaddress.IPv4Address(address)
    def log(**values):
        print(json.dumps({"wall_time":time.time(), **values}, ensure_ascii=False), flush=True)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receive, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as send:
        receive.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        receive.bind((args.listen_ip, CONTROL_PORT))
        receive.settimeout(0.1)
        if args.source_ip:
            send.bind((args.source_ip, 0))
        until = time.monotonic() + args.seconds
        game, seen, heartbeat, last_gate = None, float("-inf"), float("-inf"), None
        sequence = PacketSequence()
        log(event="start", passive=not bool(args.status_file), protocol=20, listen=receive.getsockname())
        while time.monotonic() < until:
            try:
                data, peer = receive.recvfrom(65535)
                if args.gc_ip and peer[0] != args.gc_ip:
                    raise ProtocolError("unexpected GameController source: " + peer[0])
                new_game = decode_control(data)
                new_game.team(args.team)
                if not sequence.accept(new_game.packet_number, time.monotonic()):
                    raise ProtocolError("duplicate or reordered control packet")
                game, seen = new_game, time.monotonic()
                log(event="control", source=peer[0], state=game.state_name, stopped=game.stopped,
                    packet=game.packet_number, penalty=game.team(args.team).players[args.player - 1].penalty,
                    team_budget=game.team(args.team).message_budget)
            except socket.timeout:
                pass
            except (ProtocolError, OSError) as error:
                log(event="drop", reason=str(error))
            now = time.monotonic()
            gate = diagnostic_gate(game, args.team, args.player, now - seen)
            if gate != last_gate:
                log(event="diagnostic_gate", intent=gate)
                last_gate = gate
            if args.status_file and game and now - seen <= 2.0 and now - heartbeat >= 1.0:
                heartbeat = now
                try:
                    record = json.loads(args.status_file.read_text())
                    if not 0 <= time.time() - record["written_at_unix_s"] <= 2.0:
                        raise ProtocolError("status file is stale or from the future")
                    status = RobotStatus(args.player, args.team, record["fallen"], tuple(record["pose_mm_rad"]),
                                         record["ball_age_s"], tuple(record["ball_relative_mm"]))
                    send.sendto(encode_status(status), (args.gc_ip, RETURN_PORT))
                    log(event="status_sent", source_ip=send.getsockname()[0], bytes=32)
                except (ValueError, KeyError, TypeError, OSError) as error:
                    log(event="status_skipped", reason=str(error))


if __name__ == "__main__":
    main()
