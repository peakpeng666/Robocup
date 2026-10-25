"""Local-only HTTP API for the workbench. Stdlib only.

Security model:
  - binds 127.0.0.1 only;
  - a per-boot session token is required for every API call (cookie set from
    the printed URL, or X-Workbench-Token header);
  - Host header must be 127.0.0.1/localhost (DNS-rebinding guard);
  - mutating endpoints additionally require a same-origin Origin/Referer;
  - no arbitrary shell: only whitelisted task types with validated params;
  - artifact access is by registered id with realpath containment checks.
"""
import hashlib
import hmac
import json
import mimetypes
import os
from pathlib import Path
import secrets
import threading
import time
import fcntl
import signal
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import config, db as db_mod, discovery as disc_mod, evidence as ev_mod
from . import graph as graph_mod, jobs as jobs_mod, models_registry, tasks as tasks_mod, util

FRONTEND = config.WB_DIR / "frontend"
RUN_STATE = config.WB_DIR / "run"
TOKEN_PATH = RUN_STATE / "session-token"


def load_or_create_token():
    RUN_STATE.mkdir(parents=True, exist_ok=True)
    if TOKEN_PATH.is_file():
        token = TOKEN_PATH.read_text().strip()
        if token:
            return token
    token = secrets.token_hex(32)
    fd = os.open(str(TOKEN_PATH), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(token + "\n")
    return token


class App:
    def __init__(self):
        self.proj = config.project()
        self.db = db_mod.DB(config.WB_DIR / "workbench.db")
        self.jobs = jobs_mod.JobManager(self.db, config.WB_DIR / "runs")
        self.discovery = disc_mod.Discovery()
        self.token = load_or_create_token()
        self._cap_cache = {"at": 0, "data": None}
        self._cap_lock = threading.Lock()

    def capabilities(self, refresh=False):
        with self._cap_lock:
            if refresh or self._cap_cache["data"] is None or time.time() - self._cap_cache["at"] > 3:
                self._cap_cache = {"at": time.time(), "data": self.discovery.passive()}
            return self._cap_cache["data"]

    def active_probe(self):
        data = self.discovery.active_probe()
        with self._cap_lock:
            self._cap_cache = {"at": time.time(), "data": data}
        self.db.log_event("active_probe", {"at": util.now_local()})
        return data

    def graph(self):
        caps = self.capabilities()
        ev = ev_mod.cached()
        graph = graph_mod.build_graph(caps, ev)
        from . import assessment
        matrix = assessment.matrix(self)['rows']
        l4 = matrix[4]
        for node in graph['nodes']:
            if node['id'] in ('build.booster_arm', 'artifact.bundle'):
                key = 'arm_job' if node['id'] == 'build.booster_arm' else 'bundle_job'
                job_id = l4['evidence'].get(key)
                if job_id:
                    job = self.db.one('SELECT result_json FROM jobs WHERE job_id=?',(job_id,))
                    result = json.loads(job['result_json'] or '{}')
                    node.update(status='VERIFIED',path=result.get('elf') or result.get('bundle'),last_pass=job_id,
                                note='离线静态核验；目标系统、固件和实机运行未验证')
        l2 = matrix[2]
        graph['nodes'].append({'id':'contract.walk','label':'生产 C++ 行走契约','kind':'artifact',
            'chain':'bhuman','status':l2['status'],'note':l2['gap'],'probe':l2['evidence']})
        graph['edges'].append({'from':'contract.walk','to':'src.bhuman_local','rel':'实际生产路径对照'})
        return graph


APP = None


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "RobocupWorkbench/1.0"
        protocol_version = "HTTP/1.1"

        # ---------------------------------------------------------- helpers
        def log_message(self, fmt, *args):
            pass  # quiet; server logs via events table

        def _host_ok(self):
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ("127.0.0.1", "localhost", "::1")

        def _token(self):
            header = self.headers.get("X-Workbench-Token")
            if header:
                return header
            raw = self.headers.get("Cookie")
            if raw:
                jar = cookies.SimpleCookie(raw)
                if "wb_token" in jar:
                    return jar["wb_token"].value
            qs = parse_qs(urlparse(self.path).query)
            return (qs.get("token") or [None])[0]

        def _authed(self):
            token = self._token()
            return token and hmac.compare_digest(token, app.token)

        def _same_origin(self):
            origin = self.headers.get("Origin") or self.headers.get("Referer")
            if not origin:
                return True  # curl/CLI; token still required
            parsed = urlparse(origin)
            return parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost") and parsed.port == self.server.server_port

        def _send(self, code, body=b"", ctype="application/json; charset=utf-8",
                  extra_headers=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra_headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _send_json(self, obj, code=200):
            self._send(code, obj)

        def _error(self, code, message):
            self._send_json({"error": message}, code)

        def _read_body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 <= length <= 1_000_000:
                raise ValueError("请求体过大")
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw.decode() or "{}")
            if not isinstance(body, dict):
                raise ValueError("请求体必须为对象")
            return body

        def _send_file(self, real, download=False):
            """Bounded streaming and HTTP ranges for video seeking and large artifacts."""
            size = real.stat().st_size
            start, end, code = 0, size - 1, 200
            byte_range = self.headers.get("Range")
            if byte_range:
                import re
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", byte_range)
                try:
                    if not match or not any(match.groups()):
                        raise ValueError()
                    a, b = match.groups()
                    start = int(a) if a else max(0, size - int(b))
                    end = min(int(b), size - 1) if a and b else size - 1
                    if start > end or start >= size:
                        raise ValueError()
                except ValueError:
                    return self._send(416, extra_headers={"Content-Range": f"bytes */{size}"})
                code = 206
            self.send_response(code)
            self.send_header("Content-Type", mimetypes.guess_type(str(real))[0] or "application/octet-stream")
            self.send_header("Content-Length", str(max(0, end - start + 1)))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            if download:
                self.send_header("Content-Disposition", 'attachment; filename="' + real.name.replace('"', '') + '"')
            self.end_headers()
            try:
                with real.open("rb") as stream:
                    stream.seek(start)
                    left = end - start + 1
                    while left > 0:
                        block = stream.read(min(256 * 1024, left))
                        if not block:
                            break
                        self.wfile.write(block)
                        left -= len(block)
            except (BrokenPipeError, ConnectionResetError):
                pass

        # ------------------------------------------------------------- GET
        def do_GET(self):
            if not self._host_ok():
                return self._error(403, "Host 不被允许")
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)
            if path == "/" or path == "/index.html":
                if not self._authed():
                    return self._send(401, self._login_page(), "text/html; charset=utf-8")
                headers = {"Set-Cookie": f"wb_token={app.token}; Path=/; SameSite=Strict; HttpOnly"}
                return self._send(200, (FRONTEND / "index.html").read_bytes(),
                                  "text/html; charset=utf-8", headers)
            if path.startswith("/static/"):
                if not self._authed():
                    return self._error(401, "未认证")
                return self._static(path[len("/static/"):])
            if not self._authed():
                return self._error(401, "未认证：请使用启动时打印的带 token 的 URL")
            routes = {
                "/api/health": lambda: {"ok": True, "now": util.now_local()},
                "/api/capabilities": lambda: app.capabilities(refresh=qs.get("refresh") == ["1"]),
                "/api/graph": lambda: app.graph(),
                "/api/models": lambda: models_registry.registry(),
                "/api/evidence": lambda: ev_mod.cached(),
                "/api/tasks": lambda: {"tasks": {k: {"label": v["label"], "chain": v["chain"],
                                                     "desc": v["desc"], "form": v["form"]}
                                                 for k, v in tasks_mod.TASKS.items()}},
                "/api/jobs": self._jobs_list,
                "/api/equivalence": lambda: __import__('backend.assessment', fromlist=['matrix']).matrix(app),
            }
            if path in routes:
                try:
                    return self._send_json(routes[path]())
                except Exception as exc:
                    return self._error(500, repr(exc))
            if path == "/api/raw":
                return self._raw(qs)
            if path.startswith("/api/jobs/"):
                return self._job_get(path, qs)
            if path.startswith("/api/artifacts/"):
                return self._artifact(path)
            return self._error(404, "未知端点")

        def _raw(self, qs):
            raw = (qs.get("path") or [""])[0]
            if not raw:
                return self._error(400, "缺少 path")
            allowed = [config.rp(rel) for rel in ev_mod.RUN_ROOTS.values()]
            allowed += [config.WB_DIR / "runs",
                        config.rp("bhuman/k1-training/exports"),
                        config.rp("bhuman/sim2sim")]
            try:
                real = util.safe_resolve(raw, allowed)
            except ValueError as exc:
                return self._error(403, str(exc))
            if not real.is_file():
                return self._error(404, "文件不存在")
            size = real.stat().st_size
            if size > 2 * 1024 * 1024 * 1024:
                return self._error(413, "文件过大")
            ctype = mimetypes.guess_type(str(real))[0] or "application/octet-stream"
            if real.suffix == ".mp4":
                ctype = "video/mp4"
            return self._send_file(real)

        def _login_page(self):
            return ("<html><head><meta charset='utf-8'><title>RoboCup 工作台</title></head>"
                    "<body style='font-family:sans-serif;margin:3em'>"
                    "<h2>需要会话令牌</h2><p>请使用启动脚本打印的带 token 的 URL 访问本工作台。"
                    "令牌保存在 <code>workbench/run/session-token</code>（仅本机用户可读）。</p>"
                    "</body></html>")

        def _static(self, rel):
            base = Path(os.path.realpath(str(FRONTEND)))
            target = Path(os.path.realpath(str(FRONTEND / rel)))
            try:
                target.relative_to(base)
            except ValueError:
                return self._error(403, "非法路径")
            if not target.is_file():
                return self._error(404, "不存在")
            ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            self._send(200, target.read_bytes(), ctype)

        def _jobs_list(self):
            rows = app.db.query("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 200")
            for row in rows:
                row['evidence_status'] = app.jobs.evidence_status(row)
                row.pop("result_json", None)
            return {"jobs": rows, "running": app.jobs.running()}

        def _job_get(self, path, qs):
            rest = path[len("/api/jobs/"):]
            job_id, _, sub = rest.partition("/")
            row = app.db.one("SELECT * FROM jobs WHERE job_id=?", (job_id,))
            if not row:
                return self._error(404, "任务不存在")
            if sub == "log":
                try:
                    offset = max(0, int(qs.get("offset", ["0"])[0]))
                except ValueError:
                    return self._error(400, "offset 必须为非负整数")
                log_path = row.get("log_path")
                data = ""
                size = 0
                if log_path and Path(log_path).is_file():
                    size = Path(log_path).stat().st_size
                    with open(log_path, "rb") as fh:
                        offset = min(offset, size)
                        fh.seek(offset)
                        raw = fh.read(256 * 1024)
                        data = raw.decode("utf-8", errors="replace")
                        offset += len(raw)
                return self._send_json({"offset": offset, "size": size,
                                        "data": data, "status": row["status"]})
            if sub == "events":
                return self._sse(job_id)
            row.pop("result_json", None)
            arts = app.db.query("SELECT * FROM artifacts WHERE job_id=?", (job_id,))
            detail = dict(row)
            detail['evidence_status'] = app.jobs.evidence_status(row)
            detail["artifacts"] = arts
            result = app.db.one("SELECT result_json FROM jobs WHERE job_id=?", (job_id,))
            if result and result.get("result_json"):
                try:
                    detail["result"] = json.loads(result["result_json"])
                except json.JSONDecodeError:
                    pass
            return self._send_json(detail)

        def _sse(self, job_id):
            row = app.db.one("SELECT status FROM jobs WHERE job_id=?", (job_id,))
            if not row:
                return self._error(404, "任务不存在")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q = app.jobs.subscribe(job_id)
            try:
                # replay recent in-memory tail first
                for line in app.jobs.tail(job_id, 500):
                    self.wfile.write(("data: " + json.dumps({"line": line}, ensure_ascii=False) + "\n\n").encode())
                self.wfile.flush()
                terminal = False
                while not terminal:
                    try:
                        line = q.get(timeout=1)
                        self.wfile.write(("data: " + json.dumps({"line": line}, ensure_ascii=False) + "\n\n").encode())
                    except Exception:
                        cur = app.db.one("SELECT status FROM jobs WHERE job_id=?", (job_id,))
                        status = cur["status"] if cur else "unknown"
                        self.wfile.write((": heartbeat " + status + "\n\n").encode())
                        if status in jobs_mod.STATUS_TERMINAL:
                            terminal = True
                            self.wfile.write(("data: " + json.dumps({"done": True, "status": status}) + "\n\n").encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                app.jobs.unsubscribe(job_id, q)

        def _artifact(self, path):
            rest = path[len("/api/artifacts/"):]
            art_id, _, action = rest.partition("/")
            if not art_id.isdigit():
                return self._error(400, "非法产物 ID")
            row = app.db.one("SELECT * FROM artifacts WHERE id=?", (int(art_id),))
            if not row:
                return self._error(404, "产物未登记")
            allowed = [config.root(), config.WB_DIR / "runs"]
            try:
                real = util.safe_resolve(row["path"], allowed)
            except ValueError as exc:
                return self._error(403, str(exc))
            if not real.is_file():
                return self._error(404, "文件不存在")
            if action == "download":
                ctype = mimetypes.guess_type(str(real))[0] or "application/octet-stream"
                headers = {"Content-Disposition": f"attachment; filename=\"{real.name}\""}
                return self._send_file(real, download=True)
            info = dict(row)
            info["resolved"] = str(real)
            if real.stat().st_size < 2 * 1024 * 1024 and real.suffix in (".json", ".log", ".txt", ".md", ".yaml"):
                info["preview"] = real.read_text(errors="replace")[:200000]
            return self._send_json(info)

        # ------------------------------------------------------------ POST
        def do_POST(self):
            if not self._host_ok():
                return self._error(403, "Host 不被允许")
            if not self._authed():
                return self._error(401, "未认证")
            if not self._same_origin():
                return self._error(403, "拒绝跨站请求")
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                body = self._read_body()
            except (ValueError, json.JSONDecodeError) as exc:
                return self._error(400, f"请求体无效: {exc}")
            if path == "/api/jobs/preview":
                try:
                    return self._send_json(tasks_mod.preview(body.get("type"), body.get("params") or {}))
                except tasks_mod.ParamError as exc:
                    return self._error(400, str(exc))
            if path == "/api/jobs":
                try:
                    job_id = app.jobs.submit(body.get("type"), body.get("params") or {})
                    return self._send_json({"job_id": job_id})
                except tasks_mod.ParamError as exc:
                    return self._error(400, str(exc))
            if path == "/api/capabilities/probe":
                return self._send_json(app.active_probe())
            if path == "/api/evidence/refresh":
                return self._send_json(ev_mod.refresh())
            if path.startswith("/api/jobs/") and path.endswith("/cancel"):
                job_id = path[len("/api/jobs/"):-len("/cancel")]
                try:
                    ok = app.jobs.cancel(job_id)
                    return self._send_json({"ok": ok})
                except KeyError:
                    return self._error(404, "任务不存在")
            return self._error(404, "未知端点")

    return Handler


def main():
    global APP
    RUN_STATE.mkdir(parents=True, exist_ok=True)
    lock = (RUN_STATE / "server.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("工作台已经运行；拒绝第二个实例，保留当前任务")
    if config.project()["host"] != "127.0.0.1":
        raise SystemExit("工作台仅允许绑定 127.0.0.1")
    APP = App()
    app = APP
    host, port = app.proj["host"], int(app.proj["port"])
    try:
        server = ThreadingHTTPServer((host, port), make_handler(app))
    except OSError:
        app.jobs.shutdown()
        raise
    server.daemon_threads = True
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    url = f"http://{host}:{port}/?token={app.token}"
    print("=" * 70)
    print("RoboCup 工作台已启动（仅本机回环）")
    print("URL: " + url)
    print("停止: Ctrl+C")
    print("=" * 70, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.jobs.shutdown()
        server.server_close()
        lock.close()


if __name__ == "__main__":
    main()
