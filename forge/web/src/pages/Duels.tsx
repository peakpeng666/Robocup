import { useEffect, useState } from "react";
import { api, Pack } from "../api";
import { Card, Empty, usePoll, useToast } from "../components/ui";

interface DuelRow {
  id: string; status: string; decision: string; kind: string; candidate: string; baseline: string;
  pairs: number; max_pairs: number; record?: { win: number; draw: number; loss: number }; goal_cs: [number | null, number | null];
}
interface Sequence { lower: number; upper: number; trajectory: [number, number][]; mean: number | null }
interface MatchRow {
  pair: number; candidate_team: number; kickoff_team: number; run: string; valid: boolean; invalid_reason?: string;
  candidate_goals: number; baseline_goals: number; territory_m: number | null; candidate_falls: number; baseline_falls: number;
}
interface Duel {
  id: string; status: string; decision: string; started_at: string; error?: string;
  plan: { kind: string; candidate: string; baseline: string; max_pairs: number; seconds: number; alpha: number; delta_goals: number;
          goal_clip: number; design: string; endpoints: Record<string, string> };
  matches: MatchRow[];
  summary: { pairs: { pair: number; goal_difference: number; territory_m: number; kickoff_team: number }[]; pairs_complete: number;
             matches_invalid: number; record: { win: number; draw: number; loss: number }; goals: { candidate: number; baseline: number };
             goal_difference_cs: Sequence & { clip: number; method: string }; territory_cs: Sequence & { note: string } };
}
interface StrategyProfile { id: string; name: string; kind: string }

const DECISION: Record<string, [string, string]> = {
  STRONGER: ["ok", "候选更强"], WEAKER: ["bad", "候选更弱"], EQUIVALENT: ["info", "等效（±δ 内）"],
  CONTINUE: ["muted", "继续收集"], INCONCLUSIVE: ["warn", "达上限仍无结论"],
};

function SequenceChart({ seq, points, delta, unit, bound }: { seq: Sequence; points: number[]; delta?: number; unit: string; bound: number }) {
  const W = 600, H = 220, P = { l: 46, r: 12, t: 12, b: 26 };
  const n = Math.max(seq.trajectory.length, 1);
  const ys = [...points, ...seq.trajectory.flat(), 0].filter((v) => isFinite(v));
  const top = Math.min(bound, Math.max(1, ...ys.map(Math.abs)) * 1.1);
  const sx = (i: number) => P.l + (n === 1 ? 0.5 : i / (n - 1)) * (W - P.l - P.r);
  const sy = (v: number) => P.t + (1 - (Math.max(-top, Math.min(top, v)) + top) / (2 * top)) * (H - P.t - P.b);
  const upper = seq.trajectory.map(([, hi], i) => `${sx(i).toFixed(1)},${sy(hi).toFixed(1)}`);
  const lower = seq.trajectory.map(([lo], i) => `${sx(i).toFixed(1)},${sy(lo).toFixed(1)}`).reverse();
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="置信序列">
      {[-top, -top / 2, 0, top / 2, top].map((v) => (
        <g key={v}>
          <line x1={P.l} x2={W - P.r} y1={sy(v)} y2={sy(v)} stroke={v === 0 ? "#7488a1" : "#263349"} strokeDasharray={v === 0 ? "" : "3 4"} />
          <text x={P.l - 6} y={sy(v) + 4} fill="#7488a1" fontSize="10" textAnchor="end">{Number(v.toFixed(2))}</text>
        </g>
      ))}
      {delta !== undefined && [delta, -delta].map((d) => <line key={d} x1={P.l} x2={W - P.r} y1={sy(d)} y2={sy(d)} stroke="#9b8cff" strokeDasharray="5 4" strokeOpacity={0.7} />)}
      {seq.trajectory.length > 0 && <polygon points={[...upper, ...lower].join(" ")} fill="rgba(124,196,255,0.16)" stroke="#7cc4ff" strokeWidth={1.2} />}
      {points.map((v, i) => <circle key={i} cx={sx(i)} cy={sy(v)} r={3.2} fill={v > 0 ? "#3fbf7f" : v < 0 ? "#ef6464" : "#e3b341"} />)}
      {seq.trajectory.map((_, i) => (i % Math.ceil(n / 10) === 0 || i === n - 1) && (
        <text key={i} x={sx(i)} y={H - 8} fill="#7488a1" fontSize="10" textAnchor="middle">{i + 1}</text>
      ))}
      <text x={W - P.r} y={H - 8} fill="#7488a1" fontSize="10" textAnchor="end">完成对数 · {unit}</text>
    </svg>
  );
}

