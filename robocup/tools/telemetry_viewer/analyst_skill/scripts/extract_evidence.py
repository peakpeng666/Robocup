#!/usr/bin/env python3
"""Deterministic evidence extraction for LLM-written match reports."""

from __future__ import annotations

from collections import Counter
from html import escape
from pathlib import Path
from typing import Any

from telemetry_core import (
    Row,
    angular_speed,
    dist2d,
    fmt_s,
    is_moving,
    linear_speed,
    load_jsonl,
    organise,
    pct,
    replay_link,
    robot_xy,
    t_ms,
    t_s,
)


def _round(value: float, digits: int = 3) -> float:
    return round(float(value), digits)


def _role(rrows: list[Row]) -> str:
    if not rrows:
        return "unknown"
    return str(rrows[0].get("packet", {}).get("role", "unknown") or "unknown")


def _event(
    *,
    event_type: str,
    severity: str,
    title: str,
    recording_name: str,
    viewer_url: str,
    at_ms: float,
    robot_id: int | None = None,
    end_ms: float | None = None,
    evidence: str = "",
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "type": event_type,
        "severity": severity,
        "title_zh": title,
        "time_s": _round(at_ms / 1000.0, 2),
        "link": replay_link(viewer_url, recording_name, at_ms),
        "evidence_zh": evidence,
        "metrics": metrics or {},
    }
    if robot_id is not None:
        item["robot_id"] = robot_id
    if end_ms is not None:
        item["end_s"] = _round(end_ms / 1000.0, 2)
        item["duration_s"] = _round((end_ms - at_ms) / 1000.0, 2)
    return item


def fall_segments(rrows: list[Row]) -> list[tuple[float, float]]:
    segments: list[tuple[float, float]] = []
    in_fall = False
    start_ms = 0.0
    for row in rrows:
        recovery = row.get("packet", {}).get("recovery", "IS_READY")
        if recovery != "IS_READY" and not in_fall:
            in_fall = True
            start_ms = t_ms(row)
        elif recovery == "IS_READY" and in_fall:
            in_fall = False
            segments.append((start_ms, t_ms(row)))
    if in_fall and rrows:
        segments.append((start_ms, t_ms(rrows[-1])))
    return segments


def game_state_segments(rows: list[Row]) -> list[dict[str, Any]]:
    if not rows:
        return []
    segments: list[dict[str, Any]] = []
    prev_state: str | None = None
    start_ms = t_ms(rows[0])
    for row in rows:
        state = str(row.get("packet", {}).get("game", {}).get("state", "") or "(空)")
        if prev_state is None:
            prev_state = state
            start_ms = t_ms(row)
        elif state != prev_state:
            end_ms = t_ms(row)
            segments.append(
                {
                    "state": prev_state,
                    "start_s": _round(start_ms / 1000.0, 2),
                    "end_s": _round(end_ms / 1000.0, 2),
                    "duration_s": _round((end_ms - start_ms) / 1000.0, 2),
                }
            )
            prev_state = state
            start_ms = t_ms(row)
    end_ms = t_ms(rows[-1])
    segments.append(
        {
            "state": prev_state or "(空)",
            "start_s": _round(start_ms / 1000.0, 2),
            "end_s": _round(end_ms / 1000.0, 2),
            "duration_s": _round((end_ms - start_ms) / 1000.0, 2),
        }
    )
    return segments


def robot_summary(pid: int, rrows: list[Row]) -> dict[str, Any]:
    decisions = [str(row.get("packet", {}).get("decision", "") or "(空)") for row in rrows]
    packets = [row.get("packet", {}) for row in rrows]
    fall_count = len(fall_segments(rrows))
    moving_count = sum(1 for pkt in packets if is_moving(pkt))
    detected_count = sum(1 for pkt in packets if (pkt.get("ball") or {}).get("detected"))
    team_ball_count = sum(1 for pkt in packets if (pkt.get("team_ball") or {}).get("valid"))
    speeds = [linear_speed(pkt) for pkt in packets]
    angular = [angular_speed(pkt) for pkt in packets]
    switches = sum(1 for i in range(1, len(decisions)) if decisions[i] != decisions[i - 1])
    lead_count = sum(1 for pkt in packets if pkt.get("is_lead"))
    return {
        "robot_id": pid,
        "role": _role(rrows),
        "packets": len(rrows),
        "decision_counts": dict(Counter(decisions).most_common()),
        "decision_switches": switches,
        "lead_rate_pct": _round(pct(lead_count, len(rrows)), 1),
        "fall_count": fall_count,
        "moving_rate_pct": _round(pct(moving_count, len(rrows)), 1),
        "local_ball_rate_pct": _round(pct(detected_count, len(rrows)), 1),
        "team_ball_rate_pct": _round(pct(team_ball_count, len(rrows)), 1),
        "max_linear_speed": _round(max(speeds), 3) if speeds else 0.0,
        "max_angular_speed": _round(max(angular), 3) if angular else 0.0,
    }


