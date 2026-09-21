"""Package the committed public source and verified demo for the exam's 30 MB limit.

No network requests, uploads, or exam submission occur in this script.
Untracked files, local credentials, databases and the Python environment are excluded.
"""
from datetime import datetime, timezone
import hashlib
from html import escape
import io
import json
from pathlib import Path
import subprocess
from urllib.parse import urlparse
import zipfile

ROOT = Path(__file__).resolve().parents[1]
LIMIT_BYTES = 30_000_000
VIDEO_PATH = 'artifacts/professional-review/demo-v1.1.mp4'


def git(*args: str) -> bytes:
    return subprocess.check_output(['git', *args], cwd=ROOT)


def main() -> None:
    if git('status', '--porcelain', '--untracked-files=no').strip():
        raise RuntimeError('Commit tracked changes before building a submission package.')
    revision = git('rev-parse', 'HEAD').decode().strip()
    product_url = (ROOT/'CURRENT_PRODUCT_URL.txt').read_text().strip()
    if urlparse(product_url).scheme != 'https' or not urlparse(product_url).hostname:
        raise ValueError('CURRENT_PRODUCT_URL.txt must contain the current HTTPS product URL.')
    for name in ('README.md', 'SUBMISSION.md', 'DEMO_SCRIPT.md'):
        if product_url not in (ROOT/name).read_text():
            raise ValueError(f'{name} does not contain the current product URL.')
    video = (ROOT/VIDEO_PATH).read_bytes()
    video_info = json.loads((ROOT/'artifacts/professional-review/demo-video.json').read_text())
    video_sha = hashlib.sha256(video).hexdigest()
    if video_sha != video_info['sha256']:
        raise ValueError('Video differs from its verified metadata.')
    if not 60 <= float(video_info['duration_seconds']) <= 180:
        raise ValueError('Video must be 60–180 seconds.')
    source = zipfile.ZipFile(io.BytesIO(git('archive', '--format=zip', 'HEAD')))
    contents: dict[str, bytes] = {}
    for item in source.infolist():
        if item.is_dir():
            continue
        path = Path(item.filename)
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('Unsafe archive path.')
        if set(path.parts) & {'.git', '.venv', 'data', 'secrets'} or (
            path.name.startswith('.env') and path.name != '.env.example'
        ):
            raise ValueError(f'Local-only file was tracked: {item.filename}')
        contents[item.filename] = source.read(item)
    source.close()
    if VIDEO_PATH in contents:
        raise ValueError('Video is already tracked; inspect the archive before packaging.')
    contents[VIDEO_PATH] = video
    landing = f'''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>照看 · 同花顺AIME笔试提交</title>
<style>body{{font:17px/1.7 system-ui,sans-serif;max-width:860px;margin:48px auto;padding:0 24px}}a{{display:inline-block;margin:0 24px 12px 0}}video{{width:100%;max-height:680px}}small{{display:block;margin-top:24px}}</style>
<h1>照看 · 投资监控与风险雷达</h1>
<p>把关注条件写下来，核对后开启提醒；每次触发和未触发都有检查记录。</p>
<p><a href="{escape(product_url, quote=True)}">打开交互产品</a><a href="https://github.com/wousp112/zhaokan-investment-radar">查看源码仓库</a><a href="SUBMISSION.md">完整提交说明</a></p>
<h2>产品演示</h2>
<p>约96秒，含简体中文字幕。画面取自实际操作截图分镜，行情使用模拟数据。下方视频随提交包提供，可离线播放。</p>
<video controls preload="metadata" src="{VIDEO_PATH}"></video>
<p>源码和README位于本目录。测试结果与AI使用记录见TESTING_AND_EVAL.md和AI_USAGE_AND_VERIFICATION.md。</p>
<small>公开体验依赖本机及临时通道。当前仅提供站内通知，不发送短信或手机推送。具体数据范围和未完成事项见README。</small>
<small>源代码版本：{revision}</small></html>'''
    contents['00_打开这里.html'] = landing.encode('utf-8')
    manifest = {
        'created_at': datetime.now(timezone.utc).isoformat(),
        'source_revision': revision, 'product_url': product_url,
        'video_sha256': video_sha, 'limit_bytes': LIMIT_BYTES,
        'source_scope': 'git archive HEAD plus verified video and offline entry page',
        'files': [{'path': name, 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
                  for name, body in sorted(contents.items())],
    }
    contents['SUBMISSION_MANIFEST.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2)+'\n').encode()
    out = ROOT/'artifacts/submission'
    out.mkdir(parents=True, exist_ok=True)
    target = out/f'zhaokan-AIME-{revision[:7]}.zip'
    if target.exists():
        raise FileExistsError(f'An existing submission is preserved: {target}')
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, body in sorted(contents.items()):
            archive.writestr(name, body)
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None or len(archive.namelist()) != len(contents):
            raise RuntimeError('ZIP integrity verification failed.')
        for row in manifest['files']:
            if hashlib.sha256(archive.read(row['path'])).hexdigest() != row['sha256']:
                raise RuntimeError('A packaged file failed its SHA256 check.')
    if target.stat().st_size >= LIMIT_BYTES:
        raise RuntimeError('Package exceeds the exam upload limit; do not upload it.')
    result = {
        'file': str(target), 'size_bytes': target.stat().st_size,
        'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
        'source_revision': revision, 'file_count': len(contents),
        'integrity_verified': True, 'within_30mb': True,
        'uploaded': False, 'exam_submitted': False,
    }
    target.with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
