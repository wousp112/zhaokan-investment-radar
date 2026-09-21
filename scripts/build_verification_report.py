"""Build human-readable claims directly from recorded execution evidence."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import statistics
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
def read(name):
    return json.loads((ROOT/'artifacts'/name).read_text())


def main():
    tree=ET.parse(ROOT/'artifacts/pytest-results.xml')
    suites=tree.getroot().findall('testsuite')
    tests=sum(int(s.get('tests',0)) for s in suites)
    failures=sum(int(s.get('failures',0))+int(s.get('errors',0)) for s in suites)
    skipped=sum(int(s.get('skipped',0)) for s in suites)
    browser=read('browser-acceptance.json')
    recovery=read('process-recovery.json')
    # Keep the initial measurement immutable when later runs update the default output.
    baseline_path=ROOT/'artifacts/ai-evaluation-baseline.json'
    model=json.loads(baseline_path.read_text()) if baseline_path.exists() else read('ai-evaluation.json')
    latest_path=ROOT/'artifacts/ai-evaluation-final.json'
    latest_model=json.loads(latest_path.read_text()) if latest_path.exists() else None
    if latest_model and latest_model.get('completed') != latest_model.get('total'):
        latest_model=None
    model_matches_source = bool(latest_model and latest_model.get('compiler_source_sha256') ==
                                hashlib.sha256((ROOT/'app/core/nlp_compiler.py').read_bytes()).hexdigest())
    ui=read('ui-parse-probe.json')
    initial=read('live-probe.json')
    quote=read('latest-quote-probe.json')
    valid=[r for r in model['records'] if r.get('live_model')]
    all_matching=sum(r.get('semantic_match',False) for r in model['records'])
    latencies=[r['result']['compilation']['latency_ms'] for r in valid]
    table='\n'.join(f"| {r['case_id']} | {r['prompt']} | {'模型输出' if r.get('live_model') else '本地回退'} | {'匹配' if r.get('semantic_match') else '不匹配'} | {r.get('result',{}).get('compilation',{}).get('fallback_reason') or '无'} |" for r in model['records'])
    stamp=datetime.now(timezone.utc).isoformat()
    public_file=ROOT/'artifacts/browser-public-acceptance.json'
    public=json.loads(public_file.read_text()) if public_file.exists() else None
    public_line=(f"| 公网 Chrome 操作验收 | {public['passed']} 项通过 | [原始记录](artifacts/browser-public-acceptance.json) |" if public else '| 公网 Chrome 操作验收 | 尚未生成验收记录 | 不能以本地验收替代公网验收 |')
    report=f'''# 测试与评测说明

生成时间：{stamp}。下列数字来自实际运行结果，由 `scripts/build_verification_report.py` 生成。

## 本轮证据

| 验证层 | 实际结果 | 证据 |
| --- | --- | --- |
| 单元与 API 自动化测试 | {tests-failures-skipped}/{tests} 通过，{failures} 失败，{skipped} 跳过 | [JUnit 原始记录](artifacts/pytest-results.xml) |
| 本地 Chrome 操作验收 | {browser['passed']} 项通过，{len(browser['javascript_errors'])} 个未捕获脚本异常 | [原始记录](artifacts/browser-acceptance.json) |
| 独立进程强制终止与恢复 | {'通过' if recovery['passed'] else '未通过'} | [进程级验证](artifacts/process-recovery.json) |
| 首轮真实模型调用与字段校验 | {len(valid)}/{model['total']} 次取得有效模型结果；其中 {sum(r['passed'] for r in valid)} 次字段匹配 | [20 条逐项记录](artifacts/ai-evaluation-baseline.json) |
| 含本地回退的规则编译 | {all_matching}/{model['total']} 条输出匹配固定用例预期 | 同上；模型和回退分开计数 |
| 真实黄金用例模型调用 | {initial['compiler']['compilation']['engine']}，{initial['compiler']['compilation']['latency_ms']} ms | [首次真实探测](artifacts/live-probe.json) |
| 最新扶摇行情探测 | {quote['quote']['status']}，市场开市状态为 {quote['quote']['market_open']} | [时间与请求号](artifacts/latest-quote-probe.json) |
{public_line}

最终模型复测对应当前编译器源码：{'是' if model_matches_source else '否，需要重新核验'}。最新批次结果为 {str(latest_model['passed'])+'/'+str(latest_model['total']) if latest_model else '尚无完整结果'}，原始记录见 [最终模型复测](artifacts/ai-evaluation-final.json)。本轮还验证了真实报价恰好涨跌3%时，严格比较不会因浮点误差提前触发，见 `test_live_quote_keeps_exact_percentage_boundary`。

完整题目原句在解析边界修正后，又进行了真实浏览器复测：HTTP {ui['status']}，确认窗口可见状态为 {ui['dialog_visible']}。记录见 [修复后完整原句验证](artifacts/ui-parse-probe.json)；修复前返回422的原始记录保存在 [首次错误](artifacts/ui-parse-initial-error.json)。这次模型调用与上面的首轮20条评测分别记录。

这些是固定用例和本轮环境下的结果。没有进行大规模用户测试、随机开放域基准、全天交易日压力测试或生产可用性测量，不能用它们推导整体准确率或长期服务保证。

## 功能、故障与边界覆盖

| 要求 | 测试位置 | 验证对象 |
| --- | --- | --- |
| 自然语言与可修改规则 | `test_main_pipeline.py`、`test_api.py` | 20 条本地表达、标的上下文、严格和包含边界、持续时间、AND/OR、规则修改与版本冲突 |
| 生命周期与免打扰 | `test_cooldown.py` | 激活、暂停、恢复、到期、同日价格去重、公告终身指纹、冷却中新公告保留 |
| 每轮可解释性 | `test_cooldown.py` | 连续 50 次检查对应 50 条记录；逐条件结果、来源、时间、规则校验摘要 |
| 来源异常 | `test_degradation.py` | 超时、500、过期、冲突、公告失败、休市、健康提醒去重、恢复通知 |
| 恢复与一致性 | `test_cooldown.py`、独立进程脚本 | SQLite 回滚、并发检查只产生一条提醒、SIGKILL后恢复冷却及待提醒公告 |
| 用户与输入边界 | `test_api.py`、`test_regressions.py` | 会话隔离、跨站修改拒绝、大小限制、未知字段、真实任务拒绝模拟注入、交易与收益承诺拒绝 |
| 实际操作 | `scripts/browser_acceptance.py` | 浏览器创建、确认、触发、冷却、公告保留、故障恢复、版本、消息、390像素移动布局 |

自动化测试中的接口故障由明确的演示适配器或测试替身注入。真实网络探测单独记录，不能把故障注入结果解释成真实接口长期稳定运行。

## 真实模型：成功、失败和回退分别记录

首轮模型请求完成 {model['completed']} 条。{len(valid)} 次取得 DeepSeek 输出，{model['total']-len(valid)} 次因连接错误回退。有效模型调用耗时中位数为 {statistics.median(latencies):.0f} ms，最短 {min(latencies)} ms，最长 {max(latencies)} ms。样本来自手工用例，未测用户自由输入分布。

| 编号 | 输入 | 实际引擎 | 规则字段 | 调用失败原因 |
| --- | --- | --- | --- | --- |
{table}

原始失败没有删除，也没有把回退记为模型成功。当前结果适合检查主链路与故障回退，不能声称“AI准确率100%”。

{('提示词修正后的第二批完整20条复测：'+str(latest_model['passed'])+'/'+str(latest_model['total'])+'次取得模型输出且字段匹配；其中模型实际返回'+str(latest_model['live_model_calls'])+'次。全链路字段匹配'+str(sum(r.get('semantic_match',False) for r in latest_model['records']))+'条。该批次独立保存，附当前编译器源码SHA256，见[最终模型复测](artifacts/ai-evaluation-final.json)。') if latest_model else '提示词修正后的完整20条复测尚无已完成记录，不据此更新首轮结果。'}

## 进程恢复中实际发现并修复的问题

第一次强制终止测试在准备阶段失败：模拟公告时间被截断到秒，任务开始时间保留亚秒精度，导致同一秒内新增公告被误认为早于任务开始。

已保留公告完整时间精度，并新增 `test_new_event_keeps_subsecond_timestamp`。重跑后验证了任务冷却、待提醒公告和去重指纹在进程重启后保留；推进冷却后，只补发待提醒公告，没有重复价格提醒。测试仅终止脚本创建的独立进程，不影响演示服务。

## 复现

```bash
python -m pytest -q --junitxml=artifacts/pytest-results.xml
python scripts/test_process_recovery.py
python scripts/browser_acceptance.py
python scripts/evaluate_ai.py
python scripts/probe_quote.py
python scripts/build_verification_report.py
```

浏览器验收要求应用已启动，以及 Playwright 与 Chrome 可用。模型和行情脚本需要合法的服务凭据及网络，可能产生调用用量。每次重跑会写入该脚本对应的结果文件；需要比较不同批次时应先归档现有结果。
'''
    (ROOT/'TESTING_AND_EVAL.md').write_text(report)
    usage=f'''# AI 使用与验证记录

## 使用分工

用户提供了招聘题目、产品目标、黄金场景和早期 PRD/技术草案。开发协作 AI 完成代码、页面、测试、文档与问题修复；运行时 DeepSeek 负责将关注点转换成结构化规则。本文区分代码已执行验证、模型实际调用和仍未覆盖的场景，不把初期方案中的设想记为已交付。

| 工作 | AI 的作用 | 独立于生成结果的检查 |
| --- | --- | --- |
| 规则提取 | DeepSeek `deepseek-flash` 输出 JSON | Pydantic 字段约束、已核对的股票身份、用户确认、固定用例字段比较 |
| 开发与界面 | 开发协作 AI 编写 Python、HTML、CSS、JavaScript | pytest、Chrome 实际页面操作、代码语法检查 |
| 长程运行机制 | 协助设计调度、事务、冷却和恢复 | 独立服务进程 SIGKILL 后重启，检查实际数据库状态与提醒 |
| 验证说明 | 从运行记录生成文字与数字 | 原始 JSON、JUnit 和复现脚本随仓库提供 |
| 演示视频 | 脚本操作真实 Chrome 并添加章节字幕 | 视频时长与文件属性由 ffprobe 检查；页面使用明确标注的模拟数据 |

## 运行时模型调用

模型配置来源于服务器环境变量，API key 不进入浏览器或仓库。接口为 DeepSeek `/chat/completions`，启用 JSON 输出；系统提示词及模式定义可在 `app/core/nlp_compiler.py` 检查。

提示词要求保留数值、严格比较与包含比较、条件关系、持续时间、频率和冷却；不扩展公告类别，不将其他热度猜成量比。输出必须通过结构校验。对不支持的指标和无法确定的表达，系统不会省略后直接激活。

首次黄金用例真实模型调用为 {initial['compiler']['compilation']['latency_ms']} ms，返回 {initial['compiler']['compilation']['model']}；输入和最终 Task Spec 见 [原始记录](artifacts/live-probe.json)。记录保留模型名称、请求时间、token使用量和最终结构化结果，没有保存或公开模型内部推理文本。

首轮 20 条模型评测中，15 次取得有效模型输出，5 次连接失败。失败请求由本地规则解析器完成，界面和记录中均显示 `local_rules` 与 `ConnectError`。所有 20 条最终规则匹配该固定用例集的预期字段，但只有 15 次计为真实模型成功。详见 [首轮逐项记录](artifacts/ai-evaluation-baseline.json)。后续一次有网络权限的复测为17/20，包含两次澄清和一次结构校验失败，单独保存在 `artifacts/ai-evaluation-before-prompt-fix.json`。

## 来源核验与实际修正

| 发现 | 证据或重现 | 修正 |
| --- | --- | --- |
| 初期测试文档已经写着通过，但没有对应测试代码 | 本次开始时工作区仅有方案文档 | 建立可运行测试，所有通过数改为由执行产物生成 |
| iFinD 文件并不支持原草案中的直接命令行调用 | 直接调用只返回入口提示；读取文件确认导出 `call` | 通过 Node 桥接调用导出函数 |
| 公告检索缺少稳定公告ID、原文链接和精确发布时间 | 真实查询返回标题、片段和日期；未返回这些字段 | 仅使用核验得到的标题与日期，建立首次查询基线，明确有限检索覆盖 |
| 行情连续请求触发429 | 首次真实探测记录 | 加入请求间隔和 Retry-After 等待；最新探测已返回有效行情 |
| 亚秒内的公告被误判为早于任务开始 | 独立进程测试在准备阶段失败 | 保留完整公告时间，并增加回归测试 |
| JSON校验通过不能代表所有用户条件都被保留 | 对“不支持指标+有效价格条件”进行审查 | 增加拒绝静默省略的输入检查与回归用例 |
| 完整原句中的异常通知被模型误判为需要澄清 | 实际页面返回422且确认窗口未出现 | 明确异常通知与去重属于系统内置机制；修正后真实模型返回200，确认窗口正常显示 |

最新报价探测时间为 {quote['checked_at']}，返回状态 `{quote['quote']['status']}`，请求号 `{quote['quote'].get('request_id')}`。仅为单次只读接口探测，不代表未来可用性。

提示词修正后的完整题目原句另有独立浏览器探测，[结果](artifacts/ui-parse-probe.json)显示HTTP {ui['status']}、确认窗口可见 {ui['dialog_visible']}。首轮20条结果保留原样；后续完整批次如已完成，见 `artifacts/ai-evaluation-final.json`，不能把不同批次合并成未经定义的准确率。

最终完整批次共 {latest_model['total'] if latest_model else 0} 条，其中 {latest_model['passed'] if latest_model else 0} 条取得模型输出且字段符合预期；编译器源码摘要与当前文件{'一致' if model_matches_source else '未确认一致'}。该批次为同一固定用例集上的复测，不能解释成独立留出集准确率。

## 保留的能力边界

AI 不决定买入、卖出或仓位，不直接计算触发结果，不读取服务器文件，不执行公告文本中的指令。用户必须确认规则后激活。来源失败、回退、冷却和未触发均可查看。当前验证集规模小，公告检索可能漏检，公共体验依赖临时通道；这些边界均保留在交付文档和产品说明中。
'''
    (ROOT/'AI_USAGE_AND_VERIFICATION.md').write_text(usage)
    summary={'generated_at':stamp,'automated_tests':tests,'passed':tests-failures-skipped,'failed':failures,
             'browser_checks':browser['passed'],'process_recovery':recovery['passed'],'live_model_successes':len(valid),
             'live_model_attempts':model['total'],'pipeline_semantic_matches':all_matching,'latest_quote_status':quote['quote']['status'],
             'latest_model_passed':latest_model['passed'] if latest_model else None,
             'latest_model_total':latest_model['total'] if latest_model else None,
             'model_matches_current_compiler':model_matches_source,
             'public_browser_checks':public['passed'] if public else None,
             'public_browser_checked_at':public['run_at'] if public else None}
    (ROOT/'artifacts/verification-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print(json.dumps(summary,ensure_ascii=False,indent=2))


main()
