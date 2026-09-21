"""Product-level regressions: retries, receipts, measurement and bounded promises."""
import copy
from datetime import timedelta

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.models.dsl import TaskSpec, iso, utcnow
from app.product import percentile, workspace_metrics


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as browser:
        yield browser


def draft(client, **extra):
    response=client.post('/api/tasks/parse',json={
        'prompt':'未来两周贵州茅台下跌达到3%，或者发布新的业绩预告',
        'use_ai':False,**extra})
    assert response.status_code==200,response.text
    return response.json()['task_spec']


def create(client, **extra):
    response=client.post('/api/tasks/create',json={'task_spec':draft(client),**extra})
    assert response.status_code==201,response.text
    return response.json()


def drop(client, task):
    response=client.post('/api/simulate/inject',json={'task_id':task['id'],'scenario':'drop'})
    assert response.status_code==200,response.text
    return client.get('/api/alerts').json()['alerts'][0]


def test_creation_retry_returns_one_task_even_after_restart(client,settings):
    body={'task_spec':draft(client),'request_key':'test-retry-000001'}
    first=client.post('/api/tasks/create',json=body)
    again=client.post('/api/tasks/create',json=body)
    assert first.status_code==again.status_code==201
    assert first.json()['id']==again.json()['id']
    assert len(client.get('/api/tasks').json()['tasks'])==1
    # Reopen the database through another app without a second running scheduler.
    replacement=TestClient(create_app(settings))
    replacement.cookies.set('radar_session',client.cookies.get('radar_session'))
    assert replacement.post('/api/tasks/create',json=body).json()['id']==first.json()['id']
    changed=copy.deepcopy(body);changed['task_spec']['conditions'][0]['threshold']=-.04
    assert client.post('/api/tasks/create',json=changed).status_code==409
    assert client.get('/api/workspace-report').json()['created']==1


def test_creation_key_is_scoped_to_visitor(client):
    body={'task_spec':draft(client),'request_key':'test-retry-000002'}
    first=client.post('/api/tasks/create',json=body).json()
    client.cookies.clear()
    client.get('/api/meta')
    second=client.post('/api/tasks/create',json=body).json()
    assert first['id']!=second['id']
    assert len(client.get('/api/tasks').json()['tasks'])==1


def test_archiving_frees_running_quota_but_preserves_history(client,settings):
    settings.max_tasks=1
    first=create(client)
    body={'task_spec':draft(client)}
    assert client.post('/api/tasks/create',json=body).status_code==422
    assert client.delete('/api/tasks/'+first['id']).status_code==200
    assert client.post('/api/tasks/create',json=body).status_code==201
    status=client.get('/api/workspace-status').json()
    assert (status['active'],status['saved'])==(1,2)
    assert client.get('/api/tasks/'+first['id']+'/audit-trail').json()['history']


def test_history_capacity_is_not_unbounded(client,settings):
    settings.max_saved_tasks=1
    first=create(client);client.delete('/api/tasks/'+first['id'])
    assert client.post('/api/tasks/create',json={'task_spec':draft(client)}).status_code==422


def test_alert_read_is_explicit_and_idempotent_and_evidence_stays_frozen(client):
    task=create(client);alert=drop(client,task)
    assert alert['read_at'] is None
    original=client.get('/api/alerts/'+str(alert['id'])).json()
    assert client.get('/api/alerts').json()['unread']==1
    spec=task['spec'];spec['conditions'][0]['threshold']=-.04
    assert client.put('/api/tasks/'+task['id'],json={'task_spec':spec,'expected_version':1}).status_code==200
    now=client.get('/api/alerts/'+str(alert['id'])).json()
    assert now['evidence']==original['evidence']
    assert now['rule_version']==1
    path='/api/alerts/'+str(alert['id'])+'/read'
    first=client.post(path).json();second=client.post(path).json()
    assert first['read_at']==second['read_at'] and first['read_at'] is not None
    assert client.get('/api/alerts').json()['unread']==0


def test_feedback_persists_and_can_be_withdrawn(client,settings):
    alert=drop(client,create(client));path='/api/alerts/'+str(alert['id'])+'/feedback'
    assert client.put(path,json={'feedback':'useful'}).json()['feedback']=='useful'
    reader=TestClient(create_app(settings));reader.cookies.set('radar_session',client.cookies.get('radar_session'))
    assert reader.get('/api/alerts/'+str(alert['id'])).json()['feedback']=='useful'
    assert client.get('/api/workspace-report').json()['notifications']['useful']==1
    assert client.put(path,json={'feedback':None}).json()['feedback'] is None
    assert client.get('/api/workspace-report').json()['notifications']['useful']==0
    assert client.put(path,json={'feedback':'arbitrary HTML'}).status_code==422


