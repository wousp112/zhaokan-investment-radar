from fastapi.testclient import TestClient
import pytest

from app.main import create_app


@pytest.fixture
def client(settings):
    app=create_app(settings)
    with TestClient(app) as client:
        yield client


def create(client):
    parsed=client.post('/api/tasks/parse',json={'prompt':'未来两周贵州茅台日内跌幅达到3%，或者发布新的业绩预告','use_ai':False})
    assert parsed.status_code==200, parsed.text
    response=client.post('/api/tasks/create',json={'task_spec':parsed.json()['task_spec']})
    assert response.status_code==201,response.text
    return response.json()


def test_end_to_end_api_and_export(client):
    task=create(client)
    result=client.post('/api/simulate/inject',json={'task_id':task['id'],'scenario':'drop'})
    assert result.status_code==200
    assert result.json()['state']['trigger_count']==1
    evidence=client.get('/api/tasks/'+task['id']+'/export')
    assert evidence.status_code==200
    assert evidence.json()['recent_audits'][0]['notification_sent'] is True
    assert 'owner' not in evidence.json()['task']
    assert client.get('/api/ai-records').json()['records'][0]['compilation']['engine']=='local_rules'


def test_sessions_isolated(client,settings):
    task=create(client)
    first_cookie=client.cookies.get('radar_session')
    client.cookies.clear()
    assert not client.get('/api/tasks').json()['tasks']
    assert client.cookies.get('radar_session')!=first_cookie
    assert client.get('/api/tasks/'+task['id']).status_code==404
    assert client.post('/api/tasks/'+task['id']+'/pause').status_code==404
    assert client.get('/api/tasks/'+task['id']+'/export').status_code==404


def test_cross_site_mutation_rejected(client):
    result=client.post('/api/tasks/parse',json={'prompt':'贵州茅台跌3%','use_ai':False},headers={'origin':'https://untrusted.example'})
    assert result.status_code==403


def test_unknown_fields_and_large_input_rejected(client):
    assert client.post('/api/tasks/parse',json={'prompt':'贵州茅台跌3%','execute':'rm -rf'}).status_code==422
    assert client.post('/api/tasks/parse',json={'prompt':'x'*21000}).status_code==413


def test_rule_edit_conflict_and_rollback(client):
    task=create(client);spec=task['spec'];spec['conditions'][0]['threshold']=-0.035
    assert client.put('/api/tasks/'+task['id'],json={'task_spec':spec,'expected_version':1}).status_code==200
    assert client.put('/api/tasks/'+task['id'],json={'task_spec':spec,'expected_version':1}).status_code==409
    restored=client.post('/api/tasks/'+task['id']+'/rollback',json={'version':1,'expected_version':2})
    assert restored.status_code==200
    assert restored.json()['spec']['version']==3
    assert restored.json()['spec']['conditions'][0]['threshold']==-0.03


def test_live_task_rejects_replay_injection(client):
    task=create(client)
    raw=client.app.state.store.task(task['id'])
    raw['spec']['data_mode']='live'
    client.app.state.store.save(raw)
    response=client.post('/api/simulate/inject',json={'task_id':task['id'],'scenario':'drop'})
    assert response.status_code==422


def test_durable_inbox_has_fact_only_disclaimer(client):
    task=create(client)
    client.post('/api/simulate/inject',json={'task_id':task['id'],'scenario':'drop'})
    alert=client.get('/api/alerts').json()['alerts'][0]
    assert '不构成投资建议' in alert['disclaimer']
    assert all(word not in alert['message'] for word in ('买入','卖出','稳赚'))


def test_service_health_and_security_headers(client):
    result=client.get('/api/health')
    assert result.status_code==200
    assert result.headers['X-Content-Type-Options']=='nosniff'
    assert result.headers['Cache-Control']=='no-store'
