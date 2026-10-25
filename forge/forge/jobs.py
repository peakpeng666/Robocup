"""Job runner: whitelisted job types executed as ``forge`` CLI subprocesses.

* parameters are validated and turned into an argv array (no shell, no free-form command);
* each job declares resource tokens; jobs whose tokens are free run concurrently
  (e.g. an ARM build next to a training run), conflicting ones queue
  (GPU training vs GPU-vision match, two SimRobot instances, two heavy builds);
* every job runs in its own process group and only that group is ever signalled;
* state is persisted in SQLite; a restart marks unfinished jobs ``interrupted`` and never
  re-launches them.
"""
from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from . import arena as arena_mod, paths, util

TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}
FORGE_CLI = [str(paths.INTERPRETERS["forge"]), "-B", "-m", "forge.cli"]


class JobError(ValueError):
    pass


def _int(params, name, lo, hi, default):
    value = params.get(name, default)
    if isinstance(value, bool):
        raise JobError(f"{name} 必须是整数")
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise JobError(f"{name} 必须是整数")
    if not lo <= value <= hi:
        raise JobError(f"{name} 必须在 {lo}..{hi}")
    return value


def _choice(params, name, choices, default):
    value = params.get(name, default)
    if value not in choices:
        raise JobError(f"{name} 必须是 {list(choices)} 之一")
    return value


def _ident(params, name, required=True):
    value = params.get(name)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value or "/" in value or value.startswith(".") or len(value) > 120:
        raise JobError(f"{name} 不是合法标识")
    return value


def _path_inside(params, name, roots, required=True):
    value = params.get(name)
    if not value and not required:
        return None
    if not isinstance(value, str):
        raise JobError(f"{name} 必须是路径")
    real = Path(os.path.realpath(value))
    if not any(str(real).startswith(str(Path(os.path.realpath(r))) + os.sep) for r in roots):
        raise JobError(f"{name} 必须位于 {', '.join(str(r) for r in roots)} 之内")
    if not real.is_file():
        raise JobError(f"{name} 文件不存在: {real}")
    return str(real)


CHECKPOINT_ROOTS = (paths.RUNS / "train", paths.TRAINING / "runs", paths.ISAACGYMRL / "pre-trained")


def _build_match(p):
    seconds = _int(p, "seconds", 60, 1800, 120)
    vision = _choice(p, "vision", ("cuda", "cpu"), "cuda")
    record = bool(p.get("record", True))
    tag = util.safe_name(str(p.get("tag", "match")), 32)
    arena = util.safe_name(str(p.get("arena", "main")), 32)
    argv = ["match", "--seconds", str(seconds), "--vision", vision, "--tag", tag, "--arena", arena, "--verbose"]
    if not record:
        argv.append("--no-record")
    if not os.environ.get("DISPLAY"):
        raise JobError("服务进程没有 DISPLAY：正常相机渲染需要桌面 X11/OpenGL")
    return argv, {"display", "simlock", "arena"} | ({"gpu"} if vision == "cuda" else set())


def _build_series(p):
    a, b = _ident(p, "pack_a"), _ident(p, "pack_b")
    rounds = _int(p, "rounds", 1, 10, 2)
    seconds = _int(p, "seconds", 60, 1800, 120)
    if not os.environ.get("DISPLAY"):
        raise JobError("服务进程没有 DISPLAY")
    arena = util.safe_name(str(p.get("arena", "main")), 32)
    return ["series", a, b, "--rounds", str(rounds), "--seconds", str(seconds), "--arena", arena], {"display", "simlock", "gpu", "arena"}


def _build_flash(p):
    team = _int(p, "team", 0, 255, 5)
    if team not in arena_mod.TEAM_NUMBERS:
        raise JobError(f"队伍号必须是 {arena_mod.TEAM_NUMBERS}")
    return ["flash", str(team), _ident(p, "pack_id"), "--arena", util.safe_name(str(p.get("arena", "main")), 32)], {"arena", "simlock"}


