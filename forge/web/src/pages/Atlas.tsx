import { useEffect, useMemo, useState } from "react";
import { api, Pack, short } from "../api";
import { Card, Empty, usePoll, useToast } from "../components/ui";

interface Capacity {
  margin: number; value: number; censored: boolean; at_or_below_first_level: boolean;
  ci95_margin: [number, number]; ci95_value: [number, number]; bootstrap_censored_fraction: number;
}
interface AxisResult {
  label: string; unit: string; failure_mode: string; margin_kind: string; levels: number[]; margins: number[];
  trials: number[]; failures: number[]; falls: number[]; stalls: number[]; rate: (number | null)[];
  wilson95: [number, number][]; isotonic: number[]; C10: Capacity; C50: Capacity;
  groups: Record<string, { trials: number[]; failures: number[]; isotonic: number[]; C50: Capacity & { ci95_margin?: [number, number] } }>;
  by_command: Record<string, { trials: number; C50_margin: number; C50_censored: boolean }>;
}
interface PolicyResult {
  policy: string; policy_sha256: string; axes: Record<string, AxisResult>;
  nominal_tracking_rmse: { vx: number; vy: number; wz: number; samples: number } | null;
  push_phase: { bins: number; rate: (number | null)[]; trials: number[]; window: [number, number] } | null;
  performance?: { wall_s: number; steps_per_s: number };
}
interface ComparisonAxis {
  label: string; unit: string; ratio: number | null; ci95: [number, number] | null; ci_simultaneous: [number, number] | null;
  status: string; reason: string; better: boolean; worse: boolean; candidate_C50: Capacity; baseline_C50: Capacity;
}
interface Comparison {
  candidate: string; baseline: string; verdict: string; axes: Record<string, ComparisonAxis>;
  better_axes: string[]; worse_axes: string[]; failed_axes: string[]; simultaneous_alpha: number;
}
interface AtlasRun {
  run: string; worlds: number; axes: string[]; seed: number; at: string; raw_sha256: string; evaluator_sha256: string;
  analysis_sha256: string; engine: Record<string, any>; timeline: Record<string, number>;
  bootstrap: { resamples: number; seed: number }; rules: Record<string, any>;
  policies: Record<string, PolicyResult>; comparisons: Comparison[];
}
interface RunRow { id: string; analyzed: boolean; policies?: string[]; worlds?: number; verdicts?: Record<string, string>; at?: string }

const COLORS = ["#7cc4ff", "#3fbf7f", "#e3b341", "#ef6464", "#9b8cff", "#ff8fd6"];
const STATUS_TEXT: Record<string, string> = { PASS: "非劣效", FAIL: "劣于基线", INSUFFICIENT: "证据不足" };
const STATUS_CLASS: Record<string, string> = { PASS: "ok", FAIL: "bad", INSUFFICIENT: "warn" };
const WALK_CONTRACT = "k1.walk.344x13";

function fmt(v: number | null | undefined, digits = 3) {
  if (v === null || v === undefined || !isFinite(v)) return "—";
  return Number(v.toPrecision(digits)).toString();
}

function capacityText(c: Capacity, unit: string) {
  if (c.censored) return `超出扫描范围 (≥${fmt(c.value)} ${unit})`;
  const [lo, hi] = c.ci95_value;
  return `${fmt(c.value)} ${unit} [${fmt(lo)}, ${fmt(hi)}]`;
}

