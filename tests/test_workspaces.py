import io
import re
import sqlite3
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from werkzeug.security import generate_password_hash
from inventory import create_app, SCHEMA
from inventory.workspaces import initialize_inventory, connect_inventory, workspace_directory
from test_inventory import app, client, part, post


def authenticated(app, user_id, token):
    c = app.test_client()
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('INSERT INTO auth_sessions VALUES(?,?,?,?,?)', (app.extensions['partshelf_auth']['digest'](token), user_id, int(time.time())+3600, int(time.time()), 0))
    with c.session_transaction() as s:
        s.update(sid=token, csrf='test')
    return c


def tenant(app, name='Client A', role='owner'):
    with sqlite3.connect(app.config['DATABASE']) as db:
        workspace_id = db.execute('INSERT INTO workspaces(name) VALUES(?)', (name,)).lastrowid
        user_id = db.execute('INSERT INTO users(username,password,workspace_id,role) VALUES(?,?,?,?)', (name, generate_password_hash('password-123'), workspace_id, role)).lastrowid
    initialize_inventory(app, workspace_id)
    return workspace_id, user_id, authenticated(app, user_id, name)


def make_platform(app):
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE users SET role='owner',platform_admin=1 WHERE id=1")


def test_legacy_workspace_migration_keeps_inventory_and_promotes_only_first_user(tmp_path):
    path = tmp_path/'legacy.db'
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO users VALUES(1,'original','hash')")
        db.execute("INSERT INTO users VALUES(2,'staff','hash')")
        db.execute("INSERT INTO components(name,name_id,code,stock) VALUES('private','id','code',12)")
    config = dict(TESTING=True, DATA_DIR=tmp_path, DATABASE=str(path))
    create_app(config)
    create_app(config)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT workspace_id,role,platform_admin FROM users ORDER BY id').fetchall() == [(1,'owner',1),(1,'member',0)]
        assert db.execute('SELECT name,stock FROM components').fetchone() == ('private',12)


def test_inventory_isolated_across_read_write_search_labels_uploads(client, app):
    part(client, name='Private original', category='Secret category', supplier='Hidden supplier', tags='private-tag', size='secret-size')
    post(client, '/projects', name='Secret project')
    post(client, '/storage', name='Secret cabinet', kind='Cabinet')
    root = Path(app.config['DATA_DIR'])/'uploads'
    (root/'private.pdf').write_bytes(b'%PDF-private')
    wid, uid, c = tenant(app)
    for path in ('/', '/search?q=Private', '/labels', '/components/new', '/storage', '/projects'):
        page = c.get(path)
        assert page.status_code == 200
        for private in (b'Private original', b'Secret category', b'Hidden supplier', b'private-tag', b'secret-size', b'Secret project', b'Secret cabinet'):
            assert private not in page.data
    for path in ('/components/1', '/components/1/edit', '/codes/1/qr', '/projects/1', '/uploads/private.pdf'):
        assert c.get(path).status_code == 404
    assert post(c, '/components/1/stock', quantity='3').status_code == 404
    assert post(c, '/projects/1/consume').status_code == 404
    assert c.get('/labels/pdf?item_id=1').status_code == 400
    assert post(c, '/labels/pdf', component_ids=['1']).status_code == 400
    # Local IDs may repeat; all routes must resolve them only in the current workspace.
    assert part(c, name='Client-specific', name_id='Private original').status_code == 302
    assert b'Client-specific' in c.get('/components/1').data
    assert b'Private original' in client.get('/components/1').data
    post(c, '/components/1/stock', quantity='7', direction='add')
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT stock FROM components WHERE id=1').fetchone()[0] == 20
    ownroot = workspace_directory(app, wid)/'uploads'
    (ownroot/'private.pdf').write_bytes(b'%PDF-client')
    assert c.get('/uploads/private.pdf').data == b'%PDF-client'
    assert client.get('/uploads/private.pdf').data == b'%PDF-private'
    assert c.get('/uploads/..%2Fsecret.key').status_code == 404


