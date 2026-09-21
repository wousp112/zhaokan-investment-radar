from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
import asyncio
import fcntl
import json
import re
import time
import uuid

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.adapters.live import LiveProvider
from app.config import ROOT, Settings
from app.core.audit_logger import Store
from app.core.nlp_compiler import Compiler, Clarification
from app.core.scheduler import Engine
from app.core.state_machine import STATES
from app.product import install_product_routes
from app.models.dsl import CreateRequest, InjectRequest, ParseRequest, RollbackRequest, SYMBOLS, TaskSpec, TickRequest, UpdateRequest, iso, utcnow


def public_task(task):
    return {k:v for k,v in task.items() if k not in ('owner','simulation')}


def create_app(settings=None):
    settings = settings or Settings()
    store = Store(settings.data_dir)
    engine = Engine(store,settings,LiveProvider(settings))
    compiler = Compiler(settings)
    limits = defaultdict(deque)
    ai_lock = asyncio.Lock()
    ai_slots = asyncio.Semaphore(2)

    @asynccontextmanager
    async def lifespan(application):
        lock_file = (settings.data_dir/'process.lock').open('a')
        try:
            fcntl.flock(lock_file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            lock_file.close()
            raise RuntimeError('同一数据目录只能启动一个服务进程。请使用单 worker。')
        try:
            await engine.start()
            yield
        finally:
            await engine.stop()
            fcntl.flock(lock_file,fcntl.LOCK_UN)
            lock_file.close()

    app = FastAPI(title='照看 · 投资监控与风险雷达',version='1.1.0',lifespan=lifespan)
    app.state.store, app.state.engine, app.state.settings = store, engine, settings

    def error(message,status=400):
        return JSONResponse({'error':message},status_code=status)

    @app.middleware('http')
    async def boundaries(request,call_next):
        owner = request.cookies.get('radar_session','')
        new_session = not re.fullmatch(r'[a-f0-9]{32}',owner)
        if new_session:
            owner = uuid.uuid4().hex
        request.state.owner = owner
        if request.method in ('POST','PUT','DELETE','PATCH'):
            origin = request.headers.get('origin')
            if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and urlparse(origin).netloc != request.headers.get('host')):
                return error('不接受跨站点修改请求。',403)
            if len(await request.body()) > 20000:
                return error('请求内容过长。',413)
            address = request.client.host if request.client else 'unknown'
            queue = limits[address]
            now = time.monotonic()
            while queue and queue[0] < now-60:
                queue.popleft()
            if len(queue) >= 120:
                return error('请求过于频繁，请稍后再试。',429)
            queue.append(now)
        response = await call_next(request)
        if new_session:
            response.set_cookie('radar_session',owner,httponly=True,samesite='strict',secure=settings.session_secure,max_age=30*86400)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; media-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(KeyError)
    async def missing(request,exc):
        return error(str(exc).strip("'"),404)

    @app.exception_handler(ValueError)
    async def invalid(request,exc):
        return error(str(exc),422)

    @app.exception_handler(RuntimeError)
    async def conflict(request,exc):
        return error(str(exc),409)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request,exc):
        labels={'prompt':'关注条件','threshold':'提醒数值','end_time':'结束时间','start_time':'开始时间',
                'frequency_seconds':'检查间隔','cooldown_minutes':'提醒间隔','conditions':'提醒条件',
                'target':'关注公司','symbol':'股票代码','feedback':'反馈选项','expected_version':'修改版本'}
        fields=[labels.get(str(e['loc'][-1]),'填写内容') for e in exc.errors()[:3]]
        return error('请检查'+ '、'.join(dict.fromkeys(fields))+'。数值和时间需要在页面标注的范围内；未知选项不能保存。',422)

    @app.get('/')
    async def homepage():
        return FileResponse(ROOT/'app/web/index.html')

    @app.get('/api/health')
    async def health():
        age=(utcnow()-datetime.fromisoformat(engine.heartbeat)).total_seconds() if engine.heartbeat else None
        stale=settings.scheduler_enabled and (age is None or age>30)
        return {'status':'attention' if engine.last_error is not None or stale else 'ok','scheduler_enabled':settings.scheduler_enabled,
                'heartbeat':engine.heartbeat,'started_at':engine.started_at,'last_error':engine.last_error,
                'heartbeat_age_seconds':round(age,1) if age is not None else None,'heartbeat_stale':stale,
                'build':app.state.build,
                'persistence':'SQLite WAL / atomic task + audit + inbox','notification_channel':'WEB_INBOX'}

    @app.get('/api/meta')
    async def meta():
        return {'symbols':[{'symbol':s,'name':n,'market':'A_SHARE'} for s,n in SYMBOLS.items()],
                'states':STATES,'ai_available':bool(settings.deepseek_key and settings.ai_enabled),
                'ai_model':settings.deepseek_model,'live_available':settings.allow_live,
                'build':app.state.build,'limits':{'active_tasks':settings.max_tasks,'saved_tasks':settings.max_saved_tasks},
                'data_disclosure':'演示与真实数据隔离。公告为有限覆盖的语义检索。量比目前仅演示模式提供。'}

    @app.get('/api/schema')
    async def schema():
        return TaskSpec.model_json_schema()

    @app.post('/api/tasks/parse')
    async def parse(body:ParseRequest,request:Request):
        requested=body.use_ai; reason=None; acquired=False
        store.record_product_event(request.state.owner,'parse_requested',body.data_mode)
        if body.use_ai and settings.ai_enabled and settings.deepseek_key:
            try:
                await asyncio.wait_for(ai_slots.acquire(),timeout=1)
                acquired=True
            except asyncio.TimeoutError:
                body.use_ai=False; reason='AI_BUSY'
        async with ai_lock:
            day = utcnow().date().isoformat()
            count = int(store.metadata('ai_calls:'+day) or '0')
            if body.use_ai and settings.ai_enabled and settings.deepseek_key:
                if count >= 100:
                    body.use_ai = False; reason='DAILY_LIMIT'
                else:
                    store.metadata('ai_calls:'+day,str(count+1))
        try:
            result = await compiler.compile(body)
            engine.validate_capabilities(TaskSpec.model_validate(result['task_spec']))
            result['compilation']['ai_requested']=requested
            if reason:
                result['compilation']['fallback_reason']=reason
            store.record_compilation(result['compilation']['compilation_id'],request.state.owner,{'prompt':body.prompt,**result})
            store.record_product_event(request.state.owner,'parse_ready',body.data_mode)
            return result
        except (ValueError,RuntimeError) as exc:
            store.record_product_event(request.state.owner,'parse_failed',body.data_mode)
            if isinstance(exc,Clarification):
                if exc.compilation:
                    exc.compilation['ai_requested']=requested
                    store.record_compilation(exc.compilation['compilation_id'], request.state.owner,
                        {'prompt':body.prompt, 'compilation':exc.compilation, 'clarification':str(exc)})
            raise
        finally:
            if acquired:
                ai_slots.release()

    @app.post('/api/tasks/create',status_code=201)
    async def create(body:CreateRequest,request:Request):
        task = await engine.create(body.task_spec,request.state.owner,body.activate,body.compilation_id,body.request_key)
        return public_task(task)

    @app.get('/api/tasks')
    async def tasks(request:Request):
        return {'tasks':[public_task(t) for t in store.tasks(request.state.owner)],'server_time':iso(utcnow())}

    @app.get('/api/alerts')
    async def alerts(request:Request,limit:int=Query(100,ge=1,le=100),before_id:int|None=Query(None,ge=1),unread_only:bool=False):
        rows=store.alerts(request.state.owner,limit+1,before_id,unread_only)
        more=len(rows)>limit; rows=rows[:limit]
        return {'alerts':rows,'has_more':more,'next_cursor':rows[-1]['id'] if more else None,
                **store.alert_counts(request.state.owner)}

    @app.get('/api/ai-records')
    async def ai_records(request:Request):
        return {'records':store.compilations(request.state.owner)}

    @app.get('/api/tasks/{task_id}')
    async def detail(task_id:str,request:Request):
        return public_task(engine.owned(task_id,request.state.owner))

    @app.put('/api/tasks/{task_id}')
    async def edit(task_id:str,body:UpdateRequest,request:Request):
        return public_task(await engine.edit(task_id,request.state.owner,body.task_spec,body.expected_version))

    @app.post('/api/tasks/{task_id}/pause')
    async def pause(task_id:str,request:Request):
        return public_task(await engine.change_state(task_id,request.state.owner,'pause'))

    @app.post('/api/tasks/{task_id}/resume')
    async def resume(task_id:str,request:Request):
        return public_task(await engine.change_state(task_id,request.state.owner,'resume'))

    @app.delete('/api/tasks/{task_id}')
    async def archive(task_id:str,request:Request):
        return public_task(await engine.change_state(task_id,request.state.owner,'archive'))

    @app.get('/api/tasks/{task_id}/audit-trail')
    async def history(task_id:str,request:Request,limit:int=Query(100,ge=1,le=100),before_id:int|None=Query(None,ge=1)):
        engine.owned(task_id,request.state.owner)
        rows=store.audits(task_id,limit+1,before_id)
        more=len(rows)>limit; rows=rows[:limit]
        return {'task_id':task_id,'history':rows,'total':store.audit_count(task_id),
                'has_more':more,'next_cursor':rows[-1]['audit_id'] if more else None}

    @app.get('/api/tasks/{task_id}/versions')
    async def versions(task_id:str,request:Request):
        engine.owned(task_id,request.state.owner)
        return {'versions':store.versions(task_id)}

    @app.post('/api/tasks/{task_id}/rollback')
    async def rollback(task_id:str,body:RollbackRequest,request:Request):
        engine.owned(task_id,request.state.owner)
        previous = next((v for v in store.versions(task_id) if v['version'] == body.version),None)
        if not previous:
            raise KeyError('找不到所选历史版本。')
        task = await engine.edit(task_id,request.state.owner,TaskSpec.model_validate(previous['spec']),body.expected_version,'从历史版本 v'+str(body.version)+' 恢复规则')
        return public_task(task)

    @app.get('/api/tasks/{task_id}/export')
    async def export(task_id:str,request:Request):
        task = public_task(engine.owned(task_id,request.state.owner))
        bundle = {'task':task,'versions':store.versions(task_id),'recent_audits':store.audits(task_id,1000),
                  'exported_at':iso(utcnow()),'scope':'最近1000条审计记录；历史记录保存在数据库。'}
        return Response(json.dumps(bundle,ensure_ascii=False,indent=2),media_type='application/json',
                        headers={'Content-Disposition':f'attachment; filename="{task_id}-evidence.json"'})

    @app.post('/api/simulate/tick')
    async def tick(body:TickRequest,request:Request):
        return public_task(await engine.tick(body.task_id,request.state.owner,force=True))

    @app.post('/api/simulate/inject')
    async def inject(body:InjectRequest,request:Request):
        return public_task(await engine.inject(body.task_id,request.state.owner,body.scenario,body.advance_seconds))

    install_product_routes(app,store,engine,settings)
    static = ROOT/'app/web/static'
    static.mkdir(parents=True,exist_ok=True)
    app.mount('/static',StaticFiles(directory=static),name='static')
    return app


app = create_app()
