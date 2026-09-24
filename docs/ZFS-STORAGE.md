# Partshelf storage on a Proxmox ZFS mount

Attach the ZFS-backed storage to the LXC at `/mnt/partshelf` using a persistent
Proxmox mount point. The migration script expects this to already be mounted and
writable. It does not create, format, or repartition storage.

Update Partshelf first, then run as root inside its LXC:

```sh
python3 /opt/partshelf/current/scripts/update.py
python3 /opt/partshelf/current/scripts/migrate_storage.py
```

The migration pauses the application and background jobs, copies and verifies
contents and ownership, checks every SQLite database, and switches the original
paths to symbolic links. It restores the original paths automatically if the
application health check fails. Run only once on an unmigrated installation;
existing destination directories or overrides require manual inspection.

| Persistent contents | ZFS location | Compatible path |
| --- | --- | --- |
| Git source, releases, virtual environments, update backups | `/mnt/partshelf/app` | `/opt/partshelf` |
| Accounts, workspaces, inventory, uploads, session key, demo | `/mnt/partshelf/data` | `/var/lib/partshelf` |
| Private email/OAuth configuration | `/mnt/partshelf/config/partshelf.env` | `/etc/partshelf.env` |
| App and background-service logs | `/mnt/partshelf/logs` | systemd output destination |
| Untouched migration recovery copies | `/mnt/partshelf/rollback/<timestamp>` | recorded in `config/migration.json` |

Existing updater commands continue working. Backups and update rollback resolve
the real data directory; changing email settings preserves the configuration
link. For a manual data backup on ZFS:

```sh
python3 /opt/partshelf/current/scripts/backup.py /mnt/partshelf/app/backups/manual
```

Systemd storage drop-ins and logrotate integration remain in `/etc` so the OS
can discover them. Copies are kept under `/mnt/partshelf/config`. The services
require the ZFS mount and have an explicit mount-point condition. Service logs
rotate daily or over 20 MB and keep 14 compressed rotations. Shared operating
system logs, installed OS packages, and temporary files remain managed by the LXC.

Keep `/mnt/partshelf` mounted before starting the container's Partshelf services.
The unchanged compatibility paths also preserve existing virtual-environment
script paths. Do not remove those links. The recovery copies on the same pool
are for undoing the migration; they are not an independent backup of the pool.
