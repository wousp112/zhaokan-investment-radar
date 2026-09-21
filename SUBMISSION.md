# 照看 · 提交入口

项目：可配置投资监控与风险雷达。面向同花顺 AI 产品经理（AIME金融智能Agent方向）笔试。

| 提交物 | 入口 |
| --- | --- |
| 可交互Web产品 | [打开照看](https://intention-water-assistant-comparative.trycloudflare.com) |
| 完整源代码与README | [GitHub仓库](https://github.com/wousp112/zhaokan-investment-radar) |
| 本轮约96秒演示视频 | [下载本轮视频](https://github.com/wousp112/zhaokan-investment-radar/releases/download/v1.1.0/demo.mp4) · [实例内播放](https://intention-water-assistant-comparative.trycloudflare.com/static/demo.mp4)；本地文件为 `artifacts/professional-review/demo-v1.1.mp4` |
| AI使用与验证记录 | [AI_USAGE_AND_VERIFICATION.md](AI_USAGE_AND_VERIFICATION.md) |
| 测试说明与原始证据 | [TESTING_AND_EVAL.md](TESTING_AND_EVAL.md)、[本轮原始结果](artifacts/professional-review/) |
| 产品取舍及36项补齐清单 | [专业交付检查](docs/PROFESSIONAL_GAP_REVIEW.md) |

## 建议体验顺序

初次打开，点击“用示例试一次”。也可在“新建提醒”中输入关注条件，点击“下一步：核对提醒”，核对后选择“确认并开启提醒”。不确定怎么写时，可直接选择条件。确认前不会开始检查。

进入“演示体验”，先查看未触发的依据，再测试“下跌至3.8%”“继续下跌”和“新业绩预告”。推进31分钟，检查公告是否补发；用“行情超时”和“恢复来源”查看两类通知。在“提醒记录”中打开单条通知、留下反馈，再修改原任务，核对旧通知仍保留生成时的依据。

“运行情况”显示当前浏览器近7天的过程记录。模拟和真实数据分开，没有样本时不显示成功率。

## 本轮交付状态

后端113项回归与前端16项逻辑测试通过。当前编译器的20条固定模型用例全部取得模型输出且字段匹配，失败网络批次独立保留。隔离环境中120条模拟任务通过真实调度器的首轮检查；在线备份在隔离位置完成恢复核验。

视频长95.97秒，1440×1160，H.264，带简体中文字幕。画面来自本轮实际操作截图，按环节剪辑，覆盖文字整理、核对、触发、去重、公告保留、异常、通知反馈和运行统计。它是分镜演示，各画面取自不同验证步骤。视频已完整解码检查，原生桥接未能返回可见图像，人工视觉播放检查仍待完成。

## 评审时需要知道的边界

公网服务由本机通过临时Cloudflare通道提供，依赖电脑、网络与通道持续运行。常驻主机和固定地址尚未部署。站内通知没有外部推送，清除访客Cookie或更换设备无法自动找回任务。

真实公告检索覆盖有限，缺少完整参考流，无法报告真实漏报率。真实量比和全市场搜索尚未接入。固定模型回归成绩不代表开放域准确率；真人首次使用、留存及真实交易日观测尚未完成。完整缺口及下一阶段条件见36项清单。
