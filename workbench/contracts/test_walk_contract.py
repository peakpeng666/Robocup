#!/usr/bin/env python3
"""Counterexample tests for the walk-policy I/O contract comparator.

Each mutation takes a real probe dump (walk-probe.csv), corrupts it in one
specific way that violates the production contract, and asserts that
compare_walk_contract.py rejects it (exit code 3 / verdict FAIL). A final
case asserts the unmodified dump passes (exit code 0).

The dump is located via WALK_CONTRACT_CSV or the newest
workbench/runs/*_walk_contract/walk-probe.csv; all tests skip if none exists.
"""
import glob
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
COMPARE = os.path.join(HERE, "compare_walk_contract.py")
WORKBENCH = os.path.dirname(HERE)


def find_csv():
    candidate = os.environ.get("WALK_CONTRACT_CSV")
    if candidate and os.path.exists(candidate):
        return candidate
    runs = sorted(glob.glob(os.path.join(WORKBENCH, "runs", "*_walk_contract", "walk-probe.csv")))
    return runs[-1] if runs else None


CSV = find_csv()


def run_compare(csv_path, out_dir):
    report = os.path.join(out_dir, "compare-report.json")
    proc = subprocess.run([sys.executable, COMPARE, csv_path, "-o", report],
                          capture_output=True, text=True, timeout=300)
    return proc, report


@unittest.skipUnless(CSV, "no probe dump found (run workbench/contracts/run-probe.sh first)")
class TestWalkContractCounterexamples(unittest.TestCase):
    maxDiff = None

    def mutate(self, fn):
        with open(CSV, "r", errors="replace") as stream:
            lines = stream.read().splitlines(keepends=True)
        mutated = fn(lines)
        tmp = tempfile.mkdtemp(prefix="walk-contract-test-")
        path = os.path.join(tmp, "walk-probe.csv")
        with open(path, "w") as stream:
            stream.writelines(mutated)
        proc, report = run_compare(path, tmp)
        with open(report) as stream:
            result = json.load(stream)
        return proc, result

    def test_a_swapped_history_frames_fail(self):
        """(a) Swapping two history ring entries must fail the history reconstruction."""
        def swap(lines):
            # pick the first policy group whose ring entries 3 and 4 actually differ
            # (during stand/init the buffer holds repeated identical frames)
            by_id = {}
            for i, line in enumerate(lines):
                parts = line.split(",")
                if parts[0] == "HIST" and parts[3] in ("3", "4"):
                    by_id.setdefault(parts[2], {})[parts[3]] = i
            for indices in by_id.values():
                if "3" in indices and "4" in indices:
                    i3, i4 = indices["3"], indices["4"]
                    p3, p4 = lines[i3].split(","), lines[i4].split(",")
                    if p3[4:] == p4[4:]:
                        continue
                    # swap payloads, keep the HIST,frame,id,idx headers in place
                    p3[4:], p4[4:] = p4[4:], p3[4:]
                    lines[i3], lines[i4] = ",".join(p3), ",".join(p4)
                    return lines
            raise AssertionError("no HIST group with differing indices 3 and 4 found")
        proc, result = self.mutate(swap)
        self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["checks"]["history_reconstruction"]["status"], "FAIL")

    def test_b_command_mm_instead_of_m_fails(self):
        """(b) Command scaled by 1000 (mm/m confusion) must fail the command segment."""
        def scale(lines):
            out = []
            for line in lines:
                parts = line.split(",")
                if parts[0] == "CTX":
                    parts[4] = "%.9g" % (float(parts[4]) * 1000.0)
                    parts[5] = "%.9g" % (float(parts[5]) * 1000.0)
                    line = ",".join(parts)
                out.append(line)
            return out
        proc, result = self.mutate(scale)
        self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
        self.assertEqual(result["checks"]["input_encoding"]["command"]["status"], "FAIL")

    def test_c_gravity_sign_flip_fails(self):
        """(c) Flipped gravity sign (orientation convention error) must fail."""
        def flip(lines):
            out = []
            for line in lines:
                parts = line.split(",")
                if parts[0] == "HIST":
                    for k in range(4, 7):  # gravity xyz of the dumped ring entry
                        parts[k] = "%.9g" % (-float(parts[k]))
                    line = ",".join(parts)
                out.append(line)
            return out
        proc, result = self.mutate(flip)
        self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
        self.assertEqual(result["checks"]["history_reconstruction"]["status"], "FAIL")

    def test_d_output_dim13_as_joint_target_fails(self):
        """(d) Using the 13th raw output (frequency) as joint targets must fail decoding."""
        def stuff(lines):
            out = []
            for line in lines:
                parts = line.split(",")
                if parts[0] == "OUT":
                    dim13 = parts[3 + 12]  # raw output index 12 = frequency channel
                    for j in range(12):
                        parts[3 + 13 + j] = dim13  # overwrite dumped decoded targets
                    line = ",".join(parts)
                out.append(line)
            return out
        proc, result = self.mutate(stuff)
        self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
        self.assertEqual(result["checks"]["output_decoding"]["targets"]["status"], "FAIL")

    def test_unmodified_dump_passes(self):
        tmp = tempfile.mkdtemp(prefix="walk-contract-test-")
        proc, report = run_compare(CSV, tmp)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("verdict: PASS", proc.stdout)

    def test_missing_all_output_records_fails(self):
        proc, result = self.mutate(lambda lines: [line for line in lines if not line.startswith('OUT,')])
        self.assertEqual(proc.returncode, 3, proc.stdout+proc.stderr)
        self.assertEqual(result['verdict'], 'FAIL')

    def test_metadata_only_fails(self):
        proc, result = self.mutate(lambda lines: [line for line in lines if line.startswith(('META,','LIMITS,'))])
        self.assertEqual(proc.returncode, 3, proc.stdout+proc.stderr)
        self.assertEqual(result['verdict'], 'FAIL')


if __name__ == "__main__":
    unittest.main()
