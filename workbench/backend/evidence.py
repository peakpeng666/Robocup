"""Evidence index: scan the three chains' runs directories.

Reads existing result/execution/launch JSON files (the underlying tools are the
source of truth); the workbench only indexes them, never rewrites their verdicts.
"""
from pathlib import Path

from . import config, util, identity
import time

RUN_ROOTS = {
    "bhuman": "bhuman/local-k1-validation-20261019/runs",
    "sim2sim": "bhuman/sim2sim/runs",
    "training": "bhuman/k1-training/runs",
}

RESULT_FILES = ["result.json", "execution.json", "evaluation-status.json",
                "policy-parity.json", "resume_validation.json"]


def scan() -> dict:
    entries = []
    for chain, rel in RUN_ROOTS.items():
        root = config.rp(rel)
        if not root.is_dir():
            continue
        for run in sorted(root.iterdir()):
            if not run.is_dir():
                continue
            entry = {"chain": chain, "run_dir": str(run), "name": run.name}
            created = None
            if len(run.name) >= 16 and run.name[:8].isdigit():
                created = run.name[:15]  # YYYYMMDD_HHMMSS
            entry["created_at"] = created
            result = util.read_json(run / "result.json")
            execution = util.read_json(run / "execution.json")
            launch = util.read_json(run / "launch.json")
            evalstatus = util.read_json(run / "evaluation-status.json")
            parity = util.read_json(run / "policy-parity.json")
            verdict = "NOT_EVALUATED"
            if result and isinstance(result, dict):
                status = result.get("status")
                if status == "PASS":
                    verdict = "PASS"
                elif status in ("FAIL", "ERROR"):
                    verdict = "FAIL"
            entry['execution_status'] = (execution or {}).get('status', 'UNKNOWN')
            if evalstatus and isinstance(evalstatus, dict):
                if evalstatus.get("execution_status") == "FAIL":
                    verdict = "FAIL"
                elif evalstatus.get("coverage_status") == "INSUFFICIENT_COVERAGE":
                    verdict = "INSUFFICIENT"
                elif evalstatus.get("quality_verdict") in ('PASS', 'FAIL', 'INSUFFICIENT'):
                    verdict = evalstatus["quality_verdict"]
                else:
                    verdict = 'NOT_EVALUATED'
            entry["verdict"] = verdict
            entry["exit_code"] = (execution or {}).get("exit_code")
            entry["wall_s"] = (execution or {}).get("wall_s") or (result or {}).get("performance", {}).get("wall_s")
            scope = (result or {}).get("scope")
            entry["scope"] = scope
            identity = {}
            for src, key in [(launch, "source_sha256"), (launch, "source_sha256_at_launch"),
                             (result, "policy_identity"), (launch, "unchanged_public_files_sha256"),
                             (parity, "policy_sha256")]:
                if isinstance(src, dict) and key in src:
                    identity[key] = src[key] if not isinstance(src[key], dict) else "<map>"
            if launch and "simulator_sha256" in launch:
                identity["simulator_sha256"] = launch["simulator_sha256"]
            if result and isinstance(result, dict) and "policy_identity" in result:
                identity["policy_identity"] = result["policy_identity"]
            entry["identity"] = identity
            entry['mode'] = (result or {}).get('mode')
            from . import identity as identities
            current = identities.current()
            compared = []
            if chain == 'training':
                actual = (launch or {}).get('source_sha256') or (execution or {}).get('source_sha256_at_launch')
                if actual:
                    compared.append(actual == current['training_source'])
            elif chain == 'sim2sim':
                actual = (launch or {}).get('checkpoint_sha256')
                if actual and (launch or {}).get('checkpoint'):
                    compared.append(actual == identities.file_identity((launch or {})['checkpoint']))
                for field, path_field in [('xml_sha256','xml'), ('config_sha256','config')]:
                    if (launch or {}).get(field) and (launch or {}).get(path_field):
                        compared.append(launch[field] == identities.file_identity(launch[path_field]))
            elif chain == 'bhuman':
                old = (launch or {}).get('unchanged_public_files_sha256') or {}
                for rel, sha in old.items():
                    compared.append(sha == current['protected_files'].get(rel, {}).get('working'))
                for field, rel in [('simulator_sha256', config.project()['chains']['bhuman']['binary_release']),
                                    ('controller_sha256', 'bhuman/local-k1-validation-20261019/bhuman-local/Build/Linux/SimRobot/Release/libSimulatedRobot.so')]:
                    if (launch or {}).get(field):
                        compared.append(launch[field] == identities.file_identity(config.rp(rel)))
            entry['current_status'] = 'VERIFIED' if compared and all(compared) else ('STALE' if compared else 'UNVERIFIED')
            entry['identity_scope'] = 'Recorded comparable inputs only; environment/physical equivalence is not inferred.'
            media = [p.name for p in run.glob("*.mp4")]
            if media:
                entry["media"] = media
            extras = [f for f in RESULT_FILES if (run / f).is_file()]
            entry["files"] = extras + [n for n in ("metrics.jsonl", "updates.jsonl", "config.yaml",
                                                   "observations.npy", "trajectory.npz", "console.log")
                                       if (run / n).is_file()]
            entries.append(entry)
    entries.sort(key=lambda e: (e.get("created_at") or "", e["name"]), reverse=True)
    return {"generated_at": util.now_local(), "entries": entries}


def index_path():
    return config.WB_DIR / "runs" / "evidence-index.json"


def refresh():
    data = scan()
    util.write_json(index_path(), data)
    return data


def cached():
    data = util.read_json(index_path())
    return data if data and time.time() - index_path().stat().st_mtime < 10 else refresh()
