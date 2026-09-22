"""Render the checked-in narration with the installed macOS voice, offline.

Each caption has its own audio file, so caption boundaries come from measured
audio duration. No account, credential, source screenshot or text is uploaded.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'artifacts/cinematic-v1.2'


def probe(path):
    return json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_entries',
        'format=duration,size:stream=sample_rate,channels', '-of', 'json', str(path)]))


def render_sentence(item):
    chapter, index, text, voice, rate = item
    digest = hashlib.sha256(f'{voice}|{rate}|{text}'.encode()).hexdigest()
    target = ART / 'voice' / f'{chapter}-{index:02d}.aiff'
    marker = target.with_suffix('.sha256')
    if not (target.exists() and marker.exists() and marker.read_text() == digest):
        staging = target.with_name(target.stem + '.part.aiff')
        subprocess.run(['say', '-v', voice, '-r', str(rate), '-o', str(staging), text],
                       check=True, timeout=90)
        info = probe(staging)
        duration = float(info.get('format', {}).get('duration', 0))
        if not math.isfinite(duration) or duration < .3 or staging.stat().st_size < 8000:
            raise RuntimeError(f'No usable speech samples generated for {chapter}/{index}.')
        staging.replace(target)
        marker.write_text(digest)
    info = probe(target)
    return {'chapter': chapter, 'index': index, 'text': text,
            'file': str(target.relative_to(ROOT)),
            'duration': float(info['format']['duration']),
            'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}


def main():
    if not shutil.which('say') or not shutil.which('ffprobe'):
        raise RuntimeError('This narration build requires macOS say and FFmpeg.')
    story = json.loads((ROOT / 'scripts/cinematic_story.json').read_text())
    (ART / 'voice').mkdir(parents=True, exist_ok=True)
    items = [(c['id'], i, text, story['voice'], story['voice_rate'])
             for c in story['chapters'] for i, text in enumerate(c['sentences'])]
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(render_sentence, items))
    metadata = {'provider': 'macOS offline speech synthesis', 'voice': story['voice'],
                'synthetic_voice': True, 'text_sent_off_device': False,
                'sentences': rows, 'speech_seconds': sum(r['duration'] for r in rows)}
    (ART / 'voice-manifest.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'sentences': len(rows), 'speech_seconds': round(metadata['speech_seconds'], 2),
                      'voice': story['voice'], 'offline': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()
