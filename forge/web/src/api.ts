// Same-origin API client. The session cookie is set by the server from the ?token= URL.

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    credentials: "same-origin",
  });
  const text = await response.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text };
  }
  if (!response.ok) {
    const body = data as { detail?: string; error?: string } | null;
    throw new ApiError(response.status, body?.detail || body?.error || response.statusText);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) }),
};

// ------------------------------------------------------------------ types
export type Dict<T = unknown> = Record<string, T>;

export interface PackComponent {
  file: string | null;
  official_file?: string;
  sha256: string;
  contract: string;
  source_path?: string;
  onnx?: { opset: number; parameters: number; nodes: number; ops: string[]; inputs: Dict[]; outputs: Dict[]; ort_smoke?: Dict };
}

export interface Pack {
  id: string;
  kind: "baseline" | "candidate";
  name: string;
  description: string;
  status: string;
  created_at?: string;
  components: Dict<PackComponent>;
  cfg_patches: Dict<Dict<string>>;
  provenance: Dict<any>;
}

export interface FlashReceipt {
  team: number;
  scenario: string;
  pack_id: string;
  pack_kind: string;
  pack_name: string;
  written: Dict<string>;
  networks: Dict<{ path: string; sha256: string }>;
  patches: Dict<Dict<string>>;
  at: string;
}

export interface TeamStats {
  pack_id: string | null;
  goals: number;
  goals_against: number;
  ball_contacts: number;
  fall_episodes_sampled: number;
  fall_frames: number;
  getup_frames: number;
  walk_frames: number;
  path_m: number;
  ball_seen_samples: number;
  mean_perception_hz: number;
}

export interface MatchSummary {
  id: string;
  status: string;
  score: Dict<number> | null;
  teams: Dict<TeamStats> | null;
  tag: string;
  video: boolean;
  seconds: number;
  vision: string;
  performance?: { wall_s: number; real_time_factor: number };
  failed_checks: string[];
  assignment: Dict<{ pack_id: string; pack_kind: string; scenario: string }>;
  readback_ok: boolean;
}

export interface Job {
  id: string;
  type: string;
  params: Dict;
  argv: string[];
  resources: string[];
  status: string;
  created_at: string;
  started_at?: string;
  ended_at?: string;
  exit_code?: number;
  pid?: number;
  log_path: string;
  error?: string;
}

export interface TrainRun {
  id: string;
  origin: "forge" | "mainline";
  path: string;
  preset?: string;
  label?: string;
  status: string;
  wall_s?: number;
  iterations: number;
  checkpoints: string[];
  envs?: number;
  seed?: number;
}

export function short(hash?: string | null, n = 10) {
  return hash ? hash.slice(0, n) : "—";
}

export function fmtTime(iso?: string | null) {
  return iso ? iso.replace("T", " ").slice(0, 19) : "—";
}

export function packLabel(packs: Pack[], id?: string | null) {
  if (!id) return "未刷写";
  const pack = packs.find((p) => p.id === id);
  return pack ? pack.name : id;
}
