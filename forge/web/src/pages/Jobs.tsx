import { useEffect, useRef, useState } from "react";
import { api, Dict, Job, fmtTime } from "../api";
import { Badge, Card, Empty, Json, usePoll, useToast } from "../components/ui";

const LIMIT = 400_000;

export function Jobs() {
  const toast = useToast();
  const jobs = usePoll<{ jobs: Job[]; types: Dict<string> }>("/api/jobs", 3000);
  const [selected, setSelected] = useState<string | null>(null);
  const [log, setLog] = useState("");
  const [follow, setFollow] = useState(true);
  const pre = useRef<HTMLPreElement>(null);
  useEffect(() => {
    if (!selected && jobs.data?.jobs.length) setSelected(jobs.data.jobs[0].id);
  }, [jobs.data, selected]);
  useEffect(() => {
    if (!selected) return;
    setLog("");
    const source = new EventSource(`/api/jobs/${selected}/stream`);
    source.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.text) setLog((prev) => (prev + data.text).slice(-LIMIT));
      if (data.done) source.close();
    };
    source.onerror = () => source.close();
    return () => source.close();
  }, [selected]);
  useEffect(() => {
    if (follow && pre.current) pre.current.scrollTop = pre.current.scrollHeight;
  }, [log, follow]);
  const job = jobs.data?.jobs.find((j) => j.id === selected);
  const cancel = async () => {
    if (!job) return;
    try {
      await api.post(`/api/jobs/${job.id}/cancel`);
      toast("已请求取消（仅终止该作业自己的进程组）");
      jobs.reload();
    } catch (e: any) {
      toast(e.message, true);
    }
  };
  return (
    <>
      <div className="page-title">
        <h2>作业</h2>
        <p>白名单作业 → forge CLI 子进程；资源令牌并发调度（gpu / display / simlock / cpu_heavy / arena）；重启后未完成作业标记中断、不自动重跑</p>
      </div>
      <div className="grid jobs-layout">
        <Card title="作业列表">
          {!jobs.data?.jobs.length ? (
            <Empty>暂无作业</Empty>
          ) : (
            <table>
              <thead>
                <tr><th>类型</th><th>创建</th><th>资源</th><th>状态</th></tr>
              </thead>
              <tbody>
                {jobs.data.jobs.map((j) => (
                  <tr key={j.id} className={`clickable ${j.id === selected ? "selected" : ""}`} onClick={() => setSelected(j.id)}>
                    <td>{jobs.data!.types[j.type] || j.type}</td>
                    <td className="mono hint" style={{ fontSize: 11.5 }}>{fmtTime(j.created_at).slice(5)}</td>
                    <td className="hint" style={{ fontSize: 11.5 }}>{(j.resources || []).join(" ")}</td>
                    <td><Badge value={j.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        {!job ? (
          <Empty>选择作业</Empty>
        ) : (
          <div className="stack" style={{ gap: 16 }}>
            <Card
              title={job.id}
              right={
                <div className="row">
                  <Badge value={job.status} />
                  {(job.status === "running" || job.status === "queued") && <button className="btn danger small" onClick={cancel}>取消</button>}
                </div>
              }
            >
              <div className="row hint">
                <span>开始 {fmtTime(job.started_at)}</span>
                <span>结束 {fmtTime(job.ended_at)}</span>
                <span>退出码 {job.exit_code ?? "—"}</span>
                <span>PID {job.pid ?? "—"}</span>
              </div>
              <div className="sep" />
              <div className="mono" style={{ fontSize: 12, wordBreak: "break-all" }}>{job.argv.join(" ")}</div>
              <div className="sep" />
              <Json value={job.params} />
            </Card>
            <Card title="实时日志" right={<label className="hint"><input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> 跟随</label>}>
              <pre className="log" ref={pre}>{log || "（等待输出）"}</pre>
            </Card>
          </div>
        )}
      </div>
    </>
  );
}
