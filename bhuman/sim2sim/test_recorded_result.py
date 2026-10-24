#!/usr/bin/env python3
"""CPU-only regression tests for recorded-result evidence validation.

These tests do not import a simulator, load policies, or change archived runs.
The historical PASS fixture is read-only; adversarial cases use temporary files.
"""
from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import check_sim2sim_gate as gate  # noqa: E402


class RecordedResultTests(unittest.TestCase):
    fixture_root = ROOT / gate.RECORDED_RUN

    def setUp(self) -> None:
        self.historical = json.loads((self.fixture_root / "result.json").read_text(encoding="utf-8"))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.result_path = Path(self.temp.name) / "result.json"

    def check(self, data):
        self.result_path.write_text(json.dumps(data), encoding="utf-8")
        return gate.check_recorded_result(self.result_path)

    def assert_rejected(self, data):
        report = self.check(data)
        self.assertFalse(report["ok"], report)
        self.assertTrue(report["errors"], report)
        return report

    def test_historical_pass_with_original_launch_pd(self) -> None:
        report = gate.check_recorded_result(self.fixture_root / "result.json")
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(self.historical["physics_steps"], 60000)
        self.assertEqual(self.historical["policy_calls"], 6000)

    def test_valid_pass_without_optional_launch(self) -> None:
        self.assertTrue(self.check(self.historical)["ok"])

    def test_failed_result_and_false_check_are_rejected(self) -> None:
        data = copy.deepcopy(self.historical)
        data["status"] = "FAIL"
        data["checks"]["no_fall"] = False
        report = self.assert_rejected(data)
        self.assertEqual(report["status"], "FAIL")

    def test_verdict_must_be_pass_and_skip_is_not_relabelled(self) -> None:
        for value in ("FAIL", "SKIP", "WARN", "", None, True, 1, [], {}):
            with self.subTest(status=value):
                data = copy.deepcopy(self.historical)
                data["status"] = value
                report = self.assert_rejected(data)
                self.assertEqual(report["status"], value)

    def test_each_required_check_must_be_boolean_true(self) -> None:
        for name in gate.REQUIRED_CHECKS:
            for value in (False, None, 0, 1, "true", [], {}):
                with self.subTest(check=name, value=value):
                    data = copy.deepcopy(self.historical)
                    data["checks"][name] = value
                    self.assert_rejected(data)
            data = copy.deepcopy(self.historical)
            del data["checks"][name]
            self.assert_rejected(data)

    def test_missing_required_fields_fail(self) -> None:
        for name in gate.REQUIRED_RESULT_KEYS:
            with self.subTest(field=name):
                data = copy.deepcopy(self.historical)
                del data[name]
                self.assert_rejected(data)

    def test_checks_must_be_an_object(self) -> None:
        for value in (None, [], True, "PASS", 1):
            with self.subTest(checks=value):
                data = copy.deepcopy(self.historical)
                data["checks"] = value
                self.assert_rejected(data)

    def test_counts_require_positive_json_integers(self) -> None:
        bad = (0, -1, None, True, False, 1.0, 0.5, float("nan"),
               float("inf"), -float("inf"), "6000", [], {})
        for name in ("physics_steps", "policy_calls"):
            for value in bad:
                with self.subTest(field=name, value=value):
                    data = copy.deepcopy(self.historical)
                    data[name] = value
                    self.assert_rejected(data)

    def test_zero_negative_and_wrong_ratio_fail(self) -> None:
        for calls, steps in ((0, 0), (-1, -10), (6000, 59999),
                             (6000, 60001), ("6000", "60000"),
                             (True, 10), (1, True)):
            with self.subTest(calls=calls, steps=steps):
                data = copy.deepcopy(self.historical)
                data["policy_calls"], data["physics_steps"] = calls, steps
                self.assert_rejected(data)

    def test_observation_count_and_width_are_consistent(self) -> None:
        for shape in ([0, 344], [-1, 344], [True, 344], [6000.0, 344],
                      [float("nan"), 344], [6000, 344.0], [6000, 59],
                      [5999, 344], [6000], {}, "6000,344"):
            with self.subTest(shape=shape):
                data = copy.deepcopy(self.historical)
                data["observations_shape"] = shape
                self.assert_rejected(data)

    def test_actor_only_requires_explicit_false(self) -> None:
        for identity in ({}, None, [], True, {"critic_loaded": True},
                         {"critic_loaded": 0}, {"critic_loaded": "false"}):
            with self.subTest(identity=identity):
                data = copy.deepcopy(self.historical)
                data["policy_identity"] = identity
                self.assert_rejected(data)

    def test_robot_disconnected_requires_explicit_false(self) -> None:
        for value in (True, None, 0, "false"):
            with self.subTest(robot_connected=value):
                data = copy.deepcopy(self.historical)
                data["robot_connected"] = value
                self.assert_rejected(data)

    def test_malformed_and_nonobject_result_fail_closed(self) -> None:
        for data in (None, [], True, "PASS", 1):
            with self.subTest(result=data):
                self.assert_rejected(data)
        self.result_path.write_text("{bad json", encoding="utf-8")
        self.assertFalse(gate.check_recorded_result(self.result_path)["ok"])

    def test_missing_result_cannot_be_successful_evidence(self) -> None:
        report = gate.check_recorded_result(self.result_path)
        self.assertFalse(report["ok"])
        self.assertTrue(report["errors"])

    def test_missing_live_stack_remains_explicit_skip(self) -> None:
        # Exercise the existing aggregate distinction: contract checks can pass
        # while runtime acceptance is explicitly skipped. No simulator imports.
        probe = {"ready": False, "skip_reasons": ["test: no runtime"],
                 "auto_run_requested": False}
        with patch.object(gate, "check_scripts_present", return_value=[]), \
             patch.object(gate, "official_train_pd_untouched"), \
             patch.object(gate, "probe_stack", return_value=probe):
            report = gate.run(Path(self.temp.name))
        self.assertTrue(report["ok"], report)
        self.assertTrue(report["skipped"], report)
        self.assertFalse(report["implemented"])
        self.assertIsNone(report["recorded"])
        self.assertIn("live run-mujoco.sh not invoked", report["notes"])
        self.assertTrue(any("recorded result missing" in item for item in report["warnings"]))


def run(repo: Path | None = None) -> dict:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RecordedResultTests)
    if repo is not None:
        for test in suite:
            test.fixture_root = repo / "bhuman/sim2sim" / gate.RECORDED_RUN
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    errors = [detail for _, detail in result.errors + result.failures]
    return {
        "ok": result.wasSuccessful(),
        "errors": errors,
        "notes": [f"recorded-result regressions: {result.testsRun} tests "
                  + ("PASS" if result.wasSuccessful() else "FAIL")],
        "tests_run": result.testsRun,
        "output": stream.getvalue(),
    }


if __name__ == "__main__":
    report = run()
    print(report["output"], end="")
    raise SystemExit(0 if report["ok"] else 1)

