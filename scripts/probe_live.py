"""Read-only integration smoke test. Records metadata without credentials."""
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.models.dsl import ParseRequest, utcnow
from app.core.nlp_compiler import Compiler
from app.adapters.fuyao_adapter import Fuyao


async def main():
    settings = Settings()
    result = await Compiler(settings).compile(ParseRequest(prompt='未来两周帮我盯住贵州茅台：日内跌幅达到3%，或者发布新的业绩预告，就提醒我。'))
    print('COMPILER',json.dumps(result,ensure_ascii=False))
    quote = await Fuyao(settings).quote('600519.SH',utcnow())
    print('QUOTE',json.dumps(quote,ensure_ascii=False))
    artifact = {'checked_at':utcnow().isoformat(),'compiler':result,'quote':quote,
                'scope':'单个黄金用例和单次报价探测，不代表总体准确率或长期可用性。'}
    Path('artifacts').mkdir(exist_ok=True)
    Path('artifacts/live-probe.json').write_text(json.dumps(artifact,ensure_ascii=False,indent=2))


asyncio.run(main())
