import { useEffect, useState } from "react";
import { api, Pack } from "../api";
import { Badge, Card, Checks, Empty, usePoll, useToast } from "../components/ui";
import { Field, RobotTrack } from "../components/Field";

interface Strategy {
  id: string; name: string; kind: string; description?: string;
  cfg_patches: Record<string, Record<string, string>>;
}
interface Preset { name: string; description: string; cfg_patches: Record<string, Record<string, string>> }
interface RunSummary {
  id: string; status: string; verdict: string; mode: string; completed_cases: number; case_count: number;
  motion_pack: string; strategy_id: string;
}
interface CaseResult {
  run: string; status: string; checks: Record<string, boolean>; video?: string;
  score: Record<string, number>; teams: Record<string, any>;
  robots: Record<string, { team: number; player: number; trajectory: [number, number, number, number][] }>;
  ball_track: [number, number, number][];
  behavior_readback?: { ok: boolean; files: { robot: string; filename: string; ok: boolean; actual?: Record<string, string>; mismatches?: string[]; error?: string }[] };
  network_readback?: { ok: boolean };
  motion_segments?: Record<string, Record<string, number>>;
  measurement_note: string;
}
interface ValidationRun {
  id: string; status: string; verdict: string; error?: string; arena: string;
  plan: { mode: string; motion_pack: string; strategy_id: string; case_count: number; rules: Record<string, number>; scope: string };
  cases: { case: { id: string; candidate_team?: number; kickoff_team?: number; role?: string }; result: CaseResult; result_sha256: string }[];
  comparison?: {
    verdict: string; note?: string; reason?: string;
    metrics?: { segment: string; metric: string; baseline: number; candidate: number; delta: number; ok: boolean }[];
    record?: { win: number; draw: number; loss: number };
    totals?: Record<string, any>;
  };
}
interface Plan { case_count: number; simulation_seconds: number; cases: { id: string; seconds: number }[]; scope: string }
const SEGMENTS: Record<string, string> = { forward: "前进距离 m", left: "侧移距离 m", turn: "转向角度 rad", settled_stop: "停止后漂移 m" };
const SKILLS: Record<string, string> = { walk: "跑位", shoot: "射门请求", pass: "传球请求", dribble: "带球请求", clear: "解围请求", observe: "观察" };

