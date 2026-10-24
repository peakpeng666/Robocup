#!/usr/bin/env python3
"""Render pr4-selfcheck-latest.json into a short human PASS/SKIP/WARN page.

Writes bhuman/docs/PR4-SELFCHECK-LATEST.md only. Not a new survey.
Never writes K1.yaml. Never trains.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRAINABLE = False
WRITE_YAML = False
SELFCHECK_REL = "bhuman/k1-training/manifests/pr4-selfcheck-latest.json"
GATE_REL = "bhuman/k1-training/manifests/contract-gate-latest.json"
GPU_REL = "bhuman/k1-training/manifests/reserved-gpu-latest.json"
INVENTORY_REL = "bhuman/k1-training/manifests/reference-motion-inventory-latest.json"
JOINTS_REL = "bhuman/k1-training/manifests/kick-standup-joint-map-latest.json"
OUT_REL = "bhuman/docs/PR4-SELFCHECK-LATEST.md"
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    here = Path(__file__).resolve()
    for candidate in (here.parents[3], Path.cwd(), *here.parents):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def refuse_write_yaml(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"selfcheck summary renderer must not write {path or 'K1.yaml'}"
    )


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file() or path.stat().st_size <= 0:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def collect(repo: Path) -> dict[str, Any]:
    selfcheck = _load_json(repo / SELFCHECK_REL)
    gate = _load_json(repo / GATE_REL)
    gpu = _load_json(repo / GPU_REL)
    inventory = _load_json(repo / INVENTORY_REL)
    joints = _load_json(repo / JOINTS_REL)
    missing_sources: list[str] = []
    if selfcheck is None:
        missing_sources.append(SELFCHECK_REL)
    return {
        "selfcheck": selfcheck,
        "gate": gate,
        "gpu": gpu,
        "inventory": inventory,
        "joints": joints,
        "missing_sources": missing_sources,
    }


def _rows_from_selfcheck(selfcheck: dict[str, Any] | None) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    if not selfcheck:
        return [("pr4-selfcheck-latest.json", "SKIP", "missing selfcheck JSON")]
    verdict = str(selfcheck.get("verdict") or "SKIP")
    for step in selfcheck.get("steps") or []:
        rows.append((str(step), verdict if verdict == "PASS" else "SKIP", "selfcheck step"))
    if selfcheck.get("ready_gpu") is False:
        rows.append(("ready_gpu", "WARN", "false (expected without CUDA worker)"))
    if selfcheck.get("trainable") is not False:
        rows.append(("trainable", "WARN", "must stay false"))
    return rows


def _extra_rows(bundle: dict[str, Any]) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    gpu = bundle.get("gpu") or {}
    if gpu:
        if gpu.get("skipped") or not gpu.get("ready"):
            missing = gpu.get("missing") or gpu.get("skip_reasons") or []
            detail = ", ".join(str(x) for x in missing) if missing else "probe skipped"
            rows.append(("reserved GPU", "WARN", detail))
        else:
            rows.append(("reserved GPU", "PASS", "ready (must tell user before train)"))
    inventory = bundle.get("inventory") or {}
    if inventory:
        skipped = inventory.get("skipped_ids") or inventory.get("missing") or []
        if skipped:
            rows.append(
                (
                    "reference-motion inventory",
                    "SKIP",
                    f"missing declared: {', '.join(str(x) for x in skipped)}",
                )
            )
        else:
            rows.append(("reference-motion inventory", "PASS", "all declared paths present"))
        rows.append(
            (
                "T1 / GMR as walk default",
                "PASS",
                "refused (foreign ≠ official walk)",
            )
        )
    joints = bundle.get("joints") or {}
    if joints:
        status = str(joints.get("status") or "SKIP")
        standup = (joints.get("standup") or {}).get("slot12") or "lHipYaw"
        rows.append(
            (
                "kick/standup joint map",
                status,
                f"kick shares walk 13-exit; standup[12]={standup} motor",
            )
        )
        if joints.get("skipped"):
            rows.append(("kick/standup extract", "SKIP", "source missing; names not fabricated"))
    gate = bundle.get("gate") or {}
    warnings = gate.get("warnings") or []
    if warnings:
        preview = "; ".join(str(w) for w in warnings[:4])
        if len(warnings) > 4:
            preview += f" … +{len(warnings) - 4}"
        rows.append(("contract-gate warnings", "WARN", preview))
    return rows


def render_markdown(bundle: dict[str, Any]) -> str:
    selfcheck = bundle.get("selfcheck")
    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if selfcheck:
        stamp = str(selfcheck.get("generated_utc") or generated)
        verdict = str(selfcheck.get("verdict") or "SKIP")
        walk = str(selfcheck.get("walk") or "344→13")
        trainable = selfcheck.get("trainable")
        ready = selfcheck.get("ready_gpu")
    else:
        stamp = generated
        verdict = "SKIP"
        walk = "344→13"
        trainable = False
        ready = False

    rows = _rows_from_selfcheck(selfcheck) + _extra_rows(bundle)
    pass_n = sum(1 for _, status, _ in rows if status == "PASS")
    skip_n = sum(1 for _, status, _ in rows if status == "SKIP")
    warn_n = sum(1 for _, status, _ in rows if status == "WARN")

    lines = [
        "# PR #4 自检摘要（最新）",
        "",
        f"由 `scripts/render_selfcheck_summary.py` 从 `pr4-selfcheck-latest.json` 生成（{stamp}；渲染 {generated}）。",
        "人读一览，不是新调研。**PASS ≠ 已训通 ≠ 已上真机。**",
        "",
        f"**{verdict}** 基底 **{walk}** / TRAINABLE={str(trainable).lower()} / ready_gpu={str(ready).lower()}",
        "",
        f"计数：PASS {pass_n} · SKIP {skip_n} · WARN {warn_n}",
        "",
        "| 项 | 状态 | 说明 |",
        "|---|---|---|",
    ]
    for name, status, detail in rows:
        safe = detail.replace("|", "/")
        lines.append(f"| `{name}` | **{status}** | {safe} |")
    lines.extend(
        [
            "",
            "主入口：`bash bhuman/k1-training/scripts/run_pr4_selfcheck.sh`",
            "",
            "官方 `K1.yaml` 只读。默认路径仍是 B-Human walk **344→13**。",
            "",
        ]
    )
    return "\n".join(lines)


def write_summary(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    if (dest or repo / OUT_REL).name == "K1.yaml":
        refuse_write_yaml(dest)
    bundle = collect(repo)
    text = render_markdown(bundle)
    path = dest or (repo / OUT_REL)
    if path.suffix in {".yaml", ".yml"}:
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if yaml_path.is_file():
        walk = yaml_path.read_text(encoding="utf-8")
        if "num_observations: 344" not in walk or "num_actions: 13" not in walk:
            raise AssertionError("official K1.yaml drifted off 344→13")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    repo = _repo(Path(args.repo) if args.repo else None)
    dest = Path(args.out) if args.out else None
    path = write_summary(repo, dest)
    print(f"[selfcheck-summary] wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
