#!/usr/bin/env python3
"""Local server-owner recovery when a user has lost all second factors and recovery codes."""
import os
from pathlib import Path
import sqlite3


def main():
    if os.geteuid()!=0:
        raise SystemExit('Run as root inside the inventory LXC.')
    username=input('Account to recover: ').strip()
    if input('Disable its two-step verification and sign out every device? Type yes: ')!='yes':
        raise SystemExit('Cancelled.')
    with sqlite3.connect(Path(os.environ.get('INVENTORY_DATA','/var/lib/partshelf'))/'inventory.db') as db:
        user=db.execute('SELECT id FROM users WHERE username=?',(username,)).fetchone()
        if not user:
            raise SystemExit('Account not found.')
        db.execute("UPDATE users SET mfa_method='',totp_secret=NULL,totp_step=-1 WHERE id=?",user)
        for table in ('auth_sessions','auth_challenges','recovery_codes'):
            db.execute(f'DELETE FROM {table} WHERE user_id=?',user)
    print('Second factor reset and all sessions revoked. The account password is still required.')


if __name__=='__main__':
    main()
