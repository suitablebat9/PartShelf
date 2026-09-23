"""Exercise the real activation/rollback flow without touching system services."""
import io
import subprocess
import sys
import tarfile
from pathlib import Path
from unittest.mock import patch
import pytest
from scripts import update


def archive_to(file):
    with tarfile.open(fileobj=file, mode='w') as archive:
        info = tarfile.TarInfo('requirements-dev.txt')
        content = b'pytest\n'
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))


def test_activation_is_atomic_symlink(tmp_path):
    first = tmp_path/'first'
    second = tmp_path/'second'
    first.mkdir()
    second.mkdir()
    update.activate(tmp_path, first)
    assert (tmp_path/'current').resolve() == first
    update.activate(tmp_path, second)
    assert (tmp_path/'current').resolve() == second
    assert first.exists()
    assert not (tmp_path/'current.next').exists()


def test_preflight_failure_keeps_current_release(tmp_path, monkeypatch):
    old = tmp_path/'old'
    old.mkdir()
    update.activate(tmp_path, old)
    monkeypatch.setattr(sys, 'argv', ['update.py', '--root', str(tmp_path)])
    monkeypatch.setattr(update.os, 'geteuid', lambda: 0)
    calls = []
    def run(*args, **kwargs):
        calls.append(args)
        if 'archive' in args:
            archive_to(kwargs['stdout'])
        if 'pytest' in args:
            raise subprocess.CalledProcessError(1, args)
    monkeypatch.setattr(update, 'run', run)
    monkeypatch.setattr(update.subprocess, 'check_output', lambda *a, **k: 'abc123\n')
    import fcntl
    with patch('builtins.open', return_value=io.StringIO()), patch.object(fcntl, 'flock'):
        with pytest.raises(subprocess.CalledProcessError):
            update.main()
    assert (tmp_path/'current').resolve() == old
    assert not any('systemctl' in call for call in calls)


def test_extract_without_extractall_filter(tmp_path, monkeypatch):
    def unsupported(*args, **kwargs):
        raise AssertionError('Do not depend on extractall or extraction filters')
    monkeypatch.setattr(tarfile.TarFile, 'extractall', unsupported)
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as archive:
        folder = tarfile.TarInfo('scripts')
        folder.type = tarfile.DIRTYPE
        archive.addfile(folder)
        file = tarfile.TarInfo('scripts/example.py')
        file.mode = 0o4755
        file.size = 5
        archive.addfile(file, io.BytesIO(b'hello'))
    stream.seek(0)
    with tarfile.open(fileobj=stream) as archive:
        update.extract_release(archive, tmp_path)
    assert (tmp_path/'scripts/example.py').read_text() == 'hello'
    assert (tmp_path/'scripts/example.py').stat().st_mode & 0o7777 == 0o755


@pytest.mark.parametrize('name,kind', [
    ('../outside', tarfile.REGTYPE), ('/outside', tarfile.REGTYPE),
    ('dir/../../outside', tarfile.REGTYPE), ('link', tarfile.SYMTYPE),
    ('hardlink', tarfile.LNKTYPE), ('device', tarfile.CHRTYPE),
    ('fifo', tarfile.FIFOTYPE), ('dir\\outside', tarfile.REGTYPE),
])
def test_extract_rejects_unsafe_entries_before_writing(tmp_path, name, kind):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as archive:
        archive.addfile(tarfile.TarInfo('valid.txt'), io.BytesIO())
        unsafe = tarfile.TarInfo(name)
        unsafe.type = kind
        unsafe.linkname = '../outside'
        archive.addfile(unsafe)
    stream.seek(0)
    with tarfile.open(fileobj=stream) as archive:
        with pytest.raises(ValueError, match='Unsafe'):
            update.extract_release(archive, tmp_path)
    assert not list(tmp_path.iterdir())


def test_extract_refuses_existing_directory_contents(tmp_path):
    (tmp_path/'keep').write_text('original')
    with pytest.raises(ValueError, match='empty directory'):
        update.extract_release(None, tmp_path)
    assert (tmp_path/'keep').read_text() == 'original'


def test_alert_timer_restarts_even_when_backup_fails(monkeypatch):
    from scripts import service_utils
    monkeypatch.setattr(service_utils.Path, 'exists', lambda _: True)
    calls=[]
    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args,0)
    monkeypatch.setattr(service_utils.subprocess,'run',run)
    with pytest.raises(RuntimeError):
        with service_utils.paused_alerts():
            raise RuntimeError('backup failed')
    assert calls[1]==['systemctl','stop','partshelf-alerts.timer','partshelf-alerts.service']
    assert calls[-1]==['systemctl','start','partshelf-alerts.timer']
