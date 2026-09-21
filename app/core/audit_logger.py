"""Commit checkpoints, decision evidence and durable alerts in one transaction."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import sqlite3
from datetime import datetime, timezone


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


class Store:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / 'radar.sqlite3'
        with self.connect() as db:
            db.executescript('''
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,owner TEXT NOT NULL,body TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS tasks_owner ON tasks(owner);
              CREATE TABLE IF NOT EXISTS audits(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT NOT NULL,body TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS audits_task ON audits(task_id,id);
              CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT NOT NULL,owner TEXT NOT NULL,fingerprint TEXT NOT NULL,body TEXT NOT NULL,UNIQUE(task_id,fingerprint));
              CREATE TABLE IF NOT EXISTS seen(task_id TEXT NOT NULL,fingerprint TEXT NOT NULL,PRIMARY KEY(task_id,fingerprint));
              CREATE TABLE IF NOT EXISTS versions(task_id TEXT NOT NULL,version INTEGER NOT NULL,body TEXT NOT NULL,PRIMARY KEY(task_id,version));
              CREATE TABLE IF NOT EXISTS compilations(id TEXT PRIMARY KEY,owner TEXT NOT NULL,body TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS creation_requests(owner TEXT NOT NULL,request_key TEXT NOT NULL,payload_hash TEXT NOT NULL,task_id TEXT NOT NULL,PRIMARY KEY(owner,request_key));
              CREATE TABLE IF NOT EXISTS alert_receipts(alert_id INTEGER PRIMARY KEY,read_at TEXT,feedback TEXT,feedback_at TEXT);
              CREATE INDEX IF NOT EXISTS alerts_owner_id ON alerts(owner,id);
              CREATE TABLE IF NOT EXISTS product_events(id INTEGER PRIMARY KEY AUTOINCREMENT,owner TEXT NOT NULL,name TEXT NOT NULL,mode TEXT NOT NULL,recorded_at TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS product_events_owner ON product_events(owner,recorded_at);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute('PRAGMA synchronous=FULL')
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def tasks(self, owner=None):
        with self.connect() as db:
            rows = db.execute('SELECT body FROM tasks' + (' WHERE owner=?' if owner else ''), (owner,) if owner else ()).fetchall()
            return [json.loads(r['body']) for r in rows]

    def task(self, task_id, owner=None):
        with self.connect() as db:
            row = db.execute('SELECT body FROM tasks WHERE id=?' + (' AND owner=?' if owner else ''), (task_id, owner) if owner else (task_id,)).fetchone()
            return json.loads(row['body']) if row else None

    def save(self, task, audit=None, alerts=None, fingerprints=None, version=None, creation_request=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO tasks VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body', (task['id'], task['owner'], dumps(task)))
            if audit:
                audit.setdefault('recorded_at', datetime.now(timezone.utc).isoformat())
                audit['spec_hash'] = hashlib.sha256(dumps(task['spec']).encode()).hexdigest()[:16]
                db.execute('INSERT INTO audits(task_id,body) VALUES(?,?)', (task['id'], dumps(audit)))
            for alert in alerts or []:
                alert.setdefault('recorded_at', datetime.now(timezone.utc).isoformat())
                db.execute('INSERT OR IGNORE INTO alerts(task_id,owner,fingerprint,body) VALUES(?,?,?,?)', (task['id'], task['owner'], alert['fingerprint'], dumps(alert)))
            for fingerprint in fingerprints or []:
                db.execute('INSERT OR IGNORE INTO seen VALUES(?,?)', (task['id'], fingerprint))
            if version:
                db.execute('INSERT INTO versions VALUES(?,?,?)', (task['id'], task['spec']['version'], dumps(version)))
                if version['version'] == 1:
                    db.execute('INSERT INTO product_events(owner,name,mode,recorded_at) VALUES(?,?,?,?)',
                               (task['owner'],'task_created',task['spec']['data_mode'],datetime.now(timezone.utc).isoformat()))
            if creation_request:
                key, payload_hash = creation_request
                db.execute('INSERT INTO creation_requests VALUES(?,?,?,?)',(task['owner'],key,payload_hash,task['id']))

    def creation_request(self, owner, key):
        with self.connect() as db:
            row = db.execute('SELECT payload_hash,task_id FROM creation_requests WHERE owner=? AND request_key=?',(owner,key)).fetchone()
            return dict(row) if row else None

    def seen(self, task_id):
        with self.connect() as db:
            return {row[0] for row in db.execute('SELECT fingerprint FROM seen WHERE task_id=?', (task_id,))}

    def audits(self, task_id, limit=100, before_id=None):
        with self.connect() as db:
            clause='task_id=?'; args=[task_id]
            if before_id is not None:
                clause+=' AND id<?'; args.append(before_id)
            args.append(limit)
            return [dict(json.loads(r['body']), audit_id=r['id']) for r in db.execute('SELECT * FROM audits WHERE '+clause+' ORDER BY id DESC LIMIT ?', args)]

    def audit_count(self, task_id):
        with self.connect() as db:
            return db.execute('SELECT COUNT(*) FROM audits WHERE task_id=?',(task_id,)).fetchone()[0]

    def compilation(self, ident, owner):
        with self.connect() as db:
            row=db.execute('SELECT body FROM compilations WHERE id=? AND owner=?',(ident,owner)).fetchone()
            return json.loads(row[0]) if row else None

    def alerts(self, owner, limit=100, before_id=None, unread_only=False):
        with self.connect() as db:
            clause='a.owner=?'; args=[owner]
            if before_id is not None:
                clause+=' AND a.id<?'; args.append(before_id)
            if unread_only:
                clause+=' AND r.read_at IS NULL'
            args.append(limit)
            return [dict(json.loads(r['body']),id=r['id'],read_at=r['read_at'],feedback=r['feedback']) for r in db.execute(
                'SELECT a.*,r.read_at,r.feedback FROM alerts a LEFT JOIN alert_receipts r ON r.alert_id=a.id WHERE '+clause+' ORDER BY a.id DESC LIMIT ?',args)]

    def alert_counts(self, owner):
        with self.connect() as db:
            row=db.execute('SELECT COUNT(*) total,SUM(CASE WHEN r.read_at IS NULL THEN 1 ELSE 0 END) unread FROM alerts a LEFT JOIN alert_receipts r ON r.alert_id=a.id WHERE a.owner=?',(owner,)).fetchone()
            return {'total':row['total'],'unread':row['unread'] or 0}

    def alert(self, owner, alert_id):
        with self.connect() as db:
            row=db.execute('SELECT a.*,r.read_at,r.feedback FROM alerts a LEFT JOIN alert_receipts r ON r.alert_id=a.id WHERE a.owner=? AND a.id=?',(owner,alert_id)).fetchone()
            if not row:
                raise KeyError('找不到这条提醒，或它不属于当前浏览器。')
            return dict(json.loads(row['body']),id=row['id'],read_at=row['read_at'],feedback=row['feedback'])

    def acknowledge_alert(self, owner, alert_id, feedback=None, set_feedback=False):
        now=datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM alerts WHERE owner=? AND id=?',(owner,alert_id)).fetchone():
                raise KeyError('找不到这条提醒，或它不属于当前浏览器。')
            db.execute('INSERT INTO alert_receipts(alert_id,read_at) VALUES(?,?) ON CONFLICT(alert_id) DO UPDATE SET read_at=COALESCE(alert_receipts.read_at,excluded.read_at)',(alert_id,now))
            if set_feedback:
                db.execute('UPDATE alert_receipts SET feedback=?,feedback_at=? WHERE alert_id=?',(feedback,now,alert_id))
        return self.alert(owner,alert_id)

    def record_product_event(self, owner, name, mode):
        with self.connect() as db:
            db.execute('INSERT INTO product_events(owner,name,mode,recorded_at) VALUES(?,?,?,?)',(owner,name,mode,datetime.now(timezone.utc).isoformat()))

    def versions(self, task_id):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT body FROM versions WHERE task_id=? ORDER BY version DESC', (task_id,))]

    def record_compilation(self, ident, owner, record):
        with self.connect() as db:
            db.execute('INSERT INTO compilations VALUES(?,?,?)', (ident, owner, dumps(record)))

    def compilations(self, owner):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT body FROM compilations WHERE owner=? ORDER BY rowid DESC LIMIT 50', (owner,))]

    def metadata(self, key, value=None):
        with self.connect() as db:
            if value is not None:
                db.execute('INSERT INTO metadata VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))
            row = db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            return row[0] if row else None
