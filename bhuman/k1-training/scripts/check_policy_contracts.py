#!/usr/bin/env python3
"""Static B-Human K1 policy-contract gate (no GPU / Isaac Gym / weights required).

Cross-checks walk/kick/standup observation and action dimensions across:
  * IsaacGymRL YAML (frozen MachineLearning tree and k1-training working copy)
  * Deploy C++ .cfg (ML pre-trained, k1-training copy, BHumanCodeRelease)
  * ActorCritic constructor / Linear I/O in model.py
  * Documented layout sums (policy-contract-v1)
  * Recorded official ONNX I/O in manifests/models-v2.json
  * Optional on-disk .pth/.onnx/.pt hashes when the files exist

Missing weight binaries are recorded as warnings, not failures: GitHub
snapshots gitignore *.onnx/*.pth/*.pt. Contract-number mismatches fail.

Exit 0 = contracts consistent. Exit 1 = mismatch or missing required source.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from importlib.util import module_from_spec, spec_from_file_location

try:
    import yaml
except ImportError:  # pragma: no cover - stdlib fallback is enough for env keys
    yaml = None


UPSTREAM_ML = "c3fed817e6e8fd06418bea824b1f1ab0157379d2"
UPSTREAM_BHUMAN = "2e3374ba896da8288607f9a1881b876642fe18b8"

# Frozen K1 contracts. Kick output is the walk numOutput (not restated in ball blocks).
K1_CONTRACTS = {
    "walk": {
        "task": "K1",
        "obs": 344,
        "act": 13,
        "priv": 16,
        "history_size": 10,
        "base_obs": 32,
        "last_obs": 24,
        "layout_frame": [3, 3, 12, 12, 2],  # gravity, gyro, legs, prev 12 acts, ball xy=0
        "layout_tail": [3, 2, 12, 1, 3, 2, 1],  # cmd, gait, vel, freq, ball flags, dir, range
        "yaml_name": "K1.yaml",
        "onnx_names": ("K1_walk.onnx",),
        "pth_relpaths": (
            "bhuman/k1-training/src/IsaacGymRL/pre-trained/WalkAndKick/K1_walk.pth",
        ),
        "known_pth_sha256": "7daa13e4184602bbeca4b15f0b803f8351d98209815fd07d14202c8e457ba0ff",
        "known_onnx_sha256": "9d1ec18504cb9d05ec708b9430783a2331cabf5415fc0db81c6318472e948e8f",
    },
    "kick": {
        "task": "K1_Ball",
        "obs": 59,
        "act": 13,
        "priv": 16,
        "yaml_name": "K1_Ball.yaml",
        "layout": [3, 3, 2, 1, 2, 12, 12, 13, 1, 1, 1, 2, 1, 2, 1, 2],
        "onnx_names": ("K1_kick_inner.onnx", "K1_kick_inner_soft.onnx", "K1_kick_90degree.onnx"),
        "pth_relpaths": (
            "bhuman/k1-training/src/IsaacGymRL/pre-trained/WalkAndKick/K1_kick_inner.pth",
        ),
        "known_onnx_sha256": {
            "K1_kick_inner.onnx": "7fb9ea33c36e14332861025f22e92f2f4a7ae7681f4532bdd6e1e78975fe3452",
            "K1_kick_inner_soft.onnx": "7943b41c76c841b663d84024168be5ef4ef0af4f5a3524415a40f8665f028da2",
        },
    },
    "standup": {
        "task": "K1_Stand_Up",
        "obs": 73,
        "act": 22,
        "priv": 38,
        "yaml_name": "K1_Stand_Up.yaml",
        "layout": [3, 3, 1, 22, 22, 22],
        "onnx_names": ("K1.onnx",),
        "pth_relpaths": (
            "bhuman/k1-training/src/IsaacGymRL/pre-trained/GetUp/K1_stand_up.pt",
        ),
        "known_onnx_sha256": "44ee5ddb2b64c79b511ed0914ec40fee81b03987061b130ed17bf546e47cc486",
    },
    "fast_standup": {
        "task": "K1_fast_standup",
        "obs": 72,
        "act": 22,
        "note": "Deploy-only; not the IsaacGymRL ActorCritic standup task.",
        "onnx_names": ("K1_fast_standup.onnx", "K1_fast.onnx"),
        "known_onnx_sha256": "adae2f0021e3a6c9adabe7df6095e01c86b5226c72834f475ff164cd9ee8aba5",
    },
}

# B-Human T1 (same IsaacGymRL family). Must stay distinct from K1 and from Huoshen T1.
T1_CONTRACTS = {
    "walk": {"obs": 365, "act": 14, "base_obs": 34, "last_obs": 25, "history_size": 10},
    "kick": {"obs": 62, "act": 14},
    "standup": {"obs": 76, "act": 23, "priv": 39},
}

# Huoshen / Science Robotics 2026 public T1 reactive skill (docs only; not in this tree).
HUOSHEN_DOC_CONTRACT = {
    "platform": "Booster T1 (not K1)",
    "obs": 58,
    "stack": 50,
    "history_embedding_dim": 64,
    "act": 15,
    "policy_hz": 50,
    "vision_hz": 25,
    "delay_ms": "116±18",
}

ISAAC_TREES = (
    "bhuman/MachineLearning/IsaacGymRL",
    "bhuman/k1-training/src/IsaacGymRL",
)

WALK_CFG_RELPATHS = (
    "bhuman/MachineLearning/IsaacGymRL/pre-trained/WalkAndKick/walkingEngine_k1.cfg",
    "bhuman/k1-training/src/IsaacGymRL/pre-trained/WalkAndKick/walkingEngine_k1.cfg",
    "bhuman/k1-training/src/Config/Robots/Default/K1/walkingEngine.cfg",
    "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg",
)

GETUP_CFG_RELPATHS = (
    "bhuman/MachineLearning/IsaacGymRL/pre-trained/GetUp/getUpEngine_k1.cfg",
    "bhuman/k1-training/src/IsaacGymRL/pre-trained/GetUp/getUpEngine_k1.cfg",
    "bhuman/k1-training/src/Config/Robots/Default/K1/getUpEngine.cfg",
    "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg",
)

HUOSHEN_MARKERS = (
    "history_embedding_dim",
    "num_stack",
    "huoshen",
    "HiFAR",
    "hifar",
)

# Official ONNX locations (gitignored binaries; hashes live in models-v2.json).
OFFICIAL_ONNX_RELPATHS = {
    "K1_walk.onnx": "bhuman/BHumanCodeRelease/Config/NeuralNets/Walk/K1_walk.onnx",
    "K1_kick_inner.onnx": "bhuman/BHumanCodeRelease/Config/NeuralNets/Walk/K1_kick_inner.onnx",
    "K1_kick_inner_soft.onnx": "bhuman/BHumanCodeRelease/Config/NeuralNets/Walk/K1_kick_inner_soft.onnx",
    "K1.onnx": "bhuman/BHumanCodeRelease/Config/NeuralNets/GetUpEngine/K1.onnx",
    "K1_fast_standup.onnx": "bhuman/BHumanCodeRelease/Config/NeuralNets/GetUpEngine/K1_fast_standup.onnx",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_git(repo: Path, *args: str) -> str:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(repo), *args],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return out.strip()


def load_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise ValueError(f"{path}: YAML root is not a mapping")
        return data
    env: dict[str, Any] = {}
    in_env = False
    for raw in text.splitlines():
        if raw.startswith("env:"):
            in_env = True
            continue
        if in_env and raw and not raw.startswith(" ") and not raw.startswith("\t"):
            break
        if in_env:
            match = re.match(r"\s+([A-Za-z0-9_]+):\s*(\S+)", raw)
            if match:
                key, value = match.group(1), match.group(2)
                if re.fullmatch(r"-?\d+", value):
                    env[key] = int(value)
                elif re.fullmatch(r"-?\d+\.\d+", value):
                    env[key] = float(value)
                else:
                    env[key] = value
    return {"env": env}


def extract_brace_block(text: str, name: str) -> str | None:
    token = name + " ="
    idx = text.find(token)
    if idx < 0:
        token = name + "="
        idx = text.find(token)
    if idx < 0:
        return None
    brace = text.find("{", idx)
    if brace < 0:
        return None
    depth = 0
    for pos, char in enumerate(text[brace:], start=brace):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[brace + 1 : pos]
    return None


def parse_assign_ints(block: str) -> dict[str, int]:
    found: dict[str, int] = {}
    for match in re.finditer(r"\b(numInput|numOutput|numInputFast|numOutputFast)\s*=\s*(-?\d+)\s*;", block):
        found[match.group(1)] = int(match.group(2))
    return found


def parse_getup_cfg(path: Path) -> dict[str, int]:
    return parse_assign_ints(path.read_text(encoding="utf-8", errors="replace"))


def parse_walk_cfg(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    walk = parse_assign_ints(extract_brace_block(text, "walkNeuronalNetworkParameters") or "")
    kick_blocks = {}
    for name in ("ballNetworkParameters", "oldBallNetworkParameters", "ballStealNetworkParameters"):
        block = extract_brace_block(text, name)
        if block is not None:
            kick_blocks[name] = parse_assign_ints(block)
    return {"walk": walk, "kick_blocks": kick_blocks, "path": str(path)}


def env_contract(cfg: dict[str, Any]) -> dict[str, Any]:
    env = cfg.get("env") or {}
    keys = (
        "num_observations",
        "num_actions",
        "num_privileged_obs",
        "num_base_observations",
        "num_last_observations",
        "history_size",
    )
    return {key: env.get(key) for key in keys if key in env}


def probe_environment() -> dict[str, Any]:
    nvidia = shutil.which("nvidia-smi")
    gpu_name = None
    if nvidia:
        try:
            gpu_name = subprocess.check_output(
                [nvidia, "--query-gpu=name,memory.total", "--format=csv,noheader"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            gpu_name = "nvidia-smi present but query failed"
    modules = {}
    for name in ("torch", "isaacgym", "onnx", "onnxruntime", "mujoco"):
        try:
            __import__(name)
            modules[name] = True
        except Exception:
            modules[name] = False
    bh_py = Path(os.environ.get("BH_PY") or Path.home() / ".venvs/bh-gym/bin/python")
    isaacsim_py = Path.home() / ".venvs/isaacsim-gui/bin/python"
    return {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "platform": platform.platform(),
        "nvidia_smi": nvidia,
        "gpu": gpu_name,
        "modules": modules,
        "bh_gym_python_exists": bh_py.exists(),
        "bh_gym_python": str(bh_py),
        "isaacsim_gui_python_exists": isaacsim_py.exists(),
        "can_run_isaac_gym_train": bool(nvidia and modules.get("isaacgym") and bh_py.exists()),
        "can_run_mujoco_sim2sim": bool(isaacsim_py.exists()),
    }


def check_model_py(path: Path, errors: list[str], notes: list[str]) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    actor_in = "torch.nn.Linear(num_obs, 256)" in text
    actor_out = "torch.nn.Linear(128, num_act)" in text
    critic_in = "torch.nn.Linear(num_obs + num_privileged_obs, 256)" in text
    ctor = "def __init__(self, num_act, num_obs, num_privileged_obs)" in text
    ok = actor_in and actor_out and critic_in and ctor
    record = {
        "path": str(path),
        "actor_in_num_obs": actor_in,
        "actor_out_num_act": actor_out,
        "critic_in_obs_plus_priv": critic_in,
        "ctor_order_act_obs_priv": ctor,
        "ok": ok,
    }
    if not ok:
        errors.append(f"ActorCritic I/O wiring unexpected in {path}")
    else:
        notes.append(f"ActorCritic {path}: Linear(num_obs,256) … Linear(128,num_act)")
    return record


def check_history_formula(path: Path, errors: list[str]) -> bool:
    text = path.read_text(encoding="utf-8")
    needle = "self.num_obs = self.num_base_obs * self.num_history + self.num_last_obs"
    if needle not in text:
        errors.append(f"walk history formula missing in {path}")
        return False
    return True


def _load_sibling(repo: Path, relpath: str, name: str):
    path = repo / relpath
    spec = spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(relpath)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_k1_reactive_skeleton(repo: Path, errors: list[str], notes: list[str]) -> dict[str, Any]:
    rel = "bhuman/k1-training/k1-reactive/check_skeleton.py"
    path = repo / rel
    if not path.is_file():
        errors.append(f"missing {rel}")
        return {"ok": False, "missing": True}
    module = _load_sibling(repo, rel, "k1_reactive_check_skeleton")
    report = module.check(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    # Explicit gate rule: YAML may exist; train.py must not see it.
    if report.get("skeleton_yaml_exists") and report.get("unregistered_in_train_py") == "PASS":
        notes.append(
            "unregistered in train.py = PASS "
            "(skeleton YAML exists in k1-reactive/; not a train.py task)"
        )
    elif report.get("skeleton_yaml_exists"):
        errors.append("skeleton YAML exists but unregistered_in_train_py is not PASS")
    if report.get("ok"):
        notes.append("K1_Reactive skeleton is parallel 64→15 and not registered in IsaacGymRL")
    return report


def check_gpu_free_shells(
    repo: Path,
    errors: list[str],
    notes: list[str],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Skill-switch shells, static maps, global docs, unregistered fixture, P0 stubs."""
    out: dict[str, Any] = {}
    specs = (
        (
            "bhuman/k1-training/k1-reactive/test_unregistered_in_train_py.py",
            "unregistered_fixture",
            "k1_reactive_unregistered_fixture",
            True,
        ),
        (
            "bhuman/k1-training/k1-reactive/test_skill_switch_continuity.py",
            "skill_switch_shells",
            "k1_reactive_skill_switch_shells",
            False,
        ),
        (
            "bhuman/k1-training/k1-reactive/test_skill_switch_map.py",
            "skill_switch_map",
            "k1_reactive_skill_switch_map",
            False,
        ),
        (
            "bhuman/k1-training/k1-reactive/test_global_docs.py",
            "global_docs",
            "k1_reactive_global_docs",
            True,
        ),
        (
            "bhuman/k1-training/k1-reactive/test_migrate_table.py",
            "migrate_table",
            "k1_reactive_migrate_table",
            True,
        ),
        (
            "bhuman/k1-training/k1-estimators/test_estimators.py",
            "estimators",
            "k1_estimators",
            True,
        ),
        (
            "bhuman/k1-training/k1-reactive/test_obs_schema.py",
            "obs_schema",
            "k1_reactive_obs_schema",
            True,
        ),
        (
            "bhuman/k1-training/k1-reactive/test_bt_skill_select.py",
            "bt_skill_select",
            "k1_reactive_bt_skill_select",
            True,
        ),
        (
            "bhuman/sim2sim/test_sim2sim_gate.py",
            "sim2sim_gate",
            "k1_sim2sim_gate",
            True,
        ),
        (
            "bhuman/k1-training/k1-switcher/test_switcher_sm.py",
            "switcher_sm",
            "k1_switcher_sm",
            True,
        ),
        (
            "bhuman/k1-training/k1-switcher/test_deploy_call.py",
            "deploy_call",
            "k1_deploy_call",
            True,
        ),
        (
            "bhuman/k1-training/k1-switcher/test_timeseries_contract.py",
            "timeseries_contract",
            "k1_timeseries_contract",
            True,
        ),
        (
            "bhuman/k1-training/k1-estimators/test_estimator_bypass.py",
            "estimator_bypass",
            "k1_estimator_bypass",
            True,
        ),
        (
            "bhuman/k1-training/k1-reactive/test_reactive_hardening.py",
            "reactive_hardening",
            "k1_reactive_hardening",
            True,
        ),
        (
            "bhuman/k1-training/configs/draft-only/test_p1_draft.py",
            "p1_draft",
            "k1_p1_draft",
            True,
        ),
    )
    for rel, key, mod_name, pass_repo in specs:
        if not (repo / rel).is_file():
            errors.append(f"missing {rel}")
            out[key] = {"ok": False, "missing": True}
            continue
        module = _load_sibling(repo, rel, mod_name)
        report = module.run(repo) if pass_repo else module.run()
        out[key] = report
        if key == "skill_switch_shells":
            errors.extend((report.get("anchors") or {}).get("errors") or [])
            if report.get("ok"):
                notes.append(
                    f"skill-switch continuity: {len(report.get('shells') or [])} empty shells, implemented=false"
                )
        else:
            errors.extend(report.get("errors") or [])
            notes.extend(report.get("notes") or [])
        if warnings is not None:
            warnings.extend(report.get("warnings") or [])
        if report.get("skipped"):
            notes.append(f"{key}: skipped (missing optional runtime)")
    return out


