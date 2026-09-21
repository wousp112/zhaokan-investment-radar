# 照看 · 提交入口

项目：可配置投资监控与风险雷达。面向同花顺 AI 产品经理（AIME 金融智能 Agent 方向）笔试。

| 提交物 | 入口 |
| --- | --- |
| 可交互 Web 产品 | [打开照看](https://intention-water-assistant-comparative.trycloudflare.com) |
| 完整源代码与 README | [GitHub 仓库](https://github.com/wousp112/zhaokan-investment-radar) |
| 96秒历史演示视频（改版前界面） | [下载 MP4](https://github.com/wousp112/zhaokan-investment-radar/releases/download/v1.0.0/demo.mp4) |
| AI 使用与验证记录 | [AI_USAGE_AND_VERIFICATION.md](AI_USAGE_AND_VERIFICATION.md) |
| 测试说明与原始证据 | [TESTING_AND_EVAL.md](TESTING_AND_EVAL.md)、[artifacts](artifacts/) |

当前产品已采用新的提醒列表和规则设置页。历史视频尚未重录，提交前应补上与当前界面一致的视频。

## 建议体验顺序

打开产品，点击“新建提醒”，选择“演示情景（模拟数据）”和“跌幅 + 业绩预告”示例。点击“查看规则”，核对条件后点击“开始监控”。

进入侧栏“演示体验”，先点击任务的“查看记录”了解未触发原因，再依次测试“下跌至3.8%”“继续下跌”“新业绩预告”“行情超时”和“恢复来源”。冷却期间新公告会暂存，点击“推进31分钟”后再判断。修改规则形成新版本，旧判断仍可追溯。

## 评审时需要知道的边界

当前 Web 入口由本机服务通过 Cloudflare 临时通道提供，依赖电脑、网络与通道持续运行。它用于短期交互评审，尚未迁移至常驻云主机。源码和已发布的视频独立保存在 GitHub，不依赖该通道。

真实行情与演示数据隔离。公告源使用有限覆盖的语义检索，可能漏检；真实量比未接入。当前提醒保存在站内，没有短信、邮件或后台推送。详细设计取舍见 [README](README.md) 与 [产品决策](docs/PRODUCT_DECISIONS.md)。

自动化测试通过数、模型各批次结果和进程强制终止恢复结果均保留原始记录。固定用例成绩不代表开放域准确率。视频使用明确标注的模拟行情，包含简体中文字幕，无旁白。
