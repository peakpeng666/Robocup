"""Strict HSL 2026 player protocol and a diagnostic state gate.

Wire reference: RoboCup-HumanoidSoccerLeague/GameController at
a6cc98bb9f7c0f03912134b333194af3fa880798, headers/RoboCupGameControlData.h
and the Rust control_message/status_message serializers. All numbers are LE.
This module does not infer hidden referee state and never accepts RGTD data.
The gate below is a diagnostic decision, not a physical robot safety controller.
"""

from dataclasses import dataclass
import math
import struct

CONTROL_PORT = 3838
RETURN_PORT = 3939
CONTROL_VERSION = 20
RETURN_VERSION = 4
MAX_PLAYERS = 20
TEAM_PAYLOAD_LIMIT = 512
HEADER = struct.Struct("<4s10Bhh")
TEAM = struct.Struct("<6BHH")
PLAYER = struct.Struct("<3B")
RETURN = struct.Struct("<4s4B6f")
CONTROL_SIZE = HEADER.size + 2 * (TEAM.size + MAX_PLAYERS * PLAYER.size)
STATE_NAMES = ("INITIAL", "READY", "SET", "PLAYING", "FINISHED")


class ProtocolError(ValueError):
    pass


class PacketSequence:
    """Discard duplicate/reordered control packets without refreshing liveness.

    After a receive gap the sequence is re-established to permit a GC restart.
    This is a transport diagnostic; UDP source/sequence checks are not authentication.
    """
    def __init__(self, resync_after_s: float = 2.0):
        self.last_packet = None
        self.last_time = float("-inf")
        self.resync_after_s = resync_after_s

    def accept(self, packet_number: int, now: float) -> bool:
        if not 0 <= packet_number <= 255 or not math.isfinite(now):
            return False
        if self.last_packet is not None and now - self.last_time <= self.resync_after_s:
            delta = (packet_number - self.last_packet) % 256
            if not 0 < delta < 128:
                return False
        self.last_packet, self.last_time = packet_number, now
        return True


@dataclass(frozen=True)
class PlayerInfo:
    penalty: int
    seconds_until_unpenalized: int
    cautions: int


@dataclass(frozen=True)
class TeamInfo:
    number: int
    field_color: int
    goalkeeper_color: int
    goalkeeper: int
    score: int
    penalty_shot: int
    single_shots: int
    message_budget: int
    players: tuple[PlayerInfo, ...]


@dataclass(frozen=True)
class GameControl:
    packet_number: int
    players_per_team: int
    competition_type: int
    stopped: bool
    game_phase: int
    state: int
    set_play: int
    first_half: bool
    kicking_team: int
    seconds_remaining: int
    secondary_time: int
    teams: tuple[TeamInfo, TeamInfo]

    def team(self, number: int) -> TeamInfo:
        for team in self.teams:
            if team.number == number:
                return team
        raise ProtocolError(f"team {number} is absent from the packet")

    @property
    def state_name(self) -> str:
        return STATE_NAMES[self.state]


def decode_control(data: bytes) -> GameControl:
    if len(data) != CONTROL_SIZE:
        raise ProtocolError(f"control packet size {len(data)} != {CONTROL_SIZE}")
    magic, version, packet, count, division, stopped, phase, state, play, half, kick, secs, secondary = HEADER.unpack_from(data)
    if magic != b"RGme":
        raise ProtocolError("player input must be RGme; monitor truth RGTD is forbidden")
    if version != CONTROL_VERSION:
        raise ProtocolError(f"unsupported HSL control version {version}, expected {CONTROL_VERSION}")
    if not 1 <= count <= MAX_PLAYERS or division not in (0, 1, 2):
        raise ProtocolError("invalid player count or competition type")
    if stopped not in (0, 1) or half not in (0, 1):
        raise ProtocolError("invalid stopped/firstHalf flag")
    if state not in range(5) or phase not in range(4) or play not in range(7):
        raise ProtocolError("invalid state, game phase, or set play")
    teams = []
    offset = HEADER.size
    for _ in range(2):
        fields = TEAM.unpack_from(data, offset)
        offset += TEAM.size
        players = tuple(PlayerInfo(*PLAYER.unpack_from(data, offset + i * PLAYER.size)) for i in range(MAX_PLAYERS))
        offset += MAX_PLAYERS * PLAYER.size
        if fields[3] > MAX_PLAYERS:
            raise ProtocolError("invalid goalkeeper number")
        teams.append(TeamInfo(*fields, players))
    if teams[0].number == teams[1].number:
        raise ProtocolError("both team numbers are identical")
    return GameControl(packet, count, division, bool(stopped), phase, state, play, bool(half), kick, secs, secondary, tuple(teams))


