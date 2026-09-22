"""Install only the verified movie and matching sidecars into this app's static directory."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'artifacts/cinematic-v1.2'
TARGET=ROOT/'app/web/static'


def main():
    report=json.loads((SOURCE/'verification.json').read_text())
    video=SOURCE/'demo-v1.2.mp4'
    digest=hashlib.sha256(video.read_bytes()).hexdigest()
    if digest != report['sha256'] or not report.get('technical_checks_passed'):
        raise RuntimeError('Validate the final movie before installing it.')
    metadata=json.loads((SOURCE/'demo-video.json').read_text())
    if (not report.get('product_stylesheet_matches') or
            metadata.get('presentation_theme',{}).get('source_sha256') !=
            hashlib.sha256((TARGET/'style.css').read_bytes()).hexdigest()):
        raise RuntimeError('The movie must match the current product stylesheet before installation.')
    mapping={'demo-v1.2.mp4':'demo-v1.2.mp4','poster.jpg':'demo-poster.jpg',
             'chapters.json':'demo-chapters.json','demo.srt':'demo-subtitles.srt',
             'demo.vtt':'demo-subtitles.vtt'}
    installed=[]
    for source,name in mapping.items():
        final=TARGET/name;staging=final.with_name(final.name+'.installing')
        shutil.copyfile(SOURCE/source,staging)
        staging.replace(final)
        installed.append({'file':name,'bytes':final.stat().st_size,
                          'sha256':hashlib.sha256(final.read_bytes()).hexdigest()})
    # Preserve the original v1.1 file in artifacts; retain the established URL.
    alias=TARGET/'demo.mp4';temp=TARGET/'demo.mp4.installing'
    shutil.copyfile(video,temp);temp.replace(alias)
    print(json.dumps({'installed':installed,'legacy_url_alias_matches':hashlib.sha256(alias.read_bytes()).hexdigest()==digest},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
