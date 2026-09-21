"""Measure live-model extraction separately from deterministic fallback tests."""
import asyncio
import argparse
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.core.nlp_compiler import Compiler
from app.models.dsl import ParseRequest,TaskSpec
from tests.test_main_pipeline import CASES

parser=argparse.ArgumentParser()
parser.add_argument('--output',default='ai-evaluation.json')
args=parser.parse_args()
if Path(args.output).name != args.output or not args.output.endswith('.json'):
    raise ValueError('Output must be a JSON filename inside artifacts/')


async def main():
    compiler=Compiler(Settings())
    records=[]
    for i,(prompt,kind,threshold,operator,days,logic) in enumerate(CASES,1):
        record={'case_id':f'AI{i:02}','prompt':prompt,'expected':{'type':kind,'threshold':threshold,'operator':operator,'days':days,'logic':logic}}
        try:
            result=await compiler.compile(ParseRequest(prompt=prompt,use_ai=True))
            spec=TaskSpec.model_validate(result['task_spec']);first=spec.conditions[0]
            expected_count=2 if i in (16,17) else 1
            valid=(first.type==kind and first.threshold==threshold and first.operator==operator and
                   (spec.validity.end_time-spec.validity.start_time).days==days and spec.condition_logic==logic
                   and len(spec.conditions)==expected_count)
            if i in (16,17,18):
                valid=valid and spec.conditions[-1].event_category=='PERFORMANCE_FORECAST'
            if i==19:
                valid=valid and first.event_category=='PERFORMANCE_REPORT'
            record.update(result=result,semantic_match=valid,live_model=result['compilation']['engine']=='deepseek')
            record['passed']=valid and record['live_model']
        except Exception as error:
            metadata = getattr(error, 'compilation', None)
            record.update(passed=False,error_type=type(error).__name__,error_message=str(error),
                          compilation=metadata,semantic_match=False,
                          live_model=bool(metadata and metadata.get('ai_response_received')))
        records.append(record)
        print(record['case_id'],'PASS' if record['passed'] else 'FAIL',flush=True)
        summary={'run_at':datetime.now(timezone.utc).isoformat(),'total':len(CASES),'completed':len(records),
                 'passed':sum(bool(x['passed']) for x in records),'live_model_calls':sum(bool(x['live_model']) for x in records),
                 'semantic_matches_including_fallback':sum(bool(x['semantic_match']) for x in records),
                 'scope':'20条手工定义检查用例；非随机样本，不代表开放域准确率。仅模型实际返回且字段符合预期计通过。',
                 'compiler_source_sha256':hashlib.sha256((ROOT/'app/core/nlp_compiler.py').read_bytes()).hexdigest(),
                 'records':records}
        (ROOT/'artifacts').mkdir(exist_ok=True)
        (ROOT/'artifacts'/args.output).write_text(json.dumps(summary,ensure_ascii=False,indent=2))
        await asyncio.sleep(1)
    print('RESULT',summary['passed'],'/',summary['total'],flush=True)


asyncio.run(main())