def _build_train(p):
    from .training import PRESETS

    argv = ["train", "--preset", _choice(p, "preset", tuple(PRESETS), "thu-amp"),
            "--envs", str(_int(p, "envs", 1, 4096, 64)), "--iterations", str(_int(p, "iterations", 1, 2000, 3)),
            "--seed", str(_int(p, "seed", 0, 2**31 - 1, 42)), "--timeout", str(_int(p, "timeout", 60, 21600, 900)),
            "--save-interval", str(_int(p, "save_interval", 1, 1000, 50))]
    checkpoint = _path_inside(p, "checkpoint", CHECKPOINT_ROOTS, required=False)
    if checkpoint:
        argv += ["--checkpoint", checkpoint]
    return argv, {"gpu"}


def _build_export(p):
    checkpoint = _path_inside(p, "checkpoint", CHECKPOINT_ROOTS)
    name = util.safe_name(str(p.get("name", "candidate")), 32)
    return ["export", checkpoint, name, "--verbose"], {"gpu"}


def _build_eval(p):
    policy = _path_inside(p, "policy", CHECKPOINT_ROOTS)
    argv = ["eval", policy, "--seed", str(_int(p, "seed", 0, 2**31 - 1, 2027)),
            "--seg-steps", str(_int(p, "seg_steps", 10, 1000, 100)), "--envs", str(_int(p, "envs", 1, 64, 8)), "--verbose"]
    return argv, {"gpu"}


def _build_stress(p):
    policy = _ident(p, "pack_id")
    return ["stress", policy, "--worlds", str(_int(p, "worlds", 1, 16384, 2048)),
            "--seconds", str(_int(p, "seconds", 1, 120, 20)), "--seed", str(_int(p, "seed", 0, 2**31 - 1, 2027)),
            "--push-force", str(_int(p, "push_force", 0, 400, 0)), "--tag", util.safe_name(str(p.get("tag", policy)), 40)], {"gpu"}


def _build_atlas(p):
    from . import atlas, packs

    raw = p.get("packs") or ([p["pack_id"]] if p.get("pack_id") else [])
    if not isinstance(raw, list) or not 1 <= len(raw) <= 6:
        raise JobError("packs 需为 1..6 个运控包 ID")
    pack_ids = [_ident({"p": v}, "p") for v in raw]
    baseline = _ident({"b": p.get("baseline", packs.BASELINE_ID)}, "b")
    ordered = [baseline] + [v for v in pack_ids if v != baseline]
    if len(set(ordered)) != len(ordered):
        raise JobError("运控包不能重复")
    axes = p.get("axes")
    if axes is not None and (not isinstance(axes, list) or not axes or any(a not in atlas.REQUIRED_AXES for a in axes)):
        raise JobError(f"axes 必须是 {list(atlas.REQUIRED_AXES)} 的非空子集")
    scale = p.get("replica_scale", 1.0)
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not 0.25 <= float(scale) <= 4:
        raise JobError("replica_scale 必须在 0.25..4")
    argv = ["atlas", "run", *ordered, "--baseline", baseline, "--seed", str(_int(p, "seed", 0, 2**31 - 1, 2027)),
            "--replica-scale", str(float(scale)), "--tag", util.safe_name(str(p.get("tag") or "-vs-".join(ordered[1:]) or baseline), 48)]
    if axes:
        argv += ["--axes", ",".join(axes)]
    return argv, {"gpu"}


