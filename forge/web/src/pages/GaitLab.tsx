import { useEffect, useMemo, useState } from "react";
import { api, Dict, TrainRun } from "../api";
import { LineChart, Series } from "../components/LineChart";
import { Badge, Card, Empty, Json, usePoll, useToast } from "../components/ui";

interface RunDetail {
  id: string;
  path: string;
  launch: Dict<any>;
  execution: Dict<any> | null;
  recipe: Dict<any> | null;
  metrics: Dict<number>[];
  checkpoints: { name: string; path: string; size: number }[];
}

const COMPONENTS = [
  ["双 critic · 优势 2:1", "任务组（速度/角速度跟踪 + 终止）与其余项分开估值，按火神论文 2A_goal + A_aux 合成优势"],
  ["特权量重建解码头", "挂在 actor 最后隐层（128）上重建 16 维特权观测；只在训练时存在，导出网络仍是 344→13"],
  ["AMP 风格先验", "专家数据 = B-Human 官方步态在同一环境里的滚动；判别器 (s,s′)，tanh(0.4D) 软边界 + 梯度惩罚"],
  ["镜像对称 + KL 守卫", "沿用 B-Human 镜像批与本机 KL 回滚、critic 预热、学习率自适应"],
];

function seriesOf(metrics: Dict<number>[], keys: [string, string, string][]): Series[] {
  return keys
    .filter(([k]) => metrics.some((m) => k in m))
    .map(([k, name, color]) => ({ name, color, points: metrics.filter((m) => k in m).map((m) => [m.iteration, Number(m[k])] as [number, number]) }));
}

