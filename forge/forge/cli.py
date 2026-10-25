"""``forge`` command line: packs, arena flashing, team matches, builds, training."""
from __future__ import annotations

import argparse
import json
import sys

from . import arena as arena_mod, packs, paths, util


def _print(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_pack_list(args):
    for pack in packs.list_packs():
        slots = ",".join(pack["components"]) or "-"
        patches = sum(len(v) for v in pack.get("cfg_patches", {}).values())
        print(f"{pack['id']:<40} {pack['kind']:<10} {pack.get('status', ''):<13} 网络={slots:<20} 配置项={patches} {pack['name']}")


def cmd_pack_create(args):
    components = {}
    for item in args.component or []:
        slot, _, path = item.partition("=")
        components[slot] = path
    patches = json.loads(args.cfg_patches) if args.cfg_patches else {}
    provenance = json.loads(args.provenance) if args.provenance else {}
    modules = json.loads(args.modules_json) if args.modules_json else {}
    manifest = packs.create(args.name, components, patches, args.description or "", provenance, modules)
    _print({"id": manifest["id"], "components": list(manifest["components"]), "status": manifest["status"]})


def cmd_pack_verify(args):
    _print(packs.verify(args.pack_id))


def cmd_arena_init(args):
    from . import builds

    source = builds.variant_root(args.variant) if args.variant else paths.BH_LOCAL
    _print(arena_mod.Arena(args.arena, source=source).materialize(refresh=args.refresh))


def cmd_arena_status(args):
    a = arena_mod.Arena(args.arena)
    _print({"state": a.state(), "freshness": a.freshness(),
            "flashed": {t: {"pack_id": r["pack_id"], "at": r["at"]} for t, r in a.flashed().items()}})


def cmd_flash(args):
    a = arena_mod.Arena(args.arena)
    if not a.state():
        a.materialize()
    receipt = a.flash(args.team, args.pack_id)
    report = a.verify()
    _print({"flashed": {"team": receipt["team"], "pack_id": receipt["pack_id"], "scenario": receipt["scenario"]},
            "readback": report["status"], "failed_checks": [k for k, v in report["checks"].items() if not v]})
    return 0 if report["status"] == "PASS" else 1


def cmd_verify(args):
    report = arena_mod.Arena(args.arena).verify()
    _print(report if args.full else {"status": report["status"], "checks": report["checks"]})
    return 0 if report["status"] == "PASS" else 1


def cmd_match(args):
    from . import match

    a = arena_mod.Arena(args.arena)
    result = match.run_match(a, seconds=args.seconds, record=not args.no_record, unthrottled=not args.realtime,
                             vision=args.vision, timeout=args.timeout, tag=args.tag,
                             case=args.case,
                             on_line=(lambda line: print(line, end="", flush=True)) if args.verbose else None)
    _print({"status": result["status"], "execution_status": result["execution_status"],
            "recovery_conclusion": result["recovery"]["conclusion"], "score": result["score"], "teams": result["teams"],
            "failed_checks": [k for k, v in result["checks"].items() if not v], "video": result.get("video"),
            "performance": result.get("performance")})
    return 0 if result["status"] == "PASS" else 1


def cmd_series(args):
    from . import league

    summary = league.run_series(arena_mod.Arena(args.arena), args.pack_a, args.pack_b, args.rounds, args.seconds,
                                args.vision, on_line=lambda line: print(line, end="", flush=True)
                                if (not line.startswith("AUDIT") or line.startswith("[series]")) else None)
    _print({k: summary[k] for k in ("status", "record", "totals", "rounds_valid", "rounds_played", "dir")})
    return 0 if summary["status"] == "PASS" else 1


def cmd_stress(args):
    import subprocess

    target = args.policy
    if not target.endswith((".pth", ".onnx")):
        pack = packs.load(target)
        if packs.motion_slots(pack)[0] != "walk":
            raise ValueError("此运控使用独立观测/动作契约；现有 MuJoCo Warp 评估器仅支持 B-Human walk。请使用对应适配器。")
        if pack["kind"] == "baseline":
            target = str(paths.BH_LOCAL / pack["components"]["walk"]["official_file"])
        else:
            target = str(packs.pack_dir(pack["id"]) / pack["components"]["walk"]["file"])
    command = [str(paths.INTERPRETERS["mjlab"]), "-B", str(paths.FORGE / "sim/mjwarp_eval.py"), "--policy", target,
               "--worlds", str(args.worlds), "--seconds", str(args.seconds), "--seed", str(args.seed),
               "--push-force", str(args.push_force), "--tag", util.safe_name(args.tag or args.policy, 40)]
    print(" ".join(command), flush=True)
    return subprocess.call(command)


def cmd_atlas(args):
    from . import atlas

    if args.atlas_command == "list":
        _print(atlas.list_runs())
        return
    if args.atlas_command == "show":
        result = atlas.load(args.run_id)
        _print({"run": result["run"], "worlds": result["worlds"], "axes": result["axes"],
                "capacities_C50": {label: {axis: {k: row["C50"][k] for k in ("value", "censored", "ci95_value")}
                                           for axis, row in policy["axes"].items()}
                                   for label, policy in result["policies"].items()},
                "comparisons": [{"candidate": c["candidate"], "baseline": c["baseline"], "verdict": c["verdict"],
                                 "axes": {a: {"ratio": r["ratio"], "ci95": r["ci95"], "status": r["status"]}
                                          for a, r in c["axes"].items()}} for c in result["comparisons"]]})
        return
    if args.atlas_command == "analyze":
        result = atlas.analyze(atlas.RUNS / args.run_id)
        _print({"run": result["run"], "verdicts": {c["candidate"]: c["verdict"] for c in result["comparisons"]}})
        return
    pack_ids = list(args.packs)
    if args.baseline and args.baseline not in pack_ids:
        pack_ids.insert(0, args.baseline)
    elif args.baseline:
        pack_ids.insert(0, pack_ids.pop(pack_ids.index(args.baseline)))
    axes = [a.strip() for a in args.axes.split(",")] if args.axes else None
    result = atlas.run(pack_ids, axes=axes, seed=args.seed, replica_scale=args.replica_scale, tag=args.tag,
                       on_line=lambda line: print(line, end="", flush=True))
    _print({"run": result["run"], "comparisons": [{"candidate": c["candidate"], "verdict": c["verdict"],
                                                   "better_axes": c["better_axes"], "worse_axes": c["worse_axes"]}
                                                  for c in result["comparisons"]]})


def cmd_bridge(args):
    from .bridge import analysis, contract, lessons

    if args.bridge_command == "contract":
        result = contract.audit()
        if args.json:
            _print(result)
            return
        _print({"verdict": result["verdict"], "orders": {k: v["ok"] for k, v in result["orders"].items()},
                "policy_orders": {k: v["ok"] for k, v in result["policy_orders"].items()},
                "messages": {k: v["ok"] for k, v in result["messages"].items()},
                "findings": [f"[{f['severity']}] {f['title']}" for f in result["findings"]]})
        return 1 if result["verdict"] == "CONTRACT_BROKEN" else 0
    if args.bridge_command == "lessons":
        problems = lessons.validate()
        ledger = lessons.load()
        _print({"counts": ledger["counts"], "problems": problems,
                "lessons": [f"[{x['status']}] {x['title']}" for x in ledger["lessons"]]})
        return 1 if problems else 0
    if args.bridge_command == "list":
        _print(analysis.list_runs())
        return
    if args.bridge_command in ("show", "analyze"):
        result = analysis.analyze(analysis.RUNS / args.run_id) if args.bridge_command == "analyze" else analysis.load(args.run_id)
        _print({"run": result["run_id"], "overall": result["overall"], "verdicts": result["verdicts"],
                "crosssim": result.get("crosssim_verdict"),
                "identity": [{k: i[k] for k in ("stack", "variant", "verdict", "max_position_delta_m",
                                                "max_segment_velocity_delta")} for i in result["identity"]],
                "protocol": {s["id"]: s["status"] for s in result["protocol"]},
                "weakest_axes": (result["gaps"] or {}).get("weakest"), "findings": [f["title"] for f in result["findings"]],
                "real_robot": result["real_robot"]})
        return
    experiments = [e for e in args.experiments.split(",") if e]
    simrobot = {}
    for item in args.simrobot or []:
        controller, _, run_dir = item.partition("=")
        if not run_dir:
            raise ValueError("--simrobot 需写成 控制器=runs/motion/<运行>")
        simrobot[controller] = run_dir
    result = analysis.run(experiments=experiments, controllers=[c for c in (args.controllers or "").split(",") if c] or None,
                          axes=[a for a in (args.axes or "").split(",") if a] or None, seeds=args.seeds,
                          session=not args.no_session, tag=args.tag, simrobot=simrobot or None,
                          on_line=lambda line: print(line, end="", flush=True))
    _print({"run": result["run_id"], "overall": result["overall"], "verdicts": result["verdicts"],
            "crosssim": result["crosssim_verdict"], "real_robot": result["real_robot"]})
    return 0 if result["overall"] == "SIM_BRIDGE_VERIFIED" else 1


def cmd_duel(args):
    from . import duel

    if args.duel_command == "list":
        _print(duel.list_duels())
        return
    if args.duel_command == "show":
        record = duel.load(args.duel_id)
        _print({"id": record["id"], "status": record["status"], "decision": record["decision"], "plan": {
            k: record["plan"][k] for k in ("kind", "candidate", "baseline", "max_pairs", "seconds", "alpha", "delta_goals")},
            "summary": {k: v for k, v in record["summary"].items() if k != "pairs"}})
        return
    printer = (lambda line: print(line, end="", flush=True)
               if line.startswith("[duel]") or not line.startswith("AUDIT") else None)
    if args.duel_command == "resume":
        record = duel.run(resume=args.duel_id, extra_pairs=args.extra_pairs, on_line=printer)
    else:
        options = dict(baseline=args.baseline, max_pairs=args.max_pairs, seconds=args.seconds, alpha=args.alpha,
                       delta_goals=args.delta, source_arena=args.arena, vision=args.vision,
                       record_first_pair=not args.no_record)
        if args.duel_command == "strategy":
            options["motion_pack"] = args.motion_pack
        record = duel.run(args.duel_command, args.candidate, on_line=printer, **options)
    summary = record["summary"]
    _print({"id": record["id"], "decision": record["decision"], "pairs": summary["pairs_complete"], "record": summary["record"],
            "goal_difference_cs": [summary["goal_difference_cs"][k] for k in ("lower", "upper")],
            "territory_cs": [summary["territory_cs"][k] for k in ("lower", "upper")], "path": record["path"]})


def cmd_dossier(args):
    from . import dossier

    if not args.pack_id:
        for row in dossier.overview():
            print(f"{row['id']:<42} 证据={row['total']:<3} 晋级={row['gate'] or '—':<22} 图谱={row['atlas'] or '—':<13} 对决={row['duel'] or '—'}")
        return
    data = dossier.dossier(args.pack_id)
    _print(data if args.full else {k: data[k] for k in ("pack", "walk_sha256", "hash_aliases", "lineage", "counts", "scorecard", "missing")})


def cmd_gate(args):
    from . import gates

    report = gates.assess(args.pack_id, gates.load_json(args.isaac_candidate), gates.load_json(args.isaac_baseline),
                          gates.load_json(args.mj_candidate), gates.load_json(args.mj_baseline), gates.load_json(args.series),
                          atlas_run=args.atlas)
    _print({"verdict": report["verdict"], "gates": {k: v["status"] for k, v in report["gates"].items()}, "path": report["path"]})


def cmd_pipeline(args):
    from . import pipeline

    record = pipeline.run(args.checkpoint, args.name, args.seed, args.worlds, args.seconds, args.push_force, args.rounds,
                          args.match_seconds, on_line=lambda line: print(line, end="", flush=True))
    _print({"verdict": record["verdict"], "pack_id": record["pack_id"], "dir": record["dir"],
            "steps": {k: v.get("status") for k, v in record["steps"].items()}})


def cmd_validate(args):
    from . import strategies, validation

    options = dict(motion_pack=args.motion_pack, strategy_id=args.strategy or strategies.BASELINE_ID,
                   source_arena=args.arena, repetitions=args.repetitions, seconds=args.seconds,
                   vision=args.vision, record=not args.no_record)
    if args.preview:
        _print(validation.plan(args.mode, **options))
        return
    result = validation.run(args.mode, **options, on_line=lambda line: print(line, end="", flush=True)
                            if line.startswith("[validation]") or not line.startswith("AUDIT ") else None)
    _print({"status": result["status"], "verdict": result["verdict"], "path": result["path"], "comparison": result["comparison"]})


def cmd_strategy(args):
    from . import strategies

    if args.strategy_command == "list":
        _print({"profiles": strategies.list_profiles(), "presets": strategies.PRESETS})
    elif args.preset:
        preset = strategies.PRESETS[args.preset]
        _print(strategies.create(args.name or args.preset, preset["cfg_patches"], preset["description"]))
    else:
        if not args.name or not args.patches:
            raise ValueError("提供 --preset，或同时提供 --name 与 --patches")
        _print(strategies.create(args.name, json.loads(args.patches), args.description or ""))


def cmd_bundle(args):
    from . import bundle

    _print(bundle.make(args.variant, args.pack_id))


def cmd_train(args):
    from . import training

    report = training.train_forge_thu(envs=args.envs, iterations=args.iterations, seed=args.seed, preset=args.preset,
                                      checkpoint=args.checkpoint, timeout=args.timeout, save_interval=args.save_interval,
                                      on_line=lambda line: print(line, end="", flush=True))
    _print({k: report.get(k) for k in ("status", "exit_code", "wall_s", "sampled_gpu_peak_mib", "stop_reason",
                                        "run_dir", "checkpoint")})
    return 0 if report["status"] == "PASS" else 1


def cmd_export(args):
    from . import training

    manifest = training.export_pack(args.checkpoint, args.name, args.description or "",
                                    on_line=lambda line: print(line, end="", flush=True) if args.verbose else None)
    _print({"pack_id": manifest["id"], "tri_check": manifest["provenance"].get("tri_check", {}).get("verdict")})


def cmd_eval(args):
    from . import training

    report = training.evaluate_walk(args.policy, args.seed, args.seg_steps, args.envs, args.baseline,
                                    on_line=lambda line: print(line, end="", flush=True) if args.verbose else None)
    _print({k: report.get(k) for k in ("status", "wall_s", "run_dir", "evaluation_status")})
    return 0 if report["status"] == "PASS" else 1


def cmd_variant_create(args):
    from . import builds

    data = builds.create_variant(args.name, args.patch or [], args.description or "")
    _print({"variant": data["name"], "files_changed_vs_base": data["files_changed_vs_base"],
            "util_copied": data["util_copied"], "source_sha256": data["source_sha256"]})


def cmd_variant_list(args):
    from . import builds

    for variant in builds.list_variants():
        built = ", ".join(f"{k}:{v.get('status')}" for k, v in variant["builds"].items()) or "未编译"
        print(f"{variant['name']:<24} 补丁={len(variant['patches'])} 改动文件={len(variant['files_changed_vs_base'])} {built}")


def cmd_build(args):
    from . import builds

    receipt = builds.build(args.variant, args.target, args.kind, args.jobs,
                           on_line=(lambda line: print(line, end="", flush=True)) if args.verbose else None)
    _print({k: receipt.get(k) for k in ("status", "variant", "target", "kind", "products", "elf", "log")})
    return 0 if receipt["status"] == "PASS" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(prog="forge", description="K1 Forge 运控工坊（B-Human 底座）")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("pack", help="运控包")
    ps = p.add_subparsers(dest="pack_command", required=True)
    ps.add_parser("list").set_defaults(func=cmd_pack_list)
    c = ps.add_parser("create")
    c.add_argument("name")
    c.add_argument("--component", action="append", help="slot=path.onnx；walk/kick/kick_soft 或需独立模块的 booster_walk/booster_fw16_walk")
    c.add_argument("--cfg-patches", help='JSON：{"walkingEngine.cfg": {"key.path": "value"}}')
    c.add_argument("--description")
    c.add_argument("--provenance", help="JSON 来源信息")
    c.add_argument("--modules-json", help='代码级模块：{"ForgeWalkingEngine": {"replaces": "WalkingEngine", "cfg": "forgeWalkingEngine.cfg", "params": {...}}}')
    c.set_defaults(func=cmd_pack_create)
    v = ps.add_parser("verify")
    v.add_argument("pack_id")
    v.set_defaults(func=cmd_pack_verify)

    vp = sub.add_parser("validate", help="SimRobot 运控或策略对照，独立 arena，保存运行证据")
    vp.add_argument("mode", choices=["motion", "strategy"])
    vp.add_argument("--motion-pack", default=packs.BASELINE_ID)
    vp.add_argument("--strategy", help="独立策略 ID；默认官方")
    vp.add_argument("--arena", default="main", help="程序来源；每次验证会创建独立 arena")
    vp.add_argument("--repetitions", type=int, default=1)
    vp.add_argument("--seconds", type=int, default=120, help="策略比赛时长；运控场景固定 30 秒")
    vp.add_argument("--vision", choices=["cuda", "cpu"], default="cuda")
    vp.add_argument("--no-record", action="store_true")
    vp.add_argument("--preview", action="store_true")
    vp.set_defaults(func=cmd_validate)

    strategy = sub.add_parser("strategy", help="独立足球行为策略配置")
    strategy_sub = strategy.add_subparsers(dest="strategy_command", required=True)
    strategy_sub.add_parser("list").set_defaults(func=cmd_strategy)
    strategy_create = strategy_sub.add_parser("create")
    strategy_create.add_argument("--name")
    strategy_create.add_argument("--preset", choices=["earlier-ball-search", "longer-pass-reception"])
    strategy_create.add_argument("--patches", help="JSON 配置文件到标量修改的映射")
    strategy_create.add_argument("--description")
    strategy_create.set_defaults(func=cmd_strategy)

    p = sub.add_parser("arena", help="arena 管理")
    ps = p.add_subparsers(dest="arena_command", required=True)
    i = ps.add_parser("init")
    i.add_argument("--arena", default="main")
    i.add_argument("--refresh", action="store_true")
    i.add_argument("--variant", help="以编译好的源码变体（forge/variants/NAME）为程序与配置来源")
    i.set_defaults(func=cmd_arena_init)
    s = ps.add_parser("status")
    s.add_argument("--arena", default="main")
    s.set_defaults(func=cmd_arena_status)

    f = sub.add_parser("flash", help="把运控包刷到一支队伍")
    f.add_argument("team", type=int, choices=arena_mod.TEAM_NUMBERS)
    f.add_argument("pack_id")
    f.add_argument("--arena", default="main")
    f.set_defaults(func=cmd_flash)

    v = sub.add_parser("verify", help="刷写回读校验")
    v.add_argument("--arena", default="main")
    v.add_argument("--full", action="store_true")
    v.set_defaults(func=cmd_verify)

    m = sub.add_parser("match", help="全自动队伍对抗赛（SimRobot 正常视觉）")
    m.add_argument("--case", choices=("match", "motion-basic-v1", "recovery-front-back-v1"), default="match",
                   help="比赛、30秒固定运动指令或60秒前后跌倒恢复")
    m.add_argument("--arena", default="main")
    m.add_argument("--seconds", type=int, default=120)
    m.add_argument("--vision", choices=["cuda", "cpu"], default="cuda")
    m.add_argument("--no-record", action="store_true")
    m.add_argument("--realtime", action="store_true", help="保留官方实时限速")
    m.add_argument("--timeout", type=int)
    m.add_argument("--tag", default="match")
    m.add_argument("--verbose", action="store_true")
    m.set_defaults(func=cmd_match)

    se = sub.add_parser("series", help="两个运控包主客互换系列赛")
    se.add_argument("pack_a")
    se.add_argument("pack_b")
    se.add_argument("--arena", default="main")
    se.add_argument("--rounds", type=int, default=2)
    se.add_argument("--seconds", type=int, default=120)
    se.add_argument("--vision", choices=["cuda", "cpu"], default="cuda")
    se.set_defaults(func=cmd_series)

    st = sub.add_parser("stress", help="MuJoCo Warp 批量 sim2sim 压力评测（运控包 ID 或 .pth/.onnx）")
    st.add_argument("policy")
    st.add_argument("--worlds", type=int, default=2048)
    st.add_argument("--seconds", type=float, default=20.0)
    st.add_argument("--seed", type=int, default=2027)
    st.add_argument("--push-force", type=float, default=0.0)
    st.add_argument("--tag")
    st.set_defaults(func=cmd_stress)

    g = sub.add_parser("gate", help="晋级门评估（只在仿真证据齐全且不劣于官方时标记 SIM_QUALIFIED）")
    g.add_argument("pack_id")
    g.add_argument("--isaac-candidate", help="候选主线评估 results.json")
    g.add_argument("--isaac-baseline", help="官方主线评估 results.json（同种子）")
    g.add_argument("--mj-candidate", help="候选 MuJoCo Warp result.json")
    g.add_argument("--mj-baseline", help="官方 MuJoCo Warp result.json（同设置）")
    g.add_argument("--series", help="系列赛 series.json")
    g.add_argument("--atlas", help="易损性图谱运行目录（同一世界表上评测候选与官方）")
    g.set_defaults(func=cmd_gate)

    dz = sub.add_parser("dossier", help="证据档案：运控包的血缘、各引擎证据、结论与缺口（只读索引）")
    dz.add_argument("pack_id", nargs="?")
    dz.add_argument("--full", action="store_true")
    dz.set_defaults(func=cmd_dossier)

    du = sub.add_parser("duel", help="序贯对决：换边配对比赛，随时有效置信序列，证据足够即停（SimRobot 正常视觉）")
    dus = du.add_subparsers(dest="duel_command", required=True)
    for kind, help_text in (("motion", "运控包对决（双方官方策略）"), ("strategy", "策略对决（双方同一运控包）")):
        dk = dus.add_parser(kind, help=help_text)
        dk.add_argument("candidate")
        dk.add_argument("--baseline", help="默认官方运控包 / 官方策略")
        if kind == "strategy":
            dk.add_argument("--motion-pack", default=packs.BASELINE_ID)
        dk.add_argument("--max-pairs", type=int, default=10)
        dk.add_argument("--seconds", type=int, default=120)
        dk.add_argument("--alpha", type=float, default=0.05)
        dk.add_argument("--delta", type=float, default=0.5, help="等效界：每对净胜球")
        dk.add_argument("--arena", default="main", help="程序来源；对决使用独立 arena")
        dk.add_argument("--vision", choices=["cuda", "cpu"], default="cuda")
        dk.add_argument("--no-record", action="store_true", help="第一对也不录像")
        dk.set_defaults(func=cmd_duel)
    dr = dus.add_parser("resume", help="继续中断或到达上限的对决（置信序列随时有效）")
    dr.add_argument("duel_id")
    dr.add_argument("--extra-pairs", type=int, default=0)
    dr.set_defaults(func=cmd_duel)
    dus.add_parser("list").set_defaults(func=cmd_duel)
    ds = dus.add_parser("show")
    ds.add_argument("duel_id")
    ds.set_defaults(func=cmd_duel)

    at = sub.add_parser("atlas", help="易损性图谱：多维扰动扫描 → 失效概率曲线 → 承受极限配对比较（MuJoCo Warp）")
    ats = at.add_subparsers(dest="atlas_command", required=True)
    ar = ats.add_parser("run", help="在同一世界表上评测一个或多个运控包（第一个为基线）")
    ar.add_argument("packs", nargs="+")
    ar.add_argument("--baseline", default="bhuman-official", help="基线包，自动放在最前；传空字符串则不加")
    ar.add_argument("--axes", help="逗号分隔的维度子集（默认全部）")
    ar.add_argument("--seed", type=int, default=2027)
    ar.add_argument("--replica-scale", type=float, default=1.0)
    ar.add_argument("--tag")
    ar.set_defaults(func=cmd_atlas)
    ats.add_parser("list").set_defaults(func=cmd_atlas)
    ash = ats.add_parser("show")
    ash.add_argument("run_id")
    ash.set_defaults(func=cmd_atlas)
    aa = ats.add_parser("analyze", help="从 raw.json 离线重算统计")
    aa.add_argument("run_id")
    aa.set_defaults(func=cmd_atlas)

    br = sub.add_parser("bridge", help="运控桥：K1 低层契约审计、虚拟 K1 一致性/协议/实时会话/现实差距裕度、经验库")
    brs = br.add_subparsers(dest="bridge_command", required=True)
    bc = brs.add_parser("contract", help="审计 B-Human / booster_deploy / MuJoCo 模型 / 固件 1.6 的关节、增益、限位与消息契约")
    bc.add_argument("--json", action="store_true")
    bc.set_defaults(func=cmd_bridge)
    brr = brs.add_parser("run", help="虚拟 K1 上运行桥接验证（新时间戳目录）")
    brr.add_argument("--experiments", default="identity,protocol,gaps")
    brr.add_argument("--controllers", help="逗号分隔：bhuman-training,bhuman-real-gains,booster-deploy,firmware-gait")
    brr.add_argument("--axes", help="逗号分隔的现实差距轴子集（默认全部）")
    brr.add_argument("--seeds", type=int, default=4)
    brr.add_argument("--no-session", action="store_true", help="跳过 booster_deploy 实时会话")
    brr.add_argument("--simrobot", action="append", help="跨仿真器对照：控制器=runs/motion/<motion-basic-v1 运行>（可重复）")
    brr.add_argument("--tag")
    brr.set_defaults(func=cmd_bridge)
    brs.add_parser("list").set_defaults(func=cmd_bridge)
    bsh = brs.add_parser("show")
    bsh.add_argument("run_id")
    bsh.set_defaults(func=cmd_bridge)
    ban = brs.add_parser("analyze", help="从 raw.json / session.json 离线重算结论")
    ban.add_argument("run_id")
    ban.set_defaults(func=cmd_bridge)
    brs.add_parser("lessons", help="经验库：校验证据并列出").set_defaults(func=cmd_bridge)

    pl = sub.add_parser("pipeline", help="候选全流程：导出→三引擎证据→晋级门")
    pl.add_argument("checkpoint")
    pl.add_argument("name")
    pl.add_argument("--seed", type=int, default=2027)
    pl.add_argument("--worlds", type=int, default=2048)
    pl.add_argument("--seconds", type=float, default=20.0)
    pl.add_argument("--push-force", type=float, default=60.0)
    pl.add_argument("--rounds", type=int, default=2)
    pl.add_argument("--match-seconds", type=int, default=120)
    pl.set_defaults(func=cmd_pipeline)

    bu = sub.add_parser("bundle", help="离线机器人包（Booster 程序 + Config + 运控包 scenario；不部署）")
    bu.add_argument("variant")
    bu.add_argument("pack_id")
    bu.set_defaults(func=cmd_bundle)

    t = sub.add_parser("train", help="B-Human × 火神 训练配方（Isaac Gym，契约保持）")
    t.add_argument("--preset", default="thu-amp")
    t.add_argument("--envs", type=int, default=64)
    t.add_argument("--iterations", type=int, default=3)
    t.add_argument("--seed", type=int, default=42)
    t.add_argument("--checkpoint", help="warm-start 起点（默认官方 K1_walk.pth）")
    t.add_argument("--timeout", type=int, default=900)
    t.add_argument("--save-interval", type=int, default=50)
    t.set_defaults(func=cmd_train)

    e = sub.add_parser("export", help="导出检查点并打成运控包（主线三方数值校验）")
    e.add_argument("checkpoint")
    e.add_argument("name")
    e.add_argument("--description")
    e.add_argument("--verbose", action="store_true")
    e.set_defaults(func=cmd_export)

    ev = sub.add_parser("eval", help="主线冻结日程行走评估")
    ev.add_argument("policy")
    ev.add_argument("--seed", type=int, default=2027)
    ev.add_argument("--seg-steps", type=int, default=100)
    ev.add_argument("--envs", type=int, default=8)
    ev.add_argument("--baseline")
    ev.add_argument("--verbose", action="store_true")
    ev.set_defaults(func=cmd_eval)

    va = sub.add_parser("variant", help="源码变体（bhuman-local + 补丁栈）")
    vs = va.add_subparsers(dest="variant_command", required=True)
    vc = vs.add_parser("create")
    vc.add_argument("name")
    vc.add_argument("--patch", action="append", help="git 格式补丁（-p1，相对 B-Human 根目录）")
    vc.add_argument("--description")
    vc.set_defaults(func=cmd_variant_create)
    vs.add_parser("list").set_defaults(func=cmd_variant_list)

    b = sub.add_parser("build", help="编译源码变体：simrobot(x86_64) 或 booster(AArch64+SDK)")
    b.add_argument("variant")
    b.add_argument("--target", choices=["simrobot", "booster"], default="booster")
    b.add_argument("--kind", choices=["Release", "Develop"], default="Release")
    b.add_argument("--jobs", type=int, default=12)
    b.add_argument("--verbose", action="store_true")
    b.set_defaults(func=cmd_build)

    args = parser.parse_args(argv)
    try:
        return args.func(args) or 0
    except (packs.PackError, arena_mod.ArenaError, ValueError, RuntimeError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