def _build_bridge(p):
    from .bridge import analysis

    experiments = p.get("experiments", list(analysis.EXPERIMENTS))
    if not isinstance(experiments, list) or any(e not in analysis.EXPERIMENTS for e in experiments):
        raise JobError(f"experiments 必须是 {list(analysis.EXPERIMENTS)} 的子集")
    session = bool(p.get("session", True))
    if not experiments and not session:
        raise JobError("至少选择一个实验或实时会话")
    argv = ["bridge", "run", "--experiments", ",".join(experiments), "--seeds", str(_int(p, "seeds", 1, 10, 4)),
            "--tag", util.safe_name(str(p.get("tag") or "motion-bridge"), 40)]
    controllers = p.get("controllers")
    if controllers:
        allowed = ("bhuman-training", "bhuman-real-gains", "booster-deploy", "firmware-gait")
        if not isinstance(controllers, list) or any(c not in allowed for c in controllers):
            raise JobError(f"controllers 必须是 {list(allowed)} 的子集")
        argv += ["--controllers", ",".join(controllers)]
    if not session:
        argv.append("--no-session")
    references = p.get("simrobot") or {}
    if references:
        if not isinstance(references, dict) or "crosssim" not in experiments:
            raise JobError("simrobot 需为 {控制器: motion 运行 ID}，且实验包含 crosssim")
        for controller, run_id in references.items():
            if controller not in analysis.SIMROBOT_EXPECTED:
                raise JobError(f"SimRobot 对照只支持 {sorted(analysis.SIMROBOT_EXPECTED)}")
            run_id = _ident({"r": run_id}, "r")
            if not (paths.RUNS / "motion" / run_id / "result.json").is_file():
                raise JobError(f"motion 运行不存在: {run_id}")
            argv += ["--simrobot", f"{controller}={paths.RUNS / 'motion' / run_id}"]
    return argv, {"cpu_heavy"}


