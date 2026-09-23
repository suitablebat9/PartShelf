#!/usr/bin/env python3
"""Install a tested release from origin/main, preserving data and previous releases."""
import argparse
import datetime
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
try:
    from .service_utils import paused_alerts
except ImportError:
    from service_utils import paused_alerts
import tempfile
import time
import urllib.request


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def extract_release(archive, destination):
    """Extract regular Git files safely, including on Python without tar filters."""
    destination = Path(destination).resolve()
    if not destination.is_dir() or any(destination.iterdir()):
        raise ValueError('Release extraction requires an empty directory.')
    entries = []
    seen = set()
    for member in archive.getmembers():
        name = PurePosixPath(member.name)
        if (name.is_absolute() or '..' in name.parts or not name.parts
                or '\\' in member.name or not (member.isfile() or member.isdir())
                or name in seen):
            raise ValueError(f'Unsafe release archive entry: {member.name}')
        seen.add(name)
        entries.append((member, destination.joinpath(*name.parts)))
    # Never restore archive ownership, special modes, links, or device files.
    for member, target in entries:
        target.parent.mkdir(parents=True, exist_ok=True)
        if member.isdir():
            target.mkdir(exist_ok=True)
            target.chmod(0o755)
        else:
            with archive.extractfile(member) as source, target.open('xb') as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)


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
    if sys.version_info < (3, 10):
        sys.exit('Partshelf requires Python 3.10 or newer. Use Debian 12 or 13, or run this script with a supported Python interpreter.')
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
            extract_release(files, release)
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
    with paused_alerts():
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
