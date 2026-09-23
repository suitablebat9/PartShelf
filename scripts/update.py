#!/usr/bin/env python3
"""Install a tested release from origin/main, preserving data and previous releases."""
import argparse
import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def activate(root, release):
    temp = root / 'current.next'
    temp.unlink(missing_ok=True)
    temp.symlink_to(release)
    temp.replace(root / 'current')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/opt/partshelf'))
    parser.add_argument('--branch', default='main')
    parser.add_argument('--initial', action='store_true', help='First installation; do not restart service')
    args = parser.parse_args()
    if os.geteuid() != 0:
        sys.exit('Run with sudo or as root inside your LXC.')
    import fcntl
    lock = open('/run/partshelf-update.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit('Another update is already running.')
    root = args.root.resolve()
    source = root / 'source'
    run('git', '-C', str(source), 'fetch', '--prune', 'origin')
    sha = subprocess.check_output(['git', '-C', str(source), 'rev-parse', '--verify', f'origin/{args.branch}^{{commit}}'], text=True).strip()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    release = root / 'releases' / (stamp + '-' + sha[:10])
    release.mkdir(parents=True)
    with tempfile.TemporaryFile() as archive:
        run('git', '-C', str(source), 'archive', sha, stdout=archive)
        archive.seek(0)
        # Archives come only from the configured, trusted repository.
        with tarfile.open(fileobj=archive) as files:
            files.extractall(release, filter='data')
    run(sys.executable, '-m', 'venv', str(release / '.venv'))
    python = str(release / '.venv/bin/python')
    run(python, '-m', 'pip', 'install', '-r', str(release / 'requirements-dev.txt'))
    run(python, '-m', 'pytest', '-q', cwd=release)
    previous = (root / 'current').resolve() if (root / 'current').exists() else None
    if args.initial:
        activate(root, release)
        print('Initial release ready:', release)
        return
    if previous is None:
        sys.exit('No current release. Use the installer for first setup.')
    data = Path('/var/lib/partshelf')
    backup = root / 'backups' / stamp
    backup.mkdir(parents=True, mode=0o700)
    run('systemctl', 'stop', 'partshelf')
    copied = False
    try:
        shutil.copytree(data, backup / 'data')
        copied = True
        activate(root, release)
        run('systemctl', 'start', 'partshelf')
        last_error = None
        for _ in range(15):
            try:
                with urllib.request.urlopen('http://127.0.0.1:8000/login', timeout=3) as response:
                    if response.status == 200:
                        print('Updated to', sha, '\nBackup:', backup)
                        return
            except (OSError, ValueError) as error:
                last_error = error
            time.sleep(1)
        raise RuntimeError(f'Health check failed: {last_error}')
    except Exception:
        run('systemctl', 'stop', 'partshelf')
        activate(root, previous)
        if copied:
            failed_data = backup / 'failed-data'
            shutil.move(str(data), failed_data)
            shutil.copytree(backup / 'data', data)
            run('chown', '-R', 'partshelf:partshelf', str(data))
        run('systemctl', 'start', 'partshelf')
        print('Update failed; previous release and database restored.', file=sys.stderr)
        raise


if __name__ == '__main__':
    main()
