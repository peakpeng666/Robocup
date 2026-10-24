#!/usr/bin/env python3
"""Static checks for the K1_Reactive design skeleton (no GPU / Isaac Gym)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contract import (  # noqa: E402
    ACTION_LAYOUT,
    FORBIDDEN_ACTOR_WEIGHTS,
    HUOSHEN_T1_ACT,
    HUOSHEN_T1_OBS,
    NUM_ACTIONS,
    NUM_OBSERVATIONS,
    NUM_PRIVILEGED_OBS,
    NUM_STACK,
    OBS_LAYOUT,
    TASK_NAME,
    TRAINABLE,
    WALK_ACT,
    WALK_OBS,
    assert_parallel_to_official_walk,
    layout_dims,
)
from env_stub import (  # noqa: E402
    ISAAC_GYM_TASK_REGISTERED,
    create_training_env,
    refuse_foreign_checkpoint,
)
from skill_switch_map import assert_static_slots  # noqa: E402
from virtual_perception import DelayBuffer, ball_in_fov_placeholder, maybe_drop_detection  # noqa: E402

try:
    import yaml
except ImportError:
    yaml = None

ISAAC_ENV_TREES = (
    "bhuman/MachineLearning/IsaacGymRL/envs",
    "bhuman/k1-training/src/IsaacGymRL/envs",
)

# Runner (utils/runner.py) loads envs/{task}.yaml then eval(task) from
# `from envs import *`. A YAML that only lives in k1-reactive/ is invisible.
# Required gate result when the skeleton YAML exists: unregistered_in_train_py=PASS.
TRAIN_PY_UNREGISTERED_RULE = (
    "skeleton YAML present beside IsaacGymRL AND not imported by "
    "envs/__init__.py AND not copied into envs/ = PASS"
)


def registration_is_leak(
    init_text: str,
    leaked_yaml: bool = False,
    leaked_py: bool = False,
    task: str = TASK_NAME,
) -> bool:
    """Negative-fixture helper. True = train.py could pick the stub up.

    Official init mentioning TASK_NAME, or a leaked envs/K1_Reactive.yaml /
    envs/k1_reactive.py, must FAIL the gate. Comments-only docs outside
    IsaacGymRL/envs are irrelevant; this function only scores those inputs.
    """
    if leaked_yaml or leaked_py:
        return True
    return task in (init_text or "")


def inspect_official_registry(repo: Path | None = None) -> dict[str, Any]:
    """Score official trees. Skeleton YAML in k1-reactive/ is expected."""
    repo = _repo_from(repo)
    leaked: list[str] = []
    notes: list[str] = []
    trees: list[dict[str, Any]] = []
    for rel in ISAAC_ENV_TREES:
        tree = repo / rel
        init = tree / "__init__.py"
        leaked_yaml = (tree / "K1_Reactive.yaml").is_file()
        leaked_py = (tree / "k1_reactive.py").is_file()
        init_text = init.read_text(encoding="utf-8") if init.is_file() else ""
        leak = registration_is_leak(init_text, leaked_yaml, leaked_py)
        record = {
            "rel": rel,
            "init_exists": init.is_file(),
            "mentions_task": TASK_NAME in init_text,
            "leaked_yaml": leaked_yaml,
            "leaked_py": leaked_py,
            "leak": leak,
        }
        trees.append(record)
        if leak:
            if TASK_NAME in init_text:
                leaked.append(f"{rel}/__init__.py must not import {TASK_NAME}")
            if leaked_yaml or leaked_py:
                leaked.append(
                    f"{rel} must not contain a {TASK_NAME} task file "
                    "(would be picked up by train.py)"
                )
        else:
            notes.append(f"{rel}: official registry stays walk/kick/standup only")
    yaml_exists = (ROOT / "K1_Reactive.yaml").is_file()
    unregistered = not leaked
    return {
        "skeleton_yaml_exists": yaml_exists,
        "unregistered_in_train_py": "PASS" if unregistered else "FAIL",
        "rule": TRAIN_PY_UNREGISTERED_RULE,
        "negative_fixture": (
            f"If {TASK_NAME} appears in official envs/__init__.py OR "
            "envs/K1_Reactive.yaml|k1_reactive.py exists, this MUST be FAIL. "
            "See test_unregistered_in_train_py.py."
        ),
        "trees": trees,
        "leaks": leaked,
        "notes": notes,
    }


def _repo_from(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def _load_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if yaml is None:
        raise SystemExit("PyYAML is required to check K1_Reactive.yaml")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise SystemExit(f"{path} is not a mapping")
    return data


def check(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo_from(repo)
    errors: list[str] = []
    notes: list[str] = []

    try:
        assert_parallel_to_official_walk()
    except AssertionError as exc:
        errors.append(str(exc))

    if layout_dims(OBS_LAYOUT) != 64 or NUM_OBSERVATIONS != 64:
        errors.append(f"obs layout {layout_dims(OBS_LAYOUT)} vs NUM_OBSERVATIONS={NUM_OBSERVATIONS}")
    if layout_dims(ACTION_LAYOUT) != 15 or NUM_ACTIONS != 15:
        errors.append("action layout is not 15")
    if TRAINABLE or ISAAC_GYM_TASK_REGISTERED:
        errors.append("skeleton marked trainable or registered")
    notes.append(
        f"baseline walk stays {WALK_OBS}→{WALK_ACT}; {TASK_NAME} is parallel {NUM_OBSERVATIONS}→{NUM_ACTIONS}"
    )
    if NUM_ACTIONS == HUOSHEN_T1_ACT and NUM_OBSERVATIONS == HUOSHEN_T1_OBS:
        errors.append("K1_Reactive must not copy the Huoshen T1 58→15 contract")
    notes.append(
        f"action count {NUM_ACTIONS} equals Huoshen T1 count but slots are head+legs+freq, not waist"
    )

    yaml_path = ROOT / "K1_Reactive.yaml"
    if not yaml_path.is_file():
        errors.append("missing K1_Reactive.yaml")
        cfg = {}
    else:
        cfg = _load_yaml(yaml_path)
        env = cfg.get("env") or {}
        meta = cfg.get("meta") or {}
        obs = cfg.get("observation") or {}
        if env.get("num_observations") != NUM_OBSERVATIONS or env.get("num_actions") != NUM_ACTIONS:
            errors.append(
                f"YAML env {env.get('num_observations')}→{env.get('num_actions')} "
                f"vs contract {NUM_OBSERVATIONS}→{NUM_ACTIONS}"
            )
        if env.get("num_stack") != NUM_STACK or env.get("num_privileged_obs") != NUM_PRIVILEGED_OBS:
            errors.append("YAML stack/priv dims drifted from contract.py")
        if env.get("trainable") is not False or meta.get("trainable") is not False:
            errors.append("YAML must keep trainable: false")
        if meta.get("registered_in_isaacgymrl") is not False:
            errors.append("YAML must keep registered_in_isaacgymrl: false")
        if env.get("num_envs") != 0:
            errors.append("YAML num_envs must stay 0 (no fake training fleet)")
        layout = obs.get("layout") or {}
        if isinstance(layout, dict) and sum(int(v) for v in layout.values()) != NUM_OBSERVATIONS:
            errors.append(f"YAML observation.layout sum {sum(layout.values())} != {NUM_OBSERVATIONS}")
        vp = cfg.get("virtual_perception") or {}
        if vp.get("delay_ms_mean") != 116 or vp.get("delay_steps_default") != 6:
            errors.append("virtual_perception delay fields drifted from 116 ms / 6 steps")
        switch = cfg.get("skill_switch") or {}
        if switch.get("checklist") != "bhuman/docs/SKILL-SWITCH-CONTINUITY.md":
            errors.append("YAML skill_switch.checklist must point at SKILL-SWITCH-CONTINUITY.md")
        if switch.get("implemented") is not False:
            errors.append("YAML skill_switch.implemented must stay false (empty shells only)")
        if switch.get("static_mapper") != "bhuman/k1-training/k1-reactive/skill_switch_map.py":
            errors.append("YAML skill_switch.static_mapper must point at skill_switch_map.py")

    registry = inspect_official_registry(repo)
    errors.extend(registry.get("leaks") or [])
    notes.extend(registry.get("notes") or [])
    if not registry.get("skeleton_yaml_exists"):
        errors.append("skeleton YAML missing (gate assumes K1_Reactive.yaml already exists)")
    if registry.get("unregistered_in_train_py") == "PASS":
        notes.append(
            "unregistered in train.py = PASS "
            "(YAML lives in k1-reactive/; Runner cannot eval the stub)"
        )
    else:
        notes.append("unregistered in train.py = FAIL (see leaks)")

    switch_doc = repo / "bhuman/docs/SKILL-SWITCH-CONTINUITY.md"
    if not switch_doc.is_file():
        errors.append("missing bhuman/docs/SKILL-SWITCH-CONTINUITY.md")
    elif "历史缓冲" not in switch_doc.read_text(encoding="utf-8"):
        errors.append("SKILL-SWITCH-CONTINUITY.md missing 历史缓冲 section")
    else:
        notes.append("skill-switch continuity checklist present (docs + empty shells)")

    hifar_doc = repo / "bhuman/docs/HIFAR-VS-STANDUP.md"
    if not hifar_doc.is_file():
        errors.append("missing bhuman/docs/HIFAR-VS-STANDUP.md")
    else:
        notes.append("HiFAR vs standup 73→22 / fast 72→22 boundary note present")

    for rel, label in (
        ("bhuman/docs/GLOBAL-HUMANOID-SURVEY-20261024.md", "global humanoid survey"),
        ("bhuman/docs/ROADMAP-P0-P5.md", "P0–P5 roadmap"),
        ("bhuman/docs/MIGRATE-TO-K1.md", "migrate-to-K1 table"),
        ("bhuman/docs/BEHAVIOR-TREE-SKILL-SELECT.md", "BT skill-select interface"),
        ("bhuman/docs/schemas/obs-contract-v1.json", "obs contract JSON"),
        ("bhuman/docs/SWITCHER-SM.md", "switcher state-machine note"),
        ("bhuman/docs/P1-CONFIG-DIFF-DRAFT.md", "P1 config diff draft"),
        ("bhuman/docs/DEPLOY-CALL-SEQUENCE.md", "deploy call sequence"),
        ("bhuman/docs/PR4-INDEX.md", "PR #4 file-tree index"),
        ("bhuman/docs/HISTORY-TORQUE-TIMESERIES.md", "history/torque timeseries draft"),
        ("bhuman/docs/P2-ACCEPTANCE.md", "P2 acceptance (walk default; P2 does not change 344)"),
        ("bhuman/docs/HIFAR-VS-STANDUP.md", "HiFAR ≠ standup 73→22 / fast 72→22"),
        ("bhuman/docs/CONTRACT-GATE-GUIDE.md", "contract-gate guide (PASS ≠ trained)"),
        ("bhuman/docs/P3-PREVIEW.md", "P3 preview (no training; walk stays default)"),
        ("bhuman/docs/P4-PREVIEW.md", "P4 preview (no six-robot/real-robot; three gates)"),
        ("bhuman/docs/CI-CONTRACT-GATE.md", "CI contract-gate draft (PASS+WARN, no forced CI)"),
        ("bhuman/docs/P5-PREVIEW.md", "P5 preview (no robot; docs/gate ready ≠ on robot)"),
        ("bhuman/docs/README-RL.md", "RL 5-min map (baseline / two commands / when to train)"),
        (
            "bhuman/k1-training/scripts/run_unit_tests_no_gym.sh",
            "no-Gym one-shot unit tests (walk 344→13; honest SKIP)",
        ),
        (
            "bhuman/k1-training/scripts/run_unit_tests_no_gym.py",
            "no-Gym unit-test runner (discover switcher/reactive/estimators/sim2sim/draft)",
        ),
        (
            "bhuman/k1-training/k1-switcher/onnx_export_contract.py",
            "ONNX export contract (walk 344→13 only; no real weights)",
        ),
        (
            "bhuman/k1-training/k1-switcher/test_gpu_worker_checklist.py",
            "GPU worker checklist (probe only; never train.py)",
        ),
        (
            "bhuman/k1-training/scripts/k1_reward_audit.py",
            "K1 reward read-only audit (no yaml write-back)",
        ),
        (
            "bhuman/k1-training/k1-switcher/history_buffer_shape.py",
            "walk history buffer 10×32+24=344 (zeros ≠ continuity PASS)",
        ),
        (
            "bhuman/docs/RESEARCH-MIGRATE-TABLE.md",
            "research-inputs / GLOBAL short migrate table",
        ),
        (
            "bhuman/k1-training/k1-switcher/joint_map_contract.py",
            "walk 13-D joint map (refuse 12/15/22; standup ≠ walk)",
        ),
        (
            "bhuman/k1-training/scripts/p1_draft_diff.py",
            "official vs draft-only key diff (draft_only:true; live untouched)",
        ),
        (
            "bhuman/docs/PR4-MERGE-CHECKLIST.md",
            "PR #4 merge checklist (merge ≠ trained; no auto-merge)",
        ),
        (
            "bhuman/k1-training/k1-switcher/gait_frequency_contract.py",
            "walk action[12]=gait_frequency (not a 13th motor)",
        ),
        (
            "bhuman/k1-training/scripts/booster_joints_snapshot.py",
            "WalkingEngine boosterJoints snapshot (SKIP if missing; no fabricate)",
        ),
        (
            "bhuman/k1-training/scripts/run_pr4_selfcheck.sh",
            "PR #4 selfcheck (gate + no-gym + audits + GPU probe)",
        ),
        (
            "bhuman/docs/OBS-ASSEMBLY-344.md",
            "deploy-side walk obs assembly 10×32+24=344 (not reactive concat)",
        ),
        (
            "bhuman/k1-training/k1-switcher/obs_assembly.py",
            "walk obs assembly shape check (no fabricate)",
        ),
        (
            "bhuman/k1-training/k1-switcher/last_action_reset.py",
            "return-to-walk last_action 13 zeros (refuse standup[:13])",
        ),
        (
            "bhuman/k1-training/scripts/print_train_dry_run.py",
            "print-only first-train draft --task K1 (干跑成功 ≠ 可训)",
        ),
        (
            "bhuman/k1-training/scripts/env_registry_audit.py",
            "official train.py registry (K1 in; bypass not registered)",
        ),
        (
            "bhuman/docs/GPU-AFTER-ONLINE.md",
            "GPU worker online steps (probe → tell user → wait 开训 → dry-run)",
        ),
        (
            "bhuman/docs/SIMROBOT-SIX-ROBOT-ACCEPTANCE.md",
            "SimRobot six-robot acceptance (no sim; live SKIP; no fake-green)",
        ),
        (
            "bhuman/k1-training/simrobot_acceptance/acceptance.py",
            "six-robot case table S6-1..S6-4 (default walk 344→13)",
        ),
        (
            "bhuman/k1-training/k1-reactive/skill_request_map.py",
            "SkillRequest map (empty/unknown → walk; shoot/pass stay walk)",
        ),
        (
            "bhuman/k1-training/k1-switcher/pd_domain_gap_contract.py",
            "PD domain-gap (train p60 vs robot p25; no K1.yaml write-back)",
        ),
        (
            "bhuman/k1-training/k1-switcher/teamcomm_budget.py",
            "TeamComm 512 B (teammate not into 344; WLAN SKIP)",
        ),
        (
            "bhuman/docs/CHECKPOINT-LAYOUT.md",
            "walk checkpoint layout (K1_walk.pth/onnx; missing SKIP)",
        ),
        (
            "bhuman/k1-training/k1-switcher/checkpoint_layout.py",
            "checkpoint layout checker (T1/reactive refused on walk path)",
        ),
        (
            "bhuman/k1-training/k1-switcher/kick_standup_joint_map.py",
            "kick/standup joint map (standup[12] motor ≠ walk gait_frequency)",
        ),
        (
            "bhuman/k1-training/k1-switcher/reference_motion_inventory.py",
            "reference-motion inventory (missing SKIP; T1 ≠ official walk default)",
        ),
        (
            "bhuman/k1-training/scripts/render_selfcheck_summary.py",
            "selfcheck markdown summary (PASS/SKIP/WARN; not a new survey)",
        ),
        (
            "bhuman/k1-training/scripts/getup_engine_snapshot.py",
            "GetUpEngine 22-D snapshot (match kick_standup; SKIP if missing)",
        ),
        (
            "bhuman/k1-training/scripts/walk_stability_presets_audit.py",
            "official walk-*-stability-v1 audit (draft-only excluded)",
        ),
        (
            "bhuman/k1-training/k1-switcher/forbidden_regressions.py",
            "forbidden regressions pack (silent refuse = gate red)",
        ),
        (
            "bhuman/k1-training/scripts/official_sibling_tasks_audit.py",
            "official sibling tasks (K1_Ball/Stand_Up ≠ walk 344)",
        ),
        (
            "bhuman/k1-training/scripts/onnx_deploy_path_crosscheck.py",
            "ONNX deploy path (CHECKPOINT-LAYOUT × WalkingEngine)",
        ),
        (
            "bhuman/k1-training/k1-switcher/t1_k1_isolation.py",
            "T1/K1 isolation matrix (T1 must not replace K1 walk)",
        ),
        (
            "bhuman/k1-training/scripts/command_schedule_audit.py",
            "command schedule read-only extract (draft not applied)",
        ),
        (
            "bhuman/k1-training/scripts/disturbance_curriculum_audit.py",
            "disturbance draft validator (live push_* not overwritten)",
        ),
        (
            "bhuman/k1-training/scripts/settle_jitter_audit.py",
            "settle/jitter draft (new keys; live action_rate intact)",
        ),
        (
            "bhuman/k1-training/scripts/estimator_ab_audit.py",
            "estimator A/B draft (bypass; not 344 / not train.py)",
        ),
        (
            "bhuman/k1-training/scripts/reference_penalty_anneal_audit.py",
            "reference-penalty anneal (live 1.0 intact)",
        ),
        (
            "bhuman/k1-training/scripts/behavior_control_handoff.py",
            "BehaviorControl handoff (kick/standup owners; default walk; missing SKIP)",
        ),
        (
            "bhuman/k1-training/k1-switcher/compressed_teamcomm_shape.py",
            "CompressedTeamCommunication shape (HSL 512 / official container; not into 344)",
        ),
        (
            "bhuman/k1-training/scripts/falldown_motion_chain.py",
            "FallDown / MotionEngine chain (fallen→73→22→walk; not SkillRequest)",
        ),
        (
            "bhuman/k1-training/k1-switcher/teamcomm_128_vs_512.py",
            "TeamComm 128 vs 512 contrast (do not mix; WLAN SKIP)",
        ),
        (
            "bhuman/k1-training/scripts/force_walk_afterwards.py",
            "Force walk afterwards (getup_done→walk 344→13; 13-zero last_action)",
        ),
        (
            "bhuman/k1-training/scripts/kick_engine_boundary.py",
            "KickEngine boundary (kick 59→13 bypass ≠ walk; missing KickEngine SKIP)",
        ),
        (
            "bhuman/k1-training/scripts/selfcheck_fail_hints.py",
            "selfcheck FAIL locator (先看 file/test; PASS quiet)",
        ),
    ):
        if not (repo / rel).is_file():
            errors.append(f"missing {rel}")
        else:
            notes.append(f"{label} present")

    try:
        assert_static_slots()
        notes.append("skill_switch_map static T1/T2 slots PASS (no Gym)")
    except AssertionError as exc:
        errors.append(f"skill_switch_map: {exc}")

    buf = DelayBuffer(delay_steps=6)
    for i in range(6):
        if buf.push(i) is not None:
            errors.append("DelayBuffer returned a value before 6 steps")
            break
    if buf.push(6) != 0 or buf.push(7) != 1:
        errors.append("DelayBuffer 6-step delay is wrong")
    else:
        notes.append("DelayBuffer: 6 steps ≈ 116 ms at 50 Hz")

    if ball_in_fov_placeholder((2.0, 0.0)) is not True:
        errors.append("FOV placeholder should accept a ball ahead")
    if ball_in_fov_placeholder((-1.0, 0.0)) is not False:
        errors.append("FOV placeholder should reject a ball behind")
    if maybe_drop_detection(True, 0.0) is not True:
        errors.append("dropout_prob=0 must keep a valid detection")

    try:
        refuse_foreign_checkpoint("K1_walk.pth")
    except ValueError:
        notes.append("refuse_foreign_checkpoint blocks official walk weights")
    else:
        errors.append("refuse_foreign_checkpoint accepted K1_walk.pth")
    try:
        refuse_foreign_checkpoint("model.pth")
    except ValueError:
        notes.append("refuse_foreign_checkpoint blocks Huoshen T1 model.pth")
    else:
        errors.append("refuse_foreign_checkpoint accepted Huoshen model.pth")
    try:
        create_training_env()
    except RuntimeError:
        notes.append("create_training_env() raises (stub is not a Gym task)")
    else:
        errors.append("create_training_env() must raise")

    for name in FORBIDDEN_ACTOR_WEIGHTS:
        if name in {"K1_walk.pth", "model.pth"}:
            continue

    return {
        "ok": not errors,
        "task": TASK_NAME,
        "contract": f"{NUM_OBSERVATIONS}→{NUM_ACTIONS}",
        "baseline": f"{WALK_OBS}→{WALK_ACT}",
        "trainable": TRAINABLE,
        "registered": ISAAC_GYM_TASK_REGISTERED,
        "skeleton_yaml_exists": registry.get("skeleton_yaml_exists"),
        "unregistered_in_train_py": registry.get("unregistered_in_train_py"),
        "train_py_rule": registry.get("rule"),
        "registry": registry,
        "errors": errors,
        "notes": notes,
    }


def main() -> int:
    report = check()
    print(
        f"[k1-reactive] {'PASS' if report['ok'] else 'FAIL'} "
        f"{report['contract']} parallel to walk {report['baseline']}; "
        f"unregistered_in_train_py={report.get('unregistered_in_train_py')}"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