def test_viewer_read_only_all_inventory_mutations(app):
    wid, uid, c = tenant(app, role='member')
    part(c)
    post(c, '/projects', name='Test')
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE users SET role='viewer' WHERE id=?", (uid,))
    for path in ('/components/new', '/components/1/edit'):
        assert c.get(path).status_code == 403
    for path in ('/components/new', '/components/1/edit', '/components/1/stock', '/storage', '/projects', '/projects/1', '/projects/1/consume'):
        assert post(c, path).status_code == 403
    assert c.get('/components/1').status_code == 200
    assert c.get('/labels/pdf?item_id=1').status_code == 200
    assert c.get('/management').status_code == 403


def test_platform_and_workspace_authorization(client, app):
    wid, uid, c = tenant(app)
    assert c.get('/management/workspaces/1').status_code == 403
    assert post(c, '/management/workspaces').status_code == 403
    assert post(c, '/management/registration', enabled='1').status_code == 403
    assert post(c, '/management/workspaces/1/settings', name='hijack').status_code == 403
    assert post(c, '/management/workspaces/1/invite', email='a@example.com', role='owner').status_code == 403
    assert post(c, f'/management/workspaces/{wid}/members/1', role='owner', active='1').status_code == 404
    assert post(c, f'/management/workspaces/{wid}/members/{uid}', role='viewer').status_code == 400
    assert c.get(f'/management/workspaces/{wid}').status_code == 200
    make_platform(app)
    assert client.get('/management').status_code == 200
    assert b'Client A' in client.get('/management').data
    assert client.get(f'/management/workspaces/{wid}').status_code == 200
    assert post(client, f'/management/workspaces/{wid}/status', active='0').status_code == 302
    assert c.get('/').status_code == 302
    # Password login cannot bypass workspace suspension.
    c.get('/login')
    with c.session_transaction() as s:
        csrf = s['csrf']
    assert c.post('/login', data=dict(csrf=csrf, username='Client A', password='password-123')).status_code == 401
    assert post(client, '/management/workspaces/1/status', active='0').status_code == 400
    assert post(client, f'/management/workspaces/{wid}/status', active='1').status_code == 302
    assert c.get('/').status_code == 302  # old sessions stay revoked


def signup_form(c, **fields):
    c.get('/register')
    with c.session_transaction() as s:
        token = s['csrf']
    return c.post('/register', data=dict(csrf=token, workspace_name='New customer', email='new@example.com', username='new-client', password='password-123', password_confirm='password-123', **fields))


def test_public_signup_requires_verified_email_and_creates_isolated_owner(app):
    app.config.update(PUBLIC_URL='https://inventory.example.com', SMTP_HOST='smtp.test', SMTP_USERNAME='sender', SMTP_PASSWORD='test')
    c = app.test_client()
    with patch('inventory.management.send_email') as send:
        response = signup_form(c)
    assert response.location.endswith('/register/verify')
    code = re.search(r'\b\d{6}\b', send.call_args.args[2])[0]
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 1
    with c.session_transaction() as s:
        token = s['csrf']
    assert c.post('/register/verify', data=dict(csrf=token, code='bad')).status_code == 400
    assert c.post('/register/verify', data=dict(csrf=token, code=code)).status_code == 302
    assert c.post('/register/verify', data=dict(csrf=token, code=code)).status_code == 400
    with sqlite3.connect(app.config['DATABASE']) as db:
        user = db.execute("SELECT id,workspace_id,role,email_verified,platform_admin FROM users WHERE username='new-client'").fetchone()
        assert user[1:] == (2, 'owner', 1, 0)
    c = authenticated(app, user[0], 'new-signup')
    assert c.get('/').status_code == 200
    with connect_inventory(app, 2) as inventory:
        assert inventory.execute('SELECT COUNT(*) FROM components').fetchone()[0] == 0
    assert c.get('/management/workspaces/2').status_code == 200
    assert c.get('/management/workspaces/1').status_code == 403


