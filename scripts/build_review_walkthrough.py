"""Build an explicitly captioned screenshot walkthrough from actual UI captures.

No browser is driven here. Captures come from the native browser's verified
interaction steps. This is an edited sequence, not a continuous screen recording.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFont, ImageStat

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'artifacts/professional-review'
OUT=ART/'walkthrough-build'
SIZE=(1440,1160)
STEPS=[
 ('14-natural-language.png','写下关注条件','宁德时代下跌达到3%，或发布业绩预告。AI可选，发送范围会说明。'),
 ('15-ai-review.png','核对后再开启','公司、阈值和结束时间都可以修改。当前只是草稿，确认前不会检查。'),
 ('03-manual-current.png','也能直接选择条件','不确定怎么写时，可直接选择公司与条件，再核对后开启。'),
 ('04-no-trigger.png','未触发，也给依据','模拟价98.8元，昨收100元，下跌1.2%。未达到3%，也未发现新公告。'),
 ('05-triggered.png','条件满足，保存通知','模拟下跌3.8%，实际生成一条提醒；继续下跌没有重复生成通知。'),
 ('06-announcement-held.png','间隔内保留新公告','检查继续进行。新公告先保留，推进31分钟后再判断并补发。'),
 ('07-source-timeout.png','来源异常时说清影响','行情超时后停止用该价格判断，保存异常通知；恢复后另存恢复通知。'),
 ('08-inbox.png','结果集中在提醒记录','条件满足、数据异常与恢复分开保存。目前通知在本网站查看。'),
 ('11-alert-feedback.png','用户能反馈，也能撤回','打开后未读数减少。反馈写入服务器，不会改变股票监控条件。'),
 ('12-frozen-evidence.png','修改后保留原始证据','当前阈值改为4%后，原通知仍记录第1版3%条件和96.2元的触发价格。'),
 ('09-operating-report.png','运行结果有实际统计','检查、通知打开和反馈分别统计；演示时钟的推进不充当实际运行时长。'),
 ('10-no-live-samples.png','区分演示成绩与真实运行','真实记录无样本时不显示成功率。常驻托管和外部通知仍需补齐。'),
]


def font(size):
    candidates=[os.getenv('RADAR_CAPTION_FONT',''),'/System/Library/Fonts/STHeiti Medium.ttc',
                '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']
    for name in candidates:
        if name and Path(name).is_file():return ImageFont.truetype(name,size)
    raise RuntimeError('Set RADAR_CAPTION_FONT to an installed Chinese font. Font files are not bundled.')


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    title_font,body_font,note_font=font(30),font(23),font(16)
    sources=[];lines=[]
    for i,(name,title,caption) in enumerate(STEPS,1):
        source=ART/name
        with Image.open(source) as image:
            screenshot=image.convert('RGB')
        if screenshot.width<1000 or screenshot.height<700:raise ValueError('Expected a desktop capture: '+name)
        if max(ImageStat.Stat(screenshot).stddev)<5:raise ValueError('Capture may be blank: '+name)
        # Preserve the full screenshot. Captions are placed outside its pixels.
        screenshot.thumbnail((1440,1000),Image.Resampling.LANCZOS)
        frame=Image.new('RGB',SIZE,'white')
        frame.paste(screenshot,((1440-screenshot.width)//2,(1000-screenshot.height)//2))
        draw=ImageDraw.Draw(frame)
        draw.rectangle((0,1000,1440,1160),fill='#202127')
        draw.text((38,1015),f'{i:02d}  {title}',font=title_font,fill='white')
        if draw.textbbox((0,0),caption,font=body_font)[2]>1360:raise ValueError('Caption too wide: '+title)
        draw.text((38,1062),caption,font=body_font,fill='#eeeeef')
        draw.text((38,1110),'照看  ·  本轮实际操作截图分镜  ·  模拟数据  ·  不以视频时长衡量系统性能',font=note_font,fill='#c9c9ce')
        path=OUT/f'{i:02d}.png';frame.save(path)
        lines.extend([f"file '{path.name}'",'duration 8'])
        sources.append({'source':str(source.relative_to(ROOT)),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                        'at_seconds':(i-1)*8,'duration_seconds':8,'title':title,'caption':caption})
    lines.append(f"file '{len(STEPS):02d}.png'")
    (OUT/'frames.ffconcat').write_text('ffconcat version 1.0\n'+'\n'.join(lines)+'\n')
    target=ART/'demo-v1.1.mp4'
    subprocess.run(['ffmpeg','-y','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i',str(OUT/'frames.ffconcat'),
                    '-t',str(len(STEPS)*8),'-r','30','-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p',
                    '-movflags','+faststart','-an',str(target)],check=True)
    details=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries',
        'format=duration,size:stream=codec_name,width,height','-of','json',str(target)],text=True))
    duration=float(details['format']['duration']);stream=details['streams'][0]
    if not 60<=duration<=180 or (stream['width'],stream['height'])!=SIZE or stream['codec_name']!='h264':
        raise RuntimeError('Delivery constraints failed: '+str(details))
    # Decoding the complete file catches truncated/corrupt encodes.
    subprocess.run(['ffmpeg','-v','error','-i',str(target),'-f','null','-'],check=True)
    shutil.copy2(target,ROOT/'app/web/static/demo.mp4')
    metadata={'recorded_at':datetime.now(timezone.utc).isoformat(),'file':str(target.relative_to(ROOT)),
        'format':'captioned screenshots from separate actual interaction steps','duration_seconds':duration,
        'width':stream['width'],'height':stream['height'],'codec':stream['codec_name'],
        'size_bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
        'source_mode':'simulated financial data','audio':'none; simplified Chinese captions',
        'decode_verified':True,'visual_review':'Native image-view transport unavailable; dimensions and caption bounds checked. Human playback review still required.',
        'ui_build_sha256':'a91cb8c3cd90cc05e8a6bb0ea53084202397ef4a47d4c237118517fdb147e256',
        'chapters':sources}
    (ART/'demo-video.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in metadata.items() if k!='chapters'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