def check_reserved_gpu(repo: Path, warnings: list[str], notes: list[str]) -> dict[str, Any]:
    rel = "bhuman/k1-training/scripts/probe_reserved_gpu.py"
    path = repo / rel
    if not path.is_file():
        warnings.append(f"missing reserved GPU probe {rel}")
        return {"ready": False, "skipped": True, "missing": True}
    module = _load_sibling(repo, rel, "k1_reserved_gpu_probe")
    report = module.probe()
    if report.get("skipped"):
        for reason in report.get("skip_reasons") or []:
            warnings.append(f"reserved GPU/bh-gym: {reason}")
        warnings.append("reserved GPU/bh-gym worker not present; skip Isaac Gym / official walk replay")
    else:
        notes.append("reserved GPU/bh-gym worker looks present; templates only (no auto-train)")
    return report


def find_repo_root(explicit: str | None) -> Path:
    if explicit:
        root = Path(explicit).resolve()
        if not (root / "AGENTS.md").exists() or not (root / "bhuman").is_dir():
            raise SystemExit(f"--repo {root} does not look like the Robocup workspace")
        return root
    here = Path(__file__).resolve()
    for candidate in (here.parents[3], Path.cwd(), *here.parents):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate repo root (expected AGENTS.md + bhuman/)")


