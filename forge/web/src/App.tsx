import { useEffect, useState } from "react";
import { Atlas } from "./pages/Atlas";
import { Bridge } from "./pages/Bridge";
import { Builds } from "./pages/Builds";
import { Design } from "./pages/Design";
import { Duels } from "./pages/Duels";
import { DossierPage } from "./pages/Dossier";
import { Evals } from "./pages/Evals";
import { Fleet } from "./pages/Fleet";
import { GaitLab } from "./pages/GaitLab";
import { Jobs } from "./pages/Jobs";
import { Matches } from "./pages/Matches";
import { Overview } from "./pages/Overview";
import { Packs } from "./pages/Packs";
import { Validation } from "./pages/Validation";
import { usePoll } from "./components/ui";

const PAGES: [string, string, string][] = [
  ["overview", "◎", "总览"],
  ["validation", "◉", "SimRobot 验证"],
  ["fleet", "⚑", "队伍机群 · 刷运控"],
  ["matches", "⚽", "队伍对抗赛"],
  ["duels", "⚖", "序贯对决"],
  ["train", "∿", "步态实验室"],
  ["packs", "▣", "运控包"],
  ["dossier", "❖", "证据档案"],
  ["atlas", "✺", "鲁棒性图谱"],
  ["bridge", "⇄", "运控桥 · sim2real"],
  ["evals", "✓", "评测与晋级"],
  ["builds", "⚙", "编译农场"],
  ["jobs", "☰", "作业"],
  ["design", "✎", "架构设计"],
];

interface SystemData {
  gpu: { name?: string; memory_used_mib?: number; memory_total_mib?: number; utilization?: number; temperature_c?: number; error?: string };
  cpu_percent: number;
  load: number[];
  disk_free_gib: number;
  display: string | null;
  simlock_held: boolean;
}

function SystemBar() {
  const { data } = usePoll<SystemData>("/api/system", 3000);
  if (!data) return <div className="topbar">连接中…</div>;
  const g = data.gpu;
  return (
    <div className="topbar">
      <span>GPU <b>{g.name?.replace("NVIDIA GeForce ", "") || "?"}</b> {g.utilization ?? "?"}% · {g.memory_used_mib}/{g.memory_total_mib} MiB · {g.temperature_c}°C</span>
      <span>CPU <b>{data.cpu_percent.toFixed(0)}%</b> · load {data.load.map((x) => x.toFixed(1)).join(" ")}</span>
      <span>磁盘可用 <b>{data.disk_free_gib} GiB</b></span>
      <span>DISPLAY <b>{data.display || "无"}</b></span>
      <span>仿真锁 <b style={{ color: data.simlock_held ? "var(--warn)" : "var(--ok)" }}>{data.simlock_held ? "占用（比赛中）" : "空闲"}</b></span>
      <span className="grow" />
      <span className="hint">仅本机 127.0.0.1 · 不连接机器人</span>
    </div>
  );
}

export function App() {
  const [page, setPage] = useState(() => (location.hash.slice(1) || "overview"));
  useEffect(() => {
    const onHash = () => setPage(location.hash.slice(1) || "overview");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const go = (next: string) => {
    location.hash = next;
    setPage(next);
  };
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <h1>
            K1 <span>Forge</span>
          </h1>
          <p>运控工坊 · B-Human 2026 底座</p>
        </div>
        <nav className="nav">
          {PAGES.map(([id, icon, label]) => (
            <button key={id} className={page === id ? "active" : ""} onClick={() => go(id)}>
              <span className="icon">{icon}</span>
              {label}
            </button>
          ))}
        </nav>
        <div className="foot">
          底座：BHumanCodeRelease 2e3374b · MachineLearning c3fed81
          <br />
          算法参考：清华火神（BSD 三条款）
          <br />
          This product includes software developed by B-Human.
        </div>
      </aside>
      <main className="main">
        <label className="mobile-nav">K1 Forge · 页面
          <select aria-label="切换页面" value={page} onChange={e => go(e.target.value)}>
            {PAGES.map(([id, , label]) => <option key={id} value={id}>{label}</option>)}
          </select>
        </label>
        <SystemBar />
        <div className="content">
          {page === "overview" && <Overview go={go} />}
          {page === "validation" && <Validation go={go} />}
          {page === "fleet" && <Fleet go={go} />}
          {page === "matches" && <Matches />}
          {page === "duels" && <Duels go={go} />}
          {page === "train" && <GaitLab go={go} />}
          {page === "packs" && <Packs go={go} />}
          {page === "dossier" && <DossierPage />}
          {page === "atlas" && <Atlas go={go} />}
          {page === "bridge" && <Bridge />}
          {page === "evals" && <Evals />}
          {page === "builds" && <Builds go={go} />}
          {page === "jobs" && <Jobs />}
          {page === "design" && <Design />}
        </div>
      </main>
    </div>
  );
}