def extract_events(
    recording_name: str,
    by_robot: dict[int, list[Row]],
    viewer_url: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    highlights: list[dict[str, Any]] = []

    for pid, rrows in sorted(by_robot.items()):
        role = _role(rrows)
        for start_ms, end_ms in fall_segments(rrows):
            duration_s = (end_ms - start_ms) / 1000.0
            pre_rows = [row for row in rrows if start_ms - 15000.0 <= t_ms(row) < start_ms]
            max_lin = max((linear_speed(row["packet"]) for row in pre_rows), default=0.0)
            max_ang = max((angular_speed(row["packet"]) for row in pre_rows), default=0.0)
            evidence = (
                f"{role} P{pid} 在 {fmt_s(start_ms / 1000.0)} 进入非 IS_READY，"
                f"持续 {duration_s:.1f}s；跌倒前 15s 最大线速度 {max_lin:.2f}m/s，"
                f"最大角速度 {max_ang:.2f}rad/s。"
            )
            severity = "high" if duration_s >= 10.0 else "medium"
            events.append(
                _event(
                    event_type="fall_segment",
                    severity=severity,
                    title=f"P{pid} 跌倒/恢复片段",
                    recording_name=recording_name,
                    viewer_url=viewer_url,
                    at_ms=start_ms,
                    end_ms=end_ms,
                    robot_id=pid,
                    evidence=evidence,
                    metrics={"duration_s": _round(duration_s, 2), "pre_max_linear": _round(max_lin), "pre_max_angular": _round(max_ang)},
                )
            )
            if duration_s <= 8.0:
                highlights.append(
                    _event(
                        event_type="fast_recovery",
                        severity="positive",
                        title=f"P{pid} 快速起身",
                        recording_name=recording_name,
                        viewer_url=viewer_url,
                        at_ms=start_ms,
                        end_ms=end_ms,
                        robot_id=pid,
                        evidence=f"P{pid} 从跌倒到 IS_READY 用时 {duration_s:.1f}s，属于较快恢复。",
                        metrics={"duration_s": _round(duration_s, 2)},
                    )
                )

        last_close: dict[tuple[int, int], float] = {}
        last_near_obstacle_ms = -999999.0
        for row in rrows:
            pkt = row.get("packet", {})
            own_xy = robot_xy(pkt)
            if own_xy is None:
                continue
            rx, ry = own_xy
            for teammate in pkt.get("teammates") or []:
                try:
                    teammate_id = int(teammate.get("player_id", 0) or 0)
                    tx = float(teammate["x"])
                    ty = float(teammate["y"])
                except (KeyError, TypeError, ValueError):
                    continue
                distance = dist2d(rx, ry, tx, ty)
                key = (pid, teammate_id)
                if distance < 0.5 and t_ms(row) - last_close.get(key, -999999.0) >= 5000.0:
                    last_close[key] = t_ms(row)
                    events.append(
                        _event(
                            event_type="close_teammate",
                            severity="medium",
                            title=f"P{pid} 与 P{teammate_id} 距离过近",
                            recording_name=recording_name,
                            viewer_url=viewer_url,
                            at_ms=t_ms(row),
                            robot_id=pid,
                            evidence=f"P{pid} 与队友 P{teammate_id} 的估计距离为 {distance:.2f}m，低于 0.50m 阈值。",
                            metrics={"teammate_id": teammate_id, "distance_m": _round(distance)},
                        )
                    )

            for obs in pkt.get("obstacles") or []:
                try:
                    distance = dist2d(rx, ry, float(obs["x"]), float(obs["y"]))
                except (KeyError, TypeError, ValueError):
                    continue
                if distance < 0.8 and t_ms(row) - last_near_obstacle_ms >= 10000.0:
                    last_near_obstacle_ms = t_ms(row)
                    events.append(
                        _event(
                            event_type="near_obstacle",
                            severity="medium",
                            title=f"P{pid} 近距离障碍物",
                            recording_name=recording_name,
                            viewer_url=viewer_url,
                            at_ms=t_ms(row),
                            robot_id=pid,
                            evidence=f"P{pid} 附近 {distance:.2f}m 有障碍物，可能影响局部避障或跌倒风险判断。",
                            metrics={"distance_m": _round(distance)},
                        )
                    )
                    break

        lost_start: float | None = None
        for row in rrows:
            detected = bool((row.get("packet", {}).get("ball") or {}).get("detected"))
            if not detected and lost_start is None:
                lost_start = t_ms(row)
            elif detected and lost_start is not None:
                lost_duration = t_ms(row) - lost_start
                if lost_duration >= 30000.0:
                    events.append(
                        _event(
                            event_type="long_ball_lost",
                            severity="medium",
                            title=f"P{pid} 长时间未看到球",
                            recording_name=recording_name,
                            viewer_url=viewer_url,
                            at_ms=lost_start,
                            end_ms=t_ms(row),
                            robot_id=pid,
                            evidence=f"P{pid} 连续 {lost_duration / 1000.0:.1f}s 本机未检测到球。",
                            metrics={"duration_s": _round(lost_duration / 1000.0, 2)},
                        )
                    )
                lost_start = None
        if lost_start is not None and rrows:
            lost_duration = t_ms(rrows[-1]) - lost_start
            if lost_duration >= 30000.0:
                events.append(
                    _event(
                        event_type="long_ball_lost",
                        severity="medium",
                        title=f"P{pid} 长时间未看到球",
                        recording_name=recording_name,
                        viewer_url=viewer_url,
                        at_ms=lost_start,
                        end_ms=t_ms(rrows[-1]),
                        robot_id=pid,
                        evidence=f"P{pid} 连续 {lost_duration / 1000.0:.1f}s 本机未检测到球，直到录像末尾仍未恢复。",
                        metrics={"duration_s": _round(lost_duration / 1000.0, 2)},
                    )
                )

        for i in range(1, len(rrows)):
            prev = rrows[i - 1].get("packet", {})
            curr = rrows[i].get("packet", {})
            prev_xy = robot_xy(prev)
            curr_xy = robot_xy(curr)
            if prev_xy is None or curr_xy is None:
                continue
            jump = dist2d(prev_xy[0], prev_xy[1], curr_xy[0], curr_xy[1])
            if jump > 3.0:
                events.append(
                    _event(
                        event_type="localization_jump",
                        severity="high",
                        title=f"P{pid} 定位跳变",
                        recording_name=recording_name,
                        viewer_url=viewer_url,
                        at_ms=t_ms(rrows[i]),
                        robot_id=pid,
                        evidence=f"P{pid} 相邻 1Hz 采样之间位姿跳变 {jump:.2f}m。",
                        metrics={"jump_m": _round(jump)},
                    )
                )

        attack_decisions = {"chase", "dribble", "shoot", "pass"}
        seg_start: float | None = None
        seg_decisions: list[str] = []
        for row in rrows:
            pkt = row.get("packet", {})
            decision = str(pkt.get("decision", "") or "")
            if pkt.get("is_lead") and decision in attack_decisions and pkt.get("recovery", "IS_READY") == "IS_READY":
                if seg_start is None:
                    seg_start = t_ms(row)
                    seg_decisions = [decision]
                else:
                    seg_decisions.append(decision)
            elif seg_start is not None:
                duration = t_ms(row) - seg_start
                if duration >= 5000.0:
                    unique = list(dict.fromkeys(seg_decisions))
                    highlights.append(
                        _event(
                            event_type="sustained_attack",
                            severity="positive",
                            title=f"P{pid} 连续主攻片段",
                            recording_name=recording_name,
                            viewer_url=viewer_url,
                            at_ms=seg_start,
                            end_ms=t_ms(row),
                            robot_id=pid,
                            evidence=f"P{pid} 连续 {duration / 1000.0:.1f}s 处于 lead 攻击决策：{' -> '.join(unique)}。",
                            metrics={"duration_s": _round(duration / 1000.0, 2), "decisions": unique},
                        )
                    )
                seg_start = None
                seg_decisions = []

    severity_rank = {"high": 0, "medium": 1, "low": 2, "positive": 3}
    events.sort(key=lambda event: (severity_rank.get(event["severity"], 9), event.get("time_s", 0.0)))
    highlights.sort(key=lambda event: (event.get("time_s", 0.0), event.get("robot_id", 0)))
    return events[:200], highlights[:80]


def build_evidence(recording_path: Path, viewer_url: str = "http://127.0.0.1:8090") -> dict[str, Any]:
    header, rows = load_jsonl(recording_path)
    by_robot = organise(rows)
    duration_s = (t_ms(rows[-1]) - t_ms(rows[0])) / 1000.0 if len(rows) >= 2 else 0.0
    events, highlights = extract_events(recording_path.name, by_robot, viewer_url)
    robot_summaries = [robot_summary(pid, rrows) for pid, rrows in sorted(by_robot.items())]
    fall_total = sum(summary["fall_count"] for summary in robot_summaries)
    top_events = [event for event in events if event["severity"] in ("high", "medium")][:8]
    return {
        "schema_version": 1,
        "language": "zh-CN",
        "recording": {
            "file": recording_path.name,
            "path": str(recording_path),
            "started_at_iso": header.get("started_at_iso", "unknown"),
            "duration_s": _round(duration_s, 2),
            "packet_count": len(rows),
            "robot_count": len(by_robot),
            "viewer_url": viewer_url.rstrip("/"),
        },
        "summary": {
            "robots": [summary["robot_id"] for summary in robot_summaries],
            "fall_total": fall_total,
            "issue_event_count": len(events),
            "highlight_count": len(highlights),
            "top_issue_titles": [event["title_zh"] for event in top_events],
        },
        "timeline": {"game_states": game_state_segments(rows)},
        "robots": robot_summaries,
        "events": events,
        "highlights": highlights,
        "standing_notes": [
            {
                "title_zh": "采样率限制",
                "body_zh": "当前调试 UDP 通常为 1Hz，报告不要声称亚秒级因果，只能把高速动作/跌倒前状态作为低频证据。",
                "source_hint": "src/brain/src/telemetry_sender.cpp",
            },
            {
                "title_zh": "空 decision 语义",
                "body_zh": "decision 为空通常表示 STOP/PAUSE/SET 等 clear_decision 分支，不能直接解释为字段丢失。",
                "source_hint": "src/brain/behavior_trees/game.xml",
            },
            {
                "title_zh": "team_ball.age_ms 需谨慎",
                "body_zh": "历史报告发现 team_ball.age_ms 存在时钟域问题；如本字段异常大，报告应把它列为遥测质量问题。",
                "source_hint": "src/brain/src/telemetry_sender.cpp",
            },
        ],
        "report_guidance": {
            "audience": "RoboCup 工程队赛后复盘",
            "write_final_report_with_llm": True,
            "required_language": "中文",
            "required_sections": [
                "一句话结论",
                "比赛概况",
                "关键问题与证据",
                "做得好的片段",
                "可能的代码根因",
                "下一步改进建议",
            ],
            "claim_policy": "每个行为判断都要引用事件时间/回放链接；源码根因要标明文件或说清只是猜测。",
        },
    }


def render_llm_brief(evidence: dict[str, Any]) -> str:
    rec = evidence["recording"]
    lines = [
        f"# 赛后证据简报：{rec['file']}",
        "",
        "_这不是最终报告；这是脚本提取的证据包摘要，供 LLM/Codex 写中文赛后分析使用。_",
        "",
        "## 写作任务",
        "",
        "请用中文撰写最终赛后分析报告。报告应基于本 brief 和同名 `_evidence.json`，不要直接臆测原始 JSONL 中没有的亚秒级细节。",
        "每个关键行为判断至少引用一个回放时间链接；代码原因只能在查阅源码后写成确认结论，否则写为假设。",
        "",
        "## 录像概况",
        "",
        f"- 录像文件：`{rec['file']}`",
        f"- 开始时间：{rec['started_at_iso']}",
        f"- 时长：{rec['duration_s']:.1f}s",
        f"- 包数量：{rec['packet_count']}",
        f"- 机器人数量：{rec['robot_count']}",
        "",
        "## 机器人摘要",
        "",
        "| 机器人 | 角色 | 包数 | 跌倒 | 控球率 | 本机看球 | 团队球有效 | 最大线速度 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for robot in evidence["robots"]:
        lines.append(
            f"| P{robot['robot_id']} | {robot['role']} | {robot['packets']} | {robot['fall_count']} | "
            f"{robot['lead_rate_pct']:.1f}% | {robot['local_ball_rate_pct']:.1f}% | "
            f"{robot['team_ball_rate_pct']:.1f}% | {robot['max_linear_speed']:.2f}m/s |"
        )

    lines.extend(["", "## 关键问题候选", ""])
    issue_events = [event for event in evidence["events"] if event["severity"] in ("high", "medium")]
    if not issue_events:
        lines.append("- 暂未检测到高/中优先级问题事件。")
    for event in issue_events[:20]:
        robot = f"P{event['robot_id']} " if "robot_id" in event else ""
        duration = f"，持续 {event['duration_s']:.1f}s" if "duration_s" in event else ""
        lines.append(
            f"- **{event['title_zh']}**（{robot}{event['time_s']:.1f}s{duration}）："
            f"{event['evidence_zh']} [打开回放]({event['link']})"
        )

    lines.extend(["", "## 正向片段候选", ""])
    if not evidence["highlights"]:
        lines.append("- 暂未检测到明显正向片段。")
    for event in evidence["highlights"][:12]:
        duration = f"，持续 {event['duration_s']:.1f}s" if "duration_s" in event else ""
        lines.append(
            f"- **{event['title_zh']}**（{event['time_s']:.1f}s{duration}）："
            f"{event['evidence_zh']} [打开回放]({event['link']})"
        )

    lines.extend(["", "## 低频遥测限制", ""])
    for note in evidence["standing_notes"]:
        lines.append(f"- **{note['title_zh']}**：{note['body_zh']}（线索：`{note['source_hint']}`）")

    lines.extend(
        [
            "",
            "## 建议的最终报告结构",
            "",
            "1. 一句话结论：先说这场最影响表现的 1-2 个现象。",
            "2. 比赛概况：用上面的机器人摘要和 game-state timeline，不要堆满所有数字。",
            "3. 关键问题：每条包含现象、证据时间、影响、可能根因、需要补充验证的数据。",
            "4. 正向片段：指出哪些配合/恢复/进攻片段值得保留。",
            "5. 代码改进建议：只写能落到文件、节点、参数或遥测字段的动作。",
        ]
    )
    return "\n".join(lines) + "\n"


def render_evidence_html(evidence: dict[str, Any]) -> str:
    rec = evidence["recording"]

    def esc(value: Any) -> str:
        return escape(str(value), quote=True)

    robot_rows = []
    for robot in evidence["robots"]:
        robot_rows.append(
            "<tr>"
            f"<td>P{robot['robot_id']}</td>"
            f"<td>{esc(robot['role'])}</td>"
            f"<td>{robot['packets']}</td>"
            f"<td>{robot['fall_count']}</td>"
            f"<td>{robot['lead_rate_pct']:.1f}%</td>"
            f"<td>{robot['local_ball_rate_pct']:.1f}%</td>"
            f"<td>{robot['team_ball_rate_pct']:.1f}%</td>"
            f"<td>{robot['max_linear_speed']:.2f}m/s</td>"
            "</tr>"
        )

    def card(event: dict[str, Any]) -> str:
        severity = event.get("severity", "medium")
        robot = f"P{event['robot_id']} · " if "robot_id" in event else ""
        duration = f" · 持续 {event['duration_s']:.1f}s" if "duration_s" in event else ""
        return (
            f'<article class="event {esc(severity)}">'
            f"<h3>{esc(event['title_zh'])}</h3>"
            f"<p class=\"meta\">{esc(robot)}{event['time_s']:.1f}s{duration}</p>"
            f"<p>{esc(event.get('evidence_zh', ''))}</p>"
            f"<a href=\"{esc(event['link'])}\" target=\"_blank\">打开战术板回放</a>"
            "</article>"
        )

    issue_cards = "\n".join(card(event) for event in evidence["events"][:30])
    if not issue_cards:
        issue_cards = '<p class="empty">暂无关键事件。</p>'
    highlight_cards = "\n".join(card(event) for event in evidence["highlights"][:16])
    if not highlight_cards:
        highlight_cards = '<p class="empty">暂无正向片段。</p>'

    notes = "\n".join(
        f"<li><strong>{esc(note['title_zh'])}</strong>：{esc(note['body_zh'])}</li>"
        for note in evidence["standing_notes"]
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>赛后证据看板 - {esc(rec['file'])}</title>
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #172033; background: #f6f7fb; }}
header {{ background: #111827; color: #fff; padding: 28px 36px 22px; }}
h1 {{ margin: 0 0 8px; font-size: 28px; letter-spacing: 0; }}
.sub {{ color: #cbd5e1; font-size: 14px; }}
main {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
.metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 18px; }}
.metric {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px 16px; }}
.metric span {{ display: block; color: #64748b; font-size: 12px; margin-bottom: 5px; }}
.metric strong {{ font-size: 24px; }}
section {{ margin-top: 22px; }}
h2 {{ font-size: 20px; margin: 0 0 12px; }}
table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; }}
th, td {{ padding: 10px 12px; border-bottom: 1px solid #edf0f5; text-align: left; font-size: 13px; }}
th {{ color: #475569; background: #f8fafc; }}
.event-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }}
.event {{ background: #fff; border: 1px solid #e5e7eb; border-left: 5px solid #64748b; border-radius: 8px; padding: 14px 16px; }}
.event.high {{ border-left-color: #dc2626; }}
.event.medium {{ border-left-color: #f59e0b; }}
.event.positive {{ border-left-color: #16a34a; }}
.event h3 {{ margin: 0 0 6px; font-size: 16px; }}
.event p {{ margin: 7px 0; line-height: 1.5; font-size: 13px; }}
.event .meta {{ color: #64748b; }}
.event a {{ display: inline-block; margin-top: 8px; color: #2563eb; text-decoration: none; font-weight: 600; }}
.notes {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px 20px; }}
.notes li {{ margin: 8px 0; line-height: 1.5; }}
.empty {{ color: #64748b; background: #fff; border: 1px dashed #cbd5e1; border-radius: 8px; padding: 16px; }}
</style>
</head>
<body>
<header>
  <h1>赛后证据看板</h1>
  <div class="sub">{esc(rec['file'])} · {rec['duration_s']:.1f}s · {rec['packet_count']} packets · 由脚本提取证据，最终结论请交给 LLM/Codex 撰写</div>
</header>
<main>
  <div class="metrics">
    <div class="metric"><span>机器人</span><strong>{rec['robot_count']}</strong></div>
    <div class="metric"><span>跌倒总数</span><strong>{evidence['summary']['fall_total']}</strong></div>
    <div class="metric"><span>问题事件</span><strong>{evidence['summary']['issue_event_count']}</strong></div>
    <div class="metric"><span>正向片段</span><strong>{evidence['summary']['highlight_count']}</strong></div>
  </div>

  <section>
    <h2>机器人摘要</h2>
    <table>
      <thead><tr><th>机器人</th><th>角色</th><th>包数</th><th>跌倒</th><th>控球率</th><th>本机看球</th><th>团队球有效</th><th>最大线速度</th></tr></thead>
      <tbody>
        {''.join(robot_rows)}
      </tbody>
    </table>
  </section>

  <section>
    <h2>关键事件</h2>
    <div class="event-grid">{issue_cards}</div>
  </section>

  <section>
    <h2>正向片段</h2>
    <div class="event-grid">{highlight_cards}</div>
  </section>

  <section>
    <h2>写报告时必须保留的限制</h2>
    <ul class="notes">{notes}</ul>
  </section>
</main>
</body>
</html>
"""
