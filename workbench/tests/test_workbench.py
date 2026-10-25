"""Workbench behavior tests: negative cases, security boundaries, state honesty.

Run: /usr/bin/python3 -B -m unittest discover -s tests -v   (from workbench/)
"""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection

WB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WB))

from backend import config, db as db_mod, jobs as jobs_mod, tasks as tasks_mod, util  # noqa: E402

ROOT = config.root()
WALK_PTH = str(config.rp("bhuman/k1-training/src/IsaacGymRL/pre-trained/WalkAndKick/K1_walk.pth"))
KICK_PTH = str(config.rp("bhuman/k1-training/src/IsaacGymRL/pre-trained/WalkAndKick/K1_kick_inner.pth"))
ITER71 = str(config.rp("bhuman/k1-training/runs/20261020_220631_608556_walk_reference_full_s7/nn/model_final.pth"))


class TestContractGuards(unittest.TestCase):
    def test_kick_model_rejected_in_mujoco_walk(self):
        with self.assertRaises(tasks_mod.ParamError):
            tasks_mod.build_job("mujoco_walk", {"seconds": 6, "checkpoint": KICK_PTH})

    def test_kick_model_rejected_in_walk_eval(self):
        with self.assertRaises(tasks_mod.ParamError):
            tasks_mod.build_job("train_walk_eval", {"policy": KICK_PTH})

    def test_unknown_task_type_rejected(self):
        with self.assertRaises(tasks_mod.ParamError):
            tasks_mod.build_job("arbitrary_shell", {})

    def test_path_outside_root_rejected(self):
        with self.assertRaises(tasks_mod.ParamError):
            tasks_mod.build_job("mujoco_walk", {"seconds": 6, "checkpoint": "/etc/hostname"})

    def test_full_resume_requires_checkpoint(self):
        with self.assertRaises(tasks_mod.ParamError):
            tasks_mod.build_job("train_walk_stability",
                                {"mode": "full", "envs": 4096, "iterations": 1, "seed": 7})

    def test_full_resume_rejects_public_actor(self):
        with self.assertRaises(tasks_mod.ParamError):
            tasks_mod.build_job("train_walk_stability",
                                {"mode": "full", "checkpoint": WALK_PTH})

    def test_full_resume_accepts_project_checkpoint(self):
        if not Path(ITER71).is_file():
            self.skipTest("iter71 checkpoint missing")
        job = tasks_mod.build_job("train_walk_stability",
                                  {"mode": "full", "checkpoint": ITER71,
                                   "envs": 4096, "iterations": 1, "seed": 7})
        self.assertIn("full", job["argv"])

    def test_export_requires_new_dir(self):
        existing = config.rp("bhuman/k1-training/exports/restored-public-walk-20261020")
        if existing.is_dir():
            with self.assertRaises(tasks_mod.ParamError):
                tasks_mod.build_job("train_export",
                                    {"task": "K1", "checkpoint": WALK_PTH,
                                     "output_dir": "restored-public-walk-20261020"})

    def test_export_rejects_path_separator(self):
        with self.assertRaises(tasks_mod.ParamError):
            tasks_mod.build_job("train_export",
                                {"task": "K1", "checkpoint": WALK_PTH,
                                 "output_dir": "../escape"})

    def test_seconds_bounds(self):
        with self.assertRaises(tasks_mod.ParamError):
            tasks_mod.build_job("bhuman_gait", {"seconds": 5})
        with self.assertRaises(tasks_mod.ParamError):
            tasks_mod.build_job("mujoco_walk", {"seconds": 9999})

    def test_headless_record_conflict_rejected(self):
        with self.assertRaises(tasks_mod.ParamError):
            tasks_mod.build_job("bhuman_match", {"seconds": 60, "record": True, "headless": True})


