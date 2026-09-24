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


def visitor_summary(db):
    import time
    from datetime import datetime, timezone, timedelta
    now=int(time.time())
    today=datetime.now(timezone.utc).date()
    live=db.execute('SELECT COUNT(*) AS website,COALESCE(SUM(demo_seen>=?),0) AS demo FROM visitor_activity WHERE seen>=?',(now-120,now-120)).fetchone()
    totals=db.execute('SELECT COALESCE(SUM(demo_visits),0) AS total,COALESCE(SUM(CASE WHEN day>=? THEN demo_visits ELSE 0 END),0) AS month FROM visitor_daily',((today-timedelta(days=29)).isoformat(),)).fetchone()
    day=db.execute('SELECT demo_visits FROM visitor_daily WHERE day=?',(today.isoformat(),)).fetchone()
    return dict(live_website=live['website'],live_demo=live['demo'],demo_total=totals['total'],demo_month=totals['month'],demo_today=day[0] if day else 0)


def install_visit_analytics(app, db):
    import secrets
    import time
    from datetime import datetime, timezone
    with app.app_context():
        db().executescript('''CREATE TABLE IF NOT EXISTS visitor_activity(
            visitor TEXT PRIMARY KEY,seen INTEGER NOT NULL,demo_seen INTEGER NOT NULL DEFAULT 0,
            demo_visit INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS visitor_seen ON visitor_activity(seen);
            CREATE TABLE IF NOT EXISTS visitor_daily(day TEXT PRIMARY KEY,demo_visits INTEGER NOT NULL DEFAULT 0);''')
        db().commit()

    def excluded():
        return request.headers.get('DNT')=='1' or request.headers.get('Sec-GPC')=='1' or bool(getattr(g,'user',None) and g.user['platform_admin'])

    @app.context_processor
    def visitor_context():
        enabled=not excluded() and request.method=='GET' and request.endpoint not in ('static','community.email_preferences')
        if enabled and 'visitor_id' not in session:
            session['visitor_id']=secrets.token_hex(24)
        return {'track_visits':enabled}

    @app.post('/visitor-pulse')
    def visitor_pulse():
        ident=session.get('visitor_id')
        if excluded() or not ident:
            return '',204
        now=int(time.time())
        demo=request.form.get('mode')=='demo'
        conn=db()
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute('SELECT * FROM visitor_activity WHERE visitor=?',(ident,)).fetchone()
        if row and now-row['seen']<20 and (not demo or now-row['demo_seen']<20):
            conn.rollback()
            return '',204
        last_visit=row['demo_visit'] if row else 0
        new_visit=demo and (not row or now-row['demo_seen']>=1800)
        if new_visit:
            last_visit=now
            day=datetime.fromtimestamp(now,timezone.utc).date().isoformat()
            conn.execute('INSERT INTO visitor_daily(day,demo_visits) VALUES(?,1) ON CONFLICT(day) DO UPDATE SET demo_visits=demo_visits+1',(day,))
        conn.execute('INSERT INTO visitor_activity(visitor,seen,demo_seen,demo_visit) VALUES(?,?,?,?) ON CONFLICT(visitor) DO UPDATE SET seen=excluded.seen,demo_seen=excluded.demo_seen,demo_visit=excluded.demo_visit',
                     (ident,now,now if demo else (row['demo_seen'] if row else 0),last_visit))
        conn.execute('DELETE FROM visitor_activity WHERE seen<?',(now-86400,))
        conn.commit()
        return '',204
