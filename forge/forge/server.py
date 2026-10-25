"""K1 Forge local control plane (FastAPI). Loopback only; session token; no free-form commands."""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import secrets
import shutil
import subprocess
import time
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse

from . import __version__, arena as arena_mod, builds, contracts, jobs as jobs_mod, packs, paths, util

WEB_DIST = paths.FORGE / "web/dist"
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


def _token() -> str:
    paths.STATE.mkdir(parents=True, exist_ok=True)
    token_file = paths.STATE / "session-token"
    if token_file.is_file() and token_file.read_text().strip():
        return token_file.read_text().strip()
    token = secrets.token_urlsafe(32)
    descriptor = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(token + "\n")
    return token


class Cache:
    def __init__(self):
        self.values = {}

    def get(self, key, ttl, compute):
        hit = self.values.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        value = compute()
        self.values[key] = (time.time(), value)
        return value


def create_app(start_jobs: bool = True) -> FastAPI:
    token = _token()
    manager = jobs_mod.JobManager(db_path=paths.DB_PATH, autostart=start_jobs)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        manager.shutdown()

    app = FastAPI(title="K1 Forge", version=__version__, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    cache = Cache()
    app.state.manager = manager
    app.state.token = token
    main_arena = arena_mod.Arena("main")

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in ALLOWED_HOSTS:
            return JSONResponse({"error": "Host 不被允许"}, status_code=403)
        path = request.url.path
        supplied = request.headers.get("x-forge-token") or request.cookies.get("forge_token") or request.query_params.get("token")
        authed = bool(supplied) and hmac.compare_digest(supplied, token)
        if path.startswith("/api/"):
            if not authed:
                return JSONResponse({"error": "未认证：使用启动时打印的带 token 的地址"}, status_code=401)
            if request.method not in ("GET", "HEAD"):
                origin = request.headers.get("origin") or request.headers.get("referer") or ""
                if origin and not any(origin.startswith(f"http://{h}:") for h in ALLOWED_HOSTS):
                    return JSONResponse({"error": "拒绝跨站请求"}, status_code=403)
        elif not authed:
            return HTMLResponse("<meta charset=utf-8><h3>K1 Forge 需要会话令牌</h3><p>请使用启动脚本打印的地址"
                                "（令牌在 forge/run/session-token，仅本机用户可读）。</p>", status_code=401)
        response = await call_next(request)
        if authed and request.query_params.get("token"):
            response.set_cookie("forge_token", token, httponly=True, samesite="strict")
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    # ------------------------------------------------------------------ helpers
    def gpu():
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu,driver_version",
                                  "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5).stdout.strip()
            name, used, total, utilization, temperature, driver = [x.strip() for x in out.split(",")]
            return {"name": name, "memory_used_mib": int(used), "memory_total_mib": int(total),
                    "utilization": int(utilization), "temperature_c": int(temperature), "driver": driver}
        except Exception as exc:  # noqa: BLE001
            return {"error": repr(exc)}

    def system():
        import psutil

        disk = shutil.disk_usage(paths.ROOT)
        return {"gpu": gpu(), "cpu_percent": psutil.cpu_percent(interval=None), "cpu_count": psutil.cpu_count(),
                "load": os.getloadavg(), "memory": dict(psutil.virtual_memory()._asdict()),
                "disk_free_gib": round(disk.free / 2**30, 1), "display": os.environ.get("DISPLAY"),
                "simlock_held": _simlock_held()}

    def _simlock_held():
        import fcntl

        try:
            with paths.BH_SIM_LOCK.open("a") as stream:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(stream, fcntl.LOCK_UN)
            return False
        except BlockingIOError:
            return True

    def foundation():
        from . import match

        try:
            protected = match.foundation_contract()
            protected_ok, error = True, None
        except Exception as exc:  # noqa: BLE001
            protected, protected_ok, error = {}, False, str(exc)
        interpreters = {k: {"path": str(v), "exists": v.exists()} for k, v in paths.INTERPRETERS.items()}
        return {"official": paths.OFFICIAL_UPSTREAM, "protected_files": len(protected), "protected_ok": protected_ok,
                "error": error, "simrobot_release": str(paths.SIMROBOT_RELEASE),
                "simrobot_sha256": util.sha256_file(paths.SIMROBOT_RELEASE),
                "controller_sha256": util.sha256_file(paths.SIMROBOT_RELEASE.parent / "libSimulatedRobot.so"),
                "training_fingerprint_expected": paths.TRAINING_SOURCE_FINGERPRINT,
                "interpreters": interpreters,
                "official_walk_sha256": util.sha256_file(paths.BH_OFFICIAL / contracts.CONTRACTS["walk"].official_file)}

    def match_summary(result_path: Path) -> dict:
        data = util.read_json(result_path) or {}
        launch = util.read_json(result_path.parent / "launch.json") or {}
        return {"id": result_path.parent.name, "status": data.get("status"), "score": data.get("score"),
                "teams": data.get("teams"), "tag": data.get("tag"), "video": bool(data.get("video")),
                "seconds": launch.get("seconds"), "vision": (launch.get("runtime") or {}).get("vision"),
                "performance": data.get("performance"), "failed_checks": [k for k, v in (data.get("checks") or {}).items() if not v],
                "assignment": launch.get("teams"), "readback_ok": (data.get("network_readback") or {}).get("ok")}

    def list_matches():
        rows = [match_summary(p) for p in sorted((paths.RUNS / "matches").glob("*/result.json"), reverse=True)]
        return rows

    def train_runs():
        out = []
        for base, origin in ((paths.RUNS / "train", "forge"), (paths.TRAINING / "runs", "mainline")):
            for run in sorted(base.glob("*/"), reverse=True):
                launch = util.read_json(run / "launch.json")
                if launch is None:
                    continue
                execution = util.read_json(run / "execution.json") or {}
                if not execution:
                    log = run / "console.log"
                    recent = log.is_file() and time.time() - log.stat().st_mtime < 120
                    execution = {"status": "running" if recent else "INCOMPLETE"}
                metrics_path = run / "metrics.jsonl"
                iterations = sum(1 for _ in metrics_path.open()) if metrics_path.is_file() else 0
                checkpoints = sorted((p.name for p in (run / "nn").glob("*.pth")), key=lambda n: (len(n), n)) if (run / "nn").is_dir() else []
                out.append({"id": run.name, "origin": origin, "path": str(run), "preset": launch.get("preset"),
                            "label": launch.get("label"), "status": execution.get("status"),
                            "wall_s": execution.get("wall_s"), "iterations": iterations, "checkpoints": checkpoints,
                            "envs": launch.get("envs"), "seed": launch.get("seed")})
        return out

    def find_train_run(run_id: str) -> Path:
        for base in (paths.RUNS / "train", paths.TRAINING / "runs"):
            candidate = base / run_id
            if candidate.is_dir() and candidate.resolve().parent == base.resolve():
                return candidate
        raise HTTPException(404, "训练运行不存在")

    def match_dir(match_id: str) -> Path:
        directory = (paths.RUNS / "matches" / match_id)
        if not directory.is_dir() or directory.resolve().parent != (paths.RUNS / "matches").resolve():
            raise HTTPException(404, "比赛不存在")
        return directory

    # ------------------------------------------------------------------ routes
    @app.get("/api/overview")
    def overview():
        state = main_arena.state()
        return {
            "version": __version__, "now": util.now_iso(),
            "foundation": cache.get("foundation", 60, foundation),
            "arena": {"state": state, "freshness": cache.get("fresh", 10, main_arena.freshness) if state else None,
                      "flashed": main_arena.flashed()},
            "packs": len(packs.list_packs()), "matches": list_matches()[:5], "train": train_runs()[:6],
            "variants": [{"name": v["name"], "builds": {k: b.get("status") for k, b in v["builds"].items()}}
                         for v in builds.list_variants()],
            "jobs": manager.list(20), "system": cache.get("system", 2, system),
        }

    @app.get("/api/system")
    def get_system():
        return cache.get("system", 2, system)

    @app.get("/api/contracts")
    def get_contracts():
        return {slot: {"id": c.id, "label": c.label, "inputs": c.inputs, "outputs": c.outputs, "consumer": c.consumer,
                       "cfg_file": c.cfg_file, "cfg_key": c.cfg_key, "layout": c.layout, "official_file": c.official_file,
                       "flashable": slot in contracts.PACK_SLOTS,
                       "required_module": {**contracts.ADAPTER_SLOTS, **contracts.AUXILIARY_SLOTS}.get(slot, {}).get("module")}
                for slot, c in contracts.CONTRACTS.items()}

    @app.get("/api/packs")
    def get_packs():
        return packs.list_packs()

    @app.get("/api/packs/{pack_id}")
    def get_pack(pack_id: str):
        try:
            return packs.load(pack_id)
        except packs.PackError as exc:
            raise HTTPException(404, str(exc))

    @app.post("/api/packs/{pack_id}/verify")
    def verify_pack(pack_id: str):
        try:
            return packs.verify(pack_id)
        except packs.PackError as exc:
            raise HTTPException(404, str(exc))

    def arena_named(name: str) -> arena_mod.Arena:
        if name == "main":
            return main_arena
        if not (paths.ARENAS / util.safe_name(name) / "arena.json").is_file():
            raise HTTPException(404, "arena 不存在")
        return arena_mod.Arena(name)

    @app.get("/api/arenas")
    def get_arenas():
        out = []
        for path in sorted(paths.ARENAS.glob("*/arena.json")):
            state = util.read_json(path) or {}
            out.append({"name": path.parent.name, "source": state.get("source", str(paths.BH_LOCAL)),
                        "variant": state.get("variant"), "binary_identical_to_validated_release":
                        state.get("binary_identical_to_validated_release", True)})
        return out

    @app.get("/api/arena")
    def get_arena(name: str = "main"):
        a = arena_named(name)
        return {"name": a.name, "state": a.state(), "freshness": a.freshness() if a.state() else None, "flashed": a.flashed()}

    @app.get("/api/arena/verify")
    def arena_verify(name: str = "main"):
        a = arena_named(name)
        if not a.state():
            raise HTTPException(409, "arena 尚未建立")
        return cache.get(f"verify:{a.name}", 3, a.verify)

    @app.post("/api/arena/init")
    def arena_init(body: dict | None = None):
        body = body or {}
        try:
            with manager.reserve({"simlock", "arena"}):
                a = arena_named(str(body.get("arena") or "main"))
                state = a.materialize(refresh=bool(body.get("refresh")))
                cache.values.pop(f"verify:{a.name}", None)
                cache.values.pop("fresh", None)
                return state
        except (jobs_mod.JobError, arena_mod.ArenaError) as exc:
            raise HTTPException(409, str(exc))

    @app.post("/api/flash")
    def flash(body: dict):
        try:
            team = int(body.get("team"))
            if team not in arena_mod.TEAM_NUMBERS:
                raise ValueError("队伍号无效")
            with manager.reserve({"simlock", "arena"}):
                a = arena_named(str(body.get("arena") or "main"))
                if not a.state():
                    a.materialize()
                receipt = a.flash(team, str(body.get("pack_id")))
                cache.values.pop(f"verify:{a.name}", None)
                return {"receipt": receipt, "readback": a.verify()}
        except jobs_mod.JobError as exc:
            raise HTTPException(409, str(exc))
        except (ValueError, packs.PackError, arena_mod.ArenaError, contracts.ContractError) as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/matches")
    def get_matches():
        return list_matches()

    @app.get("/api/matches/{match_id}")
    def get_match(match_id: str):
        directory = match_dir(match_id)
        result = util.read_json(directory / "result.json")
        if result is None:
            raise HTTPException(404, "比赛尚无结果")
        result["launch"] = util.read_json(directory / "launch.json")
        result["id"] = match_id
        return result

    @app.get("/api/matches/{match_id}/video")
    def get_video(match_id: str, request: Request):
        video = match_dir(match_id) / "match.mp4"
        if not video.is_file():
            raise HTTPException(404, "没有录像")
        return _ranged_file(video, request, "video/mp4")

    @app.get("/api/series")
    def get_series():
        return [dict(util.read_json(p) or {}, id=p.parent.name) for p in sorted((paths.RUNS / "series").glob("*/series.json"), reverse=True)]

    @app.get("/api/strategies")
    def get_strategies():
        from . import strategies

        return {"profiles": strategies.list_profiles(), "presets": strategies.PRESETS, "parameters": strategies.PARAMETERS}

    @app.post("/api/strategies")
    def create_strategy(body: dict):
        from . import strategies

        try:
            if body.get("preset"):
                preset = strategies.PRESETS[str(body["preset"])]
                return strategies.create(str(body.get("name") or body["preset"]), preset["cfg_patches"], preset["description"])
            return strategies.create(str(body.get("name") or "strategy"), body.get("cfg_patches"), str(body.get("description") or ""))
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/validations/preview")
    def validation_preview(body: dict):
        from . import validation

        try:
            return validation.plan(**body)
        except (ValueError, TypeError, packs.PackError, contracts.ContractError, arena_mod.ArenaError) as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/validations")
    def get_validations():
        from . import validation

        return validation.list_runs()

    @app.get("/api/validations/{run_id}")
    def get_validation(run_id: str):
        from . import validation

        try:
            return validation.load_run(run_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc))

    @app.get("/api/validations/{run_id}/cases/{case_id}/{artifact}")
    def validation_artifact(run_id: str, case_id: str, artifact: str, request: Request):
        from . import validation

        filenames = {"video": ("match.mp4", "video/mp4"), "result": ("result.json", "application/json"),
                     "console": ("console.log", "text/plain"), "launch": ("launch.json", "application/json")}
        try:
            filename, media_type = filenames[artifact]
            file = validation.case_directory(run_id, case_id) / filename
            if not file.is_file():
                raise ValueError("此场景没有该产物")
        except (ValueError, KeyError) as exc:
            raise HTTPException(404, str(exc))
        return _ranged_file(file, request, media_type) if artifact == "video" else FileResponse(file, media_type=media_type)

    @app.get("/api/train/presets")
    def get_presets():
        from .training import PRESETS

        return {k: {"label": v["label"], "config_patch": v["config_patch"], "recipe": v["recipe"]} for k, v in PRESETS.items()}

    @app.get("/api/train/runs")
    def get_train_runs():
        return train_runs()

    @app.get("/api/train/runs/{run_id}")
    def get_train_run(run_id: str):
        run = find_train_run(run_id)
        metrics = []
        if (run / "metrics.jsonl").is_file():
            for line in (run / "metrics.jsonl").read_text().splitlines():
                try:
                    metrics.append(json.loads(line))
                except ValueError:
                    continue
        return {"id": run_id, "path": str(run), "launch": util.read_json(run / "launch.json"),
                "execution": util.read_json(run / "execution.json"), "recipe": util.read_json(run / "forge-recipe.json"),
                "metrics": metrics,
                "checkpoints": [{"name": p.name, "path": str(p), "size": p.stat().st_size}
                                for p in sorted((run / "nn").glob("*.pth"), key=lambda p: p.stat().st_mtime)] if (run / "nn").is_dir() else []}

    @app.get("/api/variants")
    def get_variants():
        return builds.list_variants()

    @app.post("/api/variants")
    def post_variant(body: dict):
        try:
            return builds.create_variant(str(body.get("name", "")), [], str(body.get("description", "")))
        except builds.BuildError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/jobs")
    def get_jobs():
        return {"jobs": manager.list(200), "types": {k: v["label"] for k, v in jobs_mod.JOB_TYPES.items()},
                "external_busy": sorted(manager.external())}

    @app.post("/api/jobs/preview")
    def preview_job(body: dict):
        try:
            return manager.preview(str(body.get("type")), body.get("params") or {})
        except jobs_mod.JobError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/jobs")
    def submit_job(body: dict):
        try:
            return {"id": manager.submit(str(body.get("type")), body.get("params") or {})}
        except jobs_mod.JobError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        job = manager.get(job_id)
        if not job:
            raise HTTPException(404, "作业不存在")
        return job

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        try:
            return {"ok": manager.cancel(job_id)}
        except KeyError:
            raise HTTPException(404, "作业不存在")

    @app.get("/api/jobs/{job_id}/log")
    def job_log(job_id: str, offset: int = 0):
        job = manager.get(job_id)
        if not job:
            raise HTTPException(404, "作业不存在")
        path = Path(job["log_path"])
        if not path.is_file():
            return {"offset": 0, "data": "", "status": job["status"]}
        size = path.stat().st_size
        offset = max(0, min(offset, size))
        if offset == 0 and size > 512 * 1024:
            offset = size - 512 * 1024
        with path.open("rb") as stream:
            stream.seek(offset)
            data = stream.read(512 * 1024)
        return {"offset": offset + len(data), "size": size, "data": data.decode("utf-8", "replace"), "status": job["status"]}

    @app.get("/api/jobs/{job_id}/stream")
    async def job_stream(job_id: str):
        job = manager.get(job_id)
        if not job:
            raise HTTPException(404, "作业不存在")
        path = Path(job["log_path"])

        async def events():
            offset = max(0, path.stat().st_size - 64 * 1024) if path.is_file() else 0
            while True:
                current = manager.get(job_id)
                if path.is_file():
                    with path.open("rb") as stream:
                        stream.seek(offset)
                        chunk = stream.read(256 * 1024)
                    if chunk:
                        offset += len(chunk)
                        yield "data: " + json.dumps({"text": chunk.decode("utf-8", "replace")}, ensure_ascii=False) + "\n\n"
                if current and current["status"] in jobs_mod.TERMINAL:
                    yield "data: " + json.dumps({"done": True, "status": current["status"]}) + "\n\n"
                    return
                yield ": keepalive\n\n"
                await asyncio.sleep(1.0)

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.get("/api/evals")
    def get_evals():
        stress = []
        for path in sorted((paths.RUNS / "mjwarp").glob("*/result.json"), reverse=True):
            data = util.read_json(path) or {}
            stress.append({"id": path.parent.name, "policy": data.get("policy"), "policy_sha256": data.get("policy_sha256"),
                           "setup": data.get("setup"), "metrics": data.get("metrics"), "performance": data.get("performance"),
                           "engine": data.get("engine")})
        isaac = []
        for path in sorted((paths.RUNS / "eval").glob("*/execution.json"), reverse=True):
            data = util.read_json(path) or {}
            results = data.get("results") or {}
            isaac.append({"id": path.parent.name, "status": data.get("status"), "run_dir": data.get("run_dir"),
                          "policy": results.get("policy"), "policy_sha256": results.get("policy_sha256"), "seed": results.get("seed"),
                          "resets": (results.get("termination_events_total") or {}).get("non_timeout_reset"),
                          "segments": {k: v.get("tracking_rmse_settled_vx_vy_wz") for k, v in (results.get("segments") or {}).items()}})
        return {"stress": stress, "isaac": isaac}

    @app.get("/api/dossiers")
    def get_dossiers():
        from . import dossier

        return dossier.overview()

    @app.get("/api/dossiers/{pack_id}")
    def get_dossier(pack_id: str):
        from . import dossier

        try:
            return dossier.dossier(pack_id)
        except packs.PackError as exc:
            raise HTTPException(404, str(exc))

    @app.get("/api/duels")
    def get_duels():
        from . import duel

        return duel.list_duels()

    @app.get("/api/duels/{duel_id}")
    def get_duel(duel_id: str):
        from . import duel

        try:
            return duel.load(duel_id)
        except duel.DuelError as exc:
            raise HTTPException(404, str(exc))

    @app.get("/api/atlas")
    def get_atlas_runs():
        from . import atlas

        return atlas.list_runs()

    @app.get("/api/atlas/{run_id}")
    def get_atlas_run(run_id: str):
        from . import atlas

        try:
            return atlas.load(run_id)
        except atlas.AtlasError as exc:
            raise HTTPException(404, str(exc))

    @app.get("/api/bridge/contract")
    def get_bridge_contract():
        from .bridge import contract

        return cache.get("bridge-contract", 60, contract.audit)

    @app.get("/api/bridge/runs")
    def get_bridge_runs():
        from .bridge import analysis

        return analysis.list_runs()

    @app.get("/api/bridge/runs/{run_id}")
    def get_bridge_run(run_id: str):
        from .bridge import analysis

        try:
            return analysis.load(run_id)
        except analysis.BridgeError as exc:
            raise HTTPException(404, str(exc))

    @app.get("/api/bridge/runs/{run_id}/paths")
    def get_bridge_paths(run_id: str):
        from .bridge import analysis

        if "/" in run_id or run_id.startswith(".") or not (analysis.RUNS / run_id).is_dir():
            raise HTTPException(404, "桥接运行不存在")
        return analysis.identity_paths(run_id)

    @app.get("/api/bridge/lessons")
    def get_bridge_lessons():
        from .bridge import analysis, contract, lessons

        latest = next((r for r in analysis.list_runs() if r.get("analyzed")), None)
        run = None
        if latest:
            try:
                run = analysis.load(latest["id"])
            except analysis.BridgeError:
                run = None
        return lessons.load(run, cache.get("bridge-contract", 60, contract.audit))

    @app.get("/api/docs/bridge")
    def bridge_doc():
        path = paths.FORGE / "docs/MOTION_BRIDGE.md"
        return {"markdown": path.read_text(encoding="utf-8") if path.is_file() else ""}

    @app.get("/api/bundles")
    def get_bundles():
        return [dict(util.read_json(p) or {}, id=p.parent.name) for p in sorted((paths.RUNS / "bundles").glob("*/bundle.json"), reverse=True)]

    @app.get("/api/gates")
    def get_gates():
        return [dict(util.read_json(p) or {}, id=p.stem) for p in sorted((paths.RUNS / "gates").glob("*.json"), reverse=True)]

    @app.get("/api/docs/design")
    def design_doc():
        return {"markdown": (paths.FORGE / "docs/DESIGN.md").read_text(encoding="utf-8")}

    # ------------------------------------------------------------------ static
    @app.get("/{rest:path}")
    def spa(rest: str):
        if rest.startswith("api/"):
            raise HTTPException(404, "未知端点")
        target = (WEB_DIST / rest).resolve() if rest else WEB_DIST / "index.html"
        if rest and str(target).startswith(str(WEB_DIST.resolve()) + os.sep) and target.is_file():
            return FileResponse(target)
        index = WEB_DIST / "index.html"
        if not index.is_file():
            return HTMLResponse("<meta charset=utf-8><p>前端尚未构建：cd forge/web && npm run build</p>")
        return FileResponse(index)

    return app


