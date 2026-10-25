"""Whitelisted task registry: validated argv builders and result collectors.

No arbitrary shell execution. Each task type declares its parameter schema,
builds an argv array, and knows how to collect the underlying run's evidence.
"""
import os
from datetime import datetime
from pathlib import Path

from . import config, util

ROOT = config.root()
P = config.project()


def _abs(rel):
    return str(config.rp(rel))


BH = P["chains"]["bhuman"]
S2S = P["chains"]["sim2sim"]
TR = P["chains"]["training"]


class ParamError(ValueError):
    pass


def _int(params, name, lo, hi, default):
    raw = params.get(name, default)
    if isinstance(raw, bool) or isinstance(raw, float) and not raw.is_integer():
        raise ParamError(f"参数 {name} 必须是整数")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ParamError(f"参数 {name} 必须是整数")
    if not lo <= value <= hi:
        raise ParamError(f"参数 {name} 必须在 {lo}..{hi} 内")
    return value


def _bool(params, name, default):
    raw = params.get(name, default)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        if raw.lower() in ("1", "true", "yes", "on"):
            return True
        if raw.lower() in ("0", "false", "no", "off"):
            return False
    raise ParamError(f"参数 {name} 必须是布尔值")


def _enum(params, name, choices, default):
    value = params.get(name, default)
    if value not in choices:
        raise ParamError(f"参数 {name} 必须是 {sorted(choices)} 之一")
    return value


def _existing_file(params, name, default=None, must_exist=True):
    raw = params.get(name, default)
    if not raw:
        raise ParamError(f"参数 {name} 缺少路径")
    p = util.safe_resolve(raw, [ROOT])
    if must_exist and not (p.is_file() or p.is_dir()):
        raise ParamError(f"路径不存在: {p}")
    return str(p)


def _new_dir(params, name, parent):
    raw = params.get(name)
    if not raw:
        raise ParamError(f"参数 {name} 缺少目录名")
    if os.path.basename(raw) != raw or raw in ("", ".", ".."):
        raise ParamError(f"{name} 只能是一个新目录名（不能含路径分隔符）")
    parent_p = util.safe_resolve(parent, [ROOT])
    if not parent_p.is_dir():
        raise ParamError(f"父目录不存在: {parent_p}")
    dest = parent_p / raw
    if dest.exists():
        raise ParamError(f"输出目录必须新建，已存在: {dest}")
    return str(dest)


def _collect_pointer(pointer_path, job_row):
    """A last-run pointer is discovery, never proof that it belongs to this job."""
    path = Path(pointer_path)
    data = util.read_json(path) or {}
    run = data.get("run_dir") or data.get("run")
    if not run or not job_row.get("started_at"):
        return {}
    run = Path(run).resolve()
    try:
        run.relative_to(config.root())
        started = datetime.fromisoformat(job_row["started_at"]).timestamp()
        # Our launch receipt snapshots pointers before the subprocess is started.
        receipt = util.read_json(Path(job_row["log_path"]).parent / "workbench-launch.json") or util.read_json(Path(job_row["log_path"]).parent / "launch.json") or {}
        previous = receipt.get("pointer_before", {}).get(str(path.resolve()))
        if previous and previous == util.sha256_file(path):
            return {}
        if path.stat().st_mtime < started or run.stat().st_mtime < started:
            return {}
    except (OSError, ValueError, TypeError):
        return {}
    return data


def _register(run_dir, names):
    out = []
    base = Path(run_dir) if run_dir else None
    if not base or not base.is_dir():
        return out
    for name in names:
        p = base / name
        if p.is_file():
            out.append({"kind": name.rsplit(".", 1)[-1], "path": str(p)})
    return out


# ---------------------------------------------------------------- bhuman