def test_receipts_and_reports_are_owner_scoped(client):
    alert=drop(client,create(client));client.cookies.clear();client.get('/api/meta')
    prefix='/api/alerts/'+str(alert['id'])
    assert client.get(prefix).status_code==404
    assert client.post(prefix+'/read').status_code==404
    assert client.put(prefix+'/feedback',json={'feedback':'incorrect'}).status_code==404
    assert client.get('/api/workspace-report').json()['notifications']['generated']==0
    assert client.get('/api/workspace-status').json()['saved']==0


def test_cursor_pagination_and_unread_filter_cover_old_notifications(client):
    task=create(client);store=client.app.state.store;raw=store.task(task['id'])
    rows=[{'task_id':task['id'],'fingerprint':'page-'+str(i),'timestamp':iso(utcnow()),'kind':'condition',
           'title':'分页测试','message':'模拟测试','mode':'replay'} for i in range(103)]
    store.save(raw,alerts=rows)
    page1=client.get('/api/alerts?limit=50').json()
    page2=client.get('/api/alerts',params={'limit':50,'before_id':page1['next_cursor']}).json()
    page3=client.get('/api/alerts',params={'limit':50,'before_id':page2['next_cursor']}).json()
    ids=[r['id'] for p in (page1,page2,page3) for r in p['alerts']]
    assert len(ids)==len(set(ids))==103
    assert not page3['has_more'] and page3['next_cursor'] is None
    assert page1['total']==103
    client.post('/api/alerts/'+str(ids[0])+'/read')
    assert client.get('/api/alerts?unread_only=true').json()['unread']==102
    assert ids[0] not in [r['id'] for r in client.get('/api/alerts?unread_only=true').json()['alerts']]
    assert client.get('/api/alerts?limit=101').status_code==422


def test_metrics_use_actual_capture_time_and_keep_live_separate(client):
    task=create(client)
    client.post('/api/simulate/inject',json={'task_id':task['id'],'scenario':'advance','advance_seconds':3*86400})
    drop(client,task)
    replay=client.get('/api/workspace-report?mode=replay').json()
    live=client.get('/api/workspace-report?mode=live').json()
    assert replay['checks']>=2 and replay['notifications']['generated']==1
    assert replay['timing']['p95_ms'] is not None
    assert replay['timing']['scheduled_sample_size']==0
    assert live['checks']==0 and live['timing']['p95_ms'] is None
    assert live['notifications']['generated']==0
    assert client.get('/api/workspace-report?days=0').status_code==422


def test_legacy_records_without_capture_time_are_not_presented_as_new(client):
    task=create(client);store=client.app.state.store
    with store.connect() as db:
        db.execute('INSERT INTO audits(task_id,body) VALUES(?,?)',(task['id'],
          '{"kind":"evaluation","data_mode":"replay","overall_triggered":true,"timestamp":"2026-09-21T10:00:00+08:00"}'))
    assert client.get('/api/workspace-report').json()['checks']==0


def test_stale_heartbeat_does_not_claim_scheduler_healthy(client,settings):
    settings.scheduler_enabled=True
    engine=client.app.state.engine
    engine.heartbeat=iso(utcnow()-timedelta(minutes=2))
    data=client.get('/api/health').json()
    assert data['status']=='attention' and data['heartbeat_stale'] is True
    settings.scheduler_enabled=False
    assert client.get('/api/health').json()['scheduler_enabled'] is False


def test_late_checks_are_visible_but_paused_tasks_are_not_overdue(client,settings):
    task=create(client);store=client.app.state.store;raw=store.task(task['id'])
    raw['state']['next_check_time']=iso(utcnow()-timedelta(minutes=3));store.save(raw)
    settings.scheduler_enabled=True
    assert client.get('/api/workspace-status').json()['overdue'][0]['task_id']==task['id']
    client.post('/api/tasks/'+task['id']+'/pause')
    assert client.get('/api/workspace-status').json()['overdue']==[]


