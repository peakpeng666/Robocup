import { Dict, FlashReceipt, Job, MatchSummary, TrainRun, short } from "../api";
import { Badge, Card, Empty, usePoll } from "../components/ui";

interface OverviewData {
  version: string;
  foundation: {
    official: Dict<string>;
    protected_files: number;
    protected_ok: boolean;
    simrobot_sha256: string;
    controller_sha256: string;
    official_walk_sha256: string;
    training_fingerprint_expected: string;
    interpreters: Dict<{ path: string; exists: boolean }>;
    error?: string;
  };
  arena: { state: Dict<any> | null; freshness: { status: string } | null; flashed: Dict<FlashReceipt> };
  packs: number;
  matches: MatchSummary[];
  train: TrainRun[];
  variants: { name: string; builds: Dict<string> }[];
  jobs: Job[];
}

const STAGES = [
  ["01", "步态训练", "B-Human 环境 × 火神算法（双 critic / 重建 / AMP）"],
  ["02", "导出", "actor 严格加载，opset 11，三方数值校验"],
  ["03", "契约", "344→13 / 59→13 / 73→22 / 72→22 图级核对"],
  ["04", "刷运控", "按队 scenario 覆盖 + 三层回读"],
  ["05", "编译", "SimRobot x86_64 · Booster ARM64 + SDK"],
  ["06", "队伍对抗", "SimRobot 正常视觉 · 自动裁判 · 录像"],
  ["07", "离线部署包", "ELF 静态核验 · 不连接机器人"],
];

export function Overview({ go }: { go: (page: string) => void }) {
  const { data } = usePoll<OverviewData>("/api/overview", 5000);
  if (!data) return <Empty>加载中…</Empty>;
  const f = data.foundation;
  const lastTrain = data.train.find((t) => t.origin === "forge");
  const lastMatch = data.matches[0];
  const builds = data.variants.flatMap((v) => Object.entries(v.builds).map(([k, s]) => `${v.name}:${k}=${s}`));
  const stageStatus = [
    lastTrain ? `${lastTrain.iterations} 轮 · ${lastTrain.status}` : "尚无",
    `${data.packs} 个运控包`,
    "官方 5 个网络通过",
    Object.values(data.arena.flashed).map((r) => `T${r.team}:${r.pack_kind === "baseline" ? "官方" : "候选"}`).join(" ") || "未刷写",
    builds.length ? builds.join(" ") : "未编译",
    lastMatch ? `${Object.values(lastMatch.score || {}).join(":")} · ${lastMatch.status}` : "尚无",
    "见编译农场",
  ];
  const running = data.jobs.filter((j) => j.status === "running" || j.status === "queued");
  return (
    <>
      <div className="page-title">
        <h2>总览</h2>
        <p>以 B-Human 2026 开源代码为底座的 K1 运控研发 → 刷写 → 编译 → 对抗流水线</p>
      </div>
      <div className="pipeline">
        {STAGES.map(([n, t, d], i) => (
          <div className="stage" key={n}>
            <div className="n">{n}</div>
            <div className="t">{t}</div>
            <div className="d">{d}</div>
            <div className="sep" />
            <div className="mono" style={{ fontSize: 11.5, color: "var(--accent-2)" }}>{stageStatus[i]}</div>
          </div>
        ))}
      </div>
      <div className="grid c3">
        <Card title="B-Human 底座" sub="只读 · 哈希钉住" right={<Badge value={f.protected_ok} text={f.protected_ok ? `${f.protected_files} 个受保护文件一致` : "不一致"} />}>
          <table>
            <tbody>
              <tr><td>BHumanCodeRelease</td><td className="mono">{short(f.official.BHumanCodeRelease, 12)}</td></tr>
              <tr><td>MachineLearning</td><td className="mono">{short(f.official.MachineLearning, 12)}</td></tr>
              <tr><td>官方行走 ONNX</td><td className="mono">{short(f.official_walk_sha256, 12)}</td></tr>
              <tr><td>SimRobot Release</td><td className="mono">{short(f.simrobot_sha256, 12)}</td></tr>
              <tr><td>SimulatedRobot 控制器</td><td className="mono">{short(f.controller_sha256, 12)}</td></tr>
              <tr><td>训练主线指纹</td><td className="mono">{short(f.training_fingerprint_expected, 12)}</td></tr>
            </tbody>
          </table>
          <div className="row" style={{ marginTop: 8 }}>
            {Object.entries(f.interpreters).map(([k, v]) => (
              <span key={k} className={`badge ${v.exists ? "ok" : "bad"}`}>{k}</span>
            ))}
          </div>
        </Card>
        <Card title="Arena 队伍" sub="同一已验证 SimRobot 二进制" right={<Badge value={data.arena.freshness?.status || "NOT_MATERIALIZED"} />}>
          {Object.values(data.arena.flashed).length === 0 ? (
            <Empty>尚未刷写</Empty>
          ) : (
            <div className="stack">
              {Object.values(data.arena.flashed).map((r) => (
                <div key={r.team} className="row between">
                  <span>
                    <b>T{r.team}</b> {r.team === 5 ? "B-Human" : "B-Team"}
                  </span>
                  <span className="row">
                    <Badge value={r.pack_kind} />
                    <span className="mono hint">{r.pack_id}</span>
                  </span>
                </div>
              ))}
            </div>
          )}
          <div style={{ marginTop: 10 }}>
            <button className="btn" onClick={() => go("fleet")}>进入队伍机群 →</button>
          </div>
        </Card>
        <Card title="作业" sub={`${running.length} 个进行中`} right={<button className="btn small" onClick={() => go("jobs")}>全部</button>}>
          {data.jobs.length === 0 ? (
            <Empty>暂无作业</Empty>
          ) : (
            <table>
              <tbody>
                {data.jobs.slice(0, 7).map((j) => (
                  <tr key={j.id}>
                    <td>{j.type}</td>
                    <td className="mono hint">{j.id.slice(9, 15)}</td>
                    <td><Badge value={j.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
      <div className="grid c2">
        <Card title="最近对抗赛" right={<button className="btn small" onClick={() => go("matches")}>全部</button>}>
          {data.matches.length === 0 ? (
            <Empty>还没有比赛</Empty>
          ) : (
            <table>
              <thead>
                <tr><th>比赛</th><th>T5</th><th className="num">比分</th><th>T70</th><th>检查</th></tr>
              </thead>
              <tbody>
                {data.matches.map((m) => (
                  <tr key={m.id}>
                    <td className="mono hint">{m.id.slice(0, 15)}</td>
                    <td className="mono">{m.teams?.["5"]?.pack_id?.slice(0, 22)}</td>
                    <td className="num"><b>{m.score?.["5"]} : {m.score?.["70"]}</b></td>
                    <td className="mono">{m.teams?.["70"]?.pack_id?.slice(0, 22)}</td>
                    <td><Badge value={m.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="最近训练" right={<button className="btn small" onClick={() => go("train")}>步态实验室</button>}>
          <table>
            <thead>
              <tr><th>运行</th><th>来源</th><th className="num">轮数</th><th>状态</th></tr>
            </thead>
            <tbody>
              {data.train.map((t) => (
                <tr key={t.id}>
                  <td className="mono hint">{t.id.slice(0, 40)}</td>
                  <td>{t.origin === "forge" ? <span className="badge violet">火神配方</span> : <span className="badge muted">主线</span>}</td>
                  <td className="num">{t.iterations}</td>
                  <td><Badge value={t.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </>
  );
}