def _bhuman_argv(mode, params):
    seconds = _int(params, "seconds", 30 if mode == "gait" else 60, 1800,
                   30 if mode == "gait" else 120)
    record = _bool(params, "record", True)
    unthrottled = _bool(params, "unthrottled", True)
    vision = _enum(params, "vision", {"cuda", "cpu"}, "cuda")
    headless = _bool(params, "headless", False)
    if headless and record:
        raise ParamError("--headless 与 --record 不可混用（正常相机需要可见 3D 视图）")
    timeout = _int(params, "timeout", 1, 3600, 240 if mode == "gait" else 480)
    argv = ["bash", _abs(BH["entry"]), mode, "--seconds", str(seconds)]
    if record:
        argv.append("--record")
    if unthrottled:
        argv.append("--unthrottled")
    if headless:
        argv.append("--headless")
    argv += ["--vision", vision, "--timeout", str(timeout)]
    if not os.environ.get("DISPLAY"):
        raise ParamError("缺少 DISPLAY：正常相机渲染需要 X11/OpenGL，不能静默降级")
    return argv, str(config.rp("bhuman")), timeout + 600, (["gpu", "simlock"] if vision == "cuda" else ["simlock"])


def _collect_bhuman(mode, job_row):
    pointer = _collect_pointer(config.rp(BH["runs_dir"]).parent / f"last-bhuman-{mode}.json", job_row)
    run_dir = pointer.get("run_dir")
    result = util.read_json(Path(run_dir) / "result.json") if run_dir else None
    verdict = "NOT_EVALUATED"
    if result:
        verdict = "PASS" if result.get("status") == "PASS" else "FAIL"
    arts = _register(run_dir, ["result.json", "launch.json", "execution.json",
                               f"bhuman-k1-{mode}.mp4", "console.log"])
    return {"run_dir": run_dir, "quality_verdict": verdict, "artifacts": arts,
            "result": result}


# ---------------------------------------------------------------- sim2sim

def _mujoco_argv(params):
    seconds = _int(params, "seconds", 6, 600, 120)
    viewer = _bool(params, "viewer", False)
    realtime = _bool(params, "realtime", False)
    checkpoint = params.get("checkpoint") or _abs(P["models"]["walk_pth"])
    ckpt = util.safe_resolve(checkpoint, [ROOT])
    if not ckpt.is_file():
        raise ParamError(f"策略检查点不存在: {ckpt}")
    KNOWN_NON_WALK = {"K1_kick_inner.pth": "踢球 59→13", "K1_stand_up.pth": "普通起身 73→22",
                      "K1_stand_up.pt": "普通起身 TorchScript", "K1_fast_standup.pth": "快速起身 72→22"}
    if ckpt.name in KNOWN_NON_WALK:
        raise ParamError(f"契约不匹配：{ckpt.name} 是{KNOWN_NON_WALK[ckpt.name]}模型，"
                         "不能选进行走任务（344→13）。不会自动猜测适配。")
    argv = ["bash", _abs(S2S["entry"]), "--seconds", str(seconds),
            "--checkpoint", str(ckpt)]
    if viewer:
        argv.append("--viewer")
        if not os.environ.get("DISPLAY"):
            raise ParamError("缺少 DISPLAY：--viewer 需要显示环境")
    if realtime:
        argv.append("--realtime")
    return argv, str(config.rp("bhuman/sim2sim")), min(int(seconds * 20) + 300, 3600), ["cpu_heavy"]


def _collect_mujoco(job_row):
    pointer = _collect_pointer(config.rp("bhuman/sim2sim/last-run.json"), job_row)
    run_dir = pointer.get("run_dir") or pointer.get("run")
    result = util.read_json(Path(run_dir) / "result.json") if run_dir else None
    verdict = "NOT_EVALUATED"
    if result:
        verdict = "PASS" if result.get("status") == "PASS" else "FAIL"
    arts = _register(run_dir, ["result.json", "launch.json", "policy-parity.json",
                               "observations.npy", "trajectory.npz"])
    return {"run_dir": run_dir, "quality_verdict": verdict, "artifacts": arts,
            "result": result}


def _mujoco_verify_argv(params):
    run = _existing_file(params, "run", None)
    export_dir = _existing_file(params, "export_dir", None)
    util.safe_resolve(run, [config.rp(S2S["runs_dir"])])
    util.safe_resolve(export_dir, [config.rp(TR["exports_dir"])])
    argv = ["bash", _abs(S2S["verify_entry"]), "--run", run, "--export-dir", export_dir]
    return argv, str(config.rp("bhuman/sim2sim")), 900, []


