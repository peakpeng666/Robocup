import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Card, Checks, Empty, usePoll, useToast } from "../components/ui";

// ------------------------------------------------------------------ types (subset of forge/bridge/*)
interface Finding { id: string; severity: "critical" | "warn" | "info"; title: string; detail: unknown; evidence: unknown }
interface JointRow { index: number; canonical: string; sdk: string; deploy: string; bhuman: string; mjcf: string; group: string; parallel_in_firmware: boolean }
interface Gain { p?: number; d?: number; max?: number }
interface Contract {
  verdict: string; at: string; joints: JointRow[];
  orders: Record<string, { ok: boolean; count: number }>;
  policy_orders: Record<string, { ok: boolean; count: number }>;
  messages: Record<string, { ok: boolean }>;
  gain_profiles: Record<string, { label: string; source: string; gains: Record<string, Gain> }>;
  limits: { joint: string; mjcf: [number, number]; firmware: [number, number]; sim_wider_by: number }[];
  code_facts: { id: string; source: string; present: boolean; lines: number[]; meaning: string }[];
  findings: Finding[];
}
interface Identity {
  stack: string; variant: string; verdict: string; reference: string; max_position_delta_m: number; final_position_delta_m: number;
  first_over_1cm_s: number | null; first_over_5cm_s: number | null; max_segment_velocity_delta: number;
  segments: Record<string, { command: number[]; reference: number[]; bridge: number[]; delta: number[] }>;
}
interface Scenario { id: string; title: string; status: string; checks: Record<string, boolean>; observed?: Record<string, unknown>; deploy_log?: { t: number; event: string; [k: string]: unknown }[] }
interface Cell { level: number; trials: number; falls: number; stalls: number; mean_forward_m_s: number | null; mean_turn_rad_s: number | null; fall_times_s: number[] }
interface Margin { status: string; margin?: number | null; first_failure?: number | null; censored?: boolean; direction?: string; reference?: number; headroom?: number | null; cells?: Cell[]; reason?: string }
interface Session {
  status: string; checks: Record<string, boolean>; error: string | null; argv: string[]; transport: string; exit_mode: string;
  deploy_metrics: Record<string, { count: number; freq_hz: number }>; timeline: { t: number; event: string }[];
  rpc_sequence: (number | null)[][]; lowcmd_wall_period_ms: { median: number; p99: number; max: number; n: number } | null;
  server_lateness_ms: { p50: number; p99: number; max: number } | null; prime_to_first_policy_command_ms: number | null;
  preparation_to_task_policy_max_gap_ms: number | null; walked_m: number | null; wall_s: number; console_tail: string[];
}
interface BridgeRun {
  run_id: string; at: string; overall: string; real_robot: string; scope: string;
  verdicts: Record<string, string>; identity: Identity[]; identity_tolerance: { segment_velocity: number; exact_position_m: number };
  protocol: Scenario[]; session: Session | null; findings: Finding[];
  gaps: { table: Record<string, Record<string, Margin>>; weakest: Record<string, { axis: string; margin: number; headroom: number }[]>; stall_fraction: number } | null;
  gap_setup: { axes: Record<string, { label: string; unit: string; levels: number[]; reference: number }>; controllers: string[]; seeds: number; gap_onset_s: number; replicates: string; jobs: number; wall_s: number } | null;
  virtual_k1: { assumptions: string[] } | null; environment: Record<string, unknown> | null;
  crosssim: { rows: Record<string, CrossRow>; tolerance: { relative: number; absolute: number }; note: string } | null;
  crosssim_verdict?: string;
}
interface CrossSeg { metric: string; simrobot: number; virtual_k1: number; relative: number | null; agrees: boolean }
interface CrossRow {
  verdict: string; same_weights: boolean | null; reason?: string; segments: Record<string, CrossSeg>;
  drift: Record<string, { simrobot: number | null; virtual_k1: number | null }>; virtual_k1_fell: boolean;
  simrobot: { run: string; pack_id: string; path: string; video: string | null; fall_frames: number | null };
}
interface RunRow { id: string; analyzed: boolean; overall?: string; verdicts?: Record<string, string>; at?: string }
interface Lesson {
  id: string; title: string; category: string; stacks: string[]; status: string; summary: string; action: string; origin: string;
  evidence: { kind: string; path?: string; note?: string; check?: string; experiment?: string; scenario?: string; supported?: boolean; exists?: boolean; run_id?: string }[];
}
interface Ledger { description: string; lessons: Lesson[]; counts: Record<string, number>; problems: string[] }
type Paths = Record<string, { t: number[]; x: number[]; y: number[] }>;

