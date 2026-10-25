import { useEffect, useState } from "react";
import { api, Dict, MatchSummary, TeamStats } from "../api";
import { Field, RobotTrack } from "../components/Field";
import { Badge, Card, Checks, Empty, usePoll } from "../components/ui";

interface MatchDetail {
  id: string;
  status: string;
  score: Dict<number>;
  teams: Dict<TeamStats>;
  robots: Dict<{ team: number; player: number; trajectory: [number, number, number, number][]; fall_episodes_sampled: number; walk_frames: number; path_m: number; perception_hz: number; ball_seen_samples: number }>;
  ball_track: [number, number, number][];
  checks: Dict<boolean>;
  network_readback: { expected_loads: Dict<number>; observed_loads: Dict<number>; loaded_outside_arena: string[]; ok: boolean };
  performance: { wall_s: number; real_time_factor: number };
  video?: string;
  launch: Dict<any>;
  measurement_note: string;
  scope: string;
}

interface Series {
  id: string;
  pack_a: string;
  pack_b: string;
  status: string;
  rounds_played: number;
  rounds_valid: number;
  record: Dict<{ win: number; draw: number; loss: number }>;
  totals: Dict<Dict<number>>;
  rounds: { round: number; assignment: Dict<string>; score: Dict<number>; status: string }[];
}

const METRICS: [keyof TeamStats, string, (v: number) => string][] = [
  ["goals", "进球", (v) => String(v)],
  ["ball_contacts", "触球（10Hz 限频）", (v) => String(v)],
  ["fall_episodes_sampled", "跌倒次数（采样）", (v) => String(v)],
  ["getup_frames", "起身帧", (v) => String(v)],
  ["walk_frames", "行走帧", (v) => String(v)],
  ["path_m", "移动距离 m", (v) => v.toFixed(1)],
  ["ball_seen_samples", "看到球的感知样本", (v) => String(v)],
  ["mean_perception_hz", "感知帧率 Hz", (v) => v.toFixed(1)],
];

