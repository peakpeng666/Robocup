"""The motion-bridge experience ledger (``lessons.json``): load, validate, attach live evidence."""
from __future__ import annotations

from pathlib import Path

from .. import paths, util

LEDGER = Path(__file__).with_name("lessons.json")
STATUSES = ("verified_in_sim", "static_evidence", "assumption", "needs_real_robot")
CATEGORIES = ("contract", "gains", "timing", "safety", "modes", "model", "robustness", "process")
KINDS = ("code", "config", "doc", "audit", "bridge")


def validate(ledger: dict | None = None) -> list[str]:
    """Problems in the ledger: schema, duplicates, and file evidence that does not exist."""
    ledger = ledger if ledger is not None else util.read_json(LEDGER)
    problems = []
    if not ledger or ledger.get("schema") != "forge.bridge-lessons/1":
        return ["ledger schema missing or wrong"]
    seen = set()
    for lesson in ledger["lessons"]:
        lid = lesson.get("id")
        if not lid or lid in seen:
            problems.append(f"duplicate or missing id {lid!r}")
        seen.add(lid)
        for key in ("title", "summary", "action", "origin"):
            if not lesson.get(key):
                problems.append(f"{lid}: missing {key}")
        if lesson.get("status") not in STATUSES:
            problems.append(f"{lid}: status {lesson.get('status')!r}")
        if lesson.get("category") not in CATEGORIES:
            problems.append(f"{lid}: category {lesson.get('category')!r}")
        if not lesson.get("evidence"):
            problems.append(f"{lid}: no evidence")
        for item in lesson.get("evidence", []):
            if item.get("kind") not in KINDS:
                problems.append(f"{lid}: evidence kind {item.get('kind')!r}")
            if item.get("kind") in ("code", "config", "doc") and not (paths.ROOT / item["path"]).is_file():
                problems.append(f"{lid}: evidence file missing {item['path']}")
    return problems


def load(latest_run: dict | None = None, contract_audit: dict | None = None) -> dict:
    """Ledger plus, per evidence item, whether the latest audit / bridge run supports it."""
    ledger = util.read_json(LEDGER)
    finding_ids = {f["id"] for f in (contract_audit or {}).get("findings", [])}
    for lesson in ledger["lessons"]:
        for item in lesson["evidence"]:
            if item["kind"] == "audit" and contract_audit is not None:
                check = item["check"]
                item["supported"] = (check in finding_ids) if check != "orders" else all(
                    v["ok"] for v in contract_audit.get("orders", {}).values())
            elif item["kind"] == "bridge" and latest_run is not None:
                item["run_id"] = latest_run.get("run_id")
                experiment = item["experiment"]
                if experiment == "session":
                    item["supported"] = (latest_run.get("session") or {}).get("status") == "PASS"
                elif experiment == "protocol":
                    scenarios = {s["id"]: s["status"] for s in latest_run.get("protocol", [])}
                    item["supported"] = scenarios.get(item.get("scenario")) == "PASS" if item.get("scenario") else bool(scenarios)
                elif experiment == "identity":
                    rows = [i for i in latest_run.get("identity", []) if i["stack"] == item.get("stack", i["stack"])]
                    item["supported"] = bool(rows) and all(i["verdict"] in ("EXACT", "FAITHFUL") for i in rows)
                elif experiment == "gaps":
                    item["supported"] = latest_run.get("verdicts", {}).get("gaps") == "COMPLETE"
                elif experiment == "crosssim":
                    item["supported"] = latest_run.get("crosssim_verdict") in ("CONSISTENT", "MODEL_GAP")
            elif item["kind"] in ("code", "config", "doc"):
                item["exists"] = (paths.ROOT / item["path"]).is_file()
    ledger["problems"] = validate(util.read_json(LEDGER))
    ledger["counts"] = {s: sum(lesson["status"] == s for lesson in ledger["lessons"]) for s in STATUSES}
    return ledger
