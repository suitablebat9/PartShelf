"""Keep background writes out of data backups and release switches."""
from contextlib import contextmanager
from pathlib import Path
import subprocess


@contextmanager
def paused_alerts():
    installed=[name for name in ('partshelf-alerts','partshelf-demo-reset') if Path('/etc/systemd/system/'+name+'.timer').exists()]
    active=[name for name in installed if subprocess.run(['systemctl','is-active','--quiet',name+'.timer']).returncode==0]
    try:
        for name in installed:
            subprocess.run(['systemctl','stop',name+'.timer',name+'.service'],check=True)
        yield
    finally:
        for name in active:
            subprocess.run(['systemctl','start',name+'.timer'],check=True)
