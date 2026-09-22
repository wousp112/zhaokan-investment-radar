"""Verify the actual encoded movie and its caption/chapter contract before release."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'artifacts/cinematic-v1.2'


def validate_contract(probe: dict, chapters: list, captions: list) -> dict:
    """Consume actual ffprobe streams, never a claimed 'has_audio' flag."""
    streams = probe.get('streams', [])
    videos = [s for s in streams if s.get('codec_type') == 'video']
    audio = [s for s in streams if s.get('codec_type') == 'audio']
    if len(videos) != 1 or len(audio) != 1:
        raise ValueError('Delivery requires one video stream and one narration stream.')
    v, a = videos[0], audio[0]
    duration = float(probe['format']['duration'])
    if not math.isfinite(duration) or not 60 <= duration <= 180:
        raise ValueError('Duration is outside the 60–180 second submission limit.')
    if (v.get('width'), v.get('height')) != (1920, 1080) or v.get('codec_name') != 'h264':
        raise ValueError('Expected a fixed 1920×1080 H.264 picture.')
    if v.get('r_frame_rate') != '30/1' or v.get('pix_fmt') != 'yuv420p':
        raise ValueError('Expected constant 30 fps and broadly compatible pixel format.')
    if a.get('codec_name') != 'aac' or int(a.get('sample_rate', 0)) != 48000:
        raise ValueError('Expected 48 kHz AAC narration.')
    if not chapters or not captions:
        raise ValueError('Chapters and captions must be present.')
    previous = 0.
    for c in chapters:
        start, end = float(c['start']), float(c['end'])
        if not math.isfinite(start+end) or abs(start-previous) > .04 or end <= start or end > duration+.04:
            raise ValueError('Chapter order or coverage is invalid.')
        previous = end
    if abs(previous-duration) > .1:
        raise ValueError('Chapters do not cover the complete movie.')
    previous = 0.
    for c in captions:
        start, end = float(c['start']), float(c['end'])
        if not math.isfinite(start+end) or start < previous-.001 or end <= start or end > duration+.04:
            raise ValueError('Caption order or timing is invalid.')
        if not str(c.get('text','')).strip():
            raise ValueError('Empty caption.')
        previous = end
    return {'duration_seconds':duration, 'video_codec':v['codec_name'],
            'audio_codec':a['codec_name'], 'width':v['width'], 'height':v['height'],
            'fps':30, 'caption_count':len(captions), 'chapter_count':len(chapters)}


def parse_vtt(path: Path) -> list:
    def seconds(text):
        h,m,s=text.split(':')
        return int(h)*3600+int(m)*60+float(s)
    rows=[]
    for block in path.read_text().split('\n\n'):
        lines=block.splitlines()
        if lines and ' --> ' in lines[0]:
            start,end=lines[0].split(' --> ')
            rows.append({'start':seconds(start),'end':seconds(end),'text':'\n'.join(lines[1:])})
    return rows


def main():
    video=ART/'demo-v1.2.mp4'
    metadata=json.loads((ART/'demo-video.json').read_text())
    actual_sha=hashlib.sha256(video.read_bytes()).hexdigest()
    if actual_sha != metadata['sha256']:
        raise ValueError('Movie differs from its build record.')
    actual=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(video)]))
    chapters=json.loads((ART/'chapters.json').read_text())
    captions=parse_vtt(ART/'demo.vtt')
    report=validate_contract(actual,chapters,captions)
    expected=[s for c in chapters for s in c['sentences']]
    if [r['text'] for r in captions] != expected:
        raise ValueError('Narration script and delivered captions disagree.')
    for row in metadata['sources']:
        if hashlib.sha256((ART/row['file']).read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('A source capture has changed.')
    volume=subprocess.run(['ffmpeg','-hide_banner','-nostats','-i',str(video),
        '-af','loudnorm=I=-16:TP=-1.5:LRA=7:print_format=json','-vn','-f','null','-'],
        check=True,capture_output=True,text=True,timeout=180)
    blocks=re.findall(r'\{\s*"input_i"[\s\S]*?\}',volume.stderr)
    if not blocks:
        raise ValueError('No measured narration loudness was returned.')
    loudness=json.loads(blocks[-1])
    integrated,peak=float(loudness['input_i']),float(loudness['input_tp'])
    if not math.isfinite(integrated+peak) or not -19<=integrated<=-13 or peak>-.8:
        raise ValueError('Narration level or true peak is outside the delivery gate.')
    decode=subprocess.run(['ffmpeg','-v','error','-i',str(video),'-f','null','-'],
                          capture_output=True,text=True,timeout=180)
    if decode.returncode or decode.stderr.strip():
        raise ValueError('Movie did not decode cleanly: '+decode.stderr[-1000:])
    report.update({'verified_at':datetime.now(timezone.utc).isoformat(),'sha256':actual_sha,
                   'size_bytes':video.stat().st_size,'decode_verified':True,'source_hashes_verified':True,
                   'narration_lufs':integrated,'true_peak_dbtp':peak,
                   'script_caption_match':True,'measured_click_count':metadata['measured_click_count'],
                   'technical_checks_passed':True,
                   'scope':'Encoded media, captions, source hashes and audio levels. Subjective voice quality requires listening.'})
    (ART/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
