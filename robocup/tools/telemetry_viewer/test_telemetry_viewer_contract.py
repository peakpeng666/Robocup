#!/usr/bin/env python3
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
VIEWER_HTML = ROOT / "tools" / "telemetry_viewer" / "index.html"
TELEMETRY_SENDER = ROOT / "src" / "brain" / "src" / "telemetry_sender.cpp"
TELEMETRY_HEADER = ROOT / "src" / "brain" / "include" / "telemetry_sender.h"
BRAIN_CPP = ROOT / "src" / "brain" / "src" / "brain.cpp"
CONFIG_YAML = ROOT / "src" / "brain" / "config" / "config.yaml"
LAUNCH_PY = ROOT / "src" / "brain" / "launch" / "launch.py"


class TelemetryViewerContractTest(unittest.TestCase):
    def test_viewer_displays_decision_and_cost(self):
        html = VIEWER_HTML.read_text(encoding="utf-8")

        self.assertIn("formatCost", html)
        self.assertRegex(html, r"rc-cost[^\n]+formatCost\(r\.cost\)")
        self.assertIn("row('本机 cost'", html)
        self.assertIn("renderTeammateCostRows", html)
        self.assertIn("row('决策'", html)

    def test_viewer_supports_replay_deep_links(self):
        html = VIEWER_HTML.read_text(encoding="utf-8")

        self.assertIn("URLSearchParams", html)
        self.assertIn("loadReplayFromUrl", html)
        self.assertIn("params.get('replay')", html)
        self.assertIn("params.get('t')", html)
        self.assertIn("history.replaceState", html)

    def test_debug_telemetry_is_limited_to_one_udp_packet_per_second(self):
        sender = TELEMETRY_SENDER.read_text(encoding="utf-8")
        header = TELEMETRY_HEADER.read_text(encoding="utf-8")
        brain = BRAIN_CPP.read_text(encoding="utf-8")
        config = CONFIG_YAML.read_text(encoding="utf-8")
        launch = LAUNCH_PY.read_text(encoding="utf-8")

        self.assertIn("constexpr double kRuleMaxTelemetryRateHz = 1.0", sender)
        self.assertIn("constexpr double kMinTelemetryRateHz = 0.1", sender)
        self.assertRegex(sender, r"std::clamp\(rate_hz_,\s*kMinTelemetryRateHz,\s*kRuleMaxTelemetryRateHz\)")
        self.assertIn('"\\"cost\\":" << brain_->data->tmMyCost', sender)
        self.assertIn("double rate_hz_{1.0};", header)
        self.assertIn('declare_parameter<double>("telemetry.rate_hz", 1.0)', brain)
        self.assertRegex(config, r"rate_hz:\s+1\.0\s+#.*1Hz")
        self.assertIn("默认 1Hz", launch)


if __name__ == "__main__":
    unittest.main()
