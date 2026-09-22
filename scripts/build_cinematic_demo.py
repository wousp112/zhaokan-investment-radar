"""Build a narrated product walkthrough from verified UI captures.

UI pixels remain source-backed. Cursor movement, click rings, camera motion,
chapter labels and captions are editorial overlays. Discrete UI captures are
not represented as an uninterrupted screen recording. No network access.
"""
from __future__ import annotations

import argparse
import bisect
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'artifacts/cinematic-v1.2'
BUILD = ART / 'build'
WIDTH, HEIGHT, FPS = 1920, 1080, 30
UI_WIDTH, UI_HEIGHT = 1280, 720
PANEL = (192, 78, 1536, 864)
ACCENT = '#aaa4ff'
FONT_PATH = os.environ.get('RADAR_CAPTION_FONT', '/System/Library/Fonts/STHeiti Medium.ttc')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args: list[str]) -> bytes:
    return subprocess.check_output(args, stderr=subprocess.PIPE)


def probe(path: Path) -> dict:
    return json.loads(run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)]))


def ease(t: float) -> float:
    t = min(1., max(0., t))
    return t * t * (3. - 2. * t)


def mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


@lru_cache(maxsize=24)
def font(size: int):
    return ImageFont.truetype(FONT_PATH, size)


def wrap(text: str, size: int, width: int) -> list[str]:
    lines, line = [], ''
    f = font(size)
    for character in text:
        trial = line + character
        if line and f.getlength(trial) > width:
            lines.append(line)
            line = character
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


def normalized_source(name: str) -> Image.Image:
    path = ART / name
    with Image.open(path) as image:
        if abs(image.width / image.height - 16 / 9) > .012:
            raise ValueError(f'Unexpected capture aspect ratio: {name} {image.size}')
        return image.convert('RGB').resize((UI_WIDTH, UI_HEIGHT), Image.Resampling.LANCZOS)


def boxes(name: str) -> list[dict]:
    path = (ART / name).with_suffix('.boxes.json')
    return json.loads(path.read_text()) if path.exists() else []


def match_box(name: str, *, ident: str | None = None, label: str | None = None,
              contains: str | None = None, index: int = 0) -> tuple | None:
    candidates = [b for b in boxes(name) if
                  (ident and b.get('id') == ident) or
                  (label and b.get('label') == label) or
                  (contains and contains in str(b.get('label', '')))]
    if not candidates:
        return None
    if contains:
        candidates.sort(key=lambda b: b['rect']['width'] * b['rect']['height'])
    r = candidates[index]['rect']
    return (r['x'], r['y'], r['width'], r['height'])


def camera(rect: tuple | None, zoom: float = 1.45) -> tuple:
    """A bounded camera, never exposing pixels outside the captured viewport."""
    if rect is None:
        return (0., 0., 1280., 720.)
    x, y, w, h = rect
    cw, ch = 1280 / zoom, 720 / zoom
    left = max(0., min(1280 - cw, x + min(w, 600) / 2 - cw / 2))
    top = max(0., min(720 - ch, y + min(h, 380) / 2 - ch / 2))
    return (left, top, left + cw, top + ch)


def center(rect):
    return rect[0] + rect[2] / 2, rect[1] + rect[3] / 2


def map_point(point, crop):
    x, y, w, h = PANEL
    return (x + (point[0] - crop[0]) * w / (crop[2] - crop[0]),
            y + (point[1] - crop[1]) * h / (crop[3] - crop[1]))


def draw_cursor(draw, point, pulse=0.):
    x, y = point
    if pulse > 0:
        radius = 15 + 26 * pulse
        draw.ellipse((x-radius, y-radius, x+radius, y+radius),
                     outline=(172, 166, 255, int(220 * (1-pulse))), width=4)
    arrow = [(x,y), (x+4,y+31), (x+12,y+23), (x+21,y+40),
             (x+29,y+35), (x+19,y+19), (x+30,y+16)]
    draw.polygon([(a+2,b+2) for a,b in arrow], fill=(0,0,0,90))
    draw.polygon(arrow, fill=(250,250,255,255), outline=(31,32,48,255), width=2)


def timecode(seconds: float, comma: bool = False) -> str:
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02}:{m:02}:{s:02}{"," if comma else "."}{ms:03}'


