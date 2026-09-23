"""Workspace registry and physically separated inventory databases/uploads."""
import sqlite3
from pathlib import Path


def migrate_registry(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('CREATE TABLE IF NOT EXISTS workspaces(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        db.execute("INSERT OR IGNORE INTO workspaces(id,name) VALUES(1,'PCB Studios')")
        columns = {r[1] for r in db.execute('PRAGMA table_info(users)')}
        first_upgrade = 'workspace_id' not in columns
        for name, kind in {'workspace_id':'INTEGER NOT NULL DEFAULT 1', 'role':"TEXT NOT NULL DEFAULT 'member'", 'active':'INTEGER NOT NULL DEFAULT 1', 'platform_admin':'INTEGER NOT NULL DEFAULT 0'}.items():
            if name not in columns:
                db.execute(f'ALTER TABLE users ADD COLUMN {name} {kind}')
        if first_upgrade:
            db.execute("UPDATE users SET platform_admin=1,role='owner' WHERE id=(SELECT MIN(id) FROM users)")
        # SQLite cannot add a foreign key with a non-NULL default to a populated table.
        for event in ('INSERT', 'UPDATE OF workspace_id'):
            name = 'users_workspace_insert' if event == 'INSERT' else 'users_workspace_update'
            db.execute(f"CREATE TRIGGER IF NOT EXISTS {name} BEFORE {event} ON users WHEN NOT EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id) BEGIN SELECT RAISE(ABORT,'Invalid workspace'); END")
        db.execute('CREATE TABLE IF NOT EXISTS invitations(token_hash TEXT PRIMARY KEY,workspace_id INTEGER NOT NULL REFERENCES workspaces(id),email TEXT NOT NULL,role TEXT NOT NULL,expires INTEGER NOT NULL,created_by INTEGER NOT NULL REFERENCES users(id))')
        db.execute('CREATE TABLE IF NOT EXISTS management_audit(id INTEGER PRIMARY KEY,actor_id INTEGER,workspace_id INTEGER,action TEXT NOT NULL,detail TEXT NOT NULL,created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        db.execute('CREATE TABLE IF NOT EXISTS site_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        db.execute("INSERT OR IGNORE INTO site_settings VALUES('registration_enabled','1')")
        db.commit()
    except Exception:
        db.rollback()
        raise


def workspace_directory(app, workspace_id):
    workspace_id = int(workspace_id)
    if workspace_id < 1:
        raise ValueError('Invalid workspace.')
    root = Path(app.config['DATA_DIR'])
    return root if workspace_id == 1 else root / 'workspaces' / str(workspace_id)


def connect_inventory(app, workspace_id):
    path = app.config['DATABASE'] if int(workspace_id) == 1 else workspace_directory(app, workspace_id) / 'inventory.db'
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def initialize_inventory(app, workspace_id):
    from . import SCHEMA
    from .migrations import migrate
    root = workspace_directory(app, workspace_id)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    (root / 'uploads').mkdir(exist_ok=True, mode=0o700)
    db = connect_inventory(app, workspace_id)
    try:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript(SCHEMA)
        migrate(db)
    finally:
        db.close()
