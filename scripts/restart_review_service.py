"""Restart this workspace's local review server without touching other apps."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PORT = 8000
DATA = ROOT/'data'


def main():
    found = subprocess.run(['lsof','-t','-iTCP:8000','-sTCP:LISTEN'],
                           capture_output=True,text=True,check=False)
    pids = set(found.stdout.split())
    if len(pids) > 1:
        raise RuntimeError('Multiple listeners found; no process was stopped.')
    if pids:
        pid = int(pids.pop())
        command = subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True)
        cwd = subprocess.check_output(['lsof','-a','-p',str(pid),'-d','cwd','-Fn'],text=True)
        if '-m uvicorn app.main:app' not in command or '\nn'+str(ROOT)+'\n' not in '\n'+cwd:
            raise RuntimeError('Port 8000 belongs to another app; no process was stopped.')
        os.kill(pid,signal.SIGTERM)
        for _ in range(100):
            try:
                os.kill(pid,0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError('Previous review server did not exit gracefully.')
    DATA.mkdir(exist_ok=True)
    env = dict(os.environ,RADAR_SECURE_COOKIE='1',RADAR_DATA_DIR=str(DATA))
    with (DATA/'review-server.log').open('a') as log:
        process = subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app',
            '--host','127.0.0.1','--port',str(PORT),'--workers','1','--no-access-log'],
            cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError('Review server failed: '+(DATA/'review-server.log').read_text()[-1500:])
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/api/health',timeout=1) as response:
                health = json.load(response)
            result = {'pid':process.pid,'base_url':f'http://127.0.0.1:{PORT}',
                      'secure_cookie':True,'health':health}
            (DATA/'review-service.json').write_text(json.dumps(result,indent=2))
            print(json.dumps(result,ensure_ascii=False))
            return
        except OSError:
            time.sleep(0.1)
    process.terminate()
    process.wait(timeout=10)
    raise RuntimeError('Review server did not become healthy.')


if __name__ == '__main__':
    main()
