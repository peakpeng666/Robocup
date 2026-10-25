"""Job manager: serial worker, process groups, bounded logs, SSE subscribers.

Only jobs created by this manager are touched; cancellation kills only the
job's own process group. A server restart marks leftover running/queued jobs
as interrupted and never restarts them automatically.
"""
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import threading
import time
import uuid

from . import config, db as db_mod, tasks as tasks_mod, util

STATUS_TERMINAL = {"succeeded", "failed", "cancelled", "timed_out", "interrupted"}
LOG_TAIL_KEEP = 2000  # lines kept in memory per job


class JobManager:
    def __init__(self, db: db_mod.DB, runs_dir: Path):
        self.db = db
        self.runs_dir = runs_dir
        runs_dir.mkdir(parents=True, exist_ok=True)
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._current = None          # job_id of running job
        self._procs = {}              # job_id -> Popen
        self._subscribers = {}        # job_id -> list[queue.Queue]
        self._tails = {}              # job_id -> deque-like list of recent lines
        self._cancel_requested = set()
        self._descendants = {}        # job_id -> set of descendant pids (tracked live)
        self._stopping = threading.Event()
        stale = self.db.query("SELECT job_id FROM jobs WHERE status IN ('queued','running')")
        for row in stale:
            self.db.execute("UPDATE jobs SET status='interrupted', ended_at=? WHERE job_id=?",
                            (util.now_local(), row["job_id"]))
            self.db.log_event("job_interrupted_on_boot", {"job_id": row["job_id"]})
        self._worker = threading.Thread(target=self._loop, daemon=True, name="job-worker")
        self._worker.start()

    # -------------------------------------------------------------- submit
    def submit(self, task_type, params):
        if self._stopping.is_set():
            raise tasks_mod.ParamError("工作台正在停止，不能启动新任务")
        job = tasks_mod.build_job(task_type, params)  # raises ParamError
        job_id = util.stamp() + "_" + uuid.uuid4().hex[:8]
        job_dir = self.runs_dir / job_id
        job_dir.mkdir(parents=True)
        self.db.execute(
            "INSERT INTO jobs(job_id,type,params_json,argv_json,cwd,status,created_at,"
            "timeout_s,log_path,resources_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (job_id, task_type, json.dumps(job["params"], ensure_ascii=False),
             json.dumps(job["argv"]), job["cwd"], "queued", util.now_local(),
             job["timeout"], str(job_dir / "console.log"),
             json.dumps(job["resources"])))
        self.db.log_event("job_queued", {"job_id": job_id, "type": task_type,
                                         "argv": job["argv"]})
        self._queue.put(job_id)
        return job_id

    def cancel(self, job_id):
        row = self.db.one("SELECT * FROM jobs WHERE job_id=?", (job_id,))
        if not row:
            raise KeyError(job_id)
        if row["status"] == "queued":
            self._cancel_requested.add(job_id)
            self.db.execute("UPDATE jobs SET status='cancelled', ended_at=? WHERE job_id=?",
                            (util.now_local(), job_id))
            self.db.log_event("job_cancelled", {"job_id": job_id, "phase": "queued"})
            return True
        if row["status"] != "running":
            return False
        # 只标记；实际终止由 worker 的 _terminate 统一做（含孙进程回收）。
        self._cancel_requested.add(job_id)
        return True

    # -------------------------------------------------------------- worker
    def _loop(self):
        while True:
            job_id = self._queue.get()
            if job_id is None:
                return
            row = self.db.one("SELECT * FROM jobs WHERE job_id=?", (job_id,))
            if not row or row["status"] != "queued":
                continue
            try:
                self._run(row)
            except Exception as exc:  # never kill the worker
                proc = self._procs.get(job_id)
                if proc and proc.poll() is None:
                    self._terminate(job_id, proc)
                self.db.execute("UPDATE jobs SET status='failed', error=?, ended_at=? WHERE job_id=?",
                                (f"工作台内部错误: {exc!r}", util.now_local(), job_id))
                self.db.log_event("job_internal_error", {"job_id": job_id, "error": repr(exc)})

    def _run(self, row):
        job_id = row["job_id"]
        argv = [a.replace("{JOB_DIR}", str(self.runs_dir / job_id)) for a in json.loads(row["argv_json"])]
        cwd = row["cwd"]
        timeout = row["timeout_s"]
        log_path = Path(row["log_path"])
        self._current = job_id
        updated = self.db.execute("UPDATE jobs SET status='running', started_at=? WHERE job_id=? AND status='queued'",
                                 (util.now_local(), job_id))
        if not updated.rowcount:
            self._current = None
            return
        pointer_paths = list(config.rp("bhuman/k1-training/manifests").glob("last_*.json"))
        pointer_paths += [config.rp("bhuman/sim2sim/last-run.json")]
        pointer_paths += list(config.rp("bhuman/local-k1-validation-20261019").glob("last-bhuman-*.json"))
        receipt = {"job_id": job_id, "argv": argv, "cwd": cwd, "timeout_s": timeout,
                   "created_at": util.now_local(),
                   "pointer_before": {str(p.resolve()): util.sha256_file(p) for p in pointer_paths if p.is_file()}}
        from . import identity
        receipt["identity"] = identity.capture()
        receipt["input_files"] = {a: identity.file_identity(a) for a in argv if a.startswith('/') and Path(a).is_file()}
        receipt_path = log_path.parent / "workbench-launch.json"
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        util.write_json(receipt_path, receipt)
        self.db.log_event("job_started", {"job_id": job_id})
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        exit_code, reason = None, None
        started = time.monotonic()
        try:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, errors="replace", bufsize=1,
                                    start_new_session=True)
            self._procs[job_id] = proc
            self.db.execute("UPDATE jobs SET pid=? WHERE job_id=?", (proc.pid, job_id))
            pump = threading.Thread(target=self._pump, args=(job_id, proc, log_path), daemon=True)
            pump.start()
            deadline = started + timeout
            while proc.poll() is None:
                self._descendants[job_id] = self._descendants_of(proc.pid)
                if self._stopping.is_set():
                    reason = "interrupted"
                elif job_id in self._cancel_requested:
                    reason = "cancelled"
                elif time.monotonic() > deadline:
                    reason = "timed_out"
                if reason:
                    self._terminate(job_id, proc)
                    break
                time.sleep(0.3)
            exit_code = proc.wait()
            if reason is None and job_id in self._cancel_requested:
                reason = "cancelled"
            pump.join(timeout=10)
            if proc.stdout:
                proc.stdout.close()
        except FileNotFoundError as exc:
            exit_code, reason = 127, f"入口不存在: {exc}"
        finally:
            self._procs.pop(job_id, None)
            self._cancel_requested.discard(job_id)
            self._descendants.pop(job_id, None)
            self._current = None
        if reason == "interrupted":
            status = "interrupted"
        elif reason == "cancelled":
            status = "cancelled"
        elif reason == "timed_out":
            status = "timed_out"
            exit_code = exit_code if exit_code not in (None, 0) else 124
        elif exit_code == 0:
            status = "succeeded"
        else:
            status = "failed"
        self.db.execute("UPDATE jobs SET status=?, exit_code=?, ended_at=? WHERE job_id=?",
                        (status, exit_code, util.now_local(), job_id))
        self._collect(job_id, row["type"])
        util.write_json(log_path.parent / "job-execution.json", {
            **self.db.one("SELECT job_id,type,status,quality_verdict,exit_code,started_at,ended_at,run_dir,error FROM jobs WHERE job_id=?", (job_id,)),
            "identity_at_end": identity.capture(), "robot_connected": False})
        p = log_path.parent / 'job-execution.json'
        self.db.execute('INSERT INTO artifacts(job_id,kind,path,sha256,size,created_at) VALUES(?,?,?,?,?,?)',
                        (job_id,'json',str(p),util.sha256_file(p),p.stat().st_size,util.now_local()))

    def shutdown(self):
        """Stop our queue and our child tree before the server exits."""
        self._stopping.set()
        self.db.execute("UPDATE jobs SET status='interrupted',ended_at=? WHERE status='queued'", (util.now_local(),))
        self._queue.put(None)
        self._worker.join(timeout=25)

    @staticmethod
    def _descendants_of(pid):
        """Snapshot the live descendant set of a pid via /proc PPid links."""
        ppid_of = {}
        try:
            entries = os.listdir("/proc")
        except OSError:
            return set()
        for name in entries:
            if not name.isdigit():
                continue
            try:
                with open(f"/proc/{name}/status", "r", encoding="ascii", errors="ignore") as fh:
                    for line in fh:
                        if line.startswith("PPid:"):
                            ppid_of[int(name)] = int(line.split()[1])
                            break
            except (OSError, ValueError, IndexError):
                continue
        result = set()
        for child, parent in ppid_of.items():
            cur = parent
            depth = 0
            while cur and depth < 32:
                if cur == pid:
                    # PID identity prevents a stale snapshot targeting a reused PID.
                    try:
                        result.add((child, JobManager._start_time(child)))
                    except OSError:
                        pass
                    break
                cur = ppid_of.get(cur)
                depth += 1
        return result

    def _terminate(self, job_id, proc):
        """Stop this job's own tree: the direct child's process group plus every
        descendant we tracked while it ran (grandchildren may own their own
        sessions, e.g. SimRobot via start_new_session). Never touches pids that
        were not observed as descendants of this job."""
        descendants = self._descendants.get(job_id, set()) | self._descendants_of(proc.pid)
        targets = [(proc.pid, self._start_time(proc.pid))] + sorted(descendants)
        for sig, grace in ((signal.SIGTERM, 8), (signal.SIGKILL, 3)):
            for pid, birth in targets:
                try:
                    if self._start_time(pid) != birth:
                        continue
                except OSError:
                    continue
                try:
                    os.killpg(pid, sig)
                except (ProcessLookupError, PermissionError):
                    try:
                        os.kill(pid, sig)
                    except (ProcessLookupError, PermissionError):
                        pass
            try:
                proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                pass
            if sig == signal.SIGTERM:
                # A wrapper may exit first while a detached simulator is still alive.
                until = time.monotonic() + 2
                while time.monotonic() < until and any(self._alive(pid, birth) for pid, birth in targets):
                    time.sleep(0.05)
        proc.wait(timeout=5)

    @staticmethod
    def _start_time(pid):
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]

    @staticmethod
    def _alive(pid, birth):
        try:
            data = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            return data[19] == birth and data[0] != "Z"
        except OSError:
            return False

    def _pump(self, job_id, proc, log_path):
        tail = self._tails.setdefault(job_id, [])
        with open(log_path, "a", encoding="utf-8") as fh:
            for line in proc.stdout:
                fh.write(line)
                fh.flush()
                tail.append(line)
                if len(tail) > LOG_TAIL_KEEP:
                    del tail[: len(tail) - LOG_TAIL_KEEP]
                for sub in list(self._subscribers.get(job_id, [])):
                    try:
                        sub.put_nowait(line)
                    except queue.Full:
                        pass

    # ------------------------------------------------------------- collect
    def _collect(self, job_id, task_type):
        row = self.db.one("SELECT * FROM jobs WHERE job_id=?", (job_id,))
        row["params"] = json.loads(row["params_json"])
        spec = tasks_mod.TASKS.get(task_type)
        if not spec or not spec.get("collect"):
            return
        try:
            outcome = spec["collect"](row)
        except Exception as exc:
            self.db.log_event("collect_error", {"job_id": job_id, "error": repr(exc)})
            return
        verdict = outcome.get("quality_verdict") or "NOT_EVALUATED"
        result = outcome.get("result")
        if row["status"] in ("cancelled", "timed_out", "interrupted"):
            verdict = "INSUFFICIENT"
        elif row["status"] != "succeeded" and verdict == "PASS":
            verdict = "FAIL"
        # Never truncate JSON in the middle of a token: the result must stay readable.
        self.db.execute("UPDATE jobs SET quality_verdict=?, run_dir=?, result_json=? WHERE job_id=?",
                        (verdict, outcome.get("run_dir"),
                         json.dumps(result, ensure_ascii=False) if result else None,
                         job_id))
        own_dir = Path(row["log_path"]).parent
        outcome.setdefault("artifacts", []).extend(
            {"kind": "json", "path": str(p)} for p in [own_dir / "workbench-launch.json"] if p.is_file())
        for art in outcome.get("artifacts", []):
            p = Path(art["path"])
            try:
                size = p.stat().st_size
                digest = util.sha256_file(p) if size < 512 * 1024 * 1024 else None
            except OSError:
                size, digest = None, None
            self.db.execute(
                "INSERT INTO artifacts(job_id,kind,path,sha256,size,created_at) VALUES(?,?,?,?,?,?)",
                (job_id, art.get("kind", "file"), str(p), digest, size, util.now_local()))
        self.db.log_event("job_finished", {"job_id": job_id, "status": row["status"],
                                           "quality_verdict": verdict})

    # -------------------------------------------------------------- query
    def subscribe(self, job_id):
        q = queue.Queue(maxsize=500)
        self._subscribers.setdefault(job_id, []).append(q)
        return q

    def unsubscribe(self, job_id, q):
        subs = self._subscribers.get(job_id, [])
        if q in subs:
            subs.remove(q)

    def tail(self, job_id, n=200):
        return list(self._tails.get(job_id, []))[-n:]

    def running(self):
        return self._current

    def evidence_status(self, row):
        from . import identity
        if not row.get('log_path'):
            return 'UNVERIFIED'
        receipt = util.read_json(Path(row['log_path']).parent/'workbench-launch.json') or {}
        if not receipt.get('identity'):
            return 'UNVERIFIED'
        expected = receipt['identity']
        if row['type'] in ('arm_build', 'bhuman_build_desktop'):
            execution = util.read_json(Path(row['log_path']).parent/'job-execution.json') or {}
            after = execution.get('identity_at_end')
            if after:
                # Build outputs can change; its source inputs must remain unchanged.
                if any(expected.get(k) != after.get(k) for k in ('training_source','bhuman_source_tree','protected_files')):
                    return 'STALE'
                expected = after
        same = expected == identity.current()
        same = same and all(identity.file_identity(p) == sha for p,sha in receipt.get('input_files',{}).items())
        return 'VERIFIED' if same else 'STALE'