def _ranged_file(path: Path, request: Request, media_type: str) -> Response:
    size = path.stat().st_size
    header = request.headers.get("range")
    if not header or not header.startswith("bytes="):
        return FileResponse(path, media_type=media_type, headers={"Accept-Ranges": "bytes"})
    start_text, _, end_text = header[6:].partition("-")
    try:
        start = int(start_text) if start_text else max(0, size - int(end_text))
        end = min(int(end_text), size - 1) if start_text and end_text else size - 1
        if start > end or start >= size:
            raise ValueError
    except ValueError:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    with path.open("rb") as stream:
        stream.seek(start)
        data = stream.read(end - start + 1)
    return Response(data, status_code=206, media_type=media_type,
                    headers={"Content-Range": f"bytes {start}-{end}/{size}", "Accept-Ranges": "bytes"})


def main():
    import fcntl
    import uvicorn

    paths.STATE.mkdir(parents=True, exist_ok=True)
    lock = (paths.STATE / "server.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("K1 Forge 服务已在运行；拒绝第二个实例")
    port = int(os.environ.get("FORGE_PORT", "8920"))
    app = create_app()
    print("=" * 72)
    print("K1 Forge 运控工坊（仅本机回环）")
    print(f"地址: http://127.0.0.1:{port}/?token={app.state.token}")
    print("停止: Ctrl+C（运行中的作业会被终止并标记 interrupted）")
    print("=" * 72, flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
