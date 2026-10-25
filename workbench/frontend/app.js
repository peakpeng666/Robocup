/* RoboCup 工作台前端：无构建 vanilla JS。所有 API 调用走同源 + 会话 cookie。 */
"use strict";

const $ = (sel) => document.querySelector(sel);
const el = (tag, attrs = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else node.setAttribute(k, v);
  }
  for (const c of children) node.append(c);
  return node;
};

async function api(path, opts = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" }, ...opts,
  });
  const text = await resp.text();
  let data = null;
  try { data = JSON.parse(text); } catch { data = { raw: text }; }
  if (!resp.ok) throw new Error(data.error || resp.statusText);
  return data;
}

function badge(text) {
  return el("span", { class: "badge " + String(text), text: String(text) });
}

function fmtTime(iso) {
  return iso ? String(iso).replace("T", " ").slice(0, 19) : "-";
}

/* ---------------------------------------------------------------- tabs */
document.querySelectorAll("#tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll("main .tab").forEach((s) => s.classList.remove("active"));
    $("#tab-" + btn.dataset.tab).classList.add("active");
    const lazy = { workflows: loadTasks, jobs: loadJobs, models: loadModels,
                   evidence: loadEvidence, matrix: loadMatrix, env: loadCaps,
                   offline: loadOffline, overview: loadGraph }[btn.dataset.tab];
    if (lazy) lazy();
  });
});

/* ------------------------------------------------------------- overview */
const KIND_ORDER = ["source", "config", "model", "checkpoint", "interpreter",
                    "binary", "runtime", "artifact"];
const KIND_LABEL = { source: "源码", config: "配置", model: "模型", checkpoint: "检查点",
                     interpreter: "解释器/环境", binary: "构建程序", runtime: "仿真/训练",
                     artifact: "离线产物" };

async function loadGraph() {
  const data = await api("/api/graph");
  renderGraph(data);
  renderChains();
}

function renderGraph(data) {
  const svg = $("#graph");
  svg.innerHTML = "";
  const NS = "http://www.w3.org/2000/svg";
  const defs = document.createElementNS(NS, "defs");
  defs.innerHTML = '<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#38506b"/></marker>';
  svg.append(defs);
  const layers = {};
  KIND_ORDER.forEach((k, i) => { layers[k] = i; });
  const byLayer = {};
  for (const n of data.nodes) {
    const l = layers[n.kind] ?? 5;
    (byLayer[l] = byLayer[l] || []).push(n);
  }
  const pos = {};
  const W = 1200, layerW = W / (Object.keys(byLayer).length + 0.4);
  let maxRows = 0;
  Object.values(byLayer).forEach((arr) => { maxRows = Math.max(maxRows, arr.length); });
  svg.setAttribute("height", Math.max(560, maxRows * 64 + 40));
  for (const [l, arr] of Object.entries(byLayer)) {
    arr.forEach((n, i) => {
      pos[n.id] = { x: 20 + Number(l) * layerW, y: 30 + i * 64 };
    });
  }
  for (const e of data.edges) {
    const a = pos[e.from], b = pos[e.to];
    if (!a || !b) continue;
    const line = document.createElementNS(NS, "line");
    line.setAttribute("x1", a.x + 150); line.setAttribute("y1", a.y + 20);
    line.setAttribute("x2", b.x); line.setAttribute("y2", b.y + 20);
    line.setAttribute("class", "edge");
    line.innerHTML = `<title>${e.rel}</title>`;
    svg.append(line);
  }
  const colorFor = (st) => ({ VERIFIED: "#3fb96c", PASS: "#3fb96c", STALE: "#d8a531",
    BLOCKED: "#e05d5d", NOT_FOUND: "#e05d5d", INSTALLED: "#3d9df2" }[st] || "#8ba0b4");
  for (const n of data.nodes) {
    const p = pos[n.id];
    if (!p) continue;
    const g = document.createElementNS(NS, "g");
    g.setAttribute("class", "node");
    g.innerHTML = `<rect x="${p.x}" y="${p.y}" width="150" height="46" rx="6" style="stroke:${colorFor(n.status)};stroke-width:1.5"/>` +
      `<text x="${p.x + 8}" y="${p.y + 17}">${esc(short(n.label, 15))}</text>` +
      `<text class="st" x="${p.x + 8}" y="${p.y + 34}" fill="${colorFor(n.status)}">${esc(n.status)}</text>`;
    g.addEventListener("click", () => showNode(n, data));
    svg.append(g);
  }
  // layer captions
  for (const [l, arr] of Object.entries(byLayer)) {
    const t = document.createElementNS(NS, "text");
    t.setAttribute("x", 20 + Number(l) * layerW + 4);
    t.setAttribute("y", 14);
    t.setAttribute("fill", "#8ba0b4");
    t.setAttribute("font-size", "10");
    t.textContent = KIND_LABEL[arr[0].kind] || arr[0].kind;
    svg.append(t);
  }
}