def assemble(story, voices):
    by_chapter = {}
    for row in voices['sentences']:
        by_chapter.setdefault(row['chapter'], []).append(row)
    chapters, captions, position = [], [], 0.
    for source in story['chapters']:
        chapter = dict(source)
        cursor = .55
        chapter['captions'] = []
        for row in sorted(by_chapter[source['id']], key=lambda r: r['index']):
            entry = dict(row, start=position+cursor, end=position+cursor+row['duration'],
                         local_start=cursor, local_end=cursor+row['duration'])
            chapter['captions'].append(entry)
            captions.append(entry)
            cursor += row['duration'] + .20
        duration = math.ceil((cursor + .65) * FPS) / FPS
        chapter.update(start=position, end=position+duration, duration=duration)
        position += duration
        chapters.append(chapter)
    if not 60 <= position <= 180:
        raise ValueError(f'Walkthrough length must be 60–180 seconds; got {position}.')
    return chapters, captions, position


def prepare_sources(chapters):
    """Attach observed targets and optional short sequences of real captured frames."""
    capture = json.loads((ART / 'capture-selected/manifest.json').read_text())
    clips = {c['id']: c for c in capture['clips']}
    sources, measurements = {}, []
    # Events below were captured at the exact UI action; some final-state PNGs
    # were extracted from the last frame of those short recordings.
    event_map = {'review': '04-parse', 'activate': '06-activate', 'ai': '03-enable-ai'}
    for c in chapters:
        if c.get('graphic'):
            continue
        for name in (c['before'], c['after']):
            sources[name] = normalized_source(name)
        click = match_box(c['before'], ident=c.get('click_id'), label=c.get('click'),
                          index=c.get('click_index', 0))
        if click is None and c['id'] in event_map:
            ev = clips[event_map[c['id']]].get('events', [])
            if ev:
                r = ev[0]['rect']
                click = (r['x'],r['y'],r['width'],r['height'])
        # The result is shown as a cut when its preceding click target was not
        # captured. No unobserved click location is invented.
        c['click_rect'] = click
        c['click_time'] = min(2.3, c['captions'][0]['local_end'] * .55)
        if c['id'] == 'report':
            c['click_time'] = c['captions'][1]['local_start'] - .35
        result = match_box(c['after'], ident=c.get('focus_id'), contains=c.get('focus_text'))
        if result is None:
            for ident in ('alert-detail-dialog', 'rule-dialog', 'audit-dialog', 'report-dialog'):
                result = match_box(c['after'], ident=ident)
                if result:
                    break
        if c['id'] in ('trigger','dedup','pending','deliver','recovery') and result:
            result = (result[0], result[1]-34, min(620,result[2]), 170)
        if c['id'] == 'ai':
            result = (345, 440, 590, 230)
        if c['id'] == 'no-trigger':
            result = (715, 164, 545, 396)
        if c['id'] == 'review':
            result = (360, 134, 548, 310)
        if c['id'] == 'failure':
            result = match_box(c['after'], contains='行情暂不可用') or result
        c['focus_rect'] = result
        c['camera_before'] = camera(click, 1.42) if click else camera(result, 1.20)
        c['camera_after'] = camera(result, 1.48)
        c['transition_frames'] = []
        if c['id'] in event_map and c['id'] != 'review':
            raw = clips[event_map[c['id']]]
            event = raw['events'][0]['at'] if raw.get('events') else raw['started']
            c['transition_frames'] = [(max(0,f['at']-event),
                Image.open(ART/'capture-selected'/f['file']).convert('RGB').resize((1280,720), Image.Resampling.LANCZOS))
                for f in raw['frames'] if f['at'] >= event-.1]
        if c['id'] == 'version':
            sources['18-edited.png'] = normalized_source('18-edited.png')
            c['middle_rect'] = match_box('18-edited.png', contains='较昨收下跌达到4%')
        if c['id'] == 'feedback':
            sources['16-open.png'] = normalized_source('16-open.png')
            c['feedback_rect'] = match_box('16-open.png', label='有用')
        measurements.append({'id':c['id'],'before':c['before'],'after':c['after'],
                             'click_target':click,'focus_target':result,
                             'has_real_transition_frames':bool(c['transition_frames'])})
    return sources, measurements


