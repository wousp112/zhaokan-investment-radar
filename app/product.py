"""User-scoped receipts and operational evidence, without third-party analytics."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from typing import Literal

from fastapi import Query, Request

from app.config import ROOT
from app.models.dsl import StrictModel, utcnow


class AlertFeedback(StrictModel):
    feedback: Literal['useful', 'noisy', 'incorrect'] | None = None


def build_info():
    digest=hashlib.sha256()
    for path in sorted((ROOT/'app').rglob('*')):
        if path.is_file() and path.suffix in ('.py','.js','.html','.css'):
            digest.update(str(path.relative_to(ROOT)).encode())
            digest.update(path.read_bytes())
    return {'version':'1.1.0','source_sha256':digest.hexdigest()}


def percentile(values, quantile):
    if not values:
        return None
    ordered=sorted(values)
    return ordered[max(0,math.ceil(quantile*len(ordered))-1)]


def workspace_metrics(store, owner, mode, days=7):
    now=utcnow(); since=(now-timedelta(days=days)).isoformat()
    with store.connect() as db:
        funnel={r['name']:r['n'] for r in db.execute(
            'SELECT name,COUNT(*) n FROM product_events WHERE owner=? AND mode=? AND recorded_at>=? GROUP BY name',
            (owner,mode,since))}
        # Only records with an actual capture time are eligible. Replay clocks may be advanced.
        where="t.owner=? AND json_extract(a.body,'$.data_mode')=? AND json_extract(a.body,'$.kind')='evaluation' AND json_extract(a.body,'$.recorded_at')>=?"
        args=(owner,mode,since)
        checks=db.execute('SELECT COUNT(*) n,SUM(CASE WHEN json_type(a.body,\'$.overall_triggered\')=\'null\' THEN 1 ELSE 0 END) unknown FROM audits a JOIN tasks t ON t.id=a.task_id WHERE '+where,args).fetchone()
        samples=[json.loads(r[0]) for r in db.execute('SELECT a.body FROM audits a JOIN tasks t ON t.id=a.task_id WHERE '+where+' ORDER BY a.id DESC LIMIT 5000',args)]
        notify=db.execute("SELECT COUNT(*) generated,SUM(CASE WHEN r.read_at IS NOT NULL THEN 1 ELSE 0 END) opened,SUM(CASE WHEN r.feedback='useful' THEN 1 ELSE 0 END) useful,SUM(CASE WHEN r.feedback='noisy' THEN 1 ELSE 0 END) noisy,SUM(CASE WHEN r.feedback='incorrect' THEN 1 ELSE 0 END) incorrect FROM alerts a LEFT JOIN alert_receipts r ON r.alert_id=a.id WHERE a.owner=? AND json_extract(a.body,'$.mode')=? AND json_extract(a.body,'$.recorded_at')>=?",args).fetchone()
        comp=[json.loads(r[0])['compilation'] for r in db.execute("SELECT body FROM compilations WHERE owner=? AND json_extract(body,'$.task_spec.data_mode')=? AND julianday(json_extract(body,'$.compilation.timestamp'))>=julianday(?) ORDER BY rowid DESC LIMIT 5000",(owner,mode,since))]
    durations=[x['duration_ms'] for x in samples if x.get('duration_ms') is not None]
    scheduled=[x for x in samples if x.get('requested_manually') is False]
    requested=sum(bool(c.get('ai_requested')) for c in comp)
    ai_success=sum(c.get('engine')=='deepseek' for c in comp)
    fallbacks=sum(bool(c.get('ai_requested')) and c.get('engine')!='deepseek' for c in comp)
    return {'mode':mode,'period_days':days,'since':since,'as_of':now.isoformat(),
            'scope':'当前浏览器的记录；模拟与真实数据分开。旧记录缺少实际写入时间时不纳入。',
            'parse_requested':funnel.get('parse_requested',0),'parse_ready':funnel.get('parse_ready',0),
            'parse_failed':funnel.get('parse_failed',0),'created':funnel.get('task_created',0),
            'checks':checks['n'],'unknown_checks':checks['unknown'] or 0,
            'notifications':{k:notify[k] or 0 for k in ('generated','opened','useful','noisy','incorrect')},
            'timing':{'sample_size':len(durations),'max_sample_size':5000,'p50_ms':percentile(durations,.5),
                      'p95_ms':percentile(durations,.95),'scheduled_sample_size':len(scheduled),
                      'delay_p95_seconds':percentile([s['schedule_delay_seconds'] for s in scheduled],.95)},
            'ai_completed_drafts':{'requested':requested,'model_output':ai_success,'fallback':fallbacks,
                                  'scope':'已返回草稿的最近最多5000条记录。模型输出不代表字段正确；失败请求见整理失败计数。'},
            'limits':'打开记录不等于手机送达；用户反馈不等于独立正确率。真实漏报率需要完整的公告参考流。'}


def install_product_routes(app, store, engine, settings):
    app.state.build=build_info()

    @app.get('/api/workspace-status')
    async def workspace_status(request:Request):
        tasks=store.tasks(request.state.owner)
        active=[]; overdue=[]
        for task in tasks:
            now=engine.now_for(task); s=task['state']
            if s['status'] in ('ARCHIVED','EXPIRED') or datetime.fromisoformat(task['spec']['validity']['end_time'])<=now:
                continue
            active.append(task)
            due=s.get('next_check_time')
            if settings.scheduler_enabled and not s['paused'] and s['status']!='PENDING' and due:
                delay=(now-datetime.fromisoformat(due)).total_seconds()
                if delay>max(30,task['spec']['governance']['frequency_seconds']):
                    overdue.append({'task_id':task['id'],'delay_seconds':round(delay)})
        return {'active':len(active),'active_limit':settings.max_tasks,'saved':len(tasks),
                'saved_limit':settings.max_saved_tasks,'overdue':overdue,
                'alerts':store.alert_counts(request.state.owner),'build':app.state.build,
                'channels':{'inbox':True,'background_push':False,'email':False},
                'data':{'companies':12,'live_volume_ratio':False,'announcement_coverage':'limited_search'},
                'as_of':utcnow().isoformat()}

    @app.get('/api/alerts/{alert_id}')
    async def alert_detail(alert_id:int, request:Request):
        return store.alert(request.state.owner,alert_id)

    @app.post('/api/alerts/{alert_id}/read')
    async def alert_read(alert_id:int, request:Request):
        return store.acknowledge_alert(request.state.owner,alert_id)

    @app.put('/api/alerts/{alert_id}/feedback')
    async def alert_feedback(alert_id:int, body:AlertFeedback, request:Request):
        return store.acknowledge_alert(request.state.owner,alert_id,body.feedback,True)

    @app.get('/api/workspace-report')
    async def workspace_report(request:Request, mode:Literal['replay','live']='replay',days:int=Query(7,ge=1,le=30)):
        return dict(workspace_metrics(store,request.state.owner,mode,days),build=app.state.build)

    @app.post('/api/tasks/{task_id}/check')
    async def check(task_id:str, request:Request):
        task=await engine.tick(task_id,request.state.owner,force=True)
        return {k:v for k,v in task.items() if k not in ('owner','simulation')}
