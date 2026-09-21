"""Bounded first-cycle capacity probe using the real scheduler and synthetic I/O.

Uses an isolated temporary database. It does not call financial data services,
change the review instance, or establish a production throughput guarantee.
"""
import argparse
import asyncio
from datetime import timezone, datetime
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.core.audit_logger import Store
from app.core.nlp_compiler import Compiler
from app.core.scheduler import Engine
from app.models.dsl import ParseRequest, TaskSpec, iso, utcnow
from app.product import build_info, percentile


class SyntheticProvider:
    def __init__(self):
        self.active=0;self.peak=0;self.calls=0

    async def snapshot(self, task, now):
        self.active+=1;self.calls+=1;self.peak=max(self.peak,self.active)
        try:
            await asyncio.sleep(.25 if self.calls%10==0 else .01)
            return {'quote':{'source':'synthetic capacity probe','status':'ok','mode':'live',
                'observed_at':iso(now),'market_open':True,'last':96.2,'previous_close':100,'change':-.038},
                'announcements':{'source':'not requested','status':'ok','complete':True,'events':[]}}
        finally:
            self.active-=1


async def run(count):
    with tempfile.TemporaryDirectory(prefix='radar-capacity-') as directory:
        settings=Settings(data_dir=Path(directory),deepseek_key='',ai_enabled=False,
                          scheduler_enabled=True,allow_live=True)
        store=Store(settings.data_dir);provider=SyntheticProvider();engine=Engine(store,settings,provider)
        parsed=await Compiler(settings).compile(ParseRequest(prompt='贵州茅台下跌达到3%',use_ai=False,data_mode='live'))
        owners=set()
        for i in range(count):
            spec=TaskSpec.model_validate(parsed['task_spec']);spec.governance.frequency_seconds=60
            owner='synthetic-capacity-'+str(i//settings.max_tasks);owners.add(owner)
            await engine.create(spec,owner)
        started=time.monotonic()
        await engine.start()
        try:
            while time.monotonic()-started<30:
                if all(t['state']['check_count'] for t in store.tasks()):break
                await asyncio.sleep(.1)
        finally:
            await engine.stop()
        elapsed=time.monotonic()-started
        tasks=store.tasks();audits=[a for t in tasks for a in store.audits(t['id']) if a['kind']=='evaluation']
        alerts={'total':sum(store.alert_counts(owner)['total'] for owner in owners)}
        complete=sum(t['state']['check_count']>=1 for t in tasks)
        passed=complete==count and alerts['total']==count and provider.peak<=4 and engine.last_error is None
        return {'recorded_at':datetime.now(timezone.utc).isoformat(),'build':build_info(),
                'scope':'Isolated synthetic first-cycle probe; no real financial data or production SLA.',
                'synthetic_io_seconds':{'usual':.01,'every_tenth_request':.25},'task_count':count,
                'completed_tasks':complete,'elapsed_seconds':round(elapsed,3),'peak_concurrent_fetches':provider.peak,
                'condition_notifications':alerts['total'],'evaluation_records':len(audits),
                'schedule_delay_p95_seconds':percentile([a['schedule_delay_seconds'] for a in audits],.95),
                'check_duration_p95_ms':percentile([a['duration_ms'] for a in audits],.95),
                'pass_criteria':'All tasks finish their first check within 30s; one alert per task; at most four concurrent providers; no scheduler exception.',
                'passed':passed,'review_database_touched':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tasks',type=int,default=120)
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/professional-review/capacity.json')
    args=parser.parse_args()
    if not 1<=args.tasks<=300:parser.error('--tasks must be between 1 and 300')
    result=asyncio.run(run(args.tasks))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['passed'] else 1)