def _collect_mujoco_verify(job_row):
    params = job_row["params"]
    parity_path = Path(params["run"]) / "policy-parity.json"
    parity = util.read_json(parity_path)
    if not parity_path.exists() or parity_path.stat().st_mtime < datetime.fromisoformat(job_row["started_at"]).timestamp():
        parity = None
    verdict = "NOT_EVALUATED"
    if parity:
        verdict = "PASS" if parity.get("status") == "PASS" or parity.get("verdict") == "PASS" else "FAIL"
        if parity.get("overall_pass") is True:
            verdict = "PASS"
    return {"run_dir": params.get("run"), "quality_verdict": verdict,
            "artifacts": _register(params.get("run"), ["policy-parity.json"]),
            "result": parity}


# ---------------------------------------------------------------- training

def _train_argv(script, args, timeout=900, resources=("gpu",)):
    return (["bash", _abs(f"bhuman/k1-training/scripts/{script}")] + args,
            _abs("bhuman/k1-training"), timeout, list(resources))


def _replay_argv(params):
    task = _enum(params, "task", {"K1", "K1_Ball", "K1_Stand_Up"}, "K1")
    envs = _int(params, "envs", 1, 256, 4)
    steps = _int(params, "steps", 1, 1000, 1000)
    return _train_argv("run_replay.sh", [task, str(envs), str(steps)])


def _walk_stability_argv(params):
    envs = _int(params, "envs", 1, 4096, 64)
    iters = _int(params, "iterations", 1, 100, 3)
    seed = _int(params, "seed", 0, 2**31 - 1, 42)
    mode = _enum(params, "mode", {"warm-start", "full"}, "warm-start")
    preset = _enum(params, "preset", {"reference", "critic"}, "reference")
    ckpt_raw = params.get("checkpoint")
    if mode == "full" and not ckpt_raw:
        raise ParamError("full 恢复必须显式提供本项目同配方检查点")
    ckpt = _existing_file(params, "checkpoint",
                          _abs(P["models"]["walk_pth"]))
    if mode == "full" and ckpt.endswith("K1_walk.pth"):
        raise ParamError("full 恢复不能使用公开 actor 检查点冒充；请提供本项目 full 检查点")
    return _train_argv("run_walk_stability.sh",
                       [str(envs), str(iters), str(seed), mode, ckpt, preset])


def _walk_eval_argv(params):
    policy = _existing_file(params, "policy", _abs(P["models"]["walk_pth"]))
    KNOWN_NON_WALK = {"K1_kick_inner.pth", "K1_stand_up.pth", "K1_stand_up.pt",
                      "K1_fast_standup.pth"}
    if Path(policy).name in KNOWN_NON_WALK:
        raise ParamError(f"契约不匹配：{Path(policy).name} 不是行走 344→13 模型")
    seed = _int(params, "seed", 0, 2**31 - 1, 2027)
    seg = _int(params, "seg_steps", 10, 1000, 100)
    envs = _int(params, "envs", 1, 64, 8)
    args = [policy, str(seed), str(seg), str(envs)]
    baseline = params.get("baseline")
    if baseline:
        base = util.safe_resolve(baseline, [ROOT])
        if not base.is_file() or base.name != "results.json":
            raise ParamError("--baseline 必须指向已有评估的 results.json")
        args += ["--baseline", str(base)]
    return _train_argv("run_walk_eval.sh", args)


def _export_argv(params):
    task = _enum(params, "task", {"K1", "K1_Ball", "K1_Stand_Up"}, "K1")
    ckpt = _existing_file(params, "checkpoint", None)
    mode = _enum(params, "mode", {"actor", "torchscript"}, "actor")
    dest = _new_dir(params, "output_dir", _abs(TR["exports_dir"]))
    return _train_argv("run_export.sh", [task, ckpt, dest, mode])


