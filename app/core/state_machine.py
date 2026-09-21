from datetime import datetime
from decimal import Decimal

from app.models.dsl import SHANGHAI

STATES = {'PENDING':'待确认','ACTIVE':'监控中','SUSPENDED':'已暂停','TRIGGERED':'已触发',
          'COOLING':'冷却中','DEGRADED':'部分数据异常','EXPIRED':'已到期','ARCHIVED':'已归档'}


def compare(actual, operator, threshold):
    a, b = Decimal(str(actual)), Decimal(str(threshold))
    return {'<=':a <= b,'>=':a >= b,'<':a < b,'>':a > b}[operator]


def combine(values, logic):
    if logic == 'OR':
        return True if True in values else (None if None in values else False)
    return False if False in values else (None if None in values else True)


def evaluate(spec, snapshot, now, seen, pending_events):
    results = []
    candidate_keys = []
    day = now.astimezone(SHANGHAI).date().isoformat()
    for condition in spec.conditions:
        c = condition
        evidence = {'id':c.id,'type':c.type,'display_text':c.display_text,'operator':c.operator,
                    'threshold':c.threshold,'satisfied':None,'reason':'','actual_value':None,
                    'source':None,'observed_at':None,'fingerprints':[]}
        if c.type == 'CALENDAR':
            truth = now >= c.at
            evidence.update(satisfied=truth,actual_value=now.isoformat(),source='服务时钟',observed_at=now.isoformat(),
                            reason='已到达指定时间。' if truth else '尚未到达指定时间。')
            if truth:
                evidence['fingerprints'] = [f'calendar:{c.id}:{c.at.isoformat()}']
        elif c.type == 'ANNOUNCEMENT_EVENT':
            data = snapshot['announcements']
            evidence.update(source=data['source'],observed_at=data.get('observed_at'),coverage=data.get('coverage'))
            def matches(event):
                return c.event_category == 'ANY_ANNOUNCEMENT' or event.get('category') == c.event_category
            fresh = [e for e in pending_events.values() if matches(e) and 'event:'+e['id'] not in seen]
            evidence.update(actual_value=len(fresh),events=fresh)
            if fresh:
                evidence.update(satisfied=True,reason=f'有 {len(fresh)} 条已核对、尚未提醒的目标公告。')
                evidence['fingerprints'] = ['event:'+e['id'] for e in fresh]
            elif data['status'] != 'ok':
                evidence['reason'] = data.get('reason','公告数据不可用。')
            elif not data.get('complete',False):
                evidence['reason'] = '当前检索未发现新的目标公告；检索覆盖有限，不能据此确认没有公告。'
            else:
                evidence.update(satisfied=False,reason='本次检查未发现新的目标公告。')
        else:
            data = snapshot['quote']
            evidence.update(source=data['source'],observed_at=data.get('observed_at'),request_id=data.get('request_id'),
                            calendar_source=data.get('calendar_source'))
            if spec.governance.trading_hours_only and data.get('market_open') is False:
                evidence.update(reason='非交易时段，价格与量比条件静默；公告继续检查。',suspended=True)
            elif data['status'] != 'ok':
                evidence['reason'] = data.get('reason','行情数据不可用。')
                evidence['attempts'] = data.get('attempts')
            else:
                metric = {'PRICE_CHANGE_RATIO':'change','PRICE':'last','HEAT':'heat'}[c.type]
                actual = data.get(metric)
                if actual is None:
                    evidence['reason'] = '来源未返回此指标，暂时无法判断。'
                else:
                    value = compare(actual,c.operator,c.threshold)
                    evidence.update(satisfied=value,actual_value=actual,reason='已达到设定条件。' if value else '尚未达到设定条件。')
                    if c.type == 'PRICE_CHANGE_RATIO':
                        evidence.update(last=data.get('last'),previous_close=data.get('previous_close'),formula='(现价 / 昨收价) - 1')
                    if value:
                        evidence['fingerprints'] = [f'price:{spec.version}:{c.id}:{day}']
        evidence['fresh_fingerprints'] = [k for k in evidence['fingerprints'] if k not in seen]
        if evidence['satisfied']:
            candidate_keys.extend(evidence['fresh_fingerprints'])
        results.append(evidence)
    return results, combine([r['satisfied'] for r in results],spec.condition_logic), sorted(set(candidate_keys))
