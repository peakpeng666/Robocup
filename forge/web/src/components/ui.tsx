import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api } from "../api";

const STATUS_CLASS: Record<string, string> = {
  PASS: "ok", succeeded: "ok", VERIFIED: "ok", FRESH: "ok", baseline: "info", running: "info", queued: "muted",
  FAIL: "bad", failed: "bad", STALE: "warn", INCOMPLETE: "warn", cancelled: "warn", interrupted: "warn",
  experimental: "violet", candidate: "violet", NOT_MATERIALIZED: "muted",
  COMPLETED: "ok", RUNNING: "info", FAILED: "bad", INTERRUPTED: "warn",
  NO_REGRESSION_OBSERVED: "ok", REGRESSION_OBSERVED: "bad", READY_FOR_REVIEW: "info", INSUFFICIENT_EVIDENCE: "warn",
};

const STATUS_TEXT: Record<string, string> = {
  PASS: "通过", FAIL: "未通过", succeeded: "完成", failed: "失败", running: "运行中", queued: "排队", cancelled: "已取消",
  interrupted: "已中断", FRESH: "最新", STALE: "已过期", experimental: "实验候选", baseline: "官方基线", INCOMPLETE: "不完整",
  NOT_MATERIALIZED: "未建立",
  COMPLETED: "运行完成", RUNNING: "运行中", FAILED: "执行失败", INTERRUPTED: "已中断",
  NO_REGRESSION_OBSERVED: "未观察到退化", REGRESSION_OBSERVED: "观察到退化", READY_FOR_REVIEW: "待审阅", INSUFFICIENT_EVIDENCE: "证据不足",
};

export function Badge({ value, text }: { value?: string | boolean | null; text?: string }) {
  const key = value === true ? "PASS" : value === false ? "FAIL" : value ?? "";
  const cls = STATUS_CLASS[key] || "muted";
  return <span className={`badge ${cls}`}>{text ?? STATUS_TEXT[key] ?? (key || "—")}</span>;
}

export function Card({ title, sub, right, children, className }: { title?: ReactNode; sub?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className || ""}`}>
      {title && (
        <div className="row between" style={{ marginBottom: 10 }}>
          <h3 style={{ margin: 0 }}>
            {title} {sub && <span className="sub">{sub}</span>}
          </h3>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Checks({ checks }: { checks?: Record<string, boolean> | null }) {
  if (!checks) return null;
  return (
    <div className="checks">
      {Object.entries(checks).map(([key, value]) => (
        <div key={key}>
          <span style={{ color: value ? "var(--ok)" : "var(--bad)" }}>{value ? "✔" : "✘"}</span>
          <span className="k mono">{key}</span>
        </div>
      ))}
    </div>
  );
}

export function Json({ value }: { value: unknown }) {
  return <pre className="json mono">{JSON.stringify(value, null, 2)}</pre>;
}

export function usePoll<T>(path: string | null, intervalMs = 4000): { data: T | null; error: string | null; reload: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);
  const load = useCallback(() => {
    if (!path) return;
    api
      .get<T>(path)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(String(e.message || e)));
  }, [path]);
  useEffect(() => {
    load();
    if (intervalMs > 0) {
      timer.current = window.setInterval(load, intervalMs);
      return () => {
        if (timer.current) window.clearInterval(timer.current);
      };
    }
  }, [load, intervalMs]);
  return { data, error, reload: load };
}

type ToastState = { text: string; bad?: boolean } | null;
const ToastContext = createContext<(text: string, bad?: boolean) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastState>(null);
  const show = useCallback((text: string, bad?: boolean) => {
    setToast({ text, bad });
    window.setTimeout(() => setToast(null), bad ? 9000 : 4500);
  }, []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      {toast && <div className={`toast ${toast.bad ? "bad" : ""}`}>{toast.text}</div>}
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);

export function Stat({ label, value, unit, tone }: { label: string; value: ReactNode; unit?: string; tone?: string }) {
  return (
    <div>
      <div className="hint">{label}</div>
      <div className="kpi" style={tone ? { color: tone } : undefined}>
        {value}
        {unit && <small>{unit}</small>}
      </div>
    </div>
  );
}
