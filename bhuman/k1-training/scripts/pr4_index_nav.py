"""Read-only PR #4 index grouped navigation + volume-health pin.

Requires bhuman/docs/PR4-INDEX.md to keep:

  * grouped nav: walk / kick / standup / handoff / artifacts / GAP
  * links to the latest manifests in each group
  * volume-health hint (~335 files / +191k; LFS candidates; 勿再塞大二进制)
  * walk↔kick history GAP still open (status=GAP / gap_closed=false)

Does not delete contract scripts. Does not force-push or rewrite history.
Never writes K1.yaml. TRAINABLE=false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WALK_OBS = 344
WALK_ACT = 13
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
INDEX_REL = "bhuman/docs/PR4-INDEX.md"
SNAPSHOT_REL = "bhuman/k1-training/manifests/pr4-index-nav-latest.json"
VOLUME_FILES = 335
VOLUME_INSERTIONS = 191077

GROUPS = (
    {
        "id": "walk",
        "heading": "### walk",
        "manifests": (
            "walk-policy-apply-dims-latest.json",
            "walk-stay-remaining-latest.json",
            "walking-engine-cfg-audit-latest.json",
            "ball-network-active-latest.json",
            "intercept-avoid-bypass-latest.json",
        ),
    },
    {
        "id": "kick",
        "heading": "### kick",
        "manifests": (
            "kick-policy-apply-dims-latest.json",
            "kick-engine-boundary-latest.json",
            "kick-onnx-naming-latest.json",
            "walk-kick-policy-switch-latest.json",
        ),
    },
    {
        "id": "standup",
        "heading": "### standup",
        "manifests": (
            "standup-policy-apply-dims-latest.json",
            "fast-standup-isolation-latest.json",
            "getup-engine-cfg-audit-latest.json",
        ),
    },
    {
        "id": "handoff",
        "heading": "### handoff",
        "manifests": (
            "getup-walk-handoff-chain-latest.json",
            "force-walk-afterwards-latest.json",
            "falldown-motion-chain-latest.json",
        ),
    },
    {
        "id": "artifacts",
        "heading": "### artifacts",
        "manifests": (
            "upload-run-artifacts-latest.json",
        ),
        "extra": ("LOCAL-RUN-ARTIFACTS.md",),
    },
    {
        "id": "GAP",
        "heading": "### GAP",
        "manifests": (
            "policy-switch-history-gap-latest.json",
            "policy-switch-last-action-latest.json",
            "walk-phase-reset-allowlist-latest.json",
        ),
        "extra": ("gap_closed=false", "status=GAP", "仍未闭合"),
    },
)

VOLUME_NEEDLES = (
    "335",
    "191k",
    "勿再塞大二进制",
    "LFS",
    "不 force-push",
    "不改历史",
    "不删合同脚本",
)
LFS_CANDIDATES = (".onnx", ".pth", ".zip")
CLOSED_CLAIM_NEEDLES = (
    "gap_closed=true",
    "gap_closed: true",
    "GAP 已闭合",
    "history GAP 已闭合",
    "walk↔kick GAP 已闭合",
    "resetHistoryData GAP 已闭合",
)
OPEN_NEEDLES = (
    "gap_closed=false",
    "status=GAP",
    "仍未闭合",
)
GROUP_NAV_NEEDLE = "分组导航"


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
        f"PR4 index nav snapshot is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"PR4 index nav snapshot is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_pr_index_claims_gap_closed(claim: dict[str, Any] | str | None = None) -> None:
    if isinstance(claim, str):
        text = claim
        mapping: dict[str, Any] = {}
    elif isinstance(claim, dict):
        mapping = claim
        text = str(mapping.get("index_text") or mapping.get("text") or "")
    else:
        raise ValueError("pr-index-gap-closed claim must be a mapping or index text")
    if (
        mapping.get("pr_index_claims_gap_closed")
        or mapping.get("gap_closed") is True
        or mapping.get("claim_walk_kick_gap_closed")
        or mapping.get("status") == "CLOSED"
        or any(needle in text for needle in CLOSED_CLAIM_NEEDLES)
    ):
        raise ValueError(
            "PR4-INDEX must keep walk↔kick history GAP open "
            "(status=GAP / gap_closed=false); claiming the GAP closed is forbidden"
        )


def _section_after(text: str, heading: str) -> str:
    start = text.find(heading)
    if start < 0:
        return ""
    rest = text[start + len(heading) :]
    nxt = rest.find("\n### ")
    return rest if nxt < 0 else rest[:nxt]


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("pr4-index-nav leaked TRAINABLE/WRITE flags")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    index_path = repo / INDEX_REL
    if not index_path.is_file():
        return {
            "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "status": "SKIP",
            "skipped": True,
            "reason": "PR4-INDEX.md missing; not fabricating grouped nav",
            "fabricated": False,
            "trainable": False,
            "write_yaml": False,
            "walk": "344→13",
            "gap_closed": False,
            "note": "do not invent PR4 grouped navigation when the index is missing",
        }

    text = index_path.read_text(encoding="utf-8")
    if GROUP_NAV_NEEDLE not in text:
        raise AssertionError("PR4-INDEX.md must keep a 分组导航 section")
    if "344→13" not in text:
        raise AssertionError("PR4-INDEX.md must keep default walk 344→13")

    closed = [n for n in CLOSED_CLAIM_NEEDLES if n in text]
    if closed:
        raise AssertionError(f"PR4-INDEX.md claims GAP closed via {closed}")
    missing_open = [n for n in OPEN_NEEDLES if n not in text]
    if missing_open:
        raise AssertionError(f"PR4-INDEX.md missing GAP-open needles {missing_open}")

    missing_vol = [n for n in VOLUME_NEEDLES if n not in text]
    if missing_vol:
        raise AssertionError(f"PR4-INDEX.md missing volume-health needles {missing_vol}")
    missing_lfs = [n for n in LFS_CANDIDATES if n not in text]
    if missing_lfs:
        raise AssertionError(f"PR4-INDEX.md missing LFS candidates {missing_lfs}")

    groups: list[dict[str, Any]] = []
    for row in GROUPS:
        heading = row["heading"]
        if heading not in text:
            raise AssertionError(f"PR4-INDEX.md missing group heading {heading}")
        body = _section_after(text, heading)
        missing_m = [m for m in row["manifests"] if m not in body]
        if missing_m:
            raise AssertionError(f"group {row['id']} missing manifest links {missing_m}")
        extra_ok = all(item in body or item in text for item in row.get("extra") or ())
        if row.get("extra") and not extra_ok:
            raise AssertionError(f"group {row['id']} missing extra needles {row['extra']}")
        groups.append(
            {
                "id": row["id"],
                "heading": heading,
                "manifests": list(row["manifests"]),
                "linked": True,
            }
        )

    try:
        refuse_pr_index_claims_gap_closed(
            {"pr_index_claims_gap_closed": True, "gap_closed": True, "index_text": text}
        )
        raise AssertionError("refuse_pr_index_claims_gap_closed must raise")
    except ValueError:
        pass

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "index": INDEX_REL,
        "groups": groups,
        "volume": {
            "files": VOLUME_FILES,
            "insertions": VOLUME_INSERTIONS,
            "hint": "~+191k / 335 files vs main",
            "lfs_candidates": list(LFS_CANDIDATES),
            "no_more_large_binaries": True,
            "no_force_push": True,
            "no_history_rewrite": True,
            "do_not_delete_contract_scripts": True,
        },
        "gap": {
            "status": "GAP",
            "gap_closed": False,
            "note": "walk↔kick resetHistoryData still open; draft only",
        },
        "pr_index_claims_gap_closed": False,
        "fabricated": False,
        "note": (
            "PR4-INDEX grouped nav + volume health; default walk 344→13; "
            "GAP stays open; do not stuff large binaries"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "yaml_sha256": hashlib.sha256(yaml_path.read_bytes()).hexdigest(),
    }


def write_snapshot(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    snapshot = extract_snapshot(repo)
    path = dest or (repo / SNAPSHOT_REL)
    if path.suffix in {".yaml", ".yml", ".cfg"} or path.name == "K1.yaml":
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_index_nav_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("pr4-index-nav leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP must not fabricate grouped nav")
        return snap
    ids = [row.get("id") for row in (snap.get("groups") or [])]
    expected = [row["id"] for row in GROUPS]
    if ids != expected:
        raise AssertionError(f"PR4-INDEX groups drifted: {ids}")
    if snap.get("pr_index_claims_gap_closed") or (snap.get("gap") or {}).get("gap_closed"):
        raise AssertionError("PR4-INDEX leaked GAP-closed")
    vol = snap.get("volume") or {}
    if vol.get("files") != VOLUME_FILES or not vol.get("no_more_large_binaries"):
        raise AssertionError("volume-health pin drifted")
    return snap


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("pr4-index-nav imported Gym")

    yaml_path = repo / K1_YAML_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    try:
        snap = assert_index_nav_frozen(repo)
        notes.append("assert_index_nav_frozen: grouped nav + volume health; GAP open")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "index missing"))
        notes.append("honest SKIP: grouped nav not fabricated")
    elif snap:
        notes.append("groups: walk / kick / standup / handoff / artifacts / GAP")
        notes.append("volume ~+191k / 335 files; LFS candidates; 勿再塞大二进制")
        notes.append("walk↔kick GAP status=GAP / gap_closed=false")

    try:
        refuse_pr_index_claims_gap_closed(
            {"pr_index_claims_gap_closed": True, "gap_closed": True}
        )
        errors.append("pr_index claims GAP closed must raise")
    except ValueError:
        notes.append("negative: PR4-INDEX GAP-closed claim refused")

    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")

    if snap or not errors:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    if yaml_path.is_file():
        after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
        if before_yaml != after_yaml:
            errors.append("K1.yaml changed during pr4-index-nav audit")
        else:
            notes.append("official K1.yaml untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(snap.get("status") == "SKIP"),
        "status": snap.get("status") or "FAIL",
        "trainable": False,
        "write_yaml": False,
        "walk": "344→13",
        "gap_closed": False,
        "pr_index_claims_gap_closed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()
    repo = _repo()
    dest = Path(args.json_out) if args.json_out else None
    try:
        path = write_snapshot(repo, dest)
        snap = json.loads(path.read_text(encoding="utf-8"))
    except (AssertionError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"[pr4-index] FAIL {exc}")
        return 1
    print(
        f"[pr4-index] {snap.get('status')} "
        f"groups={len(snap.get('groups') or [])} GAP open; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