def _env_check_argv(params):
    return _train_argv("run_env_check.sh", [], timeout=300, resources=())


def _collect_training(name_fn):
    def collect(job_row):
        name = name_fn(job_row["params"]) if callable(name_fn) else name_fn
        pointer = _collect_pointer(
            config.rp("bhuman/k1-training/manifests") / f"last_{name}.json", job_row)
        run_dir = pointer.get("run_dir")
        verdict = "NOT_EVALUATED"
        result = None
        if run_dir:
            if "walk_eval" in name:
                status = util.read_json(Path(run_dir) / "evaluation-status.json")
                result = util.read_json(Path(run_dir) / "results.json")
                if status:
                    if status.get("execution_status") == "FAIL":
                        verdict = "FAIL"
                    elif status.get("coverage_status") == "INSUFFICIENT_COVERAGE":
                        verdict = "INSUFFICIENT"
                    else:
                        # 评估器自身不认证质量；覆盖足够时仍只报告
                        verdict = "NOT_EVALUATED"
            elif "export" in name or "verify" in name:
                verdict = "PASS" if pointer.get("status") == "PASS" else (
                    "FAIL" if pointer.get("status") == "FAIL" else "NOT_EVALUATED")
        arts = _register(run_dir, ["execution.json", "launch.json", "results.json",
                                   "evaluation-status.json", "metrics.jsonl",
                                   "resume_validation.json", "console.log"])
        return {"run_dir": run_dir, "quality_verdict": verdict, "artifacts": arts,
                "result": result or pointer}
    return collect


# ---------------------------------------------------------------- registry

