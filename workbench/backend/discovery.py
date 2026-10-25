"""Capability discovery: passive metadata at startup, active probes on demand.

Status levels (never collapsed into a single green "ready"):
  NOT_FOUND  未找到      PRESENT   存在（未验证内容）
  INSTALLED  已安装(版本已读)  VERIFIED  已验证（当前身份下有通过证据）
  STALE      失效（身份已变，历史通过）  UNVERIFIED 未验证（存在但无运行证据）
  BLOCKED    受阻（明确缺项）
"""
import json
import os
from pathlib import Path
import subprocess
import shutil

from . import config, util, identity

STATUS_LABEL = {
    "NOT_FOUND": "未找到", "PRESENT": "存在", "INSTALLED": "已安装",
    "VERIFIED": "已验证", "STALE": "历史通过·当前待重验", "UNVERIFIED": "未验证",
    "BLOCKED": "受阻",
}

PROBE_TIMEOUT = 25


def _exists(path):
    return Path(path).exists()


def _probe_python(python, packages):
    """Read interpreter version and package metadata versions (no heavy import)."""
    code = ("import importlib.metadata as m, json, sys; "
            "print(json.dumps({'python': sys.executable, 'version': sys.version.split()[0], "
            "'packages': {p: (m.version(p) if __import__('importlib').import_module('importlib.metadata') else None) "
            "for p in []}}))")
    # simpler: two-step to keep the one-liner robust on 3.8
    code = ("import importlib.metadata as m, json, sys\n"
            "pkgs = {}\n"
            "for p in " + repr(list(packages)) + ":\n"
            "    try: pkgs[p] = m.version(p)\n"
            "    except Exception: pkgs[p] = None\n"
            "print(json.dumps({'python': sys.executable, 'version': sys.version.split()[0], 'packages': pkgs}))")
    try:
        out = subprocess.run([python, "-I", "-B", "-c", code], capture_output=True, text=True,
                             timeout=PROBE_TIMEOUT)
        if out.returncode != 0:
            return {"ok": False, "error": out.stderr.strip()[-400:]}
        data = json.loads(out.stdout.strip().splitlines()[-1])
        data["ok"] = True
        return data
    except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": repr(exc)}


def _probe_tool(argv):
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=PROBE_TIMEOUT)
        line = (out.stdout or out.stderr).strip().splitlines()
        return {"ok": out.returncode == 0, "version": line[0] if line else ""}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": repr(exc)}


def _gpu():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu,driver_version",
                              "--format=csv,noheader"], capture_output=True, text=True, timeout=10)
        if out.returncode != 0:
            return {"ok": False, "error": out.stderr.strip()[:300]}
        name, used, total, util_, driver = [x.strip() for x in out.stdout.strip().split(",")][:5]
        return {"ok": True, "name": name, "memory_used": used, "memory_total": total,
                "utilization": util_, "driver": driver}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": repr(exc)}


