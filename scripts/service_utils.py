"""Keep background notification writes out of data backups and release switches."""
from contextlib import contextmanager
from pathlib import Path
import subprocess


@contextmanager
def paused_alerts():
    installed = Path('/etc/systemd/system/partshelf-alerts.timer').exists()
    active = installed and subprocess.run(['systemctl','is-active','--quiet','partshelf-alerts.timer']).returncode == 0
    try:
        if installed:
            subprocess.run(['systemctl','stop','partshelf-alerts.timer','partshelf-alerts.service'],check=True)
        yield
    finally:
        if active:
            subprocess.run(['systemctl','start','partshelf-alerts.timer'],check=True)
