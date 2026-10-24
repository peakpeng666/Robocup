#!/usr/bin/env python3
"""Strict offline reader for the optional BHuman GC frame sink; no sockets/ROS."""
import argparse
import json
import struct


def decode_frames(data):
    if len(data) % 184:
        raise ValueError('truncated frame file')
    frames = []
    previous = None
    for offset in range(0, len(data), 184):
        record = data[offset:offset + 184]
        magic, version, length, epoch, time_ns = struct.unpack_from('<4sHHQQ', record)
        if (magic, version, length) != (b'BGCF', 1, 158) or record[182:] != b'\0\0':
            raise ValueError('invalid frame envelope')
        if previous is not None and (epoch < previous[0] or (epoch == previous[0] and time_ns <= previous[1])):
            raise ValueError('duplicate or regressed frame clock')
        previous = (epoch, time_ns)
        packet = record[24:182]
        if packet[:5] != b'RGme\x14':
            raise ValueError('not an RGme v20 packet')
        players, competition, stopped, phase, state, play, half, kicking = packet[6:14]
        teams = []
        for base in (18, 88):
            number, field_colour, keeper_colour, keeper, score, shots, single, budget = struct.unpack_from('<6BHH', packet, base)
            if keeper > 20 or field_colour > 9 or keeper_colour > 9:
                raise ValueError('invalid team metadata')
            robots = [tuple(packet[base + 10 + i*3:base + 13 + i*3]) for i in range(20)]
            if any(penalty > 13 for penalty, _, _ in robots):
                raise ValueError('unknown v20 penalty')
            teams.append({'number': number, 'score': score, 'players': robots, 'message_budget': budget})
        if not 1 <= players <= 20 or competition > 2 or stopped > 1 or phase > 3 or state > 4 or play > 6 or half > 1:
            raise ValueError('invalid game metadata')
        if teams[0]['number'] == teams[1]['number'] or kicking not in (255, teams[0]['number'], teams[1]['number']):
            raise ValueError('invalid match identity')
        remaining, secondary = struct.unpack_from('<hh', packet, 14)
        frames.append({'epoch': epoch, 'time_ns': time_ns, 'packet_number': packet[5], 'state': state,
                       'stopped': stopped, 'set_play': play, 'kicking_team': kicking,
                       'secs_remaining': remaining, 'secondary_time': secondary, 'teams': teams})
    return frames


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file')
    args = parser.parse_args()
    with open(args.file, 'rb') as source:
        print(json.dumps(decode_frames(source.read()), indent=2))
