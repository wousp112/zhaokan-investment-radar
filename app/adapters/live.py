import asyncio
from app.adapters.fuyao_adapter import Fuyao
from app.adapters.ifind_adapter import Ifind
from app.models.dsl import iso


class LiveProvider:
    def __init__(self, settings):
        self.fuyao, self.ifind = Fuyao(settings), Ifind(settings)

    async def snapshot(self, task, now):
        kinds = {c['type'] for c in task['spec']['conditions']}
        quote = {'source':'未请求行情','status':'ok','mode':'live','observed_at':iso(now),'market_open':None}
        announcements = {'source':'未请求公告','status':'ok','mode':'live','observed_at':iso(now),'events':[],'complete':True}
        jobs, names = [], []
        if kinds & {'PRICE','PRICE_CHANGE_RATIO','HEAT'}:
            jobs.append(self.fuyao.quote(task['spec']['target']['symbol'],now)); names.append('quote')
        if 'ANNOUNCEMENT_EVENT' in kinds:
            jobs.append(self.ifind.notices(task,now)); names.append('announcements')
        output = {'quote':quote,'announcements':announcements}
        for name, data in zip(names,await asyncio.gather(*jobs,return_exceptions=True)):
            if isinstance(data,asyncio.CancelledError):
                raise data
            if isinstance(data,BaseException):
                output[name] = dict(output[name],status='unavailable',reason='该数据源返回意外错误，其他条件继续检查。')
            else:
                output[name] = data
        return output