def test_signup_closed_or_mail_unconfigured_creates_nothing(app, client):
    c = app.test_client()
    assert signup_form(c).status_code == 400
    make_platform(app)
    assert post(client, '/management/registration').status_code == 302
    app.config.update(PUBLIC_URL='https://inventory.example.com', SMTP_HOST='smtp.test', SMTP_USERNAME='sender', SMTP_PASSWORD='test')
    assert signup_form(c).status_code == 400
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT COUNT(*) FROM workspaces').fetchone()[0] == 1


def test_invites_single_use_scoped_and_roles(app):
    app.config['PUBLIC_URL'] = 'https://inventory.example.com'
    wid, uid, owner = tenant(app)
    result = post(owner, f'/management/workspaces/{wid}/invite', email='staff@example.com', role='member')
    assert result.status_code == 200
    token = re.search(rb'/invite/([A-Za-z0-9_-]+)', result.data)[1].decode()
    c = app.test_client()
    assert c.get('/invite/'+token).status_code == 200
    with c.session_transaction() as s:
        csrf = s['csrf']
    assert c.post('/invite/'+token, data=dict(csrf=csrf, username='new-staff', password='password-123', password_confirm='password-123', workspace_id='1', role='owner')).status_code == 302
    assert c.get('/invite/'+token).status_code == 404
    with sqlite3.connect(app.config['DATABASE']) as db:
        user = db.execute("SELECT id,workspace_id,role,email_verified FROM users WHERE username='new-staff'").fetchone()
        assert user[1:] == (wid, 'member', 0)
    staff = authenticated(app, user[0], 'staff-session')
    assert staff.get('/management').status_code == 403
    assert post(owner, f'/management/workspaces/{wid}/members/{user[0]}', role='viewer', active='1').status_code == 302
    assert staff.get('/').status_code == 302
    assert post(owner, f'/management/workspaces/{wid}/members/{user[0]}', role='admin', active='1').status_code == 302
    staff = authenticated(app, user[0], 'staff-admin')
    assert post(staff, f'/management/workspaces/{wid}/invite', email='bad@example.com', role='owner').status_code == 403
    assert post(staff, f'/management/workspaces/{wid}/members/{uid}', role='viewer', active='1').status_code == 403


def test_password_reset_revokes_sessions_preserves_mfa(app, client):
    app.config.update(SMTP_HOST='smtp.test', SMTP_USERNAME='sender', SMTP_PASSWORD='test')
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE users SET email='owner@example.com',email_verified=1,mfa_method='totp' WHERE id=1")
    c = app.test_client()
    c.get('/forgot-password')
    with c.session_transaction() as s:
        csrf = s['csrf']
    with patch('inventory.management.send_email') as send:
        assert c.post('/forgot-password', data=dict(csrf=csrf,email='owner@example.com')).status_code == 302
    code = re.search(r'\b\d{6}\b', send.call_args.args[2])[0]
    assert c.post('/reset-password', data=dict(csrf=csrf,code=code,password='new-password',password_confirm='new-password')).status_code == 302
    assert client.get('/').status_code == 302
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT mfa_method FROM users WHERE id=1').fetchone()[0] == 'totp'


def test_stock_alerts_do_not_cross_workspaces(app, client):
    app.config.update(PUBLIC_URL='https://inventory.example.com', SMTP_HOST='smtp.test', SMTP_USERNAME='sender', SMTP_PASSWORD='test')
    part(client, name='Private original', stock='1', low_stock='5')
    wid, uid, c = tenant(app)
    part(c, name='Private client', stock='1', low_stock='5')
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE users SET email='original@example.com',email_verified=1,low_stock_email=1 WHERE id=1")
        db.execute("UPDATE users SET email='client@example.com',email_verified=1,low_stock_email=1 WHERE id=?", (uid,))
    with patch('inventory.mailer.send_email') as send:
        result = app.test_cli_runner().invoke(args=['send-stock-alerts'])
        assert result.exit_code == 0, result.output
        assert send.call_count == 2
        content = {call.args[0]: call.args[2] for call in send.call_args_list}
        assert 'Private original' in content['original@example.com']
        assert 'Private client' not in content['original@example.com']
        assert 'Private client' in content['client@example.com']
        assert 'Private original' not in content['client@example.com']
    with patch('inventory.mailer.send_email') as send:
        assert app.test_cli_runner().invoke(args=['send-stock-alerts']).exit_code == 0
        assert send.call_count == 0


