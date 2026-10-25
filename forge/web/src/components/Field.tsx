import { useEffect, useMemo, useState } from "react";

// HSL 2026 "M" field (Config/Locations/MField/fieldDimensions.cfg), millimetres.
const F = {
  border: { x: 8000, y: 5500 },
  goalLine: 6975,
  touch: 4475,
  penaltyArea: { x: 4025, y: 2975 },
  goalArea: { x: 6025, y: 1975 },
  goal: { y: 1250, depth: 675 },
  centerRadius: 1500,
  penaltyMark: 5000,
};

export interface RobotTrack {
  name: string;
  team: number;
  player: number;
  trajectory: [number, number, number, number][]; // tick, x_mm, y_mm, yaw
}

const TEAM_COLORS: Record<number, [string, string]> = { 5: ["#e5484d", "#ff9a9d"], 70: ["#f2f2f2", "#a96cff"] };

export function Field({ robots, ball, tick, setTick }: { robots: RobotTrack[]; ball: [number, number, number][]; tick?: number; setTick?: (t: number) => void }) {
  const maxTick = useMemo(() => Math.max(1, ...robots.flatMap((r) => r.trajectory.map((p) => p[0])), ...ball.map((b) => b[0] * 1)), [robots, ball]);
  const [local, setLocal] = useState(maxTick);
  const [playing, setPlaying] = useState(false);
  const current = tick ?? local;
  const update = setTick ?? setLocal;
  useEffect(() => {
    if (!playing) return;
    const handle = window.setInterval(() => update(current >= maxTick ? 0 : Math.min(maxTick, current + 250)), 120);
    return () => window.clearInterval(handle);
  }, [playing, current, maxTick, update]);

  const W = 2 * F.border.x;
  const H = 2 * F.border.y;
  const X = (x: number) => x + F.border.x;
  const Y = (y: number) => F.border.y - y;
  const at = (track: [number, number, number, number][]) => {
    let best = track[0];
    for (const p of track) if (p[0] <= current) best = p;
    return best;
  };
  const ballAt = () => {
    // game ticks are simulation steps (every 250); physics ticks are per-robot motion updates.
    let best = ball[0];
    for (const b of ball) if (b[0] <= current) best = b;
    return best;
  };
  const b = ball.length ? ballAt() : null;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ background: "var(--field)", borderRadius: 10 }}>
        <g stroke="var(--field-line)" strokeWidth={50} fill="none">
          <rect x={X(-F.goalLine)} y={Y(F.touch)} width={2 * F.goalLine} height={2 * F.touch} />
          <line x1={X(0)} y1={Y(F.touch)} x2={X(0)} y2={Y(-F.touch)} />
          <circle cx={X(0)} cy={Y(0)} r={F.centerRadius} />
          {[1, -1].map((s) => (
            <g key={s}>
              <rect x={s > 0 ? X(F.penaltyArea.x) : X(-F.goalLine)} y={Y(F.penaltyArea.y)} width={F.goalLine - F.penaltyArea.x} height={2 * F.penaltyArea.y} />
              <rect x={s > 0 ? X(F.goalArea.x) : X(-F.goalLine)} y={Y(F.goalArea.y)} width={F.goalLine - F.goalArea.x} height={2 * F.goalArea.y} />
              <rect x={s > 0 ? X(F.goalLine) : X(-F.goalLine - F.goal.depth)} y={Y(F.goal.y)} width={F.goal.depth} height={2 * F.goal.y} stroke="#ffe08a" />
              <circle cx={X(s * F.penaltyMark)} cy={Y(0)} r={60} fill="var(--field-line)" />
            </g>
          ))}
        </g>
        {robots.map((r) => {
          const [c1] = TEAM_COLORS[r.team] || ["#4ea1ff", "#4ea1ff"];
          const pts = r.trajectory.filter((p) => p[0] <= current);
          return <polyline key={r.name + "t"} fill="none" stroke={c1} strokeOpacity={0.45} strokeWidth={45} points={pts.map((p) => `${X(p[1])},${Y(p[2])}`).join(" ")} />;
        })}
        {ball.length > 1 && (
          <polyline fill="none" stroke="#ffd166" strokeOpacity={0.55} strokeWidth={35} strokeDasharray="120 90" points={ball.filter((p) => p[0] <= current).map((p) => `${X(p[1])},${Y(p[2])}`).join(" ")} />
        )}
        {robots.map((r) => {
          if (!r.trajectory.length) return null;
          const [c1, c2] = TEAM_COLORS[r.team] || ["#4ea1ff", "#4ea1ff"];
          const p = at(r.trajectory);
          const dx = Math.cos(p[3]) * 420;
          const dy = Math.sin(p[3]) * 420;
          return (
            <g key={r.name}>
              <circle cx={X(p[1])} cy={Y(p[2])} r={230} fill={c1} stroke={c2} strokeWidth={60} />
              <line x1={X(p[1])} y1={Y(p[2])} x2={X(p[1] + dx)} y2={Y(p[2] + dy)} stroke="#0b0f15" strokeWidth={70} />
              <text x={X(p[1])} y={Y(p[2]) + 95} fontSize={260} textAnchor="middle" fill="#0b0f15" fontWeight={800}>
                {r.player}
              </text>
            </g>
          );
        })}
        {b && <circle cx={X(b[1])} cy={Y(b[2])} r={110} fill="#ffd166" stroke="#7a5b00" strokeWidth={25} />}
      </svg>
      <div className="row" style={{ marginTop: 8 }}>
        <button className="btn small" onClick={() => setPlaying((p) => !p)}>
          {playing ? "暂停" : "回放"}
        </button>
        <input type="range" min={0} max={maxTick} step={250} value={current} onChange={(e) => update(Number(e.target.value))} style={{ flex: 1 }} />
        <span className="mono hint">{(current * 0.002).toFixed(1)} s</span>
      </div>
    </div>
  );
}