function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
function short(s, n) { return s.length > n ? s.slice(0, n - 1) + "…" : s; }

function showNode(n) {
  const panel = $("#node-detail");
  panel.classList.remove("hidden");
  let html = `<h3>${esc(n.label)} <span class="badge ${n.status}">${n.status}</span></h3><div class="kv">`;
  if (n.path) html += `<div><b>路径</b><code>${esc(n.path)}</code></div>`;
  if (n.upstream_sha) html += `<div><b>上游 SHA</b><code>${n.upstream_sha}</code></div>`;
  if (n.fingerprint) html += `<div><b>源码指纹</b><code>${n.fingerprint}</code></div>`;
  if (n.sha256) html += `<div><b>SHA256</b><code>${n.sha256}</code></div>`;
  if (n.note) html += `<div><b>说明</b>${esc(n.note)}</div>`;
  if (n.last_pass) html += `<div><b>最近通过 run</b><code>${esc(n.last_pass)}</code></div>`;
  if (n.probe) html += `<div><b>主动探测</b><pre class="code">${esc(JSON.stringify(n.probe, null, 2))}</pre></div>`;
  panel.innerHTML = html + "</div>";
}

async function renderChains() {
  const ev = await api("/api/evidence");
  const wrap = $("#chain-cards");
  wrap.innerHTML = "";
  const chains = [
    { id: "bhuman", label: "B-Human 比赛/步态", desc: "正常渲染相机 + 官方 WalkingEngine；哈希保护" },
    { id: "sim2sim", label: "MuJoCo sim2sim", desc: "CPU actor + MuJoCo 3.8；默认官方行走策略" },
    { id: "training", label: "训练主线", desc: "Isaac Gym Preview 4 / Py3.8；受控配方" },
  ];
  for (const c of chains) {
    const latest = ev.entries.find((e) => e.chain === c.id);
    const card = el("div", { class: "card" });
    card.append(el("h3", { text: c.label }));
    card.append(el("div", { class: "meta", text: c.desc }));
    if (latest) {
      card.append(el("div", {}, document.createTextNode("最近 run：" + latest.name + " "), badge(latest.verdict)));
    } else {
      card.append(el("div", { class: "meta", text: "暂无证据" }));
    }
    wrap.append(card);
  }
}

/* ------------------------------------------------------------ workflows */
let TASKS = null;
let selectedTask = null;

async function loadTasks() {
  if (!TASKS) TASKS = (await api("/api/tasks")).tasks;
  const wrap = $("#task-list");
  wrap.innerHTML = "";
  for (const [id, t] of Object.entries(TASKS)) {
    const card = el("div", { class: "card" });
    card.append(el("h3", { text: t.label }));
    card.append(el("div", { class: "meta", text: `${t.chain} · ${t.desc}` }));
    const btn = el("button", { text: "配置并运行" });
    btn.addEventListener("click", () => openTaskForm(id));
    card.append(el("div", { style: "margin-top:8px" }, btn));
    wrap.append(card);
  }
}

