"""Encode the completed real screen recording and verify delivery constraints."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import fcntl
import json
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts'


def probe(path):
    result=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration,size:stream=codec_name,width,height,r_frame_rate','-of','json',str(path)],check=True,capture_output=True,text=True)
    return json.loads(result.stdout)


def main():
    recorded=json.loads((OUT/'demo-recording.json').read_text())
    if recorded['javascript_errors']:
        raise RuntimeError('Screen recording contains uncaught page errors')
    source=Path(recorded['raw_video'])
    if not source.is_absolute():
        source=ROOT/source
    if not source.resolve().is_relative_to(OUT.resolve()):
        raise ValueError('Unexpected raw video location')
    duration=float(probe(source)['format']['duration'])
    if duration<60 or duration>360:
        raise ValueError('Unexpected source duration; inspect recording before export')
    speed=max(1,duration/150)
    target=OUT/'demo.mp4'
    staging=OUT/'demo.build.mp4'
    command=['ffmpeg','-y','-hide_banner','-loglevel','error','-i',str(source),
             '-vf',f'setpts=PTS/{speed:.8f},fps=30,format=yuv420p',
             '-c:v','libx264','-preset','fast','-crf','20','-movflags','+faststart','-an',str(staging)]
    subprocess.run(command,check=True)
    staging.replace(target)
    details=probe(target)
    final_duration=float(details['format']['duration'])
    assert 60<=final_duration<=180,details
    stream=details['streams'][0]
    assert stream['codec_name']=='h264' and stream['width']==1440 and stream['height']==1000,details
    shutil.copy2(target,ROOT/'app/web/static/demo.mp4')
    for index,at in enumerate((12,38,70,100),1):
        if at<final_duration:
            subprocess.run(['ffmpeg','-y','-hide_banner','-loglevel','error','-ss',str(at),'-i',str(target),'-frames:v','1',str(OUT/f'demo-frame-{index:02}.png')],check=True)
    metadata={'verified_at':datetime.now(timezone.utc).isoformat(),'file':'demo.mp4','duration_seconds':final_duration,
              'width':stream['width'],'height':stream['height'],'codec':stream['codec_name'],
              'size_bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
              'source_duration_seconds':duration,'playback_speed':round(speed,6),
              'capture':'真实Chrome页面操作，添加章节字幕；演示行情明确标注为模拟数据。',
              'audio':'无旁白，使用中文字幕说明操作与判断。',
              'chapters':[dict(c,video_at_seconds=round(c['at_seconds']/speed,2)) for c in recorded['chapters']]}
    (OUT/'demo-video.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2))
    rows='\n'.join(f"| {c['video_at_seconds']:.1f} 秒 | {c['title']} | {c['caption']} |" for c in metadata['chapters'])
    script=f'''# 产品演示视频

[下载 MP4](https://github.com/wousp112/zhaokan-investment-radar/releases/download/v1.0.0/demo.mp4) · [演示实例内播放](https://thesaurus-extends-arrives-speaker.trycloudflare.com/static/demo.mp4)

实际导出时长 **{final_duration:.2f} 秒**，分辨率 **{stream['width']} × {stream['height']}**，H.264 编码。校验记录见 [视频文件属性](artifacts/demo-video.json)。

录制由 Playwright 操作真实 Chrome 页面完成，字幕说明操作与系统判断。画面中行情使用明确标注的演示模式，没有把情景数据称为实时市场。无旁白，字幕为简体中文。播放速度为源录屏的 {speed:.3f} 倍，模型调用时间以产品显示和原始探测记录为准。

| 视频位置 | 环节 | 字幕说明 |
| --- | --- | --- |
{rows}

复现脚本：`scripts/record_demo.py` 录制实际操作，`scripts/build_demo.py` 编码并用 ffprobe 验证时长、分辨率和编码，生成 SHA256。录制要求服务已启动、Playwright、Chrome 和 Playwright 配套 FFmpeg 可用；导出另需系统 FFmpeg。

视频展示创建、人工核对、修改阈值、未触发解释、触发解释、冷却去重、新公告保留、来源故障与恢复、规则历史和站内提醒。进程强制终止验证作为独立可复现测试记录提交，视频中的来源恢复不能替代该测试。
'''
    (ROOT/'DEMO_SCRIPT.md').write_text(script)
    print(json.dumps(metadata,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    OUT.mkdir(exist_ok=True)
    with (OUT/'demo-build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        main()
