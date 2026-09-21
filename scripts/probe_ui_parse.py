import asyncio
from datetime import datetime, timezone
from pathlib import Path
import json
from playwright.async_api import async_playwright, expect


async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='chrome',headless=True)
        page=await browser.new_page(viewport={'width':1440,'height':1000})
        await page.goto('http://127.0.0.1:8000',wait_until='networkidle')
        await expect(page.locator('#target option')).to_have_count(12)
        await page.locator('[data-example="golden"]').click()
        async with page.expect_response(lambda r:'/api/tasks/parse' in r.url,timeout=60000) as future:
            await page.locator('#parse-button').click()
        response=await future.value
        result={'checked_at':datetime.now(timezone.utc).isoformat(),'status':response.status,'body':await response.json()}
        await page.wait_for_timeout(300)
        result['dialog_visible']=await page.locator('#rule-dialog').is_visible()
        result['toast']=await page.locator('#toast').text_content()
        Path('artifacts/ui-parse-probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        await page.screenshot(path='artifacts/ui-parse-probe.png')
        print(json.dumps(result,ensure_ascii=False,indent=2))
        await browser.close()


asyncio.run(main())