def test_management_requires_csrf_and_recent_auth(app, client):
    make_platform(app)
    assert client.post('/management/workspaces', data={'name':'Bad'}).status_code == 400
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('UPDATE auth_sessions SET authenticated=0')
    assert post(client, '/management/workspaces', name='Bad').location.endswith('/account/reauthenticate')
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT COUNT(*) FROM workspaces').fetchone()[0] == 1


def test_export_contains_only_own_inventory_and_files(app, client):
    import json
    import zipfile
    part(client, name='Secret original')
    wid, uid, owner = tenant(app)
    part(owner, name='Exportable client')
    (workspace_directory(app, wid)/'uploads'/'part.pdf').write_bytes(b'%PDF-client')
    response = owner.get('/workspace/export')
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert sorted(archive.namelist()) == ['inventory.json', 'uploads/part.pdf']
        payload = json.loads(archive.read('inventory.json'))
        assert payload['tables']['components'][0]['name'] == 'Exportable client'
        assert 'users' not in payload['tables']
        assert b'Secret original' not in archive.read('inventory.json')
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE users SET role='viewer' WHERE id=?", (uid,))
    assert owner.get('/workspace/export').status_code == 403


def test_new_workspace_migration_and_alert_state_survive_restart(app):
    wid, uid, owner = tenant(app)
    part(owner, name='Persisted')
    with connect_inventory(app, wid) as db:
        db.execute('INSERT INTO stock_alerts(user_id,component_id,sent) VALUES(?,?,1)', (uid,1))
    create_app(dict(TESTING=True, DATA_DIR=app.config['DATA_DIR'], DATABASE=app.config['DATABASE']))
    with connect_inventory(app, wid) as db:
        assert db.execute('SELECT name FROM components').fetchone()[0] == 'Persisted'
        assert db.execute('SELECT sent FROM stock_alerts').fetchone()[0] == 1
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_invitation_expiry_and_revocation(app):
    app.config['PUBLIC_URL'] = 'https://inventory.example.com'
    wid, uid, owner = tenant(app)
    response = post(owner, f'/management/workspaces/{wid}/invite', email='one@example.com', role='viewer')
    token = re.search(rb'/invite/([A-Za-z0-9_-]+)', response.data)[1].decode()
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('UPDATE invitations SET expires=0')
    assert app.test_client().get('/invite/'+token).status_code == 404
    response = post(owner, f'/management/workspaces/{wid}/invite', email='two@example.com', role='viewer')
    token = re.search(rb'/invite/([A-Za-z0-9_-]+)', response.data)[1].decode()
    digest = app.extensions['partshelf_auth']['digest'](token)
    assert post(owner, f'/management/workspaces/{wid}/invites/revoke', token_hash=digest).status_code == 302
    assert app.test_client().get('/invite/'+token).status_code == 404


def test_signup_verification_cannot_be_used_in_another_browser(app):
    app.config.update(PUBLIC_URL='https://inventory.example.com', SMTP_HOST='smtp.test', SMTP_USERNAME='sender', SMTP_PASSWORD='test')
    c = app.test_client()
    with patch('inventory.management.send_email') as send:
        signup_form(c)
    code = re.search(r'\b\d{6}\b', send.call_args.args[2])[0]
    other = app.test_client()
    other.get('/register')
    with other.session_transaction() as s:
        csrf = s['csrf']
    assert other.post('/register/verify', data=dict(csrf=csrf,code=code)).status_code == 400
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT COUNT(*) FROM workspaces').fetchone()[0] == 1