function openTaskForm(id) {
  selectedTask = id;
  const t = TASKS[id];
  $("#task-form-wrap").classList.remove("hidden");
  $("#task-form-title").textContent = t.label;
  $("#task-form-desc").textContent = t.desc;
  $("#task-preview").classList.add("hidden");
  const form = $("#task-form");
  form.innerHTML = "";
  for (const f of t.form) {
    const row = el("div", { class: "field" });
    row.append(el("label", { text: f.label }));
    let input;
    if (f.type === "bool") {
      input = el("input", { type: "checkbox", name: f.name });
      input.checked = !!f.default;
    } else if (f.type === "enum") {
      input = el("select", { name: f.name });
      for (const c of f.choices) input.append(el("option", { value: c, text: c }));
      input.value = f.default;
    } else {
      input = el("input", { type: f.type === "int" ? "number" : "text", name: f.name });
      if (f.type === "int") {
        input.min = f.min; input.max = f.max;
        input.value = f.default;
      } else if (f.default) input.value = f.default;
    }
    row.append(input);
    form.append(row);
  }
}

function formParams() {
  const t = TASKS[selectedTask];
  const params = {};
  for (const f of t.form) {
    const input = $("#task-form").elements[f.name];
    if (f.type === "bool") params[f.name] = input.checked;
    else if (f.type === "int") { if (input.value !== "") params[f.name] = Number(input.value); }
    else { if (input.value.trim() !== "") params[f.name] = input.value.trim(); }
  }
  return params;
}

$("#btn-preview").addEventListener("click", async () => {
  const pre = $("#task-preview");
  try {
    const data = await api("/api/jobs/preview", { method: "POST",
      body: JSON.stringify({ type: selectedTask, params: formParams() }) });
    pre.textContent = "argv: " + JSON.stringify(data.argv, null, 2) +
      "\ncwd: " + data.cwd + "\n超时: " + data.timeout + "s\n资源锁: " + data.resources.join(", ");
    pre.classList.remove("hidden");
  } catch (e) {
    pre.textContent = "参数错误: " + e.message;
    pre.classList.remove("hidden");
  }
});

$("#btn-run").addEventListener("click", async () => {
  if (!selectedTask) return;
  try {
    const data = await api("/api/jobs", { method: "POST",
      body: JSON.stringify({ type: selectedTask, params: formParams() }) });
    document.querySelector('#tabs button[data-tab="jobs"]').click();
    setTimeout(() => openJob(data.job_id), 400);
  } catch (e) {
    alert("启动被拒绝: " + e.message);
  }
});

/* ---------------------------------------------------------------- jobs */
let currentJob = null;
let evtSource = null;

async function loadJobs() {
  const data = await api("/api/jobs");
  const tbody = $("#jobs-table tbody");
  tbody.innerHTML = "";
  for (const j of data.jobs) {
    const tr = el("tr");
    tr.append(el("td", { text: j.job_id }), el("td", { text: (TASKS && TASKS[j.type] ? TASKS[j.type].label : j.type) }));
    tr.append(el("td", {}, badge(j.status)));
    tr.append(el("td", {}, badge(j.quality_verdict), badge(j.evidence_status || "UNVERIFIED")));
    tr.append(el("td", { text: j.exit_code ?? "-" }));
    tr.append(el("td", { text: fmtTime(j.created_at) }));
    const open = el("button", { text: "详情" });
    open.addEventListener("click", () => openJob(j.job_id));
    tr.append(el("td", {}, open));
    tbody.append(tr);
  }
}

async function openJob(job_id) {
  currentJob = job_id;
  const d = await api("/api/jobs/" + job_id);
  if (currentJob !== job_id) return;
  $("#job-result").classList.add("hidden");
  $("#job-result").textContent = "";
  document.querySelector("#eval-comparison")?.remove();
  $("#job-detail").classList.remove("hidden");
  $("#job-detail-title").textContent = job_id;
  const meta = $("#job-meta");
  meta.innerHTML = "";
  const kv = el("div", { class: "kv" });
  kv.innerHTML =
    `<div><b>类型</b>${esc(d.type)}</div>` +
    `<div><b>状态</b>${d.status} · 质量判定 ${d.quality_verdict} · 当前身份 ${d.evidence_status}</div>` +
    `<div><b>argv</b><code>${esc(JSON.stringify(JSON.parse(d.argv_json || "[]")))}</code></div>` +
    `<div><b>cwd</b><code>${esc(d.cwd || "")}</code></div>` +
    `<div><b>时间</b>${fmtTime(d.started_at)} → ${fmtTime(d.ended_at)}</div>` +
    (d.run_dir ? `<div><b>run 目录</b><code>${esc(d.run_dir)}</code></div>` : "") +
    (d.exit_code !== null ? `<div><b>退出码</b>${d.exit_code}</div>` : "");
  meta.append(kv);
  if (d.artifacts && d.artifacts.length) {
    const ul = el("ul");
    for (const a of d.artifacts) {
      const li = el("li");
      const link = el("a", { href: "#", text: `${a.kind}: ${a.path}` });
      link.addEventListener("click", (ev) => { ev.preventDefault(); showArtifact(a.id); });
      li.append(link, document.createTextNode(a.size ? ` (${(a.size / 1024).toFixed(1)} KB)` : ""));
      ul.append(li);
    }
    meta.append(el("h4", { text: "登记产物" }), ul);
  }
  streamLog(job_id, d.status);
}

