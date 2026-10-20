"""No-simulation test for the guard_finite NaN diagnostics (k1-training patch).

Verifies that a NaN in logstd (the exact condition that made upstream call the
nonexistent model.reset_logstd) now leads to a clean SystemExit(2) with a
diagnostics file, and that healthy state passes silently.
"""
import json
import os
import sys
import tempfile

import torch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "IsaacGymRL"))
from utils.model import ActorCritic  # noqa: E402
from utils.bh_common import guard_finite  # noqa: E402


def main():
    model = ActorCritic(num_act=3, num_obs=5, num_privileged_obs=2)
    tmp = tempfile.mkdtemp()
    diag = os.path.join(tmp, "nan_diag.json")

    # 1) healthy state: must not raise
    guard_finite(model, {"loss": 0.5, "entropy": -3.2}, diag)
    assert not os.path.exists(diag), "healthy state must not write diagnostics"
    print("PASS: healthy state passes silently")

    # 2) NaN in logstd (upstream trigger condition): must exit(2) with diagnostics
    with torch.no_grad():
        model.logstd.fill_(float("nan"))
    try:
        guard_finite(model, {"loss": 0.5}, diag)
    except SystemExit as e:
        assert e.code == 2, "exit code must be 2, got %r" % (e.code,)
        assert os.path.exists(diag), "diagnostics file missing"
        payload = json.load(open(diag))
        assert any("logstd" in b or b.startswith("param:") for b in payload["bad"]), payload["bad"]
        assert any(v != v for v in payload["logstd"]), "logstd value not captured"
        print("PASS: NaN logstd -> SystemExit(2), diagnostics at", diag)
        print(json.dumps({k: payload[k] for k in ("n_bad", "bad", "hint")}, ensure_ascii=False, indent=2))
        return 0
    raise AssertionError("guard_finite did not exit on NaN logstd")


if __name__ == "__main__":
    sys.exit(main())
