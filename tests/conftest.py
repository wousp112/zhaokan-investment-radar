from datetime import datetime, timedelta, timezone
import pytest

from app.config import Settings
from app.core.audit_logger import Store
from app.core.scheduler import Engine
from app.models.dsl import Condition, Target, TaskSpec, Validity


class Clock:
    def __init__(self):
        self.value = datetime(2026,9,21,2,0,tzinfo=timezone.utc)
    def __call__(self):
        return self.value
    def advance(self,seconds):
        self.value += timedelta(seconds=seconds)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path,deepseek_key='',ai_enabled=False,scheduler_enabled=False)


@pytest.fixture
def engine(settings,clock):
    return Engine(Store(settings.data_dir),settings,clock=clock)


@pytest.fixture
def spec(clock):
    return TaskSpec(user_intent_raw='未来两周，贵州茅台跌3%或出现业绩预告提醒。',
        target=Target(symbol='600519.SH',name='贵州茅台'),
        validity=Validity(start_time=clock(),end_time=clock()+timedelta(days=14)),
        conditions=[Condition(id='price',type='PRICE_CHANGE_RATIO',threshold=-0.03),
                    Condition(id='event',type='ANNOUNCEMENT_EVENT',event_category='PERFORMANCE_FORECAST')])