export function Duels({ go }: { go: (page: string) => void }) {
  const toast = useToast();
  const rows = usePoll<DuelRow[]>("/api/duels", 5000);
  const packs = usePoll<Pack[]>("/api/packs", 20000);
  const strategies = usePoll<{ profiles: StrategyProfile[] }>("/api/strategies", 20000);
  const [selected, setSelected] = useState<string | null>(null);
  const detail = usePoll<Duel>(selected ? `/api/duels/${selected}` : null, 5000);
  const [kind, setKind] = useState("motion");
  const [candidate, setCandidate] = useState("");
  const [maxPairs, setMaxPairs] = useState(10);
  const [seconds, setSeconds] = useState(120);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (!selected && rows.data?.length) setSelected(rows.data[0].id); }, [rows.data, selected]);
  useEffect(() => { setCandidate(""); }, [kind]);
  const options = kind === "motion"
    ? (packs.data || []).filter((p) => p.kind !== "baseline" && !p.provenance?.composition).map((p) => [p.id, p.name])
    : (strategies.data?.profiles || []).filter((p) => p.kind !== "baseline" && p.kind !== "invalid").map((p) => [p.id, p.name]);

  const start = async (params: Record<string, unknown>) => {
    setBusy(true);
    try {
      const job = await api.post<{ id: string }>("/api/jobs", { type: "duel", params });
      toast(`对决作业已排队：${job.id}`);
      go("jobs");
    } catch (e: any) { toast(e.message, true); } finally { setBusy(false); }
  };
  const d = detail.data?.id === selected ? detail.data : null;
  const decision = d ? DECISION[d.decision] || ["muted", d.decision] : null;

  return <>
    <div className="page-title">
      <h2>序贯对决</h2>
      <p>换边配对比赛，随时有效置信序列：证据足够即停，中断后可续跑，误判率仍受控。代替“两场定胜负”。</p>
    </div>
    {(rows.error || detail.error) && <p className="hint" role="alert">{rows.error || detail.error}</p>}
    <div className="grid c2">
      <Card title="新建对决" sub="SimRobot 3v3 · 正常渲染相机 · 独立 arena">
        <div className="row" style={{ marginBottom: 10 }}>
          <button className={`btn ${kind === "motion" ? "primary" : ""}`} onClick={() => setKind("motion")}>运控包对决</button>
          <button className={`btn ${kind === "strategy" ? "primary" : ""}`} onClick={() => setKind("strategy")}>策略对决</button>
        </div>
        <div className="form">
          <label className="field">候选<select value={candidate} onChange={(e) => setCandidate(e.target.value)}>
            <option value="">选择…</option>
            {options.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select></label>
          <label className="field">最多对数<input type="number" min={1} max={60} value={maxPairs} onChange={(e) => setMaxPairs(Number(e.target.value))} /></label>
          <label className="field">每场秒数<input type="number" min={60} max={300} value={seconds} onChange={(e) => setSeconds(Number(e.target.value))} /></label>
          <button className="btn primary" disabled={busy || !candidate} onClick={() => start({ kind, candidate, max_pairs: maxPairs, seconds })}>开始对决</button>
        </div>
        <p className="hint">基线自动为官方{kind === "motion" ? "运控包（双方官方策略）" : "策略（双方同一运控包）"}。每对约 3 分钟；主指标为每对净胜球，控球区域只作辅助报告。</p>
      </Card>
      <Card title="对决记录">
        {!rows.data?.length ? <Empty>尚无对决（CLI：forge duel motion PACK）</Empty> : (
          <table><thead><tr><th>对决</th><th>进度</th><th>战绩</th><th>结论</th></tr></thead><tbody>
            {rows.data.slice(0, 10).map((r) => {
              const [cls, text] = DECISION[r.decision] || ["muted", r.decision];
              return (
                <tr key={r.id} className={`clickable ${selected === r.id ? "selected" : ""}`} onClick={() => setSelected(r.id)}>
                  <td className="mono" style={{ fontSize: 11.5 }}>{r.candidate}<div className="hint">{r.kind} · {r.status}</div></td>
                  <td>{r.pairs}/{r.max_pairs} 对</td>
                  <td>{r.record ? `${r.record.win}胜 ${r.record.draw}平 ${r.record.loss}负` : "—"}</td>
                  <td><span className={`badge ${cls}`}>{text}</span></td>
                </tr>
              );
            })}
          </tbody></table>
        )}
      </Card>
    </div>
    {d && <>
      <Card title={<span className="mono" style={{ fontSize: 14 }}>{d.plan.candidate}</span>} sub={`vs ${d.plan.baseline} · ${d.status}`}
        right={<div className="row">
          {decision && <span className={`badge ${decision[0]}`}>{decision[1]}</span>}
          {(d.status !== "RUNNING") && <button className="btn small" disabled={busy}
            onClick={() => start({ resume: d.id, extra_pairs: d.decision === "INCONCLUSIVE" ? 5 : 0 })}>
            {d.decision === "INCONCLUSIVE" ? "追加 5 对" : "续跑"}</button>}
        </div>}>
        <div className="grid c4">
          <div><div className="hint">完成对数</div><div className="kpi">{d.summary.pairs_complete}<small>/ {d.plan.max_pairs}</small></div></div>
          <div><div className="hint">逐场战绩（候选）</div><div className="kpi">{d.summary.record.win}-{d.summary.record.draw}-{d.summary.record.loss}</div></div>
          <div><div className="hint">总进球</div><div className="kpi">{d.summary.goals.candidate}:{d.summary.goals.baseline}</div></div>
          <div><div className="hint">每对净胜球 {Math.round((1 - d.plan.alpha) * 100)}% 置信序列</div>
            <div className="kpi" style={{ fontSize: 20 }}>[{d.summary.goal_difference_cs.lower.toFixed(2)}, {d.summary.goal_difference_cs.upper.toFixed(2)}]</div></div>
        </div>
        {d.error && <p className="hint" role="alert">错误：{d.error}</p>}
        <p className="hint">{d.plan.design}；等效界 δ = ±{d.plan.delta_goals} 球/对；净胜球截断 ±{d.plan.goal_clip}。{d.summary.goal_difference_cs.method}</p>
      </Card>
      <div className="grid c2">
        <Card title="主指标：每对净胜球" sub="蓝带 = 置信序列，紫虚线 = 等效界">
          <SequenceChart seq={d.summary.goal_difference_cs} points={d.summary.pairs.map((p) => p.goal_difference)} delta={d.plan.delta_goals} unit="球/对" bound={d.plan.goal_clip} />
        </Card>
        <Card title="辅助指标：控球区域" sub="球沿候选进攻方向的平均位置（m），不参与判定">
          <SequenceChart seq={d.summary.territory_cs} points={d.summary.pairs.map((p) => p.territory_m)} unit="米" bound={4} />
        </Card>
      </div>
      <Card title="逐场明细">
        {!d.matches.length ? <Empty>尚未完成比赛</Empty> : (
          <table><thead><tr><th>对</th><th>候选队</th><th>开球</th><th className="num">比分（候选:基线）</th><th className="num">控球区域 m</th><th className="num">跌倒（候选/基线）</th><th>有效</th><th>比赛</th></tr></thead>
            <tbody>{d.matches.map((m, i) => (
              <tr key={i}>
                <td>{m.pair + 1}</td><td>T{m.candidate_team}</td><td>T{m.kickoff_team}</td>
                <td className="num">{m.candidate_goals}:{m.baseline_goals}</td>
                <td className="num">{m.territory_m === null ? "—" : m.territory_m.toFixed(2)}</td>
                <td className="num">{m.candidate_falls}/{m.baseline_falls}</td>
                <td>{m.valid ? <span className="badge ok">有效</span> : <span className="badge bad" title={m.invalid_reason}>无效</span>}</td>
                <td className="mono" style={{ fontSize: 11 }}>{m.run.split("/").slice(-1)[0]}</td>
              </tr>
            ))}</tbody></table>
        )}
      </Card>
    </>}
  </>;
}