class Discovery:
    def __init__(self):
        self.proj = config.project()
        self.root = config.root()
        self.cache_path = config.WB_DIR / "runs" / "discovery-cache.json"
        self.cache = util.read_json(self.cache_path) or {}

    # ------------------------------------------------------------ passive
    def passive(self) -> dict:
        P = self.proj
        caps = []
        for chain_id, chain in P["chains"].items():
            entry_rel = chain.get("entry") or chain.get("env_script")
            entry = config.rp(entry_rel) if entry_rel else None
            caps.append({
                "id": f"chain.{chain_id}.entry", "chain": chain_id,
                "label": f"{chain['label']}入口",
                "path": str(entry) if entry else None,
                "status": "PRESENT" if entry and entry.is_file() else "NOT_FOUND",
                "note": "入口脚本存在性；运行通过见证据索引",
            })
            if "binary_release" in chain:
                binary = config.rp(chain["binary_release"])
                caps.append({
                    "id": f"chain.{chain_id}.binary_release", "chain": chain_id,
                    "label": "SimRobot Release 可执行文件", "path": str(binary),
                    "status": "PRESENT" if binary.is_file() else "NOT_FOUND",
                    "note": "存在≠当前源码已重新编译；见编译任务与历史证据",
                })
            runs_dir = config.rp(chain["runs_dir"])
            caps.append({
                "id": f"chain.{chain_id}.runs", "chain": chain_id,
                "label": f"{chain['label']}证据目录", "path": str(runs_dir),
                "status": "PRESENT" if runs_dir.is_dir() else "NOT_FOUND",
            })
        for name, interp in P["interpreters"].items():
            caps.append({
                "id": f"interp.{name}", "label": f"解释器 {name}", "path": interp,
                "status": "PRESENT" if Path(interp).is_file() and os.access(interp, os.X_OK) else "NOT_FOUND",
                "note": "主动探测后显示版本与包元数据",
                "probe": self.cache.get(f"interp.{name}"),
            })
        for key, rel in P["models"].items():
            p = config.rp(rel)
            caps.append({
                "id": f"model.{key}", "label": f"模型/检查点 {key}", "path": str(p),
                "status": "PRESENT" if p.exists() else "NOT_FOUND",
                "probe": self.cache.get(f"model.{key}"),
            })
        caps.append({
            "id": "training.source_fingerprint", "label": "训练源码指纹",
            "path": str(config.rp(P["chains"]["training"]["src"])),
            "expected": P["chains"]["training"]["source_fingerprint"],
            "status": "PRESENT",
            "probe": self.cache.get("training.source_fingerprint"),
            "note": "主动探测按 bh_common.source_hash() 重算并比对",
        })
        caps.append({
            "id": "gpu", "label": "GPU 状态", "status": "PRESENT",
            "probe": self.cache.get("gpu"),
            "note": "nvidia-smi 轻量查询；不自动做压力测试",
        })
        for tid, tool in [("cmake", "cmake"), ("ninja", "ninja"), ("clangpp", "clang++"),
                          ("ffmpeg", "ffmpeg"), ("readelf", "readelf"), ("file", "file")]:
            caps.append({
                "id": f"tool.{tid}", "label": f"构建工具 {tool}", "status": "PRESENT",
                "probe": self.cache.get(f"tool.{tid}"),
            })
        # ARM buildchain materials
        arm = {
            "toolchain_cmake": "bhuman/local-k1-validation-20261019/bhuman-local/Make/CMake/BoosterToolchain.cmake",
            "sdk_lib": "bhuman/local-k1-validation-20261019/bhuman-local/Util/BoosterRoboticsSDK/lib/LinuxArm64/libbooster_robotics_sdk.a",
            "buildchain_include": "bhuman/local-k1-validation-20261019/bhuman-local/Util/Buildchain/Booster/include",
            "buildchain_lib": "bhuman/local-k1-validation-20261019/bhuman-local/Util/Buildchain/Booster/lib",
        }
        for key, rel in arm.items():
            p = config.rp(rel)
            caps.append({
                "id": f"arm.{key}", "label": f"ARM 构建材料 {key}", "path": str(p),
                "status": "PRESENT" if p.exists() else "NOT_FOUND",
                "note": "材料存在≠ARM 编译已通过；见 L4 构建任务",
            })
        ilab = P["other_capabilities"]["isaaclab"]
        caps.append({
            "id": "cap.isaaclab", "label": "Isaac Lab 环境（独立能力）",
            "path": ilab["path"],
            "status": "PRESENT" if Path(ilab["path"]).is_dir() else "NOT_FOUND",
            "note": ilab["note"],
        })
        live = identity.current()
        for cap in caps:
            if cap['id'] == 'training.source_fingerprint':
                actual = live['training_source']
                cap['probe'] = {'sha256': actual, 'identity_match': actual == cap['expected'], 'probed_at': util.now_local()}
            if cap['id'] in ('model.walk_pth', 'model.walk_onnx_match'):
                key = cap['id'].split('.', 1)[1]
                actual = identity.file_identity(cap['path'])
                expected = P['expected_hashes'][key + '_sha256']
                cap['probe'] = {'sha256': actual, 'expected': expected, 'identity_match': bool(actual) and actual == expected,
                                'probed_at': util.now_local()}
            if cap['id'].startswith('tool.') and not shutil.which(cap['label'].split()[-1]):
                cap['status'] = 'NOT_FOUND'
        caps.append({'id': 'bhuman.protected_contract', 'label': '比赛官方步态/正常视觉受保护文件',
                     'status': 'VERIFIED' if live['official_contract_matches'] else 'STALE',
                     'probe': {'identity_match': live['official_contract_matches'], 'files': live['protected_files']},
                     'note': '19个受保护文件的当前内容与保留的官方树逐项比对；不认证全部源码/真机'})
        return {"generated_at": util.now_local(), "mode": "passive",
                "status_label": STATUS_LABEL, "capabilities": [self._effective(c) for c in caps]}

    @staticmethod
    def _effective(cap):
        """Upgrade display status from a cached active probe, never hiding staleness."""
        probe = cap.get("probe") or {}
        cap = dict(cap)
        if cap.get('status') == 'NOT_FOUND':
            return cap
        if probe.get("identity_match") is True:
            cap["status"] = "VERIFIED"
        elif probe.get("identity_match") is False:
            cap["status"] = "STALE"
        elif probe.get("ok") is True and cap["status"] == "PRESENT":
            cap["status"] = "INSTALLED"
        elif probe.get("ok") is False and probe.get("error"):
            cap["status"] = "BLOCKED" if cap["status"] != "NOT_FOUND" else "NOT_FOUND"
        return cap

    # ------------------------------------------------------------- active
    def active_probe(self) -> dict:
        """Run bounded active probes (interpreter metadata, tool versions, GPU,
        key model hashes, training source fingerprint). No training/simulation."""
        P = self.proj
        interp_pkgs = {
            "bh_gym": ["torch", "isaacgym", "numpy", "onnx", "onnxruntime"],
            "isaacsim_gui": ["mujoco", "torch", "onnx", "onnxruntime", "isaacsim"],
            "isaaclab": ["isaaclab", "torch", "onnx", "onnxruntime"],
            "system_python": [],
        }
        for name, interp in P["interpreters"].items():
            if Path(interp).is_file():
                self.cache[f"interp.{name}"] = _probe_python(interp, interp_pkgs.get(name, []))
                self.cache[f"interp.{name}"]["probed_at"] = util.now_local()
        for tid, argv in [("cmake", ["cmake", "--version"]), ("ninja", ["ninja", "--version"]),
                          ("clangpp", ["clang++", "--version"]), ("ffmpeg", ["ffmpeg", "-version"]),
                          ("readelf", ["readelf", "--version"]), ("file", ["file", "--version"])]:
            self.cache[f"tool.{tid}"] = _probe_tool(argv)
            self.cache[f"tool.{tid}"]["probed_at"] = util.now_local()
        self.cache["gpu"] = _gpu()
        self.cache["gpu"]["probed_at"] = util.now_local()
        for key, expected in [("walk_pth", P["expected_hashes"]["walk_pth_sha256"]),
                              ("walk_onnx_match", P["expected_hashes"]["walk_onnx_match_sha256"])]:
            rel = P["models"].get(key)
            p = config.rp(rel)
            entry = {"probed_at": util.now_local()}
            if p.is_file():
                actual = util.sha256_file(p)
                entry.update({"sha256": actual, "expected": expected,
                              "identity_match": actual == expected})
            else:
                entry.update({"error": "not found"})
            self.cache[f"model.{key}"] = entry
        src = config.rp(P["chains"]["training"]["src"])
        fp = util.training_source_fingerprint(src)
        self.cache["training.source_fingerprint"] = {
            "sha256": fp, "expected": P["chains"]["training"]["source_fingerprint"],
            "identity_match": fp == P["chains"]["training"]["source_fingerprint"],
            "probed_at": util.now_local(),
        }
        util.write_json(self.cache_path, self.cache)
        return self.passive() | {"mode": "active", "generated_at": util.now_local()}
