#!/usr/bin/env bash
set -euo pipefail
if [[ "$EUID" -ne 0 ]]; then echo 'Run as root inside the new Debian LXC.'; exit 1; fi
if [[ -e /opt/partshelf/current ]]; then echo 'Already installed. Run python3 /opt/partshelf/current/scripts/update.py'; exit 1; fi
REPO_URL="${1:-https://github.com/suitablebat9/Inventory.git}"
apt-get update
apt-get install -y python3 python3-venv git nginx ca-certificates
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else "Partshelf requires Python 3.10 or newer. Use a Debian 12 or 13 LXC.")'
id partshelf >/dev/null 2>&1 || useradd --system --home-dir /var/lib/partshelf --create-home --shell /usr/sbin/nologin partshelf
install -d -m 750 -o partshelf -g partshelf /var/lib/partshelf
install -d -m 755 /opt/partshelf
if [[ ! -d /opt/partshelf/source/.git ]]; then
    git clone "$REPO_URL" /opt/partshelf/source
else
    git -C /opt/partshelf/source pull --ff-only origin main
fi
python3 /opt/partshelf/source/scripts/update.py --initial
install -m 644 /opt/partshelf/current/deploy/partshelf.service /etc/systemd/system/partshelf.service
install -m 644 /opt/partshelf/current/deploy/nginx.conf /etc/nginx/sites-available/partshelf
ln -sfn /etc/nginx/sites-available/partshelf /etc/nginx/sites-enabled/partshelf
if [[ -L /etc/nginx/sites-enabled/default ]]; then unlink /etc/nginx/sites-enabled/default; fi
nginx -t
printf '\nCreate your inventory login (password: at least 8 characters).\n'
cd /opt/partshelf/current
runuser -u partshelf -- env INVENTORY_DATA=/var/lib/partshelf .venv/bin/flask --app wsgi create-user
install -m 644 /opt/partshelf/current/deploy/partshelf-demo-reset.service /etc/systemd/system/partshelf-demo-reset.service
install -m 644 /opt/partshelf/current/deploy/partshelf-demo-reset.timer /etc/systemd/system/partshelf-demo-reset.timer
systemctl daemon-reload
systemctl enable --now partshelf nginx partshelf-demo-reset.timer
systemctl reload nginx
printf '\nReady. Open http://YOUR_LXC_IP on your LAN.\n'