async function showArtifact(id) {
  const info = await api("/api/artifacts/" + id);
  const pre = $("#job-result");
  pre.classList.remove("hidden");
  let text = `产物 #${id}: ${info.path}\nSHA256: ${info.sha256 || "-"}\n`;
  if (info.preview) text += "\n" + info.preview;
  else text += "\n(二进制或过大，使用下载)";
  pre.textContent = text;
  const link = el("a", {href:"/api/artifacts/"+id+"/download",text:"下载此产物", download:""});
  pre.after(link);
}

function streamLog(job_id, status) {
  if (evtSource) { evtSource.close(); evtSource = null; }
  const log = $("#job-log");
  log.textContent = "";
  if (["succeeded", "failed", "cancelled", "timed_out", "interrupted"].includes(status)) {
    api("/api/jobs/" + job_id + "/log?offset=0").then((d) => { log.textContent = d.data; log.scrollTop = log.scrollHeight; });
    return;
  }
  evtSource = new EventSource("/api/jobs/" + job_id + "/events");
  evtSource.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.line) { log.textContent = (log.textContent + msg.line).slice(-200000); log.scrollTop = log.scrollHeight; }
    if (msg.done) { evtSource.close(); loadJobs(); openJob(job_id); }
  };
}

$("#btn-cancel").addEventListener("click", async () => {
  if (!currentJob) return;
  await api("/api/jobs/" + currentJob + "/cancel", { method: "POST", body: "{}" });
  setTimeout(loadJobs, 600);
});
$("#btn-load-result").addEventListener("click", async () => {
  const d = await api("/api/jobs/" + currentJob);
  const pre = $("#job-result");
  pre.classList.remove("hidden");
  pre.textContent = JSON.stringify(d.result || d, null, 2);
  if (d.type === "train_walk_eval" && d.result && d.result.segments) await showEvaluation(d);
});
$("#btn-refresh-jobs").addEventListener("click", loadJobs);

/* --------------------------------------------------------------- models */
async function loadModels() {
  const data = await api("/api/models");
  const wrap = $("#models-wrap");
  wrap.innerHTML = "";
  for (const c of data.contracts) {
    const panel = el("div", { class: "panel" });
    let html = `<h3>${esc(c.label)} <code>${c.input_dim}→${c.output_dim}</code></h3><div class="kv">`;
    html += `<div><b>输出语义</b>${esc(c.output_meaning || "-")}</div>`;
    if (c.actor_arch) html += `<div><b>网络结构</b>${esc(c.actor_arch)}</div>`;
    if (c.history) html += `<div><b>历史布局</b>${esc(c.history)}</div>`;
    if (c.tail) html += `<div><b>输入尾部</b>${esc(c.tail)}</div>`;
    if (c.decode) html += `<div><b>解码/限幅</b>${esc(c.decode)}</div>`;
    if (c.units) html += `<div><b>单位/周期</b>${esc(c.units)}</div>`;
    for (const key of ["official_pth_file", "official_onnx_file"]) {
      const f = c[key];
      if (!f) continue;
      const st = f.exists ? (f.identity_match === true ? "VERIFIED" : (f.identity_match === false ? "STALE" : "PRESENT")) : "NOT_FOUND";
      html += `<div><b>${key}</b><code>${esc(f.path)}</code> <span class="badge ${st}">${st}</span>`;
      if (f.sha256) html += `<br><b></b><code>sha256=${f.sha256}</code>`;
      html += "</div>";
    }
    if (c.note) html += `<div><b>注意</b>${esc(c.note)}</div>`;
    panel.innerHTML = html + "</div>";
    wrap.append(panel);
  }
}