export function GaitLab({ go }: { go: (page: string) => void }) {
  const toast = useToast();
  const runs = usePoll<TrainRun[]>("/api/train/runs", 10000);
  const presets = usePoll<Dict<{ label: string; config_patch: Dict; recipe: Dict }>>("/api/train/presets", 0);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [form, setForm] = useState({ preset: "thu-amp", envs: 4096, iterations: 400, seed: 42, timeout: 3600, save_interval: 50, checkpoint: "" });
  const [packName, setPackName] = useState("");
  useEffect(() => {
    if (!selected && runs.data?.length) setSelected(runs.data.find((r) => r.origin === "forge")?.id || runs.data[0].id);
  }, [runs.data, selected]);
  useEffect(() => {
    if (!selected) return;
    const load = () => api.get<RunDetail>(`/api/train/runs/${selected}`).then(setDetail).catch(() => setDetail(null));
    load();
    const handle = window.setInterval(load, 8000);
    return () => window.clearInterval(handle);
  }, [selected]);
  const submit = async (type: string, params: Dict) => {
    try {
      const res = await api.post<{ id: string }>("/api/jobs", { type, params });
      toast(`已提交作业 ${res.id}`);
      go("jobs");
    } catch (e: any) {
      toast(`提交失败：${e.message}`, true);
    }
  };
  const m = detail?.metrics || [];
  const charts = useMemo(
    () => [
      { title: "奖励（每步均值）", s: seriesOf(m, [["task_reward_mean", "任务", "#4ea1ff"], ["aux_reward_mean", "辅助", "#3fbf7f"], ["style_reward_mean", "风格(AMP)", "#e3b341"]]) },
      { title: "判别器输出", s: seriesOf(m, [["d_expert", "专家 D", "#3fbf7f"], ["d_policy", "策略 D", "#ef6464"]]) },
      { title: "特权量重建误差", s: seriesOf(m, [["recon_loss", "重建 MSE", "#9b8cff"]]) },
      { title: "策略更新 KL / 拒绝", s: seriesOf(m, [["kl_mean", "KL", "#4ea1ff"], ["rejected_updates", "拒绝次数", "#ef6464"]]) },
      { title: "价值损失", s: seriesOf(m, [["value_loss_task", "任务 critic", "#4ea1ff"], ["value_loss_aux", "辅助 critic", "#3fbf7f"], ["value_loss", "critic", "#4ea1ff"]]) },
      { title: "学习率", s: seriesOf(m, [["lr", "lr", "#e3b341"]]) },
    ],
    [m],
  );
  const run = runs.data?.find((r) => r.id === selected);
  return (
    <>
      <div className="page-title">
        <h2>步态实验室</h2>
        <p>B-Human K1 行走环境（奖励/观测/PD/资产原样）× 清华火神 Science Robotics 2026 算法层，导出仍可直接刷进 B-Human</p>
      </div>
      <div className="grid c2">
        <Card title="B-Human × 火神 配方" sub="契约保持：导出 actor = 344→256→128→128→13 ELU">
          <table>
            <tbody>
              {COMPONENTS.map(([k, v]) => (
                <tr key={k}><td style={{ whiteSpace: "nowrap" }}><b>{k}</b></td><td className="hint">{v}</td></tr>
              ))}
            </tbody>
          </table>
          <p className="hint">
            来源：Wang et al., <i>Learning vision-driven reactive soccer skills for humanoid robots</i>, Sci. Robot. 11, eaed1152 (2026)，代码 MIT（Zenodo 21620490）。
            训练出的候选默认是实验候选，没有评估与对抗赛证据不能晋级。
          </p>
        </Card>
        <Card title="启动训练" sub="Isaac Gym Preview 4 · bh-gym · GPU 与视觉比赛互斥">
          <div className="form">
            <label className="field">
              配方
              <select value={form.preset} onChange={(e) => setForm({ ...form, preset: e.target.value })}>
                {Object.entries(presets.data || {}).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </select>
            </label>
            {(["envs", "iterations", "seed", "timeout", "save_interval"] as const).map((k) => (
              <label className="field" key={k}>
                {{ envs: "环境数", iterations: "迭代轮数", seed: "种子", timeout: "超时(s)", save_interval: "保存间隔" }[k]}
                <input type="number" value={form[k]} onChange={(e) => setForm({ ...form, [k]: Number(e.target.value) })} />
              </label>
            ))}
            <label className="field" style={{ gridColumn: "span 2" }}>
              warm-start 起点（空 = 官方 K1_walk.pth）
              <input value={form.checkpoint} placeholder=".../nn/model_final.pth" onChange={(e) => setForm({ ...form, checkpoint: e.target.value })} />
            </label>
            <button className="btn primary" onClick={() => submit("train", { ...form, checkpoint: form.checkpoint || undefined })}>启动</button>
          </div>
          {presets.data?.[form.preset] && <Json value={presets.data[form.preset]} />}
        </Card>
      </div>
      <div className="grid" style={{ gridTemplateColumns: "minmax(320px, 0.8fr) 2.2fr" }}>
        <Card title="训练运行">
          {!runs.data ? (
            <Empty>加载中…</Empty>
          ) : (
            <table>
              <tbody>
                {runs.data.slice(0, 40).map((r) => (
                  <tr key={r.id} className={`clickable ${r.id === selected ? "selected" : ""}`} onClick={() => setSelected(r.id)}>
                    <td>
                      <div className="mono" style={{ fontSize: 11.5 }}>{r.id}</div>
                      <div className="hint" style={{ fontSize: 11 }}>
                        {r.origin === "forge" ? "火神配方" : "主线"} · {r.iterations} 轮{r.envs ? ` · ${r.envs} env` : ""}
                      </div>
                    </td>
                    <td><Badge value={r.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        {!detail ? (
          <Empty>选择一次训练</Empty>
        ) : (
          <div className="stack" style={{ gap: 16 }}>
            <Card title={detail.id} sub={detail.launch?.label || detail.launch?.command?.slice?.(-6)?.join?.(" ")} right={<Badge value={detail.execution?.status || "running"} />}>
              <div className="row">
                <span className="badge muted">{m.length} 轮</span>
                {detail.execution?.wall_s && <span className="badge muted">{Math.round(detail.execution.wall_s)} s</span>}
                {detail.execution?.sampled_gpu_peak_mib && <span className="badge muted">GPU 峰值 {detail.execution.sampled_gpu_peak_mib} MiB</span>}
                {detail.recipe && <span className="badge violet">专家 {String(detail.recipe.expert_sha256).slice(0, 10)}</span>}
                {detail.recipe && <span className="badge info">主线指纹 {String(detail.recipe.mainline_source_sha256).slice(0, 10)}</span>}
              </div>
            </Card>
            <div className="grid c2">
              {charts.map((c) => (
                <Card key={c.title}>
                  <LineChart title={c.title} series={c.s} />
                </Card>
              ))}
            </div>
            <Card title="检查点" sub="导出 = 主线 run_export.sh（actor 严格加载 + PyTorch/TorchScript/ORT 三方校验）→ 运控包">
              {detail.checkpoints.length === 0 ? (
                <Empty>暂无检查点</Empty>
              ) : (
                <>
                  <div className="row" style={{ marginBottom: 8 }}>
                    <label className="field" style={{ flex: 1 }}>
                      运控包名称
                      <input value={packName} placeholder={`${run?.preset || "candidate"}-${detail.id.slice(0, 8)}`} onChange={(e) => setPackName(e.target.value)} />
                    </label>
                  </div>
                  <table>
                    <tbody>
                      {detail.checkpoints.slice(-8).reverse().map((c) => (
                        <tr key={c.path}>
                          <td className="mono">{c.name}</td>
                          <td className="hint">{(c.size / 1e6).toFixed(1)} MB</td>
                          <td style={{ textAlign: "right" }}>
                            <button className="btn small" onClick={() => submit("eval", { policy: c.path })}>行走评估</button>{" "}
                            <button className="btn small" title="导出→Isaac Gym 评估→MuJoCo Warp 压力→SimRobot 系列赛→晋级门" onClick={() => submit("pipeline", { checkpoint: c.path, name: packName || `${run?.preset || "candidate"}-${detail.id.slice(0, 8)}-${c.name.replace(".pth", "")}`, rounds: 2, push_force: 60 })}>候选全流程</button>{" "}
                            <button className="btn small primary" onClick={() => submit("export", { checkpoint: c.path, name: packName || `${run?.preset || "candidate"}-${detail.id.slice(0, 8)}-${c.name.replace(".pth", "")}` })}>
                              导出为运控包
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
            </Card>
          </div>
        )}
      </div>
    </>
  );
}