// ------------------------------------------------------------------ charts
function Radar({ data, labels, axes, baseline }: { data: AtlasRun; labels: string[]; axes: string[]; baseline: string }) {
  const size = 360, cx = size / 2, cy = size / 2 + 6, R = 130;
  const ratios = labels.map((label) => axes.map((axis) => {
    const b = data.policies[baseline].axes[axis].C50.margin;
    const c = data.policies[label].axes[axis].C50.margin;
    return b > 0 ? c / b : 1;
  }));
  const top = Math.max(1.3, ...ratios.flat().filter(isFinite)) * 1.02;
  const point = (i: number, r: number) => {
    const angle = -Math.PI / 2 + (2 * Math.PI * i) / axes.length;
    const radius = (Math.min(r, top) / top) * R;
    return [cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)];
  };
  const ring = (r: number) => axes.map((_, i) => point(i, r).map((v) => v.toFixed(1)).join(",")).join(" ");
  return (
    <svg viewBox={`0 0 ${size} ${size + 10}`} width="100%" role="img" aria-label="各维度承受极限（相对基线）">
      {[0.5, 1.5].filter((r) => r < top).map((r) => <polygon key={r} points={ring(r)} fill="none" stroke="#263349" />)}
      <polygon points={ring(0.9)} fill="none" stroke="#e3b341" strokeDasharray="4 4" strokeOpacity={0.7} />
      <polygon points={ring(1.0)} fill="rgba(124,196,255,0.06)" stroke="#7488a1" />
      {axes.map((axis, i) => {
        const [x, y] = point(i, top);
        const [lx, ly] = point(i, top * 1.13);
        return (
          <g key={axis}>
            <line x1={cx} y1={cy} x2={x} y2={y} stroke="#263349" />
            <text x={lx} y={ly} fill="#a9b7c9" fontSize="10.5" textAnchor="middle" dominantBaseline="middle">
              {data.policies[baseline].axes[axis].label}
            </text>
          </g>
        );
      })}
      {labels.map((label, k) => label === baseline ? null : (
        <polygon key={label} points={ratios[k].map((r, i) => point(i, r).map((v) => v.toFixed(1)).join(",")).join(" ")}
          fill={COLORS[k % COLORS.length]} fillOpacity={0.12} stroke={COLORS[k % COLORS.length]} strokeWidth={1.8} />
      ))}
      <text x={8} y={size + 4} fill="#7488a1" fontSize="10">灰线 = 基线 1.0 · 黄虚线 = 非劣效界 0.9 · 半径 = C50 承受极限 / 基线</text>
    </svg>
  );
}

function PushPolar({ data, labels }: { data: AtlasRun; labels: string[] }) {
  const size = 340, cx = size / 2, cy = size / 2, R = 128;
  const groups = Object.keys(data.policies[labels[0]].axes.push?.groups || {});
  if (!groups.length) return <Empty>本次图谱未包含推搡维度</Empty>;
  const values = labels.map((label) => groups.map((g) => data.policies[label].axes.push.groups[g].C50.margin));
  const top = Math.max(...values.flat()) * 1.1;
  const point = (i: number, v: number) => {
    // 0° = push from behind (forward); counter-clockwise = towards the robot's left, drawn with forward up.
    const angle = -Math.PI / 2 - (2 * Math.PI * i) / groups.length;
    return [cx + (v / top) * R * Math.cos(angle), cy + (v / top) * R * Math.sin(angle)];
  };
  return (
    <svg viewBox={`0 0 ${size} ${size}`} width="100%" role="img" aria-label="推搡方向与承受冲量">
      {[0.25, 0.5, 0.75, 1].map((f) => <circle key={f} cx={cx} cy={cy} r={R * f} fill="none" stroke="#263349" />)}
      {[0.5, 1].map((f) => <text key={f} x={cx + 3} y={cy - R * f + 11} fill="#7488a1" fontSize="9.5">{fmt(top * f, 2)} N·s</text>)}
      {groups.map((g, i) => {
        const [x, y] = point(i, top);
        const [lx, ly] = point(i, top * 1.09);
        const word = ({ "0°": "前推", "90°": "左推", "180°": "后推", "270°": "右推" } as Record<string, string>)[g];
        return <g key={g}><line x1={cx} y1={cy} x2={x} y2={y} stroke="#1c2737" /><text x={lx} y={ly} fill={word ? "#e6edf5" : "#a9b7c9"} fontSize="9.5" textAnchor="middle" dominantBaseline="middle">{word || g}</text></g>;
      })}
      <text x={cx} y={14} fill="#7488a1" fontSize="10" textAnchor="middle">↑ 推向前方（机器人朝向）</text>
      {labels.map((label, k) => (
        <polygon key={label} points={values[k].map((v, i) => point(i, v).map((p) => p.toFixed(1)).join(",")).join(" ")}
          fill="none" stroke={COLORS[k % COLORS.length]} strokeWidth={1.8} />
      ))}
    </svg>
  );
}

