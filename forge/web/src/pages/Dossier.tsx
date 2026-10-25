import { useEffect, useState } from "react";
import { short } from "../api";
import { Badge, Card, Empty, usePoll } from "../components/ui";

interface Row {
  id: string; name: string; kind: string; status: string; evidence: Record<string, number>; total: number;
  gate: string | null; atlas: string | null; duel: string | null;
}
interface Stage { stage: string; id: string; path: string | null; status: string; detail: Record<string, any> }
interface Evidence { kind: string; path: string; id: string; at: string; packs: string[]; status?: string; summary: Record<string, any> }
interface Dossier {
  pack: { id: string; name: string; kind: string; status: string; description: string };
  walk_sha256: string | null; hash_aliases: string[]; lineage: Stage[]; evidence: Record<string, Evidence[]>;
  counts: Record<string, number>; scorecard: Record<string, any>; missing: string[]; note: string; built_at: string;
}

const KIND: Record<string, string> = {
  isaac_eval: "Isaac Gym 评估", mujoco_stress: "MuJoCo 压力评测", atlas: "易损性图谱", simrobot_match: "SimRobot 比赛",
  simrobot_motion: "SimRobot 固定指令", simrobot_recovery: "SimRobot 跌倒恢复", series: "系列赛", duel: "序贯对决",
  validation: "SimRobot 验证", gate: "晋级门", pipeline: "候选全流程",
};
const VERDICT_CLASS: Record<string, string> = {
  PASS: "ok", FAIL: "bad", INSUFFICIENT: "warn", SIM_QUALIFIED: "ok", NOT_QUALIFIED: "bad", INSUFFICIENT_EVIDENCE: "warn",
  STRONGER: "ok", WEAKER: "bad", EQUIVALENT: "info", CONTINUE: "muted", INCONCLUSIVE: "warn",
};

function Verdict({ value }: { value?: string | null }) {
  if (!value) return <span className="hint">—</span>;
  return <span className={`badge ${VERDICT_CLASS[value] || "muted"}`}>{value}</span>;
}

function summaryText(row: Evidence): string {
  const s = row.summary || {};
  switch (row.kind) {
    case "isaac_eval": return s.rmse_vx_vy_wz_moving ? `运动段 RMSE ${s.rmse_vx_vy_wz_moving.map((v: number) => v.toFixed(3)).join(" / ")} · 复位 ${s.resets}` : "—";
    case "mujoco_stress": return `${s.worlds} 世界 · 推力≤${s.push_force_max_N} N · 跌倒率 ${(s.fall_rate ?? 0).toFixed(4)} · RMSE ${s.tracking_rmse ? ["vx", "vy", "wz"].map((k) => s.tracking_rmse[k].toFixed(3)).join("/") : "—"}`;
    case "atlas": return Object.entries(s.comparisons || {}).map(([k, v]: [string, any]) => `${k.slice(0, 22)}: ${v.verdict}`).join(" · ") || "基线";
    case "simrobot_match": return `比分 ${s.score ? Object.entries(s.score).map(([t, g]) => `T${t}:${g}`).join(" ") : "—"} · 恢复 ${s.recovery || "—"}`;
    case "simrobot_motion": case "simrobot_recovery": return `${s.case || ""} · 恢复 ${s.recovery || "—"}`;
    case "series": return s.record ? JSON.stringify(s.record) : "—";
    case "duel": return `${s.kind} · ${s.pairs ?? 0} 对 · ${s.decision} · CS [${(s.goal_cs || []).map((v: number | null) => v === null ? "—" : v.toFixed(2)).join(", ")}]`;
    case "validation": return `${s.mode} · ${s.verdict}`;
    case "gate": return `${s.rule_version} · ${Object.entries(s.gates || {}).map(([k, v]) => `${k.split("_")[0]}:${v}`).join(" ")}`;
    case "pipeline": return Object.entries(s.steps || {}).map(([k, v]) => `${k}:${v}`).join(" · ");
    default: return "";
  }
}

