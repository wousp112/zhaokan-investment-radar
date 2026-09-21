from pathlib import Path
import sqlite3

import pytest

from scripts.backup_data import backup_and_verify


def test_online_backup_restores_a_wal_database_without_replacing_it(tmp_path):
    source=tmp_path/'live.sqlite3';target=tmp_path/'backup.sqlite3'
    with sqlite3.connect(source) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE evidence(id INTEGER PRIMARY KEY,body TEXT)')
        db.execute('INSERT INTO evidence(body) VALUES(?)',('original',));db.commit()
        report=backup_and_verify(source,target)
        assert report['restored_in_isolation'] is True
        assert report['live_database_replaced'] is False
        assert report['snapshot']['row_counts']=={'evidence':1}
        db.execute('INSERT INTO evidence(body) VALUES(?)',('after backup',));db.commit()
        assert db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0]==2
    with sqlite3.connect(target) as backup:
        assert backup.execute('SELECT COUNT(*) FROM evidence').fetchone()[0]==1
    assert target.stat().st_mode & 0o777 == 0o600


def test_existing_backup_is_never_overwritten(tmp_path):
    source=tmp_path/'source.sqlite3';target=tmp_path/'existing.sqlite3'
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE records(id INTEGER)')
    target.write_bytes(b'keep this backup')
    with pytest.raises(FileExistsError):
        backup_and_verify(source,target)
    assert target.read_bytes()==b'keep this backup'
    with pytest.raises(ValueError):
        backup_and_verify(source,source)
