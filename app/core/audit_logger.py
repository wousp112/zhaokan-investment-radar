"""Commit checkpoints, decision evidence and durable alerts in one transaction."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import sqlite3


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

    def save(self, task, audit=None, alerts=None, fingerprints=None, version=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO tasks VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body', (task['id'], task['owner'], dumps(task)))
            if audit:
                audit['spec_hash'] = hashlib.sha256(dumps(task['spec']).encode()).hexdigest()[:16]
                db.execute('INSERT INTO audits(task_id,body) VALUES(?,?)', (task['id'], dumps(audit)))
            for alert in alerts or []:
                db.execute('INSERT OR IGNORE INTO alerts(task_id,owner,fingerprint,body) VALUES(?,?,?,?)', (task['id'], task['owner'], alert['fingerprint'], dumps(alert)))
            for fingerprint in fingerprints or []:
                db.execute('INSERT OR IGNORE INTO seen VALUES(?,?)', (task['id'], fingerprint))
            if version:
                db.execute('INSERT INTO versions VALUES(?,?,?)', (task['id'], task['spec']['version'], dumps(version)))

    def seen(self, task_id):
        with self.connect() as db:
            return {row[0] for row in db.execute('SELECT fingerprint FROM seen WHERE task_id=?', (task_id,))}

    def audits(self, task_id, limit=100):
        with self.connect() as db:
            return [dict(json.loads(r['body']), audit_id=r['id']) for r in db.execute('SELECT * FROM audits WHERE task_id=? ORDER BY id DESC LIMIT ?', (task_id, limit))]

    def alerts(self, owner, limit=100):
        with self.connect() as db:
            return [dict(json.loads(r['body']), id=r['id']) for r in db.execute('SELECT * FROM alerts WHERE owner=? ORDER BY id DESC LIMIT ?', (owner, limit))]

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
