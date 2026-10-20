---
name: match-analyst
description: RoboCup telemetry post-match analyst for this repository. Use when Codex needs to inspect JSONL match recordings under tools/telemetry_viewer/recordings/, extract deterministic evidence, open replay links, and write Chinese post-match analysis reports in tools/telemetry_viewer/analyses/. Triggers include analysing a match, reviewing a recording, creating a Chinese 赛后复盘/赛后分析报告, finding fall/collision/localization/ball-observation issues, or turning telemetry evidence into Chinese coaching and code-improvement notes.
---

# Match Analyst

Act as the Chinese RoboCup post-match analyst for this repository. Do not ask a script to write the final judgment. Use scripts to extract reliable evidence, then write the final report yourself from that evidence and any source-code checks you perform.

## Workflow

1. Identify the recording:
   - Default directory: `tools/telemetry_viewer/recordings/`
   - Output directory: `tools/telemetry_viewer/analyses/`
2. Generate the evidence package:

```bash
python3 tools/telemetry_viewer/analyst_skill/scripts/match_analyst.py \
  tools/telemetry_viewer/recordings/<match>.jsonl \
  --force
```

For all recordings:

```bash
python3 tools/telemetry_viewer/analyst_skill/scripts/match_analyst.py --all
```

3. Read the generated artifacts:
   - `<match>_evidence.json`: machine-readable facts, events, highlights, and telemetry limitations.
   - `<match>_brief.md`: Chinese LLM writing brief with key replay links.
   - `<match>_evidence.html`: visual evidence dashboard with event cards and replay links.
4. Open or cite replay links for important moments. Links target the local viewer:
   - Start server: `python3 tools/telemetry_viewer/viewer_server.py`
   - Link form: `http://127.0.0.1:8090/?replay=<file>&t=<ms>`
5. Inspect source code for the top 2-3 issues before claiming root causes.
6. Write the final Chinese report to `tools/telemetry_viewer/analyses/<match>_analysis.md` unless the user asks for inline output only.

## Report Requirements

Write naturally in Chinese. Structure the report around evidence, not script sections:

- 一句话结论
- 比赛概况
- 关键问题与证据
- 正向片段
- 可能的代码根因
- 下一步改进建议

For every behavioral claim, cite a replay time or link from the evidence package. For every code claim, cite the source file/function/node you inspected. If the telemetry supports a hypothesis but not a confirmed cause, say so explicitly.

## What the Evidence Extractor Covers

The scripts deterministically extract:

- robot summaries: role, packet count, decision distribution, lead rate, ball visibility, falls, movement rate
- game-state timeline
- fall/recovery segments and pre-fall motion context
- close teammate proximity and near-obstacle events
- long local-ball-lost stretches
- localization jumps
- sustained lead+attack sequences and fast recoveries
- known telemetry limitations and suggested observability gaps

The extractor intentionally does not write the final report. Treat `<match>_brief.md` as a writing brief, not an answer.

## Source Files Worth Checking

Load only what is relevant to the observed events:

- `src/brain/src/telemetry_sender.cpp`: emitted telemetry fields, rate limit, timestamp logic
- `src/brain/include/brain_data.h`: runtime state that may be missing from telemetry
- `src/brain/behavior_trees/game.xml`: STOP/PAUSE/SET branches and `clear_decision`
- `src/brain/behavior_trees/subtrees/subtree_striker_play.xml`: striker chase/pass/shoot decisions
- `src/brain/behavior_trees/subtrees/subtree_goal_keeper_play.xml`: goalkeeper branches that may not emit `decision`
- `src/brain/behavior_trees/subtrees/subtree_auto_standup_and_locate.xml`: fall recovery and relocalization
- `src/brain/src/brain_tree.cpp`: decision mode mapping and behavior-tree integration

## Guardrails

- Telemetry is usually 1Hz. Do not infer sub-second gait or collision causality from it.
- `decision=""` is often a deliberate clear-decision state, not necessarily missing data.
- Treat `team_ball.age_ms` cautiously; prior telemetry showed clock-domain issues.
- Include positive moments as well as failures.
- Keep recommendations concrete: name a file, behavior-tree node, parameter, or telemetry field to add.
