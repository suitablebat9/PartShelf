#!/usr/bin/env python3
"""Create a consistent private backup; run as root inside the LXC."""
import argparse
import datetime
import os
from pathlib import Path
import subprocess
import tarfile
try:
    from .service_utils import paused_alerts
except ImportError:
    from service_utils import paused_alerts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Run as root inside the LXC.')
    import fcntl
    lock = open('/run/partshelf-update.lock', 'w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    args.destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path = args.destination / f'partshelf-{stamp}.tar.gz'
    with paused_alerts():
        active = subprocess.run(['systemctl', 'is-active', '--quiet', 'partshelf']).returncode == 0
        subprocess.run(['systemctl', 'stop', 'partshelf'], check=True)
        try:
            with path.open('xb') as stream:
                path.chmod(0o600)
                with tarfile.open(fileobj=stream, mode='w:gz') as archive:
                    archive.add(Path('/var/lib/partshelf').resolve(strict=True), arcname='partshelf')
        except Exception:
            path.unlink(missing_ok=True)
            raise
        finally:
            if active:
                subprocess.run(['systemctl', 'start', 'partshelf'], check=True)
    print(path)


if __name__ == '__main__':
    main()
