import { Dict, short } from "../api";
import { Badge, Card, Empty, usePoll } from "../components/ui";

interface StressRun {
  id: string;
  policy: string;
  policy_sha256: string;
  setup: Dict<any>;
  metrics: { fall_rate: number; fall_rate_ci95: [number, number]; falls: number; tracking_rmse: Dict<number>; stand_mean_speed: number; torque_saturation_fraction: number; mean_max_tilt_rad: number; median_time_to_fall_s: number | null };
  performance: { wall_s: number; steps_per_s: number; realtime_factor_aggregate: number };
  engine: Dict<any>;
}

interface IsaacEval {
  id: string;
  status: string;
  policy: string;
  policy_sha256: string;
  seed: number;
  resets: number;
  segments: Dict<number[]>;
}

interface Gate {
  id: string;
  pack_id: string;
  verdict: string;
  at: string;
  gates: Dict<{ status: string; reason?: string; [k: string]: any }>;
}

const VERDICT: Dict<string> = { SIM_QUALIFIED: "ok", NOT_QUALIFIED: "bad", INSUFFICIENT_EVIDENCE: "warn" };
const GATE_LABEL: Dict<string> = {
  L0_identity: "L0 身份与契约",
  L1_numerics: "L1 导出数值一致",
  G1_isaacgym_eval: "G1 Isaac Gym 冻结日程评估",
  G2_mujoco_warp: "G2 MuJoCo Warp 跨引擎压力",
  G2F_fragility: "G2F 易损性图谱（非劣效）",
  G3_simrobot_series: "G3 SimRobot 系列赛",
  L5_hardware: "L5 真机闭环",
};

function policyName(path: string) {
  const parts = path.split("/");
  const i = parts.indexOf("packs");
  return i >= 0 ? parts[i + 1] : parts.slice(-3).join("/");
}

export function Evals() {
  const evals = usePoll<{ stress: StressRun[]; isaac: IsaacEval[] }>("/api/evals", 10000);
  const gates = usePoll<Gate[]>("/api/gates", 10000);
  return (
    <>
      <div className="page-title">
        <h2>评测与晋级</h2>
        <p>三套物理引擎的独立证据：Isaac Gym（训练同源）、MuJoCo Warp（跨引擎批量 sim2sim）、SimRobot（B-Human 比赛程序）；晋级只代表仿真不劣于官方</p>
      </div>
      <Card title="晋级门" sub="缺证据 = INSUFFICIENT，永不默认通过；L5 真机固定未验证">
        {!gates.data?.length ? (
          <Empty>尚无晋级评估（CLI：forge gate PACK --isaac-candidate … --mj-candidate … --series …）</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>运控包</th>
                {Object.values(GATE_LABEL).map((l) => <th key={l}>{l}</th>)}
                <th>结论</th>
              </tr>
            </thead>
            <tbody>
              {gates.data.map((g) => (
                <tr key={g.id}>
                  <td className="mono">{g.pack_id}<div className="hint">{g.at?.slice(0, 19)}</div></td>
                  {Object.keys(GATE_LABEL).map((k) => (
                    <td key={k} title={g.gates[k]?.reason || ""}><Badge value={g.gates[k]?.status} text={g.gates[k]?.status} /></td>
                  ))}
                  <td><span className={`badge ${VERDICT[g.verdict] || "muted"}`}>{g.verdict}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <Card title="MuJoCo Warp 批量 sim2sim 压力评测" sub="B-Human 344→13 契约 · 2 ms 物理 / 20 ms 策略 · 随机指令 + 躯干推扰 · 跌倒 = 高度<0.30 m 或倾角>1 rad">
        {!evals.data?.stress.length ? (
          <Empty>尚无评测（CLI：forge stress PACK_ID --worlds 2048 --seconds 20 --push-force 60）</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>运行</th><th>策略</th><th className="num">世界</th><th className="num">推扰 N</th><th className="num">跌倒率 (95% CI)</th>
                <th className="num">vx / vy / wz RMSE</th><th className="num">站立漂移</th><th className="num">步/秒</th>
              </tr>
            </thead>
            <tbody>
              {evals.data.stress.map((r) => (
                <tr key={r.id}>
                  <td className="mono hint" style={{ fontSize: 11.5 }}>{r.id.slice(0, 22)}</td>
                  <td className="mono" style={{ fontSize: 12 }}>{policyName(r.policy || "")}<div className="hint">{short(r.policy_sha256)}</div></td>
                  <td className="num">{r.setup?.worlds}</td>
                  <td className="num">{r.setup?.push_force_max_N}</td>
                  <td className="num">
                    <b>{(r.metrics.fall_rate * 100).toFixed(1)}%</b>{" "}
                    <span className="hint">[{(r.metrics.fall_rate_ci95[0] * 100).toFixed(1)}, {(r.metrics.fall_rate_ci95[1] * 100).toFixed(1)}]</span>
                  </td>
                  <td className="num mono">{["vx", "vy", "wz"].map((k) => r.metrics.tracking_rmse[k].toFixed(3)).join(" / ")}</td>
                  <td className="num">{r.metrics.stand_mean_speed.toFixed(3)}</td>
                  <td className="num">{Math.round(r.performance.steps_per_s).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <Card title="主线冻结日程评估（Isaac Gym）" sub="真实 done/time_out 计数；分段 settled RMSE">
        {!evals.data?.isaac.length ? (
          <Empty>尚无（在步态实验室对检查点点「行走评估」）</Empty>
        ) : (
          <table>
            <thead>
              <tr><th>运行</th><th>策略</th><th className="num">种子</th><th className="num">非超时复位</th><th>状态</th></tr>
            </thead>
            <tbody>
              {evals.data.isaac.map((r) => (
                <tr key={r.id}>
                  <td className="mono hint">{r.id.slice(0, 22)}</td>
                  <td className="mono" style={{ fontSize: 12 }}>{(r.policy || "").split("/").slice(-3).join("/")}<div className="hint">{short(r.policy_sha256)}</div></td>
                  <td className="num">{r.seed}</td>
                  <td className="num">{r.resets ?? "—"}</td>
                  <td><Badge value={r.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
