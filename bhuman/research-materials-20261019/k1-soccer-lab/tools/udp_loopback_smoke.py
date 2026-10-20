#!/usr/bin/env python3
"""Six-IP loopback protocol exercise. It does not run an official GC or physics."""

from dataclasses import asdict
import json
from pathlib import Path
import socket
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from k1lab.gc2026 import HEADER, TEAM, CONTROL_PORT, RETURN_PORT, RobotStatus, decode_control, encode_status, decode_status


def control_fixture() -> bytes:
    header = HEADER.pack(b"RGme", 20, 17, 3, 1, 0, 0, 3, 0, 1, 1, 600, 0)
    teams = []
    for number in (1, 2):
        teams.append(TEAM.pack(number, number - 1, 4 + number, 1, 0, 0, 0, 12000) + bytes(60))
    return header + b"".join(teams)


def main() -> None:
    sockets = []
    identities = [(team, player, f"127.0.0.{10 * team + player}") for team in (1, 2) for player in (1, 2, 3)]
    started = time.time()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as referee:
            referee.bind(("127.0.0.10", RETURN_PORT))
            referee.settimeout(2.0)
            for team, player, address in identities:
                channel = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sockets.append(channel)
                channel.bind((address, CONTROL_PORT))
                channel.settimeout(2.0)
                referee.sendto(control_fixture(), (address, CONTROL_PORT))
                data, peer = channel.recvfrom(2048)
                game = decode_control(data)
                assert game.state_name == "PLAYING" and game.team(team).message_budget == 12000
                # Explicitly synthetic test state, never sent outside 127/8.
                status = RobotStatus(player, team, False, (float(100 * player), 0.0, 0.0), -1.0, (0.0, 0.0))
                channel.sendto(encode_status(status), ("127.0.0.10", RETURN_PORT))
            seen = []
            for _ in identities:
                data, peer = referee.recvfrom(2048)
                status = decode_status(data)
                seen.append({"source_ip": peer[0], "team":status.team_number, "player":status.player_number, "bytes":len(data)})
            assert len({item["source_ip"] for item in seen}) == 6
            assert {(item["team"], item["player"]) for item in seen} == {(a, b) for a, b, _ in identities}
            print(json.dumps({"test":"six_ip_loopback", "result":"passed", "started_at":started,
                              "control_size":158, "return_size":32, "robots":seen,
                              "scope":"loopback UDP only; official GameController GUI, LAN, DDS and physics not exercised"}, indent=2))
    finally:
        for channel in sockets:
            channel.close()


if __name__ == "__main__":
    main()
