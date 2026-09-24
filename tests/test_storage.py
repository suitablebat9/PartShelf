import io
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import pytest
from scripts import backup, migrate_storage, update
from test_update import archive_to


def test_backup_archives_relocated_data_not_just_symlink(tmp_path, monkeypatch):
    data = tmp_path/'data'
    data.mkdir()
    (data/'inventory.db').write_bytes(b'database contents')
    link = tmp_path/'legacy-data'
    link.symlink_to(data)
    monkeypatch.setattr(backup, 'Path', lambda value: link if str(value)=='/var/lib/partshelf' else Path(value))
    monkeypatch.setattr(backup.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(backup, 'paused_alerts', nullcontext)
    monkeypatch.setattr(backup.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0))
    monkeypatch.setattr(sys, 'argv', ['backup.py', str(tmp_path/'backups')])
    with patch.object(backup, 'open', return_value=io.StringIO(), create=True), patch('fcntl.flock'):
        backup.main()
    with tarfile.open(next((tmp_path/'backups').glob('*.tar.gz'))) as archive:
        assert archive.getmember('partshelf').isdir()
        assert archive.extractfile('partshelf/inventory.db').read()==b'database contents'


def test_update_rollback_preserves_data_symlink(tmp_path, monkeypatch):
    data = tmp_path/'data'
    data.mkdir()
    (data/'inventory.db').write_text('original')
    link = tmp_path/'legacy-data'
    link.symlink_to(data)
    root = tmp_path/'app'
    old = root/'old'
    old.mkdir(parents=True)
    update.activate(root, old)
    monkeypatch.setattr(update, 'Path', lambda value: link if str(value)=='/var/lib/partshelf' else Path(value))
    monkeypatch.setattr(sys, 'argv', ['update.py', '--root', str(root)])
    monkeypatch.setattr(update.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(update, 'paused_alerts', nullcontext)
    monkeypatch.setattr(update.subprocess, 'check_output', lambda *a, **k: 'abc123\n')
    def run(*args, **kwargs):
        if 'archive' in args:
            archive_to(kwargs['stdout'])
    monkeypatch.setattr(update, 'run', run)
    def fail_health(*args, **kwargs):
        (data/'inventory.db').write_text('failed migration')
        raise OSError('unhealthy')
    monkeypatch.setattr(update.urllib.request, 'urlopen', fail_health)
    monkeypatch.setattr(update.time, 'sleep', lambda _: None)
    with patch.object(update, 'open', return_value=io.StringIO(), create=True), patch('fcntl.flock'):
        with pytest.raises(RuntimeError, match='Health check'):
            update.main()
    assert link.is_symlink() and link.resolve()==data
    assert (data/'inventory.db').read_text()=='original'
    assert (root/'current').resolve()==old
    assert next((root/'backups').glob('*/failed-data/inventory.db')).read_text()=='failed migration'


@pytest.mark.parametrize('fail_health', [False, True])
def test_storage_migration_and_automatic_rollback(tmp_path, monkeypatch, fail_health):
    mount = tmp_path/'mount'
    mount.mkdir()
    fake = tmp_path/'system'
    app = fake/'opt/partshelf'
    data = fake/'var/lib/partshelf'
    config = fake/'etc/partshelf.env'
    for folder in (app, data, config.parent, fake/'etc/systemd/system', fake/'etc/logrotate.d'):
        folder.mkdir(parents=True, exist_ok=True)
    (app/'release').mkdir()
    (app/'release/code.py').write_text('code')
    (app/'current').symlink_to(app/'release')
    with sqlite3.connect(data/'inventory.db') as db:
        db.execute('CREATE TABLE sample(value)')
    config.write_text('SMTP_PASSWORD=private\n')
    config.chmod(0o600)
    def mapped(value):
        value = str(value)
        return fake/value.lstrip('/') if value.startswith(('/opt/', '/var/', '/etc/')) else Path(value)
    monkeypatch.setattr(migrate_storage, 'Path', mapped)
    monkeypatch.setattr(Path, 'is_mount', lambda _: True)
    monkeypatch.setattr(migrate_storage.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(migrate_storage, 'paused_alerts', nullcontext)
    monkeypatch.setattr(migrate_storage.shutil, 'chown', lambda *a, **k: None)
    monkeypatch.setattr(migrate_storage.subprocess, 'check_output', lambda args, **k: 'zfs' if args[0]=='findmnt' else '100')
    monkeypatch.setattr(migrate_storage.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0))
    def run(*args):
        if args[0]=='cp':
            src, dst = Path(args[-2]), Path(args[-1])
            if src.is_dir():
                shutil.copytree(src, dst, symlinks=True)
            else:
                shutil.copy2(src, dst)
    monkeypatch.setattr(migrate_storage, 'run', run)
    def health():
        if fail_health:
            raise RuntimeError('health failed')
    monkeypatch.setattr(migrate_storage, 'health_check', health)
    monkeypatch.setattr(sys, 'argv', ['migrate_storage.py', '--mount', str(mount)])
    with patch.object(migrate_storage, 'open', return_value=io.StringIO(), create=True), patch('fcntl.flock'):
        if fail_health:
            with pytest.raises(RuntimeError, match='health failed'):
                migrate_storage.main()
        else:
            migrate_storage.main()
    assert app.is_symlink() is not fail_health
    assert data.is_symlink() is not fail_health
    assert config.read_text()=='SMTP_PASSWORD=private\n'
    assert (app/'current/code.py').read_text()=='code'
    assert migrate_storage.check_databases(data)==1
    if fail_health:
        assert not list((fake/'etc/systemd/system').glob('*/storage.conf'))
    else:
        assert config.resolve()==mount/'config/partshelf.env'
        assert len(list((mount/'rollback').glob('*/original-*')))==3
        assert (mount/'config/migration.json').exists()
