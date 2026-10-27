"""Copy a quiesced site's SQLite DB and private files, then hash the snapshot.

Service lifecycle belongs to backup.sh. This helper prints paths/counts only.
"""
import hashlib
import json
import shutil
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def verify(destination):
    payload = json.loads((destination / 'manifest.json').read_text(encoding='utf-8'))
    for item in payload['files']:
        path = destination / item['path']
        assert path.resolve().is_relative_to(destination.resolve()), 'Unsafe manifest path.'
        assert path.is_file() and not path.is_symlink(), f'Missing/unsafe file: {item["path"]}'
        assert path.stat().st_size == item['bytes'], f'Size mismatch: {item["path"]}'
        assert digest(path) == item['sha256'], f'Hash mismatch: {item["path"]}'
    with closing(sqlite3.connect((destination / 'modshare.db').as_uri() + '?mode=ro', uri=True)) as database:
        assert database.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'SQLite integrity check failed.'
    print(f'Verified snapshot entries: {len(payload["files"])}')


def snapshot(base, destination):
    database = base / 'data' / 'modshare.db'
    assert database.is_file() and not database.is_symlink(), 'Site database missing/unsafe.'
    assert destination.is_dir() and not any(destination.iterdir()), 'Use an empty snapshot directory.'
    private = base / 'data' / 'files'
    assert private.is_dir() and not private.is_symlink(), 'Private file directory missing/unsafe.'
    assert not any(path.is_symlink() for path in private.rglob('*')), 'Private files contain a symlink.'
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(destination / 'modshare.db')) as target:
            source.backup(target)
            assert target.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'SQLite integrity check failed.'
    shutil.copytree(private, destination / 'files')
    shutil.copy2(base / 'secrets' / 'config.json', destination / 'config.json')
    if (base / 'secrets' / 'runtime.env').exists():
        shutil.copy2(base / 'secrets' / 'runtime.env', destination / 'runtime.env')
    requirements = base / 'app' / 'requirements.txt'
    if requirements.exists():
        shutil.copy2(requirements, destination / 'requirements.txt')
    manifest = []
    for path in sorted(destination.rglob('*')):
        if path.is_file():
            path.chmod(0o600)
            manifest.append({'path': path.relative_to(destination).as_posix(),
                             'bytes': path.stat().st_size, 'sha256': digest(path)})
    payload = {'created_at': datetime.now(timezone.utc).isoformat(),
               'database_method': 'sqlite3.Connection.backup with site service stopped',
               'files': manifest}
    manifest_path = destination / 'manifest.json'
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    manifest_path.chmod(0o600)
    verify(destination)
    print(f'Snapshot files: {len(manifest)}; bytes: {sum(item["bytes"] for item in manifest)}')


if __name__ == '__main__':
    if sys.argv[1] == '--verify':
        verify(Path(sys.argv[2]).resolve())
    else:
        snapshot(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
