"""Generate the acceptance report from the workbench DB + evidence index.

Usage: /usr/bin/python3 -B scripts/acceptance_report.py --out docs/ACCEPTANCE-20261021.md
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import config, db as db_mod, util  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    db = db_mod.DB(config.WB_DIR / "workbench.db")
    jobs = db.query("SELECT * FROM jobs ORDER BY created_at")
    lines = []
    lines.append("# 工作台验收报告（自动生成）")
    lines.append("")
    lines.append(f"生成时间：{util.now_local()}；ROOT={config.root()}")
    lines.append("")
    lines.append("| job_id | 类型 | 状态 | 质量判定 | 退出码 | run 目录 |")
    lines.append("|---|---|---|---|---|---|")
    for j in jobs:
        lines.append(f"| {j['job_id']} | {j['type']} | {j['status']} | {j['quality_verdict']} "
                     f"| {j['exit_code'] if j['exit_code'] is not None else '-'} | {j.get('run_dir') or '-'} |")
    lines.append("")
    lines.append("说明：状态为进程级；质量判定来自底层 result/evaluation JSON，"
                 "succeeded 不蕴含质量 PASS。评估器质量语义为 REPORT_ONLY（不自动认证）。")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
