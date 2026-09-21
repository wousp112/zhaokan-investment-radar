import asyncio
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.adapters.fuyao_adapter import Fuyao
from app.models.dsl import utcnow


async def main():
    quote=await Fuyao(Settings()).quote('600519.SH',utcnow())
    output={'checked_at':utcnow().isoformat(),'quote':quote}
    (ROOT/'artifacts/latest-quote-probe.json').write_text(json.dumps(output,ensure_ascii=False,indent=2))
    print(json.dumps(output,ensure_ascii=False))


asyncio.run(main())
