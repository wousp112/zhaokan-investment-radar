# 本轮产品演示视频

[下载视频](https://github.com/wousp112/zhaokan-investment-radar/releases/download/v1.1.0/demo.mp4) · [实例内播放](https://exhibitions-vienna-extending-liberty.trycloudflare.com/static/demo.mp4) · [本地MP4](artifacts/professional-review/demo-v1.1.mp4) · [文件与来源校验](artifacts/professional-review/demo-video.json)

时长95.97秒，1440×1160，H.264编码，无旁白，带简体中文字幕。视频采用本轮实际操作截图分镜，各环节来自不同的验证步骤。所有行情均为明确标注的模拟数据，未修改截图中的条件或结果，字幕放在原截图下方。视频经过完整解码检查；原生图像返回受限，人工观看的视觉验收仍待完成。

| 位置 | 展示内容 |
| --- | --- |
| 0秒 | 写下关注条件，并说明AI发送的文字范围 |
| 8秒 | 核对公司、阈值及结束时间，确认前只是草稿 |
| 16秒 | 不写自然语言，也可直接选择条件 |
| 24秒 | 下跌1.2%时，价格与公告为何均未满足 |
| 32秒 | 模拟下跌3.8%触发，继续下跌不重复通知 |
| 40秒 | 提醒间隔内保留新公告，推进后再判断 |
| 48秒 | 行情超时影响哪些判断，恢复后怎样通知 |
| 56秒 | 在提醒记录中区分条件、异常和恢复 |
| 64秒 | 打开通知、保存反馈，支持撤回 |
| 72秒 | 规则改到4%后，旧通知仍保留第1版3%的证据 |
| 80秒 | 当前浏览器的实际运行统计 |
| 88秒 | 真实记录无样本时保留空结果，说明部署和推送边界 |

```bash
pip install -r requirements-artifacts.txt
python scripts/build_review_walkthrough.py
```

构建脚本从已保存的截图生成分镜，不会操作浏览器或改动任务数据。需要系统FFmpeg和已安装的中文字体，可通过 `RADAR_CAPTION_FONT` 指定本机字体路径；不分发字体文件。每张截图的SHA256、章节和导出文件摘要保存在视频记录中。

v1.0.0历史视频继续保留在GitHub旧版本发布中。本轮容量探测、模型评测和进程恢复证据独立于视频，不以分镜停留时长推导模型或系统性能。