export function Matches() {
  const list = usePoll<MatchSummary[]>("/api/matches", 8000);
  const series = usePoll<Series[]>("/api/series", 15000);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<MatchDetail | null>(null);
  useEffect(() => {
    if (!selected && list.data?.length) setSelected(list.data[0].id);
  }, [list.data, selected]);
  useEffect(() => {
    if (!selected) return;
    setDetail(null);
    api.get<MatchDetail>(`/api/matches/${selected}`).then(setDetail).catch(() => setDetail(null));
  }, [selected]);
  const robots: RobotTrack[] = detail
    ? Object.entries(detail.robots).map(([name, r]) => ({ name, team: r.team, player: r.player, trajectory: r.trajectory }))
    : [];
  return (
    <>
      <div className="page-title">
        <h2>队伍对抗赛</h2>
        <p>SimRobot 全自动比赛的按队证据：比分、触球、跌倒、行走、感知，以及赛后网络加载回读</p>
      </div>
      {series.data && series.data.length > 0 && (
        <Card title="系列赛">
          <table>
            <thead>
              <tr><th>系列</th><th>A</th><th>B</th><th>A 胜/平/负</th><th className="num">A 进球</th><th className="num">B 进球</th><th className="num">A 跌倒</th><th className="num">B 跌倒</th><th>状态</th></tr>
            </thead>
            <tbody>
              {series.data.map((s) => (
                <tr key={s.id}>
                  <td className="mono hint">{s.id.slice(0, 15)}</td>
                  <td className="mono">{s.pack_a}</td>
                  <td className="mono">{s.pack_b}</td>
                  <td>{s.record[s.pack_a]?.win}/{s.record[s.pack_a]?.draw}/{s.record[s.pack_a]?.loss}</td>
                  <td className="num">{s.totals[s.pack_a]?.goals ?? 0}</td>
                  <td className="num">{s.totals[s.pack_b]?.goals ?? 0}</td>
                  <td className="num">{s.totals[s.pack_a]?.fall_episodes_sampled ?? 0}</td>
                  <td className="num">{s.totals[s.pack_b]?.fall_episodes_sampled ?? 0}</td>
                  <td><Badge value={s.status} /> <span className="hint">{s.rounds_valid}/{s.rounds_played}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      <div className="grid" style={{ gridTemplateColumns: "minmax(320px, 0.8fr) 2fr" }}>
        <Card title="比赛列表">
          {!list.data?.length ? (
            <Empty>还没有比赛，去「队伍机群」开赛</Empty>
          ) : (
            <table>
              <thead>
                <tr><th>时间</th><th className="num">T5 : T70</th><th>检查</th></tr>
              </thead>
              <tbody>
                {list.data.map((m) => (
                  <tr key={m.id} className={`clickable ${m.id === selected ? "selected" : ""}`} onClick={() => setSelected(m.id)}>
                    <td>
                      <div className="mono" style={{ fontSize: 12 }}>{m.id.slice(0, 15)}</div>
                      <div className="hint" style={{ fontSize: 11 }}>{m.tag}</div>
                    </td>
                    <td className="num"><b>{m.score?.["5"]} : {m.score?.["70"]}</b></td>
                    <td><Badge value={m.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        {!detail ? (
          <Empty>选择一场比赛</Empty>
        ) : (
          <div className="stack" style={{ gap: 16 }}>
            <div className="grid c2">
              <Card title="录像" sub="SimRobot 自身 3D 帧缓冲（观赛视角，非机器人相机）">
                {detail.video ? <video src={`/api/matches/${detail.id}/video`} controls preload="metadata" /> : <Empty>本场未录像</Empty>}
              </Card>
              <Card title="场地回放" sub="2 Hz 采样位姿 · 球轨迹含裁判摆放">
                <Field robots={robots} ball={detail.ball_track} />
              </Card>
            </div>
            <Card
              title={`比分 ${detail.score["5"]} : ${detail.score["70"]}`}
              sub={`墙钟 ${detail.performance?.wall_s?.toFixed(1)} s · ${detail.performance?.real_time_factor?.toFixed(2)}× 实时（含启动与采帧）`}
              right={<Badge value={detail.status} />}
            >
              <table>
                <thead>
                  <tr>
                    <th>按队指标</th>
                    {["5", "70"].map((t) => (
                      <th key={t} className="num">
                        T{t} · <span className="mono">{detail.teams[t]?.pack_id}</span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {METRICS.map(([key, label, f]) => (
                    <tr key={key}>
                      <td>{label}</td>
                      {["5", "70"].map((t) => (
                        <td key={t} className="num">{f(Number(detail.teams[t]?.[key] ?? 0))}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="hint">{detail.measurement_note}</p>
            </Card>
            <div className="grid c2">
              <Card title="运行时网络加载回读" right={<Badge value={detail.network_readback?.ok} />}>
                <table>
                  <thead><tr><th>模型</th><th className="num">期望</th><th className="num">实际</th></tr></thead>
                  <tbody>
                    {Object.entries(detail.network_readback?.expected_loads || {}).map(([model, n]) => (
                      <tr key={model}>
                        <td className="mono" style={{ fontSize: 11.5 }}>{model}</td>
                        <td className="num">{n}</td>
                        <td className="num" style={{ color: detail.network_readback.observed_loads[model] === n ? "var(--ok)" : "var(--bad)" }}>
                          {detail.network_readback.observed_loads[model] ?? 0}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {detail.network_readback?.loaded_outside_arena?.length > 0 && <p className="hint">arena 外加载：{detail.network_readback.loaded_outside_arena.join(", ")}</p>}
              </Card>
              <Card title="验收检查" sub={detail.scope}>
                <Checks checks={detail.checks} />
              </Card>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