export function DossierPage() {
  const rows = usePoll<Row[]>("/api/dossiers", 15000);
  const [selected, setSelected] = useState<string | null>(null);
  const detail = usePoll<Dossier>(selected ? `/api/dossiers/${selected}` : null, 15000);
  useEffect(() => {
    if (!selected && rows.data?.length) setSelected((rows.data.find((r) => r.kind !== "baseline" && r.total > 0) || rows.data[0]).id);
  }, [rows.data, selected]);
  const d = detail.data?.pack.id === selected ? detail.data : null;

  return <>
    <div className="page-title">
      <h2>证据档案</h2>
      <p>每个运控包一份只读档案：从训练、检查点、导出到各引擎评测、比赛、对决与晋级；指出还缺哪些证据。</p>
    </div>
    {(rows.error || detail.error) && <p className="hint" role="alert">{rows.error || detail.error}</p>}
    <Card title="运控包证据总览">
      {!rows.data?.length ? <Empty>没有运控包</Empty> : (
        <div style={{ overflowX: "auto" }}>
          <table><thead><tr><th>运控包</th><th className="num">证据</th><th>类别</th><th>晋级门</th><th>图谱</th><th>对决</th></tr></thead>
            <tbody>{rows.data.map((r) => (
              <tr key={r.id} className={`clickable ${selected === r.id ? "selected" : ""}`} onClick={() => setSelected(r.id)}>
                <td className="mono" style={{ fontSize: 12 }}>{r.id}<div className="hint">{r.kind === "baseline" ? "官方基线" : r.status}</div></td>
                <td className="num">{r.total}</td>
                <td style={{ fontSize: 12 }}>{Object.entries(r.evidence).map(([k, n]) => `${KIND[k] || k}×${n}`).join("、") || "—"}</td>
                <td><Verdict value={r.gate} /></td><td><Verdict value={r.kind === "baseline" ? null : r.atlas} /></td><td><Verdict value={r.duel} /></td>
              </tr>
            ))}</tbody></table>
        </div>
      )}
    </Card>
    {d && <>
      <Card title={<span className="mono">{d.pack.id}</span>} sub={d.pack.description}>
        <div className="row" style={{ alignItems: "stretch", gap: 8 }}>
          {d.lineage.map((stage, i) => (
            <div key={i} className="row" style={{ gap: 8, alignItems: "stretch" }}>
              <div className="stage" style={{ minWidth: 190, minHeight: 0 }}>
                <div className="n">{stage.stage}</div>
                <div className="t mono" style={{ fontSize: 12, wordBreak: "break-all" }}>{stage.id}</div>
                <div className="d"><Badge value={stage.status} text={stage.status} /></div>
                <div className="d mono" style={{ fontSize: 11 }}>
                  {Object.entries(stage.detail || {}).filter(([, v]) => v !== null && v !== undefined && !(Array.isArray(v) && !v.length)).slice(0, 5).map(([k, v]) => (
                    <div key={k}>{k}: {typeof v === "string" && v.length === 64 ? short(v, 12) : Array.isArray(v) ? v.join(",") : String(v)}</div>
                  ))}
                </div>
              </div>
              {i < d.lineage.length - 1 && <div style={{ alignSelf: "center", color: "var(--muted)" }}>→</div>}
            </div>
          ))}
        </div>
        {d.hash_aliases.length > 0 && <p className="hint">字节相同的副本：{d.hash_aliases.join("、")}（按哈希关联的证据双方共享）</p>}
        <p className="hint">{d.note}</p>
      </Card>
      <div className="grid c2">
        <Card title="结论摘要">
          <table><tbody>
            {d.scorecard.gate && <tr><td>晋级门</td><td><Verdict value={d.scorecard.gate.verdict} /> <span className="hint mono">{d.scorecard.gate.rule_version}</span></td></tr>}
            {d.scorecard.atlas && <tr><td>易损性图谱</td><td>{d.scorecard.atlas.verdict ? <>
              <Verdict value={d.scorecard.atlas.verdict} />
              <div className="hint">更强：{(d.scorecard.atlas.better_axes || []).join("、") || "无"}；更弱：{(d.scorecard.atlas.worse_axes || []).join("、") || "无"}</div></> : <span className="hint">作为基线</span>}</td></tr>}
            {d.scorecard.duel && <tr><td>序贯对决</td><td><Verdict value={d.scorecard.duel.decision} /> <span className="hint">{d.scorecard.duel.pairs ?? 0} 对 · {d.scorecard.duel.candidate === d.pack.id ? "候选" : "基线"}</span></td></tr>}
            {d.scorecard.mujoco_stress && <tr><td>MuJoCo 压力</td><td className="mono" style={{ fontSize: 12 }}>跌倒率 {(d.scorecard.mujoco_stress.fall_rate ?? 0).toFixed(4)} · 推力≤{d.scorecard.mujoco_stress.push_force_max_N} N</td></tr>}
            {d.scorecard.isaac_eval?.rmse_vx_vy_wz_moving && <tr><td>Isaac Gym</td><td className="mono" style={{ fontSize: 12 }}>RMSE {d.scorecard.isaac_eval.rmse_vx_vy_wz_moving.map((v: number) => v.toFixed(3)).join(" / ")} · 复位 {d.scorecard.isaac_eval.resets}</td></tr>}
            {d.scorecard.validation && <tr><td>SimRobot 验证</td><td><Badge value={d.scorecard.validation.verdict} /> <span className="hint">{d.scorecard.validation.mode}</span></td></tr>}
          </tbody></table>
          {!Object.keys(d.scorecard).length && <Empty>还没有评测结论</Empty>}
        </Card>
        <Card title="证据缺口" sub="晋级前建议补齐">
          {d.missing.length ? <ul style={{ margin: 0, paddingLeft: 18 }}>{d.missing.map((m) => <li key={m}>{m}</li>)}</ul>
            : <p className="hint">{d.pack.kind === "baseline" ? "官方基线，不需要晋级" : "常规证据类别均已存在（是否通过见左侧结论）"}</p>}
          <p className="hint">L5 真机闭环固定未验证，需要单独授权与实物实验。</p>
        </Card>
      </div>
      <Card title="全部证据" sub={`${Object.values(d.counts).reduce((a, b) => a + b, 0)} 份 · 按时间倒序`}>
        {Object.entries(d.evidence).map(([kind, items]) => (
          <details key={kind} open={["atlas", "duel", "gate"].includes(kind)} style={{ marginBottom: 8 }}>
            <summary><b>{KIND[kind] || kind}</b> <span className="hint">×{items.length}</span></summary>
            <table><tbody>{items.slice(0, 20).map((row) => (
              <tr key={row.path}>
                <td className="hint" style={{ whiteSpace: "nowrap" }}>{row.at}</td>
                <td><Verdict value={row.status} /></td>
                <td style={{ fontSize: 12 }}>{summaryText(row)}</td>
                <td className="mono" style={{ fontSize: 11, wordBreak: "break-all" }}>{row.path}</td>
              </tr>
            ))}</tbody></table>
          </details>
        ))}
      </Card>
    </>}
  </>;
}