function FragilityCurve({ data, labels, axis }: { data: AtlasRun; labels: string[]; axis: string }) {
  const W = 620, H = 262, P = { l: 44, r: 14, t: 24, b: 30 };
  const spec = data.policies[labels[0]].axes[axis];
  const margins = spec.margins;
  const x0 = Math.min(...margins), x1 = Math.max(...margins);
  const sx = (m: number) => P.l + ((m - x0) / Math.max(1e-9, x1 - x0)) * (W - P.l - P.r);
  const sy = (p: number) => P.t + (1 - p) * (H - P.t - P.b);
  const tickIdx = spec.levels.map((_, i) => i).filter((i) => i % Math.ceil(spec.levels.length / 8) === 0 || i === spec.levels.length - 1);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`${spec.label} 易损性曲线`}>
      {[0, 0.1, 0.5, 1].map((p) => (
        <g key={p}>
          <line x1={P.l} x2={W - P.r} y1={sy(p)} y2={sy(p)} stroke={p === 0.5 || p === 0.1 ? "#33435e" : "#263349"} strokeDasharray="3 4" />
          <text x={P.l - 6} y={sy(p) + 4} fill="#7488a1" fontSize="10" textAnchor="end">{Math.round(p * 100)}%</text>
        </g>
      ))}
      {tickIdx.map((i) => (
        <text key={i} x={sx(margins[i])} y={H - 12} fill="#7488a1" fontSize="10" textAnchor="middle">{fmt(spec.levels[i], 3)}</text>
      ))}
      <text x={W - P.r} y={12} fill="#7488a1" fontSize="10" textAnchor="end">
        {spec.label}（{spec.unit}）→ 更严苛 · 失效 = {spec.failure_mode === "functional" ? "跌倒或走不动" : "跌倒"}
      </text>
      {labels.map((label, k) => {
        const a = data.policies[label].axes[axis];
        const color = COLORS[k % COLORS.length];
        const steps = a.isotonic.map((p, i) => `${sx(margins[i]).toFixed(1)},${sy(p).toFixed(1)}`).join(" ");
        return (
          <g key={label}>
            {a.rate.map((r, i) => r === null ? null : (
              <g key={i}>
                <line x1={sx(margins[i]) + k * 2} x2={sx(margins[i]) + k * 2} y1={sy(a.wilson95[i][0])} y2={sy(a.wilson95[i][1])} stroke={color} strokeOpacity={0.35} />
                <circle cx={sx(margins[i]) + k * 2} cy={sy(r)} r={2.4} fill={color} />
              </g>
            ))}
            <polyline points={steps} fill="none" stroke={color} strokeWidth={1.6} />
            {!a.C50.censored && <line x1={sx(a.C50.margin)} x2={sx(a.C50.margin)} y1={sy(0.5) - 8} y2={H - P.b} stroke={color} strokeDasharray="2 3" />}
          </g>
        );
      })}
    </svg>
  );
}

