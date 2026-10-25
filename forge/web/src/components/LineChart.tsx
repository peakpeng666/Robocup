import { useMemo, useState } from "react";

export interface Series {
  name: string;
  color: string;
  points: [number, number][];
}

const W = 560;
const H = 200;
const PAD = { l: 48, r: 12, t: 12, b: 26 };

function ticks(min: number, max: number, count = 4) {
  if (!isFinite(min) || !isFinite(max)) return [];
  if (min === max) return [min];
  const step = (max - min) / count;
  return Array.from({ length: count + 1 }, (_, i) => min + i * step);
}

function fmt(v: number) {
  const a = Math.abs(v);
  if (a !== 0 && (a < 1e-3 || a >= 1e5)) return v.toExponential(1);
  return Number(v.toPrecision(3)).toString();
}

export function LineChart({ series, title, yLabel, height = H }: { series: Series[]; title?: string; yLabel?: string; height?: number }) {
  const [hover, setHover] = useState<number | null>(null);
  const all = series.flatMap((s) => s.points);
  const { x0, x1, y0, y1 } = useMemo(() => {
    const xs = all.map((p) => p[0]);
    const ys = all.map((p) => p[1]).filter((v) => isFinite(v));
    let lo = Math.min(...ys);
    let hi = Math.max(...ys);
    if (lo === hi) {
      lo -= 1;
      hi += 1;
    }
    const margin = (hi - lo) * 0.06;
    return { x0: Math.min(...xs), x1: Math.max(...xs), y0: lo - margin, y1: hi + margin };
  }, [all]);
  if (!all.length) return <div className="empty">{title}：暂无数据</div>;
  const sx = (x: number) => PAD.l + ((x - x0) / Math.max(1e-9, x1 - x0)) * (W - PAD.l - PAD.r);
  const sy = (y: number) => PAD.t + (1 - (y - y0) / Math.max(1e-9, y1 - y0)) * (height - PAD.t - PAD.b);
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const x = ((e.clientX - box.left) / box.width) * W;
    const value = x0 + ((x - PAD.l) / (W - PAD.l - PAD.r)) * (x1 - x0);
    setHover(value);
  };
  const nearest = (s: Series) => {
    if (hover === null || !s.points.length) return null;
    let best = s.points[0];
    for (const p of s.points) if (Math.abs(p[0] - hover) < Math.abs(best[0] - hover)) best = p;
    return best;
  };
  return (
    <div>
      {title && (
        <div className="row between" style={{ marginBottom: 4 }}>
          <b style={{ fontSize: 13 }}>{title}</b>
          <div className="legend">
            {series.map((s) => {
              const n = nearest(s);
              return (
                <span key={s.name}>
                  <i style={{ background: s.color }} />
                  {s.name}
                  {n ? `：${fmt(n[1])}` : ""}
                </span>
              );
            })}
          </div>
        </div>
      )}
      <svg viewBox={`0 0 ${W} ${height}`} width="100%" onMouseMove={onMove} onMouseLeave={() => setHover(null)} role="img" aria-label={title}>
        {ticks(y0, y1).map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={sy(t)} y2={sy(t)} stroke="#263349" strokeDasharray="3 4" />
            <text x={PAD.l - 6} y={sy(t) + 4} fill="#7488a1" fontSize="10" textAnchor="end">
              {fmt(t)}
            </text>
          </g>
        ))}
        {ticks(x0, x1, 5).map((t) => (
          <text key={t} x={sx(t)} y={height - 8} fill="#7488a1" fontSize="10" textAnchor="middle">
            {Math.round(t)}
          </text>
        ))}
        {yLabel && (
          <text x={10} y={PAD.t + 4} fill="#7488a1" fontSize="10">
            {yLabel}
          </text>
        )}
        {series.map((s) => (
          <polyline
            key={s.name}
            fill="none"
            stroke={s.color}
            strokeWidth={1.6}
            points={s.points.filter((p) => isFinite(p[1])).map((p) => `${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join(" ")}
          />
        ))}
        {hover !== null && hover >= x0 && hover <= x1 && <line x1={sx(hover)} x2={sx(hover)} y1={PAD.t} y2={height - PAD.b} stroke="#4ea1ff" strokeOpacity={0.5} />}
      </svg>
    </div>
  );
}