def append_issue(bucket: list[str], ok: bool, message: str) -> None:
    if not ok:
        bucket.append(message)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=None, help="Robocup workspace root")
    parser.add_argument("--json-out", default=None, help="Write the full report JSON here")
    parser.add_argument(
        "--strict-weights",
        action="store_true",
        help="Fail if documented official .pth/.onnx files are absent (default: warn)",
    )
    args = parser.parse_args()

    repo = find_repo_root(args.repo)
    errors: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []
    trees: dict[str, Any] = {}

    for rel in ISAAC_TREES:
        tree = repo / rel
        trees[rel] = {"exists": tree.is_dir()}
        if not tree.is_dir():
            errors.append(f"missing IsaacGymRL tree: {rel}")
            continue
        yaml_env: dict[str, Any] = {}
        for skill, spec in K1_CONTRACTS.items():
            yaml_name = spec.get("yaml_name")
            if not yaml_name:
                continue
            path = tree / "envs" / yaml_name
            if not path.is_file():
                errors.append(f"missing {path}")
                continue
            contract = env_contract(load_yaml(path))
            yaml_env[skill] = {"path": str(path.relative_to(repo)), **contract}
            append_issue(
                errors,
                contract.get("num_observations") == spec["obs"]
                and contract.get("num_actions") == spec["act"],
                f"{path.name} in {rel}: got {contract.get('num_observations')}→"
                f"{contract.get('num_actions')}, expected {spec['obs']}→{spec['act']}",
            )
            if spec.get("priv") is not None:
                append_issue(
                    errors,
                    contract.get("num_privileged_obs") == spec["priv"],
                    f"{path.name} privileged_obs={contract.get('num_privileged_obs')} "
                    f"expected {spec['priv']}",
                )
            if skill == "walk":
                append_issue(
                    errors,
                    contract.get("num_base_observations") == spec["base_obs"]
                    and contract.get("num_last_observations") == spec["last_obs"]
                    and contract.get("history_size") == spec["history_size"],
                    f"{path.name} history fields {contract} vs "
                    f"{spec['base_obs']}x{spec['history_size']}+{spec['last_obs']}",
                )
                computed = (
                    int(contract.get("num_base_observations") or 0)
                    * int(contract.get("history_size") or 0)
                    + int(contract.get("num_last_observations") or 0)
                )
                append_issue(
                    errors,
                    computed == spec["obs"],
                    f"{path.name} history formula {computed} != {spec['obs']}",
                )
        t1_yaml = {}
        t1_files = {
            "walk": "T1.yaml",
            "kick": "T1_Ball.yaml",
            "standup": "T1_Stand_Up.yaml",
        }
        for skill, name in t1_files.items():
            path = tree / "envs" / name
            if not path.is_file():
                warnings.append(f"optional T1 yaml missing: {path}")
                continue
            contract = env_contract(load_yaml(path))
            t1_yaml[skill] = {"path": str(path.relative_to(repo)), **contract}
            expect = T1_CONTRACTS[skill]
            append_issue(
                errors,
                contract.get("num_observations") == expect["obs"]
                and contract.get("num_actions") == expect["act"],
                f"{name} in {rel}: T1 {contract.get('num_observations')}→"
                f"{contract.get('num_actions')} vs {expect['obs']}→{expect['act']}",
            )
            if contract.get("num_observations") == K1_CONTRACTS[skill if skill != "kick" else "kick"]["obs"]:
                errors.append(f"{name} unexpectedly shares the K1 observation size")
        model_info = check_model_py(tree / "utils/model.py", errors, notes)
        walk_src = tree / "envs/t1.py"
        history_ok = check_history_formula(walk_src, errors) if walk_src.is_file() else False
        huoshen_hits = []
        for marker in HUOSHEN_MARKERS:
            for hit in tree.rglob("*"):
                if not hit.is_file():
                    continue
                if hit.suffix.lower() not in {".py", ".yaml", ".yml", ".md", ".cfg", ".json"}:
                    continue
                try:
                    blob = hit.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if marker in blob:
                    huoshen_hits.append({"marker": marker, "path": str(hit.relative_to(repo))})
        trees[rel].update(
            {
                "k1": yaml_env,
                "t1": t1_yaml,
                "model": model_info,
                "walk_history_formula": history_ok,
                "huoshen_markers_in_training_src": huoshen_hits,
            }
        )
        if huoshen_hits:
            errors.append(
                f"{rel} contains Huoshen/HiFAR markers; training src must stay B-Human-contracted: {huoshen_hits}"
            )
        else:
            notes.append(f"{rel}: no Huoshen/HiFAR/num_stack markers (B-Human contracts only)")

    if len(ISAAC_TREES) == 2 and all(trees[rel].get("k1") for rel in ISAAC_TREES):
        left = trees[ISAAC_TREES[0]]["k1"]
        right = trees[ISAAC_TREES[1]]["k1"]
        for skill in left:
            if {k: left[skill].get(k) for k in left[skill] if k != "path"} != {
                k: right[skill].get(k) for k in right[skill] if k != "path"
            }:
                errors.append(f"IsaacGymRL copies disagree on {skill} env contract")
            else:
                notes.append(f"both IsaacGymRL trees agree on K1 {skill} env dims")

    for skill, spec in K1_CONTRACTS.items():
        if "layout_frame" in spec:
            append_issue(errors, sum(spec["layout_frame"]) == spec["base_obs"], "walk frame layout sum")
            append_issue(errors, sum(spec["layout_tail"]) == spec["last_obs"], "walk tail layout sum")
            append_issue(
                errors,
                spec["base_obs"] * spec["history_size"] + spec["last_obs"] == spec["obs"],
                "walk 32×10+24 layout",
            )
        if "layout" in spec:
            append_issue(errors, sum(spec["layout"]) == spec["obs"], f"{skill} layout sum")

    walk_cfgs = []
    for rel in WALK_CFG_RELPATHS:
        path = repo / rel
        if not path.is_file():
            errors.append(f"missing walk cfg {rel}")
            continue
        parsed = parse_walk_cfg(path)
        walk_cfgs.append({"path": rel, **parsed})
        walk = parsed["walk"]
        append_issue(
            errors,
            walk.get("numInput") == 344 and walk.get("numOutput") == 13,
            f"{rel} walk numInput/numOutput={walk} expected 344/13",
        )
        for block_name, block in parsed["kick_blocks"].items():
            append_issue(
                errors,
                block.get("numInput") == 59,
                f"{rel} {block_name} numInput={block.get('numInput')} expected 59",
            )
            if "numOutput" in block and block["numOutput"] != 13:
                errors.append(f"{rel} {block_name} numOutput={block['numOutput']} expected 13")
        notes.append(f"{rel}: kick networks inherit walk numOutput=13 (not restated in ball blocks)")

    getup_cfgs = []
    for rel in GETUP_CFG_RELPATHS:
        path = repo / rel
        if not path.is_file():
            errors.append(f"missing getup cfg {rel}")
            continue
        parsed = parse_getup_cfg(path)
        getup_cfgs.append({"path": rel, **parsed})
        append_issue(
            errors,
            parsed.get("numInput") == 73 and parsed.get("numOutput") == 22,
            f"{rel} standup {parsed.get('numInput')}→{parsed.get('numOutput')} expected 73→22",
        )
        append_issue(
            errors,
            parsed.get("numInputFast") == 72 and parsed.get("numOutputFast") == 22,
            f"{rel} fast standup {parsed.get('numInputFast')}→{parsed.get('numOutputFast')} expected 72→22",
        )

    contract_doc = repo / "bhuman/docs/policy-contract-v1.md"
    doc_hits = {}
    if contract_doc.is_file():
        text = contract_doc.read_text(encoding="utf-8")
        for label, needle in (
            ("walk", "344 → 13"),
            ("kick", "59 → 13"),
            ("standup", "73 → 22"),
            ("fast_standup", "72 → 22"),
        ):
            doc_hits[label] = needle in text
            append_issue(errors, needle in text, f"policy-contract-v1.md missing {needle}")
    else:
        errors.append("missing bhuman/docs/policy-contract-v1.md")

    models_v2 = repo / "bhuman/k1-training/manifests/models-v2.json"
    models_v2_io = []
    if models_v2.is_file():
        recorded = json.loads(models_v2.read_text(encoding="utf-8"))
        expect_io = {
            "K1_walk.onnx": (344, 13),
            "K1_kick_inner.onnx": (59, 13),
            "K1_kick_inner_soft.onnx": (59, 13),
            "K1.onnx": (73, 22),
            "K1_fast_standup.onnx": (72, 22),
        }
        for item in recorded:
            name = Path(item.get("path", "")).name
            if name not in expect_io:
                continue
            ins = item.get("inputs") or [{}]
            outs = item.get("outputs") or [{}]
            in_dim = (ins[0].get("shape") or [None, None])[-1]
            out_dim = (outs[0].get("shape") or [None, None])[-1]
            models_v2_io.append(
                {
                    "name": name,
                    "in": in_dim,
                    "out": out_dim,
                    "sha256": item.get("sha256"),
                    "ok": (in_dim, out_dim) == expect_io[name],
                }
            )
            append_issue(
                errors,
                (in_dim, out_dim) == expect_io[name],
                f"models-v2.json {name} I/O {in_dim}→{out_dim} vs {expect_io[name]}",
            )
    else:
        warnings.append("models-v2.json missing; cannot cross-check recorded ONNX I/O")

    artifacts = []
    for name, rel in OFFICIAL_ONNX_RELPATHS.items():
        path = repo / rel
        record = {"name": name, "path": rel, "exists": path.is_file()}
        if path.is_file():
            record["sha256"] = sha256_file(path)
            expected = None
            if name == "K1_walk.onnx":
                expected = K1_CONTRACTS["walk"]["known_onnx_sha256"]
            elif name == "K1.onnx":
                expected = K1_CONTRACTS["standup"]["known_onnx_sha256"]
            elif name == "K1_fast_standup.onnx":
                expected = K1_CONTRACTS["fast_standup"]["known_onnx_sha256"]
            elif name in K1_CONTRACTS["kick"]["known_onnx_sha256"]:
                expected = K1_CONTRACTS["kick"]["known_onnx_sha256"][name]
            record["sha256_ok"] = expected is None or record["sha256"] == expected
            if expected and record["sha256"] != expected:
                errors.append(f"{rel} sha256 mismatch")
        else:
            msg = f"weight/ONNX absent (expected on operator machine / Release): {rel}"
            (errors if args.strict_weights else warnings).append(msg)
        artifacts.append(record)
    for spec in K1_CONTRACTS.values():
        for rel in spec.get("pth_relpaths") or ():
            path = repo / rel
            record = {"name": Path(rel).name, "path": rel, "exists": path.is_file()}
            if path.is_file():
                record["sha256"] = sha256_file(path)
                expected = spec.get("known_pth_sha256")
                if expected:
                    record["sha256_ok"] = record["sha256"] == expected
                    if record["sha256"] != expected:
                        errors.append(f"{rel} sha256 mismatch vs recorded public actor")
            else:
                msg = f"checkpoint absent (gitignored / local-only): {rel}"
                (errors if args.strict_weights else warnings).append(msg)
            artifacts.append(record)

    origins_path = repo / "archive/git-origins.json"
    origins = {}
    if origins_path.is_file():
        raw = json.loads(origins_path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            for item in raw:
                if item.get("path") in {"bhuman/MachineLearning", "bhuman/BHumanCodeRelease"}:
                    origins[item["path"]] = item.get("head")
        append_issue(
            errors,
            origins.get("bhuman/MachineLearning") == UPSTREAM_ML,
            f"git-origins MachineLearning {origins.get('bhuman/MachineLearning')} != {UPSTREAM_ML}",
        )
        append_issue(
            errors,
            origins.get("bhuman/BHumanCodeRelease") == UPSTREAM_BHUMAN,
            f"git-origins BHumanCodeRelease {origins.get('bhuman/BHumanCodeRelease')} != {UPSTREAM_BHUMAN}",
        )

    env = probe_environment()
    reserved_gpu = check_reserved_gpu(repo, warnings, notes)
    if not env["can_run_isaac_gym_train"]:
        notes.append(
            "Isaac Gym / official walk GPU replay cannot run here: need bh-gym "
            "(Python 3.8.20), Isaac Gym Preview 4, CUDA GPU, and K1_walk.pth"
        )

    reactive = check_k1_reactive_skeleton(repo, errors, notes)
    shells = check_gpu_free_shells(repo, errors, notes, warnings)

    research = {
        "huoshen_findings_on_main": (
            repo / "bhuman/research-materials-20261019/k1-soccer-lab/docs/evidence/huoshen_findings.md"
        ).is_file(),
        "research_branch_catalog_on_main": (repo / "research/06-落地路线建议.md").is_file(),
        "huoshen_code_vendored": False,
        "doc_contract": HUOSHEN_DOC_CONTRACT,
        "note": (
            "Huoshen public skill is T1 58-D + 50-frame stack → 15 actions. "
            "B-Human T1.yaml in this repo is the walk/kick/standup family "
            "(365→14 / 62→14 / 76→23), not the Huoshen reactive task. "
            "Do not load T1 Huoshen weights onto K1."
        ),
    }
    if not research["huoshen_findings_on_main"]:
        warnings.append("huoshen_findings.md missing on this checkout")
    if not research["research_branch_catalog_on_main"]:
        notes.append("research/01–06 live only on origin/research; not merged into main")

    commits = {
        "workspace_head": run_git(repo, "rev-parse", "HEAD"),
        "workspace_branch": run_git(repo, "branch", "--show-current"),
        "last_touch_MachineLearning": run_git(repo, "log", "-1", "--format=%H %s", "--", "bhuman/MachineLearning"),
        "last_touch_k1_training_isaac": run_git(
            repo, "log", "-1", "--format=%H %s", "--", "bhuman/k1-training/src/IsaacGymRL"
        ),
        "pinned_upstream_MachineLearning": UPSTREAM_ML,
        "pinned_upstream_BHumanCodeRelease": UPSTREAM_BHUMAN,
        "git_origins": origins,
        "k1_training_source_fingerprint": None,
    }
    source_history = repo / "bhuman/k1-training/manifests/source-history.json"
    if source_history.is_file():
        hist = json.loads(source_history.read_text(encoding="utf-8"))
        commits["k1_training_source_fingerprint"] = hist.get("current")

    verdict = "PASS" if not errors else "FAIL"
    report = {
        "generated_utc": utc_now(),
        "verdict": verdict,
        "repo": str(repo),
        "architecture": {
            "baseline": "B-Human IsaacGymRL official walk/kick/standup",
            "rule": "new skills are parallel extensions; do not rewrite frozen dims",
            "k1_reactive": "64→15 stub beside IsaacGymRL, not a train.py task",
            "unregistered_in_train_py": reactive.get("unregistered_in_train_py"),
            "skill_switch": "docs + empty shells + static slot map + walk/kick/standup SM; reactive blocked",
            "roadmap": "bhuman/docs/ROADMAP-P0-P5.md",
            "global_survey": "bhuman/docs/GLOBAL-HUMANOID-SURVEY-20261024.md",
            "migrate_table": "bhuman/docs/MIGRATE-TO-K1.md",
            "estimators": "k1-estimators RMA/DreamWaQ bypass; actor stays 344",
            "p2_acceptance": "bhuman/docs/P2-ACCEPTANCE.md",
            "reactive_hardening": "k1-reactive 64→15 bypass; not a new gait baseline",
            "sim2sim_gate": "skeleton skip without mujoco/weights; no auto-run",
            "obs_schema": "bhuman/docs/schemas/obs-contract-v1.json",
            "bt_skill_select": "docs + commented port; implemented=false; default walk 344→13",
            "switcher_sm": "walk/kick/standup skeleton; reactive blocked; no Gym",
            "p1_draft": "draft-only factor comments; official rewards untouched",
        },
        "k1_contracts": {
            "walk": "344→13",
            "kick": "59→13",
            "standup": "73→22",
            "fast_standup_deploy_only": "72→22",
        },
        "k1_reactive": reactive,
        "gpu_free_shells": shells,
        "reserved_gpu": reserved_gpu,
        "t1_bhuman_contracts": {
            "walk": "365→14",
            "kick": "62→14",
            "standup": "76→23",
            "note": "B-Human IsaacGymRL T1 family; not Huoshen T1 58+50→15",
        },
        "commits": commits,
        "environment": env,
        "trees": trees,
        "walk_cfgs": walk_cfgs,
        "getup_cfgs": getup_cfgs,
        "policy_contract_v1": doc_hits,
        "models_v2_io": models_v2_io,
        "artifacts": artifacts,
        "research": research,
        "errors": errors,
        "warnings": warnings,
        "notes": notes,
        "reproduce_walk_operator_machine": [
            "bash bhuman/k1-training/scripts/run_env_check.sh",
            "bash bhuman/k1-training/scripts/run_replay.sh K1 4 500",
            "bash bhuman/sim2sim/run-mujoco.sh --seconds 120",
        ],
        "reproduce_this_gate": [
            "python3 bhuman/k1-training/scripts/check_policy_contracts.py",
            "bash bhuman/k1-training/scripts/run_contract_gate.sh",
            "python3 bhuman/k1-training/k1-reactive/check_skeleton.py",
            "python3 bhuman/k1-training/k1-reactive/test_unregistered_in_train_py.py",
            "python3 bhuman/k1-training/k1-reactive/test_skill_switch_continuity.py",
            "python3 bhuman/k1-training/k1-reactive/test_skill_switch_map.py",
            "python3 bhuman/k1-training/k1-reactive/test_global_docs.py",
            "python3 bhuman/k1-training/k1-reactive/test_migrate_table.py",
            "python3 bhuman/k1-training/k1-estimators/test_estimators.py",
            "python3 bhuman/k1-training/k1-reactive/test_obs_schema.py",
            "python3 bhuman/k1-training/k1-reactive/test_bt_skill_select.py",
            "python3 bhuman/sim2sim/test_sim2sim_gate.py",
            "bash bhuman/sim2sim/run-sim2sim-gate.sh",
            "python3 bhuman/k1-training/k1-switcher/test_switcher_sm.py",
            "python3 bhuman/k1-training/k1-switcher/test_deploy_call.py",
            "python3 bhuman/k1-training/k1-switcher/test_timeseries_contract.py",
            "python3 bhuman/k1-training/k1-estimators/test_estimator_bypass.py",
            "python3 bhuman/k1-training/k1-reactive/test_reactive_hardening.py",
            "python3 bhuman/k1-training/configs/draft-only/test_p1_draft.py",
            "bash bhuman/k1-training/scripts/probe_reserved_gpu.sh",
        ],
    }

    text_out = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json_out:
        out_path = Path(args.json_out)
        if not out_path.is_absolute():
            out_path = repo / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text_out + "\n", encoding="utf-8")
        print(f"[write] {out_path}")

    print(f"[verdict] {verdict}")
    print(
        "[k1] baseline walk 344→13 | kick 59→13 | standup 73→22 | fast_standup 72→22 (deploy)"
    )
    print("[k1] parallel stub K1_Reactive 64→15 (not registered, not trainable)")
    print(
        "[k1] skeleton YAML present; unregistered in train.py = "
        f"{reactive.get('unregistered_in_train_py') or 'MISSING'}"
    )
    print("[k1] skill-switch: static T1/T2/T3/T5 map PASS; history shells SKIP")
    print("[k1] docs: GLOBAL-HUMANOID-SURVEY + ROADMAP-P0-P5 + MIGRATE-TO-K1")
    print("[k1] gpu-free: estimators / sim2sim-gate / obs-schema / bt-skill-select / switcher-sm / deploy-call / timeseries / reactive-hardening / p1-draft")
    print(
        f"[pin] MachineLearning {UPSTREAM_ML} | BHumanCodeRelease {UPSTREAM_BHUMAN}"
    )
    print(f"[env] python={env['python']} gpu={env['gpu']!r} isaacgym={env['modules']['isaacgym']}")
    for item in errors:
        print(f"[error] {item}")
    for item in warnings:
        print(f"[warn] {item}")
    for item in notes:
        print(f"[note] {item}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
