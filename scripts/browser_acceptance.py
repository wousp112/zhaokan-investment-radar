"""Exercise the actual browser UI. Does not install or rewrite app dependencies."""
import asyncio
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright, expect

arguments=argparse.ArgumentParser()
arguments.add_argument('--url',default='http://127.0.0.1:8000')
BASE=arguments.parse_args().url.rstrip('/')
OUT=Path(__file__).resolve().parents[1]/'artifacts'


async def main():
    OUT.mkdir(exist_ok=True)
    checks=[]; errors=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,channel='chrome')
        context=await browser.new_context(viewport={'width':1440,'height':1050},device_scale_factor=1)
        page=await context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        await page.goto(BASE,wait_until='networkidle')
        await expect(page.locator('#target option')).to_have_count(12)
        await page.screenshot(path=str(OUT/'desktop-empty.png'),full_page=True)
        await page.locator('[data-example="golden"]').click()
        await page.locator('#use-ai').uncheck()
        await page.locator('#parse-button').click()
        await expect(page.locator('#rule-dialog')).to_be_visible()
        await expect(page.locator('[data-field="threshold"]')).to_have_value('-3')
        await expect(page.locator('.review-condition')).to_have_count(2)
        checks.append('自然语言生成两条可编辑规则')
        await page.screenshot(path=str(OUT/'rule-review.png'),full_page=True)
        await page.locator('#activate-button').click()
        await expect(page.locator('#rule-dialog')).not_to_be_visible()
        await expect(page.locator('.task-card')).to_have_count(1)
        await expect(page.locator('#stat-alerts')).to_have_text('0')
        await page.locator('.fault-lab summary').click()
        await page.locator('[data-scenario="drop"]').click()
        await expect(page.locator('.status.COOLING')).to_be_visible()
        await expect(page.locator('#stat-alerts')).to_have_text('1')
        checks.append('价格触发后进入冷却并写入站内提醒')
        await page.locator('[data-scenario="deeper"]').click()
        await expect(page.locator('#stat-alerts')).to_have_text('1')
        checks.append('价格持续下跌不重复提醒')
        await page.locator('[data-scenario="announcement"]').click()
        await expect(page.locator('#stat-alerts')).to_have_text('1')
        await page.locator('[data-scenario="advance"]').click()
        await expect(page.locator('#stat-alerts')).to_have_text('2')
        checks.append('冷却期间的新公告保留并在冷却后提醒')
        await page.locator('[data-action="audit"]').first.click()
        await expect(page.locator('#audit-body .evidence-card').first).to_be_visible()
        await page.screenshot(path=str(OUT/'audit-evidence.png'),full_page=True)
        checks.append('展示逐条件判断、来源、时间与规则版本')
        await page.get_by_role('button',name='关闭检查记录',exact=True).click()
        await page.locator('[data-scenario="timeout"]').click()
        await expect(page.locator('.status.DEGRADED')).to_be_visible()
        await page.screenshot(path=str(OUT/'desktop-fault.png'),full_page=True)
        await page.locator('[data-scenario="recover"]').click()
        await expect(page.locator('.status.COOLING')).to_be_visible()
        checks.append('来源故障与恢复均有状态反馈')
        await page.locator('[data-action="edit"]').click()
        await page.locator('[data-field="threshold"]').fill('-4')
        await page.locator('#activate-button').click()
        await expect(page.locator('.ticker')).to_contain_text('v2')
        checks.append('规则修改形成新版本')
        await page.locator('[data-view="inbox"]').click()
        await expect(page.locator('.alert-card').first).to_be_visible()
        checks.append('站内提醒记录可访问')
        await page.locator('[data-view="dashboard"]').click()
        await page.screenshot(path=str(OUT/'desktop-dashboard.png'),full_page=True)
        mobile=await browser.new_context(viewport={'width':390,'height':844},device_scale_factor=1,is_mobile=True,has_touch=True)
        await mobile.add_cookies(await context.cookies())
        mobile_page=await mobile.new_page()
        await mobile_page.goto(BASE,wait_until='networkidle')
        await expect(mobile_page.locator('.task-card')).to_have_count(1)
        assert await mobile_page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        await mobile_page.screenshot(path=str(OUT/'mobile-dashboard.png'),full_page=True)
        checks.append('390像素移动端无横向溢出')
        other=await browser.new_context()
        other_page=await other.new_page()
        await other_page.goto(BASE,wait_until='networkidle')
        await expect(other_page.locator('.task-card')).to_have_count(0)
        checks.append('新浏览器会话看不到已有访客的任务')
        assert not errors,errors
        checks.append('无未捕获浏览器JavaScript异常')
        await browser.close()
    result={'run_at':datetime.now(timezone.utc).isoformat(),'checks':checks,'passed':len(checks),'javascript_errors':errors,'base_url':BASE}
    output_name='browser-public-acceptance.json' if BASE.startswith('https://') else 'browser-acceptance.json'
    (OUT/output_name).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))


asyncio.run(main())