// ------------------------------------------------------------------ page
export function Atlas({ go }: { go: (page: string) => void }) {
  const toast = useToast();
  const runs = usePoll<RunRow[]>("/api/atlas", 8000);
  const packs = usePoll<Pack[]>("/api/packs", 20000);
  const [selected, setSelected] = useState<string | null>(null);
  const detail = usePoll<AtlasRun>(selected ? `/api/atlas/${selected}` : null, 0);
  const [axis, setAxis] = useState("friction");
  const [chosen, setChosen] = useState<string[]>([]);
  const [scale, setScale] = useState(1);
  const [busy, setBusy] = useState(false);

  const analyzed = (runs.data || []).filter((r) => r.analyzed);
  useEffect(() => { if (!selected && analyzed.length) setSelected(analyzed[0].id); }, [analyzed.length, selected]);
  const data = detail.data;
  const labels = data ? Object.keys(data.policies) : [];
  const baseline = data?.comparisons[0]?.baseline || labels[0];
  const walkPacks = useMemo(() => (packs.data || []).filter((p) => p.components?.walk?.contract === WALK_CONTRACT && p.kind !== "baseline"), [packs.data]);

  const start = async () => {
    if (!chosen.length) { toast("至少选择一个候选运控包", true); return; }
    setBusy(true);
    try {
      const job = await api.post<{ id: string }>("/api/jobs", { type: "atlas", params: { packs: chosen, replica_scale: scale } });
      toast(`图谱作业已排队：${job.id}（与官方在同一世界表上配对评测）`);
      go("jobs");
    } catch (e: any) { toast(e.message, true); } finally { setBusy(false); }
  };

  return <>
    <div className="page-title">
      <h2>鲁棒性图谱</h2>
      <p>MuJoCo Warp 上千并行世界，把每种扰动推过失效区，拟合“失效概率–强度”曲线，给出带置信区间的承受极限（C50），候选与官方在同一世界表上配对比较。</p>
    </div>
    {(runs.error || detail.error) && <p className="hint" role="alert">{runs.error || detail.error}</p>}
    <div className="grid c2">
      <Card title="新建图谱" sub="B-Human 344→13 行走契约；官方基线自动加入">
        <div className="stack">
          <div className="row">
            {walkPacks.map((p) => (
              <label key={p.id} className="row" style={{ gap: 6 }}>
                <input type="checkbox" checked={chosen.includes(p.id)}
                  onChange={(e) => setChosen(e.target.checked ? [...chosen, p.id] : chosen.filter((x) => x !== p.id))} />
                <span className="mono" style={{ fontSize: 12 }}>{p.name}</span>
              </label>
            ))}
            {!walkPacks.length && <span className="hint">没有可评测的 walk 契约候选包</span>}
          </div>
          <div className="row">
            <label className="field">重复倍数<select value={scale} onChange={(e) => setScale(Number(e.target.value))}>
              {[0.5, 1, 2].map((v) => <option key={v} value={v}>{v}×（约 {Math.round(13824 * v / 1000)}k 世界/策略）</option>)}
            </select></label>
            <button className="btn primary" disabled={busy} onClick={start}>开始扫描</button>
          </div>
          <p className="hint">每个策略约 50 秒（RTX 5090，1.9M 物理步/秒）。同一次运行内所有策略共享扰动、指令、推搡时刻与初始噪声。</p>
        </div>
      </Card>
      <Card title="历史图谱">
        {!analyzed.length ? <Empty>尚无图谱（CLI：forge atlas run PACK）</Empty> : (
          <table><thead><tr><th>运行</th><th>策略</th><th>结论</th></tr></thead><tbody>
            {analyzed.slice(0, 8).map((r) => (
              <tr key={r.id} className={`clickable ${selected === r.id ? "selected" : ""}`} onClick={() => setSelected(r.id)}>
                <td className="mono" style={{ fontSize: 11.5 }}>{r.id}</td>
                <td>{r.policies?.length ?? "—"} · {r.worlds} 世界</td>
                <td>{Object.entries(r.verdicts || {}).map(([k, v]) => (
                  <div key={k}><span className={`badge ${STATUS_CLASS[v] || "muted"}`}>{STATUS_TEXT[v] || v}</span> <span className="hint">{k.split("|")[0].slice(0, 26)}</span></div>
                ))}</td>
              </tr>
            ))}
          </tbody></table>
        )}
      </Card>
    </div>
    {data && <>
      <div className="grid c3">
        {data.comparisons.map((c) => (
          <Card key={c.candidate} title={<span className="mono" style={{ fontSize: 13 }}>{c.candidate}</span>} sub={`vs ${c.baseline}`}
            right={<span className={`badge ${STATUS_CLASS[c.verdict]}`}>{STATUS_TEXT[c.verdict] || c.verdict}</span>}>
            <div className="stack">
              <div>更强（同时区间）：{c.better_axes.length ? c.better_axes.map((a) => data.policies[c.baseline].axes[a].label).join("、") : "无"}</div>
              <div>更弱（同时区间）：{c.worse_axes.length ? c.worse_axes.map((a) => data.policies[c.baseline].axes[a].label).join("、") : "无"}</div>
              <div className="hint">判定未通过的维度：{c.failed_axes.length ? c.failed_axes.map((a) => data.policies[c.baseline].axes[a].label).join("、") : "无"}</div>
            </div>
          </Card>
        ))}
      </div>
      <div className="grid c2">
        <Card title="承受极限雷达" sub="C50 / 官方">
          <Radar data={data} labels={labels} axes={data.axes} baseline={baseline} />
          <div className="legend">
            <span><i style={{ background: "#7488a1" }} />{baseline}（基线 = 1.0）</span>
            {labels.map((l, k) => l === baseline ? null : <span key={l}><i style={{ background: COLORS[k % COLORS.length] }} />{l}</span>)}
          </div>
        </Card>
        <Card title="推搡方向图" sub="各方向 50% 跌倒冲量（N·s）">
          <PushPolar data={data} labels={labels} />
          <div className="legend">{labels.map((l, k) => <span key={l}><i style={{ background: COLORS[k % COLORS.length] }} />{l}</span>)}</div>
        </Card>
      </div>
      <Card title="易损性曲线" sub="点 = 实测失效率（Wilson 95%），折线 = 单调拟合，虚线 = C50"
        right={<select value={axis} onChange={(e) => setAxis(e.target.value)}>
          {data.axes.map((a) => <option key={a} value={a}>{data.policies[baseline].axes[a].label}</option>)}
        </select>}>
        {data.axes.includes(axis) ? <FragilityCurve data={data} labels={labels} axis={axis} /> : <Empty>选择一个维度</Empty>}
        <p className="hint">{data.policies[baseline].axes[axis]?.failure_mode === "functional"
          ? "此维度把“走不动”（指令方向进度不足 50%）也计为失效；站立指令只计跌倒。"
          : "此维度只计跌倒（躯干高度 < 0.30 m 或倾角 > 1 rad）。"}</p>
      </Card>
      <Card title="逐维判定" sub={`非劣效界 0.90 · 95% 配对自助区间（${data.bootstrap.resamples} 次）`}>
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead><tr><th>维度</th><th>基线 C50 [95%]</th>
              {data.comparisons.map((c) => <th key={c.candidate}>{c.candidate.slice(0, 28)}</th>)}</tr></thead>
            <tbody>
              {data.axes.map((a) => {
                const b = data.policies[baseline].axes[a];
                return (
                  <tr key={a}>
                    <td>{b.label}<div className="hint">{b.failure_mode === "functional" ? "跌倒或走不动" : "跌倒"}</div></td>
                    <td className="mono" style={{ fontSize: 12 }}>{capacityText(b.C50, b.unit)}</td>
                    {data.comparisons.map((c) => {
                      const row = c.axes[a];
                      return (
                        <td key={c.candidate} title={row.reason}>
                          <span className={`badge ${STATUS_CLASS[row.status]}`}>{STATUS_TEXT[row.status]}</span>{" "}
                          <span className="mono" style={{ fontSize: 12 }}>×{fmt(row.ratio)} {row.ci95 ? `[${fmt(row.ci95[0])}, ${fmt(row.ci95[1])}]` : ""}</span>
                          {row.better && <span className="badge ok" style={{ marginLeft: 4 }}>更强</span>}
                          {row.worse && <span className="badge bad" style={{ marginLeft: 4 }}>更弱</span>}
                          <div className="hint mono">{capacityText(row.candidate_C50, b.unit)}</div>
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
      <div className="grid c2">
        <Card title="名义跟踪误差" sub="各维度强度 0 的世界，固定指令组合">
          <table><thead><tr><th>策略</th><th className="num">vx RMSE</th><th className="num">vy RMSE</th><th className="num">wz RMSE</th><th className="num">样本</th></tr></thead>
            <tbody>{labels.map((l) => {
              const t = data.policies[l].nominal_tracking_rmse;
              return <tr key={l}><td className="mono" style={{ fontSize: 12 }}>{l}</td>
                <td className="num">{fmt(t?.vx)}</td><td className="num">{fmt(t?.vy)}</td><td className="num">{fmt(t?.wz)}</td><td className="num">{t?.samples ?? "—"}</td></tr>;
            })}</tbody></table>
        </Card>
        <Card title="证据身份">
          <div className="stack mono" style={{ fontSize: 12 }}>
            <div>世界数 {data.worlds} · 种子 {data.seed} · 每世界 {data.timeline.seconds} s</div>
            <div>raw {short(data.raw_sha256, 16)} · 引擎 {short(data.evaluator_sha256, 16)} · 分析 {short(data.analysis_sha256, 16)}</div>
            <div>MuJoCo {data.engine?.mujoco} · MJWarp {data.engine?.mujoco_warp} · {data.engine?.device}</div>
            {labels.map((l) => <div key={l}>{l}: {short(data.policies[l].policy_sha256, 16)}</div>)}
            <div className="hint">MuJoCo 仿真结论，不代表 SimRobot 比赛或真机；GPU 物理在多次运行之间不是逐位确定，结论来自统计区间。</div>
          </div>
        </Card>
      </div>
    </>}
  </>;
}