/* ------------------------------------------------------------- evidence */
async function loadEvidence() {
  const data = await api("/api/evidence");
  const tbody = $("#evidence-table tbody");
  tbody.innerHTML = "";
  for (const e of data.entries.slice(0, 120)) {
    const tr = el("tr");
    tr.append(el("td", { text: e.chain }));
    const nameTd = el("td", { text: e.name });
    tr.append(nameTd);
    tr.append(el("td", {}, badge(e.verdict), document.createTextNode(" / 运行 "), badge(e.execution_status), badge(e.current_status)));
    tr.append(el("td", { text: e.exit_code ?? "-" }));
    tr.append(el("td", { text: e.wall_s ? Number(e.wall_s).toFixed(1) : "-" }));
    tr.append(el("td", { text: e.created_at || "-" }));
    const filesTd = el("td");
    for (const f of (e.files || []).slice(0, 8)) {
      const link = el("a", { href: "#", text: f, style: "margin-right:6px;font-size:11px" });
      link.addEventListener("click", (ev) => { ev.preventDefault(); showEvidenceFile(e.run_dir, f); });
      filesTd.append(link);
    }
    if ((e.media || []).length) {
      const v = el("a", { href: "#", text: "▶ " + e.media[0], style: "font-size:11px" });
      v.addEventListener("click", (ev) => { ev.preventDefault(); showVideo(e.run_dir, e.media[0]); });
      filesTd.append(v);
    }
    tr.append(filesTd);
    tbody.append(tr);
  }
}

async function showEvidenceFile(run_dir, name) {
  const panel = $("#evidence-detail");
  panel.classList.remove("hidden");
  try {
    const resp = await fetch("/api/raw?path=" + encodeURIComponent(run_dir + "/" + name));
    if (!resp.ok) throw new Error((await resp.json()).error || resp.statusText);
    const text = await resp.text();
    if (name === "metrics.jsonl") return showMetrics(text, panel);
    let pretty = text;
    try { pretty = JSON.stringify(JSON.parse(text), null, 2); } catch {}
    panel.innerHTML = `<h3>${esc(name)}</h3><pre class="code">${esc(pretty.slice(0, 60000))}</pre>`;
  } catch (e) {
    panel.innerHTML = `<h3>${esc(name)}</h3><p>读取失败: ${esc(e.message)}</p>`;
  }
}

function showVideo(run_dir, name) {
  const panel = $("#evidence-detail");
  panel.classList.remove("hidden");
  panel.innerHTML = `<h3>${esc(name)}</h3>` +
    `<video controls style="max-width:100%;width:900px" src="/api/raw?path=${encodeURIComponent(run_dir + "/" + name)}"></video>` +
    `<p class="hint">比赛渲染相机观赛录像；机器人感知为 544×448 正常视觉管线，勿与仿真真值混淆。</p>`;
}

$("#btn-refresh-evidence").addEventListener("click", async () => {
  await api("/api/evidence/refresh", { method: "POST", body: "{}" });
  loadEvidence();
});

/* --------------------------------------------------------------- matrix */
const MATRIX_DEFS = [
  ["L0 资产身份", "源码/模型/配置/依赖哈希明确，原版与实验 profile 可区分"],
  ["L1 网络数值", "同一真实输入上 PyTorch/TorchScript/ORT/实际 C++ 推理后端输出在声明误差内"],
  ["L2 输入输出契约", "同一原始状态/历史下，生产 C++ 观测构造、历史更新、归一化、动作解码、限幅与 Python 对照"],
  ["L3 调度控制语义", "策略门控、低层周期、PD/力矩模式、限幅、串并联映射与失效处理明确并离线验证"],
  ["L4 离线目标构建", "ARM64 ELF + 配套模型/配置/动态依赖/许可证可验证"],
  ["L5 真机闭环", "需要后续单独授权与实物实验"],
];

