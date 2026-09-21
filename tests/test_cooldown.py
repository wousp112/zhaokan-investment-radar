import asyncio
from datetime import timedelta
import pytest

from app.core.audit_logger import Store
from app.core.scheduler import Engine
from app.models.dsl import Condition


async def make(engine,spec):
    return await engine.create(spec,'owner')


async def test_golden_not_triggered_then_triggered(engine,spec):
    task=await make(engine,spec)
    result=await engine.tick(task['id'],'owner',True)
    assert result['state']['trigger_count']==0
    audit=engine.store.audits(task['id'])[0]
    assert audit['overall_triggered'] is False
    assert len(audit['conditions_evaluated'])==2
    result=await engine.inject(task['id'],'owner','drop')
    assert result['state']['trigger_count']==1
    assert result['state']['status']=='COOLING'
    assert engine.store.audits(task['id'])[0]['transitions']==['TRIGGERED','COOLING']


async def test_price_dedup_survives_cooldown_and_restart(engine,spec,clock,settings):
    task=await make(engine,spec)
    await engine.inject(task['id'],'owner','drop')
    for _ in range(10):
        await engine.inject(task['id'],'owner','deeper')
    clock.advance(1801)
    result=await engine.tick(task['id'],'owner',True)
    assert result['state']['trigger_count']==1
    restored=Engine(Store(settings.data_dir),settings,clock=clock)
    await restored.start()
    result=await restored.tick(task['id'],'owner',True)
    assert result['state']['trigger_count']==1
    clock.advance(86400)
    result=await restored.tick(task['id'],'owner',True)
    assert result['state']['trigger_count']==2


async def test_unique_notice_queued_in_cooldown(engine,spec,clock):
    task=await make(engine,spec)
    await engine.inject(task['id'],'owner','drop')
    pending=await engine.inject(task['id'],'owner','announcement')
    assert len(pending['state']['pending_events'])==1
    assert pending['state']['trigger_count']==1
    clock.advance(1801)
    result=await engine.tick(task['id'],'owner',True)
    assert result['state']['trigger_count']==2
    assert not result['state']['pending_events']
    clock.advance(1801)
    result=await engine.inject(task['id'],'owner','same_announcement')
    assert result['state']['trigger_count']==2


async def test_manual_pause_and_resume(engine,spec):
    task=await make(engine,spec)
    await engine.change_state(task['id'],'owner','pause')
    result=await engine.inject(task['id'],'owner','drop')
    assert result['state']['check_count']==0
    await engine.change_state(task['id'],'owner','resume')
    result=await engine.tick(task['id'],'owner',True)
    assert result['state']['trigger_count']==1


async def test_expiration_and_archive(engine,spec,clock):
    task=await make(engine,spec)
    clock.advance(15*86400)
    result=await engine.tick(task['id'],'owner',True)
    assert result['state']['status']=='EXPIRED'
    assert result['state']['check_count']==0


async def test_version_conflict_and_event_dedup_across_edit(engine,spec,clock):
    task=await make(engine,spec)
    await engine.inject(task['id'],'owner','announcement')
    spec.conditions[0].threshold=-0.04
    updated=await engine.edit(task['id'],'owner',spec,1)
    assert updated['spec']['version']==2
    with pytest.raises(RuntimeError):
        await engine.edit(task['id'],'owner',spec,1)
    clock.advance(1801)
    result=await engine.inject(task['id'],'owner','same_announcement')
    assert result['state']['trigger_count']==1
    assert len(engine.store.versions(task['id']))==2


async def test_fifty_checks_have_complete_evidence(engine,spec):
    task=await make(engine,spec)
    for _ in range(50):
        await engine.tick(task['id'],'owner',True)
    history=[x for x in engine.store.audits(task['id']) if x['kind']=='evaluation']
    assert len(history)==50
    assert all(x['spec_hash'] and x['timestamp'] and len(x['conditions_evaluated'])==2 for x in history)


async def test_concurrent_checks_emit_single_alert(engine,spec):
    task=await make(engine,spec)
    task['simulation']['change']=-0.04
    engine.store.save(task)
    await asyncio.gather(*(engine.tick(task['id'],'owner',True) for _ in range(8)))
    assert len([a for a in engine.store.alerts('owner') if a['kind']=='condition'])==1


async def test_calendar_and_heat_use_same_engine(engine,spec,clock):
    spec.conditions=[Condition(id='calendar',type='CALENDAR',at=clock()+timedelta(seconds=30)),
                     Condition(id='heat',type='HEAT',threshold=3,operator='>=')]
    task=await make(engine,spec)
    initial=await engine.tick(task['id'],'owner',True)
    assert initial['state']['trigger_count']==0
    result=await engine.inject(task['id'],'owner','heat')
    assert result['state']['trigger_count']==1
    clock.advance(1860)
    result=await engine.tick(task['id'],'owner',True)
    assert result['state']['trigger_count']==2


async def test_store_transaction_rollback(engine,spec):
    task=await make(engine,spec)
    original=engine.store.task(task['id'])
    task['state']['trigger_count']=999
    with pytest.raises(KeyError):
        engine.store.save(task,alerts=[{'no_fingerprint':True}])
    assert engine.store.task(task['id'])['state']['trigger_count']==original['state']['trigger_count']
