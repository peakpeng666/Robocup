import { useEffect, useState } from "react";
import { api, Dict, Pack, short } from "../api";
import { Badge, Card, Checks, Empty, Json, usePoll, useToast } from "../components/ui";

interface Contract {
  id: string;
  label: string;
  inputs: number;
  outputs: number;
  consumer: string;
  cfg_file: string | null;
  cfg_key: string | null;
  layout: [string, string][];
  flashable: boolean;
}

export function Packs({ go }: { go: (page: string) => void }) {
  const toast = useToast();
  const packs = usePoll<Pack[]>("/api/packs", 10000);
  const contracts = usePoll<Dict<Contract>>("/api/contracts", 0);
  const [selected, setSelected] = useState<string | null>(null);
  const [verify, setVerify] = useState<{ status: string; checks: Dict<boolean> } | null>(null);
  useEffect(() => {
    if (!selected && packs.data?.length) setSelected(packs.data[0].id);
  }, [packs.data, selected]);
  useEffect(() => setVerify(null), [selected]);
  const pack = packs.data?.find((p) => p.id === selected);
  const stress = async (pushForce: number) => {
    if (!pack) return;
    try {
      const res = await api.post<{ id: string }>("/api/jobs", { type: "stress", params: { pack_id: pack.id, worlds: 2048, seconds: 20, push_force: pushForce, tag: `${pack.id}-p${pushForce}` } });
      toast(`已提交 MuJoCo Warp 压力评测 ${res.id}`);
      go("jobs");
    } catch (e: any) {
      toast(e.message, true);
    }
  };
  const runVerify = async () => {
    if (!pack) return;
    try {
      setVerify(await api.post(`/api/packs/${pack.id}/verify`));
    } catch (e: any) {
      toast(e.message, true);
    }
  };
  return (
    <>
      <div className="page-title">
        <h2>运控包</h2>
        <p>内容寻址、不可变；按 B-Human C++ 消费方断言的契约核对网络图，扩展名不代表兼容</p>
      </div>
      <Card title="策略契约" sub="B-Human WalkingEngine / GetUpEngine 在加载时断言的输入输出">
        <table>
          <thead>
            <tr><th>槽位</th><th>契约</th><th className="num">输入</th><th className="num">输出</th><th>C++ 消费方</th><th>刷写键</th><th>可配置刷写</th></tr>
          </thead>
          <tbody>
            {Object.entries(contracts.data || {}).map(([slot, c]) => (
              <tr key={slot}>
                <td>{c.label} <span className="mono hint">{slot}</span></td>
                <td className="mono">{c.id}</td>
                <td className="num">{c.inputs}</td>
                <td className="num">{c.outputs}</td>
                <td className="mono">{c.consumer}</td>
                <td className="mono hint">{c.cfg_file ? `${c.cfg_file}: ${c.cfg_key}` : "—"}</td>
                <td>{c.flashable ? <span className="badge ok">是</span> : <span className="badge muted">需代码级变体</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <div className="grid" style={{ gridTemplateColumns: "minmax(320px, 0.9fr) 2fr" }}>
        <Card title="包列表" sub={`${packs.data?.length ?? 0} 个`}>
          {!packs.data ? (
            <Empty>加载中…</Empty>
          ) : (
            <table>
              <tbody>
                {packs.data.map((p) => (
                  <tr key={p.id} className={`clickable ${p.id === selected ? "selected" : ""}`} onClick={() => setSelected(p.id)}>
                    <td>
                      <div><b>{p.name}</b></div>
                      <div className="mono hint" style={{ fontSize: 11 }}>{p.id}</div>
                    </td>
                    <td><Badge value={p.kind === "baseline" ? "baseline" : p.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="hint">新建候选包：在「步态实验室」选择检查点 → 导出为运控包（主线导出 + 三方数值校验）。</p>
        </Card>
        {!pack ? (
          <Empty>选择一个运控包</Empty>
        ) : (
          <div className="stack" style={{ gap: 16 }}>
            <Card
              title={pack.name}
              sub={pack.id}
              right={
                <div className="row">
                  <button className="btn" onClick={runVerify}>重新校验</button>
                  <button className="btn" onClick={() => stress(0)}>压力评测·无推扰</button>
                  <button className="btn" onClick={() => stress(60)}>压力评测·60 N 推扰</button>
                </div>
              }
            >
              <p style={{ marginTop: 0 }}>{pack.description || <span className="hint">无说明</span>}</p>
              {verify && (
                <div style={{ marginBottom: 10 }}>
                  <Badge value={verify.status} /> <Checks checks={verify.checks} />
                </div>
              )}
              <table>
                <thead>
                  <tr><th>槽位</th><th>契约</th><th>SHA256</th><th className="num">参数量</th><th>opset</th><th>ORT 冒烟</th></tr>
                </thead>
                <tbody>
                  {Object.entries(pack.components).map(([slot, c]) => (
                    <tr key={slot}>
                      <td>{slot}</td>
                      <td className="mono">{c.contract}</td>
                      <td className="mono">{short(c.sha256, 16)}</td>
                      <td className="num">{c.onnx?.parameters?.toLocaleString() ?? "官方"}</td>
                      <td>{c.onnx?.opset ?? "—"}</td>
                      <td className="mono hint">{c.onnx?.ort_smoke ? `max|y|=${Number((c.onnx.ort_smoke as any).max_abs_output).toFixed(3)}` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {Object.keys(pack.cfg_patches || {}).length > 0 && (
                <>
                  <div className="sep" />
                  <b>配置修改</b>
                  <Json value={pack.cfg_patches} />
                </>
              )}
            </Card>
            <Card title="来源与证据" sub="训练运行 / 检查点 / 导出三方校验">
              {Object.keys(pack.provenance || {}).length === 0 ? <Empty>无</Empty> : <Json value={pack.provenance} />}
            </Card>
          </div>
        )}
      </div>
    </>
  );
}