@dataclass(frozen=True)
class RobotStatus:
    player_number: int
    team_number: int
    fallen: bool
    pose_mm_rad: tuple[float, float, float]
    ball_age_s: float
    ball_relative_mm: tuple[float, float]

    def validate(self) -> None:
        if not 1 <= self.player_number <= MAX_PLAYERS:
            raise ProtocolError("player number must be 1..20")
        if not 0 <= self.team_number <= 255:
            raise ProtocolError("team number must fit uint8")
        if type(self.fallen) is not bool:
            raise ProtocolError("fallen must be a boolean")
        if len(self.pose_mm_rad) != 3 or len(self.ball_relative_mm) != 2:
            raise ProtocolError("pose must contain 3 values and ball must contain 2")
        numbers = (*self.pose_mm_rad, self.ball_age_s, *self.ball_relative_mm)
        if not all(math.isfinite(value) and abs(value) <= 3.4028234663852886e38 for value in numbers):
            raise ProtocolError("status values must be finite and representable as float32")
        if self.ball_age_s < 0 and self.ball_age_s != -1:
            raise ProtocolError("unseen ball age must be -1, otherwise nonnegative")


def encode_status(status: RobotStatus) -> bytes:
    status.validate()
    return RETURN.pack(b"RGrt", RETURN_VERSION, status.player_number, status.team_number,
                       int(status.fallen), *status.pose_mm_rad, status.ball_age_s, *status.ball_relative_mm)


def decode_status(data: bytes) -> RobotStatus:
    if len(data) != RETURN.size:
        raise ProtocolError("return packet must contain exactly 32 bytes")
    magic, version, player, team, fallen, x, y, theta, age, bx, by = RETURN.unpack(data)
    if magic != b"RGrt" or version != RETURN_VERSION or fallen not in (0, 1):
        raise ProtocolError("invalid return packet header/version/fallen")
    status = RobotStatus(player, team, bool(fallen), (x, y, theta), age, (bx, by))
    status.validate()
    return status


def diagnostic_gate(game: GameControl | None, team_number: int, player_number: int,
                    packet_age_s: float, max_age_s: float = 2.0) -> str:
    """Return an intent for diagnostics, never a motor command.

    max_age_s=2 is a proposed lab watchdog, not an HSL-mandated deadline.
    SET needs separate whistle/event processing in the real B-Human behavior.
    """
    if not 1 <= player_number <= MAX_PLAYERS:
        return "HOLD_INVALID_PLAYER"
    if game is None or not math.isfinite(packet_age_s) or not 0 <= packet_age_s <= max_age_s:
        return "HOLD_STALE_GAMECONTROL"
    if game.stopped:
        return "HOLD_GC_STOP"
    try:
        team = game.team(team_number)
    except ProtocolError:
        return "HOLD_UNKNOWN_TEAM"
    if team.players[player_number - 1].penalty:
        return "HOLD_PENALIZED"
    if game.game_phase == 3:
        return "HOLD_TIMEOUT"
    return {1: "POSITION_FOR_READY", 3: "PLAY_ALLOWED"}.get(game.state, "HOLD_" + game.state_name)


def team_port(team_number: int) -> int:
    if not 0 <= team_number <= 255:
        raise ProtocolError("team number must fit uint8")
    return 10000 + team_number


def check_team_payload(payload: bytes, remaining_budget: int) -> None:
    if len(payload) > TEAM_PAYLOAD_LIMIT:
        raise ProtocolError("team UDP payload exceeds 512 bytes")
    if remaining_budget <= 0:
        raise ProtocolError("team message budget exhausted")
