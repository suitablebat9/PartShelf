#!/usr/bin/env python3
"""Create a user or reset a password, without passing secrets on the command line."""
import getpass
import os
from pathlib import Path
import sqlite3
from werkzeug.security import generate_password_hash


def main():
    username = input('Username: ').strip()
    if not username:
        raise SystemExit('Username cannot be empty.')
    password = getpass.getpass('New password (at least 8 characters): ')
    if len(password) < 8 or password != getpass.getpass('Repeat password: '):
        raise SystemExit('Passwords must match and contain at least 8 characters.')
    data = Path(os.environ.get('INVENTORY_DATA', 'data')) / 'inventory.db'
    if not data.exists():
        raise SystemExit('Database not found. Initialize the app first and check INVENTORY_DATA.')
    with sqlite3.connect(data) as db:
        exists = db.execute('SELECT 1 FROM users WHERE username=?', (username,)).fetchone()
        if exists and input(f'Reset password for {username}? Type yes: ') != 'yes':
            raise SystemExit('Cancelled.')
        db.execute('INSERT INTO users(username,password) VALUES(?,?) ON CONFLICT(username) DO UPDATE SET password=excluded.password', (username, generate_password_hash(password)))
        user_id = db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()[0]
        for table in ('auth_sessions', 'auth_challenges'):
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                db.execute(f'DELETE FROM {table} WHERE user_id=?', (user_id,))
    print('Credentials saved. Existing signed-in sessions and pending sign-ins have been revoked.')


if __name__ == '__main__':
    main()
