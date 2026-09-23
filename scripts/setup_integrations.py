#!/usr/bin/env python3
"""Set the public HTTPS origin, install the alert timer, and optionally enter credentials privately."""
import argparse
import getpass
import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit


def update_env(path, values):
    existing=path.read_text().splitlines() if path.exists() else []
    lines=[line for line in existing if line.split('=',1)[0] not in values]
    for key,value in values.items():
        if any(c in value for c in '\r\n\x00'):
            raise ValueError('Configuration values must be single lines.')
        lines.append(key+'="'+value.replace('\\','\\\\').replace('"','\\"')+'"')
    temporary=path.with_suffix('.env.tmp')
    with temporary.open('w',opener=lambda name,flags:os.open(name,flags,0o600)) as output:
        output.write('\n'.join(lines)+'\n')
    temporary.chmod(0o600)
    temporary.replace(path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-url',default='https://inventory.pcb-studios.com')
    parser.add_argument('--credentials',action='store_true',help='Privately prompt for Google OAuth and Workspace SMTP credentials')
    args=parser.parse_args()
    if os.geteuid()!=0:
        parser.error('Run as root inside the LXC.')
    url=args.public_url.rstrip('/')
    parsed=urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
        parser.error('Use a public HTTPS origin, for example https://inventory.pcb-studios.com')
    values={'PUBLIC_URL':url,'COOKIE_SECURE':'1','MAIL_FROM':'no-reply@pcb-studios.com'}
    if args.credentials:
        print('Leave a field blank to keep its existing setting. Secrets are hidden and are never printed.')
        client=input('Google OAuth client ID: ').strip()
        if client:
            values['GOOGLE_CLIENT_ID']=client
        secret=getpass.getpass('Google OAuth client secret: ').strip()
        if secret:
            values['GOOGLE_CLIENT_SECRET']=secret
        username=input('Google Workspace primary mailbox that owns the no-reply alias: ').strip()
        if username:
            values.update(SMTP_HOST='smtp.gmail.com',SMTP_PORT='587',SMTP_USERNAME=username)
        password=getpass.getpass('Google Workspace app password (not your normal password): ').replace(' ','')
        if password:
            values['SMTP_PASSWORD']=password
    update_env(Path('/etc/partshelf.env'),values)
    root=Path(__file__).resolve().parents[1]
    for name in ('partshelf-alerts.service','partshelf-alerts.timer'):
        shutil.copyfile(root/'deploy'/name,Path('/etc/systemd/system')/name)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','enable','--now','partshelf-alerts.timer'],check=True)
    subprocess.run(['systemctl','restart','partshelf'],check=True)
    print('Public HTTPS origin and alert timer configured. Check Account & security for integration readiness.')


if __name__=='__main__':
    main()