def create_background():
    yy, xx = np.mgrid[:HEIGHT, :WIDTH]
    glow = np.exp(-(((xx-WIDTH*.62)/950)**2+((yy-HEIGHT*.28)/700)**2))
    array = np.empty((HEIGHT,WIDTH,3), dtype=np.uint8)
    for i, (base,gain) in enumerate(((14,15),(16,15),(25,28))):
        array[:,:,i] = base + gain*glow
    return Image.fromarray(array)


def graphics(frame, chapter, local, index):
    draw = ImageDraw.Draw(frame)
    draw.text((130, 115), '照看', font=font(33), fill=ACCENT)
    draw.text((130, 171), '投资监控与风险雷达', font=font(24), fill='#b4b5c6')
    title = chapter['title']
    for n, line in enumerate(wrap(title, 76, 1450)):
        draw.text((126, 283+n*99), line, font=font(76), fill='#f5f5fc')
    if chapter['id'] == 'intro':
        steps = [('写下条件','公司 · 变化 · 时间'),('核对后开启','修改条件，确认生效'),('持续检查','减少重复打扰'),('查看依据','触发与未触发')]
        for i,(label,detail) in enumerate(steps):
            reveal = ease((local-i*.28)/.8)
            x=130+i*426
            y=535+round(28*(1-reveal))
            draw.rounded_rectangle((x,y,x+390,y+196),radius=18,fill='#242635',outline='#424454',width=2)
            draw.text((x+24,y+22), f'0{i+1}',font=font(22),fill=ACCENT)
            draw.text((x+24,y+65),label,font=font(33),fill='#f3f3fa')
            draw.text((x+24,y+124),detail,font=font(21),fill='#b7b9ca')
        draw.text((132,804),'真实操作画面  /  模拟行情  /  中文合成旁白',font=font(23),fill='#9397af')
    else:
        draw.text((132,488),'写下关注条件，核对后开启。',font=font(40),fill='#d2d0f3')
        draw.text((132,570),'到「提醒记录」查看发生了什么。',font=font(40),fill='#d2d0f3')
        draw.rounded_rectangle((130,703,870,798),radius=16,fill='#35334c',outline='#6d688b',width=2)
        draw.text((160,730),'当前提供站内提醒，真实公告覆盖有限。',font=font(27),fill='#e6e3f6')


def compose_frame(bg, chapter, local, index, chapters, sources, total):
    frame = bg.copy()
    if chapter.get('graphic'):
        graphics(frame, chapter, local, index)
    else:
        click_time=chapter['click_time']
        rect=chapter['click_rect']
        motion=ease((local-(click_time+.15))/1.1)
        crop=mix(chapter['camera_before'],chapter['camera_after'],motion)
        image=sources[chapter['before']] if local<click_time+.10 else sources[chapter['after']]
        if chapter['transition_frames'] and click_time <= local <= click_time+.85:
            eligible=[im for at,im in chapter['transition_frames'] if at <= local-click_time]
            if eligible:
                image=eligible[-1]
        if chapter['id']=='ai' and local>click_time+.8:
            image=sources[chapter['after']]
        if chapter['id']=='version':
            second=chapter['captions'][1]['local_start']
            if local<1.75:
                image=sources[chapter['before']]
                crop=camera((360,160,540,250),1.4)
            elif local<second:
                image=sources['18-edited.png']
                crop=camera(chapter.get('middle_rect'),1.3)
            else:
                image=sources[chapter['after']]
                crop=camera((350,90,555,340),1.48)
        if chapter['id']=='feedback':
            second=chapter['captions'][1]['local_start']
            if local>=click_time and local<second:
                image=sources['16-open.png']
                crop=mix(chapter['camera_before'],camera((350,90,555,370),1.4),ease((local-click_time)/.8))
            elif local>=second:
                image=sources['16-open.png'] if local<second+.8 else sources[chapter['after']]
                crop=mix(camera((350,90,555,370),1.4),camera((350,390,555,270),1.42),ease((local-second)/.85))
        px,py,pw,ph=PANEL
        panel=image.transform((pw,ph),Image.Transform.EXTENT,crop,resample=Image.Resampling.BICUBIC)
        frame.paste(panel,(px,py))
        draw=ImageDraw.Draw(frame,'RGBA')
        draw.rounded_rectangle((px-2,py-2,px+pw+2,py+ph+2),radius=3,outline=(119,121,153,120),width=2)
        draw.text((192,24),f'{index+1:02d}  {chapter["title"]}',font=font(26),fill='#ececf6')
        label='模拟数据 · 实际操作画面'
        draw.text((1728-font(20).getlength(label),29),label,font=font(20),fill='#b9b4d4')
        if rect and local<click_time+1.05:
            point=center(rect)
            travel=ease((local-.15)/max(.3,click_time-.25))
            start=(max(15,point[0]-85),min(700,point[1]+65))
            cursor=map_point(mix(start,point,travel),crop)
            pulse=(local-click_time)/.65 if click_time<=local<click_time+.65 else 0
            if px<cursor[0]<px+pw-40 and py<cursor[1]<py+ph-42:
                draw_cursor(draw,cursor,pulse)
                if click_time-.45<local<click_time+.25:
                    left,top=map_point((rect[0],rect[1]),crop)
                    right,bottom=map_point((rect[0]+rect[2],rect[1]+rect[3]),crop)
                    draw.rounded_rectangle((left-4,top-4,right+4,bottom+4),radius=6,outline=(159,148,255,220),width=3)
        if chapter['id']=='feedback' and chapter.get('feedback_rect'):
            second=chapter['captions'][1]['local_start']
            if second+.8<local<second+1.55:
                point=map_point(center(chapter['feedback_rect']),crop)
                draw_cursor(draw,point,min(.98,(local-second-.8)/.75))
    draw=ImageDraw.Draw(frame)
    caption=next((row['text'] for row in chapter['captions']
                  if row['local_start']-.08 <= local <= row['local_end']+.15),'')
    lines=wrap(caption,32,1690)
    if len(lines)>2:
        raise ValueError('Caption exceeds two lines: '+caption)
    y=976 if len(lines)==2 else 995
    for line in lines:
        draw.text(((WIDTH-font(32).getlength(line))/2,y),line,font=font(32),fill='#f4f4fb')
        y+=40
    progress=(chapter['start']+local)/total
    draw.rectangle((0,1075,round(WIDTH*progress),1079),fill='#a79fff')
    for c in chapters[1:]:
        x=round(WIDTH*c['start']/total)
        draw.line((x,1074,x,1079),fill='#151721',width=3)
    return frame


