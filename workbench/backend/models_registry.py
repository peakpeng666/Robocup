"""Policy model registry: four contracts, identity hashes, verification evidence.

Contracts are keyed by semantics, never by file extension alone. Dimensions:
  walk 344->13 (12 leg actions + gait frequency), kick 59->13,
  getup 73->22, fast getup 72->22.
"""
from pathlib import Path

from . import config, util

P = config.project()

CONTRACTS = [
    {
        "id": "walk", "label": "行走",
        "input_dim": 344, "output_dim": 13,
        "output_meaning": "12 个腿部关节动作 + 1 个步态频率（不是 13 个电机命令）",
        "actor_arch": "344→256→128→128→13，ELU",
        "history": "10 帧 × 32 维（重力3+陀螺仪3+测量关节12+上一动作12+球占位2），由旧到新",
        "tail": "命令3 + 相位cos/sin2 + 关节速度12 + rawFrequency1 + 球策略占位6",
        "decode": "动作 clip ±2 后加 offset 为关节目标；频率 clip ±0.5 + 1.5Hz",
        "units": "命令 mm→m；关节 rad；物理 2ms/策略 20ms",
        "official_pth": P["models"]["walk_pth"],
        "official_pth_sha256": P["expected_hashes"]["walk_pth_sha256"],
        "official_onnx": P["models"]["walk_onnx_match"],
        "official_onnx_sha256": P["expected_hashes"]["walk_onnx_match_sha256"],
        "tasks": ["K1"], "load_mode": "actor",
        "note": "critic 359 输入与当前配置 360 不匹配；回放/训练恢复加载语义不同",
    },
    {
        "id": "kick", "label": "踢球",
        "input_dim": 59, "output_dim": 13,
        "output_meaning": "12 腿部动作 + 步频；含球位置/方向/速度/踢球类型标志输入",
        "official_onnx": P["models"]["kick_onnx_match"],
        "tasks": ["K1_Ball"], "load_mode": "actor",
        "note": "不能与行走契约互换；选入行走任务必须在执行前拒绝",
    },
    {
        "id": "getup", "label": "普通起身",
        "input_dim": 73, "output_dim": 22,
        "output_meaning": "22 关节目标分量；clip ±3 后加偏置再做 DOF 限幅",
        "official_onnx": P["models"]["getup_onnx_match"],
        "tasks": ["K1_Stand_Up"], "load_mode": "torchscript",
        "note": "默认偏置 HipPitch -0.2 / KneePitch +0.4 / AnklePitch -0.25 rad",
    },
    {
        "id": "getup_fast", "label": "快速起身",
        "input_dim": 72, "output_dim": 22,
        "output_meaning": "输出经解码并切换控制模式（torque control/low 档），不能直接标成 N·m",
        "official_onnx": P["models"]["getup_fast_onnx_match"],
        "tasks": [], "load_mode": None,
        "note": "完整训练配方未在已核查公开版本中找到；未纳入本机导出/训练链",
    },
]


def registry() -> dict:
    out = []
    for c in CONTRACTS:
        entry = dict(c)
        for key in ("official_pth", "official_onnx"):
            rel = c.get(key)
            if not rel:
                continue
            p = config.rp(rel)
            info = {"path": str(p), "exists": p.is_file()}
            if p.is_file() and p.stat().st_size < 512 * 1024 * 1024:
                actual = util.sha256_file(p)
                info["sha256"] = actual
                expected = c.get(key + "_sha256")
                if expected:
                    info["identity_match"] = (actual == expected)
            entry[key + "_file"] = info
        out.append(entry)
    return {"generated_at": util.now_local(), "contracts": out}
