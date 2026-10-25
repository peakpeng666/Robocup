#!/usr/bin/env python3
"""Check compiled firmware switcher against recovered physical-joint state semantics.

This validates adapter state transitions without executing vendor firmware or a
simulator. The reference follows the recovered CheckSwitch/Inference dataflow.
"""
import argparse
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location("adapter", Path(__file__).with_name("make_booster_deploy_patch.py"))
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    header = args.output / "BoosterDeployPolicyCodec.h"
    header.write_text(adapter.CODEC)
    driver = args.output / "switcher-check.cpp"
    driver.write_text(r'''#include "BoosterDeployPolicyCodec.h"
#include <iostream>
#include <iomanip>
int main() {
  BoosterFirmwarePolicySwitcher c;
  int reset, enabled;
  std::cout << std::setprecision(9);
  while(std::cin >> reset >> enabled) {
    if(reset) c.reset();
    std::array<float,3> gyro{},gravity{},command{};
    std::array<float,20> position{},velocity{},action{};
    for(float& x:gyro) std::cin>>x;
    for(float& x:gravity) std::cin>>x;
    for(float& x:command) std::cin>>x;
    for(float& x:position) std::cin>>x;
    for(float& x:velocity) std::cin>>x;
    for(float& x:action) std::cin>>x;
    c.select(command, enabled);
    c.encode(gyro,gravity,command,position,velocity);
    const auto target=c.decode(action.data(),enabled);
    std::cout<<c.selected<<' ';
    for(float x:c.history) std::cout<<x<<' ';
    for(const auto& s:c.states) {
      for(float x:s.lastAction) std::cout<<x<<' ';
      for(float x:s.filteredTarget) std::cout<<x<<' ';
    }
    for(float x:target) std::cout<<x<<' ';
    std::cout<<'\n';
  }
}
''')
    binary = args.output / "switcher-check"
    subprocess.run(["c++", "-std=c++17", "-O2", str(driver), "-o", str(binary)], check=True)
    # Firmware .rodata permutations, independently recovered from ARM64 ELF.
    to_physical = np.array([0,4,8,12,1,5,9,13,2,6,10,14,16,18,3,7,11,15,17,19])
    to_policy = np.array([0,4,8,14,1,5,9,15,2,6,10,16,3,7,11,17,12,18,13,19])
    default_physical = np.array([.2,-1.25,0,-.5,.2,1.25,0,.5,-.15,0,0,.3,-.15,0,-.15,0,0,.3,-.15,0], np.float32)
    commands = np.array([[0,0,0], [0,.12,0], [0,-.12,0], [0,0,.45], [0,0,-.45], [1,0,0],
                         [.3,.3,0], [.2,.3,0], [0,.1,0], [0,.1001,0], [0,0,.1], [0,0,.1001],
                         [.1,0,.3], [.0999,0,.3], [0,.2,.2], [0,.2,.1999]], np.float32)
    rng = np.random.default_rng(16010)
    history = None
    previous_actions = np.zeros((3,20), np.float32)  # Stored in actor/policy order.
    filtered = np.tile(default_physical, (3,1))     # Independent physical-order reference.
    expected, lines, mode_counts = [], [], [0,0,0]
    switches, previous_mode = 0, None
    for i in range(192):
        reset, enabled = i % 47 == 0, i % 23 != 0
        if reset:
            history = None
            previous_actions[:] = 0
            filtered[:] = default_physical
        command = commands[i % len(commands)]
        vx, vy, wz = np.abs(command)
        if enabled and vy > np.float32(.1) and vx < np.float32(.2) and wz < np.float32(.2):
            mode = 1
        elif enabled and wz > np.float32(.1) and vx < np.float32(.1) and vy < np.float32(.1):
            mode = 2
        else:
            mode = 0
        mode_counts[mode] += 1
        switches += previous_mode is not None and mode != previous_mode
        previous_mode = mode
        values = rng.normal(0, 1 if i % 13 else 150, 69).astype(np.float32)
        values[6:9] = command
        gyro, gravity, q, dq, action = values[:3], values[3:6], values[9:29], values[29:49], values[49:]
        frame = np.concatenate([gyro, gravity, command, q-default_physical[to_policy], dq*np.float32(.1), previous_actions[mode]])
        frame = np.clip(frame, -100, 100)
        history = np.tile(frame, (10,1)) if history is None else np.concatenate([history[1:], frame[None]])
        clipped = np.clip(action, -100, 100)
        physical_action = clipped[to_physical].copy()
        physical_action[6] -= np.float32(.2)
        desired = default_physical + np.float32(.25)*physical_action
        # Actual firmware only runs the active actor; its partner receives that raw
        # action and advances its own filter without a second network inference.
        affected = [mode] + ([1 if mode == 0 else 0] if enabled else [])
        for affected_mode in affected:
            previous_actions[affected_mode] = clipped
            filtered[affected_mode] = np.float32(.8)*desired + np.float32(.2)*filtered[affected_mode]
        state = np.concatenate([np.concatenate([previous_actions[k],filtered[k,to_policy]]) for k in range(3)])
        expected.append(np.concatenate([[mode],history.ravel(),state,filtered[mode,to_policy]]))
        lines.append(f"{int(reset)} {int(enabled)} " + " ".join(format(float(x), ".9g") for x in values))
    completed = subprocess.run([str(binary)], input="\n".join(lines)+"\n", text=True, capture_output=True, check=True)
    actual = np.loadtxt(completed.stdout.splitlines(), dtype=np.float32)
    expected = np.array(expected, np.float32)
    errors = np.abs(actual-expected)
    good = np.allclose(actual, expected, rtol=2e-6, atol=4e-6)
    report = {"status": "PASS" if good else "FAIL", "frames": len(expected), "resets": 5,
              "mode_counts": dict(zip(("forward","side","turn"),mode_counts)), "switches": switches,
              "cpp_header_sha256": hashlib.sha256(header.read_bytes()).hexdigest(),
              "selection_exact": bool(np.array_equal(actual[:,0],expected[:,0])),
              "history_max_abs_error": float(errors[:,1:691].max()),
              "state_and_target_max_abs_error": float(errors[:,691:].max()),
              "reference": "Independent physical-joint NumPy reference of recovered PolicySwitcher selection, single shared history, per-actor actions/EMA, and asymmetric shadow updates.",
              "scope": "Adapter arithmetic/state validation; not execution of original ARM firmware or proof of simulation performance."}
    (args.output/"switcher-validation.json").write_text(json.dumps(report,indent=2)+"\n")
    np.savez(args.output/"switcher-vectors.npz",expected=expected,actual=actual)
    print(json.dumps(report,indent=2))
    if not good:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
