import asyncio
from datetime import timedelta
import pytest

from app.adapters.fuyao_adapter import Fuyao
from app.models.dsl import Condition


@pytest.mark.parametrize('scenario',['timeout','http500','stale','conflict'])
async def test_bad_quote_is_unknown_not_false(engine,spec,scenario):
    task=await engine.create(spec,'owner')
    result=await engine.inject(task['id'],'owner',scenario)
    assert result['state']['status']=='DEGRADED'
    audit=engine.store.audits(task['id'])[0]
    assert audit['conditions_evaluated'][0]['satisfied'] is None
    assert audit['overall_triggered'] is None
    assert result['state']['trigger_count']==0
    restored=await engine.inject(task['id'],'owner','recover')
    assert restored['state']['status']=='ACTIVE'
    assert len([a for a in engine.store.alerts('owner') if a['kind']=='recovery'])==1


async def test_healthy_event_still_triggers_with_quote_outage(engine,spec):
    task=await engine.create(spec,'owner')
    await engine.inject(task['id'],'owner','timeout')
    result=await engine.inject(task['id'],'owner','announcement')
    assert result['state']['trigger_count']==1
    assert result['state']['status']=='DEGRADED'


async def test_and_needs_all_conditions_known(engine,spec):
    spec.condition_logic='AND'
    task=await engine.create(spec,'owner')
    await engine.inject(task['id'],'owner','timeout')
    result=await engine.inject(task['id'],'owner','announcement')
    assert result['state']['trigger_count']==0
    assert engine.store.audits(task['id'])[0]['overall_triggered'] is None


async def test_announcement_failure_does_not_stop_price(engine,spec):
    task=await engine.create(spec,'owner')
    await engine.inject(task['id'],'owner','event_failure')
    result=await engine.inject(task['id'],'owner','drop')
    assert result['state']['trigger_count']==1


async def test_market_close_keeps_announcement_monitoring(engine,spec):
    task=await engine.create(spec,'owner')
    await engine.inject(task['id'],'owner','closed')
    result=await engine.inject(task['id'],'owner','announcement')
    assert result['state']['trigger_count']==1
    assert engine.store.audits(task['id'])[0]['conditions_evaluated'][0]['suspended']


async def test_price_only_market_pause_auto_recovers(engine,spec):
    spec.conditions=spec.conditions[:1]
    task=await engine.create(spec,'owner')
    result=await engine.inject(task['id'],'owner','closed')
    assert result['state']['status']=='SUSPENDED'
    assert result['state']['paused'] is False
    result=await engine.inject(task['id'],'owner','open')
    assert result['state']['status']=='ACTIVE'


async def test_failure_does_not_advance_event_cursor(engine,spec,clock):
    task=await engine.create(spec,'owner')
    original=task['state']['event_cursor']
    clock.advance(120)
    result=await engine.inject(task['id'],'owner','event_failure')
    assert result['state']['event_cursor']==original


async def test_health_outage_is_not_repeated(engine,spec):
    task=await engine.create(spec,'owner')
    for _ in range(4):
        await engine.inject(task['id'],'owner','timeout')
    assert len([a for a in engine.store.alerts('owner') if a['kind']=='health'])==1


async def test_missing_live_credentials_are_explicit(settings,clock):
    settings.fuyao_key_file='/nonexistent/unit-test-key'
    result=await Fuyao(settings).quote('600519.SH',clock())
    assert result['status']=='unconfigured'
    assert result['mode']=='live'
    assert result['observed_at'] is None