class TestPathSafety(unittest.TestCase):
    def test_traversal_rejected(self):
        with self.assertRaises(ValueError):
            util.safe_resolve("/home/peakpeng/Desktop/Robocup/../../etc/passwd", [ROOT])

    def test_sensitive_names_rejected(self):
        with self.assertRaises(ValueError):
            util.safe_resolve("/home/peakpeng/.local/share/robocup-archive/recovery-key.txt",
                              [Path("/home/peakpeng")])
        tmp = ROOT / "workbench" / "runs" / ".env"
        with self.assertRaises(ValueError):
            util.safe_resolve(str(tmp), [ROOT])

    def test_relative_rejected(self):
        with self.assertRaises(ValueError):
            util.safe_resolve("bhuman/README.md", [ROOT])

    def test_symlink_escape_rejected(self):
        link = ROOT / "workbench" / "runs" / "test-escape-link"
        try:
            if link.exists() or link.is_symlink():
                link.unlink()
            os.symlink("/etc", str(link))
            with self.assertRaises(ValueError):
                util.safe_resolve(str(link / "hostname"), [ROOT / "workbench" / "runs"])
        finally:
            if link.is_symlink():
                link.unlink()


class TestJobPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wb-test-"))
        self.db = db_mod.DB(self.tmp / "t.db")
        self.managers = []

    def manager(self):
        mgr = jobs_mod.JobManager(self.db, self.tmp / 'runs')
        self.managers.append(mgr)
        return mgr

    def tearDown(self):
        for manager in self.managers:
            manager.shutdown()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_running_marked_interrupted_on_boot(self):
        self.db.execute(
            "INSERT INTO jobs(job_id,type,params_json,status,created_at) VALUES(?,?,?,?,?)",
            ("job-x", "train_env_check", "{}", "running", util.now_local()))
        mgr = self.manager()
        row = self.db.one("SELECT status FROM jobs WHERE job_id='job-x'")
        self.assertEqual(row["status"], "interrupted")

    def test_cancel_queued(self):
        self.db.execute(
            "INSERT INTO jobs(job_id,type,params_json,status,created_at) VALUES(?,?,?,?,?)",
            ("job-y", "train_env_check", "{}", "queued", util.now_local()))
        mgr = self.manager()
        # job-y predates manager; it is interrupted on boot, so insert a fresh queued row
        self.db.execute(
            "INSERT INTO jobs(job_id,type,params_json,status,created_at) VALUES(?,?,?,?,?)",
            ("job-z", "train_env_check", "{}", "queued", util.now_local()))
        self.assertTrue(mgr.cancel("job-z"))
        row = self.db.one("SELECT status FROM jobs WHERE job_id='job-z'")
        self.assertEqual(row["status"], "cancelled")

    def test_cancel_running_reaps_setsid_grandchild(self):
        """A running job cancelled mid-flight must end as 'cancelled' and its
        grandchildren (even ones in their own session) must be reaped."""
        marker = self.tmp / "grandchild.pid"
        argv = ["bash", "-c",
                f"setsid bash -c 'echo $$ > {marker}; exec sleep 300' & exec sleep 300"]
        mgr = self.manager()
        self.db.execute(
            "INSERT INTO jobs(job_id,type,params_json,argv_json,cwd,status,created_at,"
            "timeout_s,log_path) VALUES(?,?,?,?,?,?,?,?,?)",
            ("job-run", "train_env_check", "{}", json.dumps(argv), str(self.tmp),
             "queued", util.now_local(), 600, str(self.tmp / "runs" / "job-run.log")))
        mgr._queue.put("job-run")
        # wait until running and grandchild exists
        grandchild = None
        for _ in range(100):
            row = self.db.one("SELECT status FROM jobs WHERE job_id='job-run'")
            if row["status"] == "running" and marker.is_file():
                grandchild = int(marker.read_text().strip())
                break
            time.sleep(0.1)
        self.assertIsNotNone(grandchild, "grandchild never appeared")
        self.assertTrue(mgr.cancel("job-run"))
        for _ in range(100):
            row = self.db.one("SELECT status FROM jobs WHERE job_id='job-run'")
            if row["status"] in ("cancelled", "failed", "succeeded"):
                break
            time.sleep(0.1)
        self.assertEqual(row["status"], "cancelled", f"got {row['status']}")
        # grandchild must be gone
        time.sleep(0.5)
        try:
            os.kill(grandchild, 0)
            alive = True
        except ProcessLookupError:
            alive = False
        self.assertFalse(alive, "setsid grandchild survived cancellation")

    def test_deadline_is_not_reported_as_success(self):
        mgr=self.manager()
        path=self.tmp/'runs'/'timeout-fixture'/'console.log';path.parent.mkdir()
        self.db.execute('INSERT INTO jobs(job_id,type,params_json,argv_json,cwd,status,created_at,timeout_s,log_path) VALUES(?,?,?,?,?,?,?,?,?)',
            ('timeout-fixture','train_env_check','{}',json.dumps(['/bin/sleep','30']),str(self.tmp),'queued',util.now_local(),1,str(path)))
        mgr._queue.put('timeout-fixture')
        for _ in range(80):
            row=self.db.one("SELECT * FROM jobs WHERE job_id='timeout-fixture'")
            if row['status'] in jobs_mod.STATUS_TERMINAL:break
            time.sleep(.1)
        self.assertEqual(row['status'],'timed_out')
        self.assertNotEqual(row['exit_code'],0)
        self.assertNotEqual(row['quality_verdict'],'PASS')


class TestServerSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from backend import server as server_mod
        from http.server import ThreadingHTTPServer
        cls.app = server_mod.App.__new__(server_mod.App)
        # minimal app wiring without touching real DB
        cls.tmp = Path(tempfile.mkdtemp(prefix="wb-srv-test-"))
        app = cls.app
        app.proj = config.project()
        app.db = db_mod.DB(cls.tmp / "t.db")
        app.jobs = jobs_mod.JobManager(app.db, cls.tmp / "runs")
        app.discovery = None
        app.token = "test-token-0123456789abcdef"
        app._cap_cache = {"at": 0, "data": {"capabilities": [], "status_label": {}}}
        import threading as _t
        app._cap_lock = _t.Lock()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_mod.make_handler(app))
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.app.jobs.shutdown()
        cls.app.db.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _req(self, method, path, token=None, host="127.0.0.1", origin=None, body=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Host": host}
        if token:
            headers["X-Workbench-Token"] = token
        if origin:
            headers["Origin"] = origin
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    def test_no_token_401(self):
        status, _ = self._req("GET", "/api/health")
        self.assertEqual(status, 401)

    def test_wrong_token_401(self):
        status, _ = self._req("GET", "/api/health", token="wrong")
        self.assertEqual(status, 401)

    def test_health_ok(self):
        status, data = self._req("GET", "/api/health", token=self.app.token)
        self.assertEqual(status, 200)
        self.assertIn(b'"ok": true', data)

    def test_bad_host_403(self):
        status, _ = self._req("GET", "/api/health", token=self.app.token, host="evil.example.com")
        self.assertEqual(status, 403)

    def test_cross_origin_post_403(self):
        status, _ = self._req("POST", "/api/jobs", token=self.app.token,
                              origin="http://evil.example.com", body="{}")
        self.assertEqual(status, 403)

    def test_arbitrary_task_rejected(self):
        status, data = self._req("POST", "/api/jobs", token=self.app.token,
                                 body=json.dumps({"type": "run_shell", "params": {"cmd": "rm -rf /"}}))
        self.assertEqual(status, 400)
        self.assertIn("未登记", data.decode())

    def test_raw_path_traversal_rejected(self):
        status, _ = self._req("GET", "/api/raw?path=/etc/passwd", token=self.app.token)
        self.assertEqual(status, 403)

    def test_unknown_artifact_404(self):
        status, _ = self._req("GET", "/api/artifacts/999999", token=self.app.token)
        self.assertEqual(status, 404)

    def test_json_array_rejected(self):
        status, _ = self._req('POST', '/api/jobs', token=self.app.token, body='[]')
        self.assertEqual(status, 400)

    def test_different_local_port_origin_rejected(self):
        status, _ = self._req('POST', '/api/jobs', token=self.app.token, origin='http://127.0.0.1:1', body='{}')
        self.assertEqual(status, 403)

    def test_sse_bytes_and_terminal_event(self):
        self.app.db.execute('INSERT OR REPLACE INTO jobs(job_id,type,params_json,status,created_at) VALUES(?,?,?,?,?)',
                            ('sse-fixture', 'train_env_check', '{}', 'succeeded', util.now_local()))
        self.app.jobs._tails['sse-fixture'] = ['中文日志\n']
        conn = HTTPConnection('127.0.0.1', self.port, timeout=5)
        conn.request('GET','/api/jobs/sse-fixture/events',headers={'X-Workbench-Token':self.app.token})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        lines = []
        for _ in range(6):
            lines.append(resp.readline().decode())
            if '"done": true' in lines[-1]:
                break
        self.assertIn('中文日志', ''.join(lines))
        self.assertIn('"done": true', ''.join(lines))
        conn.close()

    def test_artifact_range_streaming(self):
        path=WB/'runs'/'range-fixture.bin';path.write_bytes(b'0123456789')
        try:
            self.app.db.execute('INSERT INTO artifacts(kind,path,created_at) VALUES(?,?,?)',('bin',str(path),util.now_local()))
            art=self.app.db.one('SELECT id FROM artifacts WHERE path=?',(str(path),))['id']
            conn=HTTPConnection('127.0.0.1',self.port,timeout=5)
            conn.request('GET',f'/api/artifacts/{art}/download',headers={'X-Workbench-Token':self.app.token,'Range':'bytes=2-5'})
            response=conn.getresponse()
            self.assertEqual(response.status,206)
            self.assertEqual(response.getheader('Content-Range'),'bytes 2-5/10')
            self.assertEqual(response.read(),b'2345');conn.close()
        finally:path.unlink(missing_ok=True)


class TestResultOwnership(unittest.TestCase):
    def test_last_success_pointer_is_not_reused(self):
        tmp = Path(tempfile.mkdtemp(prefix='ownership-', dir=WB/'runs'))
        self.addCleanup(shutil.rmtree, tmp)
        run = tmp/'previous-run';run.mkdir()
        ptr = tmp/'last.json'; util.write_json(ptr, {'run_dir':str(run)})
        job = tmp/'job';job.mkdir()
        util.write_json(job/'launch.json',{'pointer_before':{str(ptr.resolve()):util.sha256_file(ptr)}})
        row={'started_at':util.now_local(),'log_path':str(job/'console.log')}
        self.assertEqual(tasks_mod._collect_pointer(ptr, row), {})
        time.sleep(.01)
        fresh=tmp/'fresh-run';fresh.mkdir()
        util.write_json(ptr, {'run_dir':str(fresh)})
        self.assertEqual(tasks_mod._collect_pointer(ptr,row)['run_dir'], str(fresh))

    def test_cancelled_job_cannot_receive_pass(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            tmp=Path(directory); database=db_mod.DB(tmp/'jobs.db')
            manager=jobs_mod.JobManager(database,tmp/'runs')
            try:
                database.execute('INSERT INTO jobs(job_id,type,params_json,status,created_at,log_path) VALUES(?,?,?,?,?,?)',
                    ('cancelled-fixture','fake','{}','cancelled',util.now_local(),str(tmp/'console.log')))
                with patch.dict(tasks_mod.TASKS, {'fake':{'collect':lambda row:{'quality_verdict':'PASS','result':{'status':'PASS'}}}}):
                    manager._collect('cancelled-fixture','fake')
                self.assertEqual(database.one('SELECT * FROM jobs')['quality_verdict'],'INSUFFICIENT')
            finally:
                manager.shutdown();database.close()

    def test_changed_file_identity_is_invalidated(self):
        from backend import identity
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'model.onnx';path.write_bytes(b'abcd')
            before=identity.file_identity(path);path.write_bytes(b'dcba')
            self.assertNotEqual(before,identity.file_identity(path))


if __name__ == "__main__":
    unittest.main()
