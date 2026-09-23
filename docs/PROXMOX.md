# Install Partshelf in Proxmox LXC

This guide targets a **fresh Debian 13 unprivileged LXC** on Proxmox VE. Commands are split between the **Proxmox host** and **inside the container**. The installer does not run on the Proxmox host. Python 3.10 or newer is required; Debian 12 with Python 3.11 is also supported. Suggested allocation: 2 cores, 1 GB RAM, 512 MB swap, 8 GB disk (increase disk for uploaded files/backups).

## 1. Download a template — Proxmox host

In Proxmox: select your node → template storage (often `local`) → CT Templates → Templates → download the current Debian 13 standard template. Or:

```bash
pveam update
pveam available --section system
# Replace the name below with the exact Debian 13 filename listed above:
pveam download local DEBIAN_13_TEMPLATE_FILENAME
pveam list local
```

Template filenames change. Use the downloaded volume ID shown by `pveam list`, not a guessed version. The official references are [Proxmox container documentation](https://pve.proxmox.com/pve-docs/chapter-pct.html) and [pct command reference](https://pve.proxmox.com/pve-docs/pct.1.html).

## 2. Create the container — Proxmox host

### Through the Proxmox UI

Choose **Create CT**, an unused container ID and hostname `partshelf`. Set a root password or SSH key for administration. Leave **Unprivileged container** enabled. Select the Debian 13 template, allocate resources above, and attach your LAN bridge (often `vmbr0`). DHCP is fine; reserve its address on your router. Enable Start at boot. Nesting, privileged mode and device passthrough are not needed.

### Or use the supplied helper

```bash
git clone https://github.com/suitablebat9/Inventory.git /root/partshelf-setup
cd /root/partshelf-setup
CT_ID=120 \
TEMPLATE='local:vztmpl/REPLACE_WITH_EXACT_DEBIAN_13_FILENAME' \
STORAGE=local-lvm BRIDGE=vmbr0 \
bash scripts/create_lxc.sh
```

Change `120`, template storage, disk storage and bridge to match your host. The helper refuses an existing container ID. It uses DHCP by default. For a static address, additionally set `NET='ip=192.168.1.120/24,gw=192.168.1.1'` to values valid for your LAN. No root password is assigned by the helper; administer through `pct enter`, or set one there with `passwd` if needed.

Wait for networking, then enter:

```bash
pct enter 120
```

## 3. Install — INSIDE the container

```bash
apt-get update
apt-get install -y git ca-certificates
git clone https://github.com/suitablebat9/Inventory.git /root/partshelf-install
cd /root/partshelf-install
bash scripts/install.sh
```

The installer installs Python and Nginx, creates the unprivileged `partshelf` service user, clones source into `/opt/partshelf/source`, builds a tested release and creates your first login interactively. Choose a password of at least 12 characters. It configures this container's default Nginx site, so use a fresh container dedicated to this application.

Find its address with:

```bash
hostname -I
```

Open **http://YOUR_LXC_IP** on a device on the same network. Use the same address on your phone/laptop; all devices share the database. The app's credentials differ from the LXC root credentials.

## 4. Updates

Run inside the container as root:

```bash
python3 /opt/partshelf/current/scripts/update.py
```

Update steps: fetch repository → create release → install pinned packages → test → stop app → back up database/uploads/secret → activate release → restart → health check. Preflight failures leave the running release unchanged. Post-switch failures restore the previous release and data. Releases are root-owned; the web service cannot modify its own code.

Repository: `https://github.com/suitablebat9/Inventory.git`, branch `main`. For another trusted branch, use `--branch BRANCH`. Only deploy reviewed code: the updater installs dependencies and runs code from that branch as part of deployment. GitHub must be reachable for updates; ordinary app use has no GitHub dependency.

When a future release explicitly changes system configuration, review then install the matching files and validate:

```bash
install -m 644 /opt/partshelf/current/deploy/partshelf.service /etc/systemd/system/partshelf.service
install -m 644 /opt/partshelf/current/deploy/nginx.conf /etc/nginx/sites-available/partshelf
nginx -t
systemctl daemon-reload
systemctl restart partshelf
systemctl reload nginx
```

Do not replace customized TLS/proxy configuration without merging your settings.

## 5. Backups and restore

Keep a scheduled Proxmox backup of the entire LXC on separate storage. Include `/var/lib/partshelf`, which contains `inventory.db`, `uploads/`, and `secret.key`. Do not copy a live SQLite database file alone; use the backup script or stop the service first.

Manual consistent application backup (briefly stops the service):

```bash
python3 /opt/partshelf/current/scripts/backup.py /opt/partshelf/manual-backups
```

Copy the resulting `.tar.gz` to separate storage. It contains credentials and private inventory data; protect it. Backups created during updates are in `/opt/partshelf/backups/TIMESTAMP/data`. A backup on the same disk is useful for rollback but does not protect against disk loss.

Restore a manual archive, inside the LXC as root:

```bash
systemctl stop partshelf
mv /var/lib/partshelf /var/lib/partshelf.before-restore
# Use a trusted archive produced by backup.py:
tar -xzf /PATH/TO/partshelf-TIMESTAMP.tar.gz -C /var/lib
chown -R partshelf:partshelf /var/lib/partshelf
systemctl start partshelf
```

Restore data with the corresponding code release if database formats differ. Keep the old directory until restoration is verified. User passwords are hashed; restoring `secret.key` also preserves the session-signing key.

## 6. Users and access

Create or reset a user's password interactively:

```bash
cd /opt/partshelf/current
runuser -u partshelf -- env INVENTORY_DATA=/var/lib/partshelf .venv/bin/python scripts/manage_user.py
```

All users can edit the shared inventory. Passwords are not passed on the command line or stored in source. Do not expose this app to the public internet as an unauthenticated reverse proxy. Use your LAN/VPN, or configure an HTTPS reverse proxy. After HTTPS is active, put `COOKIE_SECURE=1` in `/etc/partshelf.env` and restart `partshelf`. This setting is off for initial LAN HTTP access; enabling it on plain HTTP prevents sessions working. No DNS or certificates are needed for LAN-only access.

## 7. Code changes without manual server editing

Edit the repository on your development computer, test it and push it. The server only runs `update.py`. If you receive a reviewed unified patch, apply it through Python:

```bash
python3 scripts/patch_code.py /path/to/change.patch
.venv/bin/python -m pytest -q
python3 scripts/publish.py --message "Describe the change"
```

`patch_code.py` checks the patch first and refuses a dirty working tree. `publish.py` shows the paths to commit and asks for confirmation; Git handles authentication. No tokens are stored by these scripts. See `--help` for options.

## Troubleshooting

```bash
systemctl status partshelf nginx
journalctl -u partshelf -n 100 --no-pager
nginx -t
curl -I http://127.0.0.1:8000/login
```

- Connection refused: verify service status, LXC IP, LAN route and Proxmox firewall rules for TCP 80 (or 443 when configured).
- Login 503 from Nginx: login rate limit exceeded; wait a minute.
- Upload 413: combined request exceeds the 12 MB limit. Resize the image/PDF.
- Stale edit 409: another device changed that part. Reload, check the new values, reapply your edit.
- Label clipping: use actual-size printing, zero margins, correct printer stock, and disable headers/footers. The app fits text but cannot control a printer's non-printable margins. Test a QR/barcode before printing a batch.
- Reset password: use `manage_user.py` above.
- Update fails during tests/install: the old app keeps running. Fix the reported failure and retry.

Deployment follows Flask's [Gunicorn](https://flask.palletsprojects.com/en/stable/deploying/gunicorn/) and [Nginx](https://flask.palletsprojects.com/en/stable/deploying/nginx/) guidance. No Proxmox server was available during development; installation scripts must be exercised on your actual host and chosen template.

## Recover from an older Python archive-extraction error

If initial installation stopped with `TarFile.extractall() got an unexpected keyword argument 'filter'`, run inside the container as root:

```bash
git -C /opt/partshelf/source pull --ff-only origin main
bash /opt/partshelf/source/scripts/install.sh
```

The corrected updater handles archive extraction without that Python API. The installer refreshes its source on retry. This failure happens before release activation or inventory changes, so do not delete your data or rebuild the container. If the new version reports Python older than 3.10, use a Debian 12/13 container or a supported Python interpreter; the pinned app dependencies require at least 3.10.