def _build_duel(p):
    if not os.environ.get("DISPLAY"):
        raise JobError("对决需要桌面 DISPLAY（正常相机渲染）")
    vision = _choice(p, "vision", ("cuda", "cpu"), "cuda")
    resources = {"display", "simlock", "arena"} | ({"gpu"} if vision == "cuda" else set())
    if p.get("resume"):
        return ["duel", "resume", _ident(p, "resume"), "--extra-pairs", str(_int(p, "extra_pairs", 0, 60, 0))], resources
    kind = _choice(p, "kind", ("motion", "strategy"), "motion")
    argv = ["duel", kind, _ident(p, "candidate"), "--max-pairs", str(_int(p, "max_pairs", 1, 60, 10)),
            "--seconds", str(_int(p, "seconds", 60, 300, 120)), "--vision", vision,
            "--arena", util.safe_name(str(p.get("source_arena", "main")), 48)]
    if p.get("baseline"):
        argv += ["--baseline", _ident(p, "baseline")]
    if kind == "strategy" and p.get("motion_pack"):
        argv += ["--motion-pack", _ident(p, "motion_pack")]
    for name, lo, hi in (("alpha", 0.001, 0.2), ("delta", 0.05, 4.0)):
        if name in p:
            value = p[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= float(value) <= hi:
                raise JobError(f"{name} 必须在 {lo}..{hi}")
            argv += [f"--{name}", str(float(value))]
    if p.get("record") is False:
        argv.append("--no-record")
    return argv, resources


def _build_pipeline(p):
    checkpoint = _path_inside(p, "checkpoint", CHECKPOINT_ROOTS)
    name = util.safe_name(str(p.get("name", "candidate")), 32)
    if not os.environ.get("DISPLAY"):
        raise JobError("服务进程没有 DISPLAY：流水线包含 SimRobot 比赛")
    return ["pipeline", checkpoint, name, "--rounds", str(_int(p, "rounds", 1, 10, 2)),
            "--push-force", str(_int(p, "push_force", 0, 400, 60))], {"gpu", "display", "simlock", "arena"}


def _build_bundle(p):
    return ["bundle", _ident(p, "variant"), _ident(p, "pack_id")], {"cpu_heavy"}


def _build_validation(p):
    from . import packs, strategies

    if not os.environ.get("DISPLAY"):
        raise JobError("SimRobot 验证需要桌面 DISPLAY")
    mode = _choice(p, "mode", ("motion", "strategy"), "motion")
    vision = _choice(p, "vision", ("cuda", "cpu"), "cuda")
    motion_id = _ident({"motion_pack": p.get("motion_pack", packs.BASELINE_ID)}, "motion_pack")
    strategy_id = _ident({"strategy_id": p.get("strategy_id", strategies.BASELINE_ID)}, "strategy_id")
    if mode == "motion" and strategy_id != strategies.BASELINE_ID:
        raise JobError("运控验证应保持官方策略")
    argv = ["validate", mode, "--motion-pack", motion_id, "--strategy", strategy_id,
            "--arena", util.safe_name(str(p.get("source_arena", "main")), 48),
            "--repetitions", str(_int(p, "repetitions", 1, 5, 1)), "--seconds", str(_int(p, "seconds", 60, 600, 120)),
            "--vision", vision]
    if p.get("record") is False:
        argv.append("--no-record")
    return argv, {"arena", "simlock", "display"} | ({"gpu"} if vision == "cuda" else set())


def _build_build(p):
    variant = _ident(p, "variant")
    argv = ["build", variant, "--target", _choice(p, "target", ("simrobot", "booster"), "booster"),
            "--kind", _choice(p, "kind", ("Release", "Develop"), "Release"), "--jobs", str(_int(p, "jobs", 1, 32, 12)),
            "--verbose"]
    return argv, {"cpu_heavy"}


JOB_TYPES = {
    "validation": {"label": "SimRobot 运控与策略验证", "builder": _build_validation},
    "match": {"label": "队伍对抗赛", "builder": _build_match},
    "series": {"label": "主客互换系列赛", "builder": _build_series},
    "duel": {"label": "序贯对决", "builder": _build_duel},
    "flash": {"label": "刷运控", "builder": _build_flash},
    "train": {"label": "B-Human×火神 训练", "builder": _build_train},
    "export": {"label": "导出→运控包", "builder": _build_export},
    "eval": {"label": "行走评估", "builder": _build_eval},
    "stress": {"label": "MuJoCo Warp 压力评测", "builder": _build_stress},
    "atlas": {"label": "易损性图谱", "builder": _build_atlas},
    "bridge": {"label": "运控桥验证（虚拟 K1）", "builder": _build_bridge},
    "pipeline": {"label": "候选全流程", "builder": _build_pipeline},
    "bundle": {"label": "离线机器人包", "builder": _build_bundle},
    "build": {"label": "编译", "builder": _build_build},
}


class JobManager:
    def __init__(self, db_path: Path = paths.DB_PATH, autostart: bool = True):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._procs: dict[str, subprocess.Popen] = {}
        self._held: dict[str, set] = {}
        self._cancel: set[str] = set()
        self._stop = threading.Event()
        self._external, self._external_at = set(), 0.0
        self._init_db()
        with self._db() as db:
            rows = db.execute("SELECT id FROM jobs WHERE status IN ('queued','running')").fetchall()
            for (job_id,) in rows:
                db.execute("UPDATE jobs SET status='interrupted', ended_at=? WHERE id=?", (util.now_iso(), job_id))
        self._thread = threading.Thread(target=self._loop, daemon=True, name="forge-jobs")
        if autostart:
            self._thread.start()

    # ------------------------------------------------------------------ storage
    def _db(self):
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, type TEXT, params TEXT, argv TEXT, resources TEXT, status TEXT,
                created_at TEXT, started_at TEXT, ended_at TEXT, exit_code INTEGER, pid INTEGER,
                log_path TEXT, error TEXT)""")

    def _row(self, row) -> dict:
        data = dict(row)
        for key in ("params", "argv", "resources"):
            data[key] = json.loads(data[key]) if data.get(key) else None
        return data

    def list(self, limit=200) -> list[dict]:
        with self._db() as db:
            return [self._row(r) for r in db.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))]

    def get(self, job_id: str) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._row(row) if row else None

    # ------------------------------------------------------------------ control
    def preview(self, job_type: str, params: dict) -> dict:
        if job_type not in JOB_TYPES:
            raise JobError(f"未登记的作业类型: {job_type}")
        if not isinstance(params, dict):
            raise JobError("params 必须是对象")
        argv, resources = JOB_TYPES[job_type]["builder"](params)
        return {"argv": FORGE_CLI + argv, "resources": sorted(resources), "cwd": str(paths.FORGE)}

    def submit(self, job_type: str, params: dict) -> str:
        spec = self.preview(job_type, params)
        job_id = f"{util.stamp()}_{job_type}_{uuid.uuid4().hex[:6]}"
        log_dir = paths.RUNS / "jobs" / job_id
        log_dir.mkdir(parents=True)
        with self._lock, self._db() as db:
            if self._stop.is_set():
                raise JobError("服务正在停止，不能提交新作业")
            db.execute("INSERT INTO jobs(id,type,params,argv,resources,status,created_at,log_path) VALUES(?,?,?,?,?,?,?,?)",
                       (job_id, job_type, json.dumps(params, ensure_ascii=False), json.dumps(spec["argv"]),
                        json.dumps(spec["resources"]), "queued", util.now_iso(), str(log_dir / "console.log")))
        return job_id

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self.get(job_id)
            if not job:
                raise KeyError(job_id)
            if job["status"] == "queued":
                with self._db() as db:
                    db.execute("UPDATE jobs SET status='cancelled', ended_at=? WHERE id=? AND status='queued'",
                               (util.now_iso(), job_id))
                return True
            if job["status"] == "running":
                self._cancel.add(job_id)
                return True
            return False

    @contextmanager
    def reserve(self, resources: set):
        """Atomic reservation for synchronous HTTP work, shared with the scheduler."""
        owner = "request:" + uuid.uuid4().hex
        with self._lock:
            if self._stop.is_set() or resources & self._busy():
                raise JobError("比赛或配置作业正在使用所需资源，请稍后重试")
            self._held[owner] = set(resources)
        try:
            yield
        finally:
            with self._lock:
                self._held.pop(owner, None)

    def shutdown(self):
        with self._lock:
            self._stop.set()
            self._cancel.update(self._procs)
            with self._db() as db:
                db.execute("UPDATE jobs SET status='interrupted', ended_at=? WHERE status='queued'", (util.now_iso(),))
        # Stop scheduling first, then explicitly drain processes. The previous loop
        # stopped supervision before it could act on these cancellation requests.
        if self._thread.is_alive():
            self._thread.join()
        self._supervise()
        if self._procs:
            raise RuntimeError("作业进程尚未停止，不能确认服务已安全关闭")

    # ------------------------------------------------------------------ scheduler
    def _busy(self) -> set:
        with self._lock:
            held = set().union(*self._held.values()) if self._held else set()
        return held | self._external_busy()

    def _own_pids(self) -> set:
        pids = set()
        try:
            import psutil

            with self._lock:
                roots = [p.pid for p in self._procs.values()]
            for root in roots:
                try:
                    pids.add(root)
                    pids |= {c.pid for c in psutil.Process(root).children(recursive=True)}
                except psutil.Error:
                    continue
        except ImportError:
            pass
        return pids

    def _external_busy(self) -> set:
        """Resources occupied by work this manager did not start (CLI runs, other launchers)."""
        now = time.time()
        if now - getattr(self, "_external_at", 0) < 3:
            return self._external
        busy = set()
        try:
            rows = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_gpu_memory", "--format=csv,noheader,nounits"],
                                  capture_output=True, text=True, timeout=5).stdout
            own = self._own_pids()
            for row in rows.splitlines():
                try:
                    pid, memory = (int(x) for x in row.split(","))
                except ValueError:
                    continue
                if pid not in own and memory > 1024:
                    busy.add("gpu")
        except (OSError, subprocess.SubprocessError):
            pass
        import fcntl

        with self._lock:
            own_sim = any("simlock" in held for held in self._held.values())
        if not own_sim:
            try:
                with paths.BH_SIM_LOCK.open("a") as stream:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(stream, fcntl.LOCK_UN)
            except BlockingIOError:
                busy |= {"simlock", "display"}
        self._external, self._external_at = busy, now
        return busy

    def external(self) -> set:
        return set(self._external_busy())

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._schedule()
                self._supervise()
            except Exception as exc:  # the scheduler must never die
                util.write_json(paths.STATE / "scheduler-error.json", {"at": util.now_iso(), "error": repr(exc)})
            time.sleep(0.5)

    def _schedule(self):
        with self._db() as db:
            queued = [self._row(r) for r in db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at")]
        for job in queued:
            self._start(job)

    def _start(self, job):
        # Re-read under the same lock as cancel/reserve/shutdown. A queued snapshot
        # may already be cancelled or its resources reserved by an HTTP request.
        with self._lock:
            current = self.get(job["id"])
            if self._stop.is_set() or not current or current["status"] != "queued":
                return
            if set(current["resources"] or []) & self._busy():
                return
            self._start_locked(current)

    def _start_locked(self, job):
        log_path = Path(job["log_path"])
        env = dict(os.environ, PYTHONPATH=str(paths.FORGE), PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
        log = log_path.open("a")
        try:
            process = subprocess.Popen(job["argv"], cwd=paths.FORGE, env=env, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as exc:
            with self._db() as db:
                db.execute("UPDATE jobs SET status='failed', error=?, ended_at=? WHERE id=?",
                           (repr(exc), util.now_iso(), job["id"]))
            return
        finally:
            log.close()
        with self._lock:
            self._procs[job["id"]] = process
            self._held[job["id"]] = set(job["resources"] or [])
        with self._db() as db:
            db.execute("UPDATE jobs SET status='running', started_at=?, pid=? WHERE id=?",
                       (util.now_iso(), process.pid, job["id"]))

    def _supervise(self):
        with self._lock:
            items = list(self._procs.items())
        for job_id, process in items:
            if job_id in self._cancel and process.poll() is None:
                self._terminate(process)
            code = process.poll()
            if code is None:
                continue
            status = "cancelled" if job_id in self._cancel else ("succeeded" if code == 0 else "failed")
            if self._stop.is_set() and job_id in self._cancel:
                status = "interrupted"
            with self._db() as db:
                db.execute("UPDATE jobs SET status=?, exit_code=?, ended_at=? WHERE id=?",
                           (status, code, util.now_iso(), job_id))
            with self._lock:
                self._procs.pop(job_id, None)
                self._held.pop(job_id, None)
                self._cancel.discard(job_id)

    @staticmethod
    def _terminate(process: subprocess.Popen):
        """Stop the job and every descendant, including grandchildren that started their own
        session (SimRobot, managed training/export runs). Only processes observed as
        descendants of this job (with matching creation time) are signalled."""
        import psutil

        try:
            root = psutil.Process(process.pid)
            tree = [root] + root.children(recursive=True)
        except psutil.Error:
            tree = []
        identities = {(p.pid, p.create_time()) for p in tree if p.is_running()}

        def signal_tree(sig):
            groups = set()
            for proc in list(tree):
                try:
                    if (proc.pid, proc.create_time()) not in identities or not proc.is_running():
                        continue
                    groups.add(os.getpgid(proc.pid))
                    proc.send_signal(sig)
                except (psutil.Error, ProcessLookupError):
                    continue
            for group in groups:
                if group == os.getpgid(0):
                    continue  # never signal the server's own group
                try:
                    os.killpg(group, sig)
                except (ProcessLookupError, PermissionError):
                    pass

        signal_tree(signal.SIGTERM)
        _, alive = psutil.wait_procs(tree, timeout=15)
        if alive:
            signal_tree(signal.SIGKILL)
            psutil.wait_procs(alive, timeout=5)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
