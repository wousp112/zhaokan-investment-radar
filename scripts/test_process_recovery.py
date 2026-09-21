"""Actual SIGKILL/restart test against an isolated database and owned subprocess."""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import time

import httpx

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8011'


def start(env,log):
    process=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8011'],cwd=ROOT,env=env,stdout=log,stderr=log)
    for _ in range(100):
        if process.poll() is not None:
            log.flush()
            detail=Path(log.name).read_text()[-1500:]
            raise RuntimeError('Isolated test server exited before becoming healthy: '+detail)
        try:
            if httpx.get(BASE+'/api/health',timeout=0.5).status_code==200:
                return process
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    process.terminate();process.wait(timeout=10)
    raise RuntimeError('Isolated test server did not start')


def main():
    process=None
    with tempfile.TemporaryDirectory(prefix='radar-restart-') as directory:
        env=dict(os.environ,RADAR_DATA_DIR=directory,RADAR_AI_ENABLED='0',RADAR_ALLOW_LIVE='0')
        with open(Path(directory)/'server.log','w') as log, httpx.Client(base_url=BASE,timeout=10) as client:
            try:
                process=start(env,log)
                compiled=client.post('/api/tasks/parse',json={'prompt':'贵州茅台跌3%或出现业绩预告就提醒','use_ai':False}).json()
                task=client.post('/api/tasks/create',json={'task_spec':compiled['task_spec']}).json()
                tid=task['id']
                client.post('/api/simulate/inject',json={'task_id':tid,'scenario':'drop'}).raise_for_status()
                client.post('/api/simulate/inject',json={'task_id':tid,'scenario':'announcement'}).raise_for_status()
                before=client.get('/api/tasks/'+tid).json()
                assert before['state']['trigger_count']==1 and len(before['state']['pending_events'])==1
                process.kill();process.wait(timeout=10)
                process=start(env,log)
                after=client.get('/api/tasks/'+tid).json()
                assert after['state']['trigger_count']==1 and len(after['state']['pending_events'])==1
                duplicate=client.post('/api/simulate/inject',json={'task_id':tid,'scenario':'deeper'}).json()
                assert duplicate['state']['trigger_count']==1
                delivered=client.post('/api/simulate/inject',json={'task_id':tid,'scenario':'advance','advance_seconds':1860}).json()
                assert delivered['state']['trigger_count']==2 and not delivered['state']['pending_events']
                alerts=client.get('/api/alerts').json()['alerts']
                assert len([a for a in alerts if a['kind']=='condition'])==2
                history=client.get('/api/tasks/'+tid+'/audit-trail').json()['history']
                assert any(h['kind']=='recovery' for h in history)
                result={'checked_at':datetime.now(timezone.utc).isoformat(),'passed':True,'method':'真实独立服务进程SIGKILL后重新启动，使用同一SQLite目录',
                        'checks':['冷却状态保留','待提醒公告保留','已提醒价格不重复','冷却后公告正常送达','重启恢复审计可见'],
                        'before_trigger_count':1,'after_restart_trigger_count':1,'after_cooldown_trigger_count':2,
                        'scope':'一次本地进程强制终止测试；不覆盖断电、磁盘损坏、多节点故障或长期SLA。'}
                (ROOT/'artifacts/process-recovery.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
                print(json.dumps(result,ensure_ascii=False,indent=2))
            finally:
                if process and process.poll() is None:
                    process.terminate();process.wait(timeout=10)


main()
