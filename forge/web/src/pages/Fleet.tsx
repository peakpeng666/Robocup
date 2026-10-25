import { useState } from "react";
import { api, Dict, FlashReceipt, Pack, short } from "../api";
import { Badge, Card, Checks, Empty, usePoll, useToast } from "../components/ui";

interface ArenaData {
  state: Dict<any> | null;
  freshness: { status: string; source_changed?: boolean; binary_changed?: boolean } | null;
  flashed: Dict<FlashReceipt>;
}

interface VerifyReport {
  status: string;
  checks: Dict<boolean>;
  teams: Dict<{ pack_id: string; differs: string[]; undeclared_differences: string[]; networks: Dict<{ model_name: string; ok: boolean; sha256: string }> }>;
}

const TEAMS = [
  { team: 5, name: "B-Human", robots: ["robot1", "robot2", "robot3"], jersey: "#e5484d", keeper: "#3e7bfa", cls: "t5" },
  { team: 70, name: "B-Team", robots: ["robot21", "robot22", "robot23"], jersey: "#f0f0f0", keeper: "#a96cff", cls: "t70" },
];

export function Fleet({ go }: { go: (page: string) => void }) {
  const toast = useToast();
  const [arenaName, setArenaName] = useState("main");
  const arenas = usePoll<{ name: string; source: string; variant?: Dict<any> | null; binary_identical_to_validated_release: boolean }[]>("/api/arenas", 15000);
  const arena = usePoll<ArenaData>(`/api/arena?name=${arenaName}`, 5000);
  const packs = usePoll<Pack[]>("/api/packs", 10000);
  const verify = usePoll<VerifyReport>(`/api/arena/verify?name=${arenaName}`, 8000);
  const [choice, setChoice] = useState<Dict<string>>({});
  const [busy, setBusy] = useState(false);
  const [match, setMatch] = useState({ seconds: 120, vision: "cuda", record: true });
  const [series, setSeries] = useState({ pack_a: "", pack_b: "bhuman-official", rounds: 2, seconds: 120 });

  const flash = async (team: number) => {
    const packId = choice[team];
    if (!packId) return;
    setBusy(true);
    try {
      const res = await api.post<{ readback: VerifyReport }>("/api/flash", { team, pack_id: packId, arena: arenaName });
      toast(`T${team} 已刷写 ${packId}，回读 ${res.readback.status}`, res.readback.status !== "PASS");
      arena.reload();
      verify.reload();
    } catch (e: any) {
      toast(`刷写失败：${e.message}`, true);
    } finally {
      setBusy(false);
    }
  };

  const init = async (refresh: boolean) => {
    setBusy(true);
    try {
      await api.post("/api/arena/init", { refresh, arena: arenaName });
      toast(refresh ? "arena 已从 bhuman-local 重新复制" : "arena 已建立");
      arena.reload();
      verify.reload();
    } catch (e: any) {
      toast(e.message, true);
    } finally {
      setBusy(false);
    }
  };

  const submit = async (type: string, params: Dict) => {
    try {
      const res = await api.post<{ id: string }>("/api/jobs", { type, params });
      toast(`已提交作业 ${res.id}`);
      go("jobs");
    } catch (e: any) {
      toast(`提交失败：${e.message}`, true);
    }
  };

  if (!arena.data || !packs.data) return <Empty>加载中…</Empty>;
  const allPacks = packs.data;
  const state = arena.data.state;
  return (
    <>
      <div className="page-title">
        <h2>队伍机群 · 刷运控</h2>
        <p>给同一队伍的所有机器人刷写运控包（网络/参数/代码模块）；程序来自 bhuman-local 或编译好的源码变体</p>
      </div>
      <div className="row">
        <span className="hint">Arena：</span>
        {(arenas.data || [{ name: "main", source: "", binary_identical_to_validated_release: true }]).map((a) => (
          <button key={a.name} className={`btn small ${a.name === arenaName ? "primary" : ""}`} onClick={() => setArenaName(a.name)} title={a.source}>
            {a.name}
            {a.variant?.kind === "variant" ? ` · 变体 ${a.variant.name}` : " · bhuman-local"}
          </button>
        ))}
      </div>
      {!state ? (
        <Card title="Arena 尚未建立">
          <p className="hint">从 bhuman-local 复制一份 Config，把 SimulatedK1 下会遮蔽队伍配置的 6 个文件下沉到各队 scenario。</p>
          <button className="btn primary" disabled={busy} onClick={() => init(false)}>建立 arena</button>
        </Card>
      ) : (
        <Card
          title={`Arena ${arenaName}`}
          sub={`复制自 ${state.source_files} 个文件 · SimRobot ${short(state.binary_sha256)} · 控制器 ${short(state.controller_sha256)}`}
          right={
            <div className="row">
              <Badge value={arena.data.freshness?.status} />
              <button className="btn small" disabled={busy} onClick={() => init(true)}>从 bhuman-local 刷新</button>
            </div>
          }
        >
          <div className="hint">下沉的遮蔽文件：{Object.keys(state.shadow_moved || {}).join("、")}</div>
        </Card>
      )}
      <div className="grid c2">
        {TEAMS.map((t) => {
          const receipt = arena.data!.flashed[String(t.team)];
          const pack = allPacks.find((p) => p.id === receipt?.pack_id);
          const teamVerify = verify.data?.teams?.[String(t.team)];
          return (
            <div className={`team ${t.cls}`} key={t.team}>
              <div className="row between">
                <h3 style={{ margin: 0 }}>
                  T{t.team} · {t.name}
                </h3>
                {receipt ? <Badge value={receipt.pack_kind} /> : <span className="badge muted">未刷写</span>}
              </div>
              <div className="robots">
                {t.robots.map((r, i) => (
                  <div className="robot" key={r}>
                    <div className="jersey" style={{ background: i === 0 ? t.keeper : t.jersey }}>{i + 1}</div>
                    <div className="mono" style={{ fontSize: 12 }}>{r}</div>
                    <div className="pk">{pack ? pack.name : "—"}</div>
                    {pack && Object.keys((pack as any).modules || {}).length > 0 && (
                      <div className="badge violet" style={{ marginTop: 4 }}>C++ {Object.keys((pack as any).modules).join(",")}</div>
                    )}
                    <div className="mono hint" style={{ fontSize: 11 }}>
                      walk {short(teamVerify?.networks?.walk?.sha256, 8)}
                    </div>
                  </div>
                ))}
              </div>
              {receipt && (
                <div className="hint">
                  scenario <span className="mono">{receipt.scenario}</span> · 包 <span className="mono">{receipt.pack_id}</span> · {receipt.at.slice(0, 19)}
                  {teamVerify && teamVerify.differs?.length > 0 && <> · 相对原布局改动：<span className="mono">{teamVerify.differs.join(", ")}</span></>}
                </div>
              )}
              <div className="row" style={{ marginTop: 10 }}>
                <select value={choice[t.team] || ""} onChange={(e) => setChoice({ ...choice, [t.team]: e.target.value })} style={{ flex: 1 }}>
                  <option value="">选择运控包…</option>
                  {allPacks.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.kind === "baseline" ? "【官方】" : "【候选】"}
                      {p.name} — {p.id}
                    </option>
                  ))}
                </select>
                <button className="btn primary" disabled={busy || !choice[t.team] || !state} onClick={() => flash(t.team)}>
                  刷写到本队
                </button>
              </div>
            </div>
          );
        })}
      </div>
      <Card title="刷写回读校验" sub="静态：复刻 B-Human 配置搜索路径逐文件解析；赛后再做运行时网络加载回读" right={<Badge value={verify.data?.status} />}>
        {verify.data ? <Checks checks={verify.data.checks} /> : <Empty>{verify.error || "加载中…"}</Empty>}
      </Card>
      <div className="grid c2">
        <Card title="开赛" sub="3v3 · HSL-M · SimRobot 内置自动裁判 · 正常渲染相机">
          <div className="form">
            <label className="field">
              仿真秒数
              <input type="number" min={60} max={1800} value={match.seconds} onChange={(e) => setMatch({ ...match, seconds: Number(e.target.value) })} />
            </label>
            <label className="field">
              视觉后端
              <select value={match.vision} onChange={(e) => setMatch({ ...match, vision: e.target.value })}>
                <option value="cuda">CUDA（已验证 FP32）</option>
                <option value="cpu">CPU</option>
              </select>
            </label>
            <label className="field">
              录像
              <select value={match.record ? "1" : "0"} onChange={(e) => setMatch({ ...match, record: e.target.value === "1" })}>
                <option value="1">录制 MP4</option>
                <option value="0">不录</option>
              </select>
            </label>
            <button className="btn primary" onClick={() => submit("match", { ...match, tag: "ui-match", arena: arenaName })}>开始比赛</button>
          </div>
          <p className="hint">开赛前强制刷写回读 PASS；与 GPU 训练互斥排队；会在桌面打开 SimRobot 窗口。</p>
        </Card>
        <Card title="主客互换系列赛" sub="每轮重新刷写，A/B 轮换队伍，消除边侧偏差">
          <div className="form">
            <label className="field">
              运控包 A
              <select value={series.pack_a} onChange={(e) => setSeries({ ...series, pack_a: e.target.value })}>
                <option value="">选择…</option>
                {allPacks.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </label>
            <label className="field">
              运控包 B
              <select value={series.pack_b} onChange={(e) => setSeries({ ...series, pack_b: e.target.value })}>
                {allPacks.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </label>
            <label className="field">
              轮数
              <input type="number" min={1} max={10} value={series.rounds} onChange={(e) => setSeries({ ...series, rounds: Number(e.target.value) })} />
            </label>
            <label className="field">
              每场秒数
              <input type="number" min={60} max={1800} value={series.seconds} onChange={(e) => setSeries({ ...series, seconds: Number(e.target.value) })} />
            </label>
            <button className="btn primary" disabled={!series.pack_a || !series.pack_b} onClick={() => submit("series", { ...series, arena: arenaName })}>开始系列赛</button>
          </div>
        </Card>
      </div>
    </>
  );
}