const VERDICT: Record<string, [string, string]> = {
  SIM_BRIDGE_VERIFIED: ["仿真桥接已验证", "ok"], SIM_BRIDGE_ISSUES: ["桥接存在问题", "bad"], INSUFFICIENT_EVIDENCE: ["证据不足", "warn"],
  BRIDGE_FAITHFUL: ["桥接保真", "ok"], BRIDGE_DISTORTS: ["桥接失真", "bad"], PASS: ["通过", "ok"], FAIL: ["未通过", "bad"],
  COMPLETE: ["已完成", "ok"], NOT_RUN: ["未运行", "muted"], EXACT: ["逐点一致", "ok"], FAITHFUL: ["保真", "ok"], DIVERGENT: ["分叉", "bad"],
  UNVERIFIED: ["真机未验证 (L5)", "warn"], CONSISTENT_WITH_DIVERGENCES: ["契约一致（有差异项）", "ok"], CONSISTENT: ["契约一致", "ok"],
  CONTRACT_BROKEN: ["契约破坏", "bad"], CONSISTENT_ACROSS: ["跨仿真一致", "ok"], MODEL_GAP: ["模型差异", "warn"],
};
const SEGMENT_LABEL: Record<string, string> = { forward: "前进 8 s（m）", left: "侧移 6 s（m）", turn: "转向 8 s（rad）" };
const SEVERITY: Record<string, string> = { critical: "bad", warn: "warn", info: "info" };
const LESSON_STATUS: Record<string, [string, string]> = {
  verified_in_sim: ["仿真已验证", "ok"], static_evidence: ["静态证据", "info"], assumption: ["假设", "warn"], needs_real_robot: ["待真机", "violet"],
};
const CONTROLLER_LABEL: Record<string, string> = {
  "bhuman-training": "B-Human（训练增益）", "bhuman-real-gains": "B-Human（真机增益表）", "booster-deploy": "booster_deploy 开源", "firmware-gait": "原厂 1.6 步态（机载）",
};
const PROFILES = ["bhuman_training", "bhuman_sim_regular", "bhuman_real_regular", "deploy_k1_walk", "firmware_walk"];
const MARGIN_STATUS: Record<string, string> = {
  COVERS_REFERENCE: "覆盖关注值", BELOW_REFERENCE: "低于关注值", FAILS_AT_NOMINAL: "标称即失败", NOT_APPLICABLE: "不适用", INSUFFICIENT_EVIDENCE: "证据不足", MEASURED: "已测",
};

function V({ value }: { value?: string | null }) {
  const [text, cls] = VERDICT[value || ""] || [value || "—", "muted"];
  return <span className={`badge ${cls}`}>{text}</span>;
}

function fmt(v: number | null | undefined, digits = 3) {
  if (v === null || v === undefined || !isFinite(v)) return "—";
  return Number(v.toPrecision(digits)).toString();
}

