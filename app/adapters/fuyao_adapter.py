from datetime import datetime, timezone
from decimal import Decimal
import asyncio
import math
import time

import httpx

from app.models.dsl import SHANGHAI, iso


class Fuyao:
    def __init__(self, settings):
        self.settings = settings
        self.calendar_cache = None
        self.quote_cache = {}
        self.lock = asyncio.Lock()
        self.last_request_at = 0.0
        self.blocked_until = 0.0

    async def request(self, path, params=None):
        key = self.settings.read_fuyao_key()
        if not key:
            return None, {'status':'unconfigured','reason':'尚未配置扶摇行情凭据。','attempts':0}
        if time.monotonic() < self.blocked_until:
            return None, {'status':'rate_limited','reason':'行情服务仍处于限流等待期，暂不重复请求。','attempts':0}
        async with httpx.AsyncClient(timeout=self.settings.request_timeout) as client:
            for attempt in range(1,4):
                try:
                    await asyncio.sleep(max(0,1.1-(time.monotonic()-self.last_request_at)))
                    self.last_request_at = time.monotonic()
                    response = await client.get('https://fuyao.aicubes.cn'+path, params=params, headers={'X-api-key':key})
                    if response.status_code == 429:
                        try:
                            retry_after = max(5,min(120,float(response.headers.get('Retry-After','5'))))
                        except ValueError:
                            retry_after = 5
                        self.blocked_until = time.monotonic()+retry_after
                        return None, {'status':'rate_limited','reason':'行情服务返回 HTTP 429，等待后续检查，不连续重试。','attempts':attempt,'retry_after_seconds':retry_after}
                    response.raise_for_status()
                    body = response.json()
                    if not isinstance(body,dict):
                        raise ValueError('invalid_envelope')
                    if body.get('code') != 0:
                        return None, {'status':'provider_error','reason':f'行情服务业务错误，代码 {body.get("code")}。','attempts':attempt}
                    return body, None
                except (httpx.TimeoutException, httpx.NetworkError):
                    error = {'status':'timeout','reason':'行情服务连接失败或超时，下一周期重试。','attempts':attempt}
                except httpx.HTTPStatusError as error_response:
                    status = error_response.response.status_code
                    error = {'status':'http_error','reason':f'行情服务返回 HTTP {status}。','attempts':attempt}
                    if status < 500:
                        return None, error
                except (ValueError, TypeError):
                    return None, {'status':'invalid','reason':'行情响应格式不符合接口规范。','attempts':attempt}
                except httpx.RequestError:
                    return None, {'status':'unavailable','reason':'行情请求无法完成，下一周期重试。','attempts':attempt}
                if attempt < 3:
                    await asyncio.sleep(0.4 * 2 ** (attempt - 1))
            return None, error

    async def quote(self, symbol, now):
        async with self.lock:
            cached = self.quote_cache.get(symbol)
            if cached and time.monotonic()-cached[0] < 10:
                return dict(cached[1])
            local = now.astimezone(SHANGHAI)
            today = local.strftime('%Y%m%d')
            base = {'source':'扶摇 / 同花顺金融数据 API','mode':'live','observed_at':None,
                    'market_open':None,'calendar_source':'扶摇交易日历','request_id':None,'heat':None}
            if not self.calendar_cache or self.calendar_cache[0] != today:
                calendar, error = await self.request('/api/a-share/calendar/trading-days')
                if error:
                    return {**base, **error, 'reason':'交易日历不可用，价格条件暂时无法判断。'}
                try:
                    stamp = datetime.fromtimestamp(calendar['data']['timestamp']/1000, timezone.utc)
                    if stamp.astimezone(SHANGHAI).date() != local.date():
                        return dict(base,status='stale',reason='交易日历尚未更新到今天，价格条件暂时无法判断。')
                    dates = {str(item['date']) for item in calendar['data']['item']}
                    self.calendar_cache = (today, dates)
                except (KeyError, TypeError, ValueError, OverflowError):
                    return dict(base,status='invalid',reason='交易日历格式异常。')
            minutes = local.hour*60 + local.minute
            opened = today in self.calendar_cache[1] and (570 <= minutes < 690 or 780 <= minutes < 900)
            base['market_open'] = opened
            body, error = await self.request('/api/a-share/prices/snapshot', {'thscodes':symbol})
            if error:
                return dict(base, **error)
            try:
                item = next(x for x in body['data']['item'] if x['thscode'] == symbol)
                observed = datetime.fromtimestamp(body['data']['timestamp']/1000, timezone.utc)
                previous, last = float(item['prev_price']), float(item['last_price'])
                reported = float(item['price_change_ratio_pct']) / 100
                if not all(math.isfinite(v) for v in (previous,last,reported)) or previous <= 0 or last <= 0:
                    raise ValueError('invalid_price')
                # Preserve decimal-price boundaries before serializing the ratio.
                # Binary subtraction would make 19.40/20.00 appear below -3%.
                previous_decimal = Decimal(str(item['prev_price']))
                last_decimal = Decimal(str(item['last_price']))
                change = float((last_decimal - previous_decimal) / previous_decimal)
                quote = dict(base,status='ok',last=last,previous_close=previous,change=change,
                             reported_change=reported,observed_at=iso(observed),request_id=body.get('request_id'),
                             source_url='https://fuyao.aicubes.cn/docs/api-reference/prices/')
                if (now-observed).total_seconds() > 180 or (observed-now).total_seconds() > 30:
                    quote.update(status='stale',reason='行情时间距当前超过3分钟或位于未来，停止使用该价格判断。')
                elif abs(change-reported) > 0.0001:
                    quote.update(status='conflict',reason='现价与昨收计算的涨跌幅和来源指标不一致。')
                self.quote_cache[symbol] = (time.monotonic(),quote)
                return quote
            except (KeyError, ValueError, TypeError, StopIteration, OverflowError):
                return dict(base,status='invalid',reason='行情缺少代码、价格、昨收或有效时间。')
