from datetime import timedelta
import asyncio
from unittest.mock import AsyncMock
import pytest
from pydantic import ValidationError

from app.adapters.live import LiveProvider
from app.core.nlp_compiler import Compiler, Clarification, local_extract
from app.models.dsl import Governance, ParseRequest


@pytest.mark.parametrize('prompt',['贵州茅台跌3%且市盈率高于30','贵州茅台跌3%且出现利空新闻','贵州茅台跌3%也不要提醒','贵州茅台跌3%或上涨5%且发布业绩预告'])
async def test_cannot_silently_discard_unsupported_clause(settings,prompt):
    with pytest.raises(Clarification):
        await Compiler(settings).compile(ParseRequest(prompt=prompt,use_ai=True))


def test_fixed_dedup_policy_cannot_be_silently_changed():
    with pytest.raises(ValidationError):
        Governance(deduplication_keys=[])
    with pytest.raises(ValidationError):
        Governance(alert_channels=[])


async def test_expired_task_can_be_archived(engine,spec,clock):
    task=await engine.create(spec,'owner')
    clock.advance(15*86400)
    await engine.tick(task['id'],'owner',True)
    result=await engine.change_state(task['id'],'owner','archive')
    assert result['state']['status']=='ARCHIVED'


async def test_new_event_keeps_subsecond_timestamp(engine,spec,clock):
    clock.advance(0.9)
    spec.validity.start_time=clock()
    task=await engine.create(spec,'owner')
    await engine.inject(task['id'],'owner','drop')
    result=await engine.inject(task['id'],'owner','announcement')
    assert len(result['state']['pending_events'])==1


async def test_full_assignment_golden_case_keeps_system_governance(settings):
    prompt='未来两周帮我盯住贵州茅台：日内跌幅达到3%，或者发布新的业绩预告，就提醒我。同一件事别反复提醒；如果监控出了问题，也告诉我。'
    result=await Compiler(settings).compile(ParseRequest(prompt=prompt,use_ai=False))
    spec=result['task_spec']
    assert len(spec['conditions'])==2
    assert spec['condition_logic']=='OR'
    assert spec['governance']['cooldown_minutes']==30
    assert set(spec['governance']['deduplication_keys'])=={'announcement_id','trading_date'}


async def test_unexpected_source_error_does_not_cancel_other_source(engine,spec,settings,clock):
    task=await engine.create(spec,'owner')
    provider=LiveProvider(settings)
    provider.fuyao.quote=AsyncMock(side_effect=RuntimeError('unexpected provider result'))
    provider.ifind.notices=AsyncMock(return_value={'status':'ok','events':[],'complete':False,'source':'iFinD'})
    output=await provider.snapshot(task,clock())
    assert output['quote']['status']=='unavailable'
    assert output['announcements']['status']=='ok'


def test_ratio_and_absolute_price_are_both_preserved():
    result = local_extract('贵州茅台跌3%或者股价低于1500元提醒')
    assert [(c.type, c.operator, c.threshold) for c in result.conditions] == [
        ('PRICE_CHANGE_RATIO', '<=', -0.03), ('PRICE', '<', 1500)]
    assert result.logic == 'OR'


@pytest.mark.parametrize('word,operator', [('超过','>'), ('达到','>='), ('低于','<'), ('不高于','<=')])
def test_heat_comparator_keeps_strict_boundary(word, operator):
    result = local_extract(f'中芯国际量比{word}3时提醒')
    assert result.conditions[0].operator == operator
    assert result.conditions[0].threshold == 3


@pytest.mark.parametrize('phrase', ['跌幅低于3%', '涨幅不超过5%', '下跌小于2%'])
def test_local_parser_does_not_reverse_unsupported_ratio_comparator(phrase):
    with pytest.raises(Clarification):
        local_extract('贵州茅台' + phrase)


async def test_slow_live_task_does_not_lock_another_task(engine, spec):
    # This test supplies a fake provider; its mode must not inherit CI's UI restriction.
    engine.settings.allow_live = True
    replay_task = await engine.create(spec.model_copy(deep=True), 'owner')
    live_spec = spec.model_copy(deep=True)
    live_spec.data_mode = 'live'
    live_task = await engine.create(live_spec, 'owner')
    entered = asyncio.Event()
    release = asyncio.Event()
    async def slow_snapshot(task, now):
        entered.set()
        await release.wait()
        from app.adapters.replay import snapshot
        return snapshot(task, now)
    engine.provider = type('Provider', (), {'snapshot':staticmethod(slow_snapshot)})()
    waiting = asyncio.create_task(engine.tick(live_task['id'], 'owner', True))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        result = await asyncio.wait_for(engine.tick(replay_task['id'], 'owner', True), 1)
        assert result['state']['check_count'] == 1
    finally:
        release.set()
        await waiting


@pytest.mark.parametrize('last,previous,percent', [(19.4,20,-3), (20.6,20,3)])
async def test_live_quote_keeps_exact_percentage_boundary(settings, clock, last, previous, percent):
    from app.adapters.fuyao_adapter import Fuyao
    from app.core.state_machine import compare
    from app.models.dsl import SHANGHAI
    now = clock()
    today = now.astimezone(SHANGHAI).strftime('%Y%m%d')
    provider = Fuyao(settings)
    provider.calendar_cache = (today, {today})
    provider.request = AsyncMock(return_value=({'code':0, 'request_id':'test-decimal', 'data':{
        'timestamp':now.timestamp()*1000, 'item':[{'thscode':'600519.SH',
        'last_price':last, 'prev_price':previous, 'price_change_ratio_pct':percent}]}}, None))
    quote = await provider.quote('600519.SH', now)
    assert quote['status'] == 'ok'
    assert quote['change'] == percent/100
    assert not compare(quote['change'], '<' if percent < 0 else '>', percent/100)
    assert compare(quote['change'], '<=' if percent < 0 else '>=', percent/100)
