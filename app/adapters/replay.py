"""Explicit deterministic scenario data, isolated per task and persisted."""
from datetime import datetime, timedelta
import uuid

from app.models.dsl import iso


def initial_frame(now):
    return {'change':-0.012,'previous_close':100.0,'heat':1.2,'quote_fault':None,
            'event_fault':None,'market_open':True,'events':[],'clock_offset':0,
            'seeded_at':iso(now)}


def inject(task, scenario, now, advance_seconds=1860):
    frame = task['simulation']
    if scenario in ('normal','drop','deeper'):
        frame['change'] = {'normal':-0.012,'drop':-0.038,'deeper':-0.045}[scenario]
        frame['quote_fault'] = None
    elif scenario in ('announcement','same_announcement'):
        if scenario == 'announcement' or not frame['events']:
            frame['events'].append({'id':'replay_'+uuid.uuid4().hex[:12],
                'symbol':task['spec']['target']['symbol'],'title':'演示公告：公司发布业绩预告',
                'category':'PERFORMANCE_FORECAST','published_at':now.isoformat(),'url':None,
                'source':'内置演示情景','mode':'replay'})
    elif scenario in ('timeout','http500','stale','conflict'):
        frame['quote_fault'] = scenario
    elif scenario == 'event_failure':
        frame['event_fault'] = 'timeout'
    elif scenario == 'recover':
        frame['quote_fault'] = None
        frame['event_fault'] = None
    elif scenario in ('closed','open'):
        frame['market_open'] = scenario == 'open'
    elif scenario == 'advance':
        frame['clock_offset'] += advance_seconds
    elif scenario == 'heat':
        frame['heat'] = 3.6
    task['last_injection'] = {'scenario':scenario,'at':iso(now)}


def snapshot(task, now):
    frame = task['simulation']
    fault = frame['quote_fault']
    errors = {'timeout':'行情接口超时，已模拟3次失败。','http500':'行情接口返回HTTP 500，已模拟3次失败。',
              'stale':'行情时间已过期，停止使用该价格判断。','conflict':'来源价格与计算基准冲突，停止价格判断。'}
    quote = {'source':'内置演示行情','mode':'replay','status':'ok','observed_at':iso(now),
             'last':round(frame['previous_close']*(1+frame['change']),6),'previous_close':frame['previous_close'],
             'change':frame['change'],'heat':frame['heat'],'market_open':frame['market_open'],'request_id':'replay',
             'calendar_source':'演示交易时钟（可在验证台切换）'}
    if fault:
        quote.update(status=fault,reason=errors[fault],attempts=3 if fault in ('timeout','http500') else 1)
        if fault == 'stale':
            quote['observed_at'] = iso(now-timedelta(minutes=20))
    event_result = {'source':'内置演示公告','mode':'replay','status':'ok','observed_at':iso(now),
                    'events':frame['events'],'complete':True,'coverage':'完整的本任务演示事件列表'}
    if frame['event_fault']:
        event_result.update(status='timeout',reason='公告接口超时；价格条件继续检查。',events=[])
    return {'quote':quote,'announcements':event_result}