// ------------------------------------------------------------------ architecture
function Architecture() {
  const box = (x: number, y: number, w: number, h: number, title: string, lines: string[], tone = "#7cc4ff", dashed = false) => (
    <g>
      <rect x={x} y={y} width={w} height={h} rx={8} fill="rgba(20,30,44,0.9)" stroke={tone} strokeDasharray={dashed ? "5 4" : undefined} />
      <text x={x + 10} y={y + 18} fill="#e6edf5" fontSize="12.5" fontWeight={600}>{title}</text>
      {lines.map((line, i) => <text key={i} x={x + 10} y={y + 34 + i * 14} fill="#a9b7c9" fontSize="10.5">{line}</text>)}
    </g>
  );
  const link = (x1: number, y1: number, x2: number, y2: number, dashed = false) => (
    <path d={`M${x1},${y1} C${(x1 + x2) / 2},${y1} ${(x1 + x2) / 2},${y2} ${x2},${y2}`} fill="none" stroke="#3a4b63" strokeWidth={1.4}
      strokeDasharray={dashed ? "4 4" : undefined} markerEnd="url(#arrow)" />
  );
  const controllers: [string, string[], string][] = [
    ["B-Human 行走 344→13", ["BoosterProvider 语义", "q, kp=p·刚度, kd=d·刚度"], "#3fbf7f"],
    ["booster_deploy 开源 690→20", ["官方真机代码原样运行", "握手 / 50 Hz / 安全回退"], "#e3b341"],
    ["原厂 1.6 步态（机载）", ["Loco RPC: ChangeMode / Move", "三 actor + 固件 PD"], "#9b8cff"],
    ["Forge 候选运控包", ["同一契约接入", "先过桥再上赛"], "#7cc4ff"],
  ];
  const backends: [string, string[], string, boolean][] = [
    ["SimRobot（B-Human 3D）", ["SimulatedRobot3D：同一 p/d/maxTorque", "正常相机 · 全队比赛"], "#3fbf7f", false],
    ["虚拟 K1（MuJoCo 孪生）", ["锁步：一致性 / 协议 / 差距扫描", "实时：deploy.py 原样多进程"], "#7cc4ff", false],
    ["MuJoCo Warp · Isaac Gym", ["鲁棒性图谱 · 训练与冻结评估"], "#a9b7c9", false],
    ["真机 K1", ["rt/low_state · rt/joint_ctrl（DDS）", "未授权连接 · L5 未验证"], "#ef6464", true],
  ];
  return (
    <svg viewBox="0 0 980 300" width="100%" role="img" aria-label="运控桥架构：控制器经 K1 低层契约连接各后端">
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="#3a4b63" />
        </marker>
      </defs>
      <text x={10} y={14} fill="#7488a1" fontSize="11">控制器（谁产生 LowCmd）</text>
      <text x={370} y={14} fill="#7488a1" fontSize="11">K1 公开低层契约（真机边界）</text>
      <text x={700} y={14} fill="#7488a1" fontSize="11">后端（谁执行 PD 并回报 LowState）</text>
      {controllers.map(([t, l, c], i) => <g key={t}>{box(10, 24 + i * 68, 250, 58, t, l, c)}{link(262, 53 + i * 68, 368, 150)}</g>)}
      {box(370, 60, 250, 180, "LowState / LowCmd / Loco RPC", [
        "LowState 500 Hz：rpy、gyro、acc、q/dq/τ", "LowCmd SERIAL：q, dq, τ, kp, kd, weight",
        "RPC：ChangeMode 2000 · Move 2001", "      GetMode 2017 · GetStatus 2018", "模式：阻尼 / 准备 / 行走 / Custom",
        "电机环：τ = kp(q*−q) + kd(dq*−dq) + τff", "22 关节串联顺序（契约审计）", "踝：串联域 ↔ 并联曲柄（未建模）",
      ], "#e6edf5")}
      {backends.map(([t, l, c, d], i) => <g key={t}>{link(622, 150, 718, 53 + i * 68, d)}{box(720, 24 + i * 68, 250, 58, t, l, c, d)}</g>)}
    </svg>
  );
}

