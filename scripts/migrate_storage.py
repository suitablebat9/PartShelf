#!/usr/bin/env python3
"""Move an existing Partshelf installation onto an already mounted ZFS volume."""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import time
import urllib.request

try:
    from .service_utils import paused_alerts
except ImportError:
    from service_utils import paused_alerts


def run(*args):
    return subprocess.run(args, check=True)


def manifest(root):
    """Check contents, links, permissions and ownership without following links."""
    root = Path(root)
    result = {}
    paths = [root]
    if root.is_dir():
        paths += sorted(root.rglob('*'))
    for path in paths:
        info = path.lstat()
        details = [info.st_mode, info.st_uid, info.st_gid]
        if stat.S_ISLNK(info.st_mode):
            details.append(os.readlink(path))
        elif stat.S_ISREG(info.st_mode):
            digest = hashlib.sha256()
            with path.open('rb') as source:
                for chunk in iter(lambda: source.read(1024*1024), b''):
                    digest.update(chunk)
            details.append(digest.hexdigest())
        elif not stat.S_ISDIR(info.st_mode):
            raise ValueError('Unsupported special file: ' + str(path))
        result[str(path.relative_to(root))] = details
    return result


def check_databases(data):
    databases = sorted(set(data.rglob('*.db')) | set(data.rglob('*.sqlite3')))
    for path in databases:
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
            if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise RuntimeError('Database integrity check failed: ' + str(path))
    return len(databases)


def health_check():
    for _ in range(20):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8000/login', timeout=3) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(1)
    raise RuntimeError('Partshelf health check failed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mount', type=Path, default=Path('/mnt/partshelf'))
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Run as root inside the Partshelf LXC.')
    mount = args.mount.resolve(strict=True)
    if not mount.is_mount() or any(c.isspace() for c in str(mount)):
        parser.error('Use an existing mount point without whitespace in its path.')
    fstype = subprocess.check_output(['findmnt', '-n', '-o', 'FSTYPE', '-T', str(mount)], text=True).strip()
    if fstype != 'zfs':
        parser.error('The destination must be an already mounted ZFS filesystem.')
    lock = open('/run/partshelf-update.lock', 'w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    pairs = [(Path('/opt/partshelf'), mount/'app'),
             (Path('/var/lib/partshelf'), mount/'data'),
             (Path('/etc/partshelf.env'), mount/'config/partshelf.env')]
    for source, target in pairs:
        if source.is_symlink() or not source.exists() or target.exists():
            parser.error('Migration requires original source paths and unused destination paths: ' + str(source))
    units = ['partshelf', 'partshelf-alerts', 'partshelf-demo-reset']
    dropins = [Path('/etc/systemd/system')/(name+'.service.d')/'storage.conf' for name in units]
    if any(path.exists() for path in dropins):
        parser.error('An existing storage override needs manual review.')
    if shutil.disk_usage(mount).free < 4 * int(subprocess.check_output(['du', '-sb', '/opt/partshelf'], text=True).split()[0]):
        parser.error('Insufficient free space for verified copies and rollback copies.')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    rollback = mount/'rollback'/stamp
    rollback.mkdir(parents=True, mode=0o700)
    rollback.parent.chmod(0o700)
    (mount/'config').mkdir(mode=0o700)
    (mount/'logs').mkdir(mode=0o750)
    shutil.chown(mount/'logs', user='partshelf', group='partshelf')
    for name in units:
        log = mount/'logs'/(name+'.log')
        log.touch(mode=0o640)
        shutil.chown(log, user='partshelf', group='partshelf')
    switched = []
    created_dropins = []
    active = subprocess.run(['systemctl', 'is-active', '--quiet', 'partshelf']).returncode == 0
    with paused_alerts():
        run('systemctl', 'stop', 'partshelf')
        try:
            for source, target in pairs:
                print('Copying and verifying', source, '->', target, flush=True)
                run('cp', '-a', '--', str(source), str(target))
                if manifest(source) != manifest(target):
                    raise RuntimeError('Copy verification failed for ' + str(source))
            print('Database integrity checks:', check_databases(mount/'data'), 'passed', flush=True)
            for source, target in pairs:
                original = source.with_name(source.name+'.pre-zfs-'+stamp)
                source.rename(original)
                switched.append((source, original, target))
                source.symlink_to(target, target_is_directory=target.is_dir())
            for name, dropin in zip(units, dropins):
                dropin.parent.mkdir(exist_ok=True)
                dropin.write_text('[Unit]\nRequiresMountsFor='+str(mount)+'\nConditionPathIsMountPoint='+str(mount)+'\n'
                    '[Service]\nReadWritePaths='+str(mount/'data')+' '+str(mount/'logs')+'\n'
                    'StandardOutput=append:'+str(mount/'logs'/(name+'.log'))+'\n'
                    'StandardError=append:'+str(mount/'logs'/(name+'.log'))+'\n')
                created_dropins.append(dropin)
            run('systemctl', 'daemon-reload')
            if active:
                run('systemctl', 'start', 'partshelf')
                health_check()
        except Exception:
            run('systemctl', 'stop', 'partshelf')
            for path in created_dropins:
                path.unlink()
            for source, original, target in reversed(switched):
                if source.is_symlink():
                    source.unlink()
                original.rename(source)
            run('systemctl', 'daemon-reload')
            if active:
                run('systemctl', 'start', 'partshelf')
            print('Original paths restored; destination copies retained for inspection.', flush=True)
            raise
    # Only after the app is healthy, relocate the untouched originals as a
    # private recovery copy. A failed move here does not affect the running app.
    for index, (source, original, target) in enumerate(switched):
        shutil.move(str(original), str(rollback/('original-'+str(index))))
    for path in dropins:
        shutil.copy2(path, mount/'config'/(path.parent.name+'.conf'))
    logrotate = Path('/etc/logrotate.d/partshelf-zfs')
    if not logrotate.exists():
        logrotate.write_text(str(mount/'logs/*.log')+' {\n  daily\n  maxsize 20M\n  rotate 14\n  compress\n  missingok\n  notifempty\n  copytruncate\n  su partshelf partshelf\n}\n')
        shutil.copy2(logrotate, mount/'config/logrotate.conf')
    record = {'mount': str(mount), 'rollback': str(rollback),
              'paths': {str(source): str(target) for source, target in pairs}}
    (mount/'config/migration.json').write_text(json.dumps(record, indent=2)+'\n')
    print('Migration verified. Active storage:', mount, '\nRecovery copies:', rollback)


if __name__ == '__main__':
    main()