@pytest.mark.parametrize('point',['parse','create','edit'])
def test_unavailable_live_volume_ratio_cannot_be_activated(client,point):
    # Exercise the unavailable metric specifically, independently of CI's
    # instance-wide real-data switch. No provider is called by these requests.
    client.app.state.settings.allow_live=True
    heat={'id':'heat','type':'HEAT','operator':'>=','threshold':3}
    if point=='parse':
        result=client.post('/api/tasks/parse',json={'prompt':'贵州茅台量比达到3','data_mode':'live','use_ai':False})
    else:
        spec=draft(client);spec.update(data_mode='live')
        if point=='create':
            spec['conditions']=[heat]
            result=client.post('/api/tasks/create',json={'task_spec':spec})
        else:
            task=client.post('/api/tasks/create',json={'task_spec':spec}).json()
            spec['conditions']=[heat]
            result=client.put('/api/tasks/'+task['id'],json={'task_spec':spec,'expected_version':1})
    assert result.status_code==422
    assert '量比' in result.json()['error']


def test_api_cannot_silently_override_a_conflicting_company(client):
    result=client.post('/api/tasks/parse',json={'prompt':'贵州茅台下跌达到3%',
        'target':{'name':'宁德时代','symbol':'300750.SZ'},'use_ai':False})
    assert result.status_code==422 and '统一公司' in result.json()['error']


@pytest.mark.parametrize('prompt',['贵州茅台连续3天下跌达到3%','贵州茅台先下跌3%再发布业绩预告','贵州茅台下跌3%，排除周五'])
def test_temporal_and_exclusion_conditions_are_not_silently_dropped(client,prompt):
    assert client.post('/api/tasks/parse',json={'prompt':prompt,'use_ai':False}).status_code==422


def test_manual_calendar_must_fall_inside_monitoring_window(client):
    spec=draft(client)
    spec['conditions']=[{'id':'date','type':'CALENDAR','at':spec['validity']['end_time']}]
    assert client.post('/api/tasks/create',json={'task_spec':spec}).status_code==422
    spec['conditions'][0]['at']=iso(utcnow()+timedelta(days=1))
    assert client.post('/api/tasks/create',json={'task_spec':spec}).status_code==201


def test_percentiles_have_explicit_empty_and_small_sample_behavior():
    assert percentile([],.95) is None
    assert percentile([4],.95)==4
    assert percentile(list(range(1,101)),.95)==95


def test_failed_parses_count_without_storing_input_as_telemetry(client):
    prompt='这里是无法解析的内容'
    assert client.post('/api/tasks/parse',json={'prompt':prompt,'use_ai':False}).status_code==422
    report=client.get('/api/workspace-report').json()
    assert (report['parse_requested'],report['parse_failed'],report['parse_ready'])==(1,1,0)
    assert prompt not in str(report)


def test_check_history_cursor_covers_all_records_and_resists_cross_visitor_read(client):
    task=create(client);store=client.app.state.store;raw=store.task(task['id'])
    for i in range(105):
        store.save(raw,audit={'kind':'evaluation','data_mode':'replay','ordinal':i})
    url='/api/tasks/'+task['id']+'/audit-trail'
    collected=[];cursor=None
    while True:
        params={'limit':40}
        if cursor:params['before_id']=cursor
        page=client.get(url,params=params).json()
        collected.extend(x['audit_id'] for x in page['history'])
        if not page['has_more']:break
        cursor=page['next_cursor']
        # A new check arriving during pagination does not shift the older cursor.
        store.save(raw,audit={'kind':'evaluation','data_mode':'replay','ordinal':'new'})
    assert len(collected)==len(set(collected))==106
    assert client.get(url,params={'limit':101}).status_code==422
    client.cookies.clear();client.get('/api/meta')
    assert client.get(url).status_code==404


def test_creation_cannot_claim_another_visitors_ai_record(client):
    parsed=client.post('/api/tasks/parse',json={'prompt':'贵州茅台下跌达到3%','use_ai':False}).json()
    body={'task_spec':parsed['task_spec'],'compilation_id':parsed['compilation']['compilation_id']}
    assert client.post('/api/tasks/create',json=body).status_code==201
    client.cookies.clear();client.get('/api/meta')
    denied=client.post('/api/tasks/create',json=body)
    assert denied.status_code==422 and '当前浏览器' in denied.json()['error']
    assert client.get('/api/tasks').json()['tasks']==[]
    body['compilation_id']=None
    assert client.post('/api/tasks/create',json=body).status_code==201