TASKS = {
    "bhuman_gait": {
        "label": "官方步态 30s（可录像）", "chain": "bhuman",
        "desc": "官方 WalkingEngine + 正常渲染相机；哈希保护官方文件",
        "argv": lambda p: _bhuman_argv("gait", p),
        "collect": lambda row: _collect_bhuman("gait", row),
        "form": [
            {"name": "seconds", "label": "仿真秒数", "type": "int", "min": 30, "max": 1800, "default": 30},
            {"name": "record", "label": "录制 MP4", "type": "bool", "default": True},
            {"name": "unthrottled", "label": "解除实时限速（物理步长不变）", "type": "bool", "default": True},
            {"name": "vision", "label": "视觉后端", "type": "enum", "choices": ["cuda", "cpu"], "default": "cuda"},
            {"name": "timeout", "label": "墙钟超时(s)", "type": "int", "min": 1, "max": 3600, "default": 240},
        ],
    },
    "bhuman_match": {
        "label": "六机 3v3 比赛（正常视觉）", "chain": "bhuman",
        "desc": "正常渲染相机感知，非真值；GPU 视觉与训练互斥",
        "argv": lambda p: _bhuman_argv("match", p),
        "collect": lambda row: _collect_bhuman("match", row),
        "form": [
            {"name": "seconds", "label": "仿真秒数", "type": "int", "min": 60, "max": 1800, "default": 120},
            {"name": "record", "label": "录制 MP4", "type": "bool", "default": True},
            {"name": "unthrottled", "label": "解除实时限速", "type": "bool", "default": True},
            {"name": "vision", "label": "视觉后端", "type": "enum", "choices": ["cuda", "cpu"], "default": "cuda"},
            {"name": "timeout", "label": "墙钟超时(s)", "type": "int", "min": 1, "max": 3600, "default": 480},
        ],
    },
    "mujoco_walk": {
        "label": "MuJoCo 行走回放", "chain": "sim2sim",
        "desc": "CPU actor + MuJoCo 物理；默认官方行走检查点；候选需显式选择",
        "argv": _mujoco_argv, "collect": _collect_mujoco,
        "form": [
            {"name": "seconds", "label": "仿真秒数", "type": "int", "min": 6, "max": 600, "default": 120},
            {"name": "checkpoint", "label": "策略检查点(绝对路径)", "type": "path", "default": ""},
            {"name": "viewer", "label": "可视化窗口", "type": "bool", "default": False},
            {"name": "realtime", "label": "实时 pacing", "type": "bool", "default": False},
        ],
    },
    "mujoco_verify_policy": {
        "label": "MuJoCo 实际输入×三方后端比对", "chain": "sim2sim",
        "desc": "用 run 的 observations.npy 比对 TorchScript 与官方比赛 ONNX",
        "argv": _mujoco_verify_argv, "collect": _collect_mujoco_verify,
        "form": [
            {"name": "run", "label": "sim2sim run 目录", "type": "path", "default": ""},
            {"name": "export_dir", "label": "导出目录(同检查点)", "type": "path", "default": ""},
        ],
    },
    "train_env_check": {
        "label": "训练环境只读检查", "chain": "training",
        "desc": "解释器/包版本/依赖一致性；不触碰 GPU 算子",
        "argv": _env_check_argv, "collect": lambda row: {"quality_verdict": "NOT_EVALUATED", "artifacts": []},
        "form": [],
    },
    "train_replay": {
        "label": "Gym 策略回放", "chain": "training",
        "desc": "官方/指定检查点有界回放；actor 严格加载",
        "argv": _replay_argv, "collect": _collect_training(lambda p: f"replay_{p.get('task', 'K1')}"),
        "form": [
            {"name": "task", "label": "任务", "type": "enum", "choices": ["K1", "K1_Ball", "K1_Stand_Up"], "default": "K1"},
            {"name": "envs", "label": "环境数", "type": "int", "min": 1, "max": 256, "default": 4},
            {"name": "steps", "label": "策略步数", "type": "int", "min": 1, "max": 1000, "default": 1000},
        ],
    },
    "train_walk_stability": {
        "label": "行走稳定化训练（实验）", "chain": "training",
        "desc": "reference 配方为本机实验配方；warm-start 仅 actor 初始化；full 需显式父检查点",
        "argv": _walk_stability_argv, "collect": None,  # set below (name depends on params)
        "form": [
            {"name": "envs", "label": "环境数", "type": "int", "min": 1, "max": 4096, "default": 64},
            {"name": "iterations", "label": "迭代轮数", "type": "int", "min": 1, "max": 100, "default": 3},
            {"name": "seed", "label": "训练种子", "type": "int", "min": 0, "max": 2147483647, "default": 42},
            {"name": "mode", "label": "加载语义", "type": "enum", "choices": ["warm-start", "full"], "default": "warm-start"},
            {"name": "checkpoint", "label": "检查点(full 必填)", "type": "path", "default": ""},
            {"name": "preset", "label": "配方", "type": "enum", "choices": ["reference", "critic"], "default": "reference"},
        ],
    },
    "train_walk_eval": {
        "label": "行走独立评估", "chain": "training",
        "desc": "固定命令日程；质量判定 REPORT_ONLY，与官方基线并排显示",
        "argv": _walk_eval_argv, "collect": _collect_training(lambda p: f"walk_eval_s{p.get('seed', 2027)}"),
        "form": [
            {"name": "policy", "label": "策略 .pth", "type": "path", "default": ""},
            {"name": "seed", "label": "评估种子", "type": "int", "min": 0, "max": 2147483647, "default": 2027},
            {"name": "seg_steps", "label": "分段步数", "type": "int", "min": 10, "max": 1000, "default": 100},
            {"name": "envs", "label": "环境数", "type": "int", "min": 1, "max": 64, "default": 8},
            {"name": "baseline", "label": "基线 results.json(可选)", "type": "path", "default": ""},
        ],
    },
    "train_export": {
        "label": "导出 + 三方校验", "chain": "training",
        "desc": "导出 opset11 并做 PyTorch/TorchScript/ORT-CPU 校验；新目录",
        "argv": _export_argv, "collect": _collect_training("export_K1"),
        "form": [
            {"name": "task", "label": "任务", "type": "enum", "choices": ["K1", "K1_Ball", "K1_Stand_Up"], "default": "K1"},
            {"name": "checkpoint", "label": "检查点", "type": "path", "default": ""},
            {"name": "output_dir", "label": "新输出目录名(exports/ 下)", "type": "str", "default": ""},
            {"name": "mode", "label": "加载语义", "type": "enum", "choices": ["actor", "torchscript"], "default": "actor"},
        ],
    },
}


