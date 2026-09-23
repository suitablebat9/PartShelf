"""Additive account, challenge, and notification tables."""

def migrate_security(db):
    columns = {r[1] for r in db.execute('PRAGMA table_info(users)')}
    for name, kind in {
        'email': 'TEXT', 'email_verified': 'INTEGER NOT NULL DEFAULT 0',
        'google_sub': 'TEXT', 'totp_secret': 'TEXT', 'totp_step': 'INTEGER NOT NULL DEFAULT -1',
        'mfa_method': "TEXT NOT NULL DEFAULT ''", 'low_stock_email': 'INTEGER NOT NULL DEFAULT 0',
    }.items():
        if name not in columns:
            db.execute(f'ALTER TABLE users ADD COLUMN {name} {kind}')
    if 'low_stock' not in {r[1] for r in db.execute('PRAGMA table_info(components)')}:
        db.execute('ALTER TABLE components ADD COLUMN low_stock TEXT')
    for sql in (
        'CREATE UNIQUE INDEX IF NOT EXISTS users_google_sub ON users(google_sub) WHERE google_sub IS NOT NULL',
        'CREATE UNIQUE INDEX IF NOT EXISTS users_email ON users(email COLLATE NOCASE) WHERE email IS NOT NULL',
        'CREATE TABLE IF NOT EXISTS auth_sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,expires INTEGER NOT NULL,authenticated INTEGER NOT NULL,remember INTEGER NOT NULL DEFAULT 0)',
        'CREATE TABLE IF NOT EXISTS auth_challenges(id TEXT PRIMARY KEY,owner TEXT NOT NULL,purpose TEXT NOT NULL,user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,payload TEXT NOT NULL,code_hash TEXT,expires INTEGER NOT NULL,attempts INTEGER NOT NULL DEFAULT 0)',
        'CREATE TABLE IF NOT EXISTS auth_limits(key TEXT PRIMARY KEY,started INTEGER NOT NULL,count INTEGER NOT NULL)',
        'CREATE TABLE IF NOT EXISTS passkeys(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,public_key BLOB NOT NULL,sign_count INTEGER NOT NULL,name TEXT NOT NULL,created INTEGER NOT NULL)',
        'CREATE TABLE IF NOT EXISTS recovery_codes(user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,code_hash TEXT NOT NULL,PRIMARY KEY(user_id,code_hash))',
        'CREATE TABLE IF NOT EXISTS stock_alerts(user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,component_id INTEGER NOT NULL REFERENCES components(id),sent INTEGER NOT NULL DEFAULT 0,last_attempt INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(user_id,component_id))',
    ):
        db.execute(sql)
    # Recipients live in the central account registry; inventory databases are isolated.
    if any(r[2] == 'users' for r in db.execute('PRAGMA foreign_key_list(stock_alerts)')):
        db.execute('ALTER TABLE stock_alerts RENAME TO stock_alerts_legacy')
        db.execute('CREATE TABLE stock_alerts(user_id INTEGER NOT NULL,component_id INTEGER NOT NULL REFERENCES components(id),sent INTEGER NOT NULL DEFAULT 0,last_attempt INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(user_id,component_id))')
        db.execute('INSERT INTO stock_alerts SELECT * FROM stock_alerts_legacy')
        db.execute('DROP TABLE stock_alerts_legacy')
