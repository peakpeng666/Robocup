"""Arena: a flashable copy of the B-Human configuration for team-vs-team simulation.

The validated SimRobot Release binary of bhuman-local is used unchanged. On Linux
``File::getBHDir()`` searches the working directory upwards for ``Config/``, so running
that binary with ``cwd = arena root`` loads the arena configuration instead.

Per-team flashing uses B-Human's own per-team scenarios (``RoboCup.scenarios``). Every
simulated robot is called ``SimulatedK1`` and ``Config/Robots/SimulatedK1`` comes first
in the search path, so its files would shadow a team scenario; the arena therefore moves
those files into each team's ``Scenarios/Forge_T<team>/K1`` and verifies that a baseline
team resolves byte-identical configuration to the original layout.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from . import bhconfig, contracts, packs, paths, source_identity, util
from .locking import exclusive_simulation

ROBOT_NAME = "SimulatedK1"
ROBOT_TYPE = "K1"
DEFAULT_LOCATION = "MField"
GENERATED_PREFIXES = ("Scenarios/Forge_", "NeuralNets/Walk/forge/", "Scenes/K1/Forge_")
TEAM_NUMBERS = (5, 70)  # B-Human, B-Team in the public 3v3 scene


class ArenaError(RuntimeError):
    pass


def team_scenario(team: int) -> str:
    return f"Forge_T{int(team)}"


def variant_change_class(source: Path) -> dict:
    """Require additive source or a precisely reviewed opt-in simulator extension."""
    variant = util.read_json(Path(source) / "variant.json")
    if not variant:
        return {"kind": "bhuman-local", "additive": True, "baseline_compatible": True, "changed": []}
    return source_identity.classify(Path(source), paths.BH_LOCAL, variant)


class Arena:
    def __init__(self, name: str = "main", source: Path = paths.BH_LOCAL):
        self.name = util.safe_name(name)
        self.root = paths.ARENAS / self.name
        self.config = self.root / "Config"
        state = util.read_json(self.root / "arena.json")
        self.source = Path(state["source"]) if state and state.get("source") else Path(source)
        self.source_config = self.source / "Config"
        self.binary = self.source / "Build/Linux/SimRobot/Release/SimRobot"
        self.shadow_base = self.root / "shadow-base"
        self.flash_dir = self.root / "flash"
        self.state_path = self.root / "arena.json"

    # ------------------------------------------------------------ lifecycle
    def state(self) -> dict | None:
        return util.read_json(self.state_path)

    @exclusive_simulation(ArenaError)
    def materialize(self, refresh: bool = False) -> dict:
        state = self.state()
        if state and not refresh:
            return state
        if not self.binary.is_file():
            raise ArenaError(f"源码 {self.source} 没有 SimRobot Release 程序，先编译该变体")
        build_identity = source_identity.build_identity(self.source)
        if not build_identity["ok"]:
            raise ArenaError("变体编译产物未与源码身份绑定（含 Core3），请重新完整编译")
        source_manifest = util.tree_manifest(self.source_config)
        staging = self.root.with_name(self.root.name + ".staging-" + util.stamp())
        staging.mkdir(parents=True)
        shutil.copytree(self.source_config, staging / "Config", symlinks=True)
        copied = util.tree_manifest(staging / "Config")
        if copied != source_manifest:
            raise ArenaError("复制后的 Config 与 bhuman-local 不一致")
        shadow_dir = staging / "Config/Robots" / ROBOT_NAME
        moved = {}
        (staging / "shadow-base").mkdir()
        for path in sorted(shadow_dir.iterdir()):
            if path.is_file():
                moved[path.name] = util.sha256_file(path)
                shutil.move(str(path), staging / "shadow-base" / path.name)
        (staging / "flash").mkdir()
        state = {
            "schema": "forge.arena/2", "name": self.name, "created_at": util.now_iso(),
            "source_config": str(self.source_config),
            "source_manifest_sha256": util.manifest_digest(source_manifest),
            "source_files": len(source_manifest),
            "shadow_moved": moved,
            "source": str(self.source),
            "variant": variant_change_class(self.source), "build_identity": build_identity,
            "binary": str(self.binary),
            "binary_sha256": util.sha256_file(self.binary),
            "controller_sha256": util.sha256_file(self.binary.parent / "libSimulatedRobot.so"),
            "core3_sha256": util.sha256_file(self.binary.parent / "libSimRobotCore3.so"),
            "binary_identical_to_validated_release": util.sha256_file(self.binary) == util.sha256_file(paths.SIMROBOT_RELEASE)
            and util.sha256_file(self.binary.parent / "libSimulatedRobot.so")
            == util.sha256_file(paths.SIMROBOT_RELEASE.parent / "libSimulatedRobot.so")
            and util.sha256_file(self.binary.parent / "libSimRobotCore3.so")
            == util.sha256_file(paths.SIMROBOT_RELEASE.parent / "libSimRobotCore3.so"),
            "note": "cwd 指向 arena Config；程序/控制器/物理内核分别记录身份，扩展变体不声称所有二进制与官方相同",
        }
        util.write_json(staging / "arena.json", state)
        util.write_json(staging / "source-manifest.json", source_manifest)
        if self.root.exists():
            previous = paths.RUNS / "arena-archives" / f"{util.stamp()}_{self.name}"
            previous.parent.mkdir(parents=True, exist_ok=True)
            self.root.rename(previous)
        staging.rename(self.root)
        return state

    def freshness(self) -> dict:
        """Is the arena still a faithful copy of the current bhuman-local Config?"""
        state = self.state()
        if not state:
            return {"status": "NOT_MATERIALIZED"}
        current = util.manifest_digest(util.tree_manifest(self.source_config))
        binary = util.sha256_file(self.binary) if self.binary.is_file() else None
        controller_file = self.binary.parent / "libSimulatedRobot.so"
        controller = util.sha256_file(controller_file) if controller_file.is_file() else None
        core3_file = self.binary.parent / "libSimRobotCore3.so"
        core3 = util.sha256_file(core3_file) if core3_file.is_file() else None
        core3_ok = core3 == state.get("core3_sha256") and (core3 is not None or state.get("schema") != "forge.arena/2")
        build_ok = source_identity.build_identity(self.source)["ok"]
        ok = (build_ok and core3_ok and current == state["source_manifest_sha256"] and binary == state["binary_sha256"]
              and controller is not None and controller == state.get("controller_sha256"))
        return {"status": "FRESH" if ok else "STALE", "source_changed": current != state["source_manifest_sha256"],
                "binary_changed": binary != state["binary_sha256"],
                "controller_changed": controller != state.get("controller_sha256"), "core3_changed": not core3_ok,
                "build_identity_changed": not build_ok}

    # ---------------------------------------------------------------- flash
    def flashed(self) -> dict[int, dict]:
        out = {}
        if self.flash_dir.is_dir():
            for path in sorted(self.flash_dir.glob("T*.json")):
                receipt = util.read_json(path)
                if receipt:
                    out[int(receipt["team"])] = receipt
        return out

    @exclusive_simulation(ArenaError)
    def flash(self, team: int, pack_id: str) -> dict:
        state = self.state()
        if not state:
            raise ArenaError("arena 尚未建立，先执行 materialize")
        if self.freshness()["status"] != "FRESH":
            raise ArenaError("bhuman-local 的 Config 或 SimRobot 已变化，arena 已过期；请刷新 arena")
        pack = packs.load(pack_id)
        verification = packs.verify(pack_id)
        if verification["status"] != "PASS":
            raise ArenaError(f"运控包 {pack_id} 校验失败: {verification['checks']}")
        scenario = team_scenario(team)
        files = self.render_team_files(pack)
        scenario_root = self.config / "Scenarios" / scenario
        if scenario_root.exists():
            previous = paths.RUNS / "flash-history" / f"{util.stamp()}_{self.name}_T{team}"
            previous.mkdir(parents=True)
            scenario_root.rename(previous / "scenario")
            receipt_path = self.flash_dir / f"T{int(team)}.json"
            if receipt_path.is_file():
                shutil.copy2(receipt_path, previous / "receipt.json")
        target = scenario_root / ROBOT_TYPE
        target.mkdir(parents=True)
        written = {}
        for name, text in sorted(files.items()):
            (target / name).write_text(text, encoding="utf-8")
            written[name] = util.sha256_file(target / name)
        patches = packs.effective_patches(pack)
        networks = {}
        if pack["kind"] != "baseline":
            nn_dir = self.config / "NeuralNets/Walk/forge" / pack["id"]
            nn_dir.mkdir(parents=True, exist_ok=True)
            for slot, entry in pack["components"].items():
                destination = nn_dir / f"{slot}.onnx"
                shutil.copy2(packs.pack_dir(pack["id"]) / entry["file"], destination)
                networks[slot] = {"path": destination.relative_to(self.config).as_posix(),
                                  "sha256": util.sha256_file(destination)}
        receipt = {"team": int(team), "scenario": scenario, "pack_id": pack["id"], "pack_kind": pack["kind"],
                   "pack_name": pack["name"], "written": written, "networks": networks,
                   "patches": patches, "modules": pack.get("modules") or {}, "at": util.now_iso()}
        util.write_json(self.flash_dir / f"T{int(team)}.json", receipt)
        return receipt

    def render_team_files(self, pack: dict, location: str = DEFAULT_LOCATION) -> dict[str, str]:
        """Pure function: the exact team-scenario files a pack implies (used by flash and verify)."""
        state = self.state()
        patches = packs.effective_patches(pack)
        files: dict[str, str] = {}
        for name in sorted(state["shadow_moved"]):
            text = (self.shadow_base / name).read_text(encoding="utf-8")
            if name in patches:
                text = bhconfig.CfgDocument(text, name).patched(patches[name])
            files[name] = text
        for name, changes in patches.items():
            if name in files:
                continue
            base = bhconfig.resolve(self.source_config, name, robot_name=ROBOT_NAME, robot_type=ROBOT_TYPE, location=location)
            if base is None:
                raise ArenaError(f"{name} 在 B-Human 配置搜索路径中不存在，无法修改")
            files[name] = bhconfig.CfgDocument.load(base).patched(changes)
        for module, spec in sorted((pack.get("modules") or {}).items()):
            if not self.has_module(module):
                raise ArenaError(f"arena 的程序（{self.source}）里没有模块 {module}；请用包含它的源码变体建立 arena")
            threads_base = bhconfig.resolve(self.source_config, "threads.cfg", robot_name=ROBOT_NAME,
                                            robot_type=ROBOT_TYPE, location=location)
            text = files.get("threads.cfg") or threads_base.read_text(encoding="utf-8")
            marker = f"provider = {spec['replaces']};"
            if text.count(marker) == 0:
                raise ArenaError(f"threads.cfg 中没有 {spec['replaces']} 的提供者")
            files["threads.cfg"] = text.replace(marker, f"provider = {module};")
            base_cfg = spec.get("base_cfg", "walkingEngine.cfg")
            base_text = files.get(base_cfg)
            if base_text is None:
                base_path = bhconfig.resolve(self.source_config, base_cfg, robot_name=ROBOT_NAME,
                                             robot_type=ROBOT_TYPE, location=location)
                if base_path is None:
                    raise ArenaError(f"新模块的基础配置 {base_cfg} 不存在")
                base_text = base_path.read_text(encoding="utf-8")
            params = {**(spec.get("params") or {}), **packs.module_model_params(pack, module)}
            files[spec["cfg"]] = bhconfig.CfgDocument(base_text, spec["cfg"]).with_values(params)
        return files

    def has_module(self, module: str) -> bool:
        return any(self.source.glob(f"Src/Modules/**/{module}.cpp"))

    # --------------------------------------------------------------- verify
    def verify(self, teams=TEAM_NUMBERS, location: str = DEFAULT_LOCATION) -> dict:
        """Static read-back of what each team's robots will load."""
        state = self.state()
        if not state:
            raise ArenaError("arena 尚未建立")
        receipts = self.flashed()
        base_settings = dict(robot_name=ROBOT_NAME, robot_type=ROBOT_TYPE, location=location, scenario="Default")
        names = bhconfig.candidate_names(self.source_config, **base_settings)
        for team in teams:
            names |= bhconfig.candidate_names(self.config, robot_name=ROBOT_NAME, robot_type=ROBOT_TYPE,
                                              location=location, scenario=team_scenario(team))
        original = bhconfig.resolution_table(self.source_config, names, **base_settings)
        report = {"location": location, "freshness": self.freshness(), "teams": {}, "checks": {}}
        report["checks"]["arena_fresh"] = report["freshness"]["status"] == "FRESH"
        report["checks"]["untouched_outside_generated"] = self._outside_generated_unchanged(state)
        for team in teams:
            receipt = receipts.get(int(team))
            team_report = {"flashed": receipt is not None}
            if receipt is None:
                report["teams"][str(team)] = team_report
                report["checks"][f"T{team}_flashed"] = False
                continue
            pack = packs.load(receipt["pack_id"])
            settings = dict(robot_name=ROBOT_NAME, robot_type=ROBOT_TYPE, location=location,
                            scenario=team_scenario(team))
            table = bhconfig.resolution_table(self.config, names, **settings)
            try:
                expected_files = self.render_team_files(pack, location)
                render_error = None
            except (ArenaError, bhconfig.CfgError) as exc:
                expected_files, render_error = {}, str(exc)
            declared = {n for n, text in expected_files.items()
                        if original.get(n, {}).get("sha256") != util.sha256_bytes(text.encode("utf-8"))}
            missing = sorted(n for n in original if n not in table)
            diffs = sorted(n for n in set(original) | set(table)
                           if original.get(n, {}).get("sha256") != table.get(n, {}).get("sha256"))
            undeclared = [n for n in diffs if n not in declared]
            exact = bool(expected_files) and all(
                table.get(n, {}).get("sha256") == util.sha256_bytes(t.encode("utf-8")) for n, t in expected_files.items())
            from_team_scenario = bool(expected_files) and all(
                table.get(n, {}).get("path", "").startswith(f"Scenarios/{team_scenario(team)}/") for n in expected_files)
            modules = pack.get("modules") or {}
            network_cfg = next((spec["cfg"] for spec in modules.values()), "walkingEngine.cfg")
            network_report = self._network_readback(table, pack, network_cfg)
            team_report.update(pack_id=pack["id"], pack_kind=pack["kind"], missing=missing, differs=diffs,
                               undeclared_differences=undeclared, networks=network_report, modules=sorted(modules),
                               render_error=render_error)
            report["teams"][str(team)] = team_report
            report["checks"].update({
                f"T{team}_no_missing_files": not missing,
                f"T{team}_only_declared_differences": not undeclared,
                f"T{team}_patched_content_exact": exact,
                f"T{team}_motion_files_from_team_scenario": from_team_scenario,
                f"T{team}_networks_match_pack": all(v["ok"] for v in network_report.values()),
            })
            if modules:
                report["checks"][f"T{team}_modules_in_program"] = all(self.has_module(m) for m in modules)
            if pack["kind"] == "baseline":
                report["checks"][f"T{team}_baseline_byte_identical"] = not diffs
        report["status"] = "PASS" if report["checks"] and all(report["checks"].values()) else "FAIL"
        return report

    def _network_readback(self, table: dict, pack: dict, cfg_name: str = "walkingEngine.cfg") -> dict:
        out = {}
        if cfg_name not in table:
            return {cfg_name: {"ok": False, "error": f"未解析到 {cfg_name}"}}
        document = bhconfig.CfgDocument.load(self.config / table[cfg_name]["path"])
        for slot in packs.motion_slots(pack):
            contract = contracts.CONTRACTS[slot]
            model_name = document.get(contract.cfg_key)
            model_path = self.config / "NeuralNets/Walk" / model_name
            expected = pack["components"].get(slot, {}).get("sha256")
            if expected is None:  # slot not in pack -> must stay official
                expected = util.sha256_file(paths.BH_OFFICIAL / contract.official_file)
            actual = util.sha256_file(model_path) if model_path.is_file() else None
            out[slot] = {"model_name": model_name, "path": str(model_path), "sha256": actual,
                         "expected_sha256": expected, "ok": actual == expected}
        return out

    def _outside_generated_unchanged(self, state: dict) -> bool:
        source_manifest = util.read_json(self.root / "source-manifest.json") or {}
        current = util.tree_manifest(self.config)
        for relative, digest in source_manifest.items():
            if relative.startswith(f"Robots/{ROBOT_NAME}/"):
                if relative in current:
                    return False  # shadow files must stay moved out
                continue
            if current.get(relative) != digest:
                return False
        for relative in current:
            if relative not in source_manifest and not relative.startswith(GENERATED_PREFIXES):
                return False
        return True

    # ---------------------------------------------------------------- scenes
    def write_scene(self, tag: str, teams=TEAM_NUMBERS, location: str = DEFAULT_LOCATION) -> tuple[Path, Path]:
        """3v3 Middle-field scene from the validated local match scene with per-team scenarios."""
        template = (self.source_config / "Scenes/K1/BHumanLocalMatch.ros3").read_text(encoding="utf-8")
        marker = '<Compound name="scenarios">\n      <Compound name="Default"/>\n    </Compound>'
        if marker not in template or f'<Compound name="{location}"/>' not in template:
            raise ArenaError("模板场景结构与预期不同，拒绝生成")
        replacement = ('<Compound name="scenarios">\n'
                       + "".join(f'      <Compound name="{team_scenario(t)}"/>\n' for t in teams)
                       + "    </Compound>")
        scene_text = template.replace(marker, replacement)
        name = f"Forge_{util.safe_name(tag, 40).replace('-', '_')}"
        scene = self.config / "Scenes/K1" / f"{name}.ros3"
        console = scene.with_suffix(".con")
        scene.write_text(scene_text, encoding="utf-8")
        console.write_text((self.source_config / "Scenes/K1/BHumanLocalMatch.con").read_text(encoding="utf-8"),
                           encoding="utf-8")
        return scene, console

    def write_motion_scene(self, tag: str) -> tuple[Path, Path]:
        template = (self.source_config / "Scenes/K1/BHumanLocalGait.ros3").read_text(encoding="utf-8")
        marker = '<Compound name="location">'
        if template.count(marker) != 1 or 'name="robot5"' not in template:
            raise ArenaError("固定指令场景模板不匹配")
        template = template.replace(marker, '<Compound name="scenarios"><Compound name="Forge_T5"/><Compound name="Forge_T70"/></Compound>\n    ' + marker)
        scene = self.config / "Scenes/K1" / f"Forge_{util.safe_name(tag, 40).replace('-', '_')}.ros3"
        scene.write_text(template, encoding="utf-8")
        console = scene.with_suffix(".con")
        console.write_text((self.source_config / "Scenes/K1/BHumanLocalGait.con").read_text(), encoding="utf-8")
        return scene, console
