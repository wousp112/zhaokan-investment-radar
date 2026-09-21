"""Exercise the redesigned UI in an isolated test visitor. Uses only simulated market data.

Run: python scripts/browser_acceptance.py --base-url http://127.0.0.1:8000
Requires Playwright and its Chrome/Chromium browser. This is a repeatable test
script; archived task records are deliberately retained as test evidence.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts' / 'ux_redesign'
PROMPT = '未来两周帮我盯住贵州茅台：日内跌幅达到3%，或者发布新的业绩预告，就提醒我。同一件事别反复提醒；如果监控出了问题，也告诉我。'


async def run(base_url: str):
    OUT.mkdir(parents=True, exist_ok=True)
    results, errors = [], []
    report = {'run_at': datetime.now(timezone.utc).isoformat(), 'base_url': base_url,
              'market_data': 'replay', 'model': 'local parser', 'checks': results,
              'javascript_errors': errors, 'status': 'running'}
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel='chrome', headless=True)
        context = await browser.new_context(viewport={'width': 1440, 'height': 1000})
        page = await context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))

        def passed(name):
            results.append({'name': name, 'passed': True})

        async def task():
            response = await context.request.get(base_url + '/api/tasks')
            assert response.ok
            tasks = (await response.json())['tasks']
            assert len(tasks) == 1
            return tasks[0]

        async def scenario(key, expected):
            await page.locator(f'[data-scenario="{key}"]').click()
            await expect(page.locator('#scenario-result')).to_contain_text(expected)

        try:
            await page.goto(base_url, wait_until='networkidle')
            await expect(page.locator('#new-alert')).to_be_enabled()
            await expect(page.locator('#target option')).to_have_count(13)
            await expect(page.locator('#task-list .task-card')).to_have_count(0)
            passed('新访客显示空状态和明确的新建入口')
            await page.locator('#new-alert').click()
            await page.locator('#prompt').fill(PROMPT)
            await page.locator('.input-options summary').click()
            await page.locator('#use-ai').uncheck()
            await page.locator('#target').select_option('300750.SZ')
            await page.locator('#parse-button').click()
            await expect(page.locator('#parse-error')).to_contain_text('公司不同')
            await expect(page.locator('#prompt')).to_have_value(PROMPT)
            await page.locator('#target').select_option('')
            await page.locator('#parse-button').click()
            await expect(page.locator('#rule-dialog')).to_be_visible()
            await expect(page.locator('[data-field="threshold"]')).to_have_value('3')
            await expect(page.locator('[data-boundary="0"]')).to_contain_text('包含正好3%')
            await page.locator('[data-field="operator"]').select_option('>')
            await expect(page.locator('[data-boundary="0"]')).to_contain_text('不包含正好3%')
            await page.locator('[data-field="operator"]').select_option('>=')
            passed('公司冲突可纠正，正数跌幅和严格比较可检查')
            await page.locator('#activate-button').click()
            await expect(page.locator('#rule-dialog')).not_to_be_visible()
            await expect(page.locator('#task-list .task-card')).to_have_count(1)
            created = await task()
            assert created['spec']['conditions'][0]['threshold'] == -.03
            assert created['spec']['conditions'][0]['operator'] == '<='
            assert created['spec']['condition_logic'] == 'OR'
            passed('确认后保存正确的负比例与OR规则')
            await page.locator('[data-view="demo"]').click()
            await scenario('drop', '条件提醒共1条')
            await scenario('deeper', '相同条件已经提醒')
            await scenario('announcement', '新公告已保留')
            await scenario('advance', '条件提醒共2条')
            passed('触发、同日去重、间隔内保留和公告补发')
            await scenario('timeout', '暂时无法完整判断')
            await page.locator('#demo-task [data-action="audit"]').click()
            await expect(page.locator('.truth.unknown:visible')).to_contain_text('无法判断')
            await page.get_by_role('button', name='关闭检查记录', exact=True).click()
            await scenario('recover', '条件提醒共2条')
            await expect(page.locator('#demo-task .status')).not_to_have_class('status DEGRADED')
            passed('行情超时有逐条件依据，恢复后继续检查')
            await page.locator('#demo-task [data-action="edit"]').click()
            await page.locator('[data-field="threshold"]').fill('4')
            await page.locator('#activate-button').click()
            await expect(page.locator('#demo-task .rules-summary')).to_contain_text('4%')
            edited = await task()
            assert edited['spec']['conditions'][0]['threshold'] == -.04
            assert edited['spec']['version'] == 2
            await page.locator('#demo-task [data-action="audit"]').click()
            await page.locator('#show-versions').click()
            await expect(page.locator('.version-card')).to_have_count(2)
            await page.locator('[data-action="rollback"]').click()
            await expect(page.locator('.version-card')).to_have_count(3)
            assert (await task())['spec']['conditions'][0]['threshold'] == -.03
            await page.get_by_role('button', name='关闭检查记录', exact=True).click()
            passed('修改和恢复历史条件形成新版本')
            await page.locator('[data-view="dashboard"]').click()
            await page.locator('#task-list [data-action="pause"]').click()
            await expect(page.locator('#task-list .status')).to_have_text('已暂停')
            paused = await task()
            await page.wait_for_timeout(4200)
            assert (await task())['state']['check_count'] == paused['state']['check_count']
            await expect(page.locator('#task-list')).to_contain_text('检查已暂停')
            await page.locator('#task-list [data-action="resume"]').click()
            await expect(page.locator('#task-list [data-action="pause"]')).to_be_visible()
            passed('暂停后不继续检查，恢复按钮与状态一致')
            await page.locator('#task-search').fill('不存在的公司')
            await expect(page.locator('#task-list .task-card')).to_have_count(0)
            await page.locator('#task-search').fill('600519')
            await expect(page.locator('#task-list .task-card')).to_have_count(1)
            await page.locator('#task-search').fill('')
            passed('按公司或代码搜索可正确过滤')
            await page.locator('#task-list [data-action="archive"]').click()
            await page.locator('#archive-dialog .secondary').click()
            assert (await task())['state']['status'] != 'ARCHIVED'
            await page.locator('#task-list [data-action="archive"]').click()
            await page.locator('#confirm-archive').click()
            await expect(page.locator('#task-list .status')).to_have_text('已归档')
            await expect(page.locator('#task-list [data-action="resume"]')).to_have_count(0)
            passed('归档可取消；确认后停止且保留记录')
            await page.set_viewport_size({'width': 390, 'height': 844})
            assert await page.locator('html').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
            await page.locator('#mobile-menu').click()
            await expect(page.locator('#main')).to_have_attribute('inert', '')
            await page.locator('#close-nav').click()
            await expect(page.locator('#sidebar')).to_have_attribute('inert', '')
            await page.locator('#new-alert').click()
            await expect(page.locator('#compose-dialog')).to_be_visible()
            assert await page.locator('#compose-dialog').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
            await page.keyboard.press('Escape')
            await expect(page.locator('#compose-dialog')).not_to_be_visible()
            await page.screenshot(path=str(OUT/'script-mobile.png'))
            passed('390像素无横向溢出，导航和键盘关闭正常')
            other = await browser.new_context()
            second = await other.new_page()
            await second.goto(base_url, wait_until='networkidle')
            await expect(second.locator('#task-list .task-card')).to_have_count(0)
            await other.close()
            passed('其他访客无法看到当前会话任务')
            assert not errors, errors
            passed('主链路没有未捕获脚本异常')
            report['status'] = 'passed'
        except Exception as error:
            report['status'] = 'failed'
            report['error'] = str(error)
            await page.screenshot(path=str(OUT/'script-failure.png'), full_page=True)
            raise
        finally:
            report['passed'] = len(results)
            (OUT/'script-acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
            await context.close()
            await browser.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    args = parser.parse_args()
    asyncio.run(run(args.base_url.rstrip('/')))
