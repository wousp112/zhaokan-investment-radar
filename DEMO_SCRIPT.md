# 产品演示视频 v1.2

[带章节的播放器](https://exhibitions-vienna-extending-liberty.trycloudflare.com/static/demo.html) · [下载MP4](https://github.com/wousp112/zhaokan-investment-radar/releases/download/v1.2.0/demo.mp4) · [本地视频](artifacts/cinematic-v1.2/demo-v1.2.mp4) · [验证记录](artifacts/cinematic-v1.2/verification.json)

时长146.23秒，1920×1080，30帧，H.264视频与AAC声音。包含中文合成旁白、32段同步字幕和重点放大。11组主操作带有按实际控件位置绘制的点击提示，反馈选项也保留点击标注。独立播放页提供16个章节、讲解全文和下载入口。

画面来自隔离模拟环境中的实际操作，点击环与镜头运动是后期制作。部分等待经过剪辑，成片不作为连续录屏或模型延迟的测量证据。旁白使用macOS内置中文声音在本机生成，未克隆个人声音。

| 位置 | 展示内容 |
| --- | --- |
| 0.00秒 | 把关注条件，变成持续检查 |
| 9.70秒 | 先写清楚，关注什么 |
| 20.07秒 | AI 整理，用户核对 |
| 29.80秒 | 每一项条件，都能检查 |
| 39.37秒 | 确认之后，才开始检查 |
| 47.77秒 | 没有提醒，也有明确原因 |
| 58.73秒 | 条件满足，保存一条提醒 |
| 68.70秒 | 持续检查，减少重复打扰 |
| 76.23秒 | 新公告先保留 |
| 83.67秒 | 间隔结束，补发公告 |
| 92.50秒 | 数据异常，说明受影响的判断 |
| 100.63秒 | 恢复之后，继续监控 |
| 108.57秒 | 打开提醒，核对当时的依据 |
| 117.53秒 | 修改条件，保留旧的判断 |
| 127.47秒 | 演示与真实，分开统计 |
| 135.67秒 | 从一条能解释的提醒开始 |

```bash
pip install -r requirements-artifacts.txt
python scripts/build_cinematic_voice.py
python scripts/build_cinematic_demo.py
python scripts/verify_demo.py
python scripts/install_demo_assets.py
```

构建需要FFmpeg、macOS内置中文语音和本机中文字体。字体可以通过`RADAR_CAPTION_FONT`指定，字体文件不随仓库分发。源图、字幕及成片摘要保存在`artifacts/cinematic-v1.2/`；制作方法和检查范围见[影音交付说明](docs/VIDEO_PRODUCTION.md)。

视频大文件通过GitHub发布附件交付。仅克隆源码时，播放页、封面和讲解文字可用；需从发布附件下载视频到`app/web/static/demo-v1.2.mp4`后，才能在自建实例内播放。旧v1.1视频和提交包继续保留。
