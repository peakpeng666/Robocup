import pathlib
import sys
import unittest
from inspect_frames import decode_frames

DATA = pathlib.Path(sys.argv.pop(1)).read_bytes()


class Frames(unittest.TestCase):
    def test_actual_cpp_sink(self):
        frames = decode_frames(DATA)
        self.assertEqual([f['time_ns'] for f in frames], [0, 200000000])
        self.assertEqual(frames[0]['teams'][1]['players'][19], (13, 0, 2))
        self.assertEqual(frames[0]['secs_remaining'], -123)

    def test_truncated(self):
        with self.assertRaises(ValueError): decode_frames(DATA[:-1])

    def test_duplicate(self):
        with self.assertRaises(ValueError): decode_frames(DATA[:184] * 2)

    def test_version(self):
        data = bytearray(DATA); data[28] = 19
        with self.assertRaises(ValueError): decode_frames(data)

    def test_team(self):
        data = bytearray(DATA); data[24 + 88] = data[24 + 18]
        with self.assertRaises(ValueError): decode_frames(data)

    def test_penalty(self):
        data = bytearray(DATA); data[24 + 18 + 10] = 255
        with self.assertRaises(ValueError): decode_frames(data)


if __name__ == '__main__': unittest.main()