export function Validation({ go }: { go: (page: string) => void }) {
  const toast = useToast();
  const packs = usePoll<Pack[]>("/api/packs", 15000);
  const strategies = usePoll<{ profiles: Strategy[]; presets: Record<string, Preset> }>("/api/strategies", 15000);
  const arenas = usePoll<{ name: string }[]>("/api/arenas", 15000);
  const runs = usePoll<RunSummary[]>("/api/validations", 4000);
  const [mode, setMode] = useState("motion");
  const [motion, setMotion] = useState("bhuman-official");
  const [strategy, setStrategy] = useState("bhuman-official-strategy");
  const [arena, setArena] = useState("main");
  const [repetitions, setRepetitions] = useState(1);
  const [seconds, setSeconds] = useState(120);
  const [record, setRecord] = useState(true);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<Plan | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [caseId, setCaseId] = useState<string | null>(null);
  const detail = usePoll<ValidationRun>(selected ? `/api/validations/${selected}` : null, 4000);
  const [draftName, setDraftName] = useState("earlier-ball-search");
  const [draft, setDraft] = useState<Record<string, Record<string, string>>>({});

  useEffect(() => { if (!selected && runs.data?.length) setSelected(runs.data[0].id); }, [runs.data, selected]);
  useEffect(() => { setCaseId(null); }, [selected]);
  useEffect(() => { setPreview(null); }, [mode, motion, strategy, arena, repetitions, seconds, record]);
  useEffect(() => {
    if (strategies.data && !Object.keys(draft).length) {
      setDraft(structuredClone(strategies.data.presets["earlier-ball-search"].cfg_patches));
    }
  }, [strategies.data, draft]);

  const params = { mode, motion_pack: motion, strategy_id: mode === "motion" ? "bhuman-official-strategy" : strategy,
    source_arena: arena, repetitions, seconds, vision: "cuda", record };
  const prepare = async () => {
    try { setPreview(await api.post<Plan>("/api/validations/preview", params)); }
    catch (e: any) { toast(e.message, true); }
  };
  const start = async () => {
    setBusy(true);
    try {
      setPreview(await api.post<Plan>("/api/validations/preview", params));
      const job = await api.post<{ id: string }>("/api/jobs", { type: "validation", params });
      toast(`验证已排队：${job.id}`);
      go("jobs");
    } catch (e: any) { toast(e.message, true); }
    finally { setBusy(false); }
  };
  const saveStrategy = async () => {
    setBusy(true);
    try {
      const result = await api.post<Strategy>("/api/strategies", { name: draftName, cfg_patches: draft });
      strategies.reload(); setStrategy(result.id); toast(`策略已保存：${result.name}`);
    } catch (e: any) { toast(e.message, true); }
    finally { setBusy(false); }
  };
  const current = detail.data?.id === selected ? detail.data : null;
  const row = current?.cases.find(c => c.case.id === caseId) || current?.cases[0];
  const result = row?.result;
  const tracks: RobotTrack[] = result ? Object.entries(result.robots).map(([name, r]) => ({ name, ...r })) : [];
  const artifact = (kind: string) => `/api/validations/${selected}/cases/${row?.case.id}/${kind}`;
  const report = current;
  const comparison = report?.comparison;

  return <>
    <div className="page-title"><h2>SimRobot 验证</h2><p>分别验证运控响应与足球行为策略；每次实验使用独立场地，保留参数回读、轨迹、录像和原始证据。</p></div>
    {(runs.error || detail.error) && <p className="hint" role="alert">{runs.error || detail.error}</p>}
    <div className="grid c2">
      <Card title="建立对照实验">
        <div className="row" style={{ marginBottom: 12 }}>
          <button className={`btn ${mode === "motion" ? "primary" : ""}`} onClick={() => setMode("motion")}>运控验证</button>
          <button className={`btn ${mode === "strategy" ? "primary" : ""}`} onClick={() => setMode("strategy")}>策略验证</button>
        </div>
        <p className="hint">{mode === "motion" ? "同一机器人执行 30 秒固定指令，先测官方、再测候选。官方对官方可用作重复性对照。" : "两队使用相同步态，策略分别加载。每次重复包含四场，覆盖队伍互换和双方开球。"}</p>
        <div className="form">
          <label className="field">{mode === "motion" ? "候选运控包" : "两队共用运控包"}<select value={motion} onChange={e => setMotion(e.target.value)}>
            {(packs.data || []).filter(p => !p.provenance?.composition).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select></label>
          <label className="field">程序来源<select value={arena} onChange={e => setArena(e.target.value)}>
            {(arenas.data || []).filter(a => !a.name.startsWith("validation-")).map(a => <option key={a.name}>{a.name}</option>)}
          </select></label>
          {mode === "strategy" && <label className="field">候选策略<select value={strategy} onChange={e => setStrategy(e.target.value)}>
            {(strategies.data?.profiles || []).filter(p => p.kind !== "invalid").map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select></label>}
          <label className="field">重复次数<input type="number" min={1} max={5} value={repetitions} onChange={e => setRepetitions(Number(e.target.value))} /></label>
          {mode === "strategy" && <label className="field">每场仿真秒数<input type="number" min={60} max={600} value={seconds} onChange={e => setSeconds(Number(e.target.value))} /></label>}
          <label className="row"><input type="checkbox" checked={record} onChange={e => setRecord(e.target.checked)} />保存录像与原始帧</label>
        </div>
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn" onClick={prepare} disabled={busy}>查看计划</button>
          <button className="btn primary" onClick={start} disabled={busy}>开始验证</button>
        </div>
        {preview && <div style={{ marginTop: 12 }}><b>{preview.case_count} 个场景 · 共 {preview.simulation_seconds} 秒仿真</b>
          <p className="hint">{preview.cases.map(c => c.id).join(" / ")}</p><p className="hint">{preview.scope}</p></div>}
      </Card>
      <Card title="独立策略配置" sub="保存为新的实验策略">
        <p className="hint">当前支持官方行为层的搜球、丢球与接应时间参数。配置不会改变步态或视觉；是否有效由对照赛检验。</p>
        <div className="form">
        <label className="field">从预设开始<select defaultValue="earlier-ball-search" onChange={e => {
          const preset = strategies.data?.presets[e.target.value];
          if (preset) { setDraft(structuredClone(preset.cfg_patches)); setDraftName(e.target.value); }
        }}>{Object.entries(strategies.data?.presets || {}).map(([id, p]) => <option key={id} value={id}>{p.name}</option>)}</select></label>
        <label className="field">策略名称<input value={draftName} onChange={e => setDraftName(e.target.value)} /></label>
        {Object.entries(draft).map(([file, values]) => <div key={file}>
          {Object.entries(values).map(([key, value]) => <label className="field" key={key}><span className="mono">{key}</span> · ms
            <input type="number" min={0} max={30000} value={value} onChange={e => setDraft({ ...draft, [file]: { ...values, [key]: e.target.value } })} />
          </label>)}
        </div>)}
        </div>
        <button className="btn" disabled={busy || !draftName.trim()} onClick={saveStrategy} style={{ marginTop: 12 }}>保存策略副本</button>
      </Card>
    </div>
    <Card title="验证记录" sub="运行完成与性能结论分别展示">
      {!runs.data?.length ? <Empty>还没有验证运行。</Empty> : <table>
        <thead><tr><th>运行</th><th>类型</th><th>场景进度</th><th>执行状态</th><th>结论</th></tr></thead>
        <tbody>{runs.data.map(r => <tr key={r.id} className={selected === r.id ? "selected" : ""} onClick={() => setSelected(r.id)} style={{ cursor: "pointer" }}>
          <td className="mono">{r.id}</td><td>{r.mode === "motion" ? "运控" : "策略"}</td><td>{r.completed_cases} / {r.case_count}</td>
          <td><Badge value={r.status} /></td><td><Badge value={r.verdict} /></td>
        </tr>)}</tbody>
      </table>}
    </Card>
    {report && <>
      <Card title="对照结论" right={<Badge value={report.verdict} />}>
        {report.error && <p role="alert">{report.error}</p>}
        <p className="hint mono">本次运控：{report.plan.motion_pack}<br />本次策略：{report.plan.strategy_id}</p>
        <p className="hint">{comparison?.note || comparison?.reason || "场景完成后汇总；未完成不会判为通过。"}</p>
        {comparison?.metrics && <table><thead><tr><th>指标</th><th className="num">官方</th><th className="num">候选</th><th className="num">变化</th><th>检查</th></tr></thead>
          <tbody>{comparison.metrics.map(m => <tr key={m.segment}><td>{SEGMENTS[m.segment]}</td><td className="num">{m.baseline.toFixed(4)}</td><td className="num">{m.candidate.toFixed(4)}</td><td className="num">{m.delta.toFixed(4)}</td><td><Badge value={m.ok} /></td></tr>)}</tbody>
        </table>}
        {comparison?.record && <p>候选：{comparison.record.win} 胜 / {comparison.record.draw} 平 / {comparison.record.loss} 负</p>}
        {comparison?.totals && <table><thead><tr><th>指标</th><th className="num">官方策略</th><th className="num">候选策略</th></tr></thead><tbody>
          {[["goals", "进球"], ["ball_contacts", "触球样本"], ["fall_episodes_sampled", "跌倒事件（采样）"]].map(([key, label]) => <tr key={key}><td>{label}</td><td className="num">{comparison.totals!.baseline[key]}</td><td className="num">{comparison.totals!.candidate[key]}</td></tr>)}
          {Object.entries(SKILLS).map(([key, label]) => <tr key={key}><td>{label}样本</td><td className="num">{comparison.totals!.baseline.skill_samples[key]}</td><td className="num">{comparison.totals!.candidate.skill_samples[key]}</td></tr>)}
        </tbody></table>}
      </Card>
      <Card title="场景证据">
        <div className="row" style={{ flexWrap: "wrap" }}>{report.cases.map(c => <button key={c.case.id} className={`btn small ${row?.case.id === c.case.id ? "primary" : ""}`} onClick={() => setCaseId(c.case.id)}>{c.case.id} · {c.result.status}</button>)}</div>
        {result && <>
          <div className="grid c2" style={{ marginTop: 14 }}>
            <div><Field key={`${selected}-${row!.case.id}`} robots={tracks} ball={result.ball_track} /></div>
            <div>{result.video ? <video key={artifact("video")} src={artifact("video")} controls preload="metadata" style={{ width: "100%", maxHeight: 340 }} /> : <Empty>此场景未录制视频。</Empty>}
              <div className="row" style={{ marginTop: 10 }}><a href={artifact("result")} target="_blank" rel="noreferrer">结果 JSON</a><a href={artifact("launch")} target="_blank" rel="noreferrer">启动清单</a><a href={artifact("console")} target="_blank" rel="noreferrer">原始日志</a></div>
            </div>
          </div>
          <p className="hint">轨迹与跌倒按采样统计；技能请求不代表动作已成功完成。原始录像帧与配置快照保留在本机运行目录。</p>
          <div className="row"><span>实际网络加载</span><Badge value={result.network_readback?.ok} /><span>实际策略参数</span><Badge value={result.behavior_readback?.ok} /></div>
          <details style={{ marginTop: 10 }}><summary>查看每台机器人参数回读</summary><table><thead><tr><th>机器人</th><th>配置</th><th>结果</th><th>差异</th></tr></thead><tbody>
            {result.behavior_readback?.files.map(f => <tr key={`${f.robot}-${f.filename}`}><td>{f.robot}</td><td className="mono">{f.filename}</td><td><Badge value={f.ok} /></td><td>{f.error || f.mismatches?.join(", ") || "一致"}</td></tr>)}
          </tbody></table></details>
          <details style={{ marginTop: 10 }}><summary>全部运行检查</summary><Checks checks={result.checks} /></details>
        </>}
      </Card>
    </>}
  </>;
}