def make_audio(chapters, total):
    rate=48000
    track=np.zeros(round(total*rate),dtype=np.float32)
    click_times=[]
    for c in chapters:
        for row in c['captions']:
            pcm=run(['ffmpeg','-v','error','-i',str(ROOT/row['file']),'-f','f32le','-ar',str(rate),'-ac','1','pipe:1'])
            samples=np.frombuffer(pcm,dtype='<f4')
            start=round(row['start']*rate)
            count=min(len(samples),len(track)-start)
            track[start:start+count]+=samples[:count]*.82
        if c.get('click_rect'):
            click_times.append(c['start']+c['click_time'])
    n=np.arange(round(.035*rate))/rate
    click=(np.sin(2*np.pi*1100*n)+.4*np.sin(2*np.pi*2300*n))*np.exp(-n*170)*.022
    for when in click_times:
        start=round(when*rate)
        track[start:start+len(click)]+=click[:len(track)-start]
    peak=float(np.max(np.abs(track)))
    if peak<=.001:
        raise ValueError('Narration is silent.')
    if peak>.94:
        track*=.94/peak
    path=BUILD/'mix.wav'
    with wave.open(str(path),'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(rate)
        output.writeframes((track*32767).astype('<i2').tobytes())
    return path,click_times,peak


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--proof-only',action='store_true')
    args=parser.parse_args()
    BUILD.mkdir(parents=True,exist_ok=True)
    (ART/'proof').mkdir(exist_ok=True)
    story=json.loads((ROOT/'scripts/cinematic_story.json').read_text())
    voices=json.loads((ART/'voice-manifest.json').read_text())
    for row in voices['sentences']:
        if sha(ROOT/row['file'])!=row['sha256']:
            raise ValueError('Narration differs from its verified source: '+row['file'])
    chapters,captions,total=assemble(story,voices)
    sources,measurements=prepare_sources(chapters)
    bg=create_background()
    for i,c in enumerate(chapters):
        at=min(c['duration']-.5,c['captions'][1]['local_start']+.7)
        frame=compose_frame(bg,c,at,i,chapters,sources,total)
        frame.save(ART/'proof'/f'{i+1:02d}-{c["id"]}.jpg',quality=91)
        if i==0:
            frame.save(ART/'poster.jpg',quality=94)
    (ART/'demo.vtt').write_text('WEBVTT\n\n'+'\n\n'.join(
        f'{timecode(r["start"])} --> {timecode(r["end"])}\n'+r['text'] for r in captions)+'\n')
    (ART/'demo.srt').write_text('\n\n'.join(
        f'{i+1}\n{timecode(r["start"],True)} --> {timecode(r["end"],True)}\n'+r['text']
        for i,r in enumerate(captions))+'\n')
    public_chapters=[{'id':c['id'],'title':c['title'],'start':round(c['start'],3),'end':round(c['end'],3),
                      'sentences':c['sentences']} for c in chapters]
    (ART/'chapters.json').write_text(json.dumps(public_chapters,ensure_ascii=False,indent=2)+'\n')
    (ART/'shot-measurements.json').write_text(json.dumps(measurements,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'duration':total,'chapters':len(chapters),'captions':len(captions),
                      'measured_clicks':sum(bool(m['click_target']) for m in measurements)},ensure_ascii=False),flush=True)
    if args.proof_only:
        return
    audio,click_times,peak=make_audio(chapters,total)
    staging=ART/'demo-v1.2.build.mp4'
    command=['ffmpeg','-y','-hide_banner','-loglevel','error','-f','rawvideo','-pix_fmt','rgb24',
             '-s',f'{WIDTH}x{HEIGHT}','-r',str(FPS),'-i','pipe:0','-i',str(audio),
             '-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p',
             '-af','loudnorm=I=-16:TP=-1.5:LRA=7','-c:a','aac','-b:a','128k','-ar','48000',
             '-movflags','+faststart','-t',f'{total:.6f}',str(staging)]
    with (BUILD/'encode.log').open('wb') as log:
        encoder=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=log)
        try:
            for i,c in enumerate(chapters):
                for number in range(round(c['duration']*FPS)):
                    encoder.stdin.write(compose_frame(bg,c,number/FPS,i,chapters,sources,total).tobytes())
                print(f'Rendered {i+1}/{len(chapters)} {c["id"]}',flush=True)
            encoder.stdin.close()
            if encoder.wait(timeout=180):
                raise RuntimeError((BUILD/'encode.log').read_text()[-2000:])
        except BaseException:
            encoder.terminate()
            encoder.wait(timeout=20)
            raise
    info=probe(staging)
    video=next(s for s in info['streams'] if s['codec_type']=='video')
    speech=next(s for s in info['streams'] if s['codec_type']=='audio')
    if (video['width'],video['height'])!=(WIDTH,HEIGHT) or speech['codec_name']!='aac':
        raise ValueError('Unexpected delivery streams.')
    subprocess.run(['ffmpeg','-v','error','-i',str(staging),'-f','null','-'],check=True,timeout=180)
    target=ART/'demo-v1.2.mp4'
    staging.replace(target)
    metadata={'created_at':datetime.now(timezone.utc).isoformat(),'file':str(target.relative_to(ROOT)),
              'duration_seconds':float(info['format']['duration']),'width':WIDTH,'height':HEIGHT,'fps':FPS,
              'video_codec':'h264','audio_codec':'aac','audio_sample_rate':48000,
              'size_bytes':target.stat().st_size,'sha256':sha(target),'decode_verified':True,
              'audio_source':{'engine':voices['provider'],'voice':voices['voice'],'synthetic':True,
                              'offline':True,'input_sample_peak':peak},
              'capture':'Sequential verified UI captures and short captured UI transitions; postproduction cursor, click rings and camera motion. Not an uninterrupted screen recording.',
              'source_viewport':[1280,720],'source_mode':'isolated simulated data',
              'captured_ui_sha256':json.loads((ART/'capture-selected/manifest.json').read_text())['captured_ui_sha256'],
              'caption_count':len(captions),'chapter_count':len(chapters),'measured_click_count':len(click_times),
              'click_times':click_times,'chapters':public_chapters,
              'sources':[{'file':name,'sha256':sha(ART/name),'original_size':list(Image.open(ART/name).size)}
                         for name in sorted(sources)],
              'subjective_voice_review':'Human listening review not performed by the build script.'}
    (ART/'demo-video.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in metadata.items() if k not in ('sources','chapters','click_times')},ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':
    main()
