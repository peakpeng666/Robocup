#!/usr/bin/env python3
"""Measure visual loss and actual native mode handoffs in retained run events."""
import argparse
import json
from pathlib import Path


def analyze(events):
    modes = [e for e in events if e['event'] == 'NATIVE_PLANNER']
    replies = {e['uuid']: e for e in events if e['event'] == 'SDK_REPLY'}
    requests = [e for e in events if e['event'] == 'SDK_REQUEST' and e['origin'] == 'official_brain']
    starts = [e for e in requests if e['api_id'] == 2038 and json.loads(e['body']).get('start') is True]
    walks = [e for e in requests if e['api_id'] == 2000 and json.loads(e['body']).get('mode') == 2]

    def mode_at(step):
        return next((m['planner'] for m in reversed(modes) if m['step'] <= step), None)

    def next_walk(step):
        return next((m['step'] for m in modes if m['step'] > step and m['planner'] in (10, 20)), None)

    def reply_status(request):
        return replies.get(request['uuid'], {}).get('status')

    start_rows = [{'step': e['step'], 'seconds': e['step']*.002, 'native_mode_before': mode_at(e['step']),
                   'reply_status': reply_status(e)} for e in starts]
    exits = []
    for request in walks:
        step = request['step']
        if mode_at(step) not in (12, 22):
            continue
        completion = next_walk(step)
        overlap = [e['step'] for e in starts if step < e['step'] and
                   (completion is None or e['step'] < completion)]
        exits.append({'request_step': step, 'reply_status': reply_status(request),
                      'actual_walk_step': completion,
                      'native_transition_s': (completion-step)*.002 if completion is not None else None,
                      'premature_restart_steps': overlap})

    losses = []
    lost = False
    for event in events:
        if event['event'] != 'BEHAVIOR_TRANSITION':
            continue
        new_lost = event['lose_ball']
        if new_lost and not lost:
            step = event['step']
            seen = [e['step'] for e in events if e['event'] == 'OFFICIAL_PERCEPTION'
                    and e['step'] <= step and e['ball_detected']]
            if seen:
                last_seen = max(seen)
                request = next((e for e in exits if step <= e['request_step'] <= step+2500), None)
                completion = request['actual_walk_step'] if request else None
                losses.append({'last_seen_step': last_seen, 'lost_flag_step': step,
                               'memory_delay_s': (step-last_seen)*.002,
                               'exit_request_step': request['request_step'] if request else None,
                               'walk_resumed_step': completion,
                               'last_seen_to_walk_s': (completion-last_seen)*.002 if completion else None})
        lost = new_lost

    checks = {'every_start_from_actual_walk': all(e['native_mode_before'] in (10, 20) for e in start_rows),
              'every_start_accepted': all(e['reply_status'] == 0 for e in start_rows),
              'no_restart_during_exit': all(not e['premature_restart_steps'] for e in exits)}
    return {'status': 'PASS' if all(checks.values()) else 'FAIL', 'checks': checks,
            'visual_starts': start_rows, 'visual_exits': exits, 'loss_windows': losses,
            'pending_exits_at_end': sum(e['actual_walk_step'] is None for e in exits)}


def audit(run):
    result = json.loads((run/'result.json').read_text())
    report = {'schema': 'forge.official-mode-handoff/1', 'full_real2sim_qualified': False,
              'scope': 'RPC/mode overlap and measured latency; not a general reaction-speed qualification',
              'robots': {}}
    for name in ('robot21', 'robot22', 'robot23'):
        events = [json.loads(line) for line in (run/name/'application.jsonl').read_text().splitlines()]
        report['robots'][name] = analyze(events)
    report['status'] = 'PASS' if all(r['status'] == 'PASS' for r in report['robots'].values()) else 'FAIL'
    report['wall_seconds'] = result['execution']['wall_s']
    report['sim_seconds'] = max(r['steps'] for r in result['application_results'].values())*.002
    report['realtime_factor'] = report['sim_seconds']/report['wall_seconds']
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.run)
    with args.output.open('x') as handle:
        json.dump(report, handle, indent=2)
        handle.write('\n')
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['status'] == 'PASS' else 1)