// ------------------------------------------------------------------ identity XY plot
function PathPlot({ paths, keys, labels }: { paths: Paths; keys: string[]; labels: string[] }) {
  const series = keys.map((k) => paths[k]).filter(Boolean);
  if (!series.length) return <Empty>没有轨迹文件</Empty>;
  const xs = series.flatMap((s) => s.x), ys = series.flatMap((s) => s.y);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const span = Math.max(x1 - x0, y1 - y0, 0.2) * 1.1;
  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, W = 300;
  const px = (x: number) => ((x - cx) / span + 0.5) * W, py = (y: number) => (0.5 - (y - cy) / span) * W;
  const colors = ["#e6edf5", "#7cc4ff", "#e3b341"];
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${W}`} width="100%" style={{ maxWidth: 340 }} role="img" aria-label="基座平面轨迹：参考与桥接叠加">
        <rect x={0} y={0} width={W} height={W} fill="none" stroke="#263349" />
        {series.map((s, i) => (
          <polyline key={i} fill="none" stroke={colors[i % colors.length]} strokeWidth={i === 0 ? 3 : 1.4} strokeOpacity={i === 0 ? 0.35 : 1}
            points={s.x.map((x, j) => `${px(x).toFixed(1)},${py(s.y[j]).toFixed(1)}`).join(" ")} />
        ))}
        <text x={6} y={W - 6} fill="#7488a1" fontSize="10">边长 {fmt(span, 2)} m</text>
      </svg>
      <div className="legend">{labels.map((l, i) => <span key={l}><i style={{ background: colors[i % colors.length] }} />{l}</span>)}</div>
    </div>
  );
}

// ------------------------------------------------------------------ gap heatmap
function marginTone(m: Margin): string {
  if (m.status === "NOT_APPLICABLE") return "rgba(169,183,201,0.06)";
  if (m.status === "BELOW_REFERENCE" || m.status === "FAILS_AT_NOMINAL") return "rgba(239,100,100,0.20)";
  if (m.status === "INSUFFICIENT_EVIDENCE") return "rgba(227,179,65,0.18)";
  // A censored margin (no failure anywhere in the sweep) is only a lower bound: do not flag it as thin.
  if (!m.censored && (m.headroom ?? 0) < 2) return "rgba(227,179,65,0.14)";
  return "rgba(63,191,127,0.16)";
}

function GapTable({ run, onPick }: { run: BridgeRun; onPick: (c: string, a: string) => void }) {
  if (!run.gaps || !run.gap_setup) return <Empty>本次运行没有现实差距扫描</Empty>;
  const controllers = run.gap_setup.controllers;
  return (
    <div style={{ overflowX: "auto" }}>
      <table>
        <thead><tr><th>差距轴</th><th>关注值</th>{controllers.map((c) => <th key={c}>{CONTROLLER_LABEL[c] || c}</th>)}</tr></thead>
        <tbody>
          {Object.entries(run.gap_setup.axes).map(([axis, spec]) => (
            <tr key={axis}>
              <td>{spec.label} <span className="hint">({spec.unit})</span></td>
              <td className="mono">{fmt(spec.reference)}</td>
              {controllers.map((c) => {
                const m = run.gaps!.table[c]?.[axis];
                if (!m) return <td key={c}>—</td>;
                return (
                  <td key={c} className="clickable" style={{ background: marginTone(m), cursor: "pointer" }} onClick={() => onPick(c, axis)}
                    title={MARGIN_STATUS[m.status] || m.status}>
                    {m.status === "NOT_APPLICABLE" ? <span className="hint">机载·不适用</span> : (
                      <span className="mono">{m.margin === null || m.margin === undefined ? "✘" : fmt(m.margin)}{m.censored ? "+" : ""}
                        <span className="hint"> {m.first_failure !== null && m.first_failure !== undefined ? `→${fmt(m.first_failure)}` : ""}</span></span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="hint">格内：最大无失效等级（“+”表示扫描范围内未失效）→ 首个失效等级。失效 = 任一重复跌倒，或前进/转向达不到指令的 {fmt(run.gaps.stall_fraction * 100)}%。
        绿色 = 覆盖关注值且余量 ≥2 倍，或扫描范围内从未失效；黄 = 已观察到失效且余量 &lt;2 倍；红 = 低于关注值。关注值是规划假设，不是测量。差距在第 {run.gap_setup.gap_onset_s} 秒（控制器已运行）接入；{run.gap_setup.seeds} 个独立重复。</p>
    </div>
  );
}

function GapDetail({ run, controller, axis }: { run: BridgeRun; controller: string; axis: string }) {
  const m = run.gaps?.table[controller]?.[axis];
  const spec = run.gap_setup?.axes[axis];
  if (!m || !spec) return null;
  if (!m.cells) return <p className="hint">{m.reason}</p>;
  return (
    <table>
      <thead><tr><th>{spec.label}（{spec.unit}）</th><th>重复</th><th>跌倒</th><th>失速</th><th>平均前进 m/s</th><th>平均转向 rad/s</th><th>跌倒时刻 s</th></tr></thead>
      <tbody>
        {m.cells.map((c) => (
          <tr key={c.level}>
            <td className="mono">{fmt(c.level)}</td><td>{c.trials}</td>
            <td style={{ color: c.falls ? "var(--bad)" : undefined }}>{c.falls}</td>
            <td style={{ color: c.stalls ? "var(--warn)" : undefined }}>{c.stalls}</td>
            <td className="mono">{fmt(c.mean_forward_m_s)}</td><td className="mono">{fmt(c.mean_turn_rad_s)}</td>
            <td className="mono">{c.fall_times_s.join(", ") || "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ------------------------------------------------------------------ page
export function Bridge() {
  const toast = useToast();
  const runs = usePoll<RunRow[]>("/api/bridge/runs", 8000);
  const contract = usePoll<Contract>("/api/bridge/contract", 0);
  const ledger = usePoll<Ledger>("/api/bridge/lessons", 0);
  const [selected, setSelected] = useState<string | null>(null);
  const [pick, setPick] = useState<[string, string] | null>(null);
  const [seeds, setSeeds] = useState(4);
  const [session, setSession] = useState(true);
  const [busy, setBusy] = useState(false);
  const [lessonFilter, setLessonFilter] = useState<string>("all");
  useEffect(() => {
    if (!selected && runs.data?.length) setSelected(runs.data.find((r) => r.analyzed)?.id || null);
  }, [runs.data, selected]);
  const detail = usePoll<BridgeRun>(selected ? `/api/bridge/runs/${selected}` : null, 0);
  const paths = usePoll<Paths>(selected ? `/api/bridge/runs/${selected}/paths` : null, 0);
  const run = detail.data;
  const lessons = useMemo(() => (ledger.data?.lessons || []).filter((l) => lessonFilter === "all" || l.status === lessonFilter), [ledger.data, lessonFilter]);

  const start = async () => {
    setBusy(true);
    try {
      const job = await api.post<{ id: string }>("/api/jobs", { type: "bridge", params: { seeds, session, experiments: ["identity", "protocol", "gaps", "crosssim"] } });
      toast(`已提交运控桥验证作业 ${job.id}`);
    } catch (e) {
      toast(String((e as Error).message), true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="page-title">
        <h2>运控桥</h2>
        <p>sim2sim 与 sim2real 的同一条低层契约：B-Human、booster_deploy 开源运控、原厂步态在虚拟 K1 上按真机接口验证</p>
      </div>
      {(runs.error || detail.error || contract.error) && <p className="hint" role="alert">{runs.error || detail.error || contract.error}</p>}

      <Card title="桥接架构" sub="B-Human：SimulatedRobot3D ↔ BoosterProvider；Booster：MujocoController ↔ BoosterRobotPortal">
        <Architecture />
      </Card>

      <div className="grid c2">
        <Card title="结论" sub={run ? <span className="mono">{run.run_id}</span> : "尚无运行"} right={run && <V value={run.overall} />}>
          {run ? (
            <div className="stack">
              <div className="row">
                {run.crosssim_verdict && run.crosssim_verdict !== "NOT_RUN" && (
                  <span className="row" style={{ gap: 4 }}><span className="hint">跨仿真</span><V value={run.crosssim_verdict === "CONSISTENT" ? "CONSISTENT_ACROSS" : run.crosssim_verdict} /></span>
                )}
                {Object.entries(run.verdicts).map(([k, v]) => (
                  <span key={k} className="row" style={{ gap: 4 }}><span className="hint">{({ identity: "一致性", protocol: "协议", session: "实时会话", gaps: "差距扫描" } as Record<string, string>)[k] || k}</span><V value={v} /></span>
                ))}
                <span className="row" style={{ gap: 4 }}><span className="hint">真机</span><V value={run.real_robot} /></span>
              </div>
              <p className="hint">{run.scope}</p>
              {run.findings.map((f) => (
                <div key={f.id}><span className={`badge ${SEVERITY[f.severity]}`}>{f.severity}</span> {f.title}</div>
              ))}
            </div>
          ) : <Empty>还没有运控桥运行。右侧可启动。</Empty>}
        </Card>
        <Card title="运行与新建">
          <div className="stack">
            <div className="row">
              <label className="field">独立重复<select value={seeds} onChange={(e) => setSeeds(Number(e.target.value))}>{[2, 3, 4, 6, 8].map((n) => <option key={n} value={n}>{n}</option>)}</select></label>
              <label className="row" style={{ gap: 6 }}><input type="checkbox" checked={session} onChange={(e) => setSession(e.target.checked)} />包含 booster_deploy 实时会话</label>
              <button className="btn primary" disabled={busy} onClick={start}>启动验证</button>
            </div>
            <p className="hint">CPU 作业，约 1–2 分钟；不连接机器人、不使用网络。</p>
            {runs.data?.length ? (
              <table><thead><tr><th>运行</th><th>结论</th></tr></thead><tbody>
                {runs.data.map((r) => (
                  <tr key={r.id} className={`clickable ${selected === r.id ? "selected" : ""}`} onClick={() => { setSelected(r.id); setPick(null); }}>
                    <td className="mono" style={{ fontSize: 11.5 }}>{r.id}</td><td><V value={r.overall || (r.analyzed ? "" : "NOT_RUN")} /></td>
                  </tr>
                ))}
              </tbody></table>
            ) : null}
          </div>
        </Card>
      </div>

      {contract.data && (
        <Card title="K1 低层契约审计" sub={`B-Human · booster_deploy · MuJoCo 模型 · 固件 1.6 明文配置 · ${contract.data.at.slice(0, 19)}`} right={<V value={contract.data.verdict} />}>
          <div className="stack">
            <div className="row">
              {Object.entries({ ...contract.data.orders, ...contract.data.policy_orders }).map(([k, v]) => (
                <span key={k} className={`badge ${v.ok ? "ok" : "bad"}`}>{v.ok ? "✔" : "✘"} {k}</span>
              ))}
              {Object.entries(contract.data.messages).map(([k, v]) => <span key={k} className={`badge ${v.ok ? "ok" : "bad"}`}>{v.ok ? "✔" : "✘"} {k}</span>)}
            </div>
            {contract.data.findings.map((f) => (
              <div key={f.id}><span className={`badge ${SEVERITY[f.severity]}`}>{f.severity}</span> {f.title}</div>
            ))}
            <details>
              <summary className="hint">关节映射与增益表（22 关节）</summary>
              <div style={{ overflowX: "auto" }}>
                <table>
                  <thead><tr><th>#</th><th>规范名</th><th>SDK</th><th>booster_deploy</th><th>B-Human</th><th>固件限位</th><th>模型限位</th>
                    {PROFILES.map((p) => <th key={p}>{contract.data!.gain_profiles[p]?.label} p/d</th>)}</tr></thead>
                  <tbody>
                    {contract.data.joints.map((j) => {
                      const lim = contract.data!.limits[j.index];
                      const ps = PROFILES.map((p) => contract.data!.gain_profiles[p]?.gains[j.canonical] || {});
                      const ref = ps[0];
                      return (
                        <tr key={j.index}>
                          <td>{j.index}</td><td className="mono">{j.canonical}</td><td className="mono">{j.sdk}{j.parallel_in_firmware ? " ⇄" : ""}</td>
                          <td className="mono">{j.deploy}</td><td className="mono">{j.bhuman}</td>
                          <td className="mono">{fmt(lim.firmware[0])}…{fmt(lim.firmware[1])}</td>
                          <td className="mono" style={{ color: lim.sim_wider_by > 0.02 ? "var(--warn)" : undefined }}>{fmt(lim.mjcf[0])}…{fmt(lim.mjcf[1])}</td>
                          {ps.map((g, k) => (
                            <td key={k} className="mono" style={{ color: k > 0 && (g.p !== ref.p || g.d !== ref.d) ? "var(--warn)" : undefined }}>{fmt(g.p)}/{fmt(g.d)}</td>
                          ))}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="hint">⇄ = 固件并联踝曲柄在 SERIAL 域中的踝 pitch/roll。黄色 = 与 B-Human 训练增益不同 / 模型限位比固件宽。</p>
            </details>
            <details>
              <summary className="hint">决定命令语义的代码事实（{contract.data.code_facts.length}）</summary>
              <table><tbody>
                {contract.data.code_facts.map((f) => (
                  <tr key={f.id}><td>{f.present ? "✔" : "✘"}</td><td>{f.meaning}</td><td className="mono" style={{ fontSize: 11 }}>{f.source}:{f.lines.join(",")}</td></tr>
                ))}
              </tbody></table>
            </details>
          </div>
        </Card>
      )}

      {run && (
        <>
          <Card title="桥接一致性（sim2sim 自检）" sub={`各栈自己的 sim2sim 作参考；分段平均速度差 ≤ ${run.identity_tolerance.segment_velocity} 视为保真`}>
            {run.identity.length ? (
              <div className="stack" style={{ gap: 14 }}>
                <div style={{ overflowX: "auto" }}>
                <table>
                  <thead><tr><th>栈 / 变体</th><th>结论</th><th>最大位置差</th><th>分段速度差</th><th>超 1 cm 于</th></tr></thead>
                  <tbody>
                    {run.identity.map((i) => (
                      <tr key={i.stack + i.variant}>
                        <td><b>{i.stack}</b><div className="hint mono">{i.variant}</div></td><td><V value={i.verdict} /></td>
                        <td className="mono">{fmt(i.max_position_delta_m)} m</td><td className="mono">{fmt(i.max_segment_velocity_delta)}</td>
                        <td className="mono">{i.first_over_1cm_s === null ? "从未" : `${fmt(i.first_over_1cm_s)} s`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </div>
                <div className="grid c2">
                  {paths.data && <PathPlot paths={paths.data} keys={["identity-booster-reference", "identity-booster-deploy_effort_clip", "identity-booster-motor_limits"]}
                    labels={["MujocoController 参考", "真机代码·sim 钳位", "真机代码·电机上限"]} />}
                  {paths.data && <PathPlot paths={paths.data} keys={["identity-bhuman-reference", "identity-bhuman-training_velocity_filter", "identity-bhuman-raw_motor_velocity"]}
                    labels={["mujoco_walk 参考", "BoosterProvider·训练滤波", "BoosterProvider·原始速度"]} />}
                </div>
              </div>
            ) : <Empty>未运行一致性实验</Empty>}
          </Card>

          {run.crosssim && (
            <Card title="跨仿真器对照：SimRobot ↔ 虚拟 K1" sub="同一网络、同一 m/s 指令（motion-basic-v1）"
              right={<V value={run.crosssim_verdict === "CONSISTENT" ? "CONSISTENT_ACROSS" : run.crosssim_verdict} />}>
              <div className="stack">
                <div className="grid c2">
                  {Object.entries(run.crosssim.rows).map(([controller, row]) => (
                    <div key={controller} className="stack">
                      <div className="row between">
                        <b>{CONTROLLER_LABEL[controller] || controller}</b>
                        <span className="row" style={{ gap: 6 }}>
                          <span className={`badge ${row.same_weights ? "ok" : "bad"}`}>{row.same_weights ? "✔ 同一权重" : "✘ 权重不符"}</span>
                          <V value={row.verdict === "CONSISTENT" ? "CONSISTENT_ACROSS" : row.verdict} />
                        </span>
                      </div>
                      <table>
                        <thead><tr><th>窗口</th><th>SimRobot</th><th>虚拟 K1</th><th>相对差</th></tr></thead>
                        <tbody>
                          {Object.entries(row.segments || {}).map(([w, seg]) => (
                            <tr key={w}>
                              <td>{SEGMENT_LABEL[w] || w}</td><td className="mono">{fmt(seg.simrobot)}</td><td className="mono">{fmt(seg.virtual_k1)}</td>
                              <td className="mono" style={{ color: seg.agrees ? "var(--ok)" : "var(--warn)" }}>{seg.relative === null ? "—" : `${seg.relative > 0 ? "+" : ""}${fmt(seg.relative * 100, 2)}%`}</td>
                            </tr>
                          ))}
                          {row.drift && (
                            <>
                              <tr><td>前进时偏航（rad）</td><td className="mono">{fmt(row.drift.forward_window_yaw_rad?.simrobot)}</td><td className="mono">{fmt(row.drift.forward_window_yaw_rad?.virtual_k1)}</td><td /></tr>
                              <tr><td>停止漂移（m）</td><td className="mono">{fmt(row.drift.settled_stop_net_m?.simrobot)}</td><td className="mono">{fmt(row.drift.settled_stop_net_m?.virtual_k1)}</td><td /></tr>
                            </>
                          )}
                        </tbody>
                      </table>
                      <div className="hint mono" style={{ fontSize: 11 }}>{row.simrobot?.run} · {row.simrobot?.pack_id}</div>
                    </div>
                  ))}
                </div>
                <p className="hint">{run.crosssim.note} 主窗口位移差 ≤ {fmt(run.crosssim.tolerance.relative * 100)}% 或 ≤ {run.crosssim.tolerance.absolute} 视为一致。</p>
              </div>
            </Card>
          )}

          <div className="grid c2">
            <Card title="协议场景（booster_deploy 真机代码 + 原厂 RPC）" sub="锁步">
              <div className="stack">
                {run.protocol.map((s) => (
                  <details key={s.id} open={s.status !== "PASS"}>
                    <summary><span className={`badge ${s.status === "PASS" ? "ok" : "bad"}`}>{s.status}</span> {s.title}</summary>
                    <Checks checks={s.checks} />
                    {s.observed && <pre className="json mono">{JSON.stringify(s.observed, null, 1)}</pre>}
                  </details>
                ))}
              </div>
            </Card>
            <Card title="实时会话：scripts/deploy.py 原样运行" sub={run.session ? run.session.transport : "未运行"} right={run.session && <V value={run.session.status} />}>
              {run.session ? (
                <div className="stack">
                  <div className="row">
                    {Object.entries(run.session.deploy_metrics).map(([k, v]) => <span key={k} className="badge info">{k} {fmt(v.freq_hz, 4)} Hz</span>)}
                    {run.session.lowcmd_wall_period_ms && <span className="badge muted">命令周期 中位 {fmt(run.session.lowcmd_wall_period_ms.median)} / 最大 {fmt(run.session.lowcmd_wall_period_ms.max)} ms</span>}
                    {run.session.prime_to_first_policy_command_ms !== null && <span className="badge warn">预置→首个策略命令 {fmt(run.session.prime_to_first_policy_command_ms)} ms</span>}
                    {run.session.walked_m !== null && <span className="badge muted">行走 {fmt(run.session.walked_m)} m</span>}
                  </div>
                  <Checks checks={run.session.checks} />
                  <table><tbody>{run.session.timeline.map((e, i) => <tr key={i}><td className="mono">{fmt(e.t, 4)} s</td><td>{e.event}</td></tr>)}</tbody></table>
                  <details><summary className="hint">booster_deploy 控制台末尾</summary><pre className="json mono">{run.session.console_tail.join("\n")}</pre></details>
                </div>
              ) : <Empty>本次运行跳过了实时会话</Empty>}
            </Card>
          </div>

          <Card title="现实差距裕度（sim2real 接口容差）" sub={run.gap_setup ? `${run.gap_setup.jobs} 次锁步运行 · ${fmt(run.gap_setup.wall_s)} s` : ""}>
            <div className="stack">
              <GapTable run={run} onPick={(c, a) => setPick([c, a])} />
              {pick && (
                <div className="card" style={{ background: "transparent" }}>
                  <div className="row between"><b>{CONTROLLER_LABEL[pick[0]] || pick[0]} · {run.gap_setup?.axes[pick[1]]?.label}</b><button className="btn small" onClick={() => setPick(null)}>关闭</button></div>
                  <GapDetail run={run} controller={pick[0]} axis={pick[1]} />
                </div>
              )}
            </div>
          </Card>

          {run.virtual_k1 && (
            <Card title="虚拟 K1 的建模假设" sub="结论不会强于这些假设">
              <ol className="hint" style={{ margin: 0, paddingLeft: 18 }}>{run.virtual_k1.assumptions.map((a) => <li key={a}>{a}</li>)}</ol>
            </Card>
          )}
        </>
      )}

      <Card title="运控桥经验库" sub={ledger.data ? Object.entries(ledger.data.counts).map(([k, v]) => `${LESSON_STATUS[k]?.[0] || k} ${v}`).join(" · ") : ""}
        right={<select value={lessonFilter} onChange={(e) => setLessonFilter(e.target.value)}>
          <option value="all">全部</option>{Object.entries(LESSON_STATUS).map(([k, [t]]) => <option key={k} value={k}>{t}</option>)}</select>}>
        {ledger.data ? (
          <div className="stack">
            {ledger.data.problems.length > 0 && <p className="hint" style={{ color: "var(--bad)" }}>{ledger.data.problems.join("；")}</p>}
            {lessons.map((l) => (
              <details key={l.id}>
                <summary>
                  <span className={`badge ${LESSON_STATUS[l.status]?.[1] || "muted"}`}>{LESSON_STATUS[l.status]?.[0] || l.status}</span>{" "}
                  <span className="badge muted">{l.category}</span> {l.title}
                </summary>
                <div className="stack" style={{ padding: "6px 0 10px 4px" }}>
                  <div>{l.summary}</div>
                  <div><b>做法：</b>{l.action}</div>
                  <div className="hint">涉及：{l.stacks.join(" · ")} · 来源：{l.origin}</div>
                  <table><tbody>
                    {l.evidence.map((e, i) => (
                      <tr key={i}>
                        <td>{e.supported === false || e.exists === false ? "✘" : e.supported || e.exists ? "✔" : "·"}</td>
                        <td className="mono" style={{ fontSize: 11.5 }}>{e.kind}</td>
                        <td className="mono" style={{ fontSize: 11.5 }}>{e.path || e.check || [e.experiment, e.scenario].filter(Boolean).join(" / ")}{e.run_id ? ` @ ${e.run_id}` : ""}</td>
                        <td className="hint">{e.note || ""}</td>
                      </tr>
                    ))}
                  </tbody></table>
                </div>
              </details>
            ))}
          </div>
        ) : <Empty>加载中…</Empty>}
      </Card>
    </div>
  );
}
