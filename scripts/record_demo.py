"""Record actual browser actions with explanatory captions. No simulated UI clicks."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from playwright.async_api import async_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts'


async def main():
    (OUT/'video-raw').mkdir(parents=True,exist_ok=True)
    chapters=[]
    errors=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='chrome',headless=True)
        context=await browser.new_context(viewport={'width':1440,'height':1000},device_scale_factor=1,
            record_video_dir=str(OUT/'video-raw'),record_video_size={'width':1440,'height':1000})
        page=await context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        await page.goto('http://127.0.0.1:8000',wait_until='networkidle')
        await expect(page.locator('#target option')).to_have_count(13)
        await page.evaluate('''() => {
            const host=document.createElement('div');host.id='demo-captions';
            Object.assign(host.style,{position:'fixed',bottom:'0',left:'0',right:'0',zIndex:'2147483647',
                background:'rgba(5,12,23,.97)',borderTop:'1px solid #42658f',padding:'17px 32px',
                color:'#eff5ff',fontFamily:'-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif',
                pointerEvents:'none',minHeight:'94px'});
            host.innerHTML='<div id="caption-title" style="font-size:12px;letter-spacing:2px;color:#81b7ff"></div><div id="caption-body" style="font-size:21px;margin-top:5px;line-height:1.5"></div>';
            document.body.appendChild(host);
            document.querySelector('main').style.paddingBottom='180px';
            const observer=new MutationObserver(()=>{
                const parent=document.querySelector('dialog[open]')||document.body;
                if(host.parentNode!==parent)parent.appendChild(host);
            });
            document.querySelectorAll('dialog').forEach(dialog=>observer.observe(dialog,{attributes:true,attributeFilter:['open']}));
        }''')
        started=time.monotonic()
        async def chapter(title,body,hold=0):
            await page.evaluate('''([title,body])=>{
                document.querySelector('#caption-title').textContent=title;
                document.querySelector('#caption-body').textContent=body;
            }''',[title,body])
            chapters.append({'at_seconds':round(time.monotonic()-started,2),'title':title,'caption':body})
            if hold:
                await page.wait_for_timeout(hold*1000)

        await chapter('01 / 照看：投资监控与风险雷达','把一句关注点变成持续检查的规则。提醒与未提醒，都能看到依据。',7)
        await page.locator('#new-alert').click()
        await page.locator('[data-example="golden"]').click()
        await chapter('02 / 自然语言 → 可检查规则','未来两周：日内跌幅达到3%，或出现业绩预告。AI调用失败时会明确显示本地回退。',4)
        await page.locator('#parse-button').click()
        await expect(page.locator('#rule-dialog')).to_be_visible(timeout=45000)
        await chapter('03 / 激活前确认，阈值可修改','核对公司、比较关系与公告类别。将跌幅改为3.5%，保留30分钟提醒间隔。',2)
        await page.locator('[data-field="threshold"]').fill('3.5')
        await page.wait_for_timeout(5000)
        await page.locator('#activate-button').click()
        await expect(page.locator('#rule-dialog')).not_to_be_visible()
        await expect(page.locator('#task-list .task-card')).to_have_count(1)
        await page.locator('#dashboard-view').scroll_into_view_if_needed()
        await chapter('04 / 为什么没有提醒','模拟跌幅为1.2%，没有新公告。两条条件均未满足，本轮不提醒。',2)
        await page.locator('[data-action="audit"]:visible').first.click()
        await expect(page.locator('#audit-body .evidence-card').first).to_be_visible()
        await page.wait_for_timeout(6000)
        await page.get_by_role('button',name='关闭检查记录',exact=True).click()
        await page.locator('[data-view="demo"]').click()
        await page.locator('[data-scenario="drop"]').click()
        await expect(page.locator('#inbox-count')).to_have_text('1')
        await chapter('05 / 为什么提醒','模拟跌幅达到3.8%，超过设定阈值。提醒已保存，同时进入提醒间隔。',3)
        await page.locator('[data-action="audit"]:visible').first.click()
        await expect(page.locator('#audit-body .evidence-card').first).to_be_visible()
        await page.wait_for_timeout(6000)
        await page.get_by_role('button',name='关闭检查记录',exact=True).click()
        await page.locator('[data-scenario="deeper"]').click()
        await expect(page.locator('#inbox-count')).to_have_text('1')
        await chapter('06 / 提醒间隔与去重','跌幅继续扩大至4.5%，同一交易日的同一价格规则不会重复打扰。',7)
        await page.locator('[data-scenario="announcement"]').click()
        await expect(page.locator('#inbox-count')).to_have_text('1')
        await chapter('07 / 提醒间隔期间，公告仍被保留','提醒间隔期间发现新业绩预告，先保留。推进演示时钟，提醒间隔结束后再提醒。',5)
        await page.locator('[data-scenario="advance"]').click()
        await expect(page.locator('#inbox-count')).to_have_text('2')
        await page.wait_for_timeout(4000)
        await page.locator('[data-scenario="timeout"]').click()
        await expect(page.locator('.status.DEGRADED:visible')).to_be_visible()
        await chapter('08 / 来源异常，明确告诉用户','注入行情超时：价格条件显示“无法判断”，公告检查继续运行。',2)
        await page.locator('[data-action="audit"]:visible').first.click()
        await expect(page.locator('#audit-body .truth.unknown').first).to_be_visible()
        await page.wait_for_timeout(6500)
        await page.get_by_role('button',name='关闭检查记录',exact=True).click()
        await page.locator('[data-scenario="recover"]').click()
        await expect(page.locator('.status.COOLING:visible')).to_be_visible()
        await chapter('09 / 恢复与规则历史','来源恢复后继续监控。修改规则形成新版本，历史判断仍可追溯。',3)
        await page.locator('[data-action="edit"]:visible').click()
        await page.locator('[data-field="threshold"]').fill('4')
        await page.locator('#activate-button').click()
        await expect(page.locator('.rules-summary:visible')).to_contain_text('4%')
        await page.locator('[data-action="audit"]:visible').first.click()
        await page.locator('#show-versions').click()
        await expect(page.locator('.version-card')).to_have_count(2)
        await page.wait_for_timeout(5500)
        await page.get_by_role('button',name='关闭检查记录',exact=True).click()
        await page.locator('[data-view="inbox"]').click()
        await chapter('10 / 每次提醒都有记录','条件提醒、来源异常和恢复分开记录。通知与任务状态在同一事务内保存。',7)
        await page.locator('[data-view="about"]').click()
        await chapter('11 / 当前边界与验证证据','本视频使用模拟行情。已完成真实模型与数据接口探测、自动化测试及进程重启验证。',7)
        await chapter('照看 · Qiyao Tan','规则由用户确认。仅提供事实监控与站内提醒，不构成投资建议。',5)
        await page.screenshot(path=str(OUT/'demo-end-frame.png'))
        video=page.video
        await context.close()
        path=await video.path()
        await browser.close()
    metadata={'recorded_at':datetime.now(timezone.utc).isoformat(),'raw_video':str(path),
              'capture':'Playwright录制真实Chrome页面操作，章节字幕为后加说明，行情明确使用replay',
              'chapters':chapters,'javascript_errors':errors,'status':'recorded'}
    (OUT/'demo-recording.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2))
    print(json.dumps(metadata,ensure_ascii=False,indent=2))


asyncio.run(main())
