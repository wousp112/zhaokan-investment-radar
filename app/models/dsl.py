from datetime import datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

SHANGHAI = ZoneInfo('Asia/Shanghai')
DISCLAIMER = '仅监控客观事实，不构成投资建议。'
SYMBOLS = {
    '600519.SH': '贵州茅台', '300750.SZ': '宁德时代', '000001.SZ': '平安银行',
    '600036.SH': '招商银行', '002594.SZ': '比亚迪', '601318.SH': '中国平安',
    '300033.SZ': '同花顺', '000858.SZ': '五粮液', '600900.SH': '长江电力',
    '000333.SZ': '美的集团', '601138.SH': '工业富联', '688981.SH': '中芯国际',
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(SHANGHAI).isoformat(timespec='seconds')


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, validate_assignment=True)


class Target(StrictModel):
    symbol: str = Field(pattern=r'^(?:[036]\d{5})\.(?:SH|SZ)$')
    name: str = Field(min_length=1, max_length=40)
    market: Literal['A_SHARE'] = 'A_SHARE'

    @model_validator(mode='after')
    def known_target(self):
        if self.symbol not in SYMBOLS or SYMBOLS[self.symbol] != self.name:
            raise ValueError('请选择已核对代码与名称的 A 股标的。当前支持列表可在标的选择框查看。')
        return self


class Validity(StrictModel):
    start_time: datetime
    end_time: datetime
    timezone: Literal['Asia/Shanghai'] = 'Asia/Shanghai'

    @model_validator(mode='after')
    def valid_window(self):
        if self.start_time.tzinfo is None or self.end_time.tzinfo is None:
            raise ValueError('开始和结束时间必须包含时区。')
        if not timedelta(seconds=1) <= self.end_time - self.start_time <= timedelta(days=366):
            raise ValueError('监控时长须介于 1 秒和 366 天之间。')
        return self


class Condition(StrictModel):
    id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,39}$')
    type: Literal['PRICE_CHANGE_RATIO', 'PRICE', 'ANNOUNCEMENT_EVENT', 'CALENDAR', 'HEAT']
    operator: Literal['<=', '>=', '<', '>'] = '<='
    threshold: float | None = None
    event_category: Literal['PERFORMANCE_FORECAST', 'PERFORMANCE_REPORT', 'ANY_ANNOUNCEMENT'] | None = None
    at: datetime | None = None
    display_text: str = Field(default='', max_length=150)
    source: str = Field(default='', max_length=40)

    @model_validator(mode='after')
    def compatible_fields(self):
        if self.type in ('PRICE', 'PRICE_CHANGE_RATIO', 'HEAT'):
            if self.threshold is None:
                raise ValueError('价格或热度条件必须有明确阈值。')
            if self.type == 'PRICE_CHANGE_RATIO' and not -1 <= self.threshold <= 10:
                raise ValueError('涨跌幅使用比例值，例如跌 3% 写为 -0.03。')
            if self.type in ('PRICE', 'HEAT') and not 0 < self.threshold < 1000000:
                raise ValueError('价格和量比必须为正数。')
        if self.type == 'ANNOUNCEMENT_EVENT' and self.event_category is None:
            raise ValueError('公告条件必须指定公告类别。')
        if self.type == 'CALENDAR' and (self.at is None or self.at.tzinfo is None):
            raise ValueError('日历提醒必须指定含时区的时间。')
        return self


class Governance(StrictModel):
    frequency_seconds: int = Field(default=60, ge=10, le=3600)
    trading_hours_only: bool = True
    cooldown_minutes: int = Field(default=30, ge=0, le=1440)
    deduplication_keys: list[Literal['announcement_id', 'trading_date']] = Field(default_factory=lambda: ['announcement_id', 'trading_date'])
    alert_channels: list[Literal['WEB_INBOX']] = Field(default_factory=lambda: ['WEB_INBOX'])

    @model_validator(mode='after')
    def supported_policy(self):
        if set(self.deduplication_keys) != {'announcement_id','trading_date'} or len(self.deduplication_keys) != 2:
            raise ValueError('当前版本固定按公告事件和交易日去重，不能关闭该保护。')
        if self.alert_channels != ['WEB_INBOX']:
            raise ValueError('当前版本只支持站内提醒。')
        return self


class TaskSpec(StrictModel):
    schema_version: Literal['1.0'] = '1.0'
    version: int = Field(default=1, ge=1)
    user_intent_raw: str = Field(min_length=1, max_length=2000)
    target: Target
    validity: Validity
    condition_logic: Literal['OR', 'AND'] = 'OR'
    conditions: list[Condition] = Field(min_length=1, max_length=6)
    governance: Governance = Field(default_factory=Governance)
    data_mode: Literal['replay', 'live'] = 'replay'

    @model_validator(mode='after')
    def unique_ids(self):
        if len({c.id for c in self.conditions}) != len(self.conditions):
            raise ValueError('条件 ID 不能重复。')
        return self


class ParseRequest(StrictModel):
    prompt: str = Field(min_length=2, max_length=2000)
    target: Target | None = None
    data_mode: Literal['replay', 'live'] = 'replay'
    use_ai: bool = True


class CreateRequest(StrictModel):
    task_spec: TaskSpec
    activate: bool = True
    compilation_id: str | None = Field(default=None, max_length=60)


class UpdateRequest(StrictModel):
    task_spec: TaskSpec
    expected_version: int = Field(ge=1)


class InjectRequest(StrictModel):
    task_id: str = Field(min_length=1, max_length=80)
    scenario: Literal['normal', 'drop', 'deeper', 'announcement', 'same_announcement', 'timeout', 'http500', 'stale', 'conflict', 'event_failure', 'recover', 'closed', 'open', 'advance', 'heat']
    advance_seconds: int = Field(default=1860, ge=0, le=31622400)


class TickRequest(StrictModel):
    task_id: str = Field(min_length=1, max_length=80)


class RollbackRequest(StrictModel):
    version: int = Field(ge=1)
    expected_version: int = Field(ge=1)
