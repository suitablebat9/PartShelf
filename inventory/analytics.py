"""First-touch signup attribution and private platform reporting; no raw IP storage."""
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit
from flask import g, request, session
from .workspaces import workspace_directory


def migrate_analytics(db):
    columns={r[1] for r in db.execute('PRAGMA table_info(users)')}
    for field in ('created','last_login','signup_method','signup_source','signup_medium','signup_campaign','signup_country'):
        if field not in columns:
            db.execute('ALTER TABLE users ADD COLUMN '+field+' TEXT')
    db.execute("CREATE TRIGGER IF NOT EXISTS users_created AFTER INSERT ON users WHEN NEW.created IS NULL BEGIN UPDATE users SET created=CURRENT_TIMESTAMP WHERE id=NEW.id; END")


def install_attribution(app):
    def clean(value):
        return re.sub(r'[^\w .:/+-]','',value or '')[:100]

    @app.before_request
    def capture_source():
        if request.method!='GET' or request.path not in ('/','/welcome','/about','/support','/feedback','/login','/register','/demo') or session.get('signup_attribution'):
            return
        try:
            host=urlsplit(request.referrer or '').hostname or ''
        except ValueError:
            host=''
        source=clean(request.args.get('utm_source')) or (host[:100] if host and host!=request.host.split(':')[0] else 'Direct / unknown')
        country=request.headers.get('CF-IPCountry','').upper() if app.config.get('TRUST_CLOUDFLARE_COUNTRY') else ''
        session['signup_attribution']={'source':source,'medium':clean(request.args.get('utm_medium')),'campaign':clean(request.args.get('utm_campaign')),'country':country if re.fullmatch('[A-Z]{2}',country) and country not in ('XX','T1') else None}


def record_signup(db, user_id, method):
    attribution=session.get('signup_attribution',{})
    db.execute('UPDATE users SET signup_method=?,signup_source=?,signup_medium=?,signup_campaign=?,signup_country=? WHERE id=?',
               (method,attribution.get('source','Direct / unknown'),attribution.get('medium'),attribution.get('campaign'),attribution.get('country'),user_id))


def inventory_totals(app, workspace_id):
    path=Path(app.config['DATABASE']) if workspace_id==1 else workspace_directory(app,workspace_id)/'inventory.db'
    if not path.is_file():
        return {'components':None,'projects':None}
    try:
        db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
        try:
            return {'components':db.execute('SELECT COUNT(*) FROM components').fetchone()[0], 'projects':db.execute('SELECT COUNT(*) FROM projects').fetchone()[0]}
        finally:
            db.close()
    except sqlite3.Error:
        return {'components':None,'projects':None}
