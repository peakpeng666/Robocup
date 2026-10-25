import { useState } from "react";
import { api, Dict, Pack, short } from "../api";
import { Badge, Card, Checks, Empty, usePoll, useToast } from "../components/ui";

interface BuildReceipt {
  status: string;
  target: string;
  kind: string;
  variant: string;
  started_at: string;
  ended_at: string;
  toolchain: Dict<string>;
  products: Dict<{ exists: boolean; sha256: string | null; size: number | null }>;
  elf?: { status: string; checks: Dict<boolean>; details: { needed: string[]; interpreter: string; sdk_topic_markers: string[]; sha256: string; size: number; file: string }; scope: string };
  log: string;
}

interface Variant {
  name: string;
  description: string;
  created_at: string;
  patches: { file: string; sha256: string }[];
  util_linked: string[];
  util_copied: string[];
  source_sha256: string;
  files_changed_vs_base: string[];
  builds: Dict<BuildReceipt>;
}

export function Builds({ go }: { go: (page: string) => void }) {
  const toast = useToast();
  const variants = usePoll<Variant[]>("/api/variants", 8000);
  const [form, setForm] = useState({ name: "", description: "" });
  const [build, setBuild] = useState<Dict<{ target: string; kind: string }>>({});
  const packs = usePoll<Pack[]>("/api/packs", 15000);
  const bundles = usePoll<Dict<any>[]>("/api/bundles", 15000);
  const [bundle, setBundle] = useState({ variant: "base", pack_id: "" });
  const makeBundle = async () => {
    try {
      const res = await api.post<{ id: string }>("/api/jobs", { type: "bundle", params: bundle });
      toast(`已提交离线包作业 ${res.id}`);
      go("jobs");
    } catch (e: any) {
      toast(e.message, true);
    }
  };
  const create = async () => {
    try {
      await api.post("/api/variants", form);
      toast(`已建立源码变体 ${form.name}`);
      setForm({ name: "", description: "" });
      variants.reload();
    } catch (e: any) {
      toast(e.message, true);
    }
  };
  const submit = async (variant: string) => {
    const choice = build[variant] || { target: "booster", kind: "Release" };
    try {
      const res = await api.post<{ id: string }>("/api/jobs", { type: "build", params: { variant, ...choice, jobs: 12 } });
      toast(`已提交编译 ${res.id}`);
      go("jobs");
    } catch (e: any) {
      toast(e.message, true);
    }
  };
  return (
    <>
      <div className="page-title">
        <h2>编译农场</h2>
        <p>同一源码变体同时编译仿真程序（SimRobot x86_64）与机器人程序（Booster AArch64 + Booster SDK + FastDDS）；从不调用部署/安装目标</p>
      </div>
      <Card title="新建源码变体" sub="复制 bhuman-local 的 Src/Make/Config/Install；大型第三方 Util 只读链接；补丁栈用 CLI：forge variant create NAME --patch x.patch">
        <div className="form">
          <label className="field">
            名称
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="walk-tuning-a" />
          </label>
          <label className="field" style={{ gridColumn: "span 2" }}>
            说明
            <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </label>
          <button className="btn primary" disabled={!form.name} onClick={create}>建立</button>
        </div>
      </Card>
      <Card title="离线机器人包" sub="Booster AArch64 程序 + Config + 运控包 scenario（按真机 Robots/Default/K1 基准打补丁）+ manifest + verify.py；不安装、不部署">
        <div className="form">
          <label className="field">
            源码变体（需 booster 构建通过）
            <select value={bundle.variant} onChange={(e) => setBundle({ ...bundle, variant: e.target.value })}>
              {(variants.data || []).map((v) => <option key={v.name} value={v.name}>{v.name}</option>)}
            </select>
          </label>
          <label className="field" style={{ gridColumn: "span 2" }}>
            运控包
            <select value={bundle.pack_id} onChange={(e) => setBundle({ ...bundle, pack_id: e.target.value })}>
              <option value="">选择…</option>
              {(packs.data || []).map((p) => <option key={p.id} value={p.id}>{p.name} — {p.id}</option>)}
            </select>
          </label>
          <button className="btn primary" disabled={!bundle.pack_id} onClick={makeBundle}>生成离线包</button>
        </div>
        {bundles.data && bundles.data.length > 0 && (
          <table style={{ marginTop: 10 }}>
            <thead><tr><th>离线包</th><th>运控包</th><th>scenario</th><th className="num">文件</th><th className="num">大小</th><th>归档 SHA256</th></tr></thead>
            <tbody>
              {bundles.data.map((b) => (
                <tr key={b.id}>
                  <td className="mono hint" style={{ fontSize: 11.5 }}>{b.id.slice(0, 22)}</td>
                  <td className="mono">{b.pack?.id}</td>
                  <td className="mono hint">{b.scenario}</td>
                  <td className="num">{b.file_count}</td>
                  <td className="num">{b.size_mb} MB</td>
                  <td className="mono">{short(b.archive_sha256, 12)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {!variants.data ? (
        <Empty>加载中…</Empty>
      ) : variants.data.length === 0 ? (
        <Empty>还没有源码变体</Empty>
      ) : (
        variants.data.map((v) => (
          <Card key={v.name} title={v.name} sub={`${v.description || ""} · 源码 ${short(v.source_sha256)} · 相对基准改动 ${v.files_changed_vs_base.length} 个文件 · 补丁 ${v.patches.length}`}>
            <div className="row" style={{ marginBottom: 10 }}>
              <select value={build[v.name]?.target || "booster"} onChange={(e) => setBuild({ ...build, [v.name]: { target: e.target.value, kind: build[v.name]?.kind || "Release" } })}>
                <option value="booster">Booster 机器人程序 (AArch64 + SDK)</option>
                <option value="simrobot">SimRobot 仿真程序 (x86_64)</option>
              </select>
              <select value={build[v.name]?.kind || "Release"} onChange={(e) => setBuild({ ...build, [v.name]: { target: build[v.name]?.target || "booster", kind: e.target.value } })}>
                <option>Release</option>
                <option>Develop</option>
              </select>
              <button className="btn primary" onClick={() => submit(v.name)}>编译</button>
              <span className="hint">链接的第三方：{v.util_linked.join("、")}</span>
            </div>
            {Object.keys(v.builds).length === 0 ? (
              <Empty>尚未编译</Empty>
            ) : (
              <div className="grid c2">
                {Object.entries(v.builds).map(([key, b]) => (
                  <div key={key} className="card" style={{ background: "#101824" }}>
                    <div className="row between">
                      <b>{key}</b>
                      <Badge value={b.status} />
                    </div>
                    <div className="hint">{b.started_at?.slice(0, 19)} → {b.ended_at?.slice(11, 19)} · {b.toolchain?.["clang++"]}</div>
                    <table style={{ marginTop: 6 }}>
                      <tbody>
                        {Object.entries(b.products).map(([p, info]) => (
                          <tr key={p}>
                            <td className="mono" style={{ fontSize: 11.5 }}>{p}</td>
                            <td className="mono">{info.exists ? short(info.sha256, 12) : "缺失"}</td>
                            <td className="num hint">{info.size ? (info.size / 1e6).toFixed(1) + " MB" : ""}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {b.elf && (
                      <>
                        <div className="sep" />
                        <Checks checks={b.elf.checks} />
                        <div className="hint" style={{ marginTop: 6 }}>NEEDED：<span className="mono">{b.elf.details.needed.join(" ")}</span></div>
                        <div className="hint">SDK 话题：<span className="mono">{b.elf.details.sdk_topic_markers.filter((m) => !m.includes("Transport") && !m.includes("Channel") && !m.includes("shared_mem") && !m.includes("tcp/")).join(" ")}</span></div>
                        <div className="hint">{b.elf.scope}</div>
                      </>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Card>
        ))
      )}
    </>
  );
}
