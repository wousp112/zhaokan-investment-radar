"""Single-process scheduler with persistent checkpoints and transactional inbox."""
from datetime import datetime, timedelta
from collections import defaultdict
import asyncio
import contextlib
import copy
import hashlib
import logging
import uuid

from app.adapters import replay
from app.core.audit_logger import dumps
from app.core.nlp_compiler import condition_label
from app.core.state_machine import evaluate
from app.models.dsl import TaskSpec, DISCLAIMER, SHANGHAI, iso, utcnow

LOG = logging.getLogger(__name__)


class Engine:
    def __init__(self, store, settings, live_provider=None, clock=utcnow):
        self.store, self.settings, self.provider, self.clock = store, settings, live_provider, clock
        self.lock = asyncio.Lock()
        self.task_locks = defaultdict(asyncio.Lock)
        self.runner = None
        self.heartbeat = None
        self.started_at = iso(clock())
        self.last_error = None

    def now_for(self, task):
        offset = task['simulation'].get('clock_offset',0) if task['spec']['data_mode'] == 'replay' else 0
        return self.clock()+timedelta(seconds=offset)

    def owned(self, task_id, owner):
        task = self.store.task(task_id, owner)
        if task is None:
            raise KeyError('任务不存在或不属于当前浏览器。')
        return task

    def audit(self, task, action, **extra):
        return {'timestamp':iso(self.now_for(task)), 'task_id':task['id'], 'rule_version':task['spec']['version'],
                'data_mode':task['spec']['data_mode'], 'kind':'lifecycle','action_taken':action,
                'current_status':task['state']['status'],'conditions_evaluated':[],**extra}

    async def create(self, spec, owner, activate=True, compilation_id=None):
        async with self.lock:
            existing = self.store.tasks(owner)
            if len(existing) >= self.settings.max_tasks or len(self.store.tasks()) >= self.settings.max_total_tasks:
                raise ValueError('体验实例的任务容量已满。每个浏览器最多创建12个任务。')
            if spec.data_mode == 'live' and not self.settings.allow_live:
                raise ValueError('此实例只开放演示模式。')
            if spec.validity.end_time <= self.clock():
                raise ValueError('规则已经到期，请重新选择结束时间。')
            spec.version = 1
            for c in spec.conditions:
                c.display_text = condition_label(c)
            now = self.clock()
            task = {'id':'task_'+uuid.uuid4().hex[:16], 'owner':owner,'spec':spec.model_dump(mode='json'),
                    'state':{'status':'ACTIVE' if activate else 'PENDING','paused':False,'created_at':iso(now),
                             'last_check_time':None,'last_trigger_time':None,'next_check_time':iso(now),
                             'cooldown_until':None,'check_count':0,'trigger_count':0,'suppressed_count':0,
                             'degradation_reason':None,'health_episode':None,'pending_events':{},
                             'event_cursor':iso(now),'last_decision':None,'event_baseline':None},
                    'simulation':replay.initial_frame(now),'compilation_id':compilation_id}
            self.store.save(task,self.audit(task,'用户确认并激活规则。' if activate else '保存待确认规则。'),
                            version={'version':1,'at':iso(now),'author':'当前浏览器用户','reason':'首次创建','spec':task['spec']})
            return task

    async def change_state(self, task_id, owner, action):
        async with self.task_locks[task_id]:
            task = self.owned(task_id,owner)
            state = task['state']
            if state['status'] in ('EXPIRED','ARCHIVED') and action != 'archive':
                raise ValueError('已到期或归档的任务不能恢复；可复制规则创建新任务。')
            if action == 'pause':
                state.update(status='SUSPENDED',paused=True)
                message = '用户暂停全部条件检查。'
            elif action == 'resume':
                state.update(status='ACTIVE',paused=False,next_check_time=iso(self.now_for(task)))
                message = '用户恢复监控；下轮从上次成功公告检查点补查。'
            else:
                state.update(status='ARCHIVED',paused=True)
                message = '用户归档任务，停止后续调度。'
            self.store.save(task,self.audit(task,message))
            return task

    async def edit(self, task_id, owner, spec, expected_version, reason='用户修改规则'):
        async with self.task_locks[task_id]:
            task = self.owned(task_id,owner)
            if task['spec']['version'] != expected_version:
                raise RuntimeError('规则已被修改，请刷新后再保存。')
            if task['state']['status'] in ('ARCHIVED','EXPIRED'):
                raise ValueError('归档或到期任务不可修改，请创建新任务。')
            if spec.target != TaskSpec.model_validate(task['spec']).target or spec.data_mode != task['spec']['data_mode']:
                raise ValueError('修改规则时不能更换公司或数据模式，请新建任务。')
            if spec.validity.start_time != TaskSpec.model_validate(task['spec']).validity.start_time:
                raise ValueError('已有任务的开始时间不能改变。')
            spec.version = expected_version+1
            for c in spec.conditions:
                c.display_text = condition_label(c)
            previous = task['spec']
            task['spec'] = spec.model_dump(mode='json')
            task['state']['next_check_time'] = iso(self.now_for(task))
            changed = [key for key in task['spec'] if task['spec'][key] != previous.get(key)]
            version = {'version':spec.version,'at':iso(self.now_for(task)),'author':'当前浏览器用户',
                       'reason':reason,'changed_fields':changed,'spec':task['spec']}
            self.store.save(task,self.audit(task,reason,changed_fields=changed),version=version)
            return task

    async def inject(self, task_id, owner, scenario, seconds=1860):
        async with self.task_locks[task_id]:
            task = self.owned(task_id,owner)
            if task['spec']['data_mode'] != 'replay':
                raise ValueError('情景注入仅限演示任务，真实行情任务不接受模拟数据。')
            replay.inject(task,scenario,self.now_for(task),seconds)
            self.store.save(task,self.audit(task,'注入演示情景：'+scenario))
        return await self.tick(task_id,owner,force=True)

    async def tick(self, task_id, owner=None, force=False):
        async with self.task_locks[task_id]:
            task = self.owned(task_id,owner) if owner else self.store.task(task_id)
            if not task:
                return None
            spec = TaskSpec.model_validate(task['spec'])
            state, now = task['state'], self.now_for(task)
            if state['status'] in ('ARCHIVED','EXPIRED'):
                return task
            if now >= spec.validity.end_time:
                state.update(status='EXPIRED',next_check_time=None)
                self.store.save(task,self.audit(task,'监控期限已到，停止检查。'))
                return task
            if state['paused'] or state['status'] == 'PENDING' or now < spec.validity.start_time:
                return task
            if not force and state['next_check_time'] and now < datetime.fromisoformat(state['next_check_time']):
                return task
            if spec.data_mode == 'replay':
                snapshot = replay.snapshot(task,now)
            else:
                snapshot = await self.provider.snapshot(task,now)
            pending = state['pending_events']
            events = snapshot['announcements']
            seen = self.store.seen(task_id)
            baseline = state.get('event_baseline')
            establishing_baseline = spec.data_mode == 'live' and baseline is None and events['status'] == 'ok'
            if establishing_baseline:
                baseline = [e['id'] for e in events.get('events',[])]
                state['event_baseline'] = baseline
            for event in events.get('events',[]):
                try:
                    published = datetime.fromisoformat(event['published_at'])
                    admissible = spec.validity.start_time <= published <= now
                    if event.get('date_precision') == 'day':
                        admissible = (not establishing_baseline and event['id'] not in (baseline or [])
                                      and spec.validity.start_time.astimezone(SHANGHAI).date() <= published.astimezone(SHANGHAI).date() <= now.astimezone(SHANGHAI).date())
                        if admissible:
                            event = dict(event, freshness_note='首次检索发现；来源仅提供发布日期，无法确认日内发布时间。')
                    if (event['symbol'] == spec.target.symbol and admissible
                            and 'event:'+event['id'] not in seen):
                        pending[event['id']] = event
                except (KeyError,ValueError,TypeError):
                    continue
            if events['status'] == 'ok':
                state['event_cursor'] = iso(now)
            results, truth, keys = evaluate(spec,snapshot,now,seen,pending)
            cooling = bool(state['cooldown_until'] and now < datetime.fromisoformat(state['cooldown_until']))
            alerts, fingerprints, transitions = [], [], []
            if truth and keys and not cooling:
                fingerprint = 'alert:'+hashlib.sha256(dumps(keys).encode()).hexdigest()[:24]
                message = '；'.join(r['display_text'] for r in results if r['satisfied'])
                alerts.append({'task_id':task_id,'fingerprint':fingerprint,'timestamp':iso(now),'kind':'condition',
                               'title':spec.target.name+' · 条件已满足','message':message,'disclaimer':DISCLAIMER,
                               'mode':spec.data_mode,'rule_version':spec.version,'evidence':results})
                fingerprints = keys
                state['trigger_count'] += 1
                state['last_trigger_time'] = iso(now)
                state['cooldown_until'] = iso(now+timedelta(minutes=spec.governance.cooldown_minutes))
                cooling = spec.governance.cooldown_minutes > 0
                transitions.append('TRIGGERED')
                action = '提醒已写入站内消息，进入冷却。' if cooling else '提醒已写入站内消息。'
                for key in keys:
                    if key.startswith('event:'):
                        pending.pop(key[6:],None)
            elif truth and keys and cooling:
                state['suppressed_count'] += 1
                action = '条件满足但处于冷却期；新公告已保留，冷却结束后重新判断。'
            elif truth:
                state['suppressed_count'] += 1
                action = '条件满足，但同一交易日的该价格规则或相同事件已提醒，不重复发送。'
            elif truth is None:
                action = '部分条件缺少有效数据，本轮无法完整判断。'
            else:
                action = '已检查，组合条件未满足，本轮不提醒。'
            failures = [r['reason'] for r in results if r['satisfied'] is None and not r.get('suspended')]
            health = '；'.join(dict.fromkeys(failures)) or None
            if health and state['degradation_reason'] != health:
                episode = uuid.uuid4().hex[:12]
                state['health_episode'] = episode
                alerts.append({'task_id':task_id,'fingerprint':'health:'+episode,'timestamp':iso(now),'kind':'health',
                               'title':spec.target.name+' · 监控需要留意','message':health,'mode':spec.data_mode,'disclaimer':DISCLAIMER})
            elif not health and state['degradation_reason']:
                alerts.append({'task_id':task_id,'fingerprint':'recovered:'+str(state['health_episode']),
                               'timestamp':iso(now),'kind':'recovery','title':spec.target.name+' · 数据检查已恢复',
                               'message':'当前条件已有有效检查结果，继续按规则监控。','mode':spec.data_mode,'disclaimer':DISCLAIMER})
            suspended = all(r.get('suspended') for r in results)
            status = 'DEGRADED' if health else ('COOLING' if cooling else ('SUSPENDED' if suspended else 'ACTIVE'))
            state.update(status=status,last_check_time=iso(now),next_check_time=iso(now+timedelta(seconds=spec.governance.frequency_seconds)),
                         check_count=state['check_count']+1,degradation_reason=health,last_decision=action)
            state['last_snapshot'] = snapshot
            transitions.append(status)
            audit = self.audit(task,action,kind='evaluation',overall_triggered=truth,notification_sent=bool(fingerprints),
                               conditions_evaluated=results,condition_logic=spec.condition_logic,transitions=transitions,
                               pending_event_count=len(pending),cooldown_until=state['cooldown_until'])
            self.store.save(task,audit,alerts,fingerprints)
            return task

    async def start(self):
        async with self.lock:
            for task in self.store.tasks():
                if task['state']['status'] not in ('EXPIRED','ARCHIVED','PENDING'):
                    task['state']['next_check_time'] = iso(self.now_for(task))
                    self.store.save(task,self.audit(task,'服务启动后恢复持久化任务；公告从成功检查点补查，离线期间的价格路径无法还原。',
                        kind='recovery',previous_check=task['state']['last_check_time']))
        if self.settings.scheduler_enabled:
            self.runner = asyncio.create_task(self.run())

    async def run(self):
        while True:
            errors = []
            self.heartbeat = iso(self.clock())
            self.store.metadata('scheduler_heartbeat',self.heartbeat)
            slots = asyncio.Semaphore(4)
            async def check(task):
                async with slots:
                    try:
                        await self.tick(task['id'])
                    except Exception as error:
                        errors.append(type(error).__name__)
                        LOG.error('Scheduler check failed: %s', type(error).__name__)
                    self.heartbeat = iso(self.clock())
            await asyncio.gather(*(check(task) for task in self.store.tasks()))
            self.last_error = ','.join(sorted(set(errors))) or None
            await asyncio.sleep(1)

    async def stop(self):
        if self.runner:
            self.runner.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.runner
