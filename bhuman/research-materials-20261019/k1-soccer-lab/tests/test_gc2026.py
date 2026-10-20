import dataclasses
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from k1lab.gc2026 import *


class OfficialABI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("cc") or sys.byteorder != "little":
            raise unittest.SkipTest("official C byte fixture requires a little-endian C compiler host")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.exe = str(Path(cls.temporary.name) / "abi_fixture")
        subprocess.run(["cc", "-std=c11", "-I", str(ROOT / "vendor/hsl2026"),
                        str(ROOT / "tests/abi_fixture.c"), "-o", cls.exe], check=True)
        cls.control = subprocess.check_output([cls.exe, "control"])

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_layout_matches_official_c_header(self):
        self.assertEqual(subprocess.check_output([self.exe, "sizes"]).decode().strip(), "158 32 70 3")
        self.assertEqual(CONTROL_SIZE, 158)

    def test_c_control_fixture_fields(self):
        game = decode_control(self.control)
        self.assertEqual((game.packet_number, game.seconds_remaining, game.secondary_time), (251, -5, 17))
        self.assertTrue(game.stopped)
        self.assertEqual(game.state_name, "PLAYING")
        self.assertEqual(game.team(42).players[1], PlayerInfo(10, 12, 1))
        self.assertEqual(game.team(43).message_budget, 1234)

    def test_return_bytes_match_c_fixture_and_units(self):
        reference = subprocess.check_output([self.exe, "status"])
        status = RobotStatus(2, 42, False, (1500.25, -220.5, 0.75), 0.125, (450.5, -13.25))
        self.assertEqual(encode_status(status), reference)
        self.assertEqual(decode_status(reference), status)

    def test_rejects_monitor_truth_wrong_version_and_length(self):
        for data in (b"RGTD" + self.control[4:], self.control[:4] + bytes([19]) + self.control[5:], self.control[:-1], self.control + b"\0"):
            with self.subTest(data=data[:6]):
                with self.assertRaises(ProtocolError):
                    decode_control(data)

    def test_stop_penalty_and_stale_gate(self):
        game = decode_control(self.control)
        self.assertEqual(diagnostic_gate(game, 42, 1, 0.1), "HOLD_GC_STOP")
        game = dataclasses.replace(game, stopped=False)
        self.assertEqual(diagnostic_gate(game, 42, 2, 0.1), "HOLD_PENALIZED")
        self.assertEqual(diagnostic_gate(game, 42, 1, 0.1), "PLAY_ALLOWED")
        self.assertEqual(diagnostic_gate(game, 42, 1, 2.01), "HOLD_STALE_GAMECONTROL")
        self.assertEqual(diagnostic_gate(game, 99, 1, 0.1), "HOLD_UNKNOWN_TEAM")

    def test_ready_set_timeout_are_distinct(self):
        game = dataclasses.replace(decode_control(self.control), stopped=False)
        self.assertEqual(diagnostic_gate(dataclasses.replace(game, state=1), 42, 1, 0), "POSITION_FOR_READY")
        self.assertEqual(diagnostic_gate(dataclasses.replace(game, state=2), 42, 1, 0), "HOLD_SET")
        self.assertEqual(diagnostic_gate(dataclasses.replace(game, game_phase=3), 42, 1, 0), "HOLD_TIMEOUT")


class InvalidInputs(unittest.TestCase):
    def test_sequence_wrap_duplicates_reordering_and_restart(self):
        sequence = PacketSequence()
        self.assertTrue(sequence.accept(255, 1.0))
        self.assertTrue(sequence.accept(0, 1.5))
        self.assertFalse(sequence.accept(0, 1.8))
        self.assertFalse(sequence.accept(254, 2.0))
        self.assertEqual(sequence.last_time, 1.5)
        self.assertTrue(sequence.accept(5, 4.0))

    def test_bad_status_cannot_be_transmitted(self):
        valid = RobotStatus(1, 1, False, (0., 0., 0.), -1., (0., 0.))
        for status in (dataclasses.replace(valid, player_number=0), dataclasses.replace(valid, pose_mm_rad=(math.nan, 0., 0.)),
                       dataclasses.replace(valid, pose_mm_rad=(1e300, 0., 0.)),
                       dataclasses.replace(valid, ball_age_s=-0.5), dataclasses.replace(valid, fallen=255)):
            with self.assertRaises(ProtocolError):
                encode_status(status)

    def test_team_budget_and_packet_limit(self):
        self.assertEqual(team_port(42), 10042)
        check_team_payload(bytes(512), 1)
        with self.assertRaises(ProtocolError): check_team_payload(bytes(513), 1)
        with self.assertRaises(ProtocolError): check_team_payload(b"hello", 0)


if __name__ == "__main__":
    unittest.main()