def _stability_collect(job_row):
    p = job_row["params"]
    name = f"walk_{p.get('preset', 'reference')}_{p.get('mode', 'warm-start')}_s{p.get('seed', 42)}"
    return _collect_training(name)(job_row)


TASKS["train_walk_stability"]["collect"] = _stability_collect


def _export_collect(job_row):
    p = job_row["params"]
    task = p.get("task", "K1")
    out_dir = str(config.rp(TR["exports_dir"]) / p["output_dir"]) if p.get("output_dir") else None
    pointer = _collect_pointer(
        config.rp("bhuman/k1-training/manifests") / f"last_verify_export_{task}.json",
        job_row)
    run_dir = pointer.get("run_dir")
    verdict = "NOT_EVALUATED"
    manifest = None
    if out_dir:
        manifest = util.read_json(Path(out_dir) / f"{task}_actor_manifest.json")
    if manifest and isinstance(manifest.get("tri_check"), dict):
        verdict = "PASS" if manifest["tri_check"].get("verdict") == "PASS" else "FAIL"
    arts = _register(run_dir, ["execution.json", "console.log"])
    if out_dir:
        arts += _register(out_dir, [f"{task}_actor_manifest.json", f"{task}_actor.onnx",
                                    f"{task}_actor.pt"])
    return {"run_dir": run_dir, "quality_verdict": verdict, "artifacts": arts,
            "result": manifest or pointer}


TASKS["train_export"]["collect"] = _export_collect


# ---------------------------------------------------------------- builds

def _desktop_build_argv(params):
    kind = _enum(params, "kind", {"Release", "Develop"}, "Release")
    argv = ["bash", _abs(BH["build_script"])]
    if kind == "Develop":
        argv.append("--develop")
    argv.append("--build")
    return argv, str(config.rp("bhuman/local-k1-validation-20261019")), 5400, ["cpu_heavy"]


def _collect_desktop_build(job_row):
    params = job_row["params"]
    kind = params.get("kind", "Release")
    binary = config.rp(BH["binary_release"] if kind == "Release" else BH["binary_develop"])
    info = {"binary": str(binary), "exists": binary.is_file()}
    if binary.is_file():
        info["sha256"] = util.sha256_file(binary)
        info["mtime"] = binary.stat().st_mtime
    return {"quality_verdict": "NOT_EVALUATED", "artifacts": [], "result": info}


def _arm_build_argv(params):
    kind = _enum(params, "kind", {"Release", "Develop"}, "Release")
    argv = ["bash", str(config.WB_DIR / "scripts" / "arm-build.sh"), "{JOB_DIR}", kind]
    return argv, str(config.WB_DIR), 7200, ["cpu_heavy"]


def _collect_arm_build(job_row):
    run_dir = str(config.WB_DIR / "runs" / job_row["job_id"])
    verify = util.read_json(Path(run_dir) / "arm-verify.json")
    verdict = "NOT_EVALUATED"
    if verify:
        verdict = "PASS" if verify.get("status") == "PASS" else "FAIL"
    return {"run_dir": run_dir, "quality_verdict": verdict,
            "artifacts": _register(run_dir, ["arm-verify.json", "cmake-configure.log",
                                             "cmake-build.log"]),
            "result": verify}


def _bundle_argv(params):
    mode = _enum(params, "mode", {"full", "resources"}, "full")
    argv = ["/usr/bin/python3", "-B", str(config.WB_DIR / "scripts" / "make_bundle.py"),
            "--out", "{JOB_DIR}/bhuman-k1-offline-arm64.run", "--mode", mode]
    return argv, str(config.WB_DIR), 1200, []