async function loadMatrix() {
  const data = await api("/api/equivalence");
  const body = $("#matrix-table tbody");
  body.innerHTML = "";
  for (const row of data.rows) {
    const tr = el("tr");
    const evidence = el("td");
    if (row.evidence && typeof row.evidence === "object") {
      const details = el("details"); details.append(el("summary", {text:"展开本次验收证据"}),
        el("pre", {class:"code",text:JSON.stringify(row.evidence,null,2)})); evidence.append(details);
    } else evidence.textContent = row.evidence || "—";
    tr.append(el("td", {text: row.level}), el("td", {text: row.definition}),
      el("td", {}, badge(row.status)), evidence, el("td", {text: row.gap}));
    body.append(tr);
  }
}

/* ------------------------------------------------------------ env/caps */
async function loadCaps() {
  const data = await api("/api/capabilities");
  const tbody = $("#caps-table tbody");
  tbody.innerHTML = "";
  for (const c of data.capabilities) {
    const tr = el("tr");
    tr.append(el("td", { text: c.label }));
    tr.append(el("td", {}, badge(c.status)));
    let detail = c.path || "";
    if (c.probe && c.probe.ok) {
      if (c.probe.version) detail += " · " + c.probe.version;
      if (c.probe.packages) {
        detail += " · " + Object.entries(c.probe.packages).map(([k, v]) => `${k}=${v || "?"}`).join(" ");
      }
      if (c.probe.memory_used) detail += ` · 显存 ${c.probe.memory_used}/${c.probe.memory_total} · ${c.probe.utilization}`;
      if (c.probe.sha256) detail += ` · sha256=${c.probe.sha256.slice(0, 16)}… 匹配=${c.probe.identity_match}`;
      if (c.probe.probed_at) detail += ` · 探测于 ${fmtTime(c.probe.probed_at)}`;
    } else if (c.probe && c.probe.error) {
      detail += " · 探测失败: " + c.probe.error;
    }
    tr.append(el("td", { text: detail }));
    tr.append(el("td", { class: "hint", text: c.note || "" }));
    tbody.append(tr);
  }
}

$("#btn-probe").addEventListener("click", async () => {
  $("#btn-probe").disabled = true;
  try { await api("/api/capabilities/probe", { method: "POST", body: "{}" }); }
  finally { $("#btn-probe").disabled = false; loadCaps(); }
});
$("#btn-refresh-graph").addEventListener("click", loadGraph);

/* -------------------------------------------------------------- offline */
async function loadOffline() {
  const wrap = $("#offline-wrap");
  wrap.innerHTML = "";
  const panel = el("div", { class: "panel" });
  panel.innerHTML = `<h3>离线 ARM 构建与产物</h3>
    <p class="hint">构建目标为 ARM64 ELF + 配套模型/配置 + manifest + 校验工具；
    不调用部署/安装目标，不连接机器人。构建任务在「工作流」页启动（arm_build / bundle_offline）。</p>
    <div id="offline-status">加载中…</div>`;
  wrap.append(panel);
  try {
    const caps = await api("/api/capabilities");
    const arm = caps.capabilities.filter((c) => c.id.startsWith("arm."));
    const div = panel.querySelector("#offline-status");
    div.innerHTML = "";
    const ul = el("ul");
    for (const c of arm) {
      const li = el("li");
      li.append(document.createTextNode(c.label + ": " + (c.path || "-") + " "), badge(c.status));
      ul.append(li);
    }
    div.append(ul);
  } catch (e) {
    panel.querySelector("#offline-status").textContent = "加载失败: " + e.message;
  }
}

/* ---------------------------------------------------------------- boot */
(async function boot() {
  try {
    const health = await api("/api/health");
    $("#header-status").textContent = "本机回环模式 · 不连接机器人 · " + health.now;
  } catch (e) {
    $("#header-status").textContent = "API 不可用: " + e.message;
  }
  loadGraph();
  setInterval(async () => {
    const jobsTab = document.querySelector('#tabs button[data-tab="jobs"]');
    if (jobsTab.classList.contains("active")) loadJobs();
  }, 5000);
})();

