"""Create an online SQLite snapshot, then restore it in isolation and verify it.

Never overwrites an existing destination or the running database.
Usage: python scripts/backup_data.py --source data/radar.sqlite3 --destination data/backups/radar-20260921.sqlite3
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile


def database_summary(path:Path):
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        integrity=db.execute('PRAGMA quick_check').fetchone()[0]
        if integrity!='ok':
            raise RuntimeError('SQLite integrity check failed')
        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        counts={name:db.execute('SELECT COUNT(*) FROM "'+name.replace('"','""')+'"').fetchone()[0] for name in sorted(tables)}
        return {'integrity':integrity,'row_counts':counts}


def backup_and_verify(source:Path,destination:Path):
    source=source.resolve();destination=destination.resolve()
    if not source.is_file():
        raise FileNotFoundError('The source database does not exist')
    if source==destination:
        raise ValueError('The backup cannot replace the source')
    destination.parent.mkdir(parents=True,exist_ok=True)
    # Reserve the filename exclusively. A second run cannot clobber a prior backup.
    fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
    try:
        with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(destination) as dst:
            src.backup(dst,pages=128)
        snapshot=database_summary(destination)
        with tempfile.TemporaryDirectory(prefix='radar-restore-') as directory:
            restored=Path(directory)/'restored.sqlite3'
            with sqlite3.connect(destination.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(restored) as dst:
                src.backup(dst)
            restored_summary=database_summary(restored)
        if restored_summary!=snapshot:
            raise RuntimeError('Restored database does not match the backup')
        return {'verified_at':datetime.now(timezone.utc).isoformat(),
                'backup_file':destination.name,'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),
                'size_bytes':destination.stat().st_size,'snapshot':snapshot,
                'restored_in_isolation':True,'live_database_replaced':False}
    except BaseException:
        # Keep a failed attempt for diagnosis; do not report it as a usable backup.
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    report=backup_and_verify(args.source,args.destination)
    text=json.dumps(report,ensure_ascii=False,indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(text,encoding='utf-8')
    print(text)


if __name__=='__main__':
    main()
