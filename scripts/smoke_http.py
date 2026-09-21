"""Verify a running deployment using only the public HTTP contract and demo data."""
import argparse
from datetime import datetime, timezone
import http.cookiejar
import json
from pathlib import Path
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--output')
    args = parser.parse_args()
    base = args.url.rstrip('/')
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(path, method='GET', body=None):
        payload = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base+path, data=payload, method=method,
                                     headers={'Content-Type':'application/json'} if payload else {})
        with client.open(req, timeout=10) as response:
            return json.load(response)

    for attempt in range(40):
        try:
            health = request('/api/health')
            assert health['status'] == 'ok'
            break
        except (OSError, AssertionError):
            if attempt == 39:
                raise
            time.sleep(0.5)
    checks = ['服务健康接口正常']
    task = None
    try:
        parsed = request('/api/tasks/parse', 'POST', {'prompt':'贵州茅台跌3%或者发布新的业绩预告提醒我', 'use_ai':False})
        assert len(parsed['task_spec']['conditions']) == 2
        task = request('/api/tasks/create', 'POST', {'task_spec':parsed['task_spec'], 'activate':True})
        checked = request('/api/simulate/tick', 'POST', {'task_id':task['id']})
        assert checked['state']['trigger_count'] == 0
        checks.append('生成并确认规则，未满足时不提醒')
        for scenario in ('drop','deeper'):
            checked = request('/api/simulate/inject', 'POST', {'task_id':task['id'], 'scenario':scenario})
            assert checked['state']['trigger_count'] == 1
        checks.append('满足阈值后提醒，持续下跌不重复')
        for scenario in ('timeout','recover'):
            checked = request('/api/simulate/inject', 'POST', {'task_id':task['id'], 'scenario':scenario})
            assert checked['state']['status'] == ('DEGRADED' if scenario == 'timeout' else 'COOLING')
        checks.append('来源故障与恢复有明确状态')
        evidence = request('/api/tasks/'+task['id']+'/export')
        assert evidence['recent_audits'] and 'owner' not in evidence['task']
        checks.append('可导出当前会话的判断依据')
    finally:
        if task is not None:
            request('/api/tasks/'+task['id'], 'DELETE')
    report = {'checked_at':datetime.now(timezone.utc).isoformat(), 'url':base,
              'passed':len(checks), 'checks':checks,
              'scope':'通过HTTP验证单实例与模拟数据主链路；不调用外部模型或金融数据。'}
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