function showMetrics(text, panel) {
  const rows = text.trim().split("\n").filter(Boolean).map(line => JSON.parse(line));
  panel.replaceChildren(el("h3", {text:"实际训练曲线（metrics.jsonl）"}));
  if (!rows.length) return;
  const series = ["kl_mean","lr","value_loss","policy_loss","mean_reward"].filter(key => rows.some(r => Number.isFinite(r[key])));
  if (!series.length) {
    panel.append(el("pre", {class:"code",text:JSON.stringify(rows.slice(-30),null,2)})); return;
  }
  const ns = "http://www.w3.org/2000/svg";
  for (const key of series) {
    const points = rows.filter(r => Number.isFinite(r[key]));
    const values = points.map(r => r[key]);
    const lo=Math.min(...values), hi=Math.max(...values), span=hi-lo || 1;
    panel.append(el("h4", {text:key+" · "+points.length+" 次记录 · 范围 "+lo.toPrecision(4)+" — "+hi.toPrecision(4)}));
    const svg=document.createElementNS(ns,"svg"); svg.setAttribute("viewBox","0 0 820 180"); svg.style.width="100%";
    const poly=document.createElementNS(ns,"polyline");
    poly.setAttribute("points",points.map((r,i)=>(20+i*780/Math.max(1,points.length-1))+","+(160-(r[key]-lo)/span*140)).join(" "));
    poly.setAttribute("fill","none");poly.setAttribute("stroke","#3d9df2");poly.setAttribute("stroke-width","2");
    svg.append(poly);panel.append(svg);
  }
  panel.append(el("p",{class:"hint",text:"横轴为实际记录顺序；数值来自原始日志，不代表候选策略已获比赛晋级。"}));
}

async function showEvaluation(job) {
  let wrap = document.querySelector("#eval-comparison");
  if (!wrap) { wrap=el("div",{id:"eval-comparison",class:"panel"}); $("#job-result").after(wrap); }
  wrap.replaceChildren(el("h3",{text:"行走评估分段指标"}));
  const all=(await api("/api/jobs")).jobs.filter(j=>j.type==="train_walk_eval" && j.status==="succeeded" && j.job_id!==job.job_id);
  const select=el("select",{id:"eval-baseline","aria-label":"选择基线评估任务"});
  select.append(el("option",{value:"",text:"只查看本次；可显式选择基线任务"}));
  for(const other of all) select.append(el("option",{value:other.job_id,text:other.job_id}));
  wrap.append(select);
  const body=el("div"); wrap.append(body);
  const render = (base) => {
    body.replaceChildren(el("p",{class:"hint",text:"RMSE 单位：vx/vy 为 m/s，wz 为 rad/s。仅显示有界评估差异，不自动认证或替换比赛策略。"}));
    const r=job.result;
    body.append(el("p",{text:"急停收敛 "+r.settle_per_env.n_settled+"/"+r.settle_per_env.n_total+
      "；最大测得超调 "+r.max_joint_overshoot_rad+" rad；力矩饱和占比 "+r.torque_saturation_ratio}));
    const table=el("table");const head=el("tr");
    for(const name of ["命令段","当前 vx / vy / wz",...(base?["基线 vx / vy / wz","当前/基线"]:[])]) head.append(el("th",{text:name}));
    table.append(head);
    const fmt = a => a.map(v=>Number.isFinite(v)?v.toFixed(4):"无数据").join(" / ");
    for(const [name,segment] of Object.entries(r.segments)) {
      const a=segment.tracking_rmse_settled_vx_vy_wz; const tr=el("tr");tr.append(el("td",{text:name}),el("td",{text:fmt(a)}));
      if(base) {
        const b=base.segments[name].tracking_rmse_settled_vx_vy_wz;
        tr.append(el("td",{text:fmt(b)}),el("td",{text:fmt(a.map((v,i)=>b[i]>1e-8?v/b[i]:null))}));
      }
      table.append(tr);
    }
    body.append(table);
  };
  render(null);
  select.addEventListener("change",async()=>{
    if(!select.value) return render(null);
    const baseline=(await api("/api/jobs/"+select.value)).result;
    for(const key of ["source_sha256","seed","num_envs","seg_steps","schedule","evaluator_sha256","zero_command_mode"]) {
      if(JSON.stringify(job.result[key])!==JSON.stringify(baseline[key])) {
        body.replaceChildren(el("p",{text:"比较条件不一致："+key+"，拒绝直接计算比值。"}));return;
      }
    }
    render(baseline);
  });
}
