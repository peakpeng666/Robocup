"""Dependency graph: built from machine-readable discovery + evidence, not hardcoded cards."""
from pathlib import Path

from . import config, util


def build_graph(discovery_report: dict, evidence_index: dict) -> dict:
    P = config.project()
    caps = {c["id"]: c for c in discovery_report.get("capabilities", [])}

    def status_of(cap_id, default="UNVERIFIED"):
        cap = caps.get(cap_id)
        if not cap:
            return default
        probe = cap.get("probe") or {}
        if probe.get("identity_match") is True:
            return "VERIFIED"
        if probe.get("identity_match") is False:
            return "STALE"
        return cap.get("status", default)

    def latest_run(chain, verdict=None):
        for e in evidence_index.get("entries", []):
            passed = e.get('verdict') == verdict or (chain == 'training' and e.get('execution_status') == 'PASS')
            if e["chain"] == chain and e.get('current_status') == 'VERIFIED' and (verdict is None or passed):
                return e
        return None

    nodes = []
    edges = []

    def node(nid, label, kind, path=None, chain=None, status=None, extra=None):
        n = {"id": nid, "label": label, "kind": kind, "path": path,
             "chain": chain, "status": status or "UNVERIFIED"}
        if extra:
            n.update(extra)
        nodes.append(n)

    # sources
    node("src.bhuman_official", "BHumanCodeRelease (官方比赛源码)", "source",
         str(config.rp(P["chains"]["bhuman"]["official_source"])),
         chain="bhuman", status="PRESENT",
         extra={"upstream_sha": P["chains"]["bhuman"]["official_upstream_sha"]})
    node("src.bhuman_local", "bhuman-local (工作副本+审计探针)", "source",
         str(config.rp(P["chains"]["bhuman"]["source"])), chain="bhuman", status=status_of('bhuman.protected_contract'),
         extra={"note": "官方契约文件经 model_contract() 哈希与官方一致"})
    node("src.training", "MachineLearning 训练源码", "source",
         str(config.rp(P["chains"]["training"]["src"])), chain="training",
         status=status_of("training.source_fingerprint"),
         extra={"upstream_sha": P["chains"]["training"]["upstream_sha"],
                "fingerprint": P["chains"]["training"]["source_fingerprint"],
                "probe": caps.get("training.source_fingerprint", {}).get("probe")})
    node("src.sim2sim", "sim2sim MuJoCo 脚本", "source",
         str(config.rp("bhuman/sim2sim")), chain="sim2sim", status="PRESENT")

    # models / configs
    node("model.walk_pth", "官方行走 actor (K1_walk.pth)", "model",
         str(config.rp(P["models"]["walk_pth"])), chain="training",
         status=status_of("model.walk_pth"),
         extra={"sha256": P["expected_hashes"]["walk_pth_sha256"],
                "probe": caps.get("model.walk_pth", {}).get("probe")})
    node("model.walk_onnx", "比赛官方行走 ONNX", "model",
         str(config.rp(P["models"]["walk_onnx_match"])), chain="bhuman",
         status=status_of("model.walk_onnx_match"),
         extra={"sha256": P["expected_hashes"]["walk_onnx_match_sha256"],
                "probe": caps.get("model.walk_onnx_match", {}).get("probe")})
    node("cfg.k1_yaml", "K1.yaml 控制参数", "config",
         str(config.rp("bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml")), chain="training")
    node("cfg.k1_xml", "K1_locomotion.xml (MuJoCo)", "config",
         str(config.rp("bhuman/k1-training/src/IsaacGymRL/resources/K1/K1_locomotion.xml")),
         chain="sim2sim")
    node("ckpt.iter71", "续训检查点 iter71 (实验候选父)", "checkpoint",
         str(config.rp(P["models"]["resume_checkpoint_iter71"])), chain="training",
         status="UNVERIFIED",
         extra={"note": "实验候选；未获比赛部署晋级"})

    # interpreters / environments
    interp_labels = {"bh_gym": "bh-gym Py3.8 (Isaac Gym)", "isaacsim_gui": "isaacsim-gui Py3.12 (MuJoCo)",
                     "isaaclab": "isaaclab Py3.11", "system_python": "系统 Py3.10 (工作台)"}
    for name, label in interp_labels.items():
        probe = caps.get(f"interp.{name}", {}).get("probe") or {}
        st = "INSTALLED" if probe.get("ok") else ("PRESENT" if Path(P["interpreters"][name]).is_file() else "NOT_FOUND")
        node(f"env.{name}", label, "interpreter", P["interpreters"][name], status=st,
             extra={"probe": probe})
    node("env.isaaclab_src", "IsaacLab 源码（本地修改保留）", "source",
         P["other_capabilities"]["isaaclab"]["path"], status="PRESENT",
         extra={"note": P["other_capabilities"]["isaaclab"]["note"]})

    # build products
    node("build.simrobot_release", "SimRobot Release (桌面)", "binary",
         str(config.rp(P["chains"]["bhuman"]["binary_release"])), chain="bhuman",
         status=status_of("chain.bhuman.binary_release"))
    node("build.booster_arm", "bhuman ARM64 (离线目标)", "binary",
         None, chain="bhuman", status="UNVERIFIED",
         extra={"note": "L4：见离线构建任务；不连接机器人"})

    # runtime chains
    node("run.match", "比赛仿真 (正常视觉)", "runtime", chain="bhuman",
         status="VERIFIED" if latest_run("bhuman", "PASS") else "UNVERIFIED",
         extra={"last_pass": (latest_run("bhuman", "PASS") or {}).get("name")})
    node("run.mujoco", "MuJoCo 行走回放", "runtime", chain="sim2sim",
         status="VERIFIED" if latest_run("sim2sim", "PASS") else "UNVERIFIED",
         extra={"last_pass": (latest_run("sim2sim", "PASS") or {}).get("name")})
    node("run.training", "Gym 训练/回放", "runtime", chain="training",
         status="VERIFIED" if latest_run("training", "PASS") else "UNVERIFIED",
         extra={"last_pass": (latest_run("training", "PASS") or {}).get("name")})
    node("run.real_robot", "真机闭环 (L5)", "runtime", status="BLOCKED",
         extra={"note": "需要后续单独授权与实物实验；本任务固定未验证"})

    # exports & offline artifacts
    node("export.walk", "行走三方导出 (restored-public-walk-20261020)", "artifact",
         str(config.rp(P["models"]["walk_export_dir"])), chain="training", status="PRESENT",
         extra={"note": "tri-check PASS；ORT CPU 不代表 CompiledNN/ARM 后端"})
    node("artifact.bundle", "离线部署包 (.run)", "artifact", status="UNVERIFIED",
         extra={"note": "离线可检查/可解包；不自动安装"})

    E = [
        ("src.bhuman_local", "src.bhuman_official", "哈希对齐官方契约文件"),
        ("build.simrobot_release", "src.bhuman_local", "编译自"),
        ("run.match", "build.simrobot_release", "执行"),
        ("run.match", "model.walk_onnx", "加载策略"),
        ("run.match", "env.system_python", "编排"),
        ("src.training", "env.bh_gym", "运行于"),
        ("run.training", "src.training", "执行"),
        ("run.training", "model.walk_pth", "加载"),
        ("ckpt.iter71", "run.training", "产出"),
        ("export.walk", "model.walk_pth", "导出"),
        ("run.mujoco", "src.sim2sim", "执行"),
        ("run.mujoco", "env.isaacsim_gui", "运行于"),
        ("run.mujoco", "model.walk_pth", "加载 actor"),
        ("run.mujoco", "cfg.k1_yaml", "控制参数"),
        ("run.mujoco", "cfg.k1_xml", "物理模型"),
        ("run.mujoco", "export.walk", "数值比对"),
        ("build.booster_arm", "src.bhuman_local", "交叉编译"),
        ("artifact.bundle", "build.booster_arm", "打包"),
        ("artifact.bundle", "model.walk_onnx", "配套模型"),
        ("run.real_robot", "artifact.bundle", "未来部署(未授权)"),
        ("env.isaaclab_src", "env.isaaclab", "独立能力"),
    ]
    for a, b, rel in E:
        edges.append({"from": a, "to": b, "rel": rel})

    return {"generated_at": util.now_local(), "nodes": nodes, "edges": edges,
            "status_label": discovery_report.get("status_label", {})}