def _collect_bundle(job_row):
    run_dir = str(config.WB_DIR / "runs" / job_row["job_id"])
    arts = []
    for p in Path(run_dir).glob("*.run"):
        arts.append({"kind": "run", "path": str(p)})
    verification = util.read_json(Path(run_dir) / "bundle-verification.json")
    arts += _register(run_dir, ["bundle-verification.json", "bundle-manifest.json"])
    return {"run_dir": run_dir, "quality_verdict": (verification or {}).get("status", "NOT_EVALUATED"),
            "artifacts": arts, "result": verification or {"note": "离线包尚未核验；不代表可真机运行"}}


def _contract_argv(params):
    if not os.environ.get("DISPLAY"):
        raise ParamError("缺少 DISPLAY：生产 C++ 探针保持正常相机渲染")
    return (["bash", str(config.WB_DIR / "contracts/run-probe.sh"), "--output", "{JOB_DIR}"],
            str(config.WB_DIR), 1200, ["cpu_heavy", "simlock"])


def _collect_contract(job_row):
    run = config.WB_DIR / "runs" / job_row["job_id"]
    result = util.read_json(run / "compare-report.json")
    return {"run_dir": str(run), "quality_verdict": (result or {}).get("verdict", "NOT_EVALUATED"),
            "result": result, "artifacts": _register(run, ["launch.json", "result.json", "execution.json",
                "compare-report.json", "cpp-network-parity.json", "walk-probe.csv", "regression.json", "negative-tests.log"])}


TASKS_EXTRA = {
    "contract_walk_cpp": {
        "label": "生产 C++ 行走契约对照", "chain": "bhuman",
        "desc": "独立探针副本：真实 WalkingEngine 历史/344维输入/13维解码；正常相机；不修改官方基线",
        "argv": _contract_argv, "collect": _collect_contract, "form": [],
    },
    "bundle_offline": {
        "label": "离线部署包 (.run)", "chain": "bhuman",
        "desc": "ARM64 ELF+模型+配置+依赖+许可证+manifest；仅 --info/--verify/--extract",
        "argv": _bundle_argv, "collect": _collect_bundle,
        "form": [
            {"name": "mode", "label": "模式", "type": "enum", "choices": ["full", "resources"], "default": "full"},
        ],
    },
    "bhuman_build_desktop": {
        "label": "桌面编译 (SimRobot)", "chain": "bhuman",
        "desc": "cmake+Ninja 增量编译 Release/Develop；产物写回 bhuman-local/Build",
        "argv": _desktop_build_argv, "collect": _collect_desktop_build,
        "form": [
            {"name": "kind", "label": "构建类型", "type": "enum", "choices": ["Release", "Develop"], "default": "Release"},
        ],
    },
    "arm_build": {
        "label": "离线 ARM64 构建 (Booster)", "chain": "bhuman",
        "desc": "clang++ --target=aarch64 + 随库 sysroot；仅构建与静态核验，不部署",
        "argv": _arm_build_argv, "collect": _collect_arm_build,
        "form": [
            {"name": "kind", "label": "构建类型", "type": "enum", "choices": ["Release", "Develop"], "default": "Release"},
        ],
    },
}
TASKS.update(TASKS_EXTRA)


def build_job(task_type, params):
    spec = TASKS.get(task_type)
    if not spec:
        raise ParamError(f"未登记的任务类型: {task_type}")
    if not isinstance(params, (dict, type(None))):
        raise ParamError("params 必须是对象")
    params = dict(params or {})
    allowed = {f["name"] for f in spec["form"]}
    if task_type in ("bhuman_gait", "bhuman_match"):
        allowed.add("headless")
    unknown = set(params) - allowed
    if unknown:
        raise ParamError("未登记的参数: " + ", ".join(sorted(unknown)))
    try:
        argv, cwd, timeout, resources = spec["argv"](params)
    except ValueError as exc:
        if isinstance(exc, ParamError):
            raise
        raise ParamError(str(exc))
    return {"argv": argv, "cwd": cwd, "timeout": timeout, "resources": resources,
            "params": params}


def preview(task_type, params):
    job = build_job(task_type, params)
    return {"argv": job["argv"], "cwd": job["cwd"], "timeout": job["timeout"],
            "resources": job["resources"]}
