from datetime import datetime, timedelta
from pathlib import Path
import asyncio
import hashlib
import json
import shutil
import time

from app.models.dsl import SHANGHAI, iso


def decode(value):
    for _ in range(4):
        if not isinstance(value,str):
            return value
        try:
            value = json.loads(value)
        except ValueError:
            return value
    return value


def parse_notice_response(body, target, now):
    if not body.get('ok'):
        raise ValueError('Provider rejected request')
    result = body['data']['result']
    if result.get('isError'):
        raise ValueError('MCP tool failed')
    rows = []
    recognized = False
    for content in result['content']:
        if content.get('type') != 'text':
            continue
        payload = decode(content['text'])
        if isinstance(payload,dict) and payload.get('msg') == 'success':
            value = decode(payload.get('data'))
            if isinstance(value,list):
                rows.extend(value)
                recognized = True
            elif isinstance(value,str) and '搜索结果为空' in value:
                recognized = True
    if not recognized:
        raise ValueError('Unsupported notice result shape')
    events = []
    for row in rows:
        title = row.get('公告标题','')
        date = row.get('日期','')
        if not title or not date or target['name'] not in title:
            continue
        try:
            published = datetime.fromisoformat(date)
            if published.tzinfo is None:
                published = published.replace(tzinfo=SHANGHAI)
        except ValueError:
            continue
        ident = hashlib.sha256((target['symbol']+'|'+title+'|'+date).encode()).hexdigest()[:24]
        category = 'PERFORMANCE_FORECAST' if '业绩预告' in title else ('PERFORMANCE_REPORT' if '业绩快报' in title else 'ANY_ANNOUNCEMENT')
        events.append({'id':ident,'symbol':target['symbol'],'title':title,'category':category,
                       'published_at':iso(published),'date_precision':'day' if len(date) == 10 else 'second',
                       'discovered_at':iso(now),'url':None,'source':'iFinD 公告检索','mode':'live',
                       'identity_method':'公司代码、标题和发布日期的 SHA256 摘要'})
    return events


class Ifind:
    def __init__(self, settings):
        self.settings = settings
        self.lock = asyncio.Lock()
        self.last_request = 0
        self.cache = {}

    async def notices(self, task, now):
        target = task['spec']['target']
        base = {'source':'iFinD 公告检索','mode':'live','observed_at':iso(now),'events':[],
                'complete':False,'coverage':'语义检索最多20条；无法保证覆盖全部公告。日期精度以来源为准。'}
        if not Path(self.settings.ifind_script).is_file() or not shutil.which('node'):
            return dict(base,status='unconfigured',reason='此服务器尚未配置 iFinD 公告模块。')
        cursor = datetime.fromisoformat(task['state']['event_cursor'])
        start = max(cursor-timedelta(days=1),now-timedelta(days=30)).astimezone(SHANGHAI).date().isoformat()
        categories = {c.get('event_category') for c in task['spec']['conditions'] if c['type'] == 'ANNOUNCEMENT_EVENT'}
        query = target['name'] + (' 业绩预告' if categories == {'PERFORMANCE_FORECAST'} else (' 业绩快报' if categories == {'PERFORMANCE_REPORT'} else ' 公告'))
        params = {'query':query,'time_start':start,'time_end':now.astimezone(SHANGHAI).date().isoformat(),'size':20}
        cache_key = json.dumps(params,sort_keys=True)
        async with self.lock:
            cached = self.cache.get(cache_key)
            if cached and time.monotonic()-cached[0] < 60:
                return cached[1]
            await asyncio.sleep(max(0,0.6-(time.monotonic()-self.last_request)))
            self.last_request = time.monotonic()
            process = None
            try:
                process = await asyncio.create_subprocess_exec('node',str(Path(__file__).with_name('ifind_bridge.cjs')),
                    self.settings.ifind_script,json.dumps(params,ensure_ascii=False),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
                stdout, _ = await asyncio.wait_for(process.communicate(),timeout=20)
                if process.returncode or len(stdout) > 2000000:
                    raise ValueError('Provider process failed')
                events = parse_notice_response(json.loads(stdout),target,now)
                result = dict(base,status='ok',events=events,query_window={'start':start,'end':params['time_end']},
                              gap_limited=(now-cursor).total_seconds()>30*86400)
                self.cache[cache_key] = (time.monotonic(),result)
                return result
            except asyncio.CancelledError:
                if process and process.returncode is None:
                    process.kill()
                    await process.wait()
                raise
            except (asyncio.TimeoutError,OSError,ValueError,KeyError,TypeError):
                if process and process.returncode is None:
                    process.kill()
                    await process.wait()
                return dict(base,status='unavailable',reason='公告服务超时或返回格式无法核验；价格条件继续运行。')
