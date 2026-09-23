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
