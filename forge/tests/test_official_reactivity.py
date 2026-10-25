import json

from tools.audit_official_reactivity import analyze


def test_exit_restart_race_and_original_loss_delay_are_measured():
    def request(step, api, body, uid):
        return dict(event='SDK_REQUEST', step=step, origin='official_brain', api_id=api,
                    body=json.dumps(body), uuid=uid)
    events = [dict(event='NATIVE_PLANNER',step=1,planner=20),
              request(100,2038,{'start':True},'start'),
              dict(event='SDK_REPLY',step=102,uuid='start',status=0),
              dict(event='NATIVE_PLANNER',step=700,planner=22),
              dict(event='OFFICIAL_PERCEPTION',step=800,ball_detected=True),
              dict(event='BEHAVIOR_TRANSITION',step=1820,lose_ball=True),
              request(2070,2000,{'mode':2},'exit'),
              dict(event='SDK_REPLY',step=2072,uuid='exit',status=0),
              request(2300,2038,{'start':True},'premature'),
              dict(event='SDK_REPLY',step=2302,uuid='premature',status=501),
              dict(event='NATIVE_PLANNER',step=2570,planner=20)]
    report = analyze(events)
    assert report['status']=='FAIL'
    assert report['visual_exits'][0]['premature_restart_steps']==[2300]
    assert report['loss_windows'][0]['memory_delay_s']==2.04
    assert report['loss_windows'][0]['last_seen_to_walk_s']==3.54
    # Acknowledgement remains immediate; success requires actual walk feedback.
    corrected=[e for e in events if e.get('uuid')!='premature']
    corrected += [request(2600,2038,{'start':True},'restart'),
                  dict(event='SDK_REPLY',step=2602,uuid='restart',status=0)]
    result=analyze(corrected)
    assert result['status']=='PASS'
    assert result['visual_exits'][0]['native_transition_s']==1.0
