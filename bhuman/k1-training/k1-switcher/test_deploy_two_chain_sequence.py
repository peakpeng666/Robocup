#!/usr/bin/env python3
"""Deploy two-chain sequence: 链 A ≠ 链 B; PlayBall not kick net; GAP open."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def _load(repo: Path):
    rel = "bhuman/k1-training/scripts/deploy_two_chain_sequence.py"
    spec = importlib.util.spec_from_file_location("deploy_two_chain_sequence_test", repo / rel)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {rel}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("deploy two-chain test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("deploy two-chain flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_two_chain_sequence_frozen(repo)
        notes.append("assert_two_chain_sequence_frozen: 链 A ≠ 链 B; empty=walk 344→13")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "source missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate deploy two-chain")
        else:
            notes.append("honest SKIP: deploy two-chain not fabricated")
    elif snap:
        ids = [row.get("id") for row in (snap.get("chains") or [])]
        expected = ["chain_a_official_behavior", "chain_b_deploy_bypass"]
        if ids != expected:
            errors.append(f"deploy two-chain table drifted: {ids}")
        else:
            notes.append("two-chain table frozen: 链 A 官方行为 vs 链 B 部署旁路")
        chain_a = snap.get("chain_a") or {}
        if chain_a.get("is_kick_net") or chain_a.get("contract") != "344→13":
            errors.append("chain A must stay walkPolicy 344→13, not a kick net")
        else:
            notes.append("chain A: PlayBall pose → walkPolicy 344→13")
        chain_b = snap.get("chain_b") or {}
        if chain_b.get("contract") != "59→13":
            errors.append("chain B must stay kickPolicy 59→13")
        else:
            notes.append("chain B: want_kick + walk-stay → kickPolicy 59→13")
        if snap.get("chain_a_equals_chain_b") or snap.get("deploy_seq_draws_playball_as_kick_net"):
            errors.append("deploy sequence must not draw PlayBall as kick net / A=B")
        else:
            notes.append("PlayBall is not drawn as the kick net")
        if snap.get("deploy_doc_claims_gap_closed") or snap.get("gap_closed"):
            errors.append("deploy doc must keep walk↔kick GAP open")
        else:
            notes.append("walk↔kick GAP stays open")

    try:
        mod.refuse_deploy_seq_draws_playball_as_kick_net(
            {
                "deploy_seq_draws_playball_as_kick_net": True,
                "source": "PlayBall",
                "selects": "kickPolicy",
            }
        )
        errors.append("deploy seq draws PlayBall as kick net must raise")
    except ValueError:
        notes.append("negative: deploy seq draws PlayBall as kick net refused")
    try:
        mod.refuse_chain_a_equals_chain_b(
            {"chain_a_equals_chain_b": True, "same_chain": True}
        )
        errors.append("chain A equals chain B must raise")
    except ValueError:
        notes.append("negative: chain A equals chain B refused")
    try:
        mod.refuse_deploy_doc_claims_gap_closed(
            {
                "deploy_doc_claims_gap_closed": True,
                "source": "DEPLOY-CALL-SEQUENCE.md",
                "gap_closed": True,
            }
        )
        errors.append("deploy doc claims GAP closed must raise")
    except ValueError:
        notes.append("negative: deploy doc claims GAP closed refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/deploy-two-chain-sequence-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("chain_a_equals_chain_b") or blob.get("walk") != "344→13":
            errors.append("written snapshot must keep 链 A ≠ 链 B / walk 344→13")
        else:
            notes.append("wrote manifests/deploy-two-chain-sequence-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during deploy two-chain test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during deploy two-chain test")
        else:
            notes.append("official walkingEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(snap.get("status") == "SKIP"),
        "walk": "344→13",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
    }


def main() -> int:
    report = run()
    print(
        f"[deploy-2ch] {'PASS' if report['ok'] else 'FAIL'} "
        "链 A ≠ 链 B; PlayBall not kick net; GAP open"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
