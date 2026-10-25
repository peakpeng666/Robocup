#!/usr/bin/env python3
"""Compare compiled adapter codec against upstream Torch methods over real stateful sequences."""
import argparse
import ast
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch


def literal_keyword(tree, name):
    return next(ast.literal_eval(node.value) for node in ast.walk(tree)
                if isinstance(node, ast.keyword) and node.arg == name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--right-elbow-observation-offset", type=float, default=0,
                        help="Experimental offset; verified firmware 1.6 and public deploy both use zero.")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location("adapter", Path(__file__).with_name("make_booster_deploy_patch.py"))
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    cfg_ast = ast.parse((args.source / "tasks/locomotion/robots/k1/__init__.py").read_text())
    robot_ast = ast.parse((args.source / "booster_deploy/robots/k1.py").read_text())
    real_names = literal_keyword(robot_ast, "joint_names")
    policy_names = literal_keyword(cfg_ast, "policy_joint_names")
    default_position = np.array(literal_keyword(cfg_ast, "default_joint_pos"), dtype=np.float32)
    real_to_policy = np.array([real_names.index(name) for name in policy_names])
    assert np.array_equal(default_position[real_to_policy], np.array(adapter.DEFAULT, np.float32))
    source_path = args.source / "tasks/locomotion/locomotion.py"
    source_ast = ast.parse(source_path.read_text())
    upstream_class = next(n for n in source_ast.body if isinstance(n, ast.ClassDef) and n.name == "LocomotionPolicy")
    methods = [n for n in upstream_class.body if isinstance(n, ast.FunctionDef)
               and n.name in ("_action_to_targets", "_initialize_obs_history")]
    namespace = {"torch": torch}
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(source_path), "exec"), namespace)
    reference = SimpleNamespace(cfg=SimpleNamespace(action_filter=.8, arm_action_fix_offset=.2, history_init="repeat"),
                                default_joint_pos=torch.from_numpy(default_position),
                                real2sim_joint_map=torch.from_numpy(real_to_policy),
                                arm_action_fix_index=real_names.index("right_elbow_pitch_joint"),
                                action_scale=torch.full((20,), .25), actor_obs_history_length=10)
    reference.filtered_dof_target = reference.default_joint_pos.clone()
    header = args.output / "BoosterDeployPolicyCodec.h"
    header.write_text(adapter.CODEC)
    driver = args.output / "codec-check.cpp"
    driver.write_text(r'''#include "BoosterDeployPolicyCodec.h"
#include <iostream>
#include <iomanip>
#include <limits>
int main() {
  BoosterDeployPolicyCodec c;
  int reset;
  float elbowObservationOffset;
  std::cout << std::setprecision(9);
  while(std::cin >> reset >> elbowObservationOffset) {
    if(reset) c.reset();
    std::array<float,3> gyro{},gravity{},command{};
    std::array<float,20> position{},velocity{},action{};
    for(float& x:gyro) std::cin>>x;
    for(float& x:gravity) std::cin>>x;
    for(float& x:command) std::cin>>x;
    for(float& x:position) std::cin>>x;
    for(float& x:velocity) std::cin>>x;
    for(float& x:action) std::cin>>x;
    c.encode(gyro,gravity,command,position,velocity,elbowObservationOffset);
    const auto target = c.decode(action.data());
    for(float x:c.history) std::cout<<x<<' ';
    for(float x:target) std::cout<<x<<' ';
    std::cout<<'\n';
  }
  std::array<float,20> invalid{}; invalid[0] = std::numeric_limits<float>::quiet_NaN();
  try { c.decode(invalid.data()); return 42; }
  catch(const std::runtime_error&) {}
}
''')
    binary = args.output / "codec-check"
    subprocess.run(["c++", "-std=c++17", "-O2", str(driver), "-o", str(binary)], check=True)
    rng = np.random.default_rng(20261022)
    expected, inputs = [], []
    history = None
    last_action = torch.zeros(20)
    for i in range(128):
        reset = i % 17 == 0
        if reset:
            history = None
            last_action.zero_()
            reference.filtered_dof_target = reference.default_joint_pos.clone()
        # Exercise clipping, full-joint remapping, repeat initialization, rolling history and reset.
        state = rng.normal(0, 1 if i % 9 else 200, size=69).astype(np.float32)
        gyro, gravity, command = (torch.from_numpy(state[a:b]) for a, b in ((0,3),(3,6),(6,9)))
        q, qd, action = (torch.from_numpy(state[a:b]) for a, b in ((9,29),(29,49),(49,69)))
        q_offset = q - reference.default_joint_pos[reference.real2sim_joint_map]
        q_offset[9] += args.right_elbow_observation_offset
        frame = torch.cat((gyro, gravity, command, q_offset,
                           qd * .1, last_action)).clamp(-100,100)
        if history is None:
            history = namespace["_initialize_obs_history"](reference, frame)
        else:
            history = history.roll(-1, 0)
            history[-1] = frame
        last_action = action.clamp(-100,100)
        target = namespace["_action_to_targets"](reference, last_action)
        expected.append(torch.cat((history.flatten(),target[reference.real2sim_joint_map])).numpy())
        inputs.append(str(int(reset)) + " " + str(args.right_elbow_observation_offset) + " "
                      + " ".join(format(float(x), ".9g") for x in state))
    completed = subprocess.run([str(binary)], input="\n".join(inputs)+"\n", text=True, capture_output=True, check=True)
    actual = np.loadtxt(completed.stdout.splitlines(), dtype=np.float32)
    expected = np.array(expected)
    errors = np.abs(actual - expected)
    ok = np.allclose(actual, expected, rtol=2e-6, atol=2e-6)
    report = {"status": "PASS" if ok else "FAIL", "frames": 128, "resets": 8,
              "cpp_codec_sha256": hashlib.sha256(header.read_bytes()).hexdigest(),
              "upstream_source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
              "max_abs_error": float(errors.max()), "history_max_abs_error": float(errors[:,:690].max()),
              "target_max_abs_error": float(errors[:,690:].max()), "nonfinite_action_rejected": completed.returncode == 0,
              "right_elbow_observation_offset_rad": args.right_elbow_observation_offset,
              "reference": "Upstream _initialize_obs_history and _action_to_targets executed unmodified; observation expression and history roll with explicit optional experimental elbow bias."}
    (args.output / "codec-validation.json").write_text(json.dumps(report, indent=2)+"\n")
    np.savez(args.output / "codec-vectors.npz", expected=expected, actual=actual)
    print(json.dumps(report,indent=2))
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
